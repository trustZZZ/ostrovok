"""Вид на закат: рельеф (SRTM) + высоты зданий (OSM).

Алгоритм:
1. Азимут заката считается для каждого проверяемого месяца отдельно
   (положение солнца меняется по сезону).
2. От отеля строится луч на 10 км в сторону заката.
3. Вдоль луча сэмплируется DEM, проверяется перекрытие линии визирования.
4. Здания OSM в буфере луча проверяются на перекрытие с учётом этажа.
5. Перебором этажей находится минимальный, с которого горизонт открыт.

Высота наблюдателя = абсолютная высота площадки (из DEM) + этаж * 3 м.
Высота зданий отсчитывается от земли, поэтому сравнивается с этажом.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from typing import Optional

import geopandas as gpd
import numpy as np
import rasterio
from pysolar.solar import get_azimuth
from shapely.geometry import LineString, Point

FLOOR_HEIGHT_M = 3.0
RAY_LENGTH_M = 10_000.0
SAMPLE_STEP_M = 30.0
DEFAULT_BUILDING_HEIGHT_M = 9.0
# Расстояние до горизонта, м: d = 3570·√h (радиус Земли + рефракция).
HORIZON_COEF_M = 3570.0

# Из окна виден сектор ±90° от нормали фасада. Если закат смещён сильнее,
# он оказывается за стеной, и проверять рельеф с застройкой бессмысленно.
FACADE_TOLERANCE_DEG = 90.0


def angular_difference(first: float, second: float) -> float:
    """Минимальный угол между двумя азимутами, градусы (0..180)."""
    return abs((first - second + 180.0) % 360.0 - 180.0)


def block_reason(visible: bool, checked_months: int, facade_azimuth: float | None) -> str | None:
    """Почему закат не виден: окна не туда или вид загорожен.

    Разные причины требуют разных действий: в первом случае нужен номер на
    другой стороне, во втором — этаж повыше.
    """
    if visible:
        return None
    if facade_azimuth is not None and checked_months == 0:
        return "facade_facing_away"
    return "obstructed"


@dataclass
class SunsetViewResult:
    visible: bool
    from_floor: Optional[int]
    months: list[int]
    azimuth_deg: float
    confidence: float
    evidence: dict


@lru_cache(maxsize=2)
def _read_dem(dem_path: str):
    """DEM читается один раз на процесс: раньше он читался на каждую точку."""
    with rasterio.open(dem_path) as dem:
        return dem.read(1).astype("float32"), dem.transform, dem.crs, dem.nodata


def _elevation_at(lon: float, lat: float) -> float | None:
    """Абсолютная высота точки по DEM."""
    if not _dem_ready():
        return None
    data, transform, _, nodata = _read_dem(_dem_path())
    col = int((lon - transform.c) / transform.a)
    row = int((lat - transform.f) / transform.e)
    if not (0 <= row < data.shape[0] and 0 <= col < data.shape[1]):
        return None
    value = float(data[row, col])
    if nodata is not None and value == float(nodata):
        return None
    return value


_DEM_PATH = ""


def _dem_path() -> str:
    return _DEM_PATH


def _dem_ready() -> bool:
    try:
        return bool(_DEM_PATH) and _read_dem(_DEM_PATH) is not None
    except Exception:  # noqa: BLE001 - файла может не быть
        return False


def compute_sunset_view(
    hotel_lon: float,
    hotel_lat: float,
    total_floors: int,
    dem_path: str,
    buildings_gdf: gpd.GeoDataFrame | None,
    check_months: list[int] | None = None,
    facade_azimuth: float | None = None,
) -> SunsetViewResult:
    """Считает вид на закат с учётом сезона, рельефа, зданий и стороны фасада.

    ``facade_azimuth`` — оценка ориентации главного фасада в градусах от севера.
    Если она известна и закат оказывается вне сектора обзора из окна, месяц
    не засчитывается: окна смотрят в другую сторону. Когда оценки нет, расчёт
    выполняется как раньше, но уверенность снижается — сторона фасада
    не проверена.
    """
    global _DEM_PATH
    _DEM_PATH = dem_path
    months_to_check = check_months or [4, 5, 6, 7, 8]

    if buildings_gdf is None:
        buildings_gdf = gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    observer = Point(hotel_lon, hotel_lat)
    # Своё здание не затеняет вид из собственного окна: точка отеля лежит
    # внутри его контура, и луч начинается уже за стеной наблюдателя.
    own_building = bool(buildings_gdf.geometry.contains(observer).any()) if not buildings_gdf.empty else False
    ray_buildings = buildings_gdf[~buildings_gdf.geometry.contains(observer)] if own_building else buildings_gdf
    hotel_elevation = _elevation_at(hotel_lon, hotel_lat)
    dem_ok = hotel_elevation is not None
    base_elevation = hotel_elevation or 0.0

    visible_months: list[int] = []
    per_month: dict[str, int | None] = {}
    min_floor: int | None = None
    azimuths: list[float] = []
    buildings_on_ray = 0
    facade_offsets: dict[str, float] = {}
    last_ray: LineString | None = None
    checked_months = 0

    for month in months_to_check:
        azimuth = sun_azimuth_deg(hotel_lat, hotel_lon, month)
        azimuths.append(azimuth)

        # Сначала проверяем, смотрят ли окна вообще в сторону заката: иначе
        # «закат не виден» не отличить от «окна выходят на восток».
        faces_sunset = None
        if facade_azimuth is not None:
            offset = angular_difference(facade_azimuth, azimuth)
            facade_offsets[str(month)] = round(offset, 1)
            faces_sunset = offset <= FACADE_TOLERANCE_DEG

        if faces_sunset is False:
            per_month[str(month)] = None
            continue

        checked_months += 1
        ray = build_ray(observer, azimuth, distance_m=RAY_LENGTH_M)
        last_ray = ray

        if not ray_buildings.empty:
            on_ray = ray_buildings[ray_buildings.geometry.intersects(ray.buffer(0.00005))]
            buildings_on_ray = max(buildings_on_ray, int(on_ray.shape[0]))

        terrain_blocks = check_terrain_dem(ray, dem_path) if dem_ok else (lambda _height: False)
        buildings_block = check_buildings(ray, ray_buildings)

        floor_found = None
        for floor in range(1, total_floors + 1):
            observer_height = base_elevation + floor * FLOOR_HEIGHT_M
            if not terrain_blocks(observer_height) and not buildings_block(floor * FLOOR_HEIGHT_M):
                floor_found = floor
                break

        per_month[str(month)] = floor_found
        if floor_found is not None:
            visible_months.append(month)
            min_floor = floor_found if min_floor is None else min(min_floor, floor_found)

    buildings_in_buffer = 0
    if not buildings_gdf.empty:
        buildings_in_buffer = int(
            buildings_gdf[buildings_gdf.geometry.intersects(observer.buffer(0.01))].shape[0]
        )

    # Сколько зданий вокруг реально имеют высоту из OSM: без этого нельзя
    # отличить расчёт по настоящей застройке от расчёта по константе 9 м.
    buildings_with_height = _count_known_height(buildings_gdf, observer)

    confidence = _confidence(dem_ok, buildings_in_buffer, buildings_gdf.empty)
    if facade_azimuth is None:
        # Без стороны фасада вывод «закат виден» может быть неверным: окна
        # могли выходить на восток. Уверенность снижается, но результат
        # не отбрасывается — иначе пропадали бы отели без данных OSM.
        confidence = round(confidence * 0.9, 2)

    # Диагностика: максимальная высота рельефа вдоль луча — по ней видно,
    # что именно перекрывает вид (дюны/холм или застройка).
    terrain_max = None
    if dem_ok and last_ray is not None:
        elevations, _ = _sample_ray(last_ray)
        terrain_max = round(float(np.max(elevations)), 1)

    return SunsetViewResult(
        visible=bool(visible_months),
        from_floor=min_floor,
        months=visible_months,
        azimuth_deg=round(float(np.mean(azimuths)), 1) if azimuths else 0.0,
        confidence=confidence,
        evidence={
            "method": "raycasting DEM + OSM buildings",
            "dem_available": dem_ok,
            "hotel_elevation_m": round(base_elevation, 1) if dem_ok else None,
            "dem_resolution_m": 90,
            "terrain_max_on_ray_m": terrain_max,
            "buildings_in_buffer": buildings_in_buffer,
            "buildings_on_ray": buildings_on_ray,
            "buildings_total": int(len(buildings_gdf)),
            # Здание отеля исключено из проверки луча — иначе оно затеняло бы
            # вид из собственного окна.
            "own_building_excluded": own_building,
            "buildings_with_known_height": buildings_with_height,
            "building_height_source": (
                "OSM PBF building:levels / height"
                if buildings_with_height
                else f"высота неизвестна — {DEFAULT_BUILDING_HEIGHT_M:.0f} м по умолчанию"
            ),
            "floors_by_month": per_month,
            "ray_length_km": RAY_LENGTH_M / 1000.0,
            "los_model": "линия визирования к горизонту на 0 м",
            "facade_azimuth_deg": facade_azimuth,
            "facade_tolerance_deg": FACADE_TOLERANCE_DEG,
            "facade_angle_to_sunset": facade_offsets,
            "facade_source": (
                "оценка по ближайшей улице OSM; сторона входа не подтверждена"
                if facade_azimuth is not None
                else "неизвестна — сторона фасада не учитывалась"
            ),
            "block_reason": block_reason(bool(visible_months), checked_months, facade_azimuth),
        },
    )


def _count_known_height(buildings_gdf: gpd.GeoDataFrame, observer: Point) -> int:
    """Здания в радиусе ~1 км, у которых высота известна из OSM."""
    if buildings_gdf is None or buildings_gdf.empty:
        return 0
    columns = [column for column in ("levels", "height") if column in buildings_gdf.columns]
    if not columns:
        return 0
    nearby = buildings_gdf[buildings_gdf.geometry.intersects(observer.buffer(0.01))]
    if nearby.empty:
        return 0
    return int(nearby[columns].notna().any(axis=1).sum())


def _confidence(dem_ok: bool, buildings_in_buffer: int, no_buildings: bool) -> float:
    """Уверенность зависит от наличия рельефа и детализации застройки."""
    if not dem_ok:
        return 0.2
    if no_buildings:
        return 0.45
    if buildings_in_buffer > 50:
        return 0.7
    return 0.8


def sun_azimuth_deg(lat: float, lon: float, month: int) -> float:
    """Азимут заката для 21-го числа месяца (~18:00 UTC)."""
    when = datetime(2026, month, 21, 18, 0, 0, tzinfo=timezone.utc)
    return float(get_azimuth(lat, lon, when))


def build_ray(origin: Point, azimuth_deg: float, distance_m: float) -> LineString:
    """Луч от точки в направлении азимута. Плоская аппроксимация до 10 км."""
    azimuth = math.radians(azimuth_deg)
    lat, lon = origin.y, origin.x
    d_lat = (distance_m * math.cos(azimuth)) / 111_000.0
    d_lon = (distance_m * math.sin(azimuth)) / (111_000.0 * math.cos(math.radians(lat)))
    return LineString([origin, Point(lon + d_lon, lat + d_lat)])


def _sample_ray(ray: LineString) -> tuple[np.ndarray, np.ndarray]:
    """Высоты рельефа и расстояния вдоль луча (DEM читается один раз)."""
    # Луч строится сразу в метрах (см. build_ray), поэтому его длина равна
    # RAY_LENGTH_M. Пересчёт через градусы завышал дистанцию в 1.5–1.9 раза
    # для западных азимутов и давал ложные перекрытия.
    length_m = RAY_LENGTH_M
    count = max(2, int(length_m / SAMPLE_STEP_M))
    fractions = np.linspace(0.0, 1.0, count)
    distances = fractions * length_m

    if not _dem_ready():
        return np.zeros(count, dtype="float32"), distances

    data, transform, _, nodata = _read_dem(_dem_path())
    elevations = np.zeros(count, dtype="float32")
    for index, fraction in enumerate(fractions):
        point = ray.interpolate(fraction, normalized=True)
        col = int((point.x - transform.c) / transform.a)
        row = int((point.y - transform.f) / transform.e)
        if 0 <= row < data.shape[0] and 0 <= col < data.shape[1]:
            value = float(data[row, col])
            if nodata is None or value != float(nodata):
                elevations[index] = value
    return elevations, distances


def check_terrain_dem(ray: LineString, dem_path: str):
    """Функция(абсолютная_высота_наблюдателя) -> перекрыт ли горизонт рельефом."""
    elevations, distances = _sample_ray(ray)
    max_distance = distances[-1] if len(distances) else 0.0

    def is_blocked(observer_height: float) -> bool:
        if max_distance <= 0:
            return False
        # Расстояние до горизонта для наблюдателя на высоте h:
        # d ≈ 3.57·√h км (с учётом рефракции). Линия визирования идёт
        # к настоящему горизонту, а не к высоте 0 на фиксированных 10 км:
        # иначе рельеф вдали ложно «перекрывает» вид с любого этажа.
        horizon_m = HORIZON_COEF_M * math.sqrt(max(observer_height, 0.5))
        line_of_sight = observer_height * (1.0 - distances / horizon_m)
        mask = distances < horizon_m
        if not mask.any():
            return False
        return bool(np.any(elevations[mask] > line_of_sight[mask]))

    return is_blocked


def check_buildings(ray: LineString, buildings_gdf: gpd.GeoDataFrame):
    """Функция(высота_наблюдателя_над_землёй) -> перекрыт ли вид зданиями."""
    if buildings_gdf is None or buildings_gdf.empty:
        return lambda _height: False

    # Буфер узкий (≈5 м): более широкая полоса приписывала перекрытие
    # зданиям, стоящим в стороне от линии визирования.
    nearby = buildings_gdf[buildings_gdf.geometry.intersects(ray.buffer(0.00005))]
    if nearby.empty:
        return lambda _height: False

    length_m = RAY_LENGTH_M
    prepared: list[tuple[float, float]] = []
    for _, row in nearby.iterrows():
        geometry = row.geometry
        if geometry is None or geometry.is_empty:
            continue
        # Доля вдоль луча (0..1) → расстояние в метрах.
        fraction = ray.project(geometry.centroid) / max(ray.length, 1e-12)
        distance_m = fraction * length_m
        prepared.append((distance_m, _building_height(row)))

    def is_blocked(observer_height: float) -> bool:
        horizon_m = HORIZON_COEF_M * math.sqrt(max(observer_height, 0.5))
        limit_m = min(length_m, horizon_m)
        for distance_m, height in prepared:
            if distance_m <= 0 or distance_m >= limit_m:
                continue
            line_of_sight = observer_height * (1.0 - distance_m / horizon_m)
            if height > line_of_sight:
                return True
        return False

    return is_blocked


def _building_height(row) -> float:
    """Высота здания: levels -> height -> значение по умолчанию."""
    levels = row.get("levels") if hasattr(row, "get") else None
    if levels is not None and not (isinstance(levels, float) and math.isnan(levels)):
        try:
            return float(levels) * FLOOR_HEIGHT_M
        except (TypeError, ValueError):
            pass

    height = row.get("height") if hasattr(row, "get") else None
    if height is not None and not (isinstance(height, float) and math.isnan(height)):
        try:
            return float(height)
        except (TypeError, ValueError):
            pass

    return DEFAULT_BUILDING_HEIGHT_M
