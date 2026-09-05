"""PawBoost URL construction (2026-08 scheme).

The old `/lost-found-pets/{zip}/all-lost-pets/page-N` path now returns 404.
Page 1 must use the query-param feed (`/lost-found-pets?LfdbFeedStatusForm[...]`),
and pages ≥2 use the canonical city-state-zip slug path confirmed in the live
pagination links (`/lost-found-pets/{city-slug}-{state}-{zip}/{status-slug}/page-N`).
"""
from k9overwatch.scrapers.browser.pawboost import (
    STATUS_FOUND,
    STATUS_LOST,
    build_feed_url,
)


def test_page_1_uses_query_param_feed():
    url = build_feed_url("46201", STATUS_LOST, 25, 1)
    assert url.startswith("https://www.pawboost.com/lost-found-pets?")
    assert "/page-" not in url
    assert "LfdbFeedStatusForm%5Bzip%5D=46201" in url
    assert "LfdbFeedStatusForm%5Bstatus%5D=100" in url
    assert "LfdbFeedStatusForm%5Bradius%5D=25" in url
    assert "LfdbFeedStatusForm%5BsortAttribute%5D=recency" in url
    assert "LfdbFeedStatusForm%5BdateRange%5D=90" in url


def test_found_status_uses_101():
    url = build_feed_url("46201", STATUS_FOUND, 25, 1)
    assert "LfdbFeedStatusForm%5Bstatus%5D=101" in url


def test_later_pages_use_canonical_slug_path():
    slug = "indianapolis-in-46201"
    url = build_feed_url("46201", STATUS_LOST, 25, 2, canonical_slug=slug)
    assert url == (
        "https://www.pawboost.com/lost-found-pets/"
        f"{slug}/all-lost-pets/page-2"
    )


def test_status_slug_matches_status():
    slug = "indianapolis-in-46201"
    found = build_feed_url("46201", STATUS_FOUND, 25, 3, canonical_slug=slug)
    assert found.endswith(f"{slug}/all-found-stray-pets/page-3")
