"""Разбор пожелания гостя в пороги характеристик.

LLM — не единственный путь: при выключенной модели запрос разбирается по
ключевым словам. Этот режим должен находить те же характеристики и не
выдумывать пороги, которые отсекают всю выдачу.
"""
from __future__ import annotations

from app.search_engine import KEYWORD_INTENT, _clamp_intent, _keyword_intent


def test_keyword_intent_parses_the_query_from_the_track():
    query = "Тихий номер с видом на закат недалеко от моря"
    intent = _keyword_intent(query)

    assert intent["sunset_view"] is True
    assert intent["noise_score"] == 35
    assert intent["walk_to_sea"] == 15
    assert intent["room_west_windows"] is True
    assert intent["room_silence"] is True


def test_keyword_intent_is_case_insensitive():
    assert _keyword_intent("оТЕЛЬ У МОРЯ")["walk_to_sea"] == 15


def test_keyword_intent_returns_nothing_for_unrelated_query():
    assert _keyword_intent("хочу красивый отель в центре") == {}


def test_clamp_intent_keeps_thresholds_meaningful():
    clamped = _clamp_intent({"noise_score": 0, "walk_to_sea": 999, "sunset_view": True})
    assert clamped["noise_score"] == 10
    assert clamped["walk_to_sea"] == 180
    assert clamped["sunset_view"] is True


def test_clamp_intent_passes_unknown_keys_through():
    assert _clamp_intent({"unknown_feature": 1}) == {"unknown_feature": 1}


def test_keyword_intent_keys_exist_in_registry():
    """Ключевое слово без характеристики в реестре — молча потерянное пожелание."""
    from app.feature_registry import load_registry

    registry = load_registry()
    missing = sorted(set(KEYWORD_INTENT) - set(registry))
    assert missing == [], f"нет в features.yaml: {missing}"
