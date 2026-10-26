"""
Сбор демо-данных для агентной системы Routely x Островок.

Источники:
  * Geofabrik — официальный экстракт Калининградской области (OSM).
    Overpass для этой задачи не годится: публичные зеркала отдают 429/502,
    а часть зеркал (например overpass.osm.ch) содержит только свою страну
    и молча вернёт пустоту.
  * PBF того же экстракта — единственный источник реальной высоты зданий:
    shapefile-выгрузка теряет теги building:levels и height.
  * SRTM (skadi tiles) — рельеф.

Что собирается:
  hotels.geojson        — отели региона
  buildings.gpkg        — здания вокруг отелей
  noise_sources.geojson — дороги, железная дорога, бары и кафе
  beaches.geojson       — пляжи и водоёмы (для расстояния до моря)
  dem.tif               — SRTM, обрезанный по bbox региона

Запуск (локальный Python не нужен):
    make data
"""
from __future__ import annotations

import gzip
import os
import re
import shutil
import sys
import zipfile

import geopandas as gpd
import httpx
import numpy as np
import pandas as pd
from shapely import wkb as shapely_wkb
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union

# Область, для которой нужны DEM и гео-слои (600x600 при 3 arcsec ~ 720 КБ).
CLIP_BOUNDS = (20.40, 54.65, 20.85, 55.15)

# Радиус сбора объектов вокруг отеля, метры.
OSM_RADIUS_M = 2200

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
os.makedirs(DATA_DIR, exist_ok=True)

WORK_DIR = "/tmp/geofabrik"
USER_AGENT = "RoutelyOstrovokHackathon/1.0 (hackathon)"

GEOFABRIK_URL = "https://download.geofabrik.de/russia/kaliningrad-latest-free.shp.zip"

# Тот же экстракт в формате PBF (~40 МБ). Shapefile-выгрузка Geofabrik не
# содержит building:levels и height, поэтому высоты зданий берутся только
# отсюда: без них луч заката сравнивает этаж с константой 9 м.
GEOFABRIK_PBF_URL = "https://download.geofabrik.de/russia/kaliningrad-latest.osm.pbf"
PBF_PATH = os.path.join(WORK_DIR, "kaliningrad-latest.osm.pbf")

# Реальные гостиницы Калининграда и Зеленоградска: osm_id, координаты и
# названия существуют в OSM, этажность при сборке перечитывается из PBF.
# Список фиксирован, чтобы демо-набор был воспроизводим: OSM меняется,
# а демо — нет. Значения floors здесь — снимок на момент составления списка,
# он используется только если PBF недоступен.
HOTELS = [
    {"osm_type": "way", "osm_id": 162622681, "name": "Crystal House", "lat": 54.71498, "lon": 20.51511, "floors": 9},
    {"osm_type": "way", "osm_id": 48817194, "name": "Калининград", "lat": 54.71233, "lon": 20.50902, "floors": 8},
    {"osm_type": "way", "osm_id": 558380773, "name": "Кайзерхоф", "lat": 54.70281, "lon": 20.51590, "floors": 7},
    {"osm_type": "way", "osm_id": 382545007, "name": "Парадокс", "lat": 54.96003, "lon": 20.48257, "floors": 5},
    {"osm_type": "way", "osm_id": 116133914, "name": "Royal Lions", "lat": 54.95766, "lon": 20.46341, "floors": 5},
    {"osm_type": "way", "osm_id": 115643344, "name": "Королева Луиза", "lat": 54.96123, "lon": 20.48860, "floors": 4},
    {"osm_type": "way", "osm_id": 115708035, "name": "Sambia", "lat": 54.96419, "lon": 20.48398, "floors": 4},
    {"osm_type": "way", "osm_id": 162948437, "name": "Замок «Нессельбек»", "lat": 54.79303, "lon": 20.53374, "floors": 2},
]

# Соответствие классов дорог из выгрузки Geofabrik тегам OSM highway.
ROAD_CLASSES = {
    "motorway", "trunk", "primary", "secondary", "tertiary",
    "motorway_link", "trunk_link", "primary_link", "residential",
    "unclassified", "living_street", "service",
}

POI_CLASSES = {"bar", "pub", "nightclub", "cafe", "restaurant", "biergarten"}


def _log(msg: str) -> None:
    print(msg, flush=True)


def _client(timeout: float = 180.0) -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=httpx.Timeout(timeout, connect=15.0),
        follow_redirects=True,
    )


# ---------------------------------------------------------------------------
# 1. Загрузка и распаковка экстракта
# ---------------------------------------------------------------------------
def download_extract() -> str:
    os.makedirs(WORK_DIR, exist_ok=True)
    archive = os.path.join(WORK_DIR, "kaliningrad.zip")
    if os.path.exists(archive) and os.path.getsize(archive) > 10 * 1024 * 1024:
        _log("Экстракт Geofabrik уже скачан, использую его.")
        return archive

    _log("Скачиваю экстракт OSM Калининградской области (~55 МБ)...")
    with _client() as client, client.stream("GET", GEOFABRIK_URL) as resp:
        resp.raise_for_status()
        with open(archive, "wb") as fh:
            for chunk in resp.iter_bytes(chunk_size=1 << 20):
                fh.write(chunk)
    _log(f"Скачано: {os.path.getsize(archive) / 1024 / 1024:.1f} МБ")
    return archive


def extract_layers(archive: str) -> str:
    target = os.path.join(WORK_DIR, "extract")
    if os.path.isdir(target) and os.listdir(target):
        return target
    _log("Распаковываю экстракт...")
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(target)
    return target


def read_layer(folder: str, layer: str) -> gpd.GeoDataFrame | None:
    path = os.path.join(folder, f"{layer}.shp")
    if not os.path.exists(path):
        _log(f"Слой {layer} отсутствует в выгрузке")
        return None
    try:
        # DBF в экстракте Geofabrik не всегда размечен как UTF-8: без явной
        # кодировки кириллические названия приходят испорченными.
        gdf = gpd.read_file(path, encoding="utf-8")
    except TypeError:
        gdf = gpd.read_file(path)
    return gdf if not gdf.empty else None


# ---------------------------------------------------------------------------
# 2. Обработка слоёв
# ---------------------------------------------------------------------------
def near_hotels_mask(gdf: gpd.GeoDataFrame) -> gpd.GeoSeries:
    """Маска объектов в радиусе OSM_RADIUS_M от любого отеля."""
    radius_deg = OSM_RADIUS_M / 111_000
    buffers = unary_union([Point(h["lon"], h["lat"]).buffer(radius_deg) for h in HOTELS])
    return gdf.geometry.intersects(buffers)


def prepare_buildings(folder: str) -> gpd.GeoDataFrame:
    gdf = read_layer(folder, "gis_osm_buildings_a_free_1")
    if gdf is None:
        return gpd.GeoDataFrame(columns=["osm_id", "levels", "height", "fclass", "geometry"], crs="EPSG:4326")

    gdf = gdf[near_hotels_mask(gdf)].copy()
    gdf = gdf[gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])]
    # Выгрузка Geofabrik не содержит building:levels, поэтому высота здания
    # неизвестна — инструмент подставит значение по умолчанию и отметит это.
    gdf["levels"] = np.nan
    gdf["height"] = np.nan
    gdf = gdf[["osm_id", "levels", "height", "fclass", "geometry"]]
    gdf["geometry"] = gdf.geometry.simplify(0.00002)
    return gdf.set_crs("EPSG:4326", allow_override=True)


def download_pbf() -> str | None:
    """Скачивает OSM PBF области. None, если источника или сети нет."""
    if os.path.exists(PBF_PATH) and os.path.getsize(PBF_PATH) > 1024 * 1024:
        _log("PBF уже скачан, использую его.")
        return PBF_PATH

    os.makedirs(WORK_DIR, exist_ok=True)
    _log("Скачиваю OSM PBF Калининградской области (~40 МБ)...")
    try:
        with _client() as client, client.stream("GET", GEOFABRIK_PBF_URL) as resp:
            resp.raise_for_status()
            with open(PBF_PATH, "wb") as fh:
                for chunk in resp.iter_bytes(chunk_size=1 << 20):
                    fh.write(chunk)
    except Exception as exc:  # noqa: BLE001 - источник внешний
        # Недокачанный файл нельзя оставлять: следующий запуск принял бы его
        # за готовый кэш и упал бы на разборе.
        if os.path.exists(PBF_PATH):
            os.remove(PBF_PATH)
        _log(f"PBF не скачан: {exc}")
        return None

    _log(f"Скачано: {os.path.getsize(PBF_PATH) / 1024 / 1024:.1f} МБ")
    return PBF_PATH


def _tag_number(value) -> float | None:
    """«12», «12.5», «12,5», «12 m» -> число. None, если тег не разобрать."""
    if value is None:
        return None
    text = str(value).replace(",", ".").strip()
    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group())
    except ValueError:
        return None


def _floors_from_tags(tags: dict) -> int | None:
    """Этажность из тегов OSM: building:levels, иначе height / 3 м."""
    levels = _tag_number(tags.get("building:levels") or tags.get("levels"))
    if levels:
        return max(1, int(round(levels)))
    height = _tag_number(tags.get("height") or tags.get("building:height"))
    if height:
        return max(1, int(round(height / 3.0)))
    return None


def _hotel_address(tags: dict) -> str | None:
    street = tags.get("addr:street")
    number = tags.get("addr:housenumber")
    if street and number:
        return f"{street}, {number}"
    return street or None


def hotel_floors_from_pbf(pbf_path: str) -> dict[str, dict] | None:
    """Этажность и адреса самих отелей из PBF по их osm_id.

    Читаются только теги — кэш координат не нужен, поэтому проход дешёвый.
    None означает, что PBF недоступен: тогда остаётся снимок из HOTELS,
    и источник этой этажности честно помечается как snapshot.
    """
    try:
        import osmium
    except Exception as exc:  # noqa: BLE001 - зависимость может отсутствовать
        _log(f"pyosmium недоступен ({exc}) — этажность отелей останется из снимка")
        return None

    wanted = {(h["osm_type"], h["osm_id"]) for h in HOTELS}
    found: dict[str, dict] = {}

    class _HotelTags(osmium.SimpleHandler):
        def _add(self, kind: str, obj) -> None:
            if (kind, obj.id) not in wanted:
                return
            tags = dict(obj.tags)
            found[f"{kind}/{obj.id}"] = {
                "floors": _floors_from_tags(tags),
                "name": tags.get("name") or tags.get("name:ru") or tags.get("name:en"),
                "address": _hotel_address(tags),
                # В слой оставляем только то, что нужно сиду: адрес и этажность.
                "tags": {
                    key: value
                    for key, value in tags.items()
                    if key.startswith("addr:") or key == "building:levels"
                },
            }

        def node(self, obj) -> None:
            self._add("node", obj)

        def way(self, obj) -> None:
            self._add("way", obj)

        def relation(self, obj) -> None:
            self._add("relation", obj)

    try:
        _HotelTags().apply_file(pbf_path)
    except Exception as exc:  # noqa: BLE001 - повреждённый PBF
        _log(f"PBF: этажность отелей не прочитана ({exc})")
        return None

    with_levels = sum(1 for info in found.values() if info["floors"])
    _log(f"PBF hotels: найдено {len(found)} из {len(HOTELS)}, с этажностью {with_levels}")
    return found


def _building_row(osm_id: int, tags, geometry, area) -> dict | None:
    """Строка слоя зданий: высота из тегов OSM, None — если вне области."""
    if geometry is None or geometry.is_empty or not geometry.intersects(area):
        return None
    return {
        "osm_id": osm_id,
        "levels": _tag_number(tags.get("building:levels") or tags.get("levels")),
        "height": _tag_number(tags.get("height") or tags.get("building:height")),
        "fclass": tags.get("building"),
        "geometry": geometry,
    }


def prepare_buildings_from_pbf(pbf_path: str) -> gpd.GeoDataFrame | None:
    """Здания вокруг отелей с реальными высотами из тегов OSM.

    PBF — единственный источник ``building:levels`` и ``height``: shapefile
    того же экстракта этих тегов не содержит, и инструмент заката сравнивал
    этаж с константой 9 м. Если разбор невозможен (нет pyosmium, битый
    файл), возвращается None — вызывающий код честно откатывается на
    shapefile, а не выдумывает высоты.
    """
    try:
        import osmium
    except Exception as exc:  # noqa: BLE001 - зависимость может отсутствовать
        _log(f"pyosmium недоступен ({exc}) — высоты зданий останутся неизвестными")
        return None

    radius_deg = OSM_RADIUS_M / 111_000
    area = unary_union([Point(h["lon"], h["lat"]).buffer(radius_deg) for h in HOTELS])
    minx, miny, maxx, maxy = area.bounds

    rows: list[dict] = []

    try:
        # Кэш координат наполняется только из прочитанных узлов, поэтому
        # маска обязана включать NODE: с одной маской WAY pyosmium падает
        # с «Nodes not read from file». Узлы отбрасываем в цикле — фильтр
        # на уровне ридера отбросил бы их вместе с кэшем координат.
        processor = osmium.FileProcessor(
            pbf_path, osmium.osm.NODE | osmium.osm.WAY
        ).with_locations()
        for way in processor:
            if not isinstance(way, osmium.osm.Way):
                continue
            tags = way.tags
            if tags.get("building") in (None, "no"):
                continue
            try:
                coords = [(node.location.lon, node.location.lat) for node in way.nodes]
            except Exception:  # noqa: BLE001 - узел вне экстракта
                continue
            # Здание — замкнутое кольцо; незамкнутые building=construction
            # пропускаем, а не додумываем контур.
            if len(coords) < 4 or coords[0] != coords[-1]:
                continue
            # Дешёвая отсечка по bbox до построения геометрии.
            if not (minx <= coords[0][0] <= maxx and miny <= coords[0][1] <= maxy):
                continue

            geometry = Polygon(coords)
            if not geometry.is_valid:
                geometry = geometry.buffer(0)
            row = _building_row(way.id, tags, geometry, area)
            if row is not None:
                rows.append(row)
    except Exception as exc:  # noqa: BLE001 - повреждённый PBF
        _log(f"PBF не разобран: {exc}")
        return None

    if not rows:
        _log("PBF: зданий вокруг отелей не найдено")
        return None

    # Отношения (multipolygon) собираются отдельным проходом: у домов
    # с внутренним двором и у крупных корпусов контур задан несколькими way,
    # и без склейки луч заката видел бы на их месте пустоту.
    way_rows = len(rows)
    rows.extend(_pbf_building_relations(osmium, pbf_path, area))

    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")
    gdf["geometry"] = gdf.geometry.simplify(0.00002)
    gdf = gdf[["osm_id", "levels", "height", "fclass", "geometry"]]
    known = int((gdf["levels"].notna() | gdf["height"].notna()).sum())
    _log(
        f"PBF buildings: {len(gdf)} объектов ({way_rows} way, "
        f"{len(gdf) - way_rows} отношения), высота известна у {known} "
        f"({known / len(gdf) * 100:.0f}%), из них levels {int(gdf['levels'].notna().sum())}, "
        f"height {int(gdf['height'].notna().sum())}"
    )
    return gdf


def _wkb_factory():
    """Фабрика WKB: в pyosmium 3.x лежит в osmium.wkb, в 4.x — в osmium.geom."""
    try:
        from osmium.wkb import WKBFactory
    except ImportError:
        from osmium.geom import WKBFactory
    return WKBFactory()


def _pbf_building_relations(osmium, pbf_path: str, area) -> list[dict]:
    """Здания, контур которых задан отношением OSM (multipolygon).

    pyosmium читает файл дважды, чтобы склеить внешние и внутренние кольца —
    это дороже обычного прохода, зато крупные здания не выпадают из слоя.
    Области, собранные из замкнутых way, пропускаются: они уже разобраны
    первым проходом, иначе каждое здание посчиталось бы дважды.
    """
    rows: list[dict] = []

    class _RelationAreas(osmium.SimpleHandler):
        def __init__(self) -> None:
            super().__init__()
            self.factory = _wkb_factory()

        def area(self, obj) -> None:
            if obj.from_way():
                return
            tags = obj.tags
            if tags.get("building") in (None, "no"):
                return
            try:
                geometry = shapely_wkb.loads(self.factory.create_multipolygon(obj))
            except Exception:  # noqa: BLE001 - отношение с неполными членами
                return
            row = _building_row(obj.orig_id(), tags, geometry, area)
            if row is not None:
                rows.append(row)

    try:
        _RelationAreas().apply_file(pbf_path, locations=True)
    except Exception as exc:  # noqa: BLE001 - повреждённый PBF
        _log(f"PBF: отношения не разобраны ({exc})")

    return rows


def prepare_noise(folder: str) -> gpd.GeoDataFrame:
    frames: list[gpd.GeoDataFrame] = []

    roads = read_layer(folder, "gis_osm_roads_free_1")
    if roads is not None:
        roads = roads[roads["fclass"].isin(ROAD_CLASSES) & near_hotels_mask(roads)].copy()
        if not roads.empty:
            roads["highway"] = roads["fclass"]
            roads["railway"] = None
            roads["amenity"] = None
            frames.append(roads[["osm_id", "highway", "railway", "amenity", "geometry"]])

    rails = read_layer(folder, "gis_osm_railways_free_1")
    if rails is not None:
        rails = rails[near_hotels_mask(rails)].copy()
        if not rails.empty:
            rails["highway"] = None
            rails["railway"] = "rail"
            rails["amenity"] = None
            frames.append(rails[["osm_id", "highway", "railway", "amenity", "geometry"]])

    pois = read_layer(folder, "gis_osm_pois_free_1")
    if pois is not None:
        pois = pois[pois["fclass"].isin(POI_CLASSES) & near_hotels_mask(pois)].copy()
        if not pois.empty:
            pois["highway"] = None
            pois["railway"] = None
            pois["amenity"] = pois["fclass"]
            frames.append(pois[["osm_id", "highway", "railway", "amenity", "geometry"]])

    if not frames:
        return gpd.GeoDataFrame(columns=["osm_id", "highway", "railway", "amenity", "geometry"], crs="EPSG:4326")

    combined = pd.concat(frames, ignore_index=True)
    return gpd.GeoDataFrame(combined, geometry="geometry", crs="EPSG:4326")


def prepare_coast(folder: str) -> gpd.GeoDataFrame:
    """Пляжи и водоёмы: по ним считается реальное расстояние до воды."""
    frames: list[gpd.GeoDataFrame] = []
    clip = box(*CLIP_BOUNDS)

    for layer, kinds in (
        ("gis_osm_natural_a_free_1", None),
        ("gis_osm_water_a_free_1", None),
    ):
        gdf = read_layer(folder, layer)
        if gdf is None:
            continue
        gdf = gdf[gdf.geometry.intersects(clip)].copy()
        if gdf.empty:
            continue
        gdf["kind"] = gdf["fclass"].fillna("water")
        frames.append(gdf[["osm_id", "kind", "geometry"]])

    if not frames:
        return gpd.GeoDataFrame(columns=["osm_id", "kind", "geometry"], crs="EPSG:4326")

    combined = pd.concat(frames, ignore_index=True)
    combined["geometry"] = combined.geometry.simplify(0.0001)
    return gpd.GeoDataFrame(combined, geometry="geometry", crs="EPSG:4326")


# ---------------------------------------------------------------------------
# 3. DEM: реальный SRTM (skadi), обрезанный по области данных
# ---------------------------------------------------------------------------
SKADI_URL = "https://s3.amazonaws.com/elevation-tiles-prod/skadi/{lat_band}/{tile}.hgt.gz"
SRTM_SIZE = 3601  # 3 arc-second tile


def fetch_dem() -> bool:
    import rasterio
    from rasterio.transform import from_origin

    dem_path = os.path.join(DATA_DIR, "dem.tif")
    arrays = {}

    for tile in _dem_tiles():
        try:
            arrays[tile] = _download_skadi(tile)
            _log(f"DEM тайл {tile}: получен")
        except Exception as exc:  # noqa: BLE001 - источник внешний
            _log(f"DEM тайл {tile} не получен: {exc}")

    if not arrays:
        _log("DEM не получен — оставляю существующий файл без изменений.")
        return False

    lat_min = min(_tile_lat(tile) for tile in arrays)
    lon_min = min(_tile_lon(tile) for tile in arrays)
    grid_lat = max(_tile_lat(tile) for tile in arrays) - lat_min + 1
    grid_lon = max(_tile_lon(tile) for tile in arrays) - lon_min + 1
    step = 1.0 / (SRTM_SIZE - 1)

    mosaic = np.full(
        (grid_lat * (SRTM_SIZE - 1) + 1, grid_lon * (SRTM_SIZE - 1) + 1),
        -32768,
        dtype=np.int16,
    )
    for tile, arr in arrays.items():
        # В .hgt первая строка — северный край тайла, поэтому считаем от севера.
        row_off = (grid_lat - 1 - (_tile_lat(tile) - lat_min)) * (SRTM_SIZE - 1)
        col_off = (_tile_lon(tile) - lon_min) * (SRTM_SIZE - 1)
        mosaic[row_off:row_off + SRTM_SIZE, col_off:col_off + SRTM_SIZE] = arr

    north = lat_min + grid_lat
    west, south, east, _ = CLIP_BOUNDS
    row_start = int(round((north - CLIP_BOUNDS[3]) / step))
    row_end = row_start + int(round((CLIP_BOUNDS[3] - south) / step))
    col_start = int(round((west - lon_min) / step))
    col_end = col_start + int(round((east - west) / step))

    clipped = mosaic[row_start:row_end, col_start:col_end]
    if clipped.size == 0:
        _log("Пустой клип DEM — проверьте CLIP_BOUNDS.")
        return False

    with rasterio.open(
        dem_path, "w", driver="GTiff",
        height=clipped.shape[0], width=clipped.shape[1],
        count=1, dtype="int16", crs="EPSG:4326",
        transform=from_origin(west, CLIP_BOUNDS[3], step, step),
        nodata=-32768, compress="deflate",
    ) as dst:
        dst.write(clipped, 1)

    _log(f"DEM записан: {clipped.shape[1]}x{clipped.shape[0]} px, {os.path.getsize(dem_path) / 1024:.0f} КБ")
    return True


def _dem_tiles() -> list[str]:
    tiles = []
    for lat in range(int(CLIP_BOUNDS[1]), int(CLIP_BOUNDS[3]) + 1):
        for lon in range(int(CLIP_BOUNDS[0]), int(CLIP_BOUNDS[2]) + 1):
            tiles.append(f"N{lat:02d}E{lon:03d}")
    return tiles


def _tile_lat(tile: str) -> int:
    """'N54E020' -> 54."""
    return int(tile[1:3])


def _tile_lon(tile: str) -> int:
    """'N54E020' -> 20."""
    return int(tile[4:7])


def _download_skadi(tile: str) -> np.ndarray:
    url = SKADI_URL.format(lat_band=tile[:3], tile=tile)
    with _client() as client:
        resp = client.get(url)
    resp.raise_for_status()
    raw = gzip.decompress(resp.content)
    expected = SRTM_SIZE * SRTM_SIZE * 2
    if len(raw) != expected:
        raise ValueError(f"неожиданный размер тайла: {len(raw)} вместо {expected}")
    return np.frombuffer(raw, dtype=">i2").reshape(SRTM_SIZE, SRTM_SIZE).astype(np.int16)


# ---------------------------------------------------------------------------
# 4. Сохранение
# ---------------------------------------------------------------------------
def write_hotels(hotel_info: dict[str, dict] | None = None, buildings=None) -> None:
    """hotels.geojson: этажность и адрес из PBF, точка — из контура здания.

    Точку берём как representative_point контура: координата из списка
    привязана к углу way, а инструменты (луч заката, путь до моря) считают
    от точки внутри здания.
    """
    hotel_info = hotel_info or {}
    centroids: dict = {}
    if buildings is not None and not buildings.empty and "osm_id" in buildings.columns:
        wanted_ids = [hotel["osm_id"] for hotel in HOTELS]
        picked = buildings[buildings["osm_id"].isin(wanted_ids)]
        centroids = {
            int(row.osm_id): row.geometry.representative_point()
            for _, row in picked.iterrows()
        }

    rows = []
    for hotel in HOTELS:
        info = hotel_info.get(f"{hotel['osm_type']}/{hotel['osm_id']}") or {}
        floors = info.get("floors")
        rows.append(
            {
                "osm_id": hotel["osm_id"],
                "osm_type": hotel["osm_type"],
                "name": info.get("name") or hotel["name"],
                "address": info.get("address"),
                "floors": floors or hotel["floors"],
                # osm_pbf — этажность прочитана из тегов OSM в этом прогоне;
                # snapshot — PBF недоступен, оставлено значение из списка.
                "floors_source": "osm_pbf" if floors else "snapshot",
                "tags": info.get("tags") or {},
                "geometry": centroids.get(hotel["osm_id"])
                or Point(hotel["lon"], hotel["lat"]),
            }
        )

    hotels_gdf = gpd.GeoDataFrame(rows, crs="EPSG:4326")
    hotels_gdf.to_file(os.path.join(DATA_DIR, "hotels.geojson"), driver="GeoJSON")
    from_pbf = sum(1 for row in rows if row["floors_source"] == "osm_pbf")
    _log(f"hotels.geojson: {len(hotels_gdf)} записей, этажность из PBF у {from_pbf}")


def save_outputs(buildings, noise, coast, hotel_info: dict[str, dict] | None = None) -> None:
    write_hotels(hotel_info, buildings)

    for name, gdf, driver in (
        ("buildings.gpkg", buildings, "GPKG"),
        ("noise_sources.geojson", noise, "GeoJSON"),
        ("beaches.geojson", coast, "GeoJSON"),
    ):
        gdf.to_file(os.path.join(DATA_DIR, name), driver=driver)
        size = os.path.getsize(os.path.join(DATA_DIR, name)) / 1024 / 1024
        _log(f"{name}: {len(gdf)} записей, {size:.1f} МБ")


def describe(gdf: gpd.GeoDataFrame, column: str, label: str) -> None:
    if gdf is None or gdf.empty or column not in gdf.columns:
        _log(f"{label}: нет данных")
        return
    counts = gdf[column].value_counts().head(12).to_dict()
    _log(f"{label}: {len(gdf)} объектов, по классам: {counts}")


def build_buildings(folder: str | None, pbf_path: str | None = None) -> gpd.GeoDataFrame:
    """Здания вокруг отелей: сначала PBF (с высотами), затем shapefile.

    Порядок именно такой: shapefile — резерв, потому что он теряет этажность,
    а без неё луч заката не может отличить пятиэтажку от сарая.
    """
    if pbf_path:
        buildings = prepare_buildings_from_pbf(pbf_path)
        if buildings is not None:
            return buildings
        _log("PBF недоступен — высота зданий останется неизвестной (9 м по умолчанию)")

    if folder is None:
        return gpd.GeoDataFrame(
            columns=["osm_id", "levels", "height", "fclass", "geometry"], crs="EPSG:4326"
        )
    return prepare_buildings(folder)


def main() -> int:
    args = set(sys.argv[1:])
    # PBF качается один раз: из него же берётся этажность самих отелей.
    pbf_path = None if "--no-pbf" in args else download_pbf()

    if "--hotels-only" in args:
        # Только отели: этажность и адреса из PBF, точки — по готовому слою зданий.
        buildings_file = os.path.join(DATA_DIR, "buildings.gpkg")
        buildings = gpd.read_file(buildings_file) if os.path.exists(buildings_file) else None
        write_hotels(hotel_floors_from_pbf(pbf_path) if pbf_path else None, buildings)
        return 0

    if "--buildings-only" in args:
        # Пересборка только зданий: не тянет 55 МБ shapefile и тайлы DEM.
        buildings = build_buildings(None, pbf_path)
        if buildings.empty:
            _log("Здания не собраны")
            return 1
        buildings.to_file(os.path.join(DATA_DIR, "buildings.gpkg"), driver="GPKG")
        size = os.path.getsize(os.path.join(DATA_DIR, "buildings.gpkg")) / 1024 / 1024
        _log(f"buildings.gpkg: {len(buildings)} записей, {size:.1f} МБ")
        return 0

    if "--dem-only" not in args:
        _log("Сбор OSM-слоёв: Geofabrik")
        archive = download_extract()
        folder = extract_layers(archive)

        buildings = build_buildings(folder, pbf_path)
        noise = prepare_noise(folder)
        coast = prepare_coast(folder)

        describe(buildings, "fclass", "buildings")
        describe(noise, "highway", "дороги")
        describe(noise, "amenity", "POI")
        describe(noise, "railway", "железная дорога")
        describe(coast, "kind", "побережье/вода")

        save_outputs(
            buildings,
            noise,
            coast,
            hotel_floors_from_pbf(pbf_path) if pbf_path else None,
        )
        shutil.rmtree(WORK_DIR, ignore_errors=True)

    if "--osm-only" not in args:
        fetch_dem()

    _log("Готово.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
