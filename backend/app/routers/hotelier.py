"""
API роутер отельера.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db

router = APIRouter()

class AnswerRequest(BaseModel):
    answer: str

@router.get("/hotelier/inbox")
async def inbox(db: AsyncSession = Depends(get_db)):
    """Список всех pending-вопросов для всех отелей."""
    from sqlalchemy import select
    from app.models import HotelierQuestion, Hotel
    
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
    """Принимает ответ, размораживает LangGraph-поток."""
    from sqlalchemy import select, update
    from app.models import HotelierQuestion
    from datetime import datetime
    
    # Обновляем вопрос
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
    
    # Размораживаем LangGraph поток
    # В реальности: agent_graph.ainvoke(input, config={"configurable": {"thread_id": ...}})
    
    return {
        "status": "processed",
        "message": "Ответ принят и будет обработан агентом",
    }
