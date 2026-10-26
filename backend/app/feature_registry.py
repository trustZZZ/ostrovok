"""Реестр характеристик, описанный данными (features.yaml).

Добавление характеристики не требует правки графа или поиска: достаточно
блока в YAML и, при необходимости, инструмента в app/collectors.py.
Если инструмента нет, характеристика уходит в вопрос отельеру.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

REGISTRY_PATH = Path(__file__).with_name("features.yaml")


@dataclass(frozen=True)
class SearchRule:
    """Как пожелание пользователя проецируется на значение характеристики."""

    op: str = "=="  # "==", "<=", ">="
    hint: str = ""
    min_value: float | None = None
    max_value: float | None = None

    def clamp(self, wanted: Any) -> Any:
        """Держит порог в разумных границах.

        Модель охотно отвечает «шум 0» на просьбу «тихо», но шума 0/100
        не бывает: такой порог отсекает все отели и обесценивает выдачу.
        Границы заданы в реестре рядом с характеристикой.
        """
        if isinstance(wanted, bool) or not isinstance(wanted, (int, float)):
            return wanted
        if self.min_value is not None:
            wanted = max(self.min_value, wanted)
        if self.max_value is not None:
            wanted = min(self.max_value, wanted)
        return int(wanted) if float(wanted).is_integer() else wanted

    def matches(self, wanted: Any, actual: Any) -> bool:
        if actual is None:
            return False
        try:
            if self.op == "<=":
                return float(actual) <= float(wanted)
            if self.op == ">=":
                return float(actual) >= float(wanted)
        except (TypeError, ValueError):
            return False
        return bool(actual) == bool(wanted)


@dataclass(frozen=True)
class FeatureSpec:
    key: str
    title: str
    description: str
    target: str
    value_type: str
    value_field: str
    ttl_days: int
    min_confidence: float
    tools: tuple[str, ...]
    question: str
    search: SearchRule
    authoritative: str = "geo"

    @property
    def asks_hotelier(self) -> bool:
        return bool(self.question.strip())

    def extract(self, value: Any) -> Any:
        """Достаёт сопоставимое значение из произвольной структуры value."""
        if isinstance(value, dict):
            return value.get(self.value_field)
        return value


def source_kind(source: str | None) -> str:
    """Классифицирует источник: ответ отельера или вычисленные данные."""
    return "hotelier" if "hotelier" in (source or "").lower() else "geo"


def is_no_data(value: Any) -> bool:
    """Значение-заглушка «данных нет» — это не факт об отеле."""
    return isinstance(value, dict) and value.get("status") == "no_data"


def resolve_rows(rows: list[Any], spec: FeatureSpec) -> Any | None:
    """Выбирает достоверное значение среди строк разных источников.

    Правила разрешения противоречия:
      1. авторитетный источник для этой характеристики (для измеримых — гео,
         для субъективных — отельер) важнее любого другого;
      2. при равенстве — выше уверенность;
      3. при равенстве — свежее вычисление.

    Строки «нет данных» не участвуют в выборе, пока есть хоть один реальный
    факт: иначе заглушка перебивала бы вычисленное значение.
    """
    if not rows:
        return None

    def rank(row: Any) -> tuple[int, float, float]:
        authoritative = 1 if source_kind(getattr(row, "source", None)) == spec.authoritative else 0
        computed = getattr(row, "computed_at", None)
        return (
            authoritative,
            float(getattr(row, "confidence", 0.0) or 0.0),
            computed.timestamp() if computed else 0.0,
        )

    facts = [
        row
        for row in rows
        if (getattr(row, "confidence", 0.0) or 0.0) > 0
        and not is_no_data(getattr(row, "value", None))
    ]
    if facts:
        return max(facts, key=rank)
    return max(rows, key=rank)


def _parse(key: str, raw: dict[str, Any]) -> FeatureSpec:
    search_raw = raw.get("search") or {}
    tools = tuple(raw.get("tools") or ())
    return FeatureSpec(
        key=key,
        title=raw.get("title", key),
        description=" ".join(str(raw.get("description", "")).split()),
        target=raw.get("target", "hotel"),
        value_type=raw.get("value_type", "boolean"),
        value_field=raw.get("value_field", "value"),
        ttl_days=int(raw.get("ttl_days", 180)),
        min_confidence=float(raw.get("min_confidence", 0.5)),
        tools=tools,
        question=str(raw.get("question") or ""),
        search=SearchRule(
            op=search_raw.get("op", "=="),
            hint=search_raw.get("hint", ""),
            min_value=search_raw.get("min"),
            max_value=search_raw.get("max"),
        ),
        # Что считать правдой при расхождении: вычисленное по данным или
        # ответ отельера. По умолчанию — по природе характеристики.
        authoritative=str(raw.get("authoritative") or ("geo" if tools else "hotelier")),
    )


@lru_cache(maxsize=1)
def load_registry() -> dict[str, FeatureSpec]:
    with REGISTRY_PATH.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    features = data.get("features") or {}
    return {key: _parse(key, raw or {}) for key, raw in features.items()}


def select_features(target: str | None = None) -> list[FeatureSpec]:
    specs = list(load_registry().values())
    if target is not None:
        specs = [spec for spec in specs if spec.target == target]
    return specs


def get_feature(key: str) -> FeatureSpec | None:
    return load_registry().get(key)
