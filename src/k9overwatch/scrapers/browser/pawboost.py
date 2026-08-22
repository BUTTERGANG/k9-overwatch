"""PawBoost scraper — Cloudflare protected, Playwright required."""
from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from datetime import datetime
from urllib.parse import parse_qs, unquote, urlparse

from ...models.pet_record import PetRecord
from ...normalizers.pawboost import PawBoostNormalizer
from ..base import StructuralChangeError
from .base_browser import BrowserBaseScraper

_DATE_PATTERN = (
    r"(January|February|March|April|May|June|July|August|September|October"
    r"|November|December)\s+\d+,?\s+\d{4}"
)

# status=100 lost, status=101 found/stray
STATUS_LOST = 100
STATUS_FOUND = 101

_STATUS_SLUGS = {
    STATUS_LOST: "all-lost-pets",
    STATUS_FOUND: "all-found-stray-pets",
}

# Page states for listing responses
PAGE_OK = "ok"
PAGE_CHALLENGE = "challenge"  # Cloudflare interstitial — transient, skip status
PAGE_STRUCTUREAL = "structural"

_CHALLENGE_MARKERS = (
    "just a moment",
    "attention required! | cloudflare",
    "performing security verification",
    "checking your browser",
    "cf-browser-verification",
)


def classify_listing_page(status: int | None, html: str, card_count: int) -> str:
    """Classify a PawBoost listing response.

    Rapid headless requests trigger Cloudflare 403 interstitials; those are
    transient and must NOT be reported as structural site changes.
    """
    if card_count > 0:
        return PAGE_OK
    body = (html or "").lower()
    if status == 403 or any(m in body for m in _CHALLENGE_MARKERS):
        return PAGE_CHALLENGE
    return PAGE_STRUCTUREAL


def build_feed_url(
    zip_code: str,
    status_code: int,
    radius_miles: int | float,
    page_num: int,
    canonical_slug: str | None = None,
) -> str:
    """Build a PawBoost listing URL for the current (2026-08 verified) scheme.

    Page 1 must use the query-param feed — the legacy
    ``/lost-found-pets/{zip}/{status-slug}/page-1`` path now 404s. Pages ≥2 use
    the canonical ``/{city-slug}-{state}-{zip}/{status-slug}/page-N`` path that
    the site's own pagination links point at (``canonical_slug`` captured from
    page 1's DOM; falls back to query-param form when unknown).
    """
    if page_num > 1 and canonical_slug:
        return (
            f"https://www.pawboost.com/lost-found-pets/"
            f"{canonical_slug}/{_STATUS_SLUGS[status_code]}/page-{page_num}"
        )
    return (
        "https://www.pawboost.com/lost-found-pets?"
        f"LfdbFeedStatusForm%5Bzip%5D={zip_code}"
        f"&LfdbFeedStatusForm%5Bstatus%5D={status_code}"
        f"&LfdbFeedStatusForm%5Bradius%5D={radius_miles}"
        "&LfdbFeedStatusForm%5BsortAttribute%5D=recency"
        "&LfdbFeedStatusForm%5BdateRange%5D=90"
    )


class PawBoostScraper(BrowserBaseScraper):
    SOURCE_NAME = "pawboost"
    STEALTH_REQUIRED = True

    # status=100 lost, status=101 found/stray
    STATUSES = [(STATUS_LOST, "lost"), (STATUS_FOUND, "found")]

    def __init__(self, config):
        super().__init__(config)
        self.normalizer = PawBoostNormalizer()
        # Use ZIP code from config extra or default to searching by lat/lon city
        self.zip_code = config.extra.get("zip_code", "46201")

    async def _scrape_with_page(self, page, after: datetime | None) -> AsyncIterator[PetRecord]:
        for status_code, record_type in self.STATUSES:
            async for record in self._scrape_status(page, status_code, record_type, after):
                yield record

    async def _scrape_status(
        self, page, status_code: int, record_type: str, after: datetime | None
    ) -> AsyncIterator[PetRecord]:
        page_num = 1
        canonical_slug: str | None = None

        while True:
            if self.config.max_pages and page_num > self.config.max_pages:
                break

            url = build_feed_url(
                self.zip_code, status_code, self.config.search_radius_miles,
                page_num, canonical_slug=canonical_slug,
            )

            try:
                resp = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                # Give JS-rendered content time to populate
                await asyncio.sleep(3)
                status = resp.status if resp else None
            except Exception as exc:
                self._record_error(exc, f"PawBoost page {page_num}")
                break

            cards = await page.query_selector_all(".pet-search-result")
            if not cards:
                state = classify_listing_page(status, await page.content(), 0)
                if page_num == 1:
                    if state == PAGE_CHALLENGE:
                        # Transient Cloudflare interstitial — skip this status
                        # rather than flagging a structural site change.
                        self._record_error(
                            RuntimeError(
                                f"Cloudflare challenge (HTTP {status}) on "
                                f"{record_type} feed page {page_num}; status skipped"
                            ),
                            "PawBoost challenge",
                        )
                        return
                    raise StructuralChangeError(
                        "No '.pet-search-result' cards found on page 1. "
                        "Site layout may have changed."
                    )
                break

            # Capture the canonical city-state-zip slug the site's own
            # pagination uses so later pages hit the working /page-N path.
            if canonical_slug is None:
                next_btn = await page.query_selector("a[rel='next'], .pagination .next")
                next_href = (
                    await next_btn.get_attribute("href") if next_btn else None
                )
                m = re.search(
                    r"/lost-found-pets/([a-z0-9-]+-\d{5})/", next_href or ""
                )
                if m:
                    canonical_slug = m.group(1)

            page_has_new = False
            for card in cards:
                try:
                    raw_data = await self._extract_card_data(card)
                    if not raw_data:
                        continue

                    # Stop paginating if we've hit records older than `after`
                    if after and raw_data.get("reported_timestamp"):
                        card_time = datetime.fromtimestamp(raw_data["reported_timestamp"])
                        if card_time < after:
                            return

                    record = self.normalizer.normalize(raw_data, record_type)
                    self._records_fetched += 1
                    page_has_new = True
                    yield record
                except Exception as exc:
                    self._record_error(exc, "PawBoost card")

            if not page_has_new:
                break

            # Check if there's a next page
            next_btn = await page.query_selector("a[rel='next'], .pagination .next")
            if not next_btn:
                break

            page_num += 1
            await asyncio.sleep(self.config.rate_limit_seconds)

    async def _extract_card_data(self, card) -> dict | None:
        """Extract raw data from a PawBoost listing card element."""
        try:
            # Pet ID — text is "LOST PawBoost ID: 72693371", extract numeric part
            id_el = await card.query_selector(".pet-feed-id")
            pet_id_raw = (await id_el.inner_text()).strip() if id_el else None
            pet_id = None
            if pet_id_raw:
                m = re.search(r"(\d+)", pet_id_raw)
                pet_id = m.group(1) if m else pet_id_raw
            if not pet_id:
                return None

            # Name — h2 with class pet-feed-name; inner_text includes nested <small>
            # Use JS to get only the direct text node (before the <small>)
            name_el = await card.query_selector("h2.pet-feed-name, .pet-feed-name")
            name = None
            if name_el:
                name = await name_el.evaluate(
                    "el => [...el.childNodes]"
                    ".filter(n => n.nodeType === 3)"  # TEXT_NODE only
                    ".map(n => n.textContent.trim())"
                    ".filter(t => t.length > 0)"
                    ".join(' ')"
                )
                name = name.strip() or None

            # Species and gender — <small class="pet-feed-details"> contains "Male Dog"
            details_el = await card.query_selector(".pet-feed-details")
            details_text = (await details_el.inner_text()).strip() if details_el else ""
            # Split into tokens: "Male Dog" → ["Male", "Dog"]
            details = [t.strip() for t in details_text.split() if t.strip()]

            # Location city/state/zip — <h3 class="pet-feed-location">
            loc_el = await card.query_selector(".pet-feed-location")
            location_city = (await loc_el.inner_text()).strip() if loc_el else None

            # Last seen address from img alt attribute
            # Format: "Lost Male Dog last seen [address]"
            img_el = await card.query_selector("img[alt]")
            img_alt = await img_el.get_attribute("alt") if img_el else None
            location_text = None
            if img_alt:
                m = re.search(r"last\s+seen\s+(.+)$", img_alt, re.IGNORECASE)
                if m:
                    location_text = m.group(1).strip()

            # Description — <p class="pet-feed-description"> (the <p> itself has the class)
            desc_el = await card.query_selector(".pet-feed-description")
            description = (await desc_el.inner_text()).strip() if desc_el else None

            # Status badge
            badge = await card.query_selector(".label-danger, .label-success")
            badge_text = (await badge.inner_text()).strip() if badge else None

            # Thumbnail URL
            img_src = await img_el.get_attribute("src") if img_el else None

            # Full size photo from CDN (remove -thumb suffix)
            full_photo = None
            if img_src and "-thumb.jpeg" in img_src:
                full_photo = img_src.replace("-thumb.jpeg", ".jpeg")

            # Detail page URL
            link_el = await card.query_selector("a[href*='/landing/pet/']")
            detail_url = await link_el.get_attribute("href") if link_el else None
            if detail_url and not detail_url.startswith("http"):
                detail_url = f"https://www.pawboost.com{detail_url}"

            # Facebook URL
            fb_el = await card.query_selector("a.btn-facebook")
            fb_url = await fb_el.get_attribute("href") if fb_el else None

            # Nextdoor share URL (encodes owner message + date)
            nd_el = await card.query_selector("a[href*='nextdoor.com'], a[href*='/nd/']")
            nd_url = await nd_el.get_attribute("href") if nd_el else None
            date_lost, owner_message = self._decode_nextdoor_url(nd_url)

            # Extract hash from detail URL
            hash_id = None
            if detail_url:
                m = re.search(r"/landing/pet/([^/]+)/", detail_url)
                if m:
                    hash_id = m.group(1)

            # Extract ZIP from detail URL slug
            zip_code = None
            if detail_url:
                m = re.search(r"-(\d{5})$", detail_url)
                if m:
                    zip_code = m.group(1)

            return {
                "pet_id": pet_id,
                "hash_id": hash_id,
                "name": name,
                "details": details,
                "location_city": location_city,
                "location_text": location_text,
                "description": description,
                "badge": badge_text,
                "thumbnail_url": img_src,
                "full_photo_url": full_photo,
                "detail_url": detail_url,
                "facebook_post_url": fb_url,
                "nextdoor_url": nd_url,
                "date_lost_text": date_lost,
                "owner_message": owner_message,
                "zip_code": zip_code,
            }
        except Exception:
            return None

    def _decode_nextdoor_url(self, url: str | None) -> tuple[str | None, str | None]:
        """Decode the Nextdoor share URL to extract date and owner message."""
        if not url:
            return None, None
        try:
            # The URL contains encoded parameters
            parsed = urlparse(url)
            qs = parse_qs(parsed.query)
            # Nextdoor share URLs typically have 'body' or 'text' params with encoded content
            body = qs.get("body", qs.get("text", [None]))[0]
            if body:
                body = unquote(body)
                date_m = re.search(_DATE_PATTERN, body)
                date_text = date_m.group(0) if date_m else None
                return date_text, body
        except Exception:
            pass
        return None, None

    # PawBoost detail URLs embed a slug that can't be reconstructed from the
    # pet id alone, so liveness checks rely on the stored source_url. The
    # shared browser-backed check in BrowserBaseScraper loads it and fails
    # open when Cloudflare blocks the request.
    NOT_FOUND_MARKERS = ("page not found", "no longer listed", "has been removed")
