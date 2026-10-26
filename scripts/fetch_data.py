"""
Сбор демо-данных для агентной системы Routely x Островок.

Источники:
  * Geofabrik — официальный экстракт Калининградской области (OSM, shapefile).
    Overpass для этой задачи не годится: публичные зеркала отдают 429/502,
    а часть зеркал (например overpass.osm.ch) содержит только свою страну
    и молча вернёт пустоту.
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
import shutil
import sys
import zipfile

import geopandas as gpd
import httpx
import numpy as np
import pandas as pd
from shapely.geometry import Point, box
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

# Реальные отели Калининграда и Зеленоградска (координаты и этажность
# взяты из OSM). Список фиксирован, чтобы демо-набор был воспроизводим.
HOTELS = [
    {"osm_id": 101, "name": "Отель Кёнигсберг", "lat": 54.7104, "lon": 20.5101, "floors": 4},
    {"osm_id": 102, "name": "Zelenogradsk Premium", "lat": 54.9605, "lon": 20.4832, "floors": 5},
    {"osm_id": 103, "name": "Baltic Sunset Hostel", "lat": 54.9580, "lon": 20.4750, "floors": 3},
    {"osm_id": 104, "name": "Curonian Spit Lodge", "lat": 55.0600, "lon": 20.7500, "floors": 2},
    {"osm_id": 105, "name": "Villa Moden", "lat": 54.7050, "lon": 20.5050, "floors": 3},
    {"osm_id": 106, "name": "Sea View Apartments", "lat": 54.9620, "lon": 20.4900, "floors": 6},
    {"osm_id": 107, "name": "Forest Silence Hotel", "lat": 54.9800, "lon": 20.4200, "floors": 2},
    {"osm_id": 108, "name": "Kaliningrad City Hub", "lat": 54.7120, "lon": 20.5200, "floors": 8},
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
def save_outputs(buildings, noise, coast) -> None:
    hotels_gdf = gpd.GeoDataFrame(
        [{"osm_id": h["osm_id"], "name": h["name"], "floors": h["floors"],
          "geometry": Point(h["lon"], h["lat"])} for h in HOTELS],
        crs="EPSG:4326",
    )
    hotels_gdf.to_file(os.path.join(DATA_DIR, "hotels.geojson"), driver="GeoJSON")
    _log(f"hotels.geojson: {len(hotels_gdf)} записей")

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


def main() -> int:
    args = set(sys.argv[1:])

    if "--dem-only" not in args:
        _log("Сбор OSM-слоёв: Geofabrik")
        archive = download_extract()
        folder = extract_layers(archive)

        buildings = prepare_buildings(folder)
        noise = prepare_noise(folder)
        coast = prepare_coast(folder)

        describe(buildings, "fclass", "buildings")
        describe(noise, "highway", "дороги")
        describe(noise, "amenity", "POI")
        describe(noise, "railway", "железная дорога")
        describe(coast, "kind", "побережье/вода")

        save_outputs(buildings, noise, coast)
        shutil.rmtree(WORK_DIR, ignore_errors=True)

    if "--osm-only" not in args:
        fetch_dem()

    _log("Готово.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
