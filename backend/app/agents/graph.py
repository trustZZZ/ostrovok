"""Агентный граф сбора характеристик.

Поток:
    plan → collect → conflicts → [ask → wait → parse] → finalize

Ключевое отличие от «жёсткого пайплайна»: набор характеристик и инструментов
берётся из реестра (app/features.yaml). Узел ``plan`` сам решает, какими
инструментами добывать каждую характеристику, и фиксирует обоснование
в ``tool_selection`` — это видно в API и в UI.

Вопрос отельеру задаётся тогда и только тогда, когда инструменты не дали
уверенности выше порога из реестра или источники противоречат друг другу.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Optional, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt
from sqlalchemy import delete, select

from app.collectors import HotelContext, get_tool, run_tool
from app.db import async_session
from app.feature_registry import get_feature, select_features
from app.llm_utils import parse_answer_with_llm
from app.seed import upsert_feature

logger = logging.getLogger(__name__)


class AgentState(TypedDict, total=False):
    hotel_id: int
    thread_id: str
    plan: list[dict[str, Any]]
    tool_selection: list[dict[str, Any]]
    features: dict[str, dict[str, Any]]
    pending: list[str]
    questions: list[dict[str, Any]]
    conflicts: list[dict[str, Any]]
    log: list[str]
    answers: Optional[dict[str, Any]]
    saved: int


async def get_hotel(hotel_id: int) -> HotelContext:
    """Отель из БД. Никаких заглушек: нет отеля — нет сбора."""
    from geoalchemy2.shape import to_shape

    from app.models import Hotel

    async with async_session() as db:
        hotel = await db.get(Hotel, hotel_id)
        if hotel is None:
            raise ValueError(f"отель {hotel_id} не найден")
        geometry = to_shape(hotel.geom)
        return HotelContext(
            id=hotel.id,
            name=hotel.name,
            lat=geometry.y,
            lon=geometry.x,
            floors=hotel.floors or 3,
            facade_azimuth=hotel.facade_azimuth,
        )


def _value_key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


async def _should_persist(db, hotel_id: int, key: str, payload: dict) -> bool:
    """Решает, писать ли результат в БД.

    Осознанное «нет данных» (пляжа нет в радиусе) писать нужно — это факт
    об отеле. Технический сбой сети писать нельзя: иначе один таймаут
    затирает уже собранное значение, и отель теряет характеристику,
    которую мы до этого успешно посчитали.
    """
    from app.models import HotelFeature

    value = payload.get("value")
    evidence = payload.get("evidence") or {}
    no_data = isinstance(value, dict) and value.get("status") == "no_data"
    if not no_data or not evidence.get("error"):
        return True

    row = (
        await db.execute(
            select(HotelFeature).where(
                HotelFeature.hotel_id == hotel_id,
                HotelFeature.feature_key == key,
                HotelFeature.source == payload.get("source"),
            )
        )
    ).scalars().first()
    if row is None:
        return True
    # Прошлое значение сохраняем, только пока оно не просрочено:
    # просроченное всё равно надо заменить, даже если сейчас сбой.
    return bool(row.expires_at and row.expires_at < datetime.utcnow())


async def node_plan(state: AgentState) -> dict:
    """Решает, какие характеристики собирать и какими инструментами."""
    plan: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []

    # Планируем характеристики всех уровней: и отельные, и номерные. У номерных
    # инструментов нет по определению — какие категории выходят на запад или
    # во двор, знает только отельер, поэтому они честно уходят в вопрос.
    for spec in select_features():
        available = [name for name in spec.tools if get_tool(name) is not None]
        missing = [name for name in spec.tools if name not in available]

        if not spec.tools:
            # Значение поставляется тремя путями: инструмент, ответ отельера и
            # внешний источник (ingest партнёрских данных). Пустой `tools` сам
            # по себе не значит «спросим отельера»: у блогерской эмоции вопрос
            # не задаётся вовсе, и причина должна это отражать.
            reason = (
                "инструментов нет — характеристика только из ответа отельера"
                if spec.question
                else "инструментов нет — значение приходит из внешнего источника (ingest)"
            )
        elif missing:
            reason = f"нет инструментов: {', '.join(missing)}"
        else:
            reason = f"выбраны инструменты: {', '.join(available)}"

        audit.append(
            {
                "feature": spec.key,
                "target": spec.target,
                "selected_tools": available,
                "reason": reason,
            }
        )
        plan.append(
            {
                "key": spec.key,
                "target": spec.target,
                "tools": available,
                "question": spec.question,
                "ttl_days": spec.ttl_days,
                "min_confidence": spec.min_confidence,
                "title": spec.title,
            }
        )

    tool_count = sum(len(item["tools"]) for item in plan)
    return {
        "plan": plan,
        "tool_selection": audit,
        "log": list(state.get("log") or [])
        + [f"План: {len(plan)} характеристик, задействовано инструментов: {tool_count}"],
    }


async def node_collect(state: AgentState) -> dict:
    """Запускает выбранные инструменты и складывает значения с провенансом."""
    context = await get_hotel(state["hotel_id"])
    features = dict(state.get("features") or {})
    log = list(state.get("log") or [])

    for task in state.get("plan") or []:
        key = task["key"]
        if not task["tools"]:
            # Тот же третий путь, что и в плане: без вопроса отельер здесь не
            # при чём — значение приносит внешний ingest.
            log.append(
                f"{key}: инструментов нет, спросим отельера"
                if task.get("question")
                else f"{key}: инструментов нет — значение приходит из внешнего источника"
            )
            continue

        best_confidence = -1.0
        for tool_name in task["tools"]:
            result = await run_tool(tool_name, context)
            payload = {
                "value": result.value if result.value is not None else {"status": "no_data"},
                "source": result.source,
                "confidence": result.confidence,
                "evidence": {**(result.evidence or {}), "tool": tool_name},
            }
            if result.confidence >= best_confidence:
                features[key] = payload
                best_confidence = result.confidence
            log.append(
                f"{key}: {result.source}, уверенность {result.confidence:.0%}"
                + ("" if result.value is not None else " (данных нет)")
            )
            if result.confidence >= task["min_confidence"]:
                break

        if best_confidence < task["min_confidence"]:
            log.append(f"{key}: ниже порога {task['min_confidence']:.0%} — нужен отельер")

    return {"features": features, "log": log}


async def node_save_confident(state: AgentState) -> dict:
    """Сохраняет результаты инструментов до вопроса отельеру.

    Пишем и неуверенные результаты тоже: значение «нет данных» — это знание,
    и оно должно затирать устаревшее число от того же источника. Иначе
    после повторного сбора в БД остаётся старая (возможно неверная) оценка.
    Вопрос отельеру при этом всё равно задаётся — по min_confidence.
    """
    plan_by_key = {task["key"]: task for task in state.get("plan") or []}
    saved = 0

    async with async_session() as db:
        for key, payload in (state.get("features") or {}).items():
            task = plan_by_key.get(key, {})
            if payload.get("source") is None:
                continue
            if not await _should_persist(db, state["hotel_id"], key, payload):
                logger.info(
                    "отель %s, «%s»: технический сбой, оставляю прошлое значение",
                    state["hotel_id"],
                    key,
                )
                continue
            await upsert_feature(
                db,
                hotel_id=state["hotel_id"],
                feature_key=key,
                value=payload["value"],
                source=payload["source"],
                confidence=float(payload["confidence"]),
                evidence=payload.get("evidence"),
                ttl_days=int(task.get("ttl_days", 180)),
            )
            saved += 1
        await db.commit()

    return {"log": list(state.get("log") or []) + [f"Сохранено до вопроса отельеру: {saved}"]}


async def node_conflicts(state: AgentState) -> dict:
    """Ищет противоречия между источниками и решает, кого спросить."""
    from app.models import HotelFeature

    async with async_session() as db:
        rows = (
            await db.execute(
                select(HotelFeature).where(HotelFeature.hotel_id == state["hotel_id"])
            )
        ).scalars().all()

    stored: dict[str, list[Any]] = {}
    for row in rows:
        if (row.confidence or 0) > 0:
            stored.setdefault(row.feature_key, []).append(row)

    collected = state.get("features") or {}
    conflicts: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []

    for task in state.get("plan") or []:
        key = task["key"]
        current = collected.get(key)

        variants = {_value_key(row.value) for row in stored.get(key, [])}
        if current and current["value"] is not None:
            variants.add(_value_key(current["value"]))

        if len(variants) > 1:
            conflicts.append(
                {
                    "feature": key,
                    "type": "sources_disagree",
                    "variants": sorted(variants),
                    "message": f"Источники расходятся по «{task['title']}»",
                }
            )

        # Факт «в БД уже есть пригодный ответ» — тоже основание не спрашивать.
        # Раньше confident учитывал только результат инструмента в текущем
        # прогоне, поэтому характеристики без инструментов (питомцы, сторона
        # номеров, балкон) запрашивались при каждом сборе, и в кабинете
        # копились десятки одинаковых вопросов и ответов на них.
        now = datetime.utcnow()
        fresh = [
            row
            for row in stored.get(key, [])
            if (row.confidence or 0) >= task["min_confidence"]
            # Просроченное значение основанием не является: устаревшие данные
            # должны перепроверяться, иначе актуализация перестанет работать.
            and (row.expires_at is None or row.expires_at > now)
        ]
        confident = (
            bool(current) and current["confidence"] >= task["min_confidence"]
        ) or bool(fresh)
        if (not confident or len(variants) > 1) and task["question"]:
            pending.append(task)

    questions = [
        {
            "id": task["key"],
            "feature_key": task["key"],
            "question": task["question"],
            "generated_by": "registry",
        }
        for task in pending
    ]

    log = list(state.get("log") or [])
    log.append(f"Противоречий: {len(conflicts)}; вопросов отельеру: {len(questions)}")

    return {"conflicts": conflicts, "pending": [t["key"] for t in pending], "questions": questions, "log": log}


async def node_ask(state: AgentState) -> dict:
    """Сохраняет вопросы в БД, чтобы отельер увидел их в кабинете."""
    from app.models import HotelierQuestion

    questions = state.get("questions") or []
    thread_id = state.get("thread_id")

    async with async_session() as db:
        await db.execute(
            delete(HotelierQuestion).where(
                HotelierQuestion.hotel_id == state["hotel_id"],
                HotelierQuestion.status == "pending",
            )
        )
        for question in questions:
            db.add(
                HotelierQuestion(
                    hotel_id=state["hotel_id"],
                    feature_key=question["feature_key"],
                    question=question["question"],
                    status="pending",
                    thread_id=thread_id,
                )
            )
        await db.commit()

    return {"log": list(state.get("log") or []) + [f"Вопросов отправлено отельеру: {len(questions)}"]}


async def node_wait(state: AgentState) -> dict:
    """Останавливает граф до ответа отельера (interrupt + resume по thread_id)."""
    if state.get("answers"):
        return {"log": list(state.get("log") or []) + ["Ответы уже получены, ожидание пропущено"]}

    answer = interrupt(
        {
            "type": "hotelier_questions",
            "questions": state.get("questions") or [],
            "hotel_id": state["hotel_id"],
        }
    )
    return {"answers": answer}


async def node_parse(state: AgentState) -> dict:
    """Разбирает свободный ответ отельера в структурированное значение."""
    answers = state.get("answers") or {}
    features = dict(state.get("features") or {})
    log = list(state.get("log") or [])

    for question in state.get("questions") or []:
        raw = answers.get(question["id"]) or answers.get(question["feature_key"], "")
        if not raw:
            continue
        try:
            parsed = await parse_answer_with_llm(
                question=question["question"],
                raw_answer=str(raw),
                feature_key=question["feature_key"],
            )
        except Exception as exc:  # noqa: BLE001 - LLM внешний
            logger.warning("не удалось разобрать ответ отельера: %s", exc)
            parsed = {"value": str(raw), "confidence": 0.4}

        spec = get_feature(question["feature_key"])
        value = parsed.get("value", raw)
        if spec is not None:
            # Ответ — свободный текст, а реестр сравнивает boolean или число:
            # без приведения «Люкс и Апартаменты» попадёт в поиск как строка.
            value = spec.coerce(value, str(raw))

        features[question["feature_key"]] = {
            "value": value,
            "source": "hotelier",
            "confidence": float(parsed.get("confidence", 0.5)),
            "evidence": {"raw_answer": str(raw)},
        }
        log.append(f"{question['feature_key']}: ответ отельера разобран")

    return {"features": features, "log": log}


async def node_finalize(state: AgentState) -> dict:
    """Записывает все характеристики в БД с источником, уверенностью и TTL."""
    plan_by_key = {task["key"]: task for task in state.get("plan") or []}
    saved = 0

    async with async_session() as db:
        for key, payload in (state.get("features") or {}).items():
            task = plan_by_key.get(key, {})
            if not await _should_persist(db, state["hotel_id"], key, payload):
                logger.info(
                    "отель %s, «%s»: технический сбой, оставляю прошлое значение",
                    state["hotel_id"],
                    key,
                )
                continue
            await upsert_feature(
                db,
                hotel_id=state["hotel_id"],
                feature_key=key,
                value=payload["value"],
                source=payload["source"],
                confidence=float(payload["confidence"]),
                evidence=payload.get("evidence"),
                ttl_days=int(task.get("ttl_days", 180)),
            )
            saved += 1
        await db.commit()

    return {"saved": saved, "log": list(state.get("log") or []) + [f"Сохранено характеристик: {saved}"]}


def build_graph(checkpointer=None):
    graph = StateGraph(AgentState)

    graph.add_node("plan", node_plan)
    graph.add_node("collect", node_collect)
    graph.add_node("save", node_save_confident)
    graph.add_node("conflicts", node_conflicts)
    graph.add_node("ask", node_ask)
    graph.add_node("wait", node_wait)
    graph.add_node("parse", node_parse)
    graph.add_node("finalize", node_finalize)

    graph.set_entry_point("plan")
    graph.add_edge("plan", "collect")
    graph.add_edge("collect", "save")
    graph.add_edge("save", "conflicts")
    graph.add_conditional_edges(
        "conflicts",
        lambda state: "ask" if state.get("questions") else "finalize",
        {"ask": "ask", "finalize": "finalize"},
    )
    graph.add_edge("ask", "wait")
    graph.add_edge("wait", "parse")
    graph.add_edge("parse", "finalize")
    graph.add_edge("finalize", END)

    return graph.compile(checkpointer=checkpointer or MemorySaver())


agent_graph = build_graph()

# Держим контекст соединения открытым: если выйти из него, сохранение
# состояния молча перестанет работать.
_checkpointer_cm = None


def psycopg_dsn(database_url: str) -> str:
    """DSN для psycopg: драйвер asyncpg в строке подключения ему незнаком."""
    for prefix in ("postgresql+asyncpg://", "postgresql+psycopg://", "postgres+asyncpg://"):
        if database_url.startswith(prefix):
            return "postgresql://" + database_url[len(prefix):]
    return database_url


async def enable_postgres_checkpointer(database_url: str) -> bool:
    """Persistent-checkpointer: состояние прогонов переживает рестарт процесса.

    С ``MemorySaver`` незавершённый прогон (отель, ожидающий ответа, или
    прерванный рестартом сбор) после перезапуска контейнера исчезает: поток
    не найти по ``thread_id``. Здесь состояние пишется в ту же Postgres, что и
    данные, поэтому прогон можно продолжить.

    Любая проблема (нет пакета, нет прав, старый сервер) не ломает запуск:
    возвращается False, граф остаётся на MemorySaver.
    """
    global agent_graph, _checkpointer_cm

    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    except Exception as exc:  # noqa: BLE001 - пакет необязательный
        logger.warning("Postgres-checkpointer недоступен (%s) — остаётся MemorySaver", exc)
        return False

    cm = AsyncPostgresSaver.from_conn_string(psycopg_dsn(database_url))
    try:
        saver = await cm.__aenter__()
        await saver.setup()
    except Exception as exc:  # noqa: BLE001 - БД может быть недоступна
        logger.warning("Postgres-checkpointer не подключён (%s) — остаётся MemorySaver", exc)
        try:
            await cm.__aexit__(None, None, None)
        except Exception:  # noqa: BLE001 - закрытие уже сломанного соединения
            pass
        return False

    _checkpointer_cm = cm
    agent_graph = build_graph(saver)
    logger.info("Checkpointer: Postgres (состояние прогонов переживает рестарт)")
    return True


async def close_postgres_checkpointer() -> None:
    """Закрывает соединение checkpointer при остановке приложения."""
    global _checkpointer_cm

    if _checkpointer_cm is None:
        return
    cm, _checkpointer_cm = _checkpointer_cm, None
    try:
        await cm.__aexit__(None, None, None)
    except Exception as exc:  # noqa: BLE001 - остановка не должна падать
        logger.warning("Не удалось закрыть checkpointer: %s", exc)


NODE_NAMES = ("plan", "collect", "conflicts", "ask", "wait", "parse", "finalize")
