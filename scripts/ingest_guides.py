#!/usr/bin/env python3
"""Ingest партнёрских обзоров → характеристики отелей.

Читает снапшоты из ``data/guides/*.json`` (контракт — ``data/guides/CONTRACT.md``),
проверяет их по контракту, привязывает места к отелям пешим маршрутом и
пишет результат в ``hotel_features`` источником ``blogger:<partner_id>``.

Почему офлайн, а не запросом в рантайме: правила требуют запуска одной
командой ``docker compose up --build``, а чужой сервис может быть недоступен
на защите. Снапшот обновляется отдельной командой, когда партнёр доступен.

Границы ответственности: расстояние и связь «место ↔ отель» считаем мы,
доверие к обзорам — тоже мы (см. ``app/guides.py``). Партнёр поставляет
только факты с провенансом.

Запуск:
    docker compose --profile tools run --rm seed python /scripts/ingest_guides.py
    make guides

Флаги: ``--fetch`` (забрать свежий ответ у партнёра), ``--dry-run``,
``--file <путь>`` (один конкретный снапшот).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx
from geoalchemy2.shape import to_shape
from sqlalchemy import select


def _bootstrap_path() -> None:
    """Добавляет пакет ``app`` в sys.path.

    Скрипт запускается по пути (`python /scripts/ingest_guides.py`), поэтому
    рабочий каталог в sys.path не попадает. В контейнере пакет лежит в /app,
    при локальном запуске — в ./backend рядом со скриптом.
    """
    here = Path(__file__).resolve()
    for candidate in (
        Path("/app"),
        here.parent.parent / "backend",
        Path.cwd(),
        Path.cwd() / "backend",
    ):
        if (candidate / "app" / "config.py").is_file():
            sys.path.insert(0, str(candidate))
            return


_bootstrap_path()

from app.collectors import load_noise_layers
from app.config import settings
from app.db import async_session
from app.feature_registry import get_feature
from app.guides import (
    parse_batch,
    best_place,
    build_evidence,
    build_value,
    confidence_for,
    place_emotions,
)
from app.models import Hotel, HotelFeature
from app.seed import upsert_feature
from app.tools.walk_to_sea import _haversine_m, build_walk_graph, compute_walk_to_point

FEATURE_KEY = "sunset_spot_nearby"
# Дальше полутора километров по прямой — это уже другой район: гостю не
# «рядом с отелем», а «в городе». Маршрут считаем только внутри радиуса.
MAX_STRAIGHT_M = 1500.0
# Образец контракта лежит рядом со снапшотами и в сборку не попадает.
SKIP_FILES = {"contract.sample.json"}


def load_payloads(guides_dir: Path, only: Path | None) -> list[tuple[str, Any]]:
    files = [only] if only else sorted(guides_dir.glob("*.json"))
    payloads: list[tuple[str, Any]] = []
    for path in files:
        if only is None and path.name in SKIP_FILES:
            continue
        try:
            payloads.append((path.name, json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"  {path.name}: не прочитан ({exc})")
    return payloads


def fetch_snapshot(guides_dir: Path) -> Path | None:
    """Забирает свежий ответ партнёра и сохраняет снапшот.

    Токен и адрес — из окружения, не из репозитория: контракт предполагает
    авторизацию, а секреты в снапшоте и в git не живут.
    """
    url = os.getenv("GUIDES_API_URL", "").rstrip("/")
    if not url:
        print("  GUIDES_API_URL не задан — беру снапшот из репозитория")
        return None

    headers = {}
    token = os.getenv("GUIDES_API_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    params: dict[str, str] = {}
    if os.getenv("GUIDES_CITY"):
        params["city"] = os.environ["GUIDES_CITY"]

    with httpx.Client(timeout=30.0) as client:
        response = client.get(f"{url}/v1/guides", headers=headers, params=params)
        response.raise_for_status()
        payload = response.json()

    target = guides_dir / "partner.snapshot.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  снапшот обновлён: {target}")
    return target


async def ingest(payloads: list[tuple[str, Any]], dry_run: bool) -> int:
    accepted: list[tuple[Any, list[str]]] = []
    retracted: set[str] = set()
    for name, payload in payloads:
        batch, issues = parse_batch(payload)
        print(f"\n=== {name}")
        if batch is None:
            print("  пакет отклонён целиком:")
            for issue in issues:
                print(f"    - {issue}")
            continue
        retracted.update(batch.retracted_guides)
        accepted.append((batch, issues))
        print(
            f"  партнёр: {batch.partner_name} ({batch.partner_id}), "
            f"схема {batch.schema_version}"
        )
        print(
            f"  обзоров принято: {len(batch.reviews)}, "
            f"снято партнёром: {len(batch.retracted_guides)}"
        )
        for issue in issues:
            print(f"    ! отклонено: {issue}")

    if not accepted:
        print("\nнечего применять: ни один пакет не прошёл проверку")
        return 1

    spec = get_feature(FEATURE_KEY)
    if spec is None:
        print(f"в реестре нет характеристики {FEATURE_KEY} — проверьте features.yaml")
        return 1

    graph = build_walk_graph(load_noise_layers().get("highway"))
    if graph.number_of_nodes() == 0:
        print("нет дорожной сети: маршруты до партнёрских мест не посчитать")
        return 1
    print(f"\nграф дорог: {graph.number_of_nodes()} узлов")

    async with async_session() as session:
        hotels = (await session.execute(select(Hotel))).scalars().all()
        coords = {}
        for hotel in hotels:
            geometry = to_shape(hotel.geom)
            coords[hotel.id] = (geometry.y, geometry.x)
        print(f"отелей в базе: {len(coords)}")

        for batch, _issues in accepted:
            # Снятые партнёром обзоры не участвуют в подтверждении, даже если
            # пришли в том же пакете: иначе ретракция не работала бы.
            reviews = [review for review in batch.reviews if review.guide_id not in retracted]
            places = place_emotions(reviews, FEATURE_KEY)
            print(
                f"\n=== {batch.partner_name}: мест с эмоцией «{FEATURE_KEY}»: {len(places)}"
            )
            if not places:
                print("  нечего привязывать")
                continue

            candidates: dict[int, list[tuple[Any, dict]]] = {}
            for place in places:
                for hotel_id, (lat, lon) in coords.items():
                    straight = _haversine_m(place.lat, place.lon, lat, lon)
                    if straight > MAX_STRAIGHT_M:
                        continue
                    route = compute_walk_to_point(
                        lon,
                        lat,
                        place.lon,
                        place.lat,
                        dem_path=settings.DEM_PATH,
                        graph=graph,
                        straight_m=straight,
                        target_label="места",
                    )
                    candidates.setdefault(hotel_id, []).append((place, route))

            source = f"blogger:{batch.partner_id}"
            written: dict[int, dict] = {}
            for hotel_id, options in candidates.items():
                choice = best_place(options)
                if choice is None:
                    continue
                place, route = choice
                confidence = confidence_for(place.reviews, place.osm_verified)
                written[hotel_id] = build_value(place, route)
                print(
                    f"  отель {hotel_id}: {place.place_name} — "
                    f"{round(float(route['minutes']))} мин, "
                    f"подтверждений {place.reviews}, уверенность {confidence}"
                )
                if dry_run:
                    continue
                await upsert_feature(
                    session,
                    hotel_id=hotel_id,
                    feature_key=FEATURE_KEY,
                    value=build_value(place, route),
                    source=source,
                    confidence=confidence,
                    evidence=build_evidence(batch, place, FEATURE_KEY),
                    ttl_days=spec.ttl_days,
                )

            if dry_run:
                print(f"  dry-run: записали бы {len(written)} значений, источник {source}")
                continue

            # Отель, у которого место больше не подтверждено (обзор снят или
            # место выпало из радиуса), не должен сохранять прошлый факт.
            existing = (
                (
                    await session.execute(
                        select(HotelFeature).where(
                            HotelFeature.feature_key == FEATURE_KEY,
                            HotelFeature.source == source,
                        )
                    )
                )
                .scalars()
                .all()
            )
            for row in existing:
                if row.hotel_id not in written:
                    await session.delete(row)
                    print(f"  отель {row.hotel_id}: факт снят — подтверждений не осталось")

        if dry_run:
            print("\ndry-run: изменения не сохранены")
            return 0

        await session.commit()
        print("\nготово: значения записаны в hotel_features")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest партнёрских обзоров в характеристики")
    parser.add_argument("--fetch", action="store_true", help="забрать свежий ответ у партнёра")
    parser.add_argument("--dry-run", action="store_true", help="посчитать, но не записывать")
    parser.add_argument("--file", type=Path, help="один конкретный снапшот")
    args = parser.parse_args()

    guides_dir = Path(settings.GUIDES_PATH)
    if not guides_dir.is_dir():
        print(f"нет каталога снапшотов: {guides_dir}")
        return 1

    fetched = fetch_snapshot(guides_dir) if args.fetch else None
    if args.file:
        payloads = load_payloads(guides_dir, args.file)
    elif fetched is not None:
        payloads = load_payloads(guides_dir, fetched)
    else:
        payloads = load_payloads(guides_dir, None)

    if not payloads:
        print(f"в {guides_dir} нет ни одного снапшота (кроме образца контракта)")
        return 1

    return asyncio.run(ingest(payloads, args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
