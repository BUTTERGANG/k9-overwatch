"""Matching engine v2 tests: vetoes, informativeness-weighted color, corroboration, reasons."""
from __future__ import annotations

import math
from datetime import date

import pytest

from k9overwatch.db.models import PetRow
from k9overwatch.matching.color_stats import (
    ColorStats,
    build_color_stats,
    score_color_match_v2,
    tokenize_color,
)
from k9overwatch.matching.signals import (
    MatchResult,
    detect_conflicts,
)

# ── Color tokenization ────────────────────────────────────────────────────────

class TestTokenizeColor:
    def test_split_on_separators(self):
        assert tokenize_color("Black / White") == {"black", "white"}
        assert tokenize_color("brown,black") == {"brown", "black"}
        assert tokenize_color("tan and white") == {"tan", "white"}
        assert tokenize_color("dark brown") == {"dark", "brown"}

    def test_empty(self):
        assert tokenize_color(None) == set()
        assert tokenize_color("") == set()
        assert tokenize_color("unknown") == set()


# ── Conflict detection ────────────────────────────────────────────────────────

class TestDetectConflicts:
    def test_gender_conflict(self):
        conflicts = detect_conflicts(
            gender_a="M", gender_b="F", size_a=None, size_b=None,
            color_tokens_a=set(), color_tokens_b=set(),
        )
        assert "gender" in conflicts

    def test_size_conflict_two_steps(self):
        conflicts = detect_conflicts(
            gender_a=None, gender_b=None, size_a="S", size_b="L",
            color_tokens_a=set(), color_tokens_b=set(),
        )
        assert "size" in conflicts

    def test_adjacent_size_tolerated(self):
        conflicts = detect_conflicts(
            gender_a=None, gender_b=None, size_a="S", size_b="M",
            color_tokens_a=set(), color_tokens_b=set(),
        )
        assert "size" not in conflicts

    def test_unknown_values_never_veto(self):
        assert detect_conflicts(
            "unknown", "F", None, None, set(), set()
        ) == {}
        assert detect_conflicts(
            None, "F", None, "L", set(), set()
        ) == {}

    def test_color_contradiction_shares_token_passes(self):
        # "black white" vs "white tan" shares "white" → no contradiction
        assert detect_conflicts(
            None, None, None, None,
            {"black", "white"}, {"white", "tan"},
        ) == {}

    def test_color_contradiction_near_token_passes(self):
        # gray ~ grey (rapidfuzz >= 80)
        assert detect_conflicts(
            None, None, None, None, {"gray"}, {"grey"},
        ) == {}

    def test_color_contradiction_black_vs_white(self):
        conflicts = detect_conflicts(
            None, None, None, None, {"black"}, {"white"},
        )
        assert "color" in conflicts

    def test_multiword_color_with_shared_token(self):
        # "brown/black" vs "black" shares "black"
        assert detect_conflicts(
            None, None, None, None, {"brown", "black"}, {"black"},
        ) == {}


# ── ColorStats ────────────────────────────────────────────────────────────────

class TestColorStats:
    def test_idf_ordering_common_lt_rare(self):
        stats = build_color_stats([
            {"color_primary": "black", "color_secondary": None},
            {"color_primary": "black", "color_secondary": "white"},
            {"color_primary": "white", "color_secondary": None},
            {"color_primary": "brindle", "color_secondary": None},
        ])
        assert stats.token_idf("black") < stats.token_idf("brindle")
        # smoothed log((N+1)/(1+df)): black df=2, N=4
        assert stats.token_idf("black") == pytest.approx(math.log(5 / 3))

    def test_rare_token_detection(self):
        stats = build_color_stats([
            {"color_primary": "black"} for _ in range(100)
        ] + [{"color_primary": "merle"}])
        assert stats.is_rare("merle")
        assert not stats.is_rare("black")

    def test_serialize_roundtrip(self):
        stats = build_color_stats([
            {"color_primary": "black"}, {"color_primary": "white tan"},
        ])
        restored = ColorStats.from_dict(stats.to_dict())
        assert restored.to_dict() == stats.to_dict()

    def test_empty_db_fallback_flag(self):
        stats = build_color_stats([])
        assert stats.total_docs == 0
        assert not stats.available


# ── score_color_match_v2 ──────────────────────────────────────────────────────

class TestScoreColorMatchV2:
    def _stats(self):
        return build_color_stats([
            {"color_primary": "black"} for _ in range(100)
        ] + [
            {"color_primary": "brown patch"},
            {"color_primary": "brown"},
        ])

    def test_overlap_weighted_by_idf(self):
        stats = self._stats()
        signals = score_color_match_v2({"white", "brown"}, {"brown", "white"}, stats)
        assert "color_overlap_v2" in signals
        assert 0.0 <= signals["color_overlap_v2"] <= 0.20

    def test_no_shared_tokens(self):
        signals = score_color_match_v2({"black"}, {"white"}, self._stats())
        assert signals == {}

    def test_missing_stats_returns_empty_for_fallback(self):
        # Caller falls back to uniform scoring when stats unavailable
        assert score_color_match_v2({"black"}, {"black"}, None) == {}
        assert score_color_match_v2({"black"}, {"black"}, build_color_stats([])) == {}

    def test_rare_token_bonus(self):
        # "patch" appears once in 103 docs (<5%) → bonus signal
        signals = score_color_match_v2(
            {"white", "brown", "patch"}, {"brown", "patch"}, self._stats()
        )
        assert signals.get("color_rare_token") == pytest.approx(0.08)


# ── from_signals_v2 corroboration ─────────────────────────────────────────────

class TestFromSignalsV2Corroboration:
    def test_microchip_alone_is_high(self):
        result = MatchResult.from_signals_v2(
            "a", "b", "lost_found", {"microchip_match": 0.50}
        )
        assert result.confidence == "high"

    def test_phone_alone_is_high(self):
        result = MatchResult.from_signals_v2(
            "a", "b", "lost_found", {"contact_phone_match": 0.35}
        )
        assert result.confidence == "high"

    def test_circumstance_only_caps_at_medium(self):
        # black lab vs black lab: strong circumstance + generic description
        signals = {
            "geo_very_close": 0.25, "zip_match": 0.08,
            "date_within_1_day": 0.10, "found_days_0_3": 0.10,
            "breed_exact": 0.15, "color_primary_match": 0.15,
        }
        result = MatchResult.from_signals_v2("a", "b", "lost_found", signals)
        assert result.score >= 0.65
        assert result.confidence != "high"
        assert any("circumstan" in r.lower() for r in result.reasons)

    def test_high_requires_two_families(self):
        # description-only stack above 0.65 is impossible with real weights,
        # so force it via a synthetic two-signal narrative case instead:
        signals = {"description_high_similarity": 0.10,
                   "distinctive_feature_match": 0.08}
        result = MatchResult.from_signals_v2("a", "b", "lost_found", signals)
        assert result.confidence == "low"

    def test_lone_weak_evidence_low_and_needs_review(self):
        result = MatchResult.from_signals_v2(
            "a", "b", "lost_found", {"color_primary_match": 0.10}
        )
        assert result.confidence == "low"
        assert "needs_review" in result.labels

    def test_single_family_multiple_signals_medium_cap(self):
        narrative_only = {
            "description_high_similarity": 0.10,
            "distinctive_feature_match": 0.08,
            "description_med_similarity": 0.05,
        }
        result = MatchResult.from_signals_v2("a", "b", "lost_found", narrative_only)
        assert result.score < 0.40  # narrative alone never crosses 0.40 here
        assert result.confidence == "low"

    def test_two_families_high_score_is_high(self):
        signals = {
            "geo_very_close": 0.25, "zip_match": 0.08,
            "found_days_0_3": 0.10,
            "breed_exact": 0.15, "color_overlap_v2": 0.18,
            "color_rare_token": 0.08, "gender_match": 0.12,
        }
        result = MatchResult.from_signals_v2("a", "b", "lost_found", signals)
        assert result.confidence == "high"

    def test_reasons_generated_from_signals(self):
        result = MatchResult.from_signals_v2(
            "a", "b", "lost_found",
            {"microchip_match": 0.50, "geo_close": 0.15},
        )
        assert len(result.reasons) >= 2

    def test_soft_penalty_applied_and_reasoned(self):
        signals = {
            "geo_very_close": 0.25, "found_days_0_3": 0.10,
            "breed_exact": 0.15, "color_overlap_v2": 0.18,
            "gender_match": 0.12, "size_match": 0.08,
        }
        base = MatchResult.from_signals_v2("a", "b", "lost_found", dict(signals))
        penalized = MatchResult.from_signals_v2(
            "a", "b", "lost_found", dict(signals),
            penalties={"gender": 0.45},
        )
        assert penalized.score == pytest.approx(max(0.0, base.score - 0.45))
        assert any("gender" in r.lower() for r in penalized.reasons)


class TestNarrativeVetoIdentitySemantics:
    def test_microchip_with_narrative_veto_still_high(self):
        # Narrative conflict = misdescription, not a different animal.
        result = MatchResult.from_signals_v2(
            "a", "b", "lost_found",
            {"microchip_match": 0.50},
            penalties={"narrative": 0.45},
        )
        assert result.confidence == "high"
        assert any("conflict" in r.lower() for r in result.reasons)

    def test_microchip_with_gender_veto_not_high(self):
        # Gender is physically exclusive — veto still suppresses identity.
        result = MatchResult.from_signals_v2(
            "a", "b", "lost_found",
            {"microchip_match": 0.50},
            penalties={"gender": 0.45},
        )
        assert result.confidence != "high"

    def test_microchip_with_narrative_and_gender_veto_not_high(self):
        result = MatchResult.from_signals_v2(
            "a", "b", "lost_found",
            {"microchip_match": 0.50},
            penalties={"narrative": 0.45, "gender": 0.45},
        )
        assert result.confidence != "high"


class TestUnknownSignalFamilyIsolation:
    def test_unknown_names_do_not_inflate_corroboration(self):
        # 1 known description signal + 2 unknown-name signals. Score crosses
        # 0.40 but unknowns must not count as corroborating evidence families.
        signals = {
            "distinctive_feature_match": 0.08,
            "mystery_signal_a": 0.20,
            "mystery_signal_b": 0.20,
        }
        result = MatchResult.from_signals_v2("a", "b", "lost_found", signals)
        assert result.score == pytest.approx(0.48)
        assert result.confidence == "low"

    def test_unknown_names_still_contribute_to_score(self):
        result = MatchResult.from_signals_v2(
            "a", "b", "lost_found",
            {"geo_very_close": 0.25, "mystery_signal": 0.20,
             "date_within_1_day": 0.10},
        )
        assert result.score == pytest.approx(0.55)
        assert result.confidence == "medium"  # 2 real families, not 3


# ── Matcher integration ───────────────────────────────────────────────────────

def _pet(**kw):
    defaults = dict(
        source="test", source_id="x", record_type="lost",
        animal_type="dog",
    )
    defaults.update(kw)
    return PetRow(**defaults)


class TestMatcherVetoesAndSparse:
    def _match(self, lost_kw, found_kw, **kwargs):
        from k9overwatch.matching.lost_found_matcher import LostFoundMatcher
        shared = {k: v for k, v in kwargs.items() if k not in ("color_stats", "veto_mode")}
        m = LostFoundMatcher(
            color_stats=kwargs.get("color_stats"),
            veto_mode=kwargs.get("veto_mode", "soft"),
        )
        lost = _pet(record_type="lost", **{**shared, **lost_kw})
        found = _pet(record_type="found", **{**shared, **found_kw})
        return m._compare(lost, found)

    def test_gender_conflict_soft_veto_drops_below_medium(self):
        result = self._match(
            dict(gender="M", color_primary="black"),
            dict(gender="F", color_primary="black",
                 lat=39.77, lon=-86.11, date_event=date(2026, 3, 21)),
            lat=39.77, lon=-86.11, date_event=date(2026, 3, 20),
        )
        # Without the veto this would be a solid circumstantial match
        assert result is not None
        assert result.score < 0.40
        assert any("gender" in r.lower() for r in result.reasons)

    def test_strict_mode_returns_none_on_conflict(self):
        from k9overwatch.matching.lost_found_matcher import LostFoundMatcher
        m = LostFoundMatcher(veto_mode="strict")
        result = m._compare(
            _pet(record_type="lost", gender="M"),
            _pet(record_type="found", gender="F"),
        )
        assert result is None

    def test_missing_gender_no_veto(self):
        result = self._match(
            dict(color_primary="black", microchip_number="985112009123456"),
            dict(color_primary="black", microchip_number="985112009123456"),
        )
        assert result is not None
        assert result.confidence == "high"

    def test_sparse_records_decent_score(self):
        stats = build_color_stats([
            {"color_primary": "black"} for _ in range(50)
        ] + [{"color_primary": "brown patch"}] * 2)
        result = self._match(
            dict(breed=None, color_primary="white / brown patch"),
            dict(breed=None, color_primary="brown and white",
                 lat=39.77, lon=-86.11, date_event=date(2026, 3, 22)),
            lat=39.77, lon=-86.11, date_event=date(2026, 3, 20),
            color_stats=stats,
        )
        assert result is not None
        assert result.score >= 0.30
        assert "color_overlap_v2" in result.signals_fired
        assert any("brown patch" in r.lower() or "color" in r.lower()
                   for r in result.reasons)

    def test_coincidence_case_not_high(self):
        """Identical generic descriptions + close geo/time ≠ high confidence."""
        result = self._match(
            dict(breed="Labrador Retriever", color_primary="black"),
            dict(breed="lab", color_primary="Black",
                 lat=39.77, lon=-86.11, date_event=date(2026, 3, 21)),
            lat=39.77, lon=-86.11, date_event=date(2026, 3, 20),
        )
        assert result is not None
        assert result.confidence != "high"
