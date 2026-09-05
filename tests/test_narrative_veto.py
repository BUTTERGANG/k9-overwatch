"""Narrative-conflict veto: contradicting marking descriptions suppress matches.

Two identical black labs where one report says "white patch on chest" and the
other says "black chest" describe different animals — the soft veto must pull
the pair below high confidence. Sparse records (no extractable markings on at
least one side) are never penalized.
"""
from datetime import date

from k9overwatch.db.models import PetRow
from k9overwatch.matching.lost_found_matcher import LostFoundMatcher
from k9overwatch.matching.signals import extract_markings, markings_contradict


def _pet(record_type="lost", **kw):
    defaults = dict(source="test", animal_type="dog")
    return PetRow(**{**defaults, "record_type": record_type, **kw})


BASE = dict(lat=39.77, lon=-86.11, date_event=date(2026, 3, 20),
            gender="male", size="M", breed="Labrador Retriever",
            color_primary="Black")


def _found(**kw):
    return _pet(
        "found", lat=39.772, lon=-86.112, date_event=date(2026, 3, 21),
        gender="male", size="M", breed="Lab", color_primary="black", **kw
    )


LOST_WHITE_CHEST = _pet(
    id="L1", source_id="L1", **BASE,
    distinctive_features="white patch on chest",
    description="Black labrador, white patch on chest",
)
FOUND_BLACK_CHEST = _found(
    id="F1", source_id="F1",
    description="Friendly black lab found downtown, black chest, no collar",
)
FOUND_WHITE_CHEST = _found(
    id="F2", source_id="F2",
    description="Friendly black lab found downtown, white patch on chest",
)
FOUND_NO_MARKINGS = _found(
    id="F3", source_id="F3",
    description="Friendly black lab found downtown",
)


# ── unit: marking extraction ─────────────────────────────────────────────────

def test_extract_color_bodypart_bigrams():
    marks = extract_markings("white patch on chest and black mask")
    assert marks["chest"] == {"white"}
    assert marks["mask"] == {"black"}


def test_extract_reversed_order_and_variants():
    assert extract_markings("mask black and gray")["mask"] == {"black"}
    assert extract_markings("white paws")["paw"] == {"white"}
    assert extract_markings("white patch on chest")["chest"] == {"white"}


def test_extract_ignores_non_marking_text():
    assert extract_markings("very friendly dog, loves fetch") == {}


def test_contradict_requires_shared_bodypart():
    a = {"chest": {"white"}}
    b = {"belly": {"black"}}
    assert markings_contradict(a, b) == []


def test_contradict_detects_conflicting_colors():
    conflicts = markings_contradict(
        {"chest": {"white"}}, {"chest": {"black"}}
    )
    assert len(conflicts) == 1
    assert "white chest" in conflicts[0]
    assert "black chest" in conflicts[0]


def test_contradict_allows_shared_colors():
    # both report white AND black on chest → no contradiction
    assert markings_contradict(
        {"chest": {"white", "black"}}, {"chest": {"black"}}
    ) == []


# ── integration: matcher veto ────────────────────────────────────────────────

def test_adversarial_marking_conflict_not_high():
    m = LostFoundMatcher()
    result = m._compare(LOST_WHITE_CHEST, FOUND_BLACK_CHEST)
    assert result is not None                      # soft veto keeps it visible
    assert result.confidence != "high"             # must not look conclusive
    assert result.score < 0.65
    assert any("marking" in r.lower() for r in result.reasons)
    assert any("white chest" in r.lower() for r in result.reasons)


def test_one_sided_features_no_penalty():
    m = LostFoundMatcher()
    result = m._compare(LOST_WHITE_CHEST, FOUND_NO_MARKINGS)
    assert result is not None
    # no markings-penalty applied; score equals the un-penalized baseline
    assert result.score > 0.80
    assert not any("marking" in r.lower() for r in result.reasons)


def test_matching_features_fine_and_high():
    m = LostFoundMatcher()
    result = m._compare(LOST_WHITE_CHEST, FOUND_WHITE_CHEST)
    assert result is not None
    assert result.confidence == "high"
    assert not any("marking" in r.lower() for r in result.reasons)


def test_strict_mode_rejects_marking_conflict():
    result = LostFoundMatcher(veto_mode="strict")._compare(
        LOST_WHITE_CHEST, FOUND_BLACK_CHEST
    )
    assert result is None
