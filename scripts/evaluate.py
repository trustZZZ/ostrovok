#!/usr/bin/env python3
"""Замер качества собранных характеристик.

Три группы метрик:

1. Покрытие и достоверность. По каким характеристикам есть значение, сколько
   строк «нет данных», по скольким отелям агент пошёл к отельеру. Считается
   всегда и разметки не требует.

2. Согласованность с независимой оценкой. Каждая гео-характеристика
   сравнивается со своей грубой альтернативой, посчитанной другим способом:

   - `walk_to_sea` — «расстояние по прямой x коэффициент извилистости»;
   - `sunset_view` — только рельеф DEM, без зданий и без перебора этажей:
     если холм на западе ниже линии глаз, вид считается открытым;
   - `noise_score` — плотность источников шума без весов и затухания.

   Оценки грубые, поэтому названы baseline, а не истиной: они ловят
   расхождение в разы, а не точность до единицы измерения.

3. Точность на ручной разметке из data/ground_truth.csv. Незаполненные поля
   пропускаются, а не заполняются нашими же значениями — иначе метрика
   измеряла бы саму себя.

Запуск (стек должен быть поднят):
    docker compose --profile tools run --rm seed python /scripts/evaluate.py
"""
from __future__ import annotations

import csv
import json
import math
import os
import sys
from datetime import date
from pathlib import Path
from statistics import mean

import httpx

API_BASE = os.getenv("ROUTELY_API", "http://backend:8000")
BEACHES_PATH = os.getenv("BEACHES_PATH", "/data/beaches.geojson")
NOISE_PATH = os.getenv("NOISE_PATH", "/data/noise_sources.geojson")
DEM_PATH = os.getenv("DEM_PATH", "/data/dem.tif")
GROUND_TRUTH = os.getenv("GROUND_TRUTH", "/data/ground_truth.csv")
REPORT_PATH = os.getenv("EVAL_REPORT", "/data/eval_report.json")

# Коэффициент извилистости: пеший путь по улицам длиннее прямой примерно
# на треть. Значение — из практики градостроительных оценок, не из наших данных.
DETOUR_FACTOR = 1.3
WALK_SPEED_M_MIN = 80.0

# --- baseline заката: только рельеф, без зданий и без перебора этажей ----
SUNSET_MONTHS = (4, 5, 6, 7, 8)
SUNSET_SECTOR_DEG = 8.0    # половина ширины сектора вокруг азимута заката
SUNSET_RAY_KM = 10.0       # та же дальность, что у инструмента
DEM_SAMPLE_STEP_M = 150.0  # грубее, чем у инструмента: baseline должен быть простым
FLOOR_HEIGHT_M = 3.0

# --- baseline шума: плотность источников без весов и затухания -----------
NOISE_BASELINE_RADIUS_M = 400.0

NOISE_LEVELS = {"low": "Тихо", "medium": "Умеренно", "high": "Шумно"}


def get(path: str) -> object:
    with httpx.Client(timeout=30.0) as client:
        response = client.get(f"{API_BASE}{path}")
        response.raise_for_status()
        return response.json()


def is_no_data(value) -> bool:
    return isinstance(value, dict) and value.get("status") == "no_data"


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def load_beach_points() -> list[tuple[float, float]]:
    """Координаты пляжей из локального слоя OSM — независимо от пешего графа."""
    try:
        import geopandas as gpd
    except ImportError:
        return []

    try:
        frame = gpd.read_file(BEACHES_PATH)
    except Exception as exc:  # noqa: BLE001 - слой может отсутствовать
        print(f"  слой пляжей недоступен: {exc}")
        return []

    if frame.empty:
        return []

    if "kind" in frame.columns:
        beaches = frame[frame["kind"] == "beach"]
        if not beaches.empty:
            frame = beaches

    points: list[tuple[float, float]] = []
    for geometry in frame.geometry:
        if geometry is None or geometry.is_empty:
            continue
        centroid = geometry.centroid
        points.append((centroid.y, centroid.x))
    return points


def load_noise_layer():
    """Слой источников шума. Baseline берёт из него только плотность объектов."""
    try:
        import geopandas as gpd
    except ImportError:
        return None
    try:
        frame = gpd.read_file(NOISE_PATH)
    except Exception as exc:  # noqa: BLE001 - слой может отсутствовать
        print(f"  слой источников шума недоступен: {exc}")
        return None
    return None if frame.empty else frame


def load_dem():
    """DEM целиком в память: 1620x1800 float32 — около 11 МБ."""
    try:
        import rasterio
    except ImportError:
        return None
    try:
        with rasterio.open(DEM_PATH) as dem:
            return {
                "data": dem.read(1).astype("float32"),
                "transform": dem.transform,
                "nodata": dem.nodata,
            }
    except Exception as exc:  # noqa: BLE001 - файла может не быть
        print(f"  DEM недоступен: {exc}")
        return None


def dem_elevation(dem, lon: float, lat: float) -> float | None:
    data, transform = dem["data"], dem["transform"]
    col = int((lon - transform.c) / transform.a)
    row = int((lat - transform.f) / transform.e)
    if not (0 <= row < data.shape[0] and 0 <= col < data.shape[1]):
        return None
    value = float(data[row, col])
    if dem["nodata"] is not None and value == float(dem["nodata"]):
        return None
    return value


def sun_declination_deg(month: int) -> float:
    """Склонение Солнца для 21-го числа месяца (формула Купера, ~0.5°)."""
    day_of_year = date(2026, month, 21).timetuple().tm_yday
    return 23.45 * math.sin(math.radians(360.0 / 365.0 * (284 + day_of_year)))


def sunset_azimuth_deg(lat: float, month: int) -> float:
    """Азимут точки заката от севера по часовой стрелке.

    Считается астрономической формулой, а не pysolar, которым пользуется
    инструмент: baseline не должен повторять ту же библиотеку, что проверяет.
    """
    declination = math.radians(sun_declination_deg(month))
    cos_azimuth = math.sin(declination) / math.cos(math.radians(lat))
    cos_azimuth = max(-1.0, min(1.0, cos_azimuth))
    return 360.0 - math.degrees(math.acos(cos_azimuth))


def _sector_offsets() -> list[float]:
    step = SUNSET_SECTOR_DEG / 2
    return [-SUNSET_SECTOR_DEG, -step, 0.0, step, SUNSET_SECTOR_DEG]


def sunset_terrain_baseline(dem, lat: float, lon: float, observer_m: float) -> dict[int, bool]:
    """Перекрыт ли закат рельефом — без зданий, без этажей, без raycasting.

    Идём по сектору вокруг азимута заката и смотрим, поднимается ли рельеф
    выше линии глаз. Здания игнорируются, поэтому baseline систематически
    оптимистичнее инструмента — расхождения разбираются в отчёте отдельно.
    """
    max_distance = SUNSET_RAY_KM * 1000.0
    distances = [DEM_SAMPLE_STEP_M * step for step in range(1, int(max_distance / DEM_SAMPLE_STEP_M) + 1)]
    cos_lat = math.cos(math.radians(lat))

    blocked_by_month: dict[int, bool] = {}
    for month in SUNSET_MONTHS:
        azimuth = sunset_azimuth_deg(lat, month)
        steepest = None
        for offset in _sector_offsets():
            bearing = math.radians(azimuth + offset)
            sin_bearing, cos_bearing = math.sin(bearing), math.cos(bearing)
            for distance in distances:
                point_lat = lat + distance * cos_bearing / 111_000.0
                point_lon = lon + distance * sin_bearing / (111_000.0 * cos_lat)
                elevation = dem_elevation(dem, point_lon, point_lat)
                if elevation is None:
                    continue
                angle = (elevation - observer_m) / distance
                steepest = angle if steepest is None else max(steepest, angle)
        # Рельеф выше линии глаз хотя бы в одной точке сектора — горизонт закрыт.
        blocked_by_month[month] = steepest is not None and steepest > 0
    return blocked_by_month


def _ranks(values: list[float]) -> list[float]:
    """Ранги со средним для совпадающих значений."""
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    position = 0
    while position < len(order):
        end = position
        while end + 1 < len(order) and values[order[end + 1]] == values[order[position]]:
            end += 1
        average = (position + end) / 2.0 + 1.0
        for index in range(position, end + 1):
            ranks[order[index]] = average
        position = end + 1
    return ranks


def spearman_rho(xs: list[float], ys: list[float]) -> float | None:
    """Ранговая корреляция: проверяет порядок отелей, а не абсолютные баллы."""
    if len(xs) < 3 or len(xs) != len(ys):
        return None
    ranks_x, ranks_y = _ranks(xs), _ranks(ys)
    mean_x, mean_y = mean(ranks_x), mean(ranks_y)
    numerator = sum((a - mean_x) * (b - mean_y) for a, b in zip(ranks_x, ranks_y))
    denominator = math.sqrt(
        sum((a - mean_x) ** 2 for a in ranks_x) * sum((b - mean_y) ** 2 for b in ranks_y)
    )
    return round(numerator / denominator, 3) if denominator else None


def reason_label(reason: str | None) -> str:
    """Человеческая причина, по которой инструмент не видит закат."""
    if reason == "facade_facing_away":
        return "окна не на запад"
    if reason == "obstructed":
        return "загорожено"
    return ""


def format_table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))

    def line(cells: list[str]) -> str:
        return "  ".join(cell.ljust(widths[index]) for index, cell in enumerate(cells))

    parts = [line(headers), "  ".join("-" * width for width in widths)]
    parts.extend(line(row) for row in rows)
    return "\n".join(parts)


def main() -> int:
    print(f"Опрос API: {API_BASE}")
    try:
        hotels = get("/api/hotels")
        registry = get("/api/features")
        inbox = get("/api/hotelier/inbox")
    except Exception as exc:  # noqa: BLE001 - внешний сервис
        print(f"API недоступен: {exc}")
        print("Поднимите стек: docker compose up -d")
        return 1

    if not hotels:
        print("В базе нет отелей: сначала выполните сибирование")
        return 1

    beach_points = load_beach_points()
    total_hotels = len(hotels)
    total_rows = sum(len(hotel["features"]) for hotel in hotels)
    no_data_rows = sum(
        1
        for hotel in hotels
        for feature in hotel["features"]
        if is_no_data(feature["value"])
    )

    # ------------------------------------------------------------------ покрытие
    coverage_rows: list[list[str]] = []
    for spec in registry:
        key = spec["key"]
        with_value = 0
        for hotel in hotels:
            for feature in hotel["features"]:
                if feature["key"] != key:
                    continue
                if (feature.get("confidence") or 0) > 0 and not is_no_data(feature["value"]):
                    with_value += 1
                    break
        coverage_rows.append(
            [
                key,
                spec.get("target", ""),
                f"{with_value}/{total_hotels}",
                f"{with_value / total_hotels:.0%}",
                "да" if spec.get("tools") else "нет (отельер)",
            ]
        )

    print("\nПОКРЫТИЕ ХАРАКТЕРИСТИК")
    print(format_table(["характеристика", "уровень", "отелей", "доля", "инструмент"], coverage_rows))

    hotels_with_questions = len({question["hotel_id"] for question in inbox})
    print(
        f"\nстрок характеристик: {total_rows}, из них «нет данных»: {no_data_rows} "
        f"({no_data_rows / total_rows:.0%})" if total_rows else "\nстрок характеристик нет"
    )
    print(
        f"вопросов отельеру: {len(inbox)} "
        f"(отелей затронуто {hotels_with_questions}/{total_hotels})"
    )

    # ------------------------------------- согласованность с независимым baseline
    walk_errors: list[float] = []
    walk_rows: list[list[str]] = []
    if beach_points:
        for hotel in hotels:
            walk = next(
                (feature for feature in hotel["features"] if feature["key"] == "walk_to_sea"),
                None,
            )
            minutes = (walk or {}).get("value", {}).get("minutes")
            if minutes is None:
                continue
            nearest = min(
                haversine_m(hotel["lat"], hotel["lon"], lat, lon)
                for lat, lon in beach_points
            )
            baseline = nearest * DETOUR_FACTOR / WALK_SPEED_M_MIN
            walk_errors.append(minutes - baseline)
            walk_rows.append(
                [
                    hotel["name"][:26],
                    f"{minutes:.0f}",
                    f"{baseline:.0f}",
                    f"{minutes - baseline:+.0f}",
                ]
            )

    if walk_errors:
        mae = mean(abs(error) for error in walk_errors)
        bias = mean(walk_errors)
        print("\nПЕШЕЕ ВРЕМЯ: НАШ РАСЧЁТ ПРОТИВ ОЦЕНКИ ПО ПРЯМОЙ")
        print(format_table(["отель", "наш, мин", "baseline, мин", "разница"], walk_rows))
        print(f"MAE к baseline: {mae:.1f} мин, смещение: {bias:+.1f} мин")
        print(
            "трактовка: baseline — не истина, а проверка на расхождение в разы; "
            "совпадение до десятков минут уже означает, что маршрут правдоподобен"
        )

    # ------------------------------------ закат: проверка по одному рельефу
    sunset_summary = None
    dem = load_dem()
    if dem is not None:
        agreement = {
            "both_visible": 0,
            "both_hidden": 0,
            "tool_only": 0,
            "baseline_only": 0,
            # Расхождение, где рельеф открыт, а инструмент вид не видит,
            # объясняется либо застройкой на луче, либо ориентацией окон.
            "explained_by_buildings": 0,
            "explained_by_facade": 0,
        }
        sunset_rows: list[list[str]] = []

        for hotel in hotels:
            sunset = next(
                (feature for feature in hotel["features"] if feature["key"] == "sunset_view"),
                None,
            )
            if sunset is None or is_no_data(sunset["value"]):
                continue

            ground = dem_elevation(dem, hotel["lon"], hotel["lat"])
            if ground is None:
                continue

            tool_visible = bool(sunset["value"].get("visible"))
            floors = hotel.get("floors") or 1
            blocked = sunset_terrain_baseline(
                dem, hotel["lat"], hotel["lon"], ground + floors * FLOOR_HEIGHT_M
            )
            baseline_visible = any(not blocked_by_terrain for blocked_by_terrain in blocked.values())
            evidence = sunset.get("raw_evidence") or {}
            buildings_on_ray = evidence.get("buildings_on_ray") or 0
            block_reason = evidence.get("block_reason")

            if tool_visible and baseline_visible:
                agreement["both_visible"] += 1
            elif not tool_visible and not baseline_visible:
                agreement["both_hidden"] += 1
            elif tool_visible:
                agreement["tool_only"] += 1
            else:
                agreement["baseline_only"] += 1
                if block_reason == "facade_facing_away":
                    # Baseline смотрит только на рельеф и не знает, куда
                    # выходят окна: расхождение здесь ожидаемо и объяснимо.
                    agreement["explained_by_facade"] += 1
                elif buildings_on_ray > 0:
                    agreement["explained_by_buildings"] += 1

            sunset_rows.append(
                [
                    hotel["name"][:26],
                    f"{floors:>2}",
                    "виден" if tool_visible else "нет",
                    "открыт" if baseline_visible else "закрыт",
                    str(buildings_on_ray),
                    reason_label(block_reason),
                ]
            )

        if sunset_rows:
            # explained_* — подкатегории baseline_only, поэтому в размер
            # выборки они не входят: иначе 8 отелей превращаются в 13 сравнений.
            total_compared = (
                agreement["both_visible"]
                + agreement["both_hidden"]
                + agreement["tool_only"]
                + agreement["baseline_only"]
            )
            matched = agreement["both_visible"] + agreement["both_hidden"]
            sunset_summary = {
                "sample": total_compared,
                "agreement": round(matched / total_compared, 3),
                **agreement,
                # Расхождение, где инструмент видит закат, а рельеф его закрывает,
                # самый опасный: это возможный ложноположительный ответ.
                "suspicious_tool_visible": agreement["tool_only"],
            }
            print("\nЗАКАТ: НАШ РАСЧЁТ ПРОТИВ ПРОВЕРКИ ПО ОДНОМУ РЕЛЬЕФУ")
            print(
                format_table(
                    ["отель", "эт.", "наш", "рельеф", "зданий на луче", "причина"],
                    sunset_rows,
                )
            )
            print(
                f"совпадение: {matched}/{total_compared} ({matched / total_compared:.0%}), "
                f"расхождения: инструмент видит — {agreement['tool_only']}, "
                f"инструмент не видит — {agreement['baseline_only']} "
                f"(из них застройкой объяснено {agreement['explained_by_buildings']}, "
                f"стороной фасада — {agreement['explained_by_facade']})"
            )
            print(
                "трактовка: baseline учитывает только DEM и не знает, куда выходят окна. "
                "Поэтому «инструмент не видит» при открытом рельефе объясняется "
                "застройкой или тем, что главный фасад смотрит в другую сторону. "
                "Обратный случай — «виден» при закрытом рельефе — повод перепроверить расчёт."
            )
    else:
        print("\nЗАКАТ: baseline по рельефу не посчитан — нет DEM")

    # ----------------------------------- шум: проверка по плотности источников
    noise_summary = None
    noise_layer = load_noise_layer()
    if noise_layer is not None:
        scores: list[float] = []
        densities: list[float] = []
        noise_rows: list[list[str]] = []

        for hotel in hotels:
            noise = next(
                (feature for feature in hotel["features"] if feature["key"] == "noise_score"),
                None,
            )
            score = (noise or {}).get("value", {}).get("score")
            if score is None:
                continue

            # Baseline без весов, радиусов по типам и затухания: просто сколько
            # объектов шума оказалось рядом. Проверяет порядок отелей, а не балл.
            density = 0
            for geometry in noise_layer.geometry:
                if geometry is None or geometry.is_empty:
                    continue
                centroid = geometry.centroid
                if (
                    haversine_m(hotel["lat"], hotel["lon"], centroid.y, centroid.x)
                    <= NOISE_BASELINE_RADIUS_M
                ):
                    density += 1

            scores.append(float(score))
            densities.append(float(density))
            noise_rows.append([hotel["name"][:26], f"{score:.0f}", str(density)])

        rho = spearman_rho(scores, densities)
        if rho is not None:
            noise_summary = {
                "sample": len(scores),
                "spearman": rho,
                "radius_m": NOISE_BASELINE_RADIUS_M,
            }
            print("\nШУМ: НАШ БАЛЛ ПРОТИВ ПРОСТОЙ ПЛОТНОСТИ ИСТОЧНИКОВ")
            print(
                format_table(
                    ["отель", "наш балл", f"объектов в {NOISE_BASELINE_RADIUS_M:.0f} м"],
                    noise_rows,
                )
            )
            print(f"ранговая корреляция Спирмена: {rho:+.2f} (n={len(scores)})")
            print(
                "трактовка: балл взвешен по типам и расстоянию, baseline — чистая "
                "плотность. Ранговая корреляция ниже 0.6 означает, что веса "
                "переставляют отели местами и модель стоит пересмотреть."
            )
        else:
            print("\nШУМ: для ранговой корреляции нужно минимум 3 отеля со score")
    else:
        print("\nШУМ: baseline не посчитан — нет слоя источников шума")

    # ------------------------------------------------- точность на разметке
    truth_path = Path(GROUND_TRUTH)
    manual: dict[str, float] = {}
    manual_rows: list[list[str]] = []
    # Имена из разметки, которых не нашлось в БД. Сопоставление идёт по точному
    # совпадению, поэтому опечатка или переименованный отель молча выпадал из
    # выборки: метрика уменьшалась, и никто об этом не узнавал.
    unmatched_truth: list[str] = []

    if truth_path.exists():
        by_name = {hotel["name"]: hotel for hotel in hotels}
        truth_rows = list(csv.DictReader(truth_path.open(encoding="utf-8")))

        sunset_checked = sunset_ok = 0
        sunset_floor_checked = 0
        sunset_floor_errors: list[float] = []
        walk_checked = 0
        walk_manual_errors: list[float] = []
        noise_checked = noise_ok = 0

        for row in truth_rows:
            hotel = by_name.get(row.get("hotel_name", ""))
            if hotel is None:
                name = (row.get("hotel_name") or "").strip()
                if name:
                    unmatched_truth.append(name)
                continue

            features = {feature["key"]: feature for feature in hotel["features"]}

            expected_sunset = row.get("sunset_visible", "").strip()
            if expected_sunset in {"0", "1"}:
                sunset = features.get("sunset_view")
                actual = bool((sunset or {}).get("value", {}).get("visible"))
                sunset_checked += 1
                if actual == (expected_sunset == "1"):
                    sunset_ok += 1

            # Этаж, с которого открывается закат, сравниваем только когда он
            # известен с обеих сторон: если инструмент говорит «не виден»,
            # ошибка уже учтена в sunset_accuracy, и второй раз её не считаем.
            expected_floor = row.get("sunset_from_floor", "").strip()
            if expected_floor:
                try:
                    expected_floor_value = float(expected_floor.replace(",", "."))
                except ValueError:
                    expected_floor_value = None
                actual_floor = (features.get("sunset_view") or {}).get("value", {}).get("from_floor")
                if expected_floor_value is not None and actual_floor is not None:
                    sunset_floor_checked += 1
                    sunset_floor_errors.append(abs(float(actual_floor) - expected_floor_value))

            expected_noise = row.get("noise_level", "").strip().lower()
            if expected_noise in NOISE_LEVELS:
                noise = features.get("noise_score")
                actual_level = (noise or {}).get("value", {}).get("level")
                noise_checked += 1
                if actual_level == NOISE_LEVELS[expected_noise]:
                    noise_ok += 1

            expected_walk = row.get("walk_minutes_ref", "").strip()
            if expected_walk:
                walk = features.get("walk_to_sea")
                actual_minutes = (walk or {}).get("value", {}).get("minutes")
                if actual_minutes is not None:
                    walk_checked += 1
                    walk_manual_errors.append(abs(actual_minutes - float(expected_walk)))

        if sunset_checked:
            manual["sunset_accuracy"] = round(sunset_ok / sunset_checked, 3)
            manual_rows.append(
                ["закат виден", f"{sunset_ok}/{sunset_checked}", f"{sunset_ok / sunset_checked:.0%}"]
            )
        if sunset_floor_checked:
            floor_mae = mean(sunset_floor_errors)
            manual["sunset_floor_mae"] = round(floor_mae, 1)
            manual_rows.append(
                [
                    "этаж видимости заката",
                    f"MAE {floor_mae:.1f} эт. (n={sunset_floor_checked})",
                    "",
                ]
            )
        if noise_checked:
            manual["noise_accuracy"] = round(noise_ok / noise_checked, 3)
            manual_rows.append(
                ["уровень шума", f"{noise_ok}/{noise_checked}", f"{noise_ok / noise_checked:.0%}"]
            )
        if walk_checked:
            walk_mae = mean(walk_manual_errors)
            manual["walk_mae"] = round(walk_mae, 1)
            manual_rows.append(["время до пляжа", f"MAE {walk_mae:.1f} мин", ""])

    print("\nТОЧНОСТЬ НА РУЧНОЙ РАЗМЕТКЕ")
    if manual_rows:
        print(format_table(["характеристика", "результат", "доля"], manual_rows))
    else:
        print(f"разметка не заполнена ({GROUND_TRUTH}).")
        print("Заполните колонки sunset_visible (0/1), sunset_from_floor (этаж),")
        print("noise_level (low/medium/high) и walk_minutes_ref — метрики появятся здесь.")
        print("Пустые поля не считаются, чтобы не подменять разметку нашими же значениями.")

    if unmatched_truth:
        print(
            f"\nВНИМАНИЕ: строк разметки не сопоставлено с БД — {len(unmatched_truth)}, "
            "в метрики они не попали:"
        )
        for name in unmatched_truth:
            print(f"  «{name}»")
        print("Сопоставление идёт по точному совпадению имён — проверьте написание.")

    report = {
        "hotels": total_hotels,
        "feature_rows": total_rows,
        "no_data_rows": no_data_rows,
        "questions": len(inbox),
        "hotels_with_questions": hotels_with_questions,
        "coverage": {
            row[0]: {"value": row[2], "share": row[3]} for row in coverage_rows
        },
        "walk_vs_baseline": (
            {
                "mae_minutes": round(mean(abs(error) for error in walk_errors), 1),
                "bias_minutes": round(mean(walk_errors), 1),
                "sample": len(walk_errors),
            }
            if walk_errors
            else None
        ),
        "sunset_vs_terrain_baseline": sunset_summary,
        "noise_vs_density_baseline": noise_summary,
        "manual_metrics": manual,
        "manual_unmatched_hotels": unmatched_truth,
    }

    try:
        Path(REPORT_PATH).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\nотчёт сохранён: {REPORT_PATH}")
    except OSError as exc:
        print(f"\nне удалось сохранить отчёт: {exc}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
