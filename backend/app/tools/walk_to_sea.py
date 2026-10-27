"""Пешая доступность моря по реальной дорожной сети OSM.

Сеть дорог и вода берутся из локальных слоёв, собранных скриптом
``scripts/fetch_data.py``. Внешние API не используются: расчёт
воспроизводим и не зависит от доступности Overpass.

Маршрут — кратчайший путь по графу дорог, а не расстояние по прямой.
Если воды в радиусе нет или путь не найден, инструмент обязан сказать
«данных нет», а не подставить правдоподобное число.
"""
from __future__ import annotations

import logging
import math

import networkx as nx

logger = logging.getLogger(__name__)

WALK_SPEED_M_MIN = 80.0
MAJOR_ROADS = {
    "motorway", "motorway_link", "trunk", "trunk_link",
    "primary", "primary_link",
}
# Дороги, по которым нельзя идти пешком: они прерывают маршрут.
DRIVE_ONLY = {"motorway", "motorway_link", "trunk", "trunk_link"}


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def build_walk_graph(roads) -> nx.Graph:
    """Граф пеших связей из линий дорог. Узлы — концы сегментов."""
    graph = nx.Graph()
    if roads is None or getattr(roads, "empty", True):
        return graph

    for _, row in roads.iterrows():
        geometry = row.geometry
        if geometry is None or geometry.is_empty:
            continue
        highway = str(row.get("highway") or "")
        if highway in DRIVE_ONLY:
            continue
        parts = geometry.geoms if geometry.geom_type == "MultiLineString" else [geometry]
        for line in parts:
            coords = list(line.coords)
            for (lon1, lat1), (lon2, lat2) in zip(coords, coords[1:]):
                start = (round(lat1, 5), round(lon1, 5))
                end = (round(lat2, 5), round(lon2, 5))
                if start == end:
                    continue
                length = _haversine_m(lat1, lon1, lat2, lon2)
                graph.add_edge(start, end, length=length, major=highway in MAJOR_ROADS)
    return graph


def _nearest_node(graph: nx.Graph, lat: float, lon: float):
    best, best_distance = None, float("inf")
    for node in graph.nodes:
        distance = _haversine_m(lat, lon, node[0], node[1])
        if distance < best_distance:
            best, best_distance = node, distance
    return best, best_distance


def _water_point(coast, lat: float, lon: float):
    """Ближайшая точка воды и расстояние до неё по прямой."""
    if coast is None or getattr(coast, "empty", True):
        return None, None
    from shapely.geometry import Point
    from shapely.ops import nearest_points

    # Считаем расстояние до моря, а не до любой воды: река в центре города
    # не делает отель «у моря». Пляж в этом регионе — однозначный признак.
    if "kind" in coast.columns:
        coast = coast[coast["kind"] == "beach"]
        if coast.empty:
            return None, None

    origin = Point(lon, lat)
    distances = coast.geometry.distance(origin)
    if distances.empty or not (distances.min() < float("inf")):
        return None, None
    closest = coast.loc[distances.idxmin()].geometry
    point, _ = nearest_points(closest, origin)
    straight_m = _haversine_m(lat, lon, point.y, point.x)
    return (point.y, point.x), straight_m


def _elevation_penalty(graph, path, dem_path: str) -> float:
    """Штраф за подъём по DEM: 1 минута на каждые 10 м набора высоты."""
    if not dem_path or len(path) < 2:
        return 0.0
    try:
        import rasterio

        with rasterio.open(dem_path) as dem:
            elevations = []
            for lat, lon in path:
                row, col = dem.index(lon, lat)
                if 0 <= row < dem.height and 0 <= col < dem.width:
                    elevations.append(float(dem.read(1, window=((row, row + 1), (col, col + 1)))[0, 0]))
        climb = sum(
            max(0.0, elevations[i + 1] - elevations[i])
            for i in range(len(elevations) - 1)
        )
        return climb / 10.0
    except Exception as exc:  # noqa: BLE001 - DEM может отсутствовать
        logger.debug("не удалось учесть рельеф: %s", exc)
        return 0.0


def compute_walk_to_point(
    origin_lon: float,
    origin_lat: float,
    target_lon: float,
    target_lat: float,
    *,
    dem_path: str = "",
    roads_gdf=None,
    graph: nx.Graph | None = None,
    straight_m: float | None = None,
    source: str = "OSM roads",
    target_label: str = "места",
) -> dict:
    """Время пешком до произвольной точки по дорожной сети OSM.

    Тот же граф, скорость и штраф за рельеф, что и в ``compute_walk_to_sea``:
    расстояние до партнёрского места должно считаться так же, как до пляжа,
    иначе в выдаче окажутся две несопоставимые оценки «6 минут».

    ``graph`` позволяет переиспользовать уже построенный граф: пакетный сбор
    считает десятки маршрутов, и строить граф каждый раз — минуты впустую.
    """
    graph = graph if graph is not None else build_walk_graph(roads_gdf)
    if graph.number_of_nodes() == 0:
        return _no_data("нет дорожной сети для маршрута", straight_m, source)

    origin, origin_gap = _nearest_node(graph, origin_lat, origin_lon)
    target, target_gap = _nearest_node(graph, target_lat, target_lon)
    if origin is None or target is None:
        return _no_data("не удалось привязать точки к дорожной сети", straight_m, source)

    try:
        path = nx.shortest_path(graph, origin, target, weight="length")
        path_m = sum(graph[a][b]["length"] for a, b in zip(path, path[1:]))
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return _no_data(f"маршрут до {target_label} не найден в графе дорог", straight_m, source)

    path_m += origin_gap + target_gap
    penalty = _elevation_penalty(graph, path, dem_path)
    minutes = path_m / WALK_SPEED_M_MIN + penalty

    if minutes > 60:
        # Больше часа — это разрыв в дорожной сети или объезд, а не прогулка.
        # Возвращаем «нет данных» вместо правдоподобного числа.
        return _no_data(
            f"маршрут до {target_label} длиннее часа ({round(minutes)} мин) — "
            f"вероятен разрыв дорожной сети",
            straight_m,
            source,
        )

    crosses_highway = any(
        graph[a][b].get("major") for a, b in zip(path, path[1:])
    )

    return {
        "minutes": round(minutes, 1),
        "distance_m": round(path_m),
        "crosses_highway": crosses_highway,
        "confidence": 0.85,
        "source": source,
        "evidence": {
            "method": "shortest_path",
            "straight_line_m": round(straight_m) if straight_m else None,
            "detour_ratio": round(path_m / straight_m, 2) if straight_m else None,
            "path_nodes": len(path),
            "elevation_penalty_min": round(penalty, 1),
            "graph_nodes": graph.number_of_nodes(),
        },
    }


def compute_walk_to_sea(
    hotel_lon: float,
    hotel_lat: float,
    dem_path: str = "",
    coast_gdf=None,
    roads_gdf=None,
) -> dict:
    """Время пешком до ближайшей воды по дорожной сети OSM."""
    water_point, straight_m = _water_point(coast_gdf, hotel_lat, hotel_lon)
    if water_point is None:
        return _no_data("в радиусе нет воды в слое OSM")

    # Пешая доступность имеет смысл только для ближнего пляжа: 3 км по прямой
    # уже не «отель у моря», и любое число минут здесь вводило бы в заблуждение.
    if straight_m is not None and straight_m > 3000:
        return _no_data(
            f"ближайший пляж в {round(straight_m / 1000, 1)} км — это не пешая доступность",
            straight_m,
        )

    # _water_point возвращает (lat, lon) — порядок аргументов приводим к lon/lat.
    return compute_walk_to_point(
        hotel_lon,
        hotel_lat,
        water_point[1],
        water_point[0],
        dem_path=dem_path,
        roads_gdf=roads_gdf,
        straight_m=straight_m,
        source="OSM roads + bathing water",
        target_label="пляжа",
    )


def _no_data(
    reason: str,
    straight_m: float | None = None,
    source: str = "OSM roads + bathing water",
) -> dict:
    # source совпадает с успешным результатом намеренно: иначе «нет данных»
    # не затрёт устаревшее число от того же расчёта, и в БД останутся
    # две записи — старая неверная и новая пустая.
    return {
        "minutes": None,
        "distance_m": round(straight_m) if straight_m else None,
        "crosses_highway": None,
        "confidence": 0.0,
        "source": "OSM roads + bathing water",
        "evidence": {"error": reason},
    }
