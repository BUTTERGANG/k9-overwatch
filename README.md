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
|| `docs/unified-data-schema.md` | Canonical pet record schema across all sources |
|| `docs/visual-similarity.md` | Optional provider-backed visual matching seam and configuration |

---

## Sources

| # | Source | Coverage | Access Method | Status |
|---|---|---|---|---|
| 1 | [24petconnect.com](https://24petconnect.com) | National (US + CA) | HTML scraping via POST | ✅ Built & tested |
| 2 | [pawboost.com](https://www.pawboost.com) | National (US) | Playwright (Cloudflare) | ✅ Built & tested (2026-08: repaired after site redesigns) |
| 3 | [indylostpetalert.com](https://www.indylostpetalert.com) | Indianapolis metro | WordPress REST API | ✅ Built & tested |
| 4 | [petfbi.org](https://petfbi.org) | National (US) | GraphQL + Playwright (AWS WAF) | ✅ Built (needs Playwright) |
| 5 | [lostmydoggie.com](https://www.lostmydoggie.com) | National (US) | Playwright (Cloudflare) | ✅ Built & tested (2026-08: repaired after site redesigns) |

### Planned Sources

| Source | Notes |
|---|---|
| ~~[petfinder.com](https://www.petfinder.com/)~~ | **RETIRED 2026-08-22** — provider decommissioned the public API on 2025-12-02. Replacement candidates evaluated in [docs/api-alternatives-research.md](docs/api-alternatives-research.md) |
| [rescuegroups.org](https://rescuegroups.org/services/adoptable-pet-data-api/) | **PLANNED** — free public JSON:API v5, adoptable animals nationwide; free API key requested. Strongest Petfinder replacement (see api-alternatives-research.md) |
| [findingrover.com](https://www.findingrover.com) | Facial recognition for dogs |
| [petcolove.org/lost](https://petcolove.org/lost) | AI-powered facial recognition, Next.js frontend |
| Local municipal shelters | Many run on PetHarbor (same backend as 24petconnect) |

> **Investigated, not integrable:** [Helping Lost Pets](https://www.helpinglostpets.com)
> and [FidoAlert](https://fidoalert.com) were analyzed and ruled out as integration
> targets — see `docs/api-analysis-helpinglostpets.md` for the findings.

---

## Location accuracy

Pin precision is deliberately tiered and, for owner uploads, consent-gated:

- **EXIF GPS consent flow** — when an owner uploads photos, we ask before reading
  GPS coordinates from EXIF metadata. Regardless of the answer, GPS data is
  stripped from all stored photo bytes, so no location metadata ever persists
  in `/uploads`.
- **Geocode confidence tiers** — every record carries a geocode confidence:
  exact address, neighborhood (street-level centroid), or ZIP-code centroid.
  Map pin badges ("Exact location" / "Neighborhood" / "ZIP code area") reflect
  the tier with color coding.
- **Display fuzzing** — ZIP-centroid pins are fuzzed slightly on display so
  multiple pets in the same ZIP don't stack into one indistinguishable marker,
  and so a viewer can't infer a precise home location from a low-precision pin.

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
│   Runs inside the web process when RUN_SCHEDULER=true; a singleton  │
│   lock prevents duplicate scheduler ownership per database/host     │
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
│   · User accounts — owner reports, contact gating, opt-in alerts    │
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

To run the test suite:

```bash
source .venv/bin/activate
pytest
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
| `ADMIN_PASSWORD` | `changeme` (development only) | HTTP Basic password — **must be explicitly set to a non-default value in production** |
| `RUN_SCHEDULER` | `false` | Set `true` to run scrapers inside the web process |
| `LOG_FORMAT` | `pretty` | `pretty` (dev) or `json` (production) |
| `SESSION_SECRET` | dev default (development only) | Signs user session cookies — **must be explicitly set to a non-default value in production** |
| `SMTP_HOST` | — | SMTP server for match emails. If unset, emails are logged (no-op) so dev is never blocked |
| `SMTP_PORT` | `587` | SMTP port |
| `SMTP_USER` | — | SMTP username |
| `SMTP_PASSWORD` | — | SMTP password |
| `SMTP_FROM` | `k9-overwatch@localhost` | From address for match emails |
| `APP_BASE_URL` | `http://localhost:8000` | Public base URL used for unsubscribe / detail links in emails |

### Map operations

The map uses Leaflet with OpenStreetMap light tiles and CARTO dark tiles. These public tile endpoints are suitable for development and low-volume use with attribution; production deployments should select a provider whose terms and rate limits match expected traffic, or operate a permitted/self-hosted tile service. Configure any provider changes in `map.html`/`map.js` and preserve required attribution.

The map API returns at most 500 features per viewport. Responses include `total`, `returned`, and `truncated`; users are prompted to zoom in when the viewport contains more records than the payload cap.

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

The scheduler takes a singleton lock: PostgreSQL uses an advisory lock, while
SQLite/local deployments use a non-blocking host file lock. A second scheduler
process exits without running jobs.

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
│   ├── jobs.py               # run_scraper(), run_matching_pass(), check_stale_records(),
│   │                         # expire_stale_listings(), regeocode_pending_records(),
│   │                         # flush_digest_notifications(), flush_saved_search_notifications()
│   └── runner.py             # ScraperScheduler — APScheduler interval jobs
├── web/
│   ├── main.py               # FastAPI app + lifespan (init DB, warm pool, optional scheduler)
│   ├── dependencies.py       # get_db() — async session injection
│   ├── templates_config.py   # Jinja2 environment setup
│   ├── rate_limit.py         # In-process per-IP fixed-window limiter (auth + report routes)
│   ├── routers/
│   │   ├── onboarding.py     # / (landing), /how-it-works
│   │   ├── accounts.py       # /login, /register, /account, /forgot-password, /reset-password, /logout
│   │   ├── reports.py        # /report — owner-submitted lost/found/sighting with photo uploads
│   │   ├── images.py         # /img — cached, size-capped image proxy
│   │   ├── pets.py           # /pets, /pets/{id}, /pets/results (HTMX partial)
│   │   ├── map.py            # /map, /api/map/geojson, /api/map/buckets
│   │   ├── matches.py        # /matches (lost→found pairs, dedup pairs)
│   │   └── admin.py          # /admin, /admin/stats-partial (HTTP Basic auth required)
│   ├── templates/
│   │   ├── base.html         # Frosted-glass nav, mobile drawer menu, page transitions, Tailwind config
│   │   ├── macros.html       # Shared Jinja2 macros (status_badge, species_icon, loading_spinner, etc.)
│   │   ├── landing.html      # / — marketing landing page
│   │   ├── how_it_works.html # /how-it-works — onboarding guide
│   │   ├── map.html          # Leaflet map + responsive filter drawer (FAB toggle on mobile)
│   │   ├── pets/             # list.html, _results.html (HTMX partial), card.html, detail.html
│   │   ├── matches/          # list.html — scored match pairs
│   │   ├── accounts/         # login, register, account, forgot/reset-password, report.html, message.html
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
├── test_accounts_reports.py  # Accounts, owner reports, contact requests
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
| `/` | Landing page — marketing overview, calls to action |
| `/how-it-works` | Onboarding guide |
| `/map` | Interactive Leaflet map — pins colored by record type, amber badge dot on pins with matches, bounding-box "Search this area" button, filter sidebar |
| `/pets` | Filterable pet card grid — species, type, days; HTMX partial updates; URL-reflected filter state |
| `/pets/{id}` | Pet detail page — full info, photo gallery, mini-map, matched pets |
| `/matches` | Lost ↔ Found / dedup match list — confidence-scored pairs, confirm/dismiss review buttons |
| `/login`, `/register`, `/logout` | Signed-cookie account auth (rate-limited) |
| `/forgot-password`, `/reset-password` | Single-use, expiring password-reset flow (rate-limited) |
| `/account` | Notification preferences, saved searches, submitted reports |
| `/report` | Owner-submitted lost/found/sighting with photo upload (login required, rate-limited) |
| `/admin` | Scraper health dashboard — live stats, run history, error counts (auth required) |

### API Endpoints

| Endpoint | Description |
|---|---|
| `GET /api/map/geojson` | GeoJSON FeatureCollection filtered by bounding box + type + days; includes `match_count` per feature |
| `GET /api/map/buckets` | Aggregate counts by type/status for the map filter sidebar |
| `GET /img` | Cached, size-capped (8MB) image proxy for source-hosted photos |
| `GET /api/health` | Health check — returns 200 (ok) or 503 (db error) |
| `GET /admin/stats-partial` | HTMX-polled stats partial (refreshes every 30s) |
| `POST /api/matches/{id}/review?confirmed=true\|false` | Mark a match as human-reviewed; sets `confirmed` flag |

### Tech Stack

- **Framework:** FastAPI + Jinja2 templates
- **Interactivity:** HTMX (filter partials, admin polling, lazy match cards, inline match review)
- **Map:** Leaflet.js with OpenStreetMap tiles
- **Styles:** Tailwind CSS v3 (CDN) with custom brand/accent/status color palette; full dark mode (`darkMode: 'class'`) with localStorage + `prefers-color-scheme` persistence
- **Design:** Frosted-glass navbar, dark mode toggle, page transitions, mobile-first responsive drawers, accessible focus states
- **Database:** SQLite (dev) / NeonDB PostgreSQL (production)

---

## Matching Engine

### Deduplication (min score: 0.35)

Identifies the same pet listed on multiple platforms. Signals:

| Signal | Score |
|---|---|
| Geo: < 0.5 miles apart | 0.25 |
| Geo: 0.5–2 miles apart | 0.15 |
| Geo: 2–5 miles apart | 0.08 |
| Same ZIP code | 0.08 |
| Microchip match | 0.50 (conclusive) |
| Contact phone match | 0.35 |
| Contact phone partial (last 7 digits) | 0.15 |
| Exact breed match | 0.15 |
| Exact name match | 0.15 |
| Primary color match | 0.10 |
| Secondary color match | 0.06 |
| Gender match | 0.08 |
| Size match | 0.05 |
| Date within same day | 0.12 |
| Date within 1 day | 0.10 |
| Date within 3 days | 0.06 |
| Date within 7 days | 0.03 |
| Cross-source bonus | 0.05 |

> Description overlap is intentionally excluded from dedup scoring — identical descriptions are expected for the same post on multiple platforms and would inflate scores artificially.

### Lost → Found Matching (min score: 0.30)

Identifies found pet reports that likely correspond to a specific lost pet. Hard filters: same `animal_type`, found date within **180 days** after lost date (or up to 3 days before). Candidate query covers a ±180-day window to support long-running searches.

Signals:

| Signal | Score |
|---|---|
| Geo: < 0.5 miles apart | 0.25 |
| Geo: 0.5–2 miles apart | 0.15 |
| Geo: 2–5 miles apart | 0.08 |
| Same ZIP code | 0.08 |
| Microchip match | 0.50 (conclusive) |
| Contact phone match | 0.35 |
| Contact phone partial | 0.15 |
| Exact breed match | 0.15 |
| Exact name match | 0.15 |
| Primary color match | 0.15 |
| Secondary color match | up to 0.09 |
| Gender match | 0.12 |
| Size match | 0.08 |
| Found 0–3 days after lost | 0.10 |
| Found 4–14 days after lost | 0.05 |
| Found before reported (≤3 days) | 0.05 |
| Distinctive feature keyword overlap | 0.08 |
| Description overlap | 0.05–0.10 |

**Confidence tiers:**
- `high` — score ≥ 0.65
- `medium` — score ≥ 0.40
- `low` — score ≥ 0.30

> Geo signals are the strongest gate for records with coordinates. Records without geocoded coordinates fall back to ZIP-based matching.

### Score Updates

Match scores are not frozen at creation. When a scraper re-encounters a record (e.g. after geocoding fills in missing coordinates), the matching pass will update any existing **unreviewed** match if the new score is higher. Human-reviewed matches are never overwritten.

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
| Matching pass | every 30 min | Dedup + lost→found, both directions, on newly ingested records |
| Re-geocode backstop | every 20 min | Retries active records with address text but no coordinates (mainly user reports, geocoded once at submit time) — see [Geocoding Strategy](#geocoding-strategy) |
| Staleness check | every 6 hours | Verifies IndyLostPetAlert records still active |
| Age-based expiry | every 24 hours | Source-agnostic fallback: deactivates any active listing older than 120 days, regardless of source |
| Match digest | daily 19:00 UTC | Coalesced per-day email of new matches, respecting per-user notification preferences |
| Saved-search notifications | every 5 min | Drains the durable notification queue with bounded retry |
| Re-match pass | daily 04:00 | Idempotent re-scan of recent records (last 120d) so matches improve as more data arrives (e.g. geocoding fills coordinates) |

All scrapers also trigger an immediate targeted matching pass on their newly ingested records (`run_matching=True`), so new pets are matched against the existing pool without waiting for the batch job. The re-geocode backstop does the same for any record it successfully fills in coordinates for.

> `ScraperScheduler` (`scheduler/runner.py`) runs each scraper on the per-source interval shown in the table above, with staggered startup runs and one active run per source. Matching runs every 30 minutes.

---

## Deployment (Replit + NeonDB)

### Deployment status

Replit + NeonDB configuration exists as a development/deployment sketch, but
live deployment and production validation are **deferred**. Do not treat the
following as completed operational steps: provisioning secrets, running the
web process, configuring a scheduler owner, applying PostgreSQL migrations,
or validating external SMTP/browser providers. The application does normalize
`postgres://` URLs to `postgresql+asyncpg://` and handles NeonDB's
`sslmode=require` when configured, but those deployment paths remain
unverified here.

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
- [x] Source-specific normalizers (fixture-tested; live browser-source validation is deferred)

### Phase 2 — Storage & Matching ✅ Complete
- [x] Database schema (SQLAlchemy ORM, SQLite dev / PostgreSQL prod)
- [x] Upsert with deduplication by `source` + `source_id`
- [x] Cross-source matching engine (signal-weighted scoring)
- [x] Lost → Found reunification matching
- [x] Geocoding service (Google Maps + Nominatim + ZIP centroid cascade)
- [x] APScheduler polling jobs (5 scrapers + matching pass + staleness check)
- [x] Scraper state tracking (high-water mark for incremental polling)
- [x] Staleness checks (mark inactive listings)
- [x] Comprehensive test suite (314 passed, 1 skipped in the current baseline)

### Phase 3 — Web Application ✅ Complete
- [x] FastAPI + Jinja2 web application
- [x] Interactive Leaflet map with bounding-box search, clustering, and type filters
- [x] Filterable pet card grid (HTMX partials, URL-reflected filter state)
- [x] Pet detail pages with gallery, mini-map, and match cards
- [x] Lost ↔ Found match list with confidence scoring
- [x] Admin dashboard with live scraper health stats (HTTP Basic auth)
- [x] Mobile-responsive layout with hamburger nav
- [ ] NeonDB/Replit production deployment and migration validation (deferred)
- [x] UI modernization — frosted-glass navbar, page fade-in transitions, mobile filter drawers
- [x] Reusable Jinja2 macros (status_badge, species_icon, loading_spinner)
- [x] Accessibility improvements — ARIA attributes, keyboard-navigable gallery, screen reader support
- [x] Map popup redesign — branded badges, styled action buttons, auto-dismiss error banners
- [x] **Dark mode** — full site dark theme with toggle button, localStorage + `prefers-color-scheme` persistence, no flash on load
- [x] Image proxy endpoint (`/img?url=`) — serves remote listing/owner photos through our own
      origin so browsers never block them; validates scheme and resolved IP (SSRF-safe) and
      caches results on disk.

### Phase 4 — Matching & Review Improvements ✅ Complete
- [x] Contact phone signal added to both dedup and lost→found matching (0.35 / 0.15)
- [x] Secondary color signal added to deduplication
- [x] Description overlap removed from dedup (inflated cross-platform scores artificially)
- [x] ZIP weight corrected (0.20 → 0.08 — ZIP is coarser than geo distance)
- [x] `MAX_DAYS_AFTER_LOST` tuned to 60 days (most reunifications happen within 2 weeks; the
      candidate query window stays wider, at +90/-14 days, so the matcher's own hard filter
      is the precise gate)
- [x] Match scores update in place when re-scored higher (unreviewed matches only)
- [x] All scrapers now trigger immediate matching on new records (`run_matching=True`)
- [x] `match_count` computed dynamically from `pet_matches` (no denormalized column) and wired
      on map GeoJSON + pet detail — pins with matches show an amber badge dot
- [x] Match review UI — Confirm / Dismiss buttons on match cards (HTMX, no page reload)
- [x] `POST /api/matches/{id}/review` endpoint for human review workflow
- [x] Bidirectional lost↔found matching (`find_reverse_matches`) — a newly ingested found
      report is also checked against existing lost records, not just the reverse
- [x] Idempotent re-match pass (daily) — rescans recent records so scores improve as more
      data arrives (e.g. geocoding fills in coordinates), without disturbing human review
- [x] Recency buckets (`week`/`fortnight`/`month`/`older`) — map recency bar + per-pin aging

### Phase 5 — Accounts & Owner Reports ✅ Built
- [x] **User accounts** — register / log in / log out (signed-cookie sessions,
      scrypt password hashing, no external dependency). Email verification is
      required before login; single-use, expiring password-reset tokens are
      supported.
- [x] **Owner-submitted reports** — `/report` lets a logged-in person post a
      lost/found/sighting with bounded, extension- and image-signature-checked
      photo uploads (stored in `data/uploads/`) and contact info.
- [x] **Contact mechanism** — contact info is revealed only to logged-in users
      on the pet detail page.
- [x] **Saved searches** — authenticated users can create, update, and delete
      bounded search criteria; newly ingested matches are queued for delivery.
- [x] **Durable notification delivery** — saved-search notifications are stored
      in a database queue with atomic claims and bounded retry scheduling; SMTP
      remains configuration-gated and failures do not block ingestion.
- [x] **CSRF protection** — signed, user-bound tokens are embedded in forms and
      checked by middleware for cookie-authenticated state-changing requests.
- [x] **Scheduler singleton ownership** — PostgreSQL advisory locks or a
      non-blocking host file lock prevent duplicate scheduler processes.
- [x] **Rate limiting on sensitive routes** — in-process per-IP fixed-window
      limiter on login/register/password-reset/report (`web/rate_limit.py`).

### Phase 6 — Deferred / Not Yet Validated
- [ ] Real visual embeddings (CLIP/MobileNet generation, storage, and matching)
- [ ] PostGIS migration and `ST_DWithin()` geo queries at scale
- [ ] Live browser-source validation and browser-scraper staleness checks
- [ ] Broader API rate limiting (map/search/read endpoints beyond auth & report)
      and a shared (not in-process) store if this ever runs multi-worker
- [ ] Audit logging
- [ ] Database migrations and production deployment/operations validation
- [ ] Adoption listings integration
- [ ] Additional sources: RescueGroups.org v5 (free key requested — replaces retired Petfinder), Petco Love Lost (facial recognition), Finding Rover

### New features (2026-08-19)

- [x] **Geocode confidence on map pins** — pin popups now show "Exact location", "Neighborhood", or "ZIP code area" badges based on the source's geocode precision. Color-coded (green/yellow/red) with a location icon.
- [x] **Reunited status path** — pet owners can mark their lost/found/sighting reports as reunited via a "🎉 Reunited" button on the pet detail page. This deactivates the listing, closes active matches, and deactivates the matched counterpart if one exists.
- [x] **Reactivation path** — if a user report was auto-deactivated (stale flagging or admin action), the owner can reactivate it with a "↻ Reactivate" button to put it back on the map.
- [x] **Auto-stale flagging with notification window** — expired listings now get a two-phase treatment: user-submitted reports receive a `stale_notified_at` timestamp on the first stale pass, and are only deactivated on the second pass (24h later). Non-user reports are deactivated immediately as before. The `stale_notified_at` column is tracked per-row.
- [x] **Source health dashboard** — admin dashboard now shows per-source stats: active/total pet counts, geocode fill rate (% with lat/lon), and a record-type breakdown (lost/found/sighting/adoptable). Replaces the previous single-number scraper health view.

### Planned Sources (Phase 4)
| Source | Notes |
|---|---|
| [rescuegroups.org](https://rescuegroups.org/services/adoptable-pet-data-api/) | Free public JSON:API v5 — planned; replaces Petfinder (retired: API decommissioned by provider 2025-12-02) |
| [petcolove.org/lost](https://petcolove.org/lost) | AI facial recognition, Next.js frontend |
| [findingrover.com](https://www.findingrover.com) | Facial recognition for dogs |
| Local municipal shelters | Many run PetHarbor backend (same as 24petconnect) |
