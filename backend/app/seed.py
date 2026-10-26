"""Инициализация БД: идемпотентные миграции, сидирование отелей, запись фич."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from geoalchemy2.elements import WKTElement
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

logger = logging.getLogger(__name__)


async def ensure_schema(engine) -> None:
    """Колонки, которые ``create_all`` не добавляет в уже существующую таблицу."""
    statements = (
        "ALTER TABLE hotel_features ADD COLUMN IF NOT EXISTS disputed BOOLEAN DEFAULT FALSE",
        "ALTER TABLE hotel_features ADD COLUMN IF NOT EXISTS disputed_with JSONB",
    )
    async with engine.begin() as conn:
        for statement in statements:
            await conn.execute(text(statement))


def _floors(tags: dict, explicit=None) -> int:
    """Этажность: явное поле GeoJSON важнее тегов OSM."""
    raw = explicit if explicit is not None else (tags.get("building:levels") or tags.get("levels"))
    try:
        return max(1, int(float(str(raw).replace(",", "."))))
    except (TypeError, ValueError):
        return 3


def _address(tags: dict) -> str | None:
    street = tags.get("addr:street")
    number = tags.get("addr:housenumber")
    if street and number:
        return f"{_fix_mojibake(street)}, {number}"
    return _fix_mojibake(street) or None


def _fix_mojibake(value: str | None) -> str | None:
    """Чинит текст, декодированный shapefile-драйвером не в той кодировке.

    Экстракт Geofabrik отдаёт DBF без гарантированной кодировки, поэтому
    кириллические названия иногда приходят как «ÐÐµÐ»Ñ». Обратное
    преобразование возвращает читаемый текст.
    """
    if not value:
        return value
    if not any(marker in value for marker in ("Ð", "Ñ", "Ã", "Â")):
        return value
    try:
        return value.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value


async def seed_hotels(session: AsyncSession, path: str | None = None) -> int:
    """Создаёт или обновляет отели из hotels.geojson (идемпотентно по osm_id)."""
    from app.models import Hotel

    source = path or settings.HOTELS_PATH
    try:
        with open(source, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        logger.warning("Нет файла отелей %s — таблица останется пустой", source)
        return 0

    payload: list[dict] = []
    for feature in data.get("features") or []:
        props = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        coords = geometry.get("coordinates")
        if not coords or len(coords) < 2:
            continue

        tags = props.get("tags") or {}
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except json.JSONDecodeError:
                tags = {}

        lon, lat = float(coords[0]), float(coords[1])
        payload.append(
            {
                "osm_id": int(props["osm_id"]) if props.get("osm_id") else None,
                "name": _fix_mojibake(props.get("name")) or "Без названия",
                "address": _address(tags),
                "geom": WKTElement(f"POINT({lon} {lat})", srid=4326),
                "floors": _floors(tags, props.get("floors")),
            }
        )

    if not payload:
        return 0

    known = {
        row.osm_id: row
        for row in (await session.execute(select(Hotel))).scalars().all()
        if row.osm_id is not None
    }

    touched = 0
    for item in payload:
        osm_id = item.pop("osm_id")
        if osm_id is None:
            session.add(Hotel(**item))
            touched += 1
            continue
        row = known.get(osm_id)
        if row is None:
            session.add(Hotel(osm_id=osm_id, **item))
        else:
            for field, value in item.items():
                setattr(row, field, value)
        touched += 1

    await session.commit()
    logger.info("hotels: синхронизировано %s записей", touched)
    return touched


async def upsert_feature(
    session: AsyncSession,
    *,
    hotel_id: int,
    feature_key: str,
    value,
    source: str,
    confidence: float,
    evidence: dict | None = None,
    ttl_days: int = 180,
) -> None:
    """Заменяет значение характеристики от того же источника (одна строка на источник).

    Разные источники сосуществуют — это позволяет замечать противоречия:
    геоданные и ответ отельера хранятся отдельными записями.
    """
    from app.models import HotelFeature

    await session.execute(
        delete(HotelFeature).where(
            HotelFeature.hotel_id == hotel_id,
            HotelFeature.feature_key == feature_key,
            HotelFeature.source == source,
        )
    )
    session.add(
        HotelFeature(
            hotel_id=hotel_id,
            feature_key=feature_key,
            value=value,
            source=source,
            confidence=confidence,
            raw_evidence=evidence,
            # Колонка объявлена как TIMESTAMP WITHOUT TIME ZONE — храним naive UTC.
            expires_at=datetime.utcnow() + timedelta(days=ttl_days),
        )
    )
