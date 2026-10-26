"""
Шум 0–100. Веса источников (OSM-теги):
- highway=motorway/trunk: 10 в радиусе 200м
- highway=primary/secondary: 6 в радиусе 150м
- highway=residential: 2 в радиусе 100м
- railway=rail: 7 в радиусе 300м
- amenity=bar/nightclub: 8 в радиусе 150м
Суммируем, нормализуем в 0–100.
"""
import geopandas as gpd
from shapely.geometry import Point

WEIGHTS = {
    ("highway", "motorway"): (10, 200),
    ("highway", "trunk"): (10, 200),
    ("highway", "primary"): (6, 150),
    ("highway", "secondary"): (6, 150),
    ("highway", "residential"): (2, 100),
    ("railway", "rail"): (7, 300),
    ("amenity", "bar"): (8, 150),
    ("amenity", "nightclub"): (10, 200),
}


def compute_noise_score(
    hotel_geom: Point,
    osm_layers: dict[str, gpd.GeoDataFrame],
) -> dict:
    """
    Вычисляет уровень шума 0-100 для отеля.
    
    Args:
        hotel_geom: Точка отеля (lon, lat)
        osm_layers: Словарь GeoDataFrame по тегам OSM
    
    Returns:
        dict с score, breakdown, confidence, source
    """
    total = 0.0
    breakdown = {}

    for (tag_k, tag_v), (weight, radius_m) in WEIGHTS.items():
        layer = osm_layers.get(tag_k)
        if layer is None:
            continue

        subset = layer[layer[tag_k] == tag_v] if tag_v and tag_k in layer.columns else layer
        if subset.empty:
            continue

        # Радиус в градусах (грубо: 1° ≈ 111 км). Берём пересечение, а не
        # вхождение целиком: дорога, проходящая рядом, тоже создаёт шум.
        radius_deg = radius_m / 111_000.0
        nearby = subset[subset.geometry.intersects(hotel_geom.buffer(radius_deg))]
        if nearby.empty:
            continue

        # Затухание по расстоянию: объект у самого отеля весит больше.
        contribution = 0.0
        for geometry in nearby.geometry:
            distance_m = geometry.distance(hotel_geom) * 111_000.0
            ratio = min(1.0, distance_m / radius_m)
            contribution += weight * (1.0 - ratio)

        total += contribution
        breakdown[f"{tag_k}={tag_v}"] = {
            "count": int(len(nearby)),
            "weight": weight,
            "radius_m": radius_m,
            "contribution": round(contribution, 1),
        }

    score = min(100.0, total)

    if not breakdown:
        # Слоя нет или рядом ничего не найдено: это отсутствие данных,
        # а не «идеальная тишина». Ноль без источников не выдаём за факт.
        return {
            "score": None,
            "level": "нет данных",
            "breakdown": {},
            "confidence": 0.0,
            "source": "OSM",
            "evidence": {"reason": "нет слоёв шума или объектов рядом"},
        }

    level = "Тихо" if score < 25 else ("Умеренно" if score < 55 else "Шумно")
    confidence = 0.85 if len(breakdown) >= 3 else 0.7

    return {
        "score": round(score, 1),
        "level": level,
        "breakdown": breakdown,
        "confidence": confidence,
        "source": "OSM",
        "evidence": {
            "total_sources": len(breakdown),
            "max_radius_m": max(r for _, r in WEIGHTS.values()),
            "model": "линейное затухание внутри радиуса",
        },
    }
