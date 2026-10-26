"""Поиск отелей по собранным характеристикам.

Пожелание пользователя разбирается в ограничения по характеристикам из
реестра (features.yaml), затем каждый отель оценивается по фактическим
значениям из БД. Объяснение строится из тех же данных, что сохранены
при сборе: значение, источник, уверенность.

Ключевое правило: если характеристики у отеля нет, он не получает балл
за неё — в объяснении появляется «нет данных». Придумывать значение
вместо инструмента запрещено.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from geoalchemy2.shape import to_shape
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.feature_registry import (
    FeatureSpec,
    load_registry,
    resolve_rows,
    select_features,
)

logger = logging.getLogger(__name__)

# Разбор пожелания по ключевым словам. Используется, когда LLM выключен
# или недоступен: это не заглушка, а рабочий детерминированный режим.
# Значение — порог, который имеет смысл для гостя.
KEYWORD_INTENT: dict[str, tuple[tuple[str, ...], Any]] = {
    "sunset_view": (("закат", "западн", "sunset"), True),
    "noise_score": (("тих", "шум", "спокой", "не слыш", "quiet"), 35),
    "walk_to_sea": (("мор", "пляж", "побереж", "beach"), 15),
    "climate_summer": (("тепл", "жарк", "купат", "солнечн"), 22),
    "pet_friendly": (("питом", "собак", "кош", "пёс", "pet"), True),
    # Номерные характеристики: из открытых данных не выводятся, но гость
    # просит именно их — поэтому они участвуют в разборе пожелания.
    "room_west_windows": (("номер с видом", "западн"), True),
    "room_silence": (("тихий номер", "шумоизоляц", "не слыш"), True),
    "room_balcony": (("балкон", "террас"), True),
}


def _keyword_intent(query: str) -> dict[str, Any]:
    text = query.lower()
    intent: dict[str, Any] = {}
    for key, (needles, value) in KEYWORD_INTENT.items():
        if any(needle in text for needle in needles):
            intent[key] = value
    return intent


async def _llm_intent(query: str) -> dict[str, Any] | None:
    """Разбор пожелания моделью. Список характеристик берётся из реестра."""
    from app.llm_utils import get_llm

    specs = select_features()
    described = "\n".join(
        f'- "{spec.key}" ({spec.value_type}): {spec.title}. {spec.description} '
        f"Когда гость говорит про: {spec.search.hint}"
        for spec in specs
    )
    schema = ", ".join(f'"{spec.key}": <{spec.value_type} или null>' for spec in specs)
    system = (
        "Ты извлекаешь пожелания гостя об отеле. Отвечай ТОЛЬКО JSON без пояснений.\n"
        "Если пожелание не упомянуто — поставь null. Для числа верни порог, "
        "который имеет смысл для гостя: не 0 и не заведомо крайние значения "
        "(например, «тихо» — это шум около 30, а не 0).\n"
        f"Доступные характеристики:\n{described}\n\n"
        f"Формат ответа: {{{schema}}}"
    )

    try:
        llm = get_llm()
        response = await llm.ainvoke([("system", system), ("human", query)])
        text = str(response.content).replace("```json", "").replace("```", "").strip()
        data = json.loads(text)
    except Exception as exc:  # noqa: BLE001 - LLM внешний
        logger.warning("LLM-разбор пожелания недоступен: %s", exc)
        return None

    if not isinstance(data, dict):
        return None
    allowed = set(load_registry())
    return {key: value for key, value in data.items() if key in allowed}


def _clamp_intent(intent: dict[str, Any]) -> dict[str, Any]:
    """Приводит числовые пороги к границам, описанным в реестре."""
    registry = load_registry()
    result: dict[str, Any] = {}
    for key, value in intent.items():
        spec = registry.get(key)
        result[key] = spec.search.clamp(value) if spec else value
    return result


async def parse_intent(query: str) -> tuple[dict[str, Any], str]:
    """Возвращает (ограничения, источник разбора: "llm" | "keywords")."""
    heuristic = _keyword_intent(query)
    if not settings.llm_enabled:
        return _clamp_intent(heuristic), "keywords"

    llm_intent = await _llm_intent(query)
    if llm_intent is None:
        return _clamp_intent(heuristic), "keywords"

    merged = dict(heuristic)
    merged.update({key: value for key, value in llm_intent.items() if value is not None})
    return _clamp_intent(merged), "llm"


def _describe(spec: FeatureSpec, row: Any) -> str:
    """Человекочитаемое описание факта — из сохранённого значения."""
    value = row.value if isinstance(row.value, dict) else {"value": row.value}

    if spec.key == "sunset_view":
        if value.get("visible"):
            return f"закат виден с {value.get('from_floor')} этажа"
        return "закат из окон не виден"
    if spec.key == "noise_score":
        return f"шум {value.get('score')}/100 ({value.get('level')})"
    if spec.key == "walk_to_sea":
        text = f"{value.get('minutes')} мин пешком до моря"
        if value.get("crosses_highway"):
            text += " с переходом через трассу"
        return text
    if spec.key == "climate_summer":
        return f"в июле в среднем +{value.get('mean_july_max_c')} °C"
    if "allowed" in value:
        return "гостей с питомцем принимают" if value["allowed"] else "с питомцем не принимают"
    # Булевы характеристики (в том числе номерные) описываются по value_field
    # из реестра — новая фича заработает без правки этого файла.
    flag = spec.extract(value)
    if isinstance(flag, bool):
        return f"{spec.title}: {'да' if flag else 'нет'}"
    return f"{spec.title}: {json.dumps(value, ensure_ascii=False)}"


def _confidence_note(row: Any) -> str:
    return f"{row.source}, уверенность {row.confidence:.0%}"


def _empty_explanation(has_features: bool) -> str:
    """Пустая выдача объясняется по-разному — иначе сообщение врёт.

    «Характеристики не собраны» при нераспознанном пожелании отправляло бы
    пользователя запускать сбор заново, хотя данные уже есть.
    """
    if has_features:
        return "пожелание не распознано — уточните, что важно"
    return "характеристики ещё не собраны: запустите сбор для отеля"


async def search_hotels(db: AsyncSession, query: str, limit: int = 10) -> dict[str, Any]:
    from app.models import Hotel

    intent, intent_source = await parse_intent(query)
    registry = load_registry()

    hotels = (
        (await db.execute(select(Hotel).options(selectinload(Hotel.features))))
        .scalars()
        .all()
    )

    matches: list[dict[str, Any]] = []
    for hotel in hotels:
        # Выбор значения среди источников — по правилам реестра, а не по
        # «кто последний записал»: для измеримых характеристик доверяем
        # геоданным, для субъективных (номера, питомцы) — ответу отельера.
        grouped: dict[str, list[Any]] = {}
        for row in hotel.features:
            grouped.setdefault(row.feature_key, []).append(row)

        best: dict[str, Any] = {}
        for key, rows in grouped.items():
            spec = registry.get(key)
            chosen = (
                resolve_rows(rows, spec)
                if spec
                else max(rows, key=lambda item: item.confidence or 0)
            )
            if chosen is not None:
                best[key] = chosen

        matched: list[str] = []
        missed: list[str] = []
        unknown: list[str] = []
        notes: list[str] = []

        for key, wanted in intent.items():
            spec = registry.get(key)
            if spec is None or wanted is None:
                continue
            row = best.get(key)
            if row is None or (row.confidence or 0) <= 0:
                unknown.append(key)
                notes.append(f"нет данных: {spec.title}")
                continue
            actual = spec.extract(row.value)
            described = f"{_describe(spec, row)} ({_confidence_note(row)})"
            if row.disputed:
                # Противоречие источников не скрываем: гость должен видеть,
                # что данные расходятся, а не получить уверенный ответ.
                described += ", источники расходятся"
            if spec.search.matches(wanted, actual):
                matched.append(key)
                notes.append(described)
            else:
                missed.append(key)
                notes.append(f"{described} — не то, что просили")

        considered = len(matched) + len(missed) + len(unknown)
        score = len(matched) / considered if considered else 0.0

        geometry = to_shape(hotel.geom)
        match_row = {
            "id": hotel.id,
            "name": hotel.name,
            "address": hotel.address or "",
            "lat": geometry.y,
            "lon": geometry.x,
            "floors": hotel.floors,
            "facade_azimuth": hotel.facade_azimuth,
            "features": [
                {
                    "key": row.feature_key,
                    "value": row.value,
                    "source": row.source,
                    "confidence": row.confidence,
                    "disputed": bool(row.disputed),
                    "raw_evidence": row.raw_evidence,
                }
                for row in hotel.features
            ],
            "explanation": (
                "; ".join(notes)
                if notes
                else _empty_explanation(bool(hotel.features))
            ),
            "score": round(score, 3),
            "_matched": len(matched),
            "_missed": len(missed),
            "_unknown": len(unknown),
        }
        matches.append(match_row)

    matches.sort(key=lambda item: (item["score"], item["_matched"], -item["_unknown"]), reverse=True)
    for item in matches:
        item.pop("_matched", None)
        item.pop("_missed", None)
        item.pop("_unknown", None)

    agent_log = [
        f"Пожелания распознаны ({intent_source}): {intent or 'ничего не найдено'}",
        f"Проверено отелей: {len(hotels)}",
    ]
    if not intent:
        agent_log.append(
            "Пожелание не распознано: перечислите, что важно — "
            "закат, тишина, море, балкон, питомец"
        )
    if hotels and not any(hotel.features for hotel in hotels):
        agent_log.append(
            "У отелей ещё нет характеристик: запустите POST /api/hotels/{id}/enrich"
        )

    return {
        "hotels": matches[:limit],
        "agent_log": agent_log,
        "intent": intent,
        "intent_source": intent_source,
    }
