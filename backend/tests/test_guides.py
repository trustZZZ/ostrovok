"""Приём партнёрских обзоров: контракт, доверие, склейка подтверждений.

Тесты держат главное обещание партнёрского слоя: факт без провенанса не
принимается, а уверенность растёт от числа независимых авторов, а не от
количества упоминаний.
"""
from __future__ import annotations

import json
from pathlib import Path

from app import guides

SAMPLE = Path(__file__).resolve().parents[2] / "data" / "guides" / "contract.sample.json"


def _sample() -> dict:
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


def test_sample_contract_is_valid():
    """Образец контракта — рабочий документ, а не иллюстрация."""
    batch, issues = guides.parse_batch(_sample())

    assert issues == []
    assert batch is not None
    assert batch.partner_id == "local-guides"
    assert len(batch.reviews) == 3
    assert {review.place_key for review in batch.reviews} == {
        "zelenogradsk-promenade-viewpoint-3",
        "zelenogradsk-terrace-cafe-more",
    }


def test_review_without_quote_is_rejected():
    payload = _sample()
    payload["guides"][0]["places"][0]["emotions"][0]["quote"] = ""

    batch, issues = guides.parse_batch(payload)

    assert batch is not None
    assert any("quote" in issue for issue in issues)
    assert len(batch.reviews) == 2


def test_review_without_publication_metadata_is_rejected():
    payload = _sample()
    payload["guides"][1]["url"] = ""

    batch, issues = guides.parse_batch(payload)

    assert batch is not None
    assert any("url" in issue for issue in issues)
    # Обзор без ссылки не становится доказательством ни для одного места.
    assert all(review.guide_id != "lg-000145" for review in batch.reviews)


def test_salience_out_of_range_is_rejected():
    payload = _sample()
    payload["guides"][0]["places"][0]["emotions"][0]["salience"] = 1.7

    _batch, issues = guides.parse_batch(payload)

    assert any("salience" in issue for issue in issues)


def test_place_outside_region_is_rejected():
    payload = _sample()
    payload["guides"][0]["places"][0]["coordinates"] = {"lat": 59.93, "lon": 30.31}

    _batch, issues = guides.parse_batch(payload)

    assert any("вне региона" in issue for issue in issues)


def test_unknown_emotion_key_is_rejected():
    payload = _sample()
    payload["guides"][0]["places"][0]["emotions"][0]["key"] = "sunsets_everywhere"

    _batch, issues = guides.parse_batch(payload)

    assert any("неизвестна" in issue for issue in issues)


def test_unsupported_schema_blocks_whole_batch():
    """Неизвестная версия схемы — единственный случай полного отказа."""
    payload = _sample()
    payload["schema_version"] = "2.0"

    batch, issues = guides.parse_batch(payload)

    assert batch is None
    assert any("schema_version" in issue for issue in issues)


def test_retracted_guide_is_not_evidence():
    payload = _sample()
    payload["guides"][1]["status"] = "retracted"

    batch, issues = guides.parse_batch(payload)

    assert batch is not None
    assert issues == []
    assert batch.retracted_guides == ("lg-000145",)
    assert all(review.guide_id != "lg-000145" for review in batch.reviews)


def test_same_author_twice_is_one_confirmation():
    """Перепечатка обзора тем же автором не делает факт достовернее."""
    payload = _sample()
    duplicate = json.loads(json.dumps(payload["guides"][0]))
    duplicate["id"] = "lg-000999"
    payload["guides"].append(duplicate)

    batch, _issues = guides.parse_batch(payload)
    places = guides.place_emotions(batch.reviews, "sunset_spot_nearby")
    viewpoint = next(p for p in places if p.place_key == "zelenogradsk-promenade-viewpoint-3")

    assert viewpoint.reviews == 2
    assert viewpoint.score == 0.88


def test_confidence_grows_with_independent_reviews():
    assert guides.confidence_for(1, False) == 0.6
    assert guides.confidence_for(2, False) == 0.75
    assert guides.confidence_for(2, True) == 0.8
    assert guides.confidence_for(5, True) == 0.95


def _place(key: str, score: float) -> guides.PlaceEmotion:
    return guides.PlaceEmotion(
        place_key=key,
        place_name=key.upper(),
        lon=20.46,
        lat=54.96,
        osm_verified=False,
        reviews=2,
        score=score,
        months=(1,),
        time_of_day=("evening",),
        attribution=(),
    )


def test_best_place_prefers_stronger_emotion_then_closer_point():
    strong = _place("strong", 0.9)
    weak = _place("weak", 0.6)

    assert guides.best_place([(weak, {"minutes": 3}), (strong, {"minutes": 9})])[0] is strong
    chosen = guides.best_place([(strong, {"minutes": 9}), (strong, {"minutes": 3})])
    assert chosen is not None and chosen[1]["minutes"] == 3


def test_place_beyond_walk_limit_is_not_nearby():
    place = _place("far", 0.9)

    assert guides.best_place([(place, {"minutes": 40})]) is None
    assert guides.best_place([(place, {"minutes": None})]) is None


def test_value_and_evidence_keep_provenance():
    batch, _issues = guides.parse_batch(_sample())
    places = guides.place_emotions(batch.reviews, "sunset_spot_nearby")
    viewpoint = next(p for p in places if p.place_key == "zelenogradsk-promenade-viewpoint-3")

    value = guides.build_value(
        viewpoint, {"minutes": 3.44, "distance_m": 260, "crosses_highway": False}
    )
    assert value["score"] == viewpoint.score
    assert value["nearest_minutes"] == 3.4
    assert value["reviews"] == 2

    evidence = guides.build_evidence(batch, viewpoint, "sunset_spot_nearby")
    assert evidence["partner"]["license"] == "CC BY 4.0"
    assert evidence["emotion"] == "sunset_spot"
    assert len(evidence["reviews"]) == 2
    assert all(review["url"].startswith("https://") for review in evidence["reviews"])
    assert all(review["quote"] for review in evidence["reviews"])
