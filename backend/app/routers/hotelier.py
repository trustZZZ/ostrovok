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