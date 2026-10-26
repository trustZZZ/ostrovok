"""FastAPI приложение."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db import async_session, engine
from app.feature_registry import select_features
from app.models import Base
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
        }
        for spec in select_features()
    ]


from app.routers import agent, hotels, hotelier, routes, search  # noqa: E402

app.include_router(search.router, prefix="/api")
app.include_router(hotels.router, prefix="/api")
app.include_router(hotelier.router, prefix="/api")
app.include_router(routes.router, prefix="/api")
app.include_router(agent.router, prefix="/api")
