"""Разовая проверка: состояние прогона переживает рестарт контейнера.

Не входит в приложение и удаляется после проверки. Два режима:

    python _check_cp.py new 9       # запустить сбор и дождаться interrupt
    python _check_cp.py state <id>  # прочитать состояние потока из БД
"""

from __future__ import annotations

import asyncio
import sys

import httpx

from app.agents import graph as graph_module

API = "http://localhost:8000"


async def _connect() -> bool:
    """Подключает тот же persistent checkpointer, что и lifespan приложения."""
    from app.config import settings

    ok = await graph_module.enable_postgres_checkpointer(settings.DATABASE_URL)
    print(f"checkpointer={'postgres' if ok else 'memory'}", flush=True)
    return ok


async def start(hotel_id: int) -> None:
    await _connect()
    response = httpx.post(f"{API}/api/hotels/{hotel_id}/enrich", timeout=60.0)
    thread_id = response.json()["thread_id"]
    print(f"THREAD={thread_id}", flush=True)

    config = {"configurable": {"thread_id": thread_id}}
    for _ in range(40):
        await asyncio.sleep(3)
        state = await graph_module.agent_graph.aget_state(config)
        values = state.values or {}
        print(
            f"next={state.next} hotel_id={values.get('hotel_id')} "
            f"questions={len(values.get('questions') or [])}",
            flush=True,
        )
        if state.next:
            print(f"INTERRUPT_AT={state.next}", flush=True)
            return
    print("НЕ ДОЖДАЛИСЬ INTERRUPT", flush=True)


async def state(thread_id: str) -> None:
    await _connect()
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = await graph_module.agent_graph.aget_state(config)
    values = snapshot.values or {}
    print(f"next={snapshot.next}", flush=True)
    print(f"hotel_id={values.get('hotel_id')}", flush=True)
    print(f"log_tail={(values.get('log') or [])[-2:]}", flush=True)
    print(f"questions={len(values.get('questions') or [])}", flush=True)


def main() -> None:
    if len(sys.argv) < 3:
        print("usage: _check_cp.py new <hotel_id> | _check_cp.py state <thread_id>", flush=True)
        return
    mode, arg = sys.argv[1], sys.argv[2]
    if mode == "new":
        asyncio.run(start(int(arg)))
    else:
        asyncio.run(state(arg))


if __name__ == "__main__":
    main()
