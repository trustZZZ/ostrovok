"""План агента объясняет, откуда берётся значение характеристики.

Путей поставки значения три: инструмент, ответ отельера и внешний ingest
(партнёрские обзоры). Первые два уже были различимы, третий описывался как
«спросим отельера» — для характеристики из обзоров это неверно и вводит
в заблуждение в аудите `tool_selection` и в логе прогона.
"""
from __future__ import annotations

import asyncio

from app.agents.graph import node_plan


def _audit() -> dict[str, str]:
    """Причины из плана: {ключ характеристики: причина}."""
    plan = asyncio.run(node_plan({"hotel_id": 1, "log": []}))
    return {item["feature"]: item["reason"] for item in plan["tool_selection"]}


def test_external_source_is_not_reported_as_hotelier_question():
    audit = _audit()

    assert "внешн" in audit["sunset_spot_nearby"]
    assert "отельера" not in audit["sunset_spot_nearby"]


def test_hotelier_only_feature_keeps_question_reason():
    audit = _audit()

    assert "отельера" in audit["pet_friendly"]
    assert "внешн" not in audit["pet_friendly"]


def test_feature_with_tool_reports_selected_tool():
    audit = _audit()

    assert audit["sunset_view"].startswith("выбраны инструменты")
    assert "sunset_view" in audit["sunset_view"]
