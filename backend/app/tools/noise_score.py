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
        
        # Фильтруем по значению тега
        if tag_v and tag_k in layer.columns:
            subset = layer[layer[tag_k] == tag_v]
        else:
            subset = layer
        
        # Радиус в градусах (грубо: 1° ≈ 111 км)
        radius_deg = radius_m / 111_000
        nearby = subset[subset.geometry.within(hotel_geom.buffer(radius_deg))]
        
        contribution = weight * len(nearby)
        total += contribution
        breakdown[f"{tag_k}={tag_v}"] = {
            "count": len(nearby),
            "weight": weight,
            "contribution": round(contribution, 1),
        }
    
    score = min(100.0, total)
    
    # Confidence: выше, если учтено больше типов источников
    confidence = 0.9 if len(breakdown) >= 3 else (0.8 if len(breakdown) >= 1 else 0.6)
    
    return {
        "score": round(score, 1),
        "breakdown": breakdown,
        "confidence": confidence,
        "source": "OSM",
        "evidence": {
            "total_sources": len(breakdown),
            "max_radius_m": max(r for _, r in WEIGHTS.values()),
        },
    }
