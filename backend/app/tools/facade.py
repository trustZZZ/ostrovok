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


def angular_difference(first: float, second: float) -> float:
    """Минимальный угол между двумя азимутами, градусы (0..180)."""
    return abs((first - second + 180.0) % 360.0 - 180.0)


# --- Стены здания ---------------------------------------------------------
# Короче этого ребро не стена, а шум упрощения контура.
MIN_WALL_LENGTH_M = 3.0
# Рёбра с близкими нормалями — одна стена: так излом контура на 10° не
# превращается в отдельный «фасад».
WALL_GROUP_DEG = 20.0
# Точка-проба, которой проверяется, куда смотрит нормаль.
PROBE_DISTANCE_M = 1.5


def _offset_point(lon: float, lat: float, azimuth_deg: float, meters: float) -> Point:
    """Точка на расстоянии ``meters`` по азимуту."""
    azimuth = math.radians(azimuth_deg)
    delta_lat = (meters * math.cos(azimuth)) / METERS_PER_DEGREE
    delta_lon = (meters * math.sin(azimuth)) / (METERS_PER_DEGREE * math.cos(math.radians(lat)))
    return Point(lon + delta_lon, lat + delta_lat)


def building_wall_azimuths(buildings_gdf, lon: float, lat: float) -> list[dict]:
    """Направления наружных стен здания, в котором стоит отель.

    Направление на ближайшую улицу — только оценка входа. Контур здания из
    OSM — факт: у прямоугольного дома стены смотрят в четыре стороны, и закат
    виден из западных номеров даже тогда, когда главный фасад смотрит на юг.
    Поэтому вид на закат проверяется по всем стенам, а не по одной.

    Возвращает список ``{"azimuth": градусы, "length_m": метры}``, где
    ``azimuth`` — направление нормали наружу. Пустой список означает, что
    контура здания в данных нет и модель стен неприменима.
    """
    if buildings_gdf is None or getattr(buildings_gdf, "empty", True):
        return []

    point = Point(lon, lat)
    try:
        matches = buildings_gdf[buildings_gdf.geometry.contains(point)]
    except Exception as exc:  # noqa: BLE001 - геометрия OSM бывает битой
        logger.warning("не удалось найти контур здания: %s", exc)
        return []
    if matches.empty:
        return []

    geometry = matches.iloc[0].geometry
    if geometry is None or geometry.is_empty:
        return []
    if geometry.geom_type == "MultiPolygon":
        parts = [part for part in geometry.geoms if part.contains(point)]
        if not parts:
            return []
        geometry = parts[0]

    cos_lat = math.cos(math.radians(lat))
    walls: list[dict] = []
    coordinates = list(geometry.exterior.coords)
    for (x1, y1), (x2, y2) in zip(coordinates, coordinates[1:]):
        length_m = math.hypot((x2 - x1) * METERS_PER_DEGREE * cos_lat, (y2 - y1) * METERS_PER_DEGREE)
        if length_m < MIN_WALL_LENGTH_M:
            continue
        along = bearing_deg(x1, y1, x2, y2)
        mid_lon, mid_lat = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        # Нормаль наружу — та из двух, что уводит пробную точку за контур.
        for candidate in ((along + 90.0) % 360.0, (along - 90.0) % 360.0):
            if not geometry.contains(_offset_point(mid_lon, mid_lat, candidate, PROBE_DISTANCE_M)):
                walls.append({"azimuth": candidate, "length_m": length_m})
                break
    return _merge_walls(walls)


def _merge_walls(walls: list[dict]) -> list[dict]:
    """Складывает рёбра одного направления в одну стену."""
    groups: list[dict] = []
    for wall in walls:
        radians = math.radians(wall["azimuth"])
        for group in groups:
            if angular_difference(group["azimuth"], wall["azimuth"]) > WALL_GROUP_DEG:
                continue
            # Среднее взвешено длиной: иначе короткий излом перевешивает
            # длинную стену и направление уезжает.
            group["sin"] += math.sin(radians) * wall["length_m"]
            group["cos"] += math.cos(radians) * wall["length_m"]
            group["length_m"] += wall["length_m"]
            group["azimuth"] = (math.degrees(math.atan2(group["sin"], group["cos"])) + 360.0) % 360.0
            break
        else:
            groups.append(
                {
                    "azimuth": wall["azimuth"],
                    "length_m": wall["length_m"],
                    "sin": math.sin(radians) * wall["length_m"],
                    "cos": math.cos(radians) * wall["length_m"],
                }
            )
    return [
        {"azimuth": round(group["azimuth"], 1), "length_m": round(group["length_m"], 1)}
        for group in groups
    ]
