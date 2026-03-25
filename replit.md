# K9-Overwatch

Lost & found pet aggregation platform that pulls listings from multiple sources into a unified geographic map view.

## Architecture

- **Framework**: FastAPI with Jinja2 templates
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
```

## Running the App

The workflow command is:
```
PYTHONPATH=src uvicorn k9overwatch.web.main:app --host 0.0.0.0 --port 5000 --reload
```

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
| `LOG_LEVEL` | `INFO` | |
