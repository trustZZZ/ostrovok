"""
API роутер агента — SSE стриминг шагов.
"""
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
import asyncio
import json

router = APIRouter()

@router.get("/agent/{thread_id}/stream")
async def stream_agent(thread_id: str):
    """
    SSE стриминг шагов агентного графа в реальном времени.
    """
    async def event_generator():
        # В реальности — подписка на обновления LangGraph
        steps = [
            {"node": "geo", "status": "started", "message": "🛰️ Запуск GIS-инструментов..."},
            {"node": "geo", "status": "done", "message": "✅ sunset_view: виден с 3 этажа"},
            {"node": "geo", "status": "done", "message": "✅ noise_score: 22/100"},
            {"node": "geo", "status": "done", "message": "✅ walk_to_sea: 4 мин"},
            {"node": "open_data", "status": "started", "message": "🌐 Загрузка открытых данных..."},
            {"node": "open_data", "status": "done", "message": "✅ Wikidata: историческое здание"},
            {"node": "open_data", "status": "done", "message": "✅ Open-Meteo: климат загружен"},
            {"node": "conflicts", "status": "started", "message": "🔍 Поиск конфликтов..."},
            {"node": "conflicts", "status": "done", "message": "⚠️ Конфликт: шум vs позиционирование"},
            {"node": "ask", "status": "done", "message": "📋 Вопрос отправлен отельеру"},
            {"node": "finalize", "status": "done", "message": "✅ 6 характеристик сохранено в БД"},
        ]
        
        for step in steps:
            yield f"data: {json.dumps(step)}\n\n"
            await asyncio.sleep(0.5)
        
        yield f"data: {json.dumps({'node': 'END', 'status': 'done', 'message': '🏁 Завершено'})}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
    )
