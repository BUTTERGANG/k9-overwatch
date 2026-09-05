"""PawBoost page-state classification.

Rapid headless requests trigger Cloudflare 403 interstitials; those must be
skipped per-status rather than raised as structural site changes.
"""
from k9overwatch.scrapers.browser.pawboost import (
    PAGE_CHALLENGE,
    PAGE_OK,
    PAGE_STRUCTUREAL,
    classify_listing_page,
)


def test_cards_present_is_ok():
    assert classify_listing_page(200, "<html></html>", 20) == PAGE_OK


def test_403_is_challenge():
    assert classify_listing_page(403, "denied", 0) == PAGE_CHALLENGE


def test_challenge_markers_on_200_are_challenge():
    html = "Just a moment... Attention Required! | Cloudflare"
    assert classify_listing_page(200, html, 0) == PAGE_CHALLENGE


def test_zero_cards_clean_page_is_structural():
    assert classify_listing_page(200, "<html><body>feed</body></html>", 0) == (
        PAGE_STRUCTUREAL
    )
