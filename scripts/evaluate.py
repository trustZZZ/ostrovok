#!/usr/bin/env python3
"""Замер качества собранных характеристик.

Три группы метрик:

1. Покрытие и достоверность. По каким характеристикам есть значение, сколько
   строк «нет данных», по скольким отелям агент пошёл к отельеру. Считается
   всегда и разметки не требует.

2. Согласованность с независимой оценкой. Пешее время до пляжа сравнивается
   с оценкой «расстояние по прямой x коэффициент извилистости». Оценка грубая,
   поэтому названа baseline, а не истиной: она ловит расхождение в разы
   (когда «5 минут» на деле 40), а не точность до минуты.

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
from pathlib import Path
from statistics import mean

import httpx

API_BASE = os.getenv("ROUTELY_API", "http://backend:8000")
BEACHES_PATH = os.getenv("BEACHES_PATH", "/data/beaches.geojson")
GROUND_TRUTH = os.getenv("GROUND_TRUTH", "/data/ground_truth.csv")
REPORT_PATH = os.getenv("EVAL_REPORT", "/data/eval_report.json")

# Коэффициент извилистости: пеший путь по улицам длиннее прямой примерно
# на треть. Значение — из практики градостроительных оценок, не из наших данных.
DETOUR_FACTOR = 1.3
WALK_SPEED_M_MIN = 80.0

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

    # ------------------------------------------------- точность на разметке
    truth_path = Path(GROUND_TRUTH)
    manual: dict[str, int] = {}
    manual_rows: list[list[str]] = []

    if truth_path.exists():
        by_name = {hotel["name"]: hotel for hotel in hotels}
        truth_rows = list(csv.DictReader(truth_path.open(encoding="utf-8")))

        sunset_checked = sunset_ok = 0
        walk_checked = 0
        walk_manual_errors: list[float] = []
        noise_checked = noise_ok = 0

        for row in truth_rows:
            hotel = by_name.get(row.get("hotel_name", ""))
            if hotel is None:
                continue

            features = {feature["key"]: feature for feature in hotel["features"]}

            expected_sunset = row.get("sunset_visible", "").strip()
            if expected_sunset in {"0", "1"}:
                sunset = features.get("sunset_view")
                actual = bool((sunset or {}).get("value", {}).get("visible"))
                sunset_checked += 1
                if actual == (expected_sunset == "1"):
                    sunset_ok += 1

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
        print("Заполните колонки sunset_visible (0/1), noise_level (low/medium/high)")
        print("и walk_minutes_ref — метрики появятся здесь. Пустые поля не считаются,")
        print("чтобы не подменять разметку нашими же значениями.")

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
        "manual_metrics": manual,
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
