"""
Signal definitions and MatchResult data structure for the matching engine.

Both the Deduplicator and LostFoundMatcher use these shared primitives,
ensuring consistent scoring and threshold behavior across both match types.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Literal, Optional


MatchType = Literal["dedup", "lost_found"]
Confidence = Literal["low", "medium", "high"]


@dataclass
class MatchResult:
    pet_a_id: str               # DB row id
    pet_b_id: str
    match_type: MatchType
    score: float                # 0.0–1.0
    confidence: Confidence
    signals_fired: dict[str, float]  # signal_name → weight contributed

    @classmethod
    def from_signals(
        cls,
        pet_a_id: str,
        pet_b_id: str,
        match_type: MatchType,
        signals_fired: dict[str, float],
        dedup_thresholds: tuple[float, float] = (0.60, 0.80),
        lost_found_thresholds: tuple[float, float] = (0.40, 0.65),
    ) -> "MatchResult":
        score = sum(signals_fired.values())
        if match_type == "dedup":
            low_thresh, high_thresh = dedup_thresholds
        else:
            low_thresh, high_thresh = lost_found_thresholds

        if score >= high_thresh:
            confidence: Confidence = "high"
        elif score >= low_thresh:
            confidence = "medium"
        else:
            confidence = "low"

        return cls(
            pet_a_id=pet_a_id,
            pet_b_id=pet_b_id,
            match_type=match_type,
            score=min(1.0, score),
            confidence=confidence,
            signals_fired=signals_fired,
        )


# ── Signal scoring functions ──────────────────────────────────────────────────

def geo_distance_miles(
    lat1: Optional[float], lon1: Optional[float],
    lat2: Optional[float], lon2: Optional[float],
) -> Optional[float]:
    """Haversine distance in miles between two points. Returns None if either point is missing."""
    if any(v is None for v in (lat1, lon1, lat2, lon2)):
        return None
    R = 3958.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lam = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def score_geo_distance(dist_miles: Optional[float]) -> dict[str, float]:
    """Convert a distance in miles to a set of geo signals."""
    if dist_miles is None:
        return {}
    signals = {}
    if dist_miles < 0.5:
        signals["geo_very_close"] = 0.25
    elif dist_miles < 2.0:
        signals["geo_close"] = 0.15
    elif dist_miles < 5.0:
        signals["geo_nearby"] = 0.08
    return signals


def score_date_proximity(
    date_a: Optional[date], date_b: Optional[date]
) -> dict[str, float]:
    if not date_a or not date_b:
        return {}
    delta = abs((date_a - date_b).days)
    if delta == 0:
        return {"date_same_day": 0.12}
    if delta <= 1:
        return {"date_within_1_day": 0.10}
    if delta <= 3:
        return {"date_within_3_days": 0.06}
    if delta <= 7:
        return {"date_within_week": 0.03}
    return {}


def score_breed_match(breed_a: Optional[str], breed_b: Optional[str]) -> dict[str, float]:
    """Score breed similarity using exact match then fuzzy fallback."""
    if not breed_a or not breed_b:
        return {}
    try:
        from rapidfuzz import fuzz
        ratio = fuzz.token_sort_ratio(breed_a.lower(), breed_b.lower())
    except ImportError:
        ratio = 100 if breed_a.lower() == breed_b.lower() else 0

    if ratio == 100:
        return {"breed_exact": 0.15}
    if ratio >= 85:
        return {"breed_fuzzy_high": 0.08}
    if ratio >= 70:
        return {"breed_fuzzy_med": 0.04}
    return {}


def score_color_match(
    color_a: Optional[str], color_b: Optional[str], weight: float = 0.10
) -> dict[str, float]:
    if not color_a or not color_b:
        return {}
    if color_a.lower() == color_b.lower():
        return {"color_primary_match": weight}
    # Partial match (e.g., "Black and White" vs "Black")
    try:
        from rapidfuzz import fuzz
        if fuzz.partial_ratio(color_a.lower(), color_b.lower()) >= 80:
            return {"color_partial_match": weight * 0.5}
    except ImportError:
        pass
    return {}


def score_name_match(name_a: Optional[str], name_b: Optional[str]) -> dict[str, float]:
    if not name_a or not name_b:
        return {}
    if name_a.lower().strip() == name_b.lower().strip():
        return {"name_exact": 0.15}
    return {}


def score_microchip(chip_a: Optional[str], chip_b: Optional[str]) -> dict[str, float]:
    if not chip_a or not chip_b:
        return {}
    if chip_a.strip() == chip_b.strip():
        return {"microchip_match": 0.50}  # Conclusive match
    return {}


def score_description_overlap(desc_a: Optional[str], desc_b: Optional[str]) -> dict[str, float]:
    if not desc_a or not desc_b:
        return {}
    try:
        from rapidfuzz import fuzz
        ratio = fuzz.partial_ratio(desc_a.lower()[:500], desc_b.lower()[:500])
        if ratio >= 80:
            return {"description_high_similarity": 0.10}
        if ratio >= 60:
            return {"description_med_similarity": 0.05}
    except ImportError:
        pass
    return {}


def score_zip_match(zip_a: Optional[str], zip_b: Optional[str]) -> dict[str, float]:
    if not zip_a or not zip_b:
        return {}
    if zip_a[:5] == zip_b[:5]:
        return {"zip_match": 0.20}
    return {}
