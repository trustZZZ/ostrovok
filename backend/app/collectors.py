"""Инструменты сбора характеристик.

Каждый инструмент — асинхронная функция ``HotelContext -> ToolResult``.
Имена инструментов указываются в ``app/features.yaml`` (поле ``tools``),
поэтому новый источник подключается регистрацией в ``TOOL_REGISTRY``
без изменения графа.

Правило: инструмент, у которого нет данных, обязан вернуть
``confidence = 0.0``, а не правдоподобную выдумку.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

GEO_TOOL_TIMEOUT_S = 120
HTTP_TOOL_TIMEOUT_S = 20


@dataclass
class HotelContext:
    """Всё, что инструментам нужно знать об отеле."""

    id: int
    name: str
    lat: float
    lon: float
    floors: int = 3
    facade_azimuth: float | None = None


@dataclass
class ToolResult:
    """Значение характеристики вместе с провенансом."""

    value: Any
    source: str
    confidence: float
    evidence: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Кэш гео-слоёв: читаются один раз на процесс
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def load_buildings():
    """Здания вокруг отелей (buildings.gpkg). None, если слой недоступен."""
    try:
        import geopandas as gpd

        gdf = gpd.read_file(settings.BUILDINGS_PATH)
        logger.info("buildings.gpkg: %s объектов", len(gdf))
        return gdf if not gdf.empty else None
    except Exception as exc:  # noqa: BLE001 - слой может отсутствовать
        logger.warning("buildings.gpkg недоступен: %s", exc)
        return None


@lru_cache(maxsize=1)
def load_noise_layers() -> dict[str, Any]:
    """Слои источников шума, разложенные по тегу OSM."""
    try:
        import geopandas as gpd

        gdf = gpd.read_file(settings.NOISE_PATH)
    except Exception as exc:  # noqa: BLE001
        logger.warning("noise_sources.geojson недоступен: %s", exc)
        return {}

    if gdf is None or gdf.empty:
        return {}

    layers: dict[str, Any] = {}
    for column in ("highway", "railway", "amenity"):
        if column in gdf.columns:
            subset = gdf[gdf[column].notna()]
            if not subset.empty:
                layers[column] = subset
    return layers


@lru_cache(maxsize=1)
def load_coast():
    """Пляжи и линия побережья (beaches.geojson)."""
    try:
        import geopandas as gpd

        gdf = gpd.read_file(settings.BEACHES_PATH)
        logger.info("beaches.geojson: %s объектов", len(gdf))
        return gdf if not gdf.empty else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("beaches.geojson недоступен: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Геоинструменты
# ---------------------------------------------------------------------------
async def tool_sunset_view(ctx: HotelContext) -> ToolResult:
    from app.tools.sunset_view import compute_sunset_view

    result = await asyncio.to_thread(
        compute_sunset_view,
        hotel_lon=ctx.lon,
        hotel_lat=ctx.lat,
        total_floors=ctx.floors,
        dem_path=settings.DEM_PATH,
        buildings_gdf=load_buildings(),
    )
    return ToolResult(
        value={
            "visible": result.visible,
            "from_floor": result.from_floor,
            "months": result.months,
            "azimuth_deg": result.azimuth_deg,
        },
        source="SRTM+OSM",
        confidence=result.confidence,
        evidence=result.evidence,
    )


async def tool_noise_score(ctx: HotelContext) -> ToolResult:
    from shapely.geometry import Point

    from app.tools.noise_score import compute_noise_score

    payload = await asyncio.to_thread(
        compute_noise_score,
        hotel_geom=Point(ctx.lon, ctx.lat),
        osm_layers=load_noise_layers(),
    )
    return ToolResult(
        value={
            "score": payload["score"],
            "level": payload["level"],
            "breakdown": payload["breakdown"],
        },
        source="OSM",
        confidence=payload["confidence"],
        evidence=payload["evidence"],
    )


async def tool_walk_to_sea(ctx: HotelContext) -> ToolResult:
    from app.tools.walk_to_sea import compute_walk_to_sea

    payload = await asyncio.to_thread(
        compute_walk_to_sea,
        hotel_lon=ctx.lon,
        hotel_lat=ctx.lat,
        dem_path=settings.DEM_PATH,
        coast_gdf=load_coast(),
        roads_gdf=load_noise_layers().get("highway"),
    )
    return ToolResult(
        value={
            "minutes": payload["minutes"],
            "distance_m": payload["distance_m"],
            "crosses_highway": payload["crosses_highway"],
        },
        source=payload["source"],
        confidence=payload["confidence"],
        evidence=payload["evidence"],
    )


# ---------------------------------------------------------------------------
# Открытые API
# ---------------------------------------------------------------------------
_OPEN_METEO = "https://archive-api.open-meteo.com/v1/archive"


async def tool_climate_summer(ctx: HotelContext) -> ToolResult:
    """Средний июльский максимум за последние 5 лет (Open-Meteo archive)."""
    params = {
        "latitude": round(ctx.lat, 3),
        "longitude": round(ctx.lon, 3),
        "start_date": "2019-07-01",
        "end_date": "2024-07-31",
        "daily": "temperature_2m_max",
        "timezone": "UTC",
    }
    last_error: Exception | None = None
    values: list = []
    # Open-Meteo ограничивает частоту запросов: при пакетном сборе восьми
    # отелей подряд часть вызовов отбивается. Две повторные попытки с паузой
    # заметно снижают потери, а честное «нет данных» остаётся крайним случаем.
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=HTTP_TOOL_TIMEOUT_S) as client:
                resp = await client.get(_OPEN_METEO, params=params)
            resp.raise_for_status()
            values = [
                value
                for value in resp.json().get("daily", {}).get("temperature_2m_max") or []
                if value is not None
            ]
            last_error = None
            break
        except Exception as exc:  # noqa: BLE001 - внешний сервис
            last_error = exc
            await asyncio.sleep(1.5 * (attempt + 1))

    if last_error is not None:
        logger.warning("Open-Meteo недоступен: %s", last_error)
        return ToolResult(
            value=None,
            source="Open-Meteo",
            confidence=0.0,
            evidence={"error": str(last_error), "attempts": 3, "implemented": True},
        )

    july = [v for i, v in enumerate(values) if i % 365 < 31] or values
    if not july:
        return ToolResult(value=None, source="Open-Meteo", confidence=0.0, evidence={"error": "empty"})

    mean_max = round(sum(july) / len(july), 1)
    warm_days = sum(1 for v in july if v >= 20)
    return ToolResult(
        value={"mean_july_max_c": mean_max, "warm_days_july": warm_days},
        # Имя источника не должно меняться между успехом и ошибкой: иначе
        # «нет данных» не затирает прошлое значение, в БД копятся дубли,
        # и они выглядят как расхождение источников.
        source="Open-Meteo",
        confidence=0.85,
        evidence={
            "dataset": "ERA5",
            "period": "2019-2024",
            "observations": len(july),
            "definition": "средний суточный максимум в июле",
        },
    )


# ---------------------------------------------------------------------------
# Реестр инструментов
# ---------------------------------------------------------------------------
TOOL_REGISTRY = {
    "sunset_view": tool_sunset_view,
    "noise_score": tool_noise_score,
    "walk_to_sea": tool_walk_to_sea,
    "climate_summer": tool_climate_summer,
}

# Каноническое имя источника для каждого инструмента. Нужно, чтобы падение
# или таймаут инструмента не создавал в БД вторую строку с другим source:
# иначе «нет данных» и прошлый факт живут одновременно.
TOOL_SOURCES = {
    "sunset_view": "SRTM+OSM",
    "noise_score": "OSM",
    "walk_to_sea": "OSM roads + bathing water",
    "climate_summer": "Open-Meteo",
}


def get_tool(name: str):
    return TOOL_REGISTRY.get(name)


async def run_tool(name: str, ctx: HotelContext) -> ToolResult:
    """Запуск инструмента с таймаутом. Падение инструмента не рушит сбор."""
    tool = get_tool(name)
    if tool is None:
        return ToolResult(
            value=None,
            source="none",
            confidence=0.0,
            evidence={"error": f"инструмент '{name}' не зарегистрирован"},
        )
    source = TOOL_SOURCES.get(name, name)
    try:
        return await asyncio.wait_for(tool(ctx), timeout=GEO_TOOL_TIMEOUT_S)
    except asyncio.TimeoutError:
        logger.warning("инструмент %s превысил таймаут", name)
        return ToolResult(value=None, source=source, confidence=0.0, evidence={"error": "timeout"})
    except Exception as exc:  # noqa: BLE001 - инструмент внешний по отношению к графу
        logger.warning("инструмент %s упал: %s", name, exc)
        return ToolResult(value=None, source=source, confidence=0.0, evidence={"error": str(exc)})
