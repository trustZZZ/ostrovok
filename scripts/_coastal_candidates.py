"""Разовая разведка: какие отели есть в OSM у берега (расширение демо-набора).

Не входит в демо и удаляется после использования. Задача — найти реальные
объекты OSM (tourism=hotel и родственные), которые стоят близко к пляжу
внутри CLIP_BOUNDS, чтобы добавить 3-4 из них в HOTELS в fetch_data.py.

Критерий отбора объективный — расстояние до ближайшего пляжа и наличие
этажности; «виден ли закат» здесь не учитывается, иначе набор отелей
подгонялся бы под нужный результат.
"""

from __future__ import annotations

import json
import math
import os

import httpx
import osmium
from shapely.geometry import Point, shape
from shapely.ops import unary_union

PBF_URL = "https://download.geofabrik.de/russia/kaliningrad-latest.osm.pbf"
PBF_PATH = "/tmp/kaliningrad-latest.osm.pbf"

# Только то, что попадает в CLIP_BOUNDS (20.40..20.85, 54.65..55.15).
# Светлогорск (20.15) в область не входит, поэтому его здесь нет.
BBOX = (20.40, 54.93, 20.52, 55.00)

TOURISM = {"hotel", "hostel", "guest_house", "apartment", "motel", "resort", "bed_and_breakfast"}

EXISTING_IDS = {
    162622681, 48817194, 558380773, 382545007, 116133914, 115643344, 115708035, 162948437,
}


def download() -> str:
    if os.path.exists(PBF_PATH) and os.path.getsize(PBF_PATH) > 10 * 1024 * 1024:
        print("PBF уже скачан", flush=True)
        return PBF_PATH
    print("Скачиваю PBF (~40 МБ)...", flush=True)
    with httpx.Client(timeout=httpx.Timeout(300.0, connect=20.0), follow_redirects=True) as client:
        with client.stream("GET", PBF_URL) as resp:
            resp.raise_for_status()
            with open(PBF_PATH, "wb") as fh:
                for chunk in resp.iter_bytes(1 << 20):
                    fh.write(chunk)
    print(f"PBF: {os.path.getsize(PBF_PATH)} байт", flush=True)
    return PBF_PATH


def _num(value):
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _in_bbox(lon: float, lat: float) -> bool:
    return BBOX[0] <= lon <= BBOX[2] and BBOX[1] <= lat <= BBOX[3]


class _Collector(osmium.SimpleHandler):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[dict] = []

    def _row(self, kind: str, obj, lon: float, lat: float) -> None:
        tags = {tag.k: tag.v for tag in obj.tags}
        tourism = tags.get("tourism")
        if tourism not in TOURISM:
            return
        if not _in_bbox(lon, lat):
            return
        self.rows.append(
            {
                "osm_type": kind,
                "osm_id": obj.id,
                "name": tags.get("name") or tags.get("name:ru") or tags.get("name:en"),
                "tourism": tourism,
                "lat": round(lat, 5),
                "lon": round(lon, 5),
                "levels": _num(tags.get("building:levels") or tags.get("levels")),
                "height": _num(tags.get("height")),
                "address": " ".join(
                    filter(None, [tags.get("addr:street"), tags.get("addr:housenumber")])
                ) or None,
            }
        )

    def node(self, obj) -> None:
        location = obj.location
        if location.valid():
            self._row("node", obj, location.lon, location.lat)

    def way(self, obj) -> None:
        points = []
        for node in obj.nodes:
            location = node.location
            if location.valid():
                points.append((location.lon, location.lat))
        if not points:
            return
        lon = sum(p[0] for p in points) / len(points)
        lat = sum(p[1] for p in points) / len(points)
        self._row("way", obj, lon, lat)


def main() -> None:
    pbf = download()

    collector = _Collector()
    collector.apply_file(pbf, locations=True)
    print(f"Объектов tourism в bbox: {len(collector.rows)}", flush=True)

    with open("/data/beaches.geojson", encoding="utf-8") as fh:
        beaches = [shape(f["geometry"]) for f in json.load(fh)["features"] if f.get("geometry")]
    beach_union = unary_union(beaches)

    def metres_to_beach(lon: float, lat: float) -> float:
        point = Point(lon, lat)
        # Градусы в метры: 1° широты ≈ 111 320 м, долготы — с косинусом широты.
        return float(beach_union.distance(point)) * 111320.0 * math.cos(math.radians(lat))

    for row in collector.rows:
        row["beach_m"] = round(metres_to_beach(row["lon"], row["lat"]))
        row["existing"] = row["osm_id"] in EXISTING_IDS

    collector.rows.sort(key=lambda r: r["beach_m"])
    with open("/data/_coastal_candidates.json", "w", encoding="utf-8") as fh:
        json.dump(collector.rows, fh, ensure_ascii=False, indent=2)

    print(f"Записано /data/_coastal_candidates.json: {len(collector.rows)}", flush=True)
    print("Топ-15 по близости к пляжу (beach_m | levels | tourism | osm_id | existing):", flush=True)
    for row in collector.rows[:15]:
        print(
            f"  {row['beach_m']:>5} m | {row['levels']} | {row['tourism']:<14} | "
            f"{row['osm_id']} | {'EXISTING' if row['existing'] else 'new'}",
            flush=True,
        )


if __name__ == "__main__":
    main()
