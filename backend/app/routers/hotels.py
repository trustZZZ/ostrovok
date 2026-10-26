"""API отелей: список, характеристики, запуск сбора агентом."""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from geoalchemy2.shape import to_shape
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.models import Hotel

logger = logging.getLogger(__name__)
router = APIRouter()


def _serialize_feature(row) -> dict:
    return {
        "key": row.feature_key,
        "value": row.value,
        "source": row.source,
        "confidence": row.confidence,
        "raw_evidence": row.raw_evidence,
        "computed_at": row.computed_at.isoformat() if row.computed_at else None,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
    }


def _serialize_hotel(hotel: Hotel) -> dict:
    geometry = to_shape(hotel.geom)
    return {
        "id": hotel.id,
        "name": hotel.name,
        "address": hotel.address or "",
        "lat": geometry.y,
        "lon": geometry.x,
        "floors": hotel.floors,
        "facade_azimuth": hotel.facade_azimuth,
        "features": [_serialize_feature(row) for row in hotel.features],
    }


@router.get("/hotels")
async def list_hotels(db: AsyncSession = Depends(get_db)):
    """Все отели с собранными характеристиками — источник данных для UI."""
    hotels = (
        (await db.execute(
            select(Hotel).options(selectinload(Hotel.features)).order_by(Hotel.name)
        ))
        .scalars()
        .all()
    )
    return [_serialize_hotel(hotel) for hotel in hotels]


@router.get("/hotels/{hotel_id}/features")
async def get_features(hotel_id: int, db: AsyncSession = Depends(get_db)):
    """Характеристики отеля с источником, уверенностью и evidence."""
    hotel = await db.get(Hotel, hotel_id, options=[selectinload(Hotel.features)])
    if hotel is None:
        raise HTTPException(status_code=404, detail="Отель не найден")
    return [_serialize_feature(row) for row in hotel.features]


@router.post("/hotels/{hotel_id}/enrich")
async def enrich(hotel_id: int, background: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    """Запускает агентный сбор характеристик в фоне."""
    hotel = await db.get(Hotel, hotel_id)
    if hotel is None:
        raise HTTPException(status_code=404, detail="Отель не найден")

    thread_id = str(uuid.uuid4())
    background.add_task(_run_agent, hotel_id, thread_id)
    return {
        "thread_id": thread_id,
        "status": "started",
        "message": f"Сбор характеристик для «{hotel.name}» запущен",
    }


@router.post("/hotels/enrich-all")
async def enrich_all(background: BackgroundTasks, limit: int = 10, db: AsyncSession = Depends(get_db)):
    """Ставит в очередь сбор для всех отелей — удобно для подготовки демо."""
    hotels = (await db.execute(select(Hotel).order_by(Hotel.id).limit(limit))).scalars().all()
    if not hotels:
        raise HTTPException(status_code=404, detail="В базе нет отелей: выполните сидирование")

    thread_ids = {}
    for hotel in hotels:
        thread_id = str(uuid.uuid4())
        thread_ids[hotel.id] = thread_id
        background.add_task(_run_agent, hotel.id, thread_id)

    return {"started": len(hotels), "thread_ids": thread_ids}


async def _run_agent(hotel_id: int, thread_id: str) -> None:
    """Фоновая задача: прогон графа до записи характеристик в БД."""
    from app.agents.graph import agent_graph

    config = {"configurable": {"thread_id": thread_id}}
    initial = {"hotel_id": hotel_id, "thread_id": thread_id, "log": [], "features": {}}
    try:
        await agent_graph.ainvoke(initial, config)
    except Exception:  # noqa: BLE001 - фоновая задача не должна ронять процесс
        logger.exception("сбор характеристик для отеля %s упал", hotel_id)
