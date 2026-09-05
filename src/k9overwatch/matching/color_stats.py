"""
Color statistics for informativeness-weighted color scoring.

Common colors ("black", "brown") carry little identifying information;
rare ones ("merle", "blue tick") are highly discriminative. We build
token document frequencies from all pet rows in the DB and weight shared
color tokens by their IDF.

Pure functions/classes only: ``build_color_stats`` takes rows (dicts or
PetRow objects); use ``load_color_stats`` to fetch from the DB.
"""
from __future__ import annotations

import math
import re
from collections.abc import Iterable
from typing import Any

# A token is "rare" when it appears in fewer than RARE_TOKEN_FRACTION of records.
RARE_TOKEN_FRACTION = 0.05

# \band\b (not bare "and") so words like "sandy" survive; "-" so "gray-white"
# splits like "gray white".
_SPLIT_RE = re.compile(r"[/,\-]|\band\b|\s+")
_UNKNOWN_VALUES = {"", "unknown", "unk", "n/a", "none", "na"}


def tokenize_color(text: str | None) -> set[str]:
    """Split a free-form color string into a normalized token set."""
    if not text or text.strip().lower() in _UNKNOWN_VALUES:
        return set()
    return {t for t in _SPLIT_RE.split(text.strip().lower()) if t}


def record_color_tokens(record: Any) -> set[str]:
    """Tokenized color set for a record exposing ``color_primary`` /
    ``color_secondary`` as attributes or dict keys. Shared by the matcher,
    deduplicator and corpus builder so tokenization lives in exactly one place.
    """
    cp = getattr(record, "color_primary", None)
    cs = getattr(record, "color_secondary", None)
    if cp is None and isinstance(record, dict):
        cp = record.get("color_primary")
        cs = record.get("color_secondary")
    return tokenize_color(cp) | tokenize_color(cs)


class ColorStats:
    """IDF weights for color tokens over the corpus of pet records."""

    def __init__(self, doc_freq: dict[str, int], total_docs: int) -> None:
        self.doc_freq = doc_freq
        self.total_docs = total_docs

    @property
    def available(self) -> bool:
        return self.total_docs > 0

    def token_idf(self, token: str) -> float:
        """Smoothed IDF log((N+1) / (1 + df)) — always >= 0; higher = rarer.

        The +1 in the numerator keeps the value non-negative even when a token
        appears in every document (df == N), which the plain log(N/(1+df))
        formula would drive below zero on small corpora.
        """
        df = self.doc_freq.get(token, 0)
        return math.log((self.total_docs + 1) / (1 + df))

    def is_rare(self, token: str) -> bool:
        """True when the token appears in < RARE_TOKEN_FRACTION of records."""
        if not self.available:
            return False
        return (self.doc_freq.get(token, 0) / self.total_docs) < RARE_TOKEN_FRACTION

    def to_dict(self) -> dict[str, Any]:
        return {"doc_freq": dict(self.doc_freq), "total_docs": self.total_docs}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ColorStats:
        return cls(doc_freq=dict(data["doc_freq"]), total_docs=int(data["total_docs"]))

    def to_json(self) -> str:
        import json
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, blob: str) -> ColorStats:
        import json
        return cls.from_dict(json.loads(blob))


def build_color_stats(rows: Iterable[Any]) -> ColorStats:
    """
    Build stats from an iterable of records with ``color_primary`` /
    ``color_secondary`` attributes or keys. Pure — no DB access.
    """
    doc_freq: dict[str, int] = {}
    total = 0
    for row in rows:
        tokens = record_color_tokens(row)
        if not tokens:
            continue
        total += 1
        for t in tokens:
            doc_freq[t] = doc_freq.get(t, 0) + 1
    return ColorStats(doc_freq=doc_freq, total_docs=total)


async def load_color_stats(session_factory) -> ColorStats:
    """Query the DB for color document frequencies and build stats."""
    from sqlalchemy import select

    from ..db.models import PetRow

    async with session_factory() as session:
        result = await session.execute(
            select(PetRow.color_primary, PetRow.color_secondary)
        )
        rows = [
            {"color_primary": cp, "color_secondary": cs}
            for cp, cs in result.all()
        ]
    return build_color_stats(rows)


def score_color_match_v2(
    tokens_a: set[str],
    tokens_b: set[str],
    stats: ColorStats | None,
    max_weight: float = 0.20,
) -> dict[str, float]:
    """
    Informativeness-weighted color overlap.

    overlap_score = Σ idf(shared tokens) / Σ idf(tokens of the rarer record),
    scaled by max_weight → signal in 0..max_weight. Returns {} when stats are
    unavailable (caller should fall back to uniform ``score_color_match``).
    """
    if not tokens_a or not tokens_b:
        return {}
    if stats is None or not stats.available:
        return {}
    shared = tokens_a & tokens_b
    if not shared:
        return {}

    # "Rarer" record = fewer tokens (tie → the one with lower total idf mass)
    idf_a = {t: stats.token_idf(t) for t in tokens_a}
    idf_b = {t: stats.token_idf(t) for t in tokens_b}
    denom_a = sum(idf_a.values())
    denom_b = sum(idf_b.values())
    if len(tokens_a) != len(tokens_b):
        denom = denom_a if len(tokens_a) < len(tokens_b) else denom_b
    else:
        denom = min(denom_a, denom_b)
    if denom <= 0:
        return {}

    overlap = sum(idf_a[t] for t in shared) / denom
    signals: dict[str, float] = {"color_overlap_v2": min(1.0, overlap) * max_weight}

    # Distinctive-pair bonus for genuinely rare shared tokens
    if any(stats.is_rare(t) for t in shared):
        signals["color_rare_token"] = 0.08
    return signals
