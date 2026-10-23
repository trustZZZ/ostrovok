"""
API роутер поиска.
"""
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

class SearchRequest(BaseModel):
    query: str
    region: str = "kaliningrad"
    limit: int = 10

class SearchResponse(BaseModel):
    hotels: list
    agent_log: list[str]
    intent: dict

@router.post("/search")
async def search(req: SearchRequest):
    """
    1. LLM парсит запрос в Pydantic-схему SearchIntent.
    2. SQL-запрос к hotel_features с учётом confidence >= 0.7.
    3. Для pgvector — семантический поиск по описаниям фич.
    4. Возвращает отели + объяснения.
    """
    # В полной версии:
    # 1. Parse query with LLM → SearchIntent
    # 2. Query DB with filters
    # 3. Rank by relevance + confidence
    # 4. Generate explanations
    
    return SearchResponse(
        hotels=[],
        agent_log=["Парсинг запроса...", "Поиск в БД...", "Ранжирование..."],
        intent={"sunset_view": True, "noise_score_lt": 30, "walk_to_sea_min": 5},
    )
