"""Tests for the optional, provider-backed visual matching seam."""
from __future__ import annotations

import pytest

from k9overwatch.matching.visual_similarity import (
    cosine_similarity,
    score_visual_similarity,
)


def test_cosine_similarity_is_deterministic_for_supplied_embeddings():
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_similarity_rejects_incompatible_embeddings():
    with pytest.raises(ValueError):
        cosine_similarity([1.0], [1.0, 0.0])


def test_visual_signal_is_fail_closed_without_provider():
    assert score_visual_similarity(["lost.jpg"], ["found.jpg"], provider=None) == {}


def test_visual_signal_uses_provider_embeddings_only_when_configured():
    embeddings = {"lost.jpg": [1.0, 0.0], "found.jpg": [0.99, 0.01]}

    class Provider:
        def embed(self, image_ref: str) -> list[float]:
            return embeddings[image_ref]

    assert score_visual_similarity(
        ["lost.jpg"], ["found.jpg"], provider=Provider(), threshold=0.9, weight=0.2
    ) == {"visual_similarity": pytest.approx(0.2)}


def test_visual_signal_does_not_claim_a_match_below_threshold():
    class Provider:
        def embed(self, image_ref: str) -> list[float]:
            return [1.0, 0.0] if image_ref == "lost.jpg" else [0.0, 1.0]

    assert score_visual_similarity(
        ["lost.jpg"], ["found.jpg"], provider=Provider(), threshold=0.9
    ) == {}


def test_provider_failure_falls_back_without_visual_signal():
    class BrokenProvider:
        def embed(self, image_ref: str) -> list[float]:
            raise RuntimeError("provider unavailable")

    assert score_visual_similarity(
        ["lost.jpg"], ["found.jpg"], provider=BrokenProvider()
    ) == {}


def test_multiple_photos_use_best_valid_pair():
    embeddings = {
        "lost-1.jpg": [1.0, 0.0],
        "lost-2.jpg": [0.0, 1.0],
        "found.jpg": [0.0, 1.0],
    }

    class Provider:
        def embed(self, image_ref: str) -> list[float]:
            return embeddings[image_ref]

    assert score_visual_similarity(
        ["lost-1.jpg", "lost-2.jpg"], ["found.jpg"], provider=Provider(), threshold=0.99
    ) == {"visual_similarity": pytest.approx(0.1)}


def test_invalid_or_zero_embeddings_are_ignored():
    class Provider:
        def embed(self, image_ref: str) -> list[float]:
            return [0.0, 0.0] if image_ref == "lost.jpg" else [1.0, 0.0]

    assert score_visual_similarity(
        ["lost.jpg"], ["found.jpg"], provider=Provider()
    ) == {}

    with pytest.raises(ValueError):
        cosine_similarity([1.0, float("nan")], [1.0, 0.0])


def test_matcher_adds_visual_signal_only_with_injected_provider():
    from datetime import date

    from k9overwatch.db.models import PetRow
    from k9overwatch.matching.lost_found_matcher import LostFoundMatcher

    lost = PetRow(
        id="lost", record_type="lost", animal_type="dog", source="test",
        source_id="lost", date_event=date(2026, 1, 1), photos=["lost.jpg"],
    )
    found = PetRow(
        id="found", record_type="found", animal_type="dog", source="test",
        source_id="found", date_event=date(2026, 1, 1), photos=["found.jpg"],
    )

    class Provider:
        def embed(self, image_ref: str) -> list[float]:
            return [1.0, 0.0]

    result = LostFoundMatcher(visual_provider=Provider())._compare(lost, found)
    assert result is not None
    assert result.signals_fired["visual_similarity"] == pytest.approx(0.1)
    assert "visual_similarity" not in LostFoundMatcher()._compare(lost, found).signals_fired
