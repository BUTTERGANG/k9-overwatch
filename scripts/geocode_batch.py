#!/usr/bin/env python3
"""
Batch geocode DB records that are missing lat/lon.

Reads all active PetRecords from the database that have a location_text or zip
but no coordinates, runs them through the geocoding cascade, and writes results
back to the DB.

Usage:
    python scripts/geocode_batch.py
    python scripts/geocode_batch.py --source indy         # limit to one source
    python scripts/geocode_batch.py --limit 200           # max records to process
    python scripts/geocode_batch.py --dry-run             # show what would be geocoded
    python scripts/geocode_batch.py --provider nominatim  # force a specific provider
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dotenv import load_dotenv
load_dotenv()


async def main() -> None:
    args = sys.argv[1:]

    # Parse CLI flags
    source_filter: str | None = None
    limit: int = 500
    dry_run: bool = False
    provider_name: str = "nominatim"

    i = 0
    while i < len(args):
        if args[i] == "--source" and i + 1 < len(args):
            source_filter = args[i + 1]
            i += 2
        elif args[i] == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1])
            i += 2
        elif args[i] == "--dry-run":
            dry_run = True
            i += 1
        elif args[i] == "--provider" and i + 1 < len(args):
            provider_name = args[i + 1]
            i += 2
        elif args[i] in ("-h", "--help"):
            print(__doc__)
            sys.exit(0)
        else:
            i += 1

    from k9overwatch.db.connection import init_db, get_session
    from k9overwatch.db.models import Base, PetRow
    from k9overwatch.geocoding.geocoder import GeocodingService, _ZIP_CENTROIDS
    from k9overwatch.geocoding.providers.nominatim import NominatimProvider
    from k9overwatch.models.enums import GeocodeConfidence, GeocodeSource
    from k9overwatch.models.pet_record import PetRecord
    from sqlalchemy import and_, select, update

    # Build provider list
    providers = []
    if provider_name == "nominatim":
        providers.append(NominatimProvider())
    elif provider_name == "google":
        from k9overwatch.geocoding.providers.google import GoogleProvider
        providers.append(GoogleProvider(api_key=os.getenv("GOOGLE_MAPS_API_KEY", "")))
    elif provider_name == "none":
        pass  # ZIP centroid fallback only
    else:
        print(f"Unknown provider '{provider_name}'. Use: nominatim, google, none")
        sys.exit(1)

    await init_db()

    print(f"\n{'='*60}")
    print(f"  Batch Geocoder")
    print(f"  Provider:  {provider_name}")
    print(f"  Source:    {source_filter or 'all'}")
    print(f"  Limit:     {limit}")
    print(f"  Dry run:   {dry_run}")
    print(f"  Started:   {datetime.now().isoformat(timespec='seconds')}")
    print(f"{'='*60}\n")

    geocoded = 0
    skipped = 0
    errors = 0

    async with get_session() as session:
        # Find records missing coordinates but having an address
        filters = [
            PetRow.active == True,
            PetRow.lat == None,
        ]
        if source_filter:
            filters.append(PetRow.source == source_filter)

        stmt = (
            select(PetRow)
            .where(and_(*filters))
            .limit(limit)
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()

    total = len(rows)
    print(f"Found {total} records missing coordinates.\n")

    if dry_run:
        print("DRY RUN — no changes will be written.\n")

    for idx, row in enumerate(rows, 1):
        # Reconstruct a minimal PetRecord for geocoding
        record = PetRecord(
            source=row.source,
            source_id=row.source_id,
            record_type=row.record_type,
            location_text=row.location_text,
            zip=row.zip,
            state=row.state,
            country=row.country or "US",
        )

        if not record.needs_geocoding():
            skipped += 1
            continue

        address = record.geocoding_address()
        if not address:
            skipped += 1
            continue

        try:
            async with get_session() as session:
                geo_service = GeocodingService(session=session, providers=providers)
                enriched = await geo_service.geocode(record)

            if enriched.lat is not None:
                geocoded += 1
                source_label = str(enriched.geocode_source or "unknown")
                conf_label = str(enriched.geocode_confidence or "?")

                print(
                    f"[{idx:4d}/{total}] ✓ {row.source:20s} {row.source_id:10s} "
                    f"→ ({enriched.lat:.5f}, {enriched.lon:.5f})  "
                    f"[{source_label}/{conf_label}]"
                )

                if not dry_run:
                    async with get_session() as session:
                        await session.execute(
                            update(PetRow)
                            .where(PetRow.id == row.id)
                            .values(
                                lat=enriched.lat,
                                lon=enriched.lon,
                                geocode_source=str(enriched.geocode_source),
                                geocode_confidence=str(enriched.geocode_confidence),
                            )
                        )
            else:
                skipped += 1
                print(
                    f"[{idx:4d}/{total}] ✗ {row.source:20s} {row.source_id:10s} "
                    f"  no result for: {address[:60]}"
                )

        except Exception as exc:
            errors += 1
            print(f"[{idx:4d}/{total}] ERROR {row.source}/{row.source_id}: {exc}")

        # Nominatim rate-limit: 1 req/sec
        if provider_name == "nominatim" and not dry_run:
            await asyncio.sleep(1.1)

    print(f"\n{'='*60}")
    print(f"  Done. Geocoded: {geocoded}  Skipped: {skipped}  Errors: {errors}")
    if dry_run:
        print("  (Dry run — no data written)")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(main())
