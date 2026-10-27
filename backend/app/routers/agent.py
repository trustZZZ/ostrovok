"""
API роутер агента — реальный SSE стриминг шагов LangGraph.
"""
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
import json
from app.agents import graph as agent_module  # граф берём из модуля: checkpointer подменяется при старте

router = APIRouter()

# Имена узлов агентного графа
NODE_NAMES = ("geo", "open_data", "conflicts", "ask", "wait", "parse", "finalize")


@router.get("/agent/{thread_id}/stream")
async def stream_agent(thread_id: str):
    """SSE стриминг реальных шагов агентного графа."""
    async def event_generator():
        config = {"configurable": {"thread_id": thread_id}}

        # astream_events отдает все события выполнения графа
        async for event in agent_module.agent_graph.astream_events({}, config=config, version="v2"):
            kind = event["event"]
            node_name = event.get("name", "")

            # Фильтруем только начало и конец выполнения узлов
            if kind == "on_chain_start" and node_name in NODE_NAMES:
                yield f"data: {json.dumps({'node': node_name, 'status': 'started', 'message': f'⏳ Запуск {node_name}...'})}\n\n"

            elif kind == "on_chain_end" and node_name in NODE_NAMES:
                # Можно вытащить реальные логи из состояния, если они там есть
                yield f"data: {json.dumps({'node': node_name, 'status': 'done', 'message': f'✅ {node_name} завершен'})}\n\n"

            # Специальная обработка прерывания (wait)
            elif kind == "on_custom_event" and node_name == "interrupt":
                yield f"data: {json.dumps({'node': 'wait', 'status': 'interrupted', 'message': '⏸️ Ожидание ответа отельера', 'data': event.get('data')})}\n\n"

        yield f"data: {json.dumps({'node': 'END', 'status': 'done', 'message': '🏁 Обработка завершена'})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")