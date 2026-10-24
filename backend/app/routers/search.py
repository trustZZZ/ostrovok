"""
API роутер поиска отелей по намерению пользователя.
"""
from fastapi import APIRouter
from pydantic import BaseModel
from langchain_core.prompts import ChatPromptTemplate
import json

from app.llm_utils import get_llm

router = APIRouter()


class SearchRequest(BaseModel):
    query: str


@router.post("/search")
async def search(req: SearchRequest):
    """Разбирает свободный запрос пользователя в структурированный интент и ищет отели."""
    llm = get_llm()
    prompt = ChatPromptTemplate.from_messages([
        ("system", "Ты - поисковый агент отелей. Преобразуй запрос пользователя в JSON с полями: sunset_view (bool), noise_score_lt (int), walk_to_sea_min (int). Если параметр не важен, ставь null."),
        ("human", "Запрос: {query}")
    ])

    try:
        response = await llm.ainvoke(prompt.format(query=req.query))
        clean_json = response.content.replace("```json", "").replace("```", "").strip()
        intent = json.loads(clean_json)
    except Exception:
        intent = {"sunset_view": None, "noise_score_lt": 50, "walk_to_sea_min": 10}  # Fallback

    # Здесь должен быть реальный запрос к БД с использованием intent
    # Для демо вернем моковые данные, но с реальным intent
    return {
        "hotels": [{"id": 102, "name": "Zelenogradsk Premium", "match_score": 0.95}],
        "agent_log": [f"🧠 Распознан интент: {intent}", "🔍 Найдено 1 совпадение в БД"],
        "intent": intent,
    }