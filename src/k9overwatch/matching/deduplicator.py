"""
Deduplicator — identifies the same pet posted on multiple platforms simultaneously.

Example: A lost dog posted on both PawBoost AND IndyLostPetAlert
on the same day, same ZIP, same breed → probable duplicate.
"""
from __future__ import annotations

from ..db.models import PetRow
from .breed_normalizer import normalize_breed
from .color_stats import ColorStats, score_color_match_v2, tokenize_color
from .signals import (
    VETO_PENALTY,
    MatchResult,
    detect_conflicts,
    geo_distance_miles,
    score_breed_match,
    score_color_match,
    score_contact_phone,
    score_date_proximity,
    score_geo_distance,
    score_microchip,
    score_name_match,
    score_zip_match,
)

# Minimum score to record as a dedup match
DEDUP_MIN_SCORE = 0.35

# v2 confidence thresholds for dedup (kept close to the legacy 0.60/0.80)
DEDUP_V2_THRESHOLDS = (0.55, 0.75)


class Deduplicator:
    """
    Identifies duplicate records — the same physical pet listed on multiple sources.
    Operates on DB row objects (PetRow), not PetRecord instances.

    Conflicting known values (gender/size/color) are treated as data errors for a
    duplicate posting, so they apply a soft penalty rather than a hard reject.
    """

    def __init__(
        self,
        *,
        color_stats: ColorStats | None = None,
        veto_penalty: float = VETO_PENALTY,
    ) -> None:
        self.color_stats = color_stats
        self.veto_penalty = veto_penalty

    def find_duplicates(
        self,
        record: PetRow,
        candidates: list[PetRow],
    ) -> list[MatchResult]:
        """
        Compare `record` against `candidates` and return all pairs scoring above the threshold.
        Candidates should already be pre-filtered by animal_type, date window, and radius.
        """
        results = []
        for candidate in candidates:
            result = self._compare(record, candidate)
            if result and result.score >= DEDUP_MIN_SCORE:
                results.append(result)

        return sorted(results, key=lambda r: r.score, reverse=True)

    def _compare(self, a: PetRow, b: PetRow) -> MatchResult | None:
        # Hard filters
        if a.animal_type != b.animal_type:
            return None
        if a.record_type == b.record_type:
            # Dedup: same type (both lost or both found) — plausible duplicate
            pass
        # Different sources are more interesting for dedup, but same-source duplication
        # can happen if a scraper re-posts. Don't hard-filter on source.

        signals: dict[str, float] = {}

        # ── Record-type hint ─────────────────────────────────────────────────
        # Dedup: the same physical pet is typically posted with the same
        # record_type on each platform (both "lost" or both "found"). A matching
        # type is a weak positive signal; mismatched types are still possible
        # (e.g. one site lists it as "found" while another has the original
        # "lost" report) so we don't hard-filter on it.
        if a.record_type == b.record_type:
            signals["same_record_type"] = 0.04
        dist = geo_distance_miles(a.lat, a.lon, b.lat, b.lon)
        signals.update(score_geo_distance(dist))
        signals.update(score_zip_match(a.zip, b.zip))

        # ── Date ─────────────────────────────────────────────────────────────
        signals.update(score_date_proximity(a.date_event, b.date_event))

        # ── Animal characteristics ────────────────────────────────────────────
        breed_a = normalize_breed(a.breed)
        breed_b = normalize_breed(b.breed)
        signals.update(score_breed_match(breed_a, breed_b))

        # ── Vetoes: conflicts between known values (data errors for dedup) ───
        color_tokens_a = tokenize_color(a.color_primary) | tokenize_color(a.color_secondary)
        color_tokens_b = tokenize_color(b.color_primary) | tokenize_color(b.color_secondary)
        conflicts = detect_conflicts(
            a.gender, b.gender, a.size, b.size, color_tokens_a, color_tokens_b,
        )

        if self.color_stats is not None and self.color_stats.available:
            signals.update(score_color_match_v2(color_tokens_a, color_tokens_b, self.color_stats))
        else:
            signals.update(score_color_match(a.color_primary, b.color_primary, weight=0.10))
            signals.update(score_color_match(a.color_secondary, b.color_secondary, weight=0.06))
        signals.update(score_name_match(a.name, b.name))

        # ── Gender ───────────────────────────────────────────────────────────
        if a.gender and b.gender and a.gender == b.gender and a.gender != "unknown":
            signals["gender_match"] = 0.08

        # ── Size ─────────────────────────────────────────────────────────────
        if a.size and b.size and a.size == b.size:
            signals["size_match"] = 0.05

        # ── Microchip ────────────────────────────────────────────────────────
        signals.update(score_microchip(a.microchip_number, b.microchip_number))

        # ── Contact phone ─────────────────────────────────────────────────────
        signals.update(score_contact_phone(a.contact_phone, b.contact_phone))

        # ── Cross-source bonus ────────────────────────────────────────────────
        if a.source != b.source:
            signals["cross_source"] = 0.05

        if not signals:
            return None

        penalties = (
            {fam: self.veto_penalty for fam in conflicts} if conflicts else None
        )
        return MatchResult.from_signals_v2(
            pet_a_id=a.id,
            pet_b_id=b.id,
            match_type="dedup",
            signals_fired=signals,
            penalties=penalties,
            thresholds=DEDUP_V2_THRESHOLDS,
        )
