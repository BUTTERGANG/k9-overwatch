# K9-Overwatch Application Architecture

## Overview

K9-Overwatch is a lost & found pet aggregation platform that consolidates pet listings from multiple external sources into a unified database. It provides an interactive map interface, intelligent matching algorithms to reunite lost pets with found reports, and an admin dashboard for monitoring system health.

**Stack:** Python 3.11+ / FastAPI / SQLAlchemy (async) / Jinja2 + HTMX / Tailwind CSS / Leaflet.js

---

## High-Level Architecture

```
                        +-----------------------+
                        |    External Sources    |
                        |  (5 pet listing sites) |
                        +-----------+-----------+
                                    |
                     +--------------v--------------+
                     |      Scraper Layer           |
                     |  HTTP Scrapers (aiohttp)     |
                     |  Browser Scrapers (Playwright)|
                     +--------------+--------------+
                                    |
                     +--------------v--------------+
                     |     Normalizer Layer          |
                     |  Source-specific parsers       |
                     |  Output: canonical PetRecord   |
                     +--------------+--------------+
                                    |
                     +--------------v--------------+
                     |     Geocoding Layer           |
                     |  Google Maps / Nominatim      |
                     |  ZIP centroid fallback         |
                     |  DB-backed cache               |
                     +--------------+--------------+
                                    |
                     +--------------v--------------+
                     |     Database Layer            |
                     |  Repository pattern            |
                     |  Upsert with dedup             |
                     |  SQLite (dev) / PostgreSQL     |
                     +--------------+--------------+
                                    |
                     +--------------v--------------+
                     |     Matching Engine           |
                     |  Deduplicator (cross-source)  |
                     |  Lost<->Found matcher          |
                     |  Signal-based scoring          |
                     +--------------+--------------+
                                    |
                     +--------------v--------------+
                     |       Web Layer              |
                     |  FastAPI + Jinja2 + HTMX     |
                     |  Leaflet map / GeoJSON API    |
                     |  Admin dashboard               |
                     +--------------+--------------+
                                    |
                     +--------------v--------------+
                     |      Scheduler               |
                     |  APScheduler (in-process)     |
                     |  Scraper intervals             |
                     |  Matching passes               |
                     |  Staleness checks              |
                     +------------------------------+
```

---

## Directory Structure

```
src/k9overwatch/
├── db/                    # Database connection, ORM models, repository
│   ├── connection.py      # Async engine, session factory, init_db()
│   ├── models.py          # PetRow, PetMatch, ScraperState, GeocodeCache
│   └── repository.py      # PetRepository (all data access)
├── models/                # Pydantic data schemas
│   ├── enums.py           # RecordType, AnimalType, Gender, Size, etc.
│   └── pet_record.py      # Canonical PetRecord model
├── scrapers/              # Data acquisition
│   ├── base.py            # BaseScraper abstract class
│   ├── http/              # aiohttp-based scrapers
│   └── browser/           # Playwright-based scrapers
├── normalizers/           # Source-specific HTML/JSON -> PetRecord
├── matching/              # Pet matching algorithms
│   ├── breed_normalizer.py
│   ├── signals.py         # MatchResult + signal scoring
│   ├── deduplicator.py    # Cross-source dedup
│   └── lost_found_matcher.py
├── geocoding/             # Address -> coordinates
│   ├── geocoder.py        # GeocodingService with cascade
│   └── providers/         # Google, Nominatim
├── scheduler/             # Background job scheduling
│   ├── runner.py          # APScheduler configuration
│   └── jobs.py            # Job functions
├── web/                   # FastAPI web application
│   ├── main.py            # App entry point, lifespan
│   ├── dependencies.py    # Dependency injection
│   ├── routers/           # API route handlers
│   ├── schemas/           # Response models
│   ├── static/            # CSS, JS, images
│   └── templates/         # Jinja2 HTML templates
└── utils/                 # Shared utilities
    ├── alerts.py          # Webhook notifications
    ├── http_client.py     # Shared HTTP session
    ├── text.py            # Text utilities
    └── logging_config.py  # structlog setup
```

---

## Data Flow Pipeline

### Record Ingestion (every 15-45 minutes per source)

```
1. Scraper fetches raw data from external source
2. Normalizer converts source-specific format -> PetRecord
3. GeocodingService resolves address -> lat/lon coordinates
4. PetRepository.upsert() stores or updates the record
5. Matching engine evaluates new record against candidates
6. PetMatch records saved for human review
```

### Web Request Flow

```
Browser Request
      |
  FastAPI Router -> Jinja2 Template (HTML pages)
      |                    or
  FastAPI Router -> JSON Response (API endpoints)
      |
  PetRepository queries DB
      |
  Response returned
```

### HTMX Dynamic Updates

The frontend uses HTMX for partial page updates without full reloads:
- Filter changes on `/pets` trigger `/pets/results` (returns HTML fragment)
- Admin stats auto-refresh via `/admin/stats-partial`
- Map data loaded via `/api/map/geojson` (JavaScript fetch)

---

## Key Design Decisions

1. **Repository Pattern** - All database access goes through `PetRepository`, providing a single point of control for queries, caching, and optimization.

2. **Canonical Data Model** - All scrapers normalize to a single `PetRecord` pydantic model, decoupling source-specific formats from the rest of the system.

3. **Geocoding Cascade** - Provider -> cache -> ZIP centroid fallback ensures every record gets at least approximate coordinates.

4. **Signal-Based Matching** - Matching uses weighted signals rather than hard rules, allowing flexible tuning and transparent scoring.

5. **In-Process Scheduler** - APScheduler runs inside the FastAPI process (toggleable via `RUN_SCHEDULER` env var), simplifying deployment while allowing separation if needed.

6. **Async Throughout** - SQLAlchemy async, aiohttp, Playwright async - the entire pipeline is non-blocking.

---

## Technology Choices

| Layer | Technology | Why |
|-------|-----------|-----|
| Web Framework | FastAPI | Async-native, automatic OpenAPI docs, dependency injection |
| ORM | SQLAlchemy 2.0 (async) | Mature, supports SQLite + PostgreSQL |
| Templates | Jinja2 + HTMX | Server-rendered with dynamic updates, no JS framework needed |
| CSS | Tailwind CSS | Utility-first, rapid prototyping |
| Maps | Leaflet.js | Lightweight, open-source, mobile-friendly |
| Scraping | aiohttp + Playwright | HTTP for simple APIs, browser for JS-rendered/protected sites |
| Matching | rapidfuzz | High-performance fuzzy string matching |
| Scheduling | APScheduler | Lightweight, async-compatible, cron + interval jobs |
| Geocoding | Google Maps / Nominatim | Google for accuracy, Nominatim as free fallback |

---

## Phase 5 Architecture Goals (Performance & Design)

As the platform scales to support more concurrent users and a larger geographic area, the architecture must transition from its initial proof-of-concept design to a more robust, production-ready state.

### Performance Upgrades

1. **Database-Native Geolocation (PostGIS)**
   - **Current:** Python-side Haversine distance calculations in `repository.py` require loading extra rows into application memory.
   - **Goal:** Migrate NeonDB PostgreSQL to use the `PostGIS` extension. Replace Python bounding-box math with the SQL-native `ST_DWithin` function. This offloads complex spatial queries entirely to the database engine for significantly faster map filtering.

2. **GeoJSON Endpoint Optimization**
   - **Current:** Generating the map pins (`/api/map/geojson`) requires a complex real-time `UNION ALL` subquery on the `pet_matches` table to assign match counts.
   - **Goal:** Denormalize data by adding a `match_count` integer column to the `PetRow` table. Use SQLAlchemy hooks or database triggers to update this column organically. This flattens map retrieval to a single O(1) query.

3. **In-Memory Caching (Redis/FastAPI-Cache)**
   - **Current:** Every HTMX request and Map render queries the database fresh.
   - **Goal:** Since scraper data only alters the database state every 15-45 minutes, wrap read-heavy endpoints in a cache layer. Invalidate the cache *only* when a background scraper completes a run containing new records (`records_new > 0`).

### Design & UI Architecture Upgrades

1. **Compiled Asset Pipeline**
   - **Current:** CSS is executed in-browser via the Tailwind CDN (`<script src="https://cdn.tailwindcss.com"></script>`), causing parse delays and Flash-of-Unstyled-Content (FOUC).
   - **Goal:** Introduce a Node.js build step (`npx tailwindcss -i input.css -o static/css/output.css --minify`) to generate a static CSS bundle for production.

2. **Synchronized Map Theming** ✅ *Completed*
   - **Implementation:** `map.js` uses `makeTileLayer(dark)` to select between OSM (light) and CartoDB Dark Matter (dark). A `k9:darkModeChange` custom event dispatched from `base.html`'s dark-mode toggle triggers an instant tile layer swap on the live map without a page reload. CSP `img-src` updated to allow `*.basemaps.cartocdn.com`.

3. **Skeleton Loading (Perceived Performance)** ✅ *Completed*
   - **Implementation:** `pets/list.html` listens for `htmx:beforeRequest` on the filter form. Before the database query returns, `#results-container` is replaced with 8 shimmer skeleton cards (matching real card height with `animate-pulse`). The real grid arrives via HTMX swap as normal. No layout shift occurs.

4. **Toast Notification System** ✅ *Completed*
   - **Implementation:** `base.html` exposes `window.showToast(message, type)` and a fixed `#toast-container` (top-right, `z-[9999]`). Supports `success`, `error`, `warning`, `info` types with matching icons and colors. Toasts animate in/out and auto-dismiss after 3.5s. Currently wired to match review actions; available globally for future user-facing interactions (saved searches, share actions, etc.).
