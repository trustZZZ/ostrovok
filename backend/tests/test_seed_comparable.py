"""Сравнение значений источников для детекции противоречий.

У источников разные структуры значения: гео кладёт floor и months, отельер —
только сам факт. Противоречием считается расхождение по value_field из
реестра, иначе любая разница в деталях помечала бы характеристики как
спорные и кабинет отельера утонул бы в ложных конфликтах.
"""
from __future__ import annotations

from app.seed import _comparable


def test_comparable_uses_registry_value_field():
    assert _comparable("sunset_view", {"visible": True, "from_floor": 5}) is True
    assert _comparable("noise_score", {"score": 42, "level": "тихо"}) == 42
    assert _comparable("walk_to_sea", {"minutes": 12, "crosses_highway": False}) == 12
    assert _comparable("pet_friendly", {"allowed": False}) is False


def test_comparable_ignores_fields_other_than_value_field():
    geo = {"visible": True, "from_floor": 5, "months": [4, 5, 6]}
    hotelier = {"visible": True, "from_floor": 3}
    assert _comparable("sunset_view", geo) == _comparable("sunset_view", hotelier)


def test_comparable_passes_scalars_and_unknown_features_through():
    assert _comparable("sunset_view", True) is True
    assert _comparable("unknown_feature", {"any": 1}) == {"any": 1}
