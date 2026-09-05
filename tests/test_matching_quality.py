"""Matching-v2 quality validation: do the matches actually look similar?

Scored fixture suites of realistic record pairs:
  (a) obvious      — same distinctive description, near geo   → rank top, medium/high
  (b) coincidence  — common color, close geo/time             → never high
  (c) conflict     — gender mismatch                          → suppressed by soft veto
  (d) sparse-true  — color-only + rare token                  → low/medium + needs_review
  (e) adversarial  — two black labs, different white markings → score(a)-score(e) >= 0.15,
                      separated by description/distinctive-feature signals
"""
from __future__ import annotations

from datetime import date

import pytest

from k9overwatch.db.models import PetRow
from k9overwatch.matching.color_stats import build_color_stats
from k9overwatch.matching.lost_found_matcher import LostFoundMatcher


def _pet(record_type="lost", **kw):
    defaults = dict(
        source="test", source_id="x", animal_type="dog",
    )
    return PetRow(**{**defaults, "record_type": record_type, **kw})


BASE = dict(lat=39.77, lon=-86.11, date_event=date(2026, 3, 20), gender="male", size="M")

# (a) Obvious: same distinctive narrative, 0.3 mi away, next day
LOST_A = _pet(id="A-lost", source_id="A", **BASE,
              breed="Labrador Retriever", color_primary="Black",
              name="Scout",
              distinctive_features="white blaze on chest and one blue eye",
              description="Black lab named Scout, white blaze on chest, one blue eye, "
                          "wearing a red collar, very friendly")
FOUND_A = _pet(record_type="found", id="A-found", source_id="Af",
               lat=39.775, lon=-86.113, date_event=date(2026, 3, 21),
               gender="male", size="M",
               breed="Labrador", color_primary="Black",
               name="Scout",
               description="Black lab named Scout, white blaze on chest, one blue eye, "
                           "wearing a red collar, very friendly and sweet")

# (b) Coincidence: common color only, close geo/time, nothing descriptive
LOST_B = _pet(id="B-lost", source_id="B", **BASE, color_primary="Brown")
FOUND_B = _pet(record_type="found", id="B-found", source_id="Bf",
               lat=39.772, lon=-86.112, date_event=date(2026, 3, 21),
               color_primary="brown")

# (c) Conflict: identical otherwise-plausible pair but opposite genders
LOST_C = _pet(id="C-lost", source_id="C", **{**BASE, "gender": "male"},
              breed="Beagle", color_primary="Tricolor")
FOUND_C = _pet(record_type="found", id="C-found", source_id="Cf",
               lat=39.773, lon=-86.111, date_event=date(2026, 3, 21),
               breed="Beagle", color_primary="Tricolor", gender="female")

# (d) Sparse-but-true: rare color token is all we have
LOST_D = _pet(id="D-lost", source_id="D", color_primary="blue merle")
FOUND_D = _pet(record_type="found", id="D-found", source_id="Df",
               color_primary="Blue Merle")

# (e) Adversarial: two black labs, DIFFERENT white markings, different narratives
LOST_E = _pet(id="E-lost", source_id="E", **BASE,
              breed="Labrador Retriever", color_primary="Black",
              description="Black labrador, white patch on left front paw")
FOUND_E = _pet(record_type="found", id="E-found", source_id="Ef",
               lat=39.774, lon=-86.110, date_event=date(2026, 3, 21),
               gender="male", size="M",
               breed="Lab", color_primary="black",
               description="Friendly black lab found downtown, no collar, "
                           "white spot on belly")


def _matcher(stats=None):
    return LostFoundMatcher(color_stats=stats)


@pytest.fixture(scope="module")
def scores():
    """Compare one lost record against every counterpart; return by label."""
    m = _matcher()
    lost = LOST_A
    results = m.find_matches(lost, [FOUND_A, FOUND_B, FOUND_C, FOUND_D, FOUND_E])
    by_id = {r.pet_b_id: r for r in results}
    return {"a": by_id.get("A-found"), "b": by_id.get("B-found"),
            "c": by_id.get("C-found"), "d": by_id.get("D-found"),
            "e": by_id.get("E-found")}


class TestObviousMatchRanksTop:
    def test_obvious_ranks_first(self, scores):
        assert scores["a"] is not None
        others = [scores[k] for k in "bcde" if scores[k]]
        assert all(scores["a"].score >= o.score for o in others)

    def test_obvious_confidence_medium_or_high(self, scores):
        assert scores["a"].confidence in ("medium", "high")


class TestCoincidenceNeverHigh:
    def test_common_color_close_geo_never_high(self):
        result = _matcher()._compare(LOST_B, FOUND_B)
        assert result is not None
        assert result.confidence != "high"


class TestConflictSuppressedByVeto:
    def test_gender_conflict_drops_below_medium(self):
        result = _matcher()._compare(LOST_C, FOUND_C)
        assert result is not None          # soft mode keeps it visible
        assert result.score < 0.40         # …but below medium threshold
        assert any("gender" in r.lower() for r in result.reasons)

    def test_strict_mode_rejects(self):
        result = LostFoundMatcher(veto_mode="strict")._compare(LOST_C, FOUND_C)
        assert result is None


class TestSparseButTrue:
    def test_rare_color_only_is_low_with_needs_review(self):
        # Corpus where merle is genuinely rare
        stats = build_color_stats(
            [{"color_primary": "black"} for _ in range(60)]
            + [{"color_primary": "merle"}] * 2
        )
        result = _matcher(stats=stats)._compare(LOST_D, FOUND_D)
        assert result is not None
        assert result.score > 0                     # some evidence fired
        assert result.confidence == "low"
        assert "needs_review" in result.labels


class TestAdversarialSeparation:
    def test_adversarial_scores_below_obvious_by_0_15(self, scores):
        assert scores["a"] is not None and scores["e"] is not None
        gap = scores["a"].score - scores["e"].score
        assert gap >= 0.15
        # The separation comes from narrative evidence, not circumstance
        a_sig = scores["a"].signals_fired
        e_sig = scores["e"].signals_fired
        narrative_a = sum(v for k, v in a_sig.items()
                          if k in ("description_high_similarity",
                                   "description_med_similarity",
                                   "distinctive_feature_match"))
        narrative_e = sum(v for k, v in e_sig.items()
                          if k in ("description_high_similarity",
                                   "description_med_similarity",
                                   "distinctive_feature_match"))
        assert narrative_a - narrative_e >= 0.15


class TestRealDataSanity:
    """Query the dev DB (if it has matches) and flag high-confidence pairs
    sharing zero color tokens."""

    @pytest.mark.asyncio
    async def test_no_high_confidence_zero_color_token_matches(self):
        import os

        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from k9overwatch.db.models import PetMatch, PetRow
        from k9overwatch.matching.color_stats import record_color_tokens

        url = os.getenv(
            "DATABASE_URL", "sqlite+aiosqlite:///data/k9overwatch.db"
        )
        # The real-data audit only makes sense against a populated dev DB.
        # In CI (or any checkout without data/), the sqlite file doesn't exist
        # and the query would raise OperationalError instead of skipping — so
        # probe for the file first and skip when absent.
        db_path = url.split("///")[-1]
        if not os.path.exists(db_path):
            pytest.skip(f"dev DB not present at {db_path} — nothing to audit")
        engine = create_async_engine(url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as session:
                matches = list((await session.execute(
                    select(PetMatch).where(PetMatch.confidence.in_(["high", "medium"]))
                )).scalars().all())
                if not matches:
                    pytest.skip("dev DB has no medium/high matches to audit")
                ids = {i for m in matches for i in (m.pet_a_id, m.pet_b_id)}
                rows = {
                    r.id: r for r in (await session.execute(
                        select(PetRow).where(PetRow.id.in_(ids))
                    )).scalars().all()
                }
                flagged = []
                for m in matches:
                    ra, rb = rows.get(m.pet_a_id), rows.get(m.pet_b_id)
                    if not ra or not rb:
                        continue
                    ta = record_color_tokens(ra)
                    tb = record_color_tokens(rb)
                    if ta and tb and not (ta & tb):
                        flagged.append((m.id, m.confidence))
                assert not flagged, f"high/med matches with disjoint colors: {flagged}"
        finally:
            await engine.dispose()
