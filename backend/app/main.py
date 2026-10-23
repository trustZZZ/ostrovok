"""
FastAPI приложение.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.db import engine
from app.models import Base

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables on startup
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield

app = FastAPI(
    title="Routely × Островок API",
    description="Агентный подбор отелей по скрытым характеристикам",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health():
    return {"status": "ok", "service": "routely-ostrovok"}

# Import routers
from app.routers import search, hotels, hotelier, routes, agent

app.include_router(search.router, prefix="/api")
app.include_router(hotels.router, prefix="/api")
app.include_router(hotelier.router, prefix="/api")
app.include_router(routes.router, prefix="/api")
app.include_router(agent.router, prefix="/api")
