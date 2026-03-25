# K9-Overwatch

A pet aggregation platform that consolidates lost, found, and adoptable animal listings from multiple sources into a single geographic view — helping owners reunite with their pets faster.

---

## Project Goals

1. **Aggregate** lost/found/adoptable pet data from multiple services into a unified database
2. **Geocode** street-level addresses to lat/lon coordinates
3. **Display** pets on an interactive map with filtering by type, status, color, size, and recency
4. **Match** lost pets against found/shelter records using description similarity
5. **Alert** users when new pets matching their criteria appear near their location

---

## Documentation

| File | Description |
|---|---|
| `docs/api-analysis-24petconnect.md` | 24petconnect.com — PetHarbor backend, HTML scraping |
| `docs/api-analysis-pawboost.md` | PawBoost — Cloudflare-protected, Playwright required |
| `docs/api-analysis-indylostpetalert.md` | IndyLostPetAlert — Open WordPress REST API |
| `docs/api-analysis-petfbi.md` | Pet FBI — GraphQL API, AWS WAF protected, provides lat/lon directly |
| `docs/api-analysis-lostmydoggie.md` | Lost My Doggie — Cloudflare-protected, phone alert service |
| `docs/unified-data-schema.md` | Canonical pet record schema across all sources |

---

## Sources

| # | Source | Coverage | Access Method | Status |
|---|---|---|---|---|
| 1 | [24petconnect.com](https://24petconnect.com) | National (US + CA) | HTML scraping via POST | ✅ Built & tested |
| 2 | [pawboost.com](https://www.pawboost.com) | National (US) | Playwright (Cloudflare) | ✅ Built (needs Playwright) |
| 3 | [indylostpetalert.com](https://www.indylostpetalert.com) | Indianapolis metro | WordPress REST API | ✅ Built & tested |
| 4 | [petfbi.org](https://petfbi.org) | National (US) | GraphQL + Playwright (AWS WAF) | ✅ Built (needs Playwright) |
| 5 | [lostmydoggie.com](https://www.lostmydoggie.com) | National (US) | Playwright (Cloudflare) | ✅ Built & tested |

### Planned Sources

| Source | Notes |
|---|---|
| [petfinder.com](https://www.petfinder.com/developers/) | Official public JSON API — adoptions primarily |
| [findingrover.com](https://www.findingrover.com) | Facial recognition for dogs |
| [petcolove.org/lost](https://petcolove.org/lost) | AI-powered facial recognition, Next.js frontend |
| Local municipal shelters | Many run on PetHarbor (same backend as 24petconnect) |

---

## Quick Source Comparison

| | 24petconnect | PawBoost | IndyLostPetAlert | Pet FBI | Lost My Doggie |
|---|---|---|---|---|---|
| **Coverage** | National | National | Indianapolis metro | National | National |
| **Lost pets** | Yes | Yes | Yes | Yes | Yes |
| **Found pets** | Yes | Yes | Yes | Yes | Yes |
| **Adoptions** | Yes | No | No | No | No |
| **Sightings** | No | No | Yes | Yes | No |
| **API type** | HTML POST | HTML GET (Playwright) | JSON REST | GraphQL (Playwright) | HTML GET (Playwright) |
| **Bot protection** | None | Cloudflare (strict) | None | AWS WAF (strict) | Cloudflare (strict) |
| **Auth required** | No | No | No | WAF token | No |
| **Address precision** | Street level | Street level | Street level | Street level | ZIP/city level |
| **Lat/lon provided** | No (geocode) | No (geocode) | No (geocode) | ✅ Yes | No (geocode) |
| **Photos** | Yes | Yes | Yes | Yes | Yes |
| **Breed info** | Yes (structured) | Yes (description) | Yes (description) | Yes (structured) | Yes |
| **Color info** | In description | In description | Structured tag | Yes (structured) | In description |
| **Size info** | In description | In description | Structured category | Yes (structured) | In description |
| **Contact info** | Via form only | Via form only | Phone number exposed | Email (optional) | Via form |
| **Shelter integration** | Yes (PetHarbor) | Yes (5 platforms) | No | No | 35K shelters |
| **Update frequency** | Real-time | 1–2 hr (shelters) | Real-time | Unknown | Real-time |
| **Scraper interval** | 30 min | 35 min | 15 min | 40 min | 45 min |

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Scraper Layer                               │
│                                                                     │
│  HTTP scrapers (no browser needed)   Browser scrapers (Playwright)  │
│  ┌──────────────┐ ┌───────────────┐  ┌──────────┐ ┌──────┐ ┌─────┐ │
│  │ 24petconnect │ │IndyLostPetAlt │  │ PawBoost │ │PetFBI│ │LostM│ │
│  │  aiohttp +   │ │ WP REST API   │  │Cloudflare│ │ AWS  │ │yDogg│ │
│  │  BeautifulS  │ │  incremental  │  │ stealth  │ │ WAF  │ │ ie  │ │
│  └──────┬───────┘ └───────┬───────┘  └────┬─────┘ └──┬───┘ └──┬──┘ │
└─────────┼─────────────────┼───────────────┼──────────┼─────────┼────┘
          │                 │               │          │         │
          ▼                 ▼               ▼          ▼         ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       Normalizer Layer                              │
│         Source-specific HTML/JSON → Canonical PetRecord             │
│    (breed normalization, color parsing, type inference, etc.)       │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        Geocoding Layer                              │
│   location_text → lat/lon  (Google Maps → Nominatim → ZIP centroid) │
│                  Results cached to geocode_cache table              │
│              PetFBI skipped — provides coordinates natively         │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                          Database                                   │
│               SQLite (dev) · NeonDB/PostgreSQL (prod)               │
│          pets · pet_matches · scraper_state · geocode_cache         │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       Matching Engine                               │
│   Deduplication  — same pet on multiple platforms (min score 0.35)  │
│   Lost→Found     — identify matches across record types (min 0.30)  │
│   Signals: geo distance, breed, color, gender, size, name,          │
│            microchip, description overlap, distinctive features     │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       Scheduler (APScheduler)                       │
│   Each scraper runs on its own interval; matching pass every 30 min │
│   Staleness check every 6 hours (marks removed listings inactive)   │
│   Runs inside the web process when RUN_SCHEDULER=true               │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       Web Application (FastAPI)                     │
│   · Interactive Leaflet map — clustered pins, bounding-box search   │
│   · Pet grid — filters by type, status, species, days; HTMX partials│
│   · Pet detail pages — full info, gallery, mini-map, match cards    │
│   · Lost ↔ Found match list — scored pairs with confidence tiers    │
│   · Admin dashboard — scraper health, live stats (auth-protected)   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Getting Started

### Prerequisites

- Python 3.11+
- Playwright (optional — for browser-based scrapers: PawBoost, PetFBI, LostMyDoggie)

### Install

```bash
# Create virtual environment
python3.11 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Install with PostgreSQL support (production)
pip install -e ".[dev,postgres]"

# Install browser scraper dependencies (optional)
pip install -e ".[browser]"
playwright install chromium
```

### Configure

```bash
cp .env.example .env
# Edit .env — set DATABASE_URL, search coordinates, geocoding provider, etc.
```

Key `.env` settings:

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:///data/k9overwatch.db` | Database connection string |
| `SEARCH_LAT` | `39.7684` | Search center latitude (default: Indianapolis) |
| `SEARCH_LON` | `-86.1581` | Search center longitude |
| `SEARCH_RADIUS_MILES` | `25` | Search radius in miles |
| `SEARCH_ZIP` | `46201` | ZIP code for sources that require it |
| `GEOCODE_PROVIDER` | `nominatim` | `nominatim` (free) or `google` |
| `GOOGLE_MAPS_API_KEY` | — | Required only when `GEOCODE_PROVIDER=google` |
| `ADMIN_USER` | `admin` | HTTP Basic username for `/admin` routes |
| `ADMIN_PASSWORD` | `changeme` | HTTP Basic password — **change in production** |
| `RUN_SCHEDULER` | `false` | Set `true` to run scrapers inside the web process |
| `LOG_FORMAT` | `pretty` | `pretty` (dev) or `json` (production) |

### Run the Web App

```bash
# Development
PYTHONPATH=src uvicorn k9overwatch.web.main:app --host 0.0.0.0 --port 5000 --reload

# With scheduler running inside the web process
RUN_SCHEDULER=true PYTHONPATH=src uvicorn k9overwatch.web.main:app --host 0.0.0.0 --port 5000 --reload
```

### Run the Scheduler Standalone

```bash
# As a separate process (alternative to RUN_SCHEDULER=true)
PYTHONPATH=src python -m k9overwatch.scheduler.runner
```

### Test a Single Scraper

```bash
# Quick test — print results to stdout, no DB write
python scripts/scrape_one.py indy --max-pages 2
python scripts/scrape_one.py 24petconnect --max-pages 1

# With DB write and geocoding
python scripts/scrape_one.py indy --max-pages 2 --save

# Show raw source data alongside normalized fields
python scripts/scrape_one.py indy --max-pages 1 --show-raw

# Browser scrapers (requires Playwright)
python scripts/scrape_one.py pawboost --max-pages 2
python scripts/scrape_one.py petfbi --max-pages 1
python scripts/scrape_one.py lostmydoggie --max-pages 2
```

### Run Tests

```bash
# All tests
pytest tests/

# Specific suites
pytest tests/test_normalizers.py     # scraper normalizers
pytest tests/test_matching.py        # matching engine signals
pytest tests/test_geocoding.py       # geocoding service
pytest tests/test_integration.py     # full DB pipeline
pytest tests/test_web_routes.py      # FastAPI route tests
pytest tests/test_repository_extra.py  # repository edge cases
```

---

## Project Structure

```
src/k9overwatch/
├── models/
│   ├── enums.py              # RecordType, AnimalType, Gender, Size, GeocodeSource
│   └── pet_record.py         # PetRecord — canonical in-memory model (Pydantic v2)
├── db/
│   ├── models.py             # SQLAlchemy ORM: PetRow, PetMatch, ScraperState, GeocodeCache
│   ├── connection.py         # Async engine + session factory (SQLite dev / asyncpg prod)
│   └── repository.py         # PetRepository — upsert, geo search, match storage, staleness
├── geocoding/
│   ├── geocoder.py           # GeocodingService — cascade: cache → Google → Nominatim → ZIP
│   └── providers/
│       ├── nominatim.py      # Free, 1 req/sec rate limit
│       └── google.py         # Google Maps Geocoding API (GOOGLE_MAPS_API_KEY required)
├── scrapers/
│   ├── base.py               # BaseScraper ABC + ScraperConfig
│   ├── http/
│   │   ├── indy_lost_pet_alert.py   # WordPress REST API, incremental via after=
│   │   └── petconnect24.py          # ASP.NET HTML POST, LOST/FOUND/ADOPT
│   └── browser/
│       ├── base_browser.py          # Playwright lifecycle + stealth management
│       ├── pawboost.py              # Cloudflare stealth scraper
│       ├── petfbi.py                # AWS WAF token capture → aiohttp GraphQL
│       └── lostmydoggie.py          # Cloudflare stealth scraper
├── normalizers/
│   ├── indy_lost_pet_alert.py       # WP post HTML → PetRecord
│   ├── petconnect24.py              # BeautifulSoup card → PetRecord
│   ├── pawboost.py                  # Card data dict → PetRecord
│   ├── petfbi.py                    # GraphQL response dict → PetRecord
│   └── lostmydoggie.py             # HTML card → PetRecord
├── matching/
│   ├── signals.py            # Scoring functions + MatchResult dataclass
│   ├── breed_normalizer.py   # normalize_breed() with alias dict + rapidfuzz fallback
│   ├── deduplicator.py       # Deduplicator — same pet on multiple platforms
│   └── lost_found_matcher.py # LostFoundMatcher — lost → found reunification
├── scheduler/
│   ├── jobs.py               # run_scraper(), run_matching_pass(), check_stale_records()
│   └── runner.py             # ScraperScheduler — APScheduler interval jobs
├── web/
│   ├── main.py               # FastAPI app + lifespan (init DB, warm pool, optional scheduler)
│   ├── dependencies.py       # get_db() — async session injection
│   ├── templates_config.py   # Jinja2 environment setup
│   ├── routers/
│   │   ├── pets.py           # /pets, /pets/{id}, /pets/results (HTMX partial)
│   │   ├── map.py            # /map, /api/map/geojson (GeoJSON bounding-box endpoint)
│   │   ├── matches.py        # /matches (lost→found pairs, dedup pairs)
│   │   └── admin.py          # /admin, /admin/stats-partial (HTTP Basic auth required)
│   ├── templates/
│   │   ├── base.html         # Nav, mobile hamburger menu, active link highlighting
│   │   ├── macros.html       # Shared Jinja2 macros (camera placeholder SVG, etc.)
│   │   ├── map.html          # Leaflet map + filter sidebar
│   │   ├── pets/             # list.html, _results.html (HTMX partial), card.html, detail.html
│   │   ├── matches/          # list.html — scored match pairs
│   │   ├── admin/            # dashboard.html, stats_partial.html
│   │   └── errors/           # 404.html, 500.html
│   └── static/
│       └── js/
│           └── map.js        # Leaflet pin loading, popups, search-area button, XSS-safe
└── utils/
    └── logging_config.py     # structlog-based JSON/pretty logging (configure_logging())
scripts/
├── scrape_one.py             # CLI test utility for any individual scraper
└── geocode_batch.py          # Batch geocode existing DB records
tests/
├── conftest.py               # Shared async DB fixtures (in-memory SQLite)
├── test_normalizers.py       # All 5 source normalizers against realistic fixtures
├── test_matching.py          # Signal scoring, dedup, lost→found matcher
├── test_geocoding.py         # Geocoding cascade, cache, ZIP centroid fallback
├── test_integration.py       # Full pipeline: upsert → geocode → match → save
├── test_web_routes.py        # FastAPI TestClient: routes, validation, auth
└── test_repository_extra.py  # mark_inactive_bulk, get_stale_records, cache savepoint
docs/
├── api-analysis-*.md         # Per-source API analysis
└── unified-data-schema.md    # Canonical schema + PostgreSQL DDL
```

---

## Web Application

### Pages

| Route | Description |
|---|---|
| `/map` | Interactive Leaflet map — pins colored by record type, bounding-box search, filter sidebar |
| `/pets` | Filterable pet card grid — species, type, days; HTMX partial updates; URL-reflected filter state |
| `/pets/{id}` | Pet detail page — full info, photo gallery, mini-map, matched pets |
| `/matches` | Lost ↔ Found match list — confidence-scored pairs across sources |
| `/admin` | Scraper health dashboard — live stats, run history, error counts (auth required) |

### API Endpoints

| Endpoint | Description |
|---|---|
| `GET /api/map/geojson` | GeoJSON FeatureCollection filtered by bounding box + type + days |
| `GET /api/health` | Health check — returns 200 (ok) or 503 (db error) |
| `GET /admin/stats-partial` | HTMX-polled stats partial (refreshes every 30s) |

### Tech Stack

- **Framework:** FastAPI + Jinja2 templates
- **Interactivity:** HTMX (filter partials, admin polling, lazy match cards)
- **Map:** Leaflet.js with OpenStreetMap tiles
- **Styles:** Tailwind CSS (CDN)
- **Database:** SQLite (dev) / NeonDB PostgreSQL (production)

---

## Matching Engine

### Deduplication (min score: 0.35)

Identifies the same pet listed on multiple platforms. Signals:

| Signal | Score |
|---|---|
| Geo: < 0.1 miles apart | 0.25 |
| Same ZIP code | 0.20 |
| Exact breed match | 0.15 |
| Exact name match | 0.15 |
| Color match | 0.10 |
| Gender match | 0.08 |
| Date within same day | 0.12 |
| Microchip match | 0.50 (conclusive) |
| Cross-source bonus | 0.05 |

### Lost → Found Matching (min score: 0.30)

Identifies found pet reports that likely correspond to a specific lost pet. Hard filters: same `animal_type`, found date within 90 days after lost date (or up to 3 days before). Signals include geo distance, breed, color, gender, size, microchip, description overlap, and distinctive feature keywords.

**Confidence tiers:**
- `high` — score ≥ 0.65
- `medium` — score ≥ 0.40
- `low` — score ≥ 0.30

> Note: Geo signals are the strongest gate. Records without geocoded coordinates will produce more weak matches.

---

## Geocoding Strategy

Most sources provide street-level address text but no coordinates. **Exception: Pet FBI returns `geo_latitude`/`geo_longitude` directly.**

Geocoding cascade for all other sources:

1. **Cache lookup** — check `geocode_cache` table (keyed on normalized address string)
2. **Google Maps** — if `GEOCODE_PROVIDER=google` and API key is set
3. **Nominatim** — free OpenStreetMap geocoder (1 req/sec rate limit enforced)
4. **ZIP centroid fallback** — approximate coordinates from ZIP code (low confidence)

Cache writes use a SAVEPOINT so a duplicate key collision never rolls back surrounding pet record writes.

Geocoding cost:
- Google Maps: $5 per 1,000 requests (first 40,000/month free)
- Nominatim: Free, 1 req/sec, no commercial use without permission

---

## Polling Schedule

| Job | Interval | Notes |
|---|---|---|
| IndyLostPetAlert | every 15 min | Incremental — uses `after=` param |
| 24petconnect | every 30 min | Full re-scrape (no date filter available) |
| PawBoost | every 35 min | Playwright required |
| Pet FBI | every 40 min | Playwright required (WAF token capture) |
| Lost My Doggie | every 45 min | Playwright required |
| Matching pass | every 30 min | Dedup + lost→found on unmatched records |
| Staleness check | every 6 hours | Marks IndyLostPetAlert records inactive when removed |

---

## Deployment (Replit + NeonDB)

The app is configured for Replit with NeonDB as the production database.

1. Add your NeonDB connection string as a Replit secret named `neondb`
2. Add `ADMIN_USER` and `ADMIN_PASSWORD` secrets for the admin dashboard
3. Optionally add `RUN_SCHEDULER=true` to run scrapers inside the web process
4. Hit **Run** — the workflow installs dependencies, then starts uvicorn on port 5000

The `DATABASE_URL` environment variable is automatically set to `$neondb` by the workflow. The app normalizes `postgres://` URLs to `postgresql+asyncpg://` and handles NeonDB's `sslmode=require` automatically.

---

## Development Phases

### Phase 1 — Data Pipeline ✅ Complete
- [x] Analyze and document all source APIs (5 sources)
- [x] Build scraper for IndyLostPetAlert (WP REST API)
- [x] Build scraper for 24petconnect (HTML POST)
- [x] Build scraper for PawBoost (Playwright + Cloudflare stealth)
- [x] Build scraper for Pet FBI (Playwright + GraphQL + AWS WAF bypass)
- [x] Build scraper for Lost My Doggie (Playwright + Cloudflare stealth)
- [x] Unified PetRecord schema (Pydantic v2)
- [x] Source-specific normalizers (all 5 validated against live pages)

### Phase 2 — Storage & Matching ✅ Complete
- [x] Database schema (SQLAlchemy ORM, SQLite dev / PostgreSQL prod)
- [x] Upsert with deduplication by `source` + `source_id`
- [x] Cross-source matching engine (signal-weighted scoring)
- [x] Lost → Found reunification matching
- [x] Geocoding service (Google Maps + Nominatim + ZIP centroid cascade)
- [x] APScheduler polling jobs (5 scrapers + matching pass + staleness check)
- [x] Scraper state tracking (high-water mark for incremental polling)
- [x] Staleness checks (mark inactive listings)
- [x] Comprehensive test suite (195 tests — normalizers, matching, geocoding, DB, web routes)

### Phase 3 — Web Application ✅ Complete
- [x] FastAPI + Jinja2 web application
- [x] Interactive Leaflet map with bounding-box search and type filters
- [x] Filterable pet card grid (HTMX partials, URL-reflected filter state)
- [x] Pet detail pages with gallery, mini-map, and match cards
- [x] Lost ↔ Found match list with confidence scoring
- [x] Admin dashboard with live scraper health stats (HTTP Basic auth)
- [x] Mobile-responsive layout with hamburger nav
- [x] NeonDB (PostgreSQL) production deployment on Replit

### Phase 4 — Advanced Features
- [ ] User accounts + saved searches
- [ ] Email/push alerts for new matches
- [ ] **Visual similarity matching** — CLIP/MobileNet image embeddings as an additional matching signal (catches same-pet listings with mismatched text, e.g. "brown mutt" vs "tan terrier")
- [ ] PostGIS migration for `ST_DWithin()` geo queries at scale
- [ ] Image proxy endpoint (resize + cache thumbnails)
- [ ] Additional sources: Petfinder API, Petco Love Lost, Finding Rover

### Planned Sources (Phase 4)
| Source | Notes |
|---|---|
| [petfinder.com](https://www.petfinder.com/developers/) | Official public JSON API — adoptions primarily |
| [petcolove.org/lost](https://petcolove.org/lost) | AI facial recognition, Next.js frontend |
| [findingrover.com](https://www.findingrover.com) | Facial recognition for dogs |
| Local municipal shelters | Many run PetHarbor backend (same as 24petconnect) |
