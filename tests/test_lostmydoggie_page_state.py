"""LostMyDoggie page-state classification (2026-08 repair).

Live finding: card selectors (.box_icon etc.) remain correct, but rapid
sequential searches trigger Cloudflare 403 challenges mid-scrape. The
challenge page has zero .box_icon cards and was being misread as
"site layout changed", aborting the whole run via StructuralChangeError.
"""
from k9overwatch.scrapers.browser.lostmydoggie import (
    PAGE_CHALLENGE,
    PAGE_EMPTY,
    PAGE_OK,
    PAGE_STRUCTUREAL,
    classify_listing_page,
)


def test_ok_page_with_cards():
    assert classify_listing_page(200, "<div class='box_icon'></div>", 20) == PAGE_OK


def test_empty_results_page_is_not_structural():
    # 200 with a result-count header but zero cards = legitimately empty feed
    assert classify_listing_page(
        200, "<h1>Showing 0 - Found Pets</h1>", 0
    ) == PAGE_EMPTY


def test_cloudflare_403_is_challenge():
    html = "Performing security verification ... Ray ID: abc123 cloudflare"
    assert classify_listing_page(403, html, 0) == PAGE_CHALLENGE


def test_challenge_markers_on_200_are_still_challenge():
    html = "Please stand by, we are checking your browser before accessing"
    assert classify_listing_page(200, html, 0) == PAGE_CHALLENGE


def test_zero_cards_no_challenge_marker_is_structural():
    assert classify_listing_page(200, "<html><body>hello</body></html>", 0) == (
        PAGE_STRUCTUREAL
    )


def test_500_without_challenge_is_structural():
    assert classify_listing_page(500, "server error", 0) == PAGE_STRUCTUREAL
