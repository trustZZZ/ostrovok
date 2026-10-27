"""
API роутер отельера.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from datetime import datetime
from app.db import get_db
from app.feature_registry import get_feature
from app.models import Hotel, HotelFeature, HotelierQuestion

logger = logging.getLogger(__name__)

router = APIRouter()

class AnswerRequest(BaseModel):
    answer: str
    thread_id: str | None = None # Добавляем thread_id для возобновления


@router.get("/hotelier/inbox")
async def inbox(
    status: str = Query(
        default="all",
        pattern="^(pending|answered|all)$",
        description="pending — очередь вопросов, answered — история ответов, all — оба",
    ),
    db: AsyncSession = Depends(get_db),
):
    """Вопросы отельеру вместе с ответами и записанным значением.

    Раньше отдавались только pending: после ответа вопрос исчезал из выдачи,
    поэтому кабинет не мог показать, что отельер ответил и какое значение из
    ответа записалось. История ответов — доказательство того, что ответ стал
    самостоятельным источником характеристики, а не строчкой в переписке.
    """
    query = select(HotelierQuestion, Hotel.name).join(Hotel)
    if status != "all":
        query = query.where(HotelierQuestion.status == status)
    rows = (await db.execute(query.order_by(HotelierQuestion.asked_at.desc()))).all()

    stored = await _hotelier_values(db, rows)

    result = []
    for question, hotel_name in rows:
        feature = stored.get((question.hotel_id, question.feature_key))
        spec = get_feature(question.feature_key)
        result.append(
            {
                "id": question.id,
                "hotel_id": question.hotel_id,
                "hotel_name": hotel_name,
                "feature_key": question.feature_key,
                "question": question.question,
                "status": question.status,
                "thread_id": question.thread_id,
                "asked_at": question.asked_at.isoformat() if question.asked_at else None,
                "answer_raw": question.answer_raw,
                "answer_parsed": question.answer_parsed,
                "answered_at": question.answered_at.isoformat() if question.answered_at else None,
                # Фактическое значение, по которому идёт поиск: то же, что
                # видит гость в карточке отеля (source=hotelier).
                "value": (
                    spec.extract(feature.value) if feature is not None and spec
                    else feature.value if feature is not None else None
                ),
                "confidence": round(float(feature.confidence or 0), 3) if feature is not None else None,
                "computed_at": (
                    feature.computed_at.isoformat()
                    if feature is not None and feature.computed_at
                    else None
                ),
            }
        )
    return result


async def _hotelier_values(db: AsyncSession, rows) -> dict[tuple[int, str], HotelFeature]:
    """Значения характеристик от отельера по парам (отель, характеристика)."""
    pairs = {(question.hotel_id, question.feature_key) for question, _ in rows}
    if not pairs:
        return {}
    features = (
        (
            await db.execute(
                select(HotelFeature).where(
                    HotelFeature.hotel_id.in_({hotel_id for hotel_id, _ in pairs}),
                    HotelFeature.source == "hotelier",
                )
            )
        )
        .scalars()
        .all()
    )
    return {
        (feature.hotel_id, feature.feature_key): feature
        for feature in features
        if (feature.hotel_id, feature.feature_key) in pairs
    }

@router.post("/hotelier/{hotel_id}/answer/{question_id}")
async def answer(
    hotel_id: int,
    question_id: int,
    req: AnswerRequest,
    db: AsyncSession = Depends(get_db),
):
    """Принимает ответ и РАЗМОРАЖИВАЕТ LangGraph-поток."""
    
    # 1. Получаем вопрос, чтобы узнать thread_id
    q_result = await db.execute(select(HotelierQuestion).where(HotelierQuestion.id == question_id))
    question = q_result.scalar_one_or_none()
    
    if not question:
        raise HTTPException(status_code=404, detail="Вопрос не найден")
        
    thread_id = req.thread_id or question.thread_id

    # 2. Обновляем вопрос в БД
    await db.execute(
        update(HotelierQuestion)
        .where(HotelierQuestion.id == question_id)
        .values(
            answer_raw=req.answer,
            status="answered",
            answered_at=datetime.utcnow(),
        )
    )
    await db.commit()

    # 3. Сразу записываем значение из ответа. Полагаться только на живое
    #    состояние графа нельзя: MemorySaver держит его в памяти процесса, и
    #    после рестарта контейнера ответ на зависший вопрос уже не разморозит
    #    граф (раздел 12, P3). Ответ отельера — самостоятельный источник,
    #    поэтому пишем его тем же upsert_feature, что и граф: одна строка на
    #    (отель, характеристика, источник), провенанс сохраняется.
    saved_value = None
    try:
        from app.feature_registry import get_feature
        from app.llm_utils import parse_answer_with_llm
        from app.seed import upsert_feature

        spec = get_feature(question.feature_key)
        parsed = await parse_answer_with_llm(
            question=question.question,
            raw_answer=req.answer,
            feature_key=question.feature_key,
        )
        value = parsed.get("value", req.answer)
        if spec is not None:
            # Реестр знает тип характеристики, поэтому и приводит к нему:
            # свободный ответ «Люкс и Апартаменты» становится true.
            value = spec.coerce(value, req.answer)
            if not isinstance(value, dict):
                # Сравнение идёт по одному полю значения, тому же, что и у
                # вычисленных характеристик.
                value = {spec.value_field: value}
        await upsert_feature(
            db,
            hotel_id=question.hotel_id,
            feature_key=question.feature_key,
            value=value,
            source="hotelier",
            confidence=float(parsed.get("confidence", 0.95)),
            evidence={"raw_answer": req.answer},
            ttl_days=spec.ttl_days if spec else 180,
        )
        # Разбор свободного ответа храним в самом вопросе: кабинет показывает,
        # что именно система поняла, не отправляя текст в модель повторно.
        await db.execute(
            update(HotelierQuestion)
            .where(HotelierQuestion.id == question_id)
            .values(answer_parsed={"value": value, "parsed": parsed})
        )
        await db.commit()
        saved_value = value
    except Exception:  # noqa: BLE001 - ответ уже принят, значение не должно теряться молча
        await db.rollback()
        logger.exception(
            "не удалось сохранить ответ отельера: отель %s, «%s»",
            question.hotel_id,
            question.feature_key,
        )

    # 4. Состояние графа не возобновляем. Проверено фактом: ainvoke по потоку,
    #    чьё состояние не подхватилось (MemorySaver живёт в памяти процесса и
    #    теряется при рестарте контейнера), запускает полный прогон заново.
    #    node_ask при этом удаляет очередь вопросов и создаёт её с новыми id,
    #    поэтому ответы на остальные вопросы начинают возвращать 404, а
    #    очередь бесконечно пересобирается. Ответ отельера уже записан выше
    #    как самостоятельный источник (source=hotelier) — для цикла
    #    «вопрос → ответ → значение» этого достаточно.
    logger.info(
        "ответ отельера сохранён напрямую: отель %s, «%s», поток %s",
        question.hotel_id,
        question.feature_key,
        thread_id,
    )

    return {
        "status": "processed",
        "message": "Ответ принят, значение записано с источником «отельер»",
        "value_saved": saved_value is not None,
    }


class ResolveRequest(BaseModel):
    value: str | bool | float | None = None
    note: str | None = None


@router.post("/hotelier/{hotel_id}/resolve/{feature_key}")
async def resolve(
    hotel_id: int,
    feature_key: str,
    req: ResolveRequest,
    db: AsyncSession = Depends(get_db),
):
    """Отельер подтверждает или исправляет значение — противоречие снимается.

    Это вторая половина требования «система замечает и разбирается»: мало
    пометить расхождение, нужен способ его закрыть. Ответ отельера пишется
    отдельным источником, после чего ``upsert_feature`` пересчитывает
    ``disputed``: совпало с геоданными — расхождение снято, не совпало —
    осталось видимым, но с явной позицией отельера.
    """
    from app.feature_registry import get_feature
    from app.models import HotelFeature
    from app.seed import upsert_feature

    spec = get_feature(feature_key)
    if spec is None:
        raise HTTPException(
            status_code=404,
            detail=f"Характеристика «{feature_key}» не описана в реестре",
        )

    hotel = await db.get(Hotel, hotel_id)
    if hotel is None:
        raise HTTPException(status_code=404, detail="Отель не найден")

    # Значение приводим к форме, из которой реестр умеет достать value_field:
    # отельер может прислать и голый true, и готовый объект.
    value = req.value
    if not isinstance(value, dict):
        value = {spec.value_field: value}
    value["confirmed_by"] = "hotelier"

    await upsert_feature(
        db,
        hotel_id=hotel_id,
        feature_key=feature_key,
        value=value,
        source="hotelier",
        confidence=0.95,
        evidence={"note": req.note, "resolved_by": "hotelier"},
        ttl_days=spec.ttl_days,
    )
    await db.commit()

    rows = (
        await db.execute(
            select(HotelFeature).where(
                HotelFeature.hotel_id == hotel_id,
                HotelFeature.feature_key == feature_key,
            )
        )
    ).scalars().all()

    return {
        "status": "resolved",
        "feature": feature_key,
        "still_disputed": bool(rows and rows[0].disputed),
        "rows": [
            {
                "source": row.source,
                "value": spec.extract(row.value),
                "confidence": round(float(row.confidence or 0), 3),
                "disputed": bool(row.disputed),
            }
            for row in rows
        ],
    }