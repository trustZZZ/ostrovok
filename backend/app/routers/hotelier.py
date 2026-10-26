"""
API роутер отельера.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from datetime import datetime
from app.db import get_db
from app.models import HotelierQuestion, Hotel
from app.agents.graph import agent_graph # Импортируем граф

router = APIRouter()

class AnswerRequest(BaseModel):
    answer: str
    thread_id: str | None = None # Добавляем thread_id для возобновления

@router.get("/hotelier/inbox")
async def inbox(db: AsyncSession = Depends(get_db)):
    """Список всех pending-вопросов."""
    result = await db.execute(
        select(HotelierQuestion, Hotel.name)
        .join(Hotel)
        .where(HotelierQuestion.status == "pending")
    )
    return [
        {
            "id": q.id,
            "hotel_id": q.hotel_id,
            "hotel_name": name,
            "feature_key": q.feature_key,
            "question": q.question,
            "status": q.status,
            "thread_id": q.thread_id, # Возвращаем thread_id фронтенду
            "asked_at": q.asked_at.isoformat() if q.asked_at else None,
        }
        for q, name in result.all()
    ]

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

    # 3. Размораживаем LangGraph, передавая ответ в узел wait
    if thread_id:
        config = {"configurable": {"thread_id": thread_id}}
        try:
            # Значение, переданное в ainvoke, interrupt() вернет как ответ в node_wait,
            # а node_parse ожидает словарь {feature_key: raw_answer}
            resume_input = {question.feature_key: req.answer}
            await agent_graph.ainvoke(resume_input, config)
        except Exception as e:
            print(f"⚠️ Ошибка при возобновлении графа: {e}")

    return {
        "status": "processed",
        "message": "Ответ принят, агент продолжил обработку",
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