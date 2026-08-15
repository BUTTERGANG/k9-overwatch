"""PetFBI scraper — AWS WAF protected, GraphQL API, Playwright with anti-automation flags.

AWS WAF on api.petfbi.org uses a CAPTCHA challenge that is silently resolved by the
AwsWafIntegration SDK when the browser passes real fingerprinting signals.  The key
requirements are:
  1. --disable-blink-features=AutomationControlled launch flag
  2. navigator.webdriver overridden to undefined via init script
  3. Geolocation granted so the YES+SEARCH UI flow establishes the WAF session
  4. All GraphQL calls go through AwsWafIntegration.fetch() (page.evaluate)

The PetFBI API requires start_date/end_date to return results; without a date
range the resultCount is always 0.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

from ...models.pet_record import PetRecord
from ...normalizers.petfbi import PetFBINormalizer
from .base_browser import BrowserBaseScraper

GRAPHQL_QUERY = """
query searchReports($input: ReportSearch!) {
  result: searchReportsPublic(input: $input) {
    metadata {
      code
      success
      message
      resultCount
      nextPageToken
    }
    reports {
      report_id
      animal_name
      species
      report_type
      status
      event_date
      last_updated
      breedlabel1
      breedlabel2
      colorlabel1
      colorlabel2
      colorlabel3
      markings
      collar
      height
      weight
      age
      gender
      hair_length
      coat_type
      location_comments
      comments
      picture_file
      public_email
      contact_name
      geo_latitude
      geo_longitude
    }
  }
}
"""

# report_type integer codes used by the PetFBI API
REPORT_TYPE_LOST = 1
REPORT_TYPE_FOUND = 2

# Default lookback when no `after` date is provided (full scrape)
FULL_SCRAPE_LOOKBACK_DAYS = 180


class PetFBIScraper(BrowserBaseScraper):
    SOURCE_NAME = "petfbi"
    STEALTH_REQUIRED = False    # AWS WAF, not Cloudflare
    BROWSER_ARGS = ["--disable-blink-features=AutomationControlled"]

    GRAPHQL_ENDPOINT = "https://api.petfbi.org/v3prod/public"
    SEARCH_URL = "https://petfbi.org/search.html"

    def __init__(self, config):
        super().__init__(config)
        self.normalizer = PetFBINormalizer()

    async def _setup_context(self, context) -> None:
        """Grant geolocation and suppress navigator.webdriver for WAF fingerprinting."""
        await context.grant_permissions(["geolocation"])
        await context.set_geolocation({
            "latitude": self.config.search_lat,
            "longitude": self.config.search_lon,
        })
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

    async def _scrape_with_page(self, page, after: datetime | None) -> AsyncIterator[PetRecord]:
        # Phase 1: UI flow to establish WAF session for api.petfbi.org
        ok = await self._establish_waf_session(page)
        if not ok:
            raise RuntimeError("Failed to establish AWS WAF session for PetFBI")

        # Phase 2: Paginated GraphQL via AwsWafIntegration.fetch() in page context
        async for record in self._graphql_scrape(page, after):
            yield record

    async def _establish_waf_session(self, page) -> bool:
        """
        Load PetFBI search page, click YES (use my location), click SEARCH.
        The AwsWafIntegration SDK silently solves the api.petfbi.org CAPTCHA
        challenge when the browser fingerprints pass.  Wait for the first 200
        API response to confirm the session is established.
        """
        try:
            await page.goto(self.SEARCH_URL, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(5)
        except Exception as exc:
            self._record_error(exc, "PetFBI page load")
            return False

        session_ready = asyncio.Event()

        async def on_response(resp):
            if "api.petfbi.org" in resp.url and resp.status == 200:
                session_ready.set()

        page.on("response", on_response)

        # Click YES (use current location)
        try:
            yes = await page.query_selector("button:has-text('YES')")
            if yes:
                await yes.click()
                await asyncio.sleep(2)
        except Exception:
            pass

        # Click SEARCH
        try:
            search = await page.query_selector("button:has-text('SEARCH')")
            if search:
                cls = await search.get_attribute("class") or ""
                if "disabled" not in cls:
                    await search.click()
        except Exception as exc:
            self._record_error(exc, "PetFBI SEARCH click")
            return False

        try:
            await asyncio.wait_for(session_ready.wait(), timeout=20)
            return True
        except TimeoutError:
            self._record_error(RuntimeError("Timed out waiting for WAF session"), "PetFBI WAF")
            return False

    async def _graphql_scrape(
        self, page, after: datetime | None
    ) -> AsyncIterator[PetRecord]:
        """
        Paginate through PetFBI GraphQL results using AwsWafIntegration.fetch()
        called from the page's JS context (where the WAF SDK is loaded and the
        session is already established).
        """
        next_page_token = None
        page_count = 0

        while True:
            if self.config.max_pages and page_count >= self.config.max_pages:
                break

            # PetFBI requires a date range — without it resultCount is always 0
            if after:
                start_dt = after
            else:
                start_dt = datetime.now(UTC) - timedelta(days=FULL_SCRAPE_LOOKBACK_DAYS)

            variables: dict = {
                "input": {
                    "latitude": self.config.search_lat,
                    "longitude": self.config.search_lon,
                    "distance": self.config.search_radius_miles,
                    "report_type": [REPORT_TYPE_LOST, REPORT_TYPE_FOUND],
                    "start_date": start_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                    "end_date": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                }
            }
            if next_page_token:
                variables["input"]["nextPageToken"] = next_page_token

            payload = json.dumps({
                "operationName": "searchReports",
                "query": GRAPHQL_QUERY,
                "variables": variables,
            })

            try:
                data = await page.evaluate(
                    """
                    async (payload) => {
                        const resp = await AwsWafIntegration.fetch(
                            'https://api.petfbi.org/v3prod/public',
                            {
                                method: 'POST',
                                headers: {'Content-Type': 'application/json'},
                                body: payload
                            }
                        );
                        if (!resp.ok && resp.status !== 200) {
                            const text = await resp.text();
                            throw new Error('HTTP ' + resp.status + ': ' + text.slice(0, 200));
                        }
                        return await resp.json();
                    }
                    """,
                    payload,
                )
            except Exception as exc:
                self._record_error(exc, f"GraphQL page {page_count}")
                break

            result = data.get("data", {}).get("result")
            if result is None and page_count == 0:
                from ..base import StructuralChangeError
                raise StructuralChangeError(f"Unexpected GraphQL response structure: {data}")
                
            metadata = result.get("metadata", {})
            reports = result.get("reports", [])

            for report in reports:
                try:
                    record = self.normalizer.normalize(report)
                    self._records_fetched += 1
                    yield record
                except Exception as exc:
                    self._record_error(exc, f"report {report.get('report_id')}")

            next_page_token = metadata.get("nextPageToken")  # cursor-based pagination
            if not next_page_token or not reports:
                break

            page_count += 1
            await asyncio.sleep(self.config.rate_limit_seconds)

    async def check_active(self, source_id: str) -> bool:
        return True  # PetFBI doesn't expose a single-record endpoint publicly
