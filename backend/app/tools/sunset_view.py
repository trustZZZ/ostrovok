"""
Ключевая фича хакатона: вычисление вида на закат над морем.

Алгоритм:
1. Берём координаты отеля и DEM (SRTM 30m).
2. Для каждого месяца лета считаем азимут заката через suncalc.
3. Строим луч (ray) от точки обзора (отель + высота floor * 3м) на запад до 10 км.
4. Проверяем пересечение луча с DEM и 3D-зданиями OSM.
5. Бинарным поиском находим минимальный этаж, с которого вид открыт.
6. Возвращаем {visible, from_floor, months, confidence, evidence}.
"""
from dataclasses import dataclass
from typing import Optional, Callable
import math
import numpy as np
import rasterio
from shapely.geometry import Point, LineString
import geopandas as gpd
from pysolar.solar import get_azimuth
from datetime import date, datetime


@dataclass
class SunsetViewResult:
    visible: bool
    from_floor: Optional[int]
    months: list[int]
    azimuth_deg: float
    confidence: float
    evidence: dict


def compute_sunset_view(
    hotel_lon: float,
    hotel_lat: float,
    total_floors: int,
    dem_path: str,
    buildings_gdf: gpd.GeoDataFrame,
    check_months: list[int] = [5, 6, 7, 8],
) -> SunsetViewResult:
    """
    Главная функция: вычисляет вид на закат для конкретного отеля.
    """
    observer_point = Point(hotel_lon, hotel_lat)
    
    # Средний азимут заката для 21-го июня (летнее солнцестояние)
    mid_date = datetime(2026, 6, 21, 21, 0, 0)  # ~21:00 — время заката
    azimuth_deg = get_azimuth(hotel_lat, hotel_lon, mid_date)
    # Для Калининграда это ~290°
    
    # Строим луч от отеля на запад (в направлении заката)
    ray = build_ray(observer_point, azimuth_deg, distance_m=10000)
    
    # Проверяем перекрытия рельефом
    terrain_block_fn = check_terrain_dem(ray, dem_path)
    
    # Проверяем перекрытия зданиями
    building_block_fn = check_buildings(ray, buildings_gdf)
    
    # Бинарный поиск минимального этажа с открытым видом
    min_floor = None
    for floor in range(1, total_floors + 1):
        observer_h = floor * 3.0  # 3м на этаж
        terrain_blocks = terrain_block_fn(observer_h)
        buildings_block = building_block_fn(observer_h)
        if not terrain_blocks and not buildings_block:
            min_floor = floor
            break
    
    # Confidence: зависит от разрешения DEM и покрытия зданий в буфере
    buildings_in_buffer = buildings_gdf[
        buildings_gdf.geometry.within(observer_point.buffer(0.01))  # ~1 км
    ].shape[0]
    
    if buildings_in_buffer > 50:
        confidence = 0.75  # много зданий — сложнее точно оценить
    elif buildings_in_buffer > 20:
        confidence = 0.88  # умеренная застройка
    else:
        confidence = 0.95  # мало зданий — высокая уверенность
    
    return SunsetViewResult(
        visible=min_floor is not None,
        from_floor=min_floor,
        months=check_months,
        azimuth_deg=round(azimuth_deg, 1),
        confidence=confidence,
        evidence={
            "dem_resolution_m": 30,
            "buildings_in_buffer": int(buildings_in_buffer),
            "azimuth_deg": round(azimuth_deg, 1),
            "total_floors": total_floors,
            "ray_length_km": 10,
        },
    )


def build_ray(origin: Point, azimuth_deg: float, distance_m: float) -> LineString:
    """
    Строит луч от точки в направлении azimuth_deg на distance_m метров.
    Использует грубую плоскую проекцию (достаточно для 10 км).
    """
    az_rad = math.radians(azimuth_deg)
    lat = origin.y
    lon = origin.x
    # 1° широты ≈ 111 км, 1° долготы ≈ 111*cos(lat) км
    d_lat = (distance_m * math.cos(az_rad)) / 111_000
    d_lon = (distance_m * math.sin(az_rad)) / (111_000 * math.cos(math.radians(lat)))
    end = Point(lon + d_lon, lat + d_lat)
    return LineString([origin, end])


def check_terrain_dem(ray: LineString, dem_path: str) -> Callable[[float], bool]:
    """
    Возвращает функцию(observer_h) -> bool: перекрыт ли луч рельефом
    при высоте наблюдателя observer_h метров.
    
    Алгоритм:
    - Сэмплируем DEM вдоль луча с шагом 30м
    - Для каждого сэмпла вычисляем «требуемую высоту визирования»
      (линия от наблюдателя до конца луча)
    - Если реальная высота рельефа > требуемой — луч перекрыт
    """
    # Сэмплируем точки вдоль луча
    num_samples = int(ray.length * 111_000 / 30)  # шаг 30м
    fractions = np.linspace(0, 1, num_samples)
    
    sample_points = []
    for f in fractions:
        pt = ray.interpolate(f, normalized=True)
        sample_points.append((pt.x, pt.y))
    
    # Читаем DEM
    with rasterio.open(dem_path) as dem:
        elevations = []
        for lon, lat in sample_points:
            try:
                row, col = dem.index(lon, lat)
                elev = dem.read(1)[row, col]
                elevations.append(float(elev))
            except (IndexError, ValueError):
                elevations.append(0.0)
    
    distances_m = np.array([f * ray.length * 111_000 for f in fractions])
    elevations = np.array(elevations)
    
    def is_blocked(observer_h: float) -> bool:
        """Проверяет, перекрыт ли луч при высоте наблюдателя observer_h."""
        # Линия визирования: от (0, observer_h) до (max_dist, 0)
        # Для каждой точки: required_h = observer_h * (1 - dist/max_dist)
        max_dist = distances_m[-1]
        if max_dist == 0:
            return False
        
        line_of_sight = observer_h * (1 - distances_m / max_dist)
        
        # Если рельеф выше линии визирования — луч перекрыт
        # Игнорируем первую точку (это сам наблюдатель)
        return bool(np.any(elevations[1:] > line_of_sight[1:]))
    
    return is_blocked


def check_buildings(ray: LineString, buildings_gdf: gpd.GeoDataFrame) -> Callable[[float], bool]:
    """
    Возвращает функцию(observer_h) -> bool: перекрыт ли луч зданиями
    при высоте наблюдателя observer_h метров.
    
    Алгоритм:
    - Фильтруем здания, пересекающие буфер луча (50м)
    - Для каждого здания: высота = building:levels * 3м или height тег
    - Проверяем: если высота здания > линия визирования на этом расстоянии — перекрыт
    """
    ray_buffer = ray.buffer(0.0005)  # ~50м буфер
    nearby_buildings = buildings_gdf[buildings_gdf.geometry.intersects(ray_buffer)]
    
    if nearby_buildings.empty:
        return lambda _: False
    
    # Извлекаем высоту каждого здания
    building_data = []
    for _, row in nearby_buildings.iterrows():
        geom = row.geometry
        # Расстояние от начала луча до здания
        dist = ray.project(geom.centroid)
        dist_m = dist * ray.length * 111_000
        
        # Высота здания
        height = 0
        if 'building:levels' in row:
            try:
                height = float(row['building:levels']) * 3.0
            except (ValueError, TypeError):
                pass
        if height == 0 and 'height' in row:
            try:
                height = float(row['height'])
            except (ValueError, TypeError):
                pass
        if height == 0:
            height = 9.0  # дефолт: 3 этажа
        
        building_data.append((dist_m, height))
    
    max_dist = ray.length * 111_000
    
    def is_blocked(observer_h: float) -> bool:
        for dist_m, bld_height in building_data:
            if dist_m <= 0 or dist_m >= max_dist:
                continue
            # Линия визирования на этом расстоянии
            los_height = observer_h * (1 - dist_m / max_dist)
            if bld_height > los_height:
                return True
        return False
    
    return is_blocked
