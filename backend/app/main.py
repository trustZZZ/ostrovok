"""FastAPI приложение."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session, engine, get_db
from app.feature_registry import get_feature, resolve_rows, select_features
from app.models import Base, HotelFeature
from app.seed import ensure_schema, seed_hotels

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Схема, идемпотентные миграции и сидирование отелей при старте."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await ensure_schema(engine)

    async with async_session() as session:
        created = await seed_hotels(session)
        if created:
            logger.info("Засидировано отелей: %s", created)

    yield


app = FastAPI(
    title="Routely × Островок API",
    description="Агентный подбор отелей по скрытым характеристикам",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "routely-ostrovok"}


@app.get("/api/features")
async def list_features():
    """Реестр характеристик: что система умеет собирать и у кого спрашивает.

    Реестр описан данными (app/features.yaml), поэтому этот ответ меняется
    без правки кода — добавленная характеристика появляется здесь сразу.
    """
    return [
        {
            "key": spec.key,
            "title": spec.title,
            "description": spec.description,
            "target": spec.target,
            "tools": list(spec.tools),
            "ttl_days": spec.ttl_days,
            "min_confidence": spec.min_confidence,
            "question": spec.question,
            "search": {"op": spec.search.op, "hint": spec.search.hint},
            # Кому верим при расхождении источников: геоданным или отельеру.
            "authoritative": spec.authoritative,
        }
        for spec in select_features()
    ]


@app.get("/api/conflicts")
async def list_conflicts(db: AsyncSession = Depends(get_db)):
    """Противоречия источников и то, как система их разрешила.

    Строки, где геоданные и отельер говорят разное, помечаются ``disputed``
    при записи. Здесь видно все варианты и выбранное значение — это и есть
    «система замечает и разбирается», а не молча берёт последнее.
    """
    rows = (
        (
            await db.execute(
                select(HotelFeature)
                .where(HotelFeature.disputed.is_(True))
                .order_by(HotelFeature.hotel_id, HotelFeature.feature_key)
            )
        )
        .scalars()
        .all()
    )

    grouped: dict[tuple[int, str], list] = {}
    for row in rows:
        grouped.setdefault((row.hotel_id, row.feature_key), []).append(row)

    conflicts = []
    for (hotel_id, key), items in grouped.items():
        spec = get_feature(key)
        winner = resolve_rows(items, spec) if spec else None
        conflicts.append(
            {
                "hotel_id": hotel_id,
                "feature": key,
                "title": spec.title if spec else key,
                "authoritative": spec.authoritative if spec else None,
                "variants": [
                    {
                        "source": row.source,
                        "confidence": round(float(row.confidence or 0), 3),
                        "value": spec.extract(row.value) if spec else row.value,
                    }
                    for row in items
                ],
                "resolved": {
                    "source": winner.source if winner else None,
                    "value": spec.extract(winner.value) if (spec and winner) else None,
                },
            }
        )
    return conflicts


from app.routers import agent, hotels, hotelier, routes, search  # noqa: E402

app.include_router(search.router, prefix="/api")
app.include_router(hotels.router, prefix="/api")
app.include_router(hotelier.router, prefix="/api")
app.include_router(routes.router, prefix="/api")
app.include_router(agent.router, prefix="/api")
