"""Regression tests for workstream-A hardening fixes.

Covers:
  - tokenize_color: word-boundary 'and' split ("sandy" must survive),
    hyphenated color compounds split into tokens.
  - ColorStats.token_idf: never negative even when a token appears in every
    document (df == N); score_color_match_v2 stays sane on such corpora.
  - record_color_tokens helper used by matcher/deduplicator.
  - jobs.check_stale_records: one source raising must not prevent other
    sources from being checked nor abort the whole job.
"""
import pytest

from k9overwatch.matching.color_stats import (
    build_color_stats,
    record_color_tokens,
    score_color_match_v2,
    tokenize_color,
)


class TestTokenizeColor:
    def test_sandy_is_not_split_by_inner_and(self):
        # Regression: bare "and" alternation split "sandy" -> {"s", "y"}
        assert tokenize_color("Sandy Blonde") == {"sandy", "blonde"}

    def test_orange_survives(self):
        assert tokenize_color("Orange") == {"orange"}

    def test_word_and_splits(self):
        assert tokenize_color("Black and White") == {"black", "white"}

    def test_hyphen_compound_splits(self):
        assert tokenize_color("gray-white") == {"gray", "white"}

    def test_unicode_lowercases(self):
        assert tokenize_color("BLACK") == {"black"}

    def test_none_and_unknown(self):
        assert tokenize_color(None) == set()
        assert tokenize_color("Unknown") == set()


class TestColorStatsNonNegativeIdf:
    def test_idf_never_negative_when_token_in_all_docs(self):
        rows = [
            {"color_primary": "Black", "color_secondary": None},
            {"color_primary": "Black", "color_secondary": "Merle"},
            {"color_primary": "Black", "color_secondary": None},
        ]
        stats = build_color_stats(rows)
        # "black" appears in every doc — old formula log(N/(1+df)) < 0 here.
        assert stats.token_idf("black") >= 0.0
        assert stats.token_idf("merle") > stats.token_idf("black")

    def test_v2_score_on_all_same_color_corpus(self):
        stats = build_color_stats(
            [{"color_primary": "Black", "color_secondary": None} for _ in range(4)]
        )
        # Zero-information token (idf 0) → no signal, never a negative score
        assert score_color_match_v2({"black"}, {"black"}, stats) == {}


def test_record_color_tokens_attr_and_dict():
    class Row:
        color_primary = "Black"
        color_secondary = "White"

    assert record_color_tokens(Row()) == {"black", "white"}
    assert record_color_tokens({"color_primary": "Tan", "color_secondary": None}) == {"tan"}
    assert record_color_tokens({"color_primary": None, "color_secondary": None}) == set()


@pytest.mark.asyncio
async def test_staleness_one_failing_source_does_not_block_others(monkeypatch):
    """A check_active crash (timeout etc.) for one source must not stop the others."""
    import k9overwatch.scheduler.jobs as jobs

    checked: list[str] = []

    class FakeScraper:
        def __init__(self, name, boom=False):
            self.SOURCE_NAME = name
            self.boom = boom

        async def check_active(self, source_id, source_url=None):
            if self.boom:
                raise TimeoutError("simulated scraper timeout")
            return True

    scrapers = {
        "src_ok_1": FakeScraper("src_ok_1"),
        "src_boom": FakeScraper("src_boom", boom=True),
        "src_ok_2": FakeScraper("src_ok_2"),
    }
    monkeypatch.setattr(jobs, "build_staleness_scrapers", lambda config: scrapers)

    class FakeRepo:
        def __init__(self, session):
            pass

        async def get_stale_records(self, source, older_than_hours):
            checked.append(source)
            return []

        async def mark_inactive(self, source, source_id):  # pragma: no cover
            return 1

    monkeypatch.setattr(jobs, "PetRepository", FakeRepo)

    monkeypatch.setattr(FakeScraper, "check_active", FakeScraper.check_active)

    result = await jobs.check_stale_records(stale_hours=48)
    # All three sources were still checked despite src_boom raising
    assert sorted(checked) == ["src_boom", "src_ok_1", "src_ok_2"]
    assert result["deactivated"] == 0
    assert result["per_source"] == {
        "src_ok_1": 0,
        "src_boom": 0,
        "src_ok_2": 0,
    }
