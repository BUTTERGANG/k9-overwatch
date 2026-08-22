"""
LostFoundMatcher — identifies lost pet reports that likely correspond to found pet reports.

This is the primary reunification feature of K9-Overwatch.

Example: A "lost dog" report (black lab, Indianapolis, March 20) matched against a
"found dog" report (black lab, same ZIP, March 22) → alert the owner.
"""
from __future__ import annotations

from ..db.models import PetRow
from .breed_normalizer import normalize_breed
from .color_stats import ColorStats, record_color_tokens, score_color_match_v2
from .signals import (
    VETO_PENALTY,
    MatchResult,
    detect_conflicts,
    extract_markings,
    geo_distance_miles,
    markings_contradict,
    score_breed_match,
    score_color_match,
    score_contact_phone,
    score_description_overlap,
    score_geo_distance,
    score_microchip,
    score_name_match,
    score_zip_match,
)
from .visual_similarity import EmbeddingProvider, score_visual_similarity

# Minimum score to record a lost→found match
LOST_FOUND_MIN_SCORE = 0.30

# Maximum days the found date can precede the lost date (animals can be found before reported)
MAX_DAYS_BEFORE_LOST = 3

# Maximum days the found date can follow the lost date.
# Most reunifications happen within 2 weeks; beyond 60 days the odds drop sharply.
MAX_DAYS_AFTER_LOST = 60


class LostFoundMatcher:
    """
    Finds found pet reports that may correspond to a specific lost pet report.
    Operates on PetRow DB objects for access to normalized fields (breed_normalized etc).

    ``visual_provider`` is optional by design. Without a real provider, visual
    similarity contributes no signal and matching remains deterministic.
    """

    def __init__(
        self,
        visual_provider: EmbeddingProvider | None = None,
        *,
        visual_threshold: float = 0.85,
        visual_weight: float = 0.10,
        color_stats: ColorStats | None = None,
        color_max_weight: float = 0.20,
        veto_mode: str = "soft",       # "soft" (penalize) or "strict" (reject)
        veto_penalty: float = VETO_PENALTY,
    ) -> None:
        self.visual_provider = visual_provider
        self.visual_threshold = visual_threshold
        self.visual_weight = visual_weight
        self.color_stats = color_stats
        self.color_max_weight = color_max_weight
        if veto_mode not in ("soft", "strict"):
            raise ValueError("veto_mode must be 'soft' or 'strict'")
        self.veto_mode = veto_mode
        self.veto_penalty = veto_penalty

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

    def find_reverse_matches(
        self,
        found_record: PetRow,
        candidates: list[PetRow],
    ) -> list[MatchResult]:
        """
        Reverse direction: compare a newly-ingested FOUND/SIGHTING record against a
        pool of LOST records, to surface reunifications where the lost pet was
        already in the DB before this found report arrived.

        Delegates to the same `_compare` used by `find_matches` with the roles
        swapped (the candidate LOST record becomes the "lost" side). The scoring
        signals are symmetric, so the score is identical regardless of direction.
        """
        if found_record.record_type not in ("found", "sighting"):
            return []

        results = []
        for candidate in candidates:
            if candidate.record_type != "lost":
                continue
            # _compare expects (lost, found); pass the LOST candidate as lost.
            result = self._compare(candidate, found_record)
            if result and result.score >= LOST_FOUND_MIN_SCORE:
                results.append(result)

        return sorted(results, key=lambda r: r.score, reverse=True)

    def _compare(self, lost: PetRow, found: PetRow) -> MatchResult | None:
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
        # NOTE: uses TRUE coordinates — display-layer pin fuzzing
        # (geocoding/display_fuzz.py) applies only to map rendering and must
        # never leak into match scoring.
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
                signals["found_before_lost"] = 0.05  # found before reported — plausible

        # ── Breed ────────────────────────────────────────────────────────────
        breed_lost = normalize_breed(lost.breed) or normalize_breed(lost.breed_normalized)
        breed_found = normalize_breed(found.breed) or normalize_breed(found.breed_normalized)
        signals.update(score_breed_match(breed_lost, breed_found))

        # ── Vetoes: conflicts between known values ───────────────────────────
        color_tokens_lost = record_color_tokens(lost)
        color_tokens_found = record_color_tokens(found)
        conflicts = detect_conflicts(
            lost.gender, found.gender,
            lost.size, found.size,
            color_tokens_lost, color_tokens_found,
        )
        # Narrative veto: contradicting marking descriptions ("white chest"
        # vs "black chest") between two otherwise-similar records. Fields are
        # extracted separately so colors never attach across field boundaries.
        markings_a: dict[str, set[str]] = {}
        for text in (lost.distinctive_features, lost.description):
            for part, colors in extract_markings(text).items():
                markings_a.setdefault(part, set()).update(colors)
        markings_b: dict[str, set[str]] = {}
        for text in (found.distinctive_features, found.description):
            for part, colors in extract_markings(text).items():
                markings_b.setdefault(part, set()).update(colors)
        marking_conflicts = markings_contradict(markings_a, markings_b)
        if marking_conflicts:
            conflicts["markings"] = "; ".join(marking_conflicts)
        if conflicts and self.veto_mode == "strict":
            return None

        # ── Color (informativeness-weighted when stats are available) ────────
        if self.color_stats is not None and self.color_stats.available:
            signals.update(score_color_match_v2(
                color_tokens_lost, color_tokens_found,
                self.color_stats, max_weight=self.color_max_weight,
            ))
        else:
            signals.update(score_color_match(lost.color_primary, found.color_primary, weight=0.15))
            if lost.color_secondary and found.color_secondary:
                secondary_signals = score_color_match(
                    lost.color_secondary, found.color_secondary, weight=0.15
                )
                signals.update(
                    {k + "_secondary": v * 0.4 for k, v in secondary_signals.items()}
                )

        # ── Gender ───────────────────────────────────────────────────────────
        if (
            lost.gender and found.gender
            and lost.gender == found.gender
            and lost.gender != "unknown"
        ):
            signals["gender_match"] = 0.12

        # ── Size ─────────────────────────────────────────────────────────────
        if lost.size and found.size and lost.size == found.size:
            signals["size_match"] = 0.08

        # ── Name ─────────────────────────────────────────────────────────────
        # Found pets rarely have names, but when they do it's significant
        signals.update(score_name_match(lost.name, found.name))

        # ── Microchip ────────────────────────────────────────────────────────
        signals.update(score_microchip(lost.microchip_number, found.microchip_number))

        # ── Contact phone ─────────────────────────────────────────────────────
        signals.update(score_contact_phone(lost.contact_phone, found.contact_phone))

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

        # ── Optional visual similarity ───────────────────────────────────────
        # This is deliberately provider-backed; no image embedding is guessed.
        signals.update(
            score_visual_similarity(
                lost.photos,
                found.photos,
                provider=self.visual_provider,
                threshold=self.visual_threshold,
                weight=self.visual_weight,
            )
        )

        if not signals:
            return None

        penalties = (
            {fam: self.veto_penalty for fam in conflicts}
            if conflicts and self.veto_mode == "soft"
            else None
        )
        extra_reasons = (
            [f"Markings conflict: {c}" for c in marking_conflicts]
            if marking_conflicts
            else None
        )
        return MatchResult.from_signals_v2(
            pet_a_id=lost.id,
            pet_b_id=found.id,
            match_type="lost_found",
            signals_fired=signals,
            penalties=penalties,
            extra_reasons=extra_reasons,
        )
