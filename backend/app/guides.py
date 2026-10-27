"""Приём партнёрских обзоров и превращение их в характеристики отелей.

Партнёрский сервис отдаёт обзоры блогеров (контракт — ``data/guides/CONTRACT.md``),
из которых строится характеристика ``sunset_spot_nearby``: «место, где
встречают закат, в пешей доступности от отеля».

Три правила живут здесь и только здесь:

1. Факт без провенанса не принимается. Нет ссылки, автора, даты или цитаты —
   запись отклоняется: «обзор так сказал» без ссылки неотличимо от выдумки
   языковой модели, а ТЗ называет такое решение нерешением.
2. Уверенность считаем мы, а не партнёр. Она зависит от числа независимых
   авторов (перепечатка одного текста — не второе подтверждение) и от того,
   подтверждено ли место в OSM. Присланный партнёром confidence создал бы
   второй источник истины и повисший вопрос «почему вы уверены».
3. Расстояние до места считает пеший маршрут (``app/tools/walk_to_sea``),
   а не прямая: гость идёт по улицам, а не по воде.

Модуль чистый: ни БД, ни сети. Запись в ``hotel_features`` — в
``scripts/ingest_guides.py``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

SUPPORTED_SCHEMA_VERSIONS = ("1.0",)

# Таксономия партнёра → ключ характеристики в нашем реестре.
# Партнёру не нужно знать про features.yaml: маппинг живёт у нас, поэтому
# его словарь эмоций может меняться независимо от нашего реестра.
EMOTION_TO_FEATURE: dict[str, str] = {
    "sunset_spot": "sunset_spot_nearby",
}
FEATURE_TO_EMOTION: dict[str, str] = {value: key for key, value in EMOTION_TO_FEATURE.items()}

VALID_STATUS = ("active", "retracted")


@dataclass(frozen=True)
class Review:
    """Один обзор одного места — минимальная единица доказательства."""

    guide_id: str
    author_id: str
    author_name: str
    url: str
    published_at: str
    quote: str
    locator: dict[str, Any] | None
    salience: float
    emotion_key: str
    place_key: str
    place_name: str
    lon: float
    lat: float
    osm: dict[str, Any] | None
    months: tuple[int, ...]
    time_of_day: tuple[str, ...]


@dataclass(frozen=True)
class Batch:
    partner_id: str
    partner_name: str
    license: str
    attribution_required: bool
    schema_version: str
    reviews: tuple[Review, ...]
    retracted_guides: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlaceEmotion:
    """Место, подтверждённое обзорами, в разрезе одной эмоции."""

    place_key: str
    place_name: str
    lon: float
    lat: float
    osm_verified: bool
    reviews: int  # число независимых авторов, а не упоминаний
    score: float  # средний salience: насколько обзоры связывают место с эмоцией
    months: tuple[int, ...]
    time_of_day: tuple[str, ...]
    attribution: tuple[dict[str, Any], ...]


# ---------------------------------------------------------------------------
# Разбор и валидация контракта
# ---------------------------------------------------------------------------
def _require(mapping: dict[str, Any], key: str, path: str, issues: list[str]) -> Any:
    value = mapping.get(key)
    if value in (None, "", [], {}):
        issues.append(f"{path}: обязательное поле «{key}» отсутствует")
        return None
    return value


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _months(raw: Any) -> tuple[int, ...]:
    if not isinstance(raw, list):
        return ()
    months = {int(item) for item in raw if isinstance(item, (int, float)) and 1 <= int(item) <= 12}
    return tuple(sorted(months))


def _strings(raw: Any) -> tuple[str, ...]:
    if not isinstance(raw, list):
        return ()
    return tuple(str(item) for item in raw if isinstance(item, str))


def _bbox(payload: dict[str, Any]) -> tuple[float, float, float, float] | None:
    """Границы региона из пакета: (min_lon, min_lat, max_lon, max_lat)."""
    raw = (payload.get("region") or {}).get("bbox")
    if not isinstance(raw, list) or len(raw) != 4:
        return None
    values = [_as_float(item) for item in raw]
    if any(value is None for value in values):
        return None
    return (values[0], values[1], values[2], values[3])  # type: ignore[return-value]


def parse_batch(payload: Any) -> tuple[Batch | None, list[str]]:
    """Проверяет ответ партнёра по контракту.

    Возвращает разобранный пакет и список отклонённых записей. Пакет
    возвращается даже при частичных ошибках: изоляция дефектного обзора
    важнее принципа «всё или ничего», иначе одна битая запись блокирует
    обновление остальных. Полный отказ (``None``) — только когда непонятно,
    чей это пакет или какая версия схемы.
    """
    issues: list[str] = []
    if not isinstance(payload, dict):
        return None, ["ответ не является JSON-объектом"]

    schema = str(payload.get("schema_version") or "")
    if schema not in SUPPORTED_SCHEMA_VERSIONS:
        return None, [
            f"schema_version «{schema}» не поддерживается "
            f"(ожидается {SUPPORTED_SCHEMA_VERSIONS[0]})"
        ]

    partner = payload.get("partner") or {}
    partner_id = _require(partner, "id", "partner", issues)
    if not partner_id:
        return None, issues

    bbox = _bbox(payload)
    reviews: list[Review] = []
    retracted: list[str] = []
    for index, guide in enumerate(payload.get("guides") or []):
        reviews.extend(_parse_guide(guide, index, bbox, issues, retracted))

    batch = Batch(
        partner_id=str(partner_id),
        partner_name=str(partner.get("name") or partner_id),
        license=str(partner.get("license") or ""),
        attribution_required=bool(partner.get("attribution_required", False)),
        schema_version=schema,
        reviews=tuple(reviews),
        retracted_guides=tuple(retracted),
    )
    if batch.attribution_required and not batch.license:
        issues.append("partner: атрибуция обязательна, но license не указана")
    return batch, issues


def _parse_guide(
    guide: Any,
    index: int,
    bbox: tuple[float, float, float, float] | None,
    issues: list[str],
    retracted: list[str],
) -> list[Review]:
    path = f"guides[{index}]"
    if not isinstance(guide, dict):
        issues.append(f"{path}: не объект")
        return []

    status = str(guide.get("status") or "active")
    if status not in VALID_STATUS:
        issues.append(f"{path}.status: «{status}» не поддерживается")
        return []

    guide_id = _require(guide, "id", path, issues)
    # Ревизия и updated_at обязательны: без них повторный приём снапшота
    # нельзя отличить от новой версии обзора.
    _require(guide, "revision", path, issues)
    _require(guide, "updated_at", path, issues)

    author = guide.get("author") if isinstance(guide.get("author"), dict) else {}
    author_id = _require(author, "id", f"{path}.author", issues)

    if status == "retracted":
        # Снятый обзор — это тоже факт: место из него больше не подтверждено.
        # Цитаты и координаты для него не требуются.
        if guide_id:
            retracted.append(str(guide_id))
        return []

    url = _require(guide, "url", path, issues)
    published_at = _require(guide, "published_at", path, issues)
    if not (guide_id and author_id and url and published_at):
        return []

    reviews: list[Review] = []
    for place_index, place in enumerate(guide.get("places") or []):
        reviews.extend(
            _parse_place(
                place,
                f"{path}.places[{place_index}]",
                bbox,
                issues,
                guide_id=str(guide_id),
                author_id=str(author_id),
                author_name=str(author.get("name") or author_id),
                url=str(url),
                published_at=str(published_at),
            )
        )
    return reviews


def _parse_place(
    place: Any,
    path: str,
    bbox: tuple[float, float, float, float] | None,
    issues: list[str],
    *,
    guide_id: str,
    author_id: str,
    author_name: str,
    url: str,
    published_at: str,
) -> list[Review]:
    if not isinstance(place, dict):
        issues.append(f"{path}: не объект")
        return []

    place_key = _require(place, "key", path, issues)
    place_name = str(place.get("name") or place_key or "")

    coordinates = place.get("coordinates") if isinstance(place.get("coordinates"), dict) else {}
    lat = _as_float(coordinates.get("lat"))
    lon = _as_float(coordinates.get("lon"))
    if lat is None or lon is None:
        issues.append(f"{path}.coordinates: нужны числовые lat и lon")
        return []
    if bbox and not (bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]):
        # Точка вне региона почти всегда означает перепутанные lat/lon
        # или чужой город: привязывать её к нашим отелям нельзя.
        issues.append(f"{path}.coordinates: точка вне региона {bbox}")
        return []
    if not place_key:
        return []

    osm = place.get("osm") if isinstance(place.get("osm"), dict) else None
    reviews: list[Review] = []
    for emotion_index, emotion in enumerate(place.get("emotions") or []):
        emotion_path = f"{path}.emotions[{emotion_index}]"
        if not isinstance(emotion, dict):
            issues.append(f"{emotion_path}: не объект")
            continue

        emotion_key = str(emotion.get("key") or "")
        if emotion_key not in EMOTION_TO_FEATURE:
            issues.append(f"{emotion_path}.key: эмоция «{emotion_key}» неизвестна")
            continue

        salience = _as_float(emotion.get("salience"))
        if salience is None or not 0.0 <= salience <= 1.0:
            issues.append(f"{emotion_path}.salience: нужно число 0..1")
            continue

        quote = str(emotion.get("quote") or "").strip()
        if not quote:
            issues.append(f"{emotion_path}.quote: без цитаты факт не принимается")
            continue

        reviews.append(
            Review(
                guide_id=guide_id,
                author_id=author_id,
                author_name=author_name,
                url=url,
                published_at=published_at,
                quote=quote,
                locator=emotion.get("quote_locator")
                if isinstance(emotion.get("quote_locator"), dict)
                else None,
                salience=salience,
                emotion_key=emotion_key,
                place_key=str(place_key),
                place_name=place_name,
                lon=lon,
                lat=lat,
                osm=osm,
                months=_months(emotion.get("best_months")),
                time_of_day=_strings(emotion.get("time_of_day")),
            )
        )
    return reviews


# ---------------------------------------------------------------------------
# Агрегация: несколько обзоров → один факт об отеле
# ---------------------------------------------------------------------------
def place_emotions(reviews: Iterable[Review], feature_key: str) -> list[PlaceEmotion]:
    """Склеивает обзоры по местам: одна точка — одно подтверждение.

    Считаем независимых авторов, а не упоминания. Два обзора одного человека
    не делают факт достовернее, а перепечатка чужого текста — тем более.
    """
    emotion_key = FEATURE_TO_EMOTION.get(feature_key)
    if emotion_key is None:
        return []

    grouped: dict[str, list[Review]] = {}
    for review in reviews:
        if review.emotion_key == emotion_key:
            grouped.setdefault(review.place_key, []).append(review)

    places: list[PlaceEmotion] = []
    for place_key, group in grouped.items():
        by_author: dict[str, Review] = {}
        for review in group:
            current = by_author.get(review.author_id)
            if current is None or review.salience > current.salience:
                by_author[review.author_id] = review

        strongest = max(by_author.values(), key=lambda item: item.salience)
        score = sum(item.salience for item in by_author.values()) / len(by_author)
        months = {month for item in by_author.values() for month in item.months}
        time_of_day = {part for item in by_author.values() for part in item.time_of_day}

        places.append(
            PlaceEmotion(
                place_key=place_key,
                place_name=strongest.place_name,
                lon=strongest.lon,
                lat=strongest.lat,
                osm_verified=any(item.osm is not None for item in by_author.values()),
                reviews=len(by_author),
                score=round(score, 2),
                # Пустой список месяцев означает «круглый год»: иначе место
                # выпадало бы из выдачи из-за отсутствия поля, а не из-за факта.
                months=tuple(sorted(months)) or tuple(range(1, 13)),
                time_of_day=tuple(sorted(time_of_day)),
                attribution=tuple(
                    {
                        "guide_id": item.guide_id,
                        "author": item.author_name,
                        "author_id": item.author_id,
                        "url": item.url,
                        "published_at": item.published_at,
                        "quote": item.quote,
                        "quote_locator": item.locator,
                        "salience": item.salience,
                    }
                    for item in sorted(by_author.values(), key=lambda it: -it.salience)
                ),
            )
        )
    return places


def confidence_for(reviews: int, osm_verified: bool) -> float:
    """Насколько мы верим факту: один обзор — 0.65, три — 0.95.

    Ниже 0.5 не опускаемся: такой факт не прошёл бы min_confidence из
    реестра и не попал бы в поиск, а показывать «наполовину подтверждённое»
    рядом с вычисленными характеристиками нечестно.
    """
    value = 0.45 + 0.15 * min(reviews, 3) + (0.05 if osm_verified else 0.0)
    return round(min(value, 0.95), 2)


def best_place(
    candidates: Iterable[tuple[PlaceEmotion, dict[str, Any]]],
    max_minutes: float = 20.0,
) -> tuple[PlaceEmotion, dict[str, Any]] | None:
    """Лучшее место рядом с отелем: сначала выраженность эмоции, потом близость.

    Двадцати минут достаточно, чтобы «рядом» оставалось правдой: точка
    в получасе пешком — уже отдельный маршрут, а не свойство отеля.
    """
    usable = [
        (place, route)
        for place, route in candidates
        if route.get("minutes") is not None and float(route["minutes"]) <= max_minutes
    ]
    if not usable:
        return None
    return max(usable, key=lambda item: (item[0].score, -float(item[1]["minutes"])))


def build_value(place: PlaceEmotion, route: dict[str, Any]) -> dict[str, Any]:
    """Значение характеристики: score для поиска и контекст для карточки."""
    return {
        "score": place.score,
        "nearest_minutes": round(float(route["minutes"]), 1),
        "distance_m": route.get("distance_m"),
        "crosses_highway": route.get("crosses_highway"),
        "reviews": place.reviews,
        "place_key": place.place_key,
        "place_name": place.place_name,
        "osm_verified": place.osm_verified,
        "best_months": list(place.months),
        "time_of_day": list(place.time_of_day),
    }


def build_evidence(batch: Batch, place: PlaceEmotion, feature_key: str) -> dict[str, Any]:
    """Провенанс значения: кто это сказал, где и когда."""
    return {
        "partner": {
            "id": batch.partner_id,
            "name": batch.partner_name,
            "license": batch.license,
        },
        "attribution_required": batch.attribution_required,
        "emotion": FEATURE_TO_EMOTION.get(feature_key),
        "definition": "место, где встречают закат, в пешей доступности от отеля",
        "reviews": list(place.attribution),
        "method": "walking route (app/tools/walk_to_sea)",
    }
