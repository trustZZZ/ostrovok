"""Инициализация БД: идемпотентные миграции, сидирование отелей, запись фич."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from geoalchemy2.elements import WKTElement
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.feature_registry import get_feature

logger = logging.getLogger(__name__)


async def ensure_schema(engine) -> None:
    """Колонки, которые ``create_all`` не добавляет в уже существующую таблицу."""
    statements = (
        "ALTER TABLE hotel_features ADD COLUMN IF NOT EXISTS disputed BOOLEAN DEFAULT FALSE",
        "ALTER TABLE hotel_features ADD COLUMN IF NOT EXISTS disputed_with JSONB",
        # Раньше инструмент климата подписывал успех иначе, чем ошибку
        # («Open-Meteo (ERA5, 2019-2024)» против «Open-Meteo»), из-за чего
        # в таблице копились дубли одной характеристики. Приводим имя к
        # каноническому и оставляем по одной строке на источник: это
        # инвариант, на который опирается детекция противоречий.
        "UPDATE hotel_features SET source = 'Open-Meteo' WHERE source LIKE 'Open-Meteo (%'",
        (
            "DELETE FROM hotel_features a USING hotel_features b "
            "WHERE a.hotel_id = b.hotel_id AND a.feature_key = b.feature_key "
            "AND a.source = b.source AND a.id < b.id"
        ),
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
    seen = {item.get("osm_id") for item in payload}
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

    # Файл отелей — источник истины для демо-набора: гостиницы, которых в нём
    # больше нет, удаляются вместе с характеристиками. Иначе после смены
    # набора в выдаче остались бы отели, которых не существует.
    for osm_id, row in known.items():
        if osm_id in seen:
            continue
        logger.info("hotel удалён: %s (osm_id %s) — его нет в файле отелей", row.name, osm_id)
        await session.delete(row)
        touched += 1

    await session.commit()
    logger.info("hotels: синхронизировано %s записей", touched)
    return touched


def _comparable(feature_key: str, value):
    """Сопоставимая часть значения: для сравнения источников между собой.

    Полные структуры у источников разные (геоданные кладут from_floor и months,
    отельер — только факт), поэтому сравниваем по value_field из реестра.
    """
    spec = get_feature(feature_key)
    return spec.extract(value) if spec else value


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
    геоданные и ответ отельера хранятся отдельными записями. Если их значения
    расходятся, обе строки помечаются ``disputed``, а ``disputed_with`` хранит
    все варианты: разбирается это в кабинете отельера, а не замалчивается.
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
    await session.flush()

    rows = (
        (
            await session.execute(
                select(HotelFeature).where(
                    HotelFeature.hotel_id == hotel_id,
                    HotelFeature.feature_key == feature_key,
                )
            )
        )
        .scalars()
        .all()
    )

    meaningful = [row for row in rows if (row.confidence or 0) > 0]
    variants = {
        json.dumps(_comparable(feature_key, row.value), sort_keys=True, ensure_ascii=False, default=str)
        for row in meaningful
    }
    disputed = len(variants) > 1

    snapshot = None
    if disputed:
        snapshot = [
            {
                "source": row.source,
                "confidence": round(float(row.confidence or 0), 3),
                "value": _comparable(feature_key, row.value),
            }
            for row in meaningful
        ]

    for row in rows:
        row.disputed = disputed
        row.disputed_with = snapshot

    if disputed:
        logger.info(
            "противоречие источников: отель %s, «%s», вариантов %s",
            hotel_id,
            feature_key,
            len(variants),
        )
