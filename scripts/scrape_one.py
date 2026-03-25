#!/usr/bin/env python3
"""
Run a single scraper and print results to stdout.

Usage:
    python scripts/scrape_one.py indy          # IndyLostPetAlert
    python scripts/scrape_one.py 24petconnect  # 24petconnect
    python scripts/scrape_one.py pawboost      # PawBoost (requires Playwright)
    python scripts/scrape_one.py petfbi        # PetFBI (requires Playwright)
    python scripts/scrape_one.py lostmydoggie  # LostMyDoggie (requires Playwright)

Optional flags:
    --max-pages N    Limit pages fetched (default: 2 for quick test)
    --save           Also write to database
    --show-raw       Print raw source data alongside normalized fields
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dotenv import load_dotenv
load_dotenv()


SCRAPER_MAP = {
    "indy": ("k9overwatch.scrapers.http.indy_lost_pet_alert", "IndyLostPetAlertScraper"),
    "indylostpetalert": ("k9overwatch.scrapers.http.indy_lost_pet_alert", "IndyLostPetAlertScraper"),
    "24petconnect": ("k9overwatch.scrapers.http.petconnect24", "PetConnect24Scraper"),
    "pawboost": ("k9overwatch.scrapers.browser.pawboost", "PawBoostScraper"),
    "petfbi": ("k9overwatch.scrapers.browser.petfbi", "PetFBIScraper"),
    "lostmydoggie": ("k9overwatch.scrapers.browser.lostmydoggie", "LostMyDoggieScraper"),
}


async def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    source = args[0].lower()
    if source not in SCRAPER_MAP:
        print(f"Unknown source '{source}'. Choose from: {', '.join(SCRAPER_MAP)}")
        sys.exit(1)

    # Parse flags
    max_pages = 2
    save = False
    show_raw = False
    for i, arg in enumerate(args[1:]):
        if arg == "--max-pages" and i + 2 < len(args):
            max_pages = int(args[i + 2])
        elif arg == "--save":
            save = True
        elif arg == "--show-raw":
            show_raw = True

    module_path, class_name = SCRAPER_MAP[source]
    import importlib
    module = importlib.import_module(module_path)
    ScraperClass = getattr(module, class_name)

    from k9overwatch.scrapers.base import ScraperConfig
    config = ScraperConfig(
        search_lat=float(os.getenv("SEARCH_LAT", "39.7684")),
        search_lon=float(os.getenv("SEARCH_LON", "-86.1581")),
        search_radius_miles=int(os.getenv("SEARCH_RADIUS_MILES", "25")),
        max_pages=max_pages,
        extra={"zip_code": os.getenv("SEARCH_ZIP", "46201")},
    )

    scraper = ScraperClass(config)
    count = 0

    print(f"\n{'='*60}")
    print(f"  Scraping: {source}  (max_pages={max_pages})")
    print(f"  Center: {config.search_lat}, {config.search_lon}  radius={config.search_radius_miles}mi")
    print(f"{'='*60}\n")

    if save:
        from k9overwatch.db.connection import init_db, get_session
        from k9overwatch.db.repository import PetRepository
        from k9overwatch.geocoding.geocoder import GeocodingService
        from k9overwatch.geocoding.providers.nominatim import NominatimProvider
        await init_db()

    async for record in scraper.scrape():
        count += 1
        print(f"[{count:3d}] {record.record_type:8s} | {str(record.animal_type):5s} | "
              f"{str(record.gender or '?'):6s} | {record.breed or '?':25s} | "
              f"{str(record.color_primary or '?'):10s} | {record.name or '(no name)':15s} | "
              f"{'★geo' if record.lat else '?geo':4s} | {record.source_id}")

        if show_raw and record.raw:
            print(f"     RAW: {json.dumps(record.raw, default=str)[:200]}")

        if save:
            async with get_session() as session:
                repo = PetRepository(session)
                geocoder = GeocodingService(session, [NominatimProvider()])
                if record.needs_geocoding():
                    record = await geocoder.geocode(record)
                row, created = await repo.upsert(record)
                print(f"     DB: {'CREATED' if created else 'updated'} id={row.id[:8]}")

    print(f"\nTotal: {count} records | Errors: {len(scraper._errors)}")
    for err in scraper._errors[:5]:
        print(f"  ERROR: {err}")


if __name__ == "__main__":
    asyncio.run(main())
