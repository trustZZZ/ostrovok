"""Оценка стороны главного фасада по ближайшей улице.

OSM не хранит сторону входа, но вход в городской отель почти всегда с улицы.
Поэтому направление от здания к ближайшей проезжей части используется как
оценка ориентации фасада.

Это именно оценка, а не факт: у отеля бывает несколько фасадов, а вход может
быть со двора. Поэтому значение сохраняется с пометкой о способе получения, а
расчёт вида на закат не отбрасывает результат молча — причина фиксируется в
evidence.
"""
from __future__ import annotations

import logging
import math

from shapely.geometry import Point

logger = logging.getLogger(__name__)

# Служебные проезды и пешеходные дорожки фасад не образуют.
SKIP_HIGHWAY = {
    "service",
    "track",
    "path",
    "footway",
    "cycleway",
    "steps",
    "bridleway",
    "corridor",
    "construction",
    "proposed",
}

# Дальше этого расстояния улица уже не «своя» — оценка фасада ненадёжна.
MAX_DISTANCE_M = 300.0

# Один градус по широте в метрах: для перевода расстояния из градусов.
METERS_PER_DEGREE = 111_000.0


def bearing_deg(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Азимут от первой точки ко второй, градусы от севера по часовой."""
    delta_lon = math.radians(lon2 - lon1)
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    x = math.sin(delta_lon) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(delta_lon)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def estimate_facade_azimuth(lon: float, lat: float, roads) -> tuple[float | None, dict]:
    """Азимут главного фасада по ближайшей улице.

    Возвращает пару (азимут | None, диагностика для evidence). None означает,
    что оценить не удалось: слоя нет, улиц рядом нет или они слишком далеко.
    """
    meta: dict = {"method": "направление на ближайшую улицу OSM", "available": False}
    if roads is None or getattr(roads, "empty", True):
        meta["reason"] = "слой дорог не загружен"
        return None, meta

    candidates = roads
    if "highway" in candidates.columns:
        candidates = candidates[~candidates["highway"].isin(SKIP_HIGHWAY)]
    # В слое смешаны линии, точки POI и полигоны. Проецировать точку можно
    # только на линейную геометрию, иначе shapely роняет весь расчёт.
    candidates = candidates[candidates.geometry.notna() & ~candidates.geometry.is_empty]
    candidates = candidates[candidates.geometry.geom_type.isin({"LineString", "MultiLineString"})]
    if candidates.empty:
        meta["reason"] = "в слое нет проезжих улиц"
        return None, meta

    point = Point(lon, lat)
    distances = candidates.geometry.distance(point)
    if distances.empty:
        meta["reason"] = "не удалось измерить расстояние до улиц"
        return None, meta

    nearest_index = distances.idxmin()
    distance_m = float(distances.loc[nearest_index]) * METERS_PER_DEGREE
    meta["distance_m"] = round(distance_m)

    if distance_m > MAX_DISTANCE_M:
        meta["reason"] = f"ближайшая улица в {distance_m:.0f} м — далеко для ориентира"
        return None, meta

    geometry = candidates.loc[nearest_index].geometry
    if geometry is None or geometry.is_empty:
        meta["reason"] = "у ближайшей улицы нет геометрии"
        return None, meta

    # Азимут считаем к ближайшей точке улицы, а не к середине сегмента:
    # иначе длинная улица даёт направление мимо отеля.
    try:
        street_point = geometry.interpolate(geometry.project(point))
    except Exception as exc:  # noqa: BLE001 - геометрия OSM бывает битой
        meta["reason"] = f"не удалось спроецировать точку на улицу: {exc}"
        return None, meta
    azimuth = bearing_deg(lon, lat, street_point.x, street_point.y)

    highway = candidates.loc[nearest_index].get("highway")
    meta.update(
        {
            "available": True,
            "highway": str(highway) if highway is not None else None,
            "note": "направление на ближайшую улицу; сторона входа не подтверждена",
        }
    )
    return round(azimuth, 1), meta
