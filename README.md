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
| `docs/api-analysis-petfbi.md` | Pet FBI — GraphQL API, AWS WAF protected, **provides lat/lon directly** |
| `docs/api-analysis-lostmydoggie.md` | Lost My Doggie — Cloudflare-protected, phone alert service |
| `docs/unified-data-schema.md` | Canonical pet record schema across all sources |

---

## Sources

| # | Source | Coverage | Access Method | Status |
|---|---|---|---|---|
| 1 | [24petconnect.com](https://24petconnect.com) | National (US + CA) | HTML scraping via POST | ✅ Scraper built & tested |
| 2 | [pawboost.com](https://www.pawboost.com) | National (US) | Playwright (Cloudflare) | ✅ Scraper built (needs Playwright install) |
| 3 | [indylostpetalert.com](https://www.indylostpetalert.com) | Indianapolis metro | WordPress REST API | ✅ Scraper built & tested |
| 4 | [petfbi.org](https://petfbi.org) | National (US) | GraphQL + Playwright (AWS WAF) | ✅ Scraper built (needs Playwright install) |
| 5 | [lostmydoggie.com](https://www.lostmydoggie.com) | National (US) | Playwright (Cloudflare) | ✅ Scraper built & tested |

### Planned Sources

| Source | Notes |
|---|---|
| [petfinder.com](https://www.petfinder.com/developers/) | Official public JSON API — adoptions primarily; developer page currently inaccessible |
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
| **Lat/lon provided** | No (geocode) | No (geocode) | No (geocode) | **✅ Yes** | No (geocode) |
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
│                  Cache results to avoid re-geocoding                │
│              PetFBI skipped — provides coordinates natively         │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                          Database                                   │
│          SQLite (dev) · PostgreSQL + PostGIS (production)           │
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
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       Application Layer  (built — see Phase 3)            │
│   · Geographic map view (Leaflet / MapboxGL)                        │
│   · Filters: type, species, color, size, date, radius               │
│   · Pet detail pages with source attribution                        │
│   · Lost ↔ Found match alerts (HTMX partials)                       │
│   · Admin dashboard + scraper health                                │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Getting Started

### Prerequisites

- Python 3.11+
- [optional] Playwright (for browser-based scrapers: PawBoost, PetFBI, LostMyDoggie)

### Install

```bash
# Clone and enter the project
cd "/home/alex/code/BUTTERGANG/k9-overwatch"

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install core dependencies
pip install -e ".[dev]"

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
# Edit .env to set your search coordinates, geocoding provider, etc.
```

Key `.env` settings:

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:///data/k9overwatch.db` | Database connection string |
| `SEARCH_LAT` | `39.7684` | Search center latitude (default: Indianapolis) |
| `SEARCH_LON` | `-86.1581` | Search center longitude |
| `SEARCH_RADIUS_MILES` | `25` | Search radius |
| `SEARCH_ZIP` | `46201` | ZIP code for sources that require it |
| `GEOCODE_PROVIDER` | `nominatim` | `nominatim` (free) or `google` |
| `GOOGLE_MAPS_API_KEY` | — | Required only when `GEOCODE_PROVIDER=google` |

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

### Run the Full Scheduler

```bash
python -m k9overwatch.scheduler.runner
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
│   ├── connection.py         # Async engine + session factory
│   └── repository.py         # PetRepository — upsert, queries, geo search, match storage
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
└── scheduler/
    ├── jobs.py               # run_scraper(), run_matching_pass(), check_stale_records()
    └── runner.py             # ScraperScheduler — APScheduler interval jobs
scripts/
└── scrape_one.py             # CLI test utility for any individual scraper
docs/
├── api-analysis-*.md         # Per-source API analysis documentation
└── unified-data-schema.md    # Canonical schema + PostgreSQL DDL
```

---

## Matching Engine

The matching engine runs in two modes:

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

> Note: Geo signals are the strongest gate. Records without geocoded coordinates will produce more weak matches (expected until geocoding runs).

---

## Geocoding Strategy

Most sources provide street-level address text but no coordinates. **Exception: Pet FBI returns `geo_latitude`/`geo_longitude` directly.**

Geocoding cascade for all other sources:

1. **Cache lookup** — check `geocode_cache` table (keyed on normalized address string)
2. **Google Maps** — if `GEOCODE_PROVIDER=google` and API key is set
3. **Nominatim** — free OpenStreetMap geocoder (1 req/sec rate limit enforced)
4. **ZIP centroid fallback** — approximate coordinates from ZIP code (low confidence)

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
| Staleness check | every 6 hours | Verifies IndyLostPetAlert records still active |
| Re-match pass | daily 04:00 | Idempotent re-scan of recent records (last 120d) so matches improve as more data arrives (e.g. geocoding fills coordinates) |

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
- [x] Database schema (SQLAlchemy ORM, SQLite dev / PostgreSQL+PostGIS prod)
- [x] Upsert with deduplication by `source` + `source_id`
- [x] Cross-source matching engine (signal-weighted scoring)
- [x] Lost → Found reunification matching
- [x] Geocoding service (Google Maps + Nominatim cascade + ZIP centroid fallback)
- [x] APScheduler polling jobs (7 jobs: 5 scrapers + matching pass + staleness check)
- [x] Scraper state tracking (high-water mark for incremental polling)
- [x] Staleness checks (mark inactive listings)
- [x] LostMyDoggie HTML structure confirmed (`.box_icon` cards, full-res image URLs)

### Phase 2b — Finalization (Mostly complete)
- [x] Write test suite (`tests/`) — pytest + pytest-asyncio, normalizers + matching + geocoding
- [x] Populate `utils/` — `logging_config.py`, `http_client.py`, `text.py`
- [ ] Run batch geocoding on existing DB records (`scripts/geocode_batch.py`)
- [x] End-to-end integration test: run full scheduler cycle, verify DB state

### Phase 3 — Application ✅ Built
- [x] REST API layer (FastAPI) — routers: map, pets, matches, admin
- [x] Map UI (Leaflet, cluster markers, HTMX filter partials)
- [x] Filter panel (type, species, color, size, date range, radius)
- [x] Pet detail pages with source attribution
- [x] Match alert display (HTMX partials on pet detail)
- [x] Admin dashboard (scraper health, match stats)
- [ ] Image proxy endpoint (resize + cache for large sources like IndyLostPetAlert)

### Phase 4 — Advanced Features
- [ ] User accounts + saved searches
- [ ] Email/push alerts for new matches
- [ ] **Visual similarity matching** — generate CLIP/MobileNet embedding vectors per image,
      store in DB, use cosine similarity as an additional matching signal to catch
      same-dog listings with mismatched text descriptions (e.g. "brown mutt" vs "tan terrier")
- [ ] Adoption listings integration
- [ ] Add additional sources: Petfinder (official API), Petco Love Lost (facial recognition), Finding Rover

### Planned Sources (Phase 4)
| Source | Notes |
|---|---|
| [petfinder.com](https://www.petfinder.com/developers/) | Official public JSON API — adoptions primarily |
| [petcolove.org/lost](https://petcolove.org/lost) | AI facial recognition, Next.js frontend |
| [findingrover.com](https://www.findingrover.com) | Facial recognition for dogs |
| Local municipal shelters | Many run PetHarbor backend (same as 24petconnect) |
