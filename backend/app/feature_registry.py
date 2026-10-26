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

    @property
    def asks_hotelier(self) -> bool:
        return bool(self.question.strip())

    def extract(self, value: Any) -> Any:
        """Достаёт сопоставимое значение из произвольной структуры value."""
        if isinstance(value, dict):
            return value.get(self.value_field)
        return value


def _parse(key: str, raw: dict[str, Any]) -> FeatureSpec:
    search_raw = raw.get("search") or {}
    return FeatureSpec(
        key=key,
        title=raw.get("title", key),
        description=" ".join(str(raw.get("description", "")).split()),
        target=raw.get("target", "hotel"),
        value_type=raw.get("value_type", "boolean"),
        value_field=raw.get("value_field", "value"),
        ttl_days=int(raw.get("ttl_days", 180)),
        min_confidence=float(raw.get("min_confidence", 0.5)),
        tools=tuple(raw.get("tools") or ()),
        question=str(raw.get("question") or ""),
        search=SearchRule(op=search_raw.get("op", "=="), hint=search_raw.get("hint", "")),
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
