"""
LostFoundMatcher — identifies lost pet reports that likely correspond to found pet reports.

This is the primary reunification feature of K9-Overwatch.

Example: A "lost dog" report (black lab, Indianapolis, March 20) matched against a
"found dog" report (black lab, same ZIP, March 22) → alert the owner.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from ..db.models import PetRow
from .breed_normalizer import normalize_breed
from .signals import (
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

# Minimum score to record a lost→found match
LOST_FOUND_MIN_SCORE = 0.30

# Maximum days the found date can precede the lost date (animals can be found before reported)
MAX_DAYS_BEFORE_LOST = 3

# Maximum days the found date can follow the lost date
MAX_DAYS_AFTER_LOST = 90


class LostFoundMatcher:
    """
    Finds found pet reports that may correspond to a specific lost pet report.
    Operates on PetRow DB objects for access to normalized fields (breed_normalized etc).
    """

    def find_matches(
        self,
        lost_record: PetRow,
        candidates: list[PetRow],
    ) -> list[MatchResult]:
        """
        Compare a lost pet record against a pool of found records.
        Returns all matches above the minimum score threshold, sorted by score descending.
        """
        if lost_record.record_type != "lost":
            return []

        results = []
        for candidate in candidates:
            if candidate.record_type not in ("found", "sighting"):
                continue
            result = self._compare(lost_record, candidate)
            if result and result.score >= LOST_FOUND_MIN_SCORE:
                results.append(result)

        return sorted(results, key=lambda r: r.score, reverse=True)

    def _compare(self, lost: PetRow, found: PetRow) -> Optional[MatchResult]:
        # Hard filters
        if lost.animal_type != found.animal_type:
            return None

        # Temporal constraint: found date must be within valid window of lost date
        if lost.date_event and found.date_event:
            delta = (found.date_event - lost.date_event).days
            if delta < -MAX_DAYS_BEFORE_LOST or delta > MAX_DAYS_AFTER_LOST:
                return None

        signals: dict[str, float] = {}

        # ── Geo ──────────────────────────────────────────────────────────────
        dist = geo_distance_miles(lost.lat, lost.lon, found.lat, found.lon)
        signals.update(score_geo_distance(dist))
        signals.update(score_zip_match(lost.zip, found.zip))

        # ── Temporal ─────────────────────────────────────────────────────────
        if lost.date_event and found.date_event:
            delta = (found.date_event - lost.date_event).days
            if 0 <= delta <= 3:
                signals["found_days_0_3"] = 0.10
            elif 0 <= delta <= 14:
                signals["found_days_4_14"] = 0.05
            elif delta < 0:
                signals["found_before_lost"] = 0.02  # found before reported — plausible

        # ── Breed ────────────────────────────────────────────────────────────
        breed_lost = normalize_breed(lost.breed) or normalize_breed(lost.breed_normalized)
        breed_found = normalize_breed(found.breed) or normalize_breed(found.breed_normalized)
        signals.update(score_breed_match(breed_lost, breed_found))

        # ── Color ────────────────────────────────────────────────────────────
        signals.update(score_color_match(lost.color_primary, found.color_primary, weight=0.15))
        if lost.color_secondary and found.color_secondary:
            signals.update(
                {k + "_secondary": v * 0.4
                 for k, v in score_color_match(lost.color_secondary, found.color_secondary, weight=0.15).items()}
            )

        # ── Gender ───────────────────────────────────────────────────────────
        if lost.gender and found.gender and lost.gender == found.gender and lost.gender != "unknown":
            signals["gender_match"] = 0.12

        # ── Size ─────────────────────────────────────────────────────────────
        if lost.size and found.size and lost.size == found.size:
            signals["size_match"] = 0.08

        # ── Name ─────────────────────────────────────────────────────────────
        # Found pets rarely have names, but when they do it's significant
        signals.update(score_name_match(lost.name, found.name))

        # ── Microchip ────────────────────────────────────────────────────────
        signals.update(score_microchip(lost.microchip_number, found.microchip_number))

        # ── Description ──────────────────────────────────────────────────────
        signals.update(score_description_overlap(lost.description, found.description))

        # ── Distinctive features boost ────────────────────────────────────────
        if lost.distinctive_features and found.description:
            feat_lower = lost.distinctive_features.lower()
            desc_lower = found.description.lower()
            # Check for keyword overlap in distinctive features
            keywords = [w for w in feat_lower.split() if len(w) > 4]
            matches = sum(1 for kw in keywords if kw in desc_lower)
            if keywords and matches / len(keywords) >= 0.5:
                signals["distinctive_feature_match"] = 0.08

        if not signals:
            return None

        return MatchResult.from_signals(
            pet_a_id=lost.id,
            pet_b_id=found.id,
            match_type="lost_found",
            signals_fired=signals,
        )
