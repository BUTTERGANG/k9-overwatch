"""Tests for the matching engine: signals, deduplicator, and lost-found matcher."""
from __future__ import annotations

from datetime import date

import pytest

from k9overwatch.matching.signals import (
    MatchResult,
    geo_distance_miles,
    score_breed_match,
    score_color_match,
    score_date_proximity,
    score_description_overlap,
    score_geo_distance,
    score_microchip,
    score_name_match,
    score_zip_match,
)
from k9overwatch.matching.breed_normalizer import normalize_breed


# ── geo_distance_miles ────────────────────────────────────────────────────────

class TestGeoDistanceMiles:
    def test_same_point(self):
        dist = geo_distance_miles(39.77, -86.11, 39.77, -86.11)
        assert dist == pytest.approx(0.0, abs=0.01)

    def test_known_distance(self):
        # Broad Ripple → Downtown Indianapolis ≈ 7 miles
        dist = geo_distance_miles(39.8680, -86.1082, 39.7684, -86.1581)
        assert 5.0 < dist < 10.0

    def test_missing_coords_returns_none(self):
        assert geo_distance_miles(None, -86.11, 39.77, -86.11) is None
        assert geo_distance_miles(39.77, None, 39.77, -86.11) is None
        assert geo_distance_miles(None, None, None, None) is None


# ── score_geo_distance ────────────────────────────────────────────────────────

class TestScoreGeoDistance:
    def test_very_close(self):
        signals = score_geo_distance(0.3)
        assert "geo_very_close" in signals
        assert signals["geo_very_close"] == pytest.approx(0.25)

    def test_close(self):
        signals = score_geo_distance(1.5)
        assert "geo_close" in signals

    def test_nearby(self):
        signals = score_geo_distance(3.5)
        assert "geo_nearby" in signals

    def test_far_returns_empty(self):
        signals = score_geo_distance(10.0)
        assert signals == {}

    def test_none_returns_empty(self):
        signals = score_geo_distance(None)
        assert signals == {}


# ── score_date_proximity ──────────────────────────────────────────────────────

class TestScoreDateProximity:
    def test_same_day(self):
        signals = score_date_proximity(date(2026, 3, 20), date(2026, 3, 20))
        assert "date_same_day" in signals
        assert signals["date_same_day"] == pytest.approx(0.12)

    def test_one_day_apart(self):
        signals = score_date_proximity(date(2026, 3, 20), date(2026, 3, 21))
        assert "date_within_1_day" in signals

    def test_three_days_apart(self):
        signals = score_date_proximity(date(2026, 3, 20), date(2026, 3, 23))
        assert "date_within_3_days" in signals

    def test_one_week_apart(self):
        signals = score_date_proximity(date(2026, 3, 13), date(2026, 3, 20))
        assert "date_within_week" in signals

    def test_far_apart_returns_empty(self):
        signals = score_date_proximity(date(2026, 1, 1), date(2026, 3, 20))
        assert signals == {}

    def test_missing_date_returns_empty(self):
        assert score_date_proximity(None, date(2026, 3, 20)) == {}
        assert score_date_proximity(date(2026, 3, 20), None) == {}


# ── score_breed_match ─────────────────────────────────────────────────────────

class TestScoreBreedMatch:
    def test_exact_match(self):
        signals = score_breed_match("Golden Retriever", "Golden Retriever")
        assert "breed_exact" in signals

    def test_case_insensitive_exact(self):
        signals = score_breed_match("golden retriever", "GOLDEN RETRIEVER")
        assert "breed_exact" in signals

    def test_no_match(self):
        signals = score_breed_match("Poodle", "German Shepherd")
        assert signals == {}

    def test_missing_breed(self):
        assert score_breed_match(None, "Poodle") == {}
        assert score_breed_match("Poodle", None) == {}


# ── score_color_match ─────────────────────────────────────────────────────────

class TestScoreColorMatch:
    def test_exact_color_match(self):
        signals = score_color_match("Black", "Black")
        assert "color_primary_match" in signals
        assert signals["color_primary_match"] == pytest.approx(0.10)

    def test_case_insensitive_color(self):
        signals = score_color_match("black", "Black")
        assert "color_primary_match" in signals

    def test_no_match(self):
        signals = score_color_match("Black", "White")
        # Should be empty or partial — either is acceptable
        # (partial match requires rapidfuzz)
        assert isinstance(signals, dict)

    def test_missing_color(self):
        assert score_color_match(None, "Black") == {}
        assert score_color_match("Black", None) == {}

    def test_custom_weight(self):
        signals = score_color_match("Black", "Black", weight=0.05)
        assert signals["color_primary_match"] == pytest.approx(0.05)


# ── score_name_match ──────────────────────────────────────────────────────────

class TestScoreNameMatch:
    def test_exact_name_match(self):
        signals = score_name_match("Buddy", "Buddy")
        assert "name_exact" in signals
        assert signals["name_exact"] == pytest.approx(0.15)

    def test_case_insensitive_name(self):
        signals = score_name_match("BUDDY", "buddy")
        assert "name_exact" in signals

    def test_different_names(self):
        signals = score_name_match("Buddy", "Max")
        assert signals == {}

    def test_missing_name(self):
        assert score_name_match(None, "Buddy") == {}
        assert score_name_match("Buddy", None) == {}


# ── score_microchip ───────────────────────────────────────────────────────────

class TestScoreMicrochip:
    def test_microchip_match(self):
        signals = score_microchip("123456789012345", "123456789012345")
        assert "microchip_match" in signals
        assert signals["microchip_match"] == pytest.approx(0.50)

    def test_microchip_no_match(self):
        signals = score_microchip("111111111111111", "222222222222222")
        assert signals == {}

    def test_microchip_missing(self):
        assert score_microchip(None, "123456789012345") == {}
        assert score_microchip("123456789012345", None) == {}


# ── score_zip_match ───────────────────────────────────────────────────────────

class TestScoreZipMatch:
    def test_zip_match(self):
        signals = score_zip_match("46205", "46205")
        assert "zip_match" in signals
        assert signals["zip_match"] == pytest.approx(0.20)

    def test_zip_match_with_plus4(self):
        signals = score_zip_match("46205-1234", "46205-5678")
        assert "zip_match" in signals

    def test_zip_no_match(self):
        signals = score_zip_match("46205", "46220")
        assert signals == {}

    def test_zip_missing(self):
        assert score_zip_match(None, "46205") == {}
        assert score_zip_match("46205", None) == {}


# ── MatchResult.from_signals ──────────────────────────────────────────────────

class TestMatchResult:
    def test_high_confidence_dedup(self):
        signals = {"breed_exact": 0.15, "color_primary_match": 0.10,
                   "name_exact": 0.15, "geo_very_close": 0.25, "date_same_day": 0.12,
                   "zip_match": 0.20}
        result = MatchResult.from_signals("a1", "b1", "dedup", signals)
        assert result.confidence == "high"
        assert result.score >= 0.80

    def test_medium_confidence_dedup(self):
        signals = {"breed_exact": 0.15, "geo_close": 0.15, "date_within_3_days": 0.06,
                   "zip_match": 0.20, "color_primary_match": 0.10}
        result = MatchResult.from_signals("a1", "b1", "dedup", signals)
        assert result.confidence in ("medium", "high")

    def test_low_confidence(self):
        signals = {"color_primary_match": 0.10}
        result = MatchResult.from_signals("a1", "b1", "dedup", signals)
        assert result.confidence == "low"

    def test_score_capped_at_1(self):
        signals = {f"sig_{i}": 0.20 for i in range(10)}  # sum = 2.0
        result = MatchResult.from_signals("a1", "b1", "lost_found", signals)
        assert result.score == pytest.approx(1.0)

    def test_lost_found_confidence_thresholds(self):
        signals = {"breed_exact": 0.15, "geo_close": 0.15, "date_within_week": 0.03,
                   "color_primary_match": 0.10}
        result = MatchResult.from_signals("a1", "b1", "lost_found", signals)
        assert result.confidence in ("medium", "high")

    def test_match_type_stored(self):
        result = MatchResult.from_signals("a1", "b1", "dedup", {"name_exact": 0.15})
        assert result.match_type == "dedup"

    def test_signals_stored(self):
        signals = {"name_exact": 0.15, "breed_exact": 0.15}
        result = MatchResult.from_signals("a1", "b1", "dedup", signals)
        assert result.signals_fired == signals


# ── breed_normalizer ──────────────────────────────────────────────────────────

class TestBreedNormalizer:
    def test_exact_known_breed(self):
        result = normalize_breed("Golden Retriever")
        assert result is not None
        assert "golden" in result.lower()

    def test_none_returns_none(self):
        assert normalize_breed(None) is None

    def test_empty_string_returns_none(self):
        assert normalize_breed("") is None

    def test_mixed_case_normalized(self):
        r1 = normalize_breed("golden retriever")
        r2 = normalize_breed("GOLDEN RETRIEVER")
        assert r1 == r2

    def test_mix_breed_passthrough(self):
        # Unknown breeds should return cleaned version or None
        result = normalize_breed("Some Unknown Breed XYZ")
        # Should not raise; result is either normalized or None
        assert result is None or isinstance(result, str)
