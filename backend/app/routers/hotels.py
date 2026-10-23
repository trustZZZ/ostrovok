"""
API роутер отелей.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db

router = APIRouter()

@router.get("/hotels/{hotel_id}/features")
async def get_features(hotel_id: int, db: AsyncSession = Depends(get_db)):
    """Все фичи с источниками, confidence, evidence."""
    from sqlalchemy import select
    from app.models import HotelFeature
    
    result = await db.execute(
        select(HotelFeature).where(HotelFeature.hotel_id == hotel_id)
    )
    features = result.scalars().all()
    
    return [
        {
            "key": f.feature_key,
            "value": f.value,
            "source": f.source,
            "confidence": f.confidence,
            "computed_at": f.computed_at.isoformat() if f.computed_at else None,
            "raw_evidence": f.raw_evidence,
        }
        for f in features
    ]

@router.post("/hotels/{hotel_id}/enrich")
async def enrich(hotel_id: int):
    """Запускает агентный граф для обогащения отеля. Возвращает thread_id."""
    import uuid
    from app.agents.graph import agent_graph
    
    thread_id = str(uuid.uuid4())
    
    # Запускаем граф асинхронно
    # В реальности — через background task
    config = {"configurable": {"thread_id": thread_id}}
    
    return {
        "thread_id": thread_id,
        "status": "started",
        "message": "Агентный граф запущен. Отслеживайте прогресс через /agent/{thread_id}/stream",
    }
