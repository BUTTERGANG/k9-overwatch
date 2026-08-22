"""
Signal definitions and MatchResult data structure for the matching engine.

Both the Deduplicator and LostFoundMatcher use these shared primitives,
ensuring consistent scoring and threshold behavior across both match types.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

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
    reasons: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)

    @classmethod
    def from_signals(
        cls,
        pet_a_id: str,
        pet_b_id: str,
        match_type: MatchType,
        signals_fired: dict[str, float],
        dedup_thresholds: tuple[float, float] = (0.60, 0.80),
        lost_found_thresholds: tuple[float, float] = (0.40, 0.65),
    ) -> MatchResult:
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


# ── v2: corroboration-based confidence ───────────────────────────────────────

# Evidence families: signals grouped by what kind of evidence they provide.
SIGNAL_FAMILIES: dict[str, str] = {
    # circumstance: where + when
    "geo_very_close": "circumstance", "geo_close": "circumstance",
    "geo_nearby": "circumstance", "zip_match": "circumstance",
    "date_same_day": "circumstance", "date_within_1_day": "circumstance",
    "date_within_3_days": "circumstance", "date_within_week": "circumstance",
    "found_days_0_3": "circumstance", "found_days_4_14": "circumstance",
    "found_before_lost": "circumstance",
    # description: what the animal looks like
    "color_primary_match": "description", "color_partial_match": "description",
    "color_overlap_v2": "description", "color_rare_token": "description",
    "gender_match": "description", "size_match": "description",
    "breed_exact": "description", "breed_fuzzy_high": "description",
    "breed_fuzzy_med": "description",
    # identity: who it belongs to
    "microchip_match": "identity", "contact_phone_match": "identity",
    "contact_phone_partial": "identity", "name_exact": "identity",
    # narrative: what the reports say
    "description_high_similarity": "narrative",
    "description_med_similarity": "narrative",
    "distinctive_feature_match": "narrative",
    # visual: image similarity
    "visual_similarity_match": "visual",
    "visual_similarity_partial": "visual",
}

SIGNAL_REASON_MAP: dict[str, str] = {
    "geo_very_close": "Found less than half a mile from where the pet went missing",
    "geo_close": "Found within 2 miles of the reported location",
    "geo_nearby": "Found within 5 miles of the reported location",
    "zip_match": "Same ZIP code as the loss location",
    "date_same_day": "Found the same day the pet was reported lost",
    "date_within_1_day": "Found 1 day after the pet was reported lost",
    "date_within_3_days": "Found within 3 days of the loss report",
    "date_within_week": "Found within a week of the loss report",
    "found_days_0_3": "Found within 3 days of the loss report",
    "found_days_4_14": "Found within two weeks of the loss report",
    "found_before_lost": "Found just before the pet was reported lost",
    "breed_exact": "Same breed listed on both reports",
    "breed_fuzzy_high": "Very similar breeds listed on both reports",
    "breed_fuzzy_med": "Broadly similar breeds listed on both reports",
    "color_primary_match": "Primary color matches on both reports",
    "color_partial_match": "Primary colors partially overlap",
    "color_overlap_v2": "Color descriptions overlap",
    "color_rare_token": "A distinctive, uncommon color detail appears in both reports",
    "gender_match": "Same sex recorded on both reports",
    "size_match": "Same size recorded on both reports",
    "name_exact": "Same name on both reports",
    "microchip_match": "Microchip numbers are identical",
    "contact_phone_match": "Same contact phone number on both reports",
    "contact_phone_partial": "Contact phone numbers match on the last 7 digits",
    "description_high_similarity": "Report descriptions are very similar",
    "description_med_similarity": "Report descriptions are moderately similar",
    "distinctive_feature_match": "A distinctive feature noted on one report appears in the other's description",
    "visual_similarity_match": "Photos of the two animals are highly similar",
    "visual_similarity_partial": "Photos of the two animals are moderately similar",
}

CIRCUMSTANCE_ONLY_REASON = (
    "Match relies mainly on circumstances (where/when); descriptive details "
    "are too generic on their own to confirm"
)

# Tunable thresholds for v2 confidence (lost_found semantics)
V2_HIGH_SCORE = 0.65
V2_MEDIUM_SCORE = 0.40
VETO_PENALTY = 0.45
COINCIDENCE_MAX_GENERIC_DESC_SIGNALS = 2

# Human-readable names for veto families shown in match reasons.
_VETO_FAMILY_LABELS = {
    "gender": "gender",
    "size": "size",
    "color": "color",
    "narrative": "markings/description",
}


@classmethod
def from_signals_v2(
    cls,
    pet_a_id: str,
    pet_b_id: str,
    match_type: MatchType,
    signals_fired: dict[str, float],
    penalties: dict[str, float] | None = None,
    extra_reasons: list[str] | None = None,
    thresholds: tuple[float, float] = (V2_MEDIUM_SCORE, V2_HIGH_SCORE),
) -> MatchResult:
    """
    Corroboration-based confidence ("filter first, rank second, explain always").

    Rules (in precedence order):
      * identity family hit → high
      * high requires score ≥ 0.65 AND ≥ 2 evidence families AND not a
        circumstance+generic-description coincidence stack
      * medium requires score ≥ 0.40 AND ≥ 1 family; single-family matches
        need ≥ 2 distinct signals in that family, else low
      * lone weak evidence (score < 0.40) → low + "needs_review" label

    ``penalties`` maps veto family → penalty subtracted from the raw score.
    """
    penalties = penalties or {}
    raw = sum(signals_fired.values())
    score = max(0.0, raw - sum(penalties.values()))

    families: dict[str, list[str]] = {}
    for sig in signals_fired:
        families.setdefault(SIGNAL_FAMILIES.get(sig, "narrative"), []).append(sig)
    families_present = set(families)

    # Identity evidence (microchip/phone/name) is conclusive: a narrative
    # conflict means someone misdescribed the animal, not a different one.
    # Physically exclusive vetoes (gender/size/color) still suppress identity.
    identity_hit = any(
        fam == "identity" for fam in families_present
    ) and set(penalties) <= {"narrative"}

    coincidence = (
        families_present and families_present <= {"circumstance", "description"}
        and "identity" not in families_present
        and len(families.get("description", []))
        <= COINCIDENCE_MAX_GENERIC_DESC_SIGNALS
    )

    if identity_hit:
        confidence: Confidence = "high"
    elif score >= thresholds[1] and len(families_present) >= 2 and not coincidence:
        confidence = "high"
    elif score >= thresholds[0] and families_present and (
        len(families_present) > 1 or len(next(iter(families.values()))) >= 2
    ):
        confidence = "medium"
    else:
        confidence = "low"

    reasons = [SIGNAL_REASON_MAP[s] for s in signals_fired if s in SIGNAL_REASON_MAP]
    if penalties:
        for fam, pen in penalties.items():
            reasons.append(
                f"Conflicting {fam} between records — score penalized by {pen:.2f}"
            )
    if confidence != "high" and coincidence:
        reasons.append(CIRCUMSTANCE_ONLY_REASON)
    reasons.extend(extra_reasons or [])

    labels: list[str] = []
    if confidence == "low" and score > 0:
        labels.append("needs_review")

    return cls(
        pet_a_id=pet_a_id,
        pet_b_id=pet_b_id,
        match_type=match_type,
        score=min(1.0, score),
        confidence=confidence,
        signals_fired=signals_fired,
        reasons=reasons,
        labels=labels,
    )


MatchResult.from_signals_v2 = from_signals_v2  # type: ignore[attr-defined]


# ── v2: conflict (soft/strict veto) detection ────────────────────────────────

SIZE_ORDER = {"S": 0, "M": 1, "L": 2, "XL": 3}


def _known(value: str | None) -> str | None:
    if not value:
        return None
    v = value.strip().lower()
    return None if v in ("", "unknown", "unk", "n/a", "na", "none") else v


def _near_tokens(a: set[str], b: set[str]) -> bool:
    """
    True when any token pair is near-identical. Uses rapidfuzz ratio ≥ 75 so
    single-character variants ("gray" ~ "grey", ratio 75) count as near-tokens.
    """
    try:
        from rapidfuzz import fuzz
        return any(
            fuzz.ratio(x, y) >= 75 for x in a for y in b
        )
    except ImportError:
        return any(x == y for x in a for y in b)


def colors_contradict(tokens_a: set[str], tokens_b: set[str]) -> bool:
    """Contradiction = both non-empty, no shared token, no near-token pair."""
    if not tokens_a or not tokens_b:
        return False
    if tokens_a & tokens_b:
        return False
    return not _near_tokens(tokens_a, tokens_b)


def detect_conflicts(
    gender_a: str | None, gender_b: str | None,
    size_a: str | None, size_b: str | None,
    color_tokens_a: set[str], color_tokens_b: set[str],
) -> dict[str, str]:
    """
    Detect conflicting record attributes. Returns {family: human description}.
    Never flags a conflict when either side's value is missing/"unknown".
    """
    conflicts: dict[str, str] = {}

    ga, gb = _known(gender_a), _known(gender_b)
    if ga and gb and ga != gb:
        conflicts["gender"] = f"gender ({ga} vs {gb})"

    sa, sb = size_a.strip().upper() if size_a else None, size_b.strip().upper() if size_b else None
    if sa and sb and sa in SIZE_ORDER and sb in SIZE_ORDER:
        if abs(SIZE_ORDER[sa] - SIZE_ORDER[sb]) > 1:
            conflicts["size"] = f"size ({sa} vs {sb})"

    if colors_contradict(color_tokens_a, color_tokens_b):
        conflicts["color"] = "primary color descriptions"

    return conflicts


# ── narrative-conflict (markings) veto ───────────────────────────────────────

_MARKING_COLORS = frozenset({
    "white", "black", "brown", "tan", "gray", "grey", "red", "orange",
    "yellow", "blonde", "blond", "golden", "cream", "blue", "brindle",
    "merle", "fawn", "silver", "chocolate", "liver", "sable", "spotted",
})

# bodypart key → surface forms accepted in text
_MARKING_BODYPARTS: dict[str, tuple[str, ...]] = {
    "chest": ("chest", "breast"),
    "belly": ("belly", "stomach", "tummy"),
    "paw": ("paw", "paws", "foot", "feet"),
    "leg": ("leg", "legs"),
    "face": ("face",),
    "mask": ("mask",),
    "blaze": ("blaze",),
    "stripe": ("stripe", "stripes", "striping"),
    "patch": ("patch", "patches"),
    "spot": ("spot", "spots", "spotting"),
    "tail": ("tail",),
    "ear": ("ear", "ears"),
    "muzzle": ("muzzle", "snout"),
    "nose": ("nose",),
    "back": ("back",),
    "neck": ("neck",),
    "head": ("head",),
}
_SURFACE_TO_BODYPART = {
    surface: key
    for key, surfaces in _MARKING_BODYPARTS.items()
    for surface in surfaces
}

# marking nouns whose color describes a nearby bodypart rather than themselves
_MODIFIER_NOUNS = frozenset({"patch", "spot", "stripe", "blaze"})
_CONNECTORS = frozenset({
    "on", "the", "a", "an", "his", "her", "its", "their", "and",
    "of", "over", "at", "in", "left", "right", "front", "rear", "back",
})


def extract_markings(text: str | None) -> dict[str, set[str]]:
    """Extract color+bodypart markings ("white chest" → chest: {white}).

    Scans adjacent word pairs for a color word next to a bodypart word in
    either order ("white patch on chest", "chest is white"). Note: collar /
    scar / notch mentions are deliberately NOT extracted — their absence on
    the other report is not contradictory (collars are removable; scars and
    ear-notches are frequently unreported rather than absent).
    """
    if not text:
        return {}
    words = re.findall(r"[a-z]+", text.lower())
    marks: dict[str, set[str]] = {}
    for i in range(len(words) - 1):
        w1, w2 = words[i], words[i + 1]
        color, part = None, None
        if w1 in _MARKING_COLORS and w2 in _SURFACE_TO_BODYPART:
            color, part = w1, _SURFACE_TO_BODYPART[w2]
        elif w2 in _MARKING_COLORS and w1 in _SURFACE_TO_BODYPART:
            color, part = w2, _SURFACE_TO_BODYPART[w1]
        if not (color and part):
            continue
        marks.setdefault(part, set()).add(color)
        # "white patch on left front paw" — propagate the color from a
        # marking-noun (patch/spot/stripe/blaze) to the bodypart that follows
        # within a few connector words.
        if part in _MODIFIER_NOUNS:
            j = i + 2
            while j < len(words) and j <= i + 5:
                w = words[j]
                if w in _SURFACE_TO_BODYPART:
                    marks.setdefault(_SURFACE_TO_BODYPART[w], set()).add(color)
                    break
                if w not in _CONNECTORS:
                    break
                j += 1
    return marks


def markings_contradict(
    marks_a: dict[str, set[str]], marks_b: dict[str, set[str]]
) -> list[str]:
    """Human-readable conflicts where a shared bodypart has disjoint colors.

    Both marking sets must be non-empty (sparse records are never penalized).
    A bodypart appearing on both sides with zero shared color modifiers is a
    contradiction ("white chest" vs "black chest").
    """
    if not marks_a or not marks_b:
        return []
    conflicts: list[str] = []
    for part in sorted(set(marks_a) & set(marks_b)):
        colors_a, colors_b = marks_a[part], marks_b[part]
        if not (colors_a & colors_b):
            conflicts.append(
                f"{'/'.join(sorted(colors_a))} {part} vs "
                f"{'/'.join(sorted(colors_b))} {part}"
            )
    return conflicts


# ── Signal scoring functions ──────────────────────────────────────────────────

def geo_distance_miles(
    lat1: float | None, lon1: float | None,
    lat2: float | None, lon2: float | None,
) -> float | None:
    """Haversine distance in miles between two points. Returns None if either point is missing."""
    if any(v is None for v in (lat1, lon1, lat2, lon2)):
        return None
    R = 3958.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lam = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def score_geo_distance(dist_miles: float | None) -> dict[str, float]:
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
    date_a: date | None, date_b: date | None
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


def score_breed_match(breed_a: str | None, breed_b: str | None) -> dict[str, float]:
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
    color_a: str | None, color_b: str | None, weight: float = 0.10
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


def score_name_match(name_a: str | None, name_b: str | None) -> dict[str, float]:
    if not name_a or not name_b:
        return {}
    if name_a.lower().strip() == name_b.lower().strip():
        return {"name_exact": 0.15}
    return {}


def score_microchip(chip_a: str | None, chip_b: str | None) -> dict[str, float]:
    if not chip_a or not chip_b:
        return {}
    if chip_a.strip() == chip_b.strip():
        return {"microchip_match": 0.50}  # Conclusive match
    return {}


def score_description_overlap(desc_a: str | None, desc_b: str | None) -> dict[str, float]:
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


def score_zip_match(zip_a: str | None, zip_b: str | None) -> dict[str, float]:
    if not zip_a or not zip_b:
        return {}
    if zip_a[:5] == zip_b[:5]:
        return {"zip_match": 0.08}
    return {}


def score_contact_phone(phone_a: str | None, phone_b: str | None) -> dict[str, float]:
    """Matching phone numbers are strong evidence of the same owner (especially for dedup)."""
    if not phone_a or not phone_b:
        return {}
    import re
    digits_a = re.sub(r"\D", "", phone_a)
    digits_b = re.sub(r"\D", "", phone_b)
    if len(digits_a) < 7 or len(digits_b) < 7:
        return {}
    if digits_a == digits_b:
        return {"contact_phone_match": 0.35}
    # Last 7 digits match (local number vs. number with area code)
    if digits_a[-7:] == digits_b[-7:]:
        return {"contact_phone_partial": 0.15}
    return {}
