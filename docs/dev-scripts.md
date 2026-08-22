# Dev Scripts

One-off developer/ops utilities. They are not part of the app runtime; run them
from the repo root with the project virtualenv active. Both scripts load `.env`
automatically for DB and API-key configuration.

## `scripts/scrape_one.py`

Run a single scraper and print normalized results to stdout — the fastest way to
check whether a source's markup/API changed.

```bash
python scripts/scrape_one.py indy           # IndyLostPetAlert (HTTP)
python scripts/scrape_one.py 24petconnect   # 24petconnect (HTTP)
python scripts/scrape_one.py pawboost       # PawBoost (requires Playwright)
python scripts/scrape_one.py petfbi         # PetFBI (requires Playwright)
python scripts/scrape_one.py lostmydoggie   # Lost My Doggie (requires Playwright)
```

Flags:
- `--max-pages N` — limit pages fetched (default 2, for quick checks)
- `--save` — also upsert results into the database
- `--show-raw` — print raw source data alongside normalized fields

Exit status is non-zero if the scraper fails; use it in smoke checks.

## `scripts/geocode_batch.py`

Batch geocode DB records that are missing lat/lon. Reads all active records with
a `location_text` or ZIP but no coordinates, runs them through the geocoding
cascade (Google → Nominatim → ZIP-centroid), and writes coordinates back.
Run this after enabling a new source or after a geocode-provider outage; the
periodic `regeocode_pending_records` job only covers recent failures.

```bash
python scripts/geocode_batch.py                    # all sources, default provider
python scripts/geocode_batch.py --source indy      # one source only
python scripts/geocode_batch.py --limit 200        # cap records processed
python scripts/geocode_batch.py --dry-run          # list what would be geocoded
python scripts/geocode_batch.py --provider nominatim
```

Notes:
- Respect Nominatim rate limits — the script throttles automatically, but large
  backlogs take time; prefer `--limit` batches.
- Results are cached in `geocode_cache`, so re-runs are cheap.
