"""API роутер поиска отелей по пожеланиям пользователя."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.search_engine import parse_intent, search_hotels

router = APIRouter()


class SearchRequest(BaseModel):
    query: str
    limit: int = 10


@router.post("/search")
async def search(req: SearchRequest, db: AsyncSession = Depends(get_db)):
    """Ищет отели по свободному описанию пожеланий.

    Разбор пожелания — LLM (или ключевые слова без ключа), ранжирование —
    по фактическим характеристикам из БД с указанием источника и уверенности.
    """
    return await search_hotels(db, req.query, limit=req.limit)


@router.post("/search/intent")
async def search_intent(req: SearchRequest):
    """Только разбор пожелания, без поиска: удобно для отладки и UI."""
    parsed, source = await parse_intent(req.query)
    return {"intent": parsed, "source": source}
