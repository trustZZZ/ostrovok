"""Реестр характеристик: нормализация ответов, пороги поиска, разрешение противоречий.

Держим три инварианта, на которых стоит доверие к значениям:

* свободный ответ отельера приводится к типу характеристики, а не хранится как текст;
* пожелание гостя не превращается в невыполнимый порог (шум 0/100 отсекает всё);
* расхождение источников разрешается по правилам реестра, а не по порядку строк в БД.

Тесты работают на данных features.yaml и не требуют ни БД, ни сети, ни DEM.
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from app.feature_registry import (
    SearchRule,
    is_no_data,
    load_registry,
    resolve_rows,
    source_kind,
)


def make_row(source: str, value, confidence: float = 0.5, computed_at=None):
    """Строка характеристики в том виде, в каком её видит resolve_rows."""
    return SimpleNamespace(
        source=source,
        value=value,
        confidence=confidence,
        computed_at=computed_at,
    )


# --- приведение ответа отельера к типу характеристики ---------------------


def test_boolean_coercion_reads_head_of_answer():
    spec = load_registry()["room_balcony"]
    assert spec.coerce(True) is True
    assert spec.coerce("Да, в люксе и апартаментах", "Да, есть") is True
    assert spec.coerce("Нет, балконов нет", "Нет") is False


def test_boolean_coercion_handles_enumeration_without_yes_word():
    """«Люкс и Апартаменты» — это «да», а не строка вместо boolean."""
    spec = load_registry()["room_balcony"]
    assert spec.coerce("Люкс и Апартаменты", "Есть в люксе") is True


def test_boolean_coercion_detects_negation_inside_answer():
    spec = load_registry()["pet_friendly"]
    assert spec.coerce("К сожалению, животных не принимаем", "") is False


def test_number_coercion_accepts_comma_and_keeps_non_numbers():
    spec = load_registry()["walk_to_sea"]
    assert spec.coerce(7) == 7
    assert spec.coerce("12") == 12
    assert spec.coerce("12,5") == 12.5
    assert spec.coerce("не знаю") == "не знаю"


def test_extract_uses_value_field_from_registry():
    registry = load_registry()
    assert registry["sunset_view"].extract({"visible": False, "from_floor": 4}) is False
    assert registry["noise_score"].extract({"score": 31}) == 31
    assert registry["sunset_view"].extract(True) is True


# --- пороги поиска --------------------------------------------------------


def test_search_rule_clamps_thresholds_to_registry_bounds():
    spec = load_registry()["noise_score"]
    # «тихо» не означает 0: такой порог отсекает все отели подряд.
    assert spec.search.clamp(0) == 10
    assert spec.search.clamp(150) == 100
    assert spec.search.clamp(35) == 35
    assert spec.search.clamp(35.0) == 35


def test_search_rule_clamp_leaves_non_numbers_alone():
    spec = load_registry()["noise_score"]
    assert spec.search.clamp(True) is True
    assert spec.search.clamp(None) is None
    assert spec.search.clamp("тихо") == "тихо"


def test_matches_requires_a_real_value():
    rule = SearchRule(op="<=")
    assert rule.matches(35, 20) is True
    assert rule.matches(35, 45) is False
    assert rule.matches(35, None) is False
    assert rule.matches(35, "нет данных") is False


def test_matches_supports_both_numeric_operators_and_boolean():
    assert SearchRule(op=">=").matches(22, 24) is True
    assert SearchRule(op=">=").matches(22, 18) is False
    assert SearchRule().matches(True, True) is True
    assert SearchRule().matches(True, False) is False


# --- разрешение противоречий ---------------------------------------------


def test_resolve_rows_prefers_authoritative_source():
    """Для измеримой характеристики гео важнее ответа отельера."""
    spec = load_registry()["sunset_view"]
    geo = make_row("geo:sunset_view", {"visible": True}, 0.62, datetime(2024, 1, 1))
    hotelier = make_row("hotelier:sunset_view", {"visible": False}, 0.95, datetime(2025, 1, 1))
    assert resolve_rows([hotelier, geo], spec) is geo


def test_resolve_rows_uses_confidence_then_freshness_on_tie():
    spec = load_registry()["sunset_view"]
    low = make_row("geo", {"visible": False}, 0.4, datetime(2025, 1, 1))
    high = make_row("geo", {"visible": True}, 0.8, datetime(2024, 1, 1))
    assert resolve_rows([low, high], spec) is high

    older = make_row("geo", {"visible": False}, 0.6, datetime(2024, 1, 1))
    newer = make_row("geo", {"visible": True}, 0.6, datetime(2025, 1, 1))
    assert resolve_rows([older, newer], spec) is newer


def test_no_data_stub_does_not_win_over_a_fact():
    spec = load_registry()["sunset_view"]
    stub = make_row("geo", {"status": "no_data"}, 0.9, datetime(2025, 6, 1))
    fact = make_row("hotelier", {"visible": False}, 0.55, datetime(2020, 1, 1))
    assert is_no_data(stub.value)
    assert resolve_rows([stub, fact], spec) is fact
    assert resolve_rows([], spec) is None


def test_zero_confidence_row_is_ignored_when_a_fact_exists():
    spec = load_registry()["noise_score"]
    zero = make_row("hotelier", {"score": 90}, 0.0, datetime(2025, 1, 1))
    fact = make_row("geo", {"score": 30}, 0.5, datetime(2024, 1, 1))
    assert resolve_rows([zero, fact], spec) is fact


def test_source_kind_classifies_rows():
    assert source_kind("hotelier:pet_friendly") == "hotelier"
    assert source_kind("Open-Meteo") == "geo"
    assert source_kind(None) == "geo"


# --- сам реестр -----------------------------------------------------------


def test_registry_declares_authoritative_source_per_feature():
    registry = load_registry()
    assert registry["sunset_view"].authoritative == "geo"
    assert registry["pet_friendly"].authoritative == "hotelier"
    assert registry["room_balcony"].target == "room"


def test_registry_knows_which_features_ask_the_hotelier():
    registry = load_registry()
    assert registry["pet_friendly"].asks_hotelier is True
    # Климат считается по Open-Meteo, спрашивать отельера не о чем.
    assert registry["climate_summer"].asks_hotelier is False


def test_registry_thresholds_are_ordered():
    """min < max: иначе clamp вывернул бы порог наизнанку."""
    for spec in load_registry().values():
        if spec.search.min_value is not None and spec.search.max_value is not None:
            assert spec.search.min_value < spec.search.max_value, spec.key


def test_registry_contains_the_features_search_relies_on():
    registry = load_registry()
    for key in ("sunset_view", "noise_score", "walk_to_sea", "climate_summer"):
        assert key in registry
        assert registry[key].tools, f"{key}: характеристика должна считаться по данным"
