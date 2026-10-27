"""Геометрия фасада: стены здания и азимут на ближайшую улицу.

Проверяем то, на чём стоит расчёт вида на закат: стены контура дают нормали
наружу (иначе закат «виден» из глухой стены), а оценка по улице честно
отказывается работать, когда ориентира нет.

Тесты синтетические: контур и улица строятся в метрах от точки отеля, поэтому
результат не зависит от содержимого data/buildings.gpkg.
"""
from __future__ import annotations

import math

import geopandas as gpd
import pytest
from shapely.geometry import LineString, Polygon

from app.tools.facade import (
    METERS_PER_DEGREE,
    angular_difference,
    building_wall_azimuths,
    estimate_facade_azimuth,
)

LAT = 54.71
LON = 20.51
COS_LAT = math.cos(math.radians(LAT))


def meters_to_deg_lon(meters: float) -> float:
    return meters / (METERS_PER_DEGREE * COS_LAT)


def meters_to_deg_lat(meters: float) -> float:
    return meters / METERS_PER_DEGREE


def square_around_hotel(size_m: float = 10.0) -> Polygon:
    """Квадрат с отелем в центре: четыре стены по 10 м."""
    half_lat = meters_to_deg_lat(size_m) / 2
    half_lon = meters_to_deg_lon(size_m) / 2
    return Polygon(
        [
            (LON - half_lon, LAT - half_lat),
            (LON + half_lon, LAT - half_lat),
            (LON + half_lon, LAT + half_lat),
            (LON - half_lon, LAT + half_lat),
        ]
    )


def buildings_with(geometry) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame({"osm_id": [1], "geometry": [geometry]}, crs="EPSG:4326")


def roads_with(geometry, highway: str = "residential") -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame({"highway": [highway], "geometry": [geometry]}, crs="EPSG:4326")


# --- стены здания ---------------------------------------------------------


def test_square_building_gives_four_outward_walls():
    walls = building_wall_azimuths(buildings_with(square_around_hotel()), LON, LAT)
    assert len(walls) == 4

    expected = (0.0, 90.0, 180.0, 270.0)
    for wall in walls:
        # Нормаль наружу, а не внутрь: иначе закат «виден» сквозь стену.
        assert min(angular_difference(wall["azimuth"], target) for target in expected) < 2.0
        assert wall["length_m"] == pytest.approx(10.0, abs=1.0)


def test_walls_are_merged_by_direction():
    """Излом контура на несколько градусов — всё ещё одна стена."""
    dlat = meters_to_deg_lat(10.0)
    dlon = meters_to_deg_lon(10.0)
    # Пятиугольник: южная стена с небольшим изломом посередине.
    polygon = Polygon(
        [
            (LON - dlon, LAT - dlat),
            (LON, LAT - dlat * 1.02),
            (LON + dlon, LAT - dlat),
            (LON + dlon, LAT + dlat),
            (LON - dlon, LAT + dlat),
        ]
    )
    walls = building_wall_azimuths(buildings_with(polygon), LON, LAT)
    assert len(walls) == 4


def test_missing_building_contour_returns_no_walls():
    assert building_wall_azimuths(None, LON, LAT) == []
    assert building_wall_azimuths(buildings_with(LineString([(LON, LAT), (LON + 0.001, LAT)])), LON, LAT) == []


def test_hotel_outside_contour_returns_no_walls():
    far_away = Polygon(
        [
            (LON + 0.01, LAT),
            (LON + 0.0102, LAT),
            (LON + 0.0102, LAT + 0.0002),
            (LON + 0.01, LAT + 0.0002),
        ]
    )
    assert building_wall_azimuths(buildings_with(far_away), LON, LAT) == []


# --- фасад по ближайшей улице --------------------------------------------


def test_facade_follows_nearest_street():
    street = LineString(
        [
            (LON + meters_to_deg_lon(25), LAT - meters_to_deg_lat(40)),
            (LON + meters_to_deg_lon(25), LAT + meters_to_deg_lat(40)),
        ]
    )
    azimuth, meta = estimate_facade_azimuth(LON, LAT, roads_with(street))
    assert meta["available"] is True
    assert azimuth == pytest.approx(90.0, abs=2.0)
    assert meta["highway"] == "residential"


def test_footways_are_not_a_facade_reference():
    street = LineString(
        [
            (LON + meters_to_deg_lon(10), LAT - meters_to_deg_lat(40)),
            (LON + meters_to_deg_lon(10), LAT + meters_to_deg_lat(40)),
        ]
    )
    azimuth, meta = estimate_facade_azimuth(LON, LAT, roads_with(street, highway="footway"))
    assert azimuth is None
    assert meta["available"] is False
    assert "проезжих улиц" in meta["reason"]


def test_missing_road_layer_is_reported_not_guessed():
    azimuth, meta = estimate_facade_azimuth(LON, LAT, None)
    assert azimuth is None
    assert meta["available"] is False
    assert "не загружен" in meta["reason"]


def test_street_too_far_away_is_not_a_landmark():
    street = LineString(
        [
            (LON + meters_to_deg_lon(500), LAT - meters_to_deg_lat(40)),
            (LON + meters_to_deg_lon(500), LAT + meters_to_deg_lat(40)),
        ]
    )
    azimuth, meta = estimate_facade_azimuth(LON, LAT, roads_with(street))
    assert azimuth is None
    assert meta["available"] is False
    assert "далеко" in meta["reason"]


# --- утилиты --------------------------------------------------------------


def test_angular_difference_wraps_around_north():
    assert angular_difference(350.0, 10.0) == pytest.approx(20.0)
    assert angular_difference(10.0, 350.0) == pytest.approx(20.0)
    assert angular_difference(0.0, 180.0) == pytest.approx(180.0)
    assert angular_difference(90.0, 90.0) == pytest.approx(0.0)
