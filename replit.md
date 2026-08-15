# K9-Overwatch

Lost & found pet aggregation platform that pulls listings from multiple sources into a unified geographic map view.

## Architecture

- **Framework**: FastAPI with Jinja2 templates
- **Frontend**: Tailwind CSS v3 (CDN), HTMX for progressive enhancement, Leaflet.js maps
- **UI Design**: Frosted-glass navbar, dark mode toggle (localStorage + `prefers-color-scheme`), page transitions, mobile-first responsive filter drawers, reusable Jinja2 macros (status_badge, species_icon, loading_spinner)
- **Database**: PostgreSQL (via Replit-managed DB) using SQLAlchemy async engine + asyncpg driver
- **Scheduler**: APScheduler for periodic scraping and match jobs
- **Scraping**: aiohttp (HTTP scrapers) + Playwright (browser scrapers for WAF-protected sites)
- **Matching**: rapidfuzz for string similarity; custom weighted signal scoring
- **Geocoding**: geopy (cascading Google Maps → Nominatim → ZIP centroid fallback)

## Project Structure

```
src/k9overwatch/
  db/            # SQLAlchemy models, async engine, repository
  geocoding/     # Geocoding service and provider adapters
  matching/      # Lost↔found matcher, deduplicator, breed normalizer
  models/        # Pydantic PetRecord schema and enums
  normalizers/   # Source-specific raw data → PetRecord converters
  scrapers/
    http/        # Plain aiohttp scrapers
    browser/     # Playwright scrapers for JS-heavy/WAF sites
  scheduler/     # APScheduler runner and job definitions
  utils/         # HTTP client, logging config, text helpers
  web/
    routers/     # FastAPI route handlers (map, pets, matches, admin)
    schemas/     # Pydantic response schemas (GeoJSON, PetSummary, etc.)
    templates/   # Jinja2 HTML templates
    static/      # JS assets (map.js using Leaflet)
scripts/         # CLI utilities (scrape_one.py, geocode_batch.py)
tests/           # pytest suite (normalizers, matching, geocoding, integration, web routes)
```

## Running the App

The workflow command is:
```
PYTHONPATH=src uvicorn k9overwatch.web.main:app --host 0.0.0.0 --port 5000 --reload
```

## Matching Engine

Signal-weighted scoring system for dedup and lost→found reunification. Key design decisions:

- **Contact phone** (0.35 exact / 0.15 partial) — same owner posting on multiple platforms
- **ZIP weight is 0.08**, not high — ZIP covers ~15 sq miles, less precise than geo distance
- **Description overlap excluded from dedup** — identical descriptions are expected cross-platform
- **Candidate window ±180 days** — supports pets missing for months before being found
- **Score updates** — unreviewed matches are re-scored if a later pass finds a higher score (e.g. after geocoding completes)
- **Immediate matching** — all 5 scrapers run a targeted match pass on new records rather than waiting for the 30-min batch job
- **Human review** — `POST /api/matches/{id}/review?confirmed=true|false` marks a match as confirmed or dismissed; reviewed matches are never auto-updated

## Key Implementation Notes

### Database URL normalization
The Replit-managed `DATABASE_URL` uses the libpq `postgresql://` scheme with query params like `sslmode` and `channel_binding` that asyncpg rejects. `db/connection.py::_normalize_database_url()` rewrites the URL to `postgresql+asyncpg://` and strips unsupported libpq params, translating `sslmode=require` to asyncpg's `ssl=True` connect arg.

### Template API
Uses Starlette 0.36+ `TemplateResponse` API: `templates.TemplateResponse(request, "template.html", context_dict)`. The `request` object is the first positional argument, NOT inside the context dict.

### Deployment
`.replit` deployment config runs on port 8080. Development workflow runs on port 5000.

## Environment Variables

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | (Replit-managed PostgreSQL) | Auto-set by Replit |
| `GEOCODE_PROVIDER` | `nominatim` | `nominatim` or `google` |
| `GOOGLE_MAPS_API_KEY` | — | Required if using Google geocoding |
| `NOMINATIM_USER_AGENT` | `k9overwatch/1.0` | Required for Nominatim |
| `SEARCH_LAT` / `SEARCH_LON` | Indianapolis | Default map center |
| `SEARCH_ZIP` | `46201` | ZIP code for sources that require it |
| `ADMIN_USER` / `ADMIN_PASSWORD` | `admin` / `changeme` | HTTP Basic auth for `/admin` |
| `RUN_SCHEDULER` | `false` | Set `true` to run scrapers inside web process |
| `LOG_LEVEL` | `INFO` | |
