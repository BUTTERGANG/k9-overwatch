# K9-Overwatch — Web Application Architecture Plan

**Date:** 2026-03-25
**Status:** Handoff document for Phase 3 implementation
**Audience:** Architect / implementing AI agent

---

## 1. Project Context

K9-Overwatch is a lost/found pet aggregation platform for the Indianapolis metro area. It scrapes 5 pet reporting services, normalizes records into a unified schema, geocodes addresses, and runs a matching engine to identify duplicate listings and potential lost→found reunification candidates.

**The data backend is fully built and tested.** This document covers the web application layer (Phase 3) that exposes the data to users.

### What exists today

```
src/k9overwatch/
├── models/           # PetRecord (Pydantic), enums
├── db/               # SQLAlchemy ORM (PetRow, PetMatch), repository, connection
├── scrapers/         # 5 scrapers (IndyLostPetAlert, 24petconnect, PawBoost, PetFBI, LostMyDoggie)
├── normalizers/      # One per source → PetRecord
├── geocoding/        # GeocodingService, Nominatim + Google providers, ZIP centroids
├── matching/         # Deduplicator, LostFoundMatcher, signal functions, breed normalizer
├── scheduler/        # jobs.py (scrape→geocode→upsert→match pipeline), runner.py
└── utils/            # logging_config.py, http_client.py, text.py

tests/                # 178 tests, all passing
scripts/
├── scrape_one.py     # Manual single-source test runner
└── geocode_batch.py  # Batch geocode DB records
data/
└── k9overwatch.db    # SQLite (dev only — PostgreSQL in production/Replit)
```

### Key data structures

**`pets` table** — normalized pet listings from all sources
- `id` UUID, `source`, `source_id`, `record_type` (lost/found/sighting/adoptable)
- `animal_type`, `name`, `breed`, `color_primary`, `color_secondary`, `gender`, `age`, `size`
- `lat`, `lon`, `geocode_source`, `geocode_confidence`
- `location_text`, `city`, `county`, `state`, `zip`
- `date_event`, `date_posted`, `active` (boolean)
- `photos` (JSON array of URLs), `thumbnail_url`
- `description`, `contact_phone`, `contact_email`, `contact_name`
- `shelter_name`, `shelter_code`

**`pet_matches` table** — dedup + lost→found match pairs
- `pet_a_id`, `pet_b_id`, `match_type` (dedup/lost_found)
- `score` (0.0–1.0), `confidence` (low/medium/high)
- `signals_fired` (JSON: `{"breed_exact": 0.15, "zip_match": 0.20, ...}`)
- `reviewed` (boolean), `confirmed` (boolean) — for human review workflow

**`scraper_state` table** — per-source scraper health
- `source`, `last_run_at`, `last_run_success`, `records_fetched`, `records_new`, `error_message`

**`geocode_cache` table** — cached geocoding results

---

## 2. Deployment Target: Replit

The application will be hosted on Replit. This shapes several architecture decisions.

### Replit constraints

| Concern | Constraint | Decision |
|---|---|---|
| **Database** | SQLite unreliable on free tier (container sleep) | Use Replit's managed PostgreSQL from day one |
| **Browser scrapers** | Playwright + Chromium is CPU/RAM heavy | Scrapers run as separate Replit Scheduled Deployments, not in the web process |
| **Python version** | Replit supports up to Python 3.13 via Nix | Pin `python312` or `python313` in `replit.nix` |
| **Port** | Replit expects `0.0.0.0:8080` | Configure uvicorn accordingly |
| **Secrets** | Managed via Replit Secrets panel | All env vars: `DATABASE_URL`, `GOOGLE_MAPS_API_KEY`, `SEARCH_LAT`, `SEARCH_LON`, etc. |
| **Always On** | Web app needs `$20/month` Always On deployment | Single web Repl with Always On |
| **Scrapers** | Use Replit Scheduled Deployments | Each scraper = a separate scheduled job (cron, isolated process) |

### Replit deployment structure

```
Repl 1 (Always On — web app):
  run: uvicorn k9overwatch.web.main:app --host 0.0.0.0 --port 8080

Repl 2 / Scheduled jobs (or same Repl with Scheduled Deployments):
  - scrape-indy:      python scripts/scrape_one.py indy --save        (every 4h)
  - scrape-24pet:     python scripts/scrape_one.py 24petconnect --save (every 6h)
  - scrape-pawboost:  python scripts/scrape_one.py pawboost --save     (every 6h)
  - scrape-petfbi:    python scripts/scrape_one.py petfbi --save       (every 12h)
  - scrape-lmd:       python scripts/scrape_one.py lostmydoggie --save (every 12h)
  - geocode-batch:    python scripts/geocode_batch.py --limit 200      (nightly)
```

### `replit.nix` requirements

```nix
{ pkgs }:
{
  deps = [
    pkgs.python312
    pkgs.chromium          # for Playwright scrapers
    pkgs.nodejs_20         # Playwright dependency
    pkgs.postgresql_15     # client tools (psql)
  ];
  env = {
    PLAYWRIGHT_BROWSERS_PATH = "/nix/store";
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD = "1";
  };
}
```

Playwright must be configured to use the Nix Chromium binary path rather than downloading its own. Set `executable_path` in `BrowserBaseScraper` via an env var `CHROMIUM_PATH`.

### Database migration: SQLite → PostgreSQL

The existing SQLAlchemy models require zero changes. Only `DATABASE_URL` changes:

```
# Dev (local)
DATABASE_URL=sqlite+aiosqlite:///data/k9overwatch.db

# Production (Replit managed PostgreSQL)
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/k9overwatch
```

The Haversine approximation in `PetRepository.find_within_radius()` can be replaced with `ST_DWithin` once PostGIS is available. This is a future optimization — the Python-side Haversine works correctly today.

---

## 3. Technology Stack for the Web App

| Layer | Choice | Rationale |
|---|---|---|
| **API framework** | FastAPI | Async-native (matches existing async codebase), auto OpenAPI docs, clean path operations |
| **Template engine** | Jinja2 (built into FastAPI) | Server-rendered HTML, no separate build step, works well on Replit single-process model |
| **Frontend interactivity** | HTMX | Enables dynamic filtering/search without a JS framework; responses are HTML fragments, not JSON |
| **Map** | Leaflet.js + OpenStreetMap tiles | Free, no API key required, works fully client-side |
| **CSS** | Tailwind CSS (CDN) | Utility-first, no build step required (use CDN play.tailwindcss.com in dev, stable CDN in prod) |
| **Icons** | Heroicons (inline SVG) | No external CDN dependency |

### Why not React/Vue?

- Replit single-process model favors minimal build complexity
- HTMX + Jinja2 delivers all required interactivity (search, filter, infinite scroll) with less overhead
- Server-rendered pages load faster on initial request (important for map pins on mobile)
- Easier to add later if needed — FastAPI's JSON endpoints can serve both HTML and a future SPA

---

## 4. Application Structure

The web app lives in a new top-level package `src/k9overwatch/web/`:

```
src/k9overwatch/web/
├── __init__.py
├── main.py              # FastAPI app factory, router registration, startup events
├── dependencies.py      # Shared FastAPI dependencies (DB session, config)
├── routers/
│   ├── __init__.py
│   ├── pets.py          # /pets — list, search, detail
│   ├── map.py           # /map — map view page + GeoJSON endpoint
│   ├── matches.py       # /matches — dedup + lost→found matches
│   └── admin.py         # /admin — scraper status, stats dashboard
├── schemas/
│   ├── __init__.py
│   └── pet.py           # Pydantic response schemas (PetSummary, PetDetail, GeoJSONFeature)
├── templates/
│   ├── base.html        # Layout: nav, footer, head
│   ├── map.html         # Full-screen map view
│   ├── pets/
│   │   ├── list.html    # Search results list (HTMX target)
│   │   ├── card.html    # Single pet card partial
│   │   └── detail.html  # Full pet detail page
│   ├── matches/
│   │   └── list.html    # Match pairs with score breakdown
│   └── admin/
│       └── dashboard.html
└── static/
    ├── css/
    │   └── app.css      # Minimal custom styles (Tailwind handles most)
    └── js/
        └── map.js       # Leaflet map init + GeoJSON layer loading
```

---

## 5. Pages and Routes

### 5.1 Map View — `/map` (primary landing page)

The main interface. A full-screen Leaflet map with a slide-out filter panel.

**User interactions:**
- Pan/zoom the map
- Filter by: species (dog/cat/other), record type (lost/found/sighting/adoptable), date range, radius from a point
- Click a pin → opens a popup with thumbnail + name + date + "View details" link
- "Search this area" button re-queries based on current map bounds

**Implementation:**
- `GET /map` → renders `map.html` (Jinja2, full page)
- `GET /api/map/geojson` → returns GeoJSON FeatureCollection of all active records within bounds
  - Query params: `sw_lat`, `sw_lng`, `ne_lat`, `ne_lng`, `record_type[]`, `animal_type[]`, `days`
  - Response capped at ~500 features for performance
  - Each feature's `properties` includes: `id`, `record_type`, `animal_type`, `name`, `breed`, `color_primary`, `date_event`, `thumbnail_url`, `source`, `match_count`

**Pin color coding:**
- Red = lost
- Green = found
- Blue = sighting
- Orange = adoptable
- Purple outline = has a match

### 5.2 Search / List View — `/pets`

Filterable list view for users who prefer browsing over a map.

**URL pattern:** `/pets?record_type=lost&animal_type=dog&zip=46205&radius=10&days=30&page=1`

**Filters (sidebar):**
- Record type (lost / found / sighting / adoptable) — checkbox
- Species (dog / cat / bird / rabbit / other) — checkbox
- Gender — radio
- Date range (last 7 / 30 / 90 days, or custom)
- ZIP code + radius (miles)
- Breed (text search)
- Color (text search)
- Source (IndyLostPetAlert / PawBoost / etc.) — checkbox

**HTMX behavior:** filter changes trigger `hx-get="/pets/results" hx-target="#results-container"` — only the results list re-renders, not the whole page.

**Routes:**
- `GET /pets` → full page with filters + initial results
- `GET /pets/results` → HTMX partial — just the results list (used for filter updates + pagination)
- `GET /pets/{id}` → pet detail page

### 5.3 Pet Detail — `/pets/{id}`

Full record page for a single pet.

**Sections:**
1. **Header** — record type badge, species, name, date, source badge
2. **Photo gallery** — thumbnail grid if multiple photos, full-size on click
3. **Details** — breed, color, gender, age, size, microchip, distinctive features
4. **Location** — embedded Leaflet mini-map showing the pin + surrounding area; location text
5. **Contact** — phone, email (masked behind "Show contact" click for spam protection), source link
6. **Possible matches** — cards showing dedup/lost→found candidates with score breakdown
7. **Source** — "Originally posted on [source] on [date]" + link

**Routes:**
- `GET /pets/{id}` → full detail page
- `GET /pets/{id}/matches` → HTMX partial for the matches section (lazy-loaded)

### 5.4 Matches View — `/matches`

Focused view for reviewing potential lost→found reunifications and duplicate detections.

**Two tabs:**
- **Reunifications** (lost_found type) — sorted by score desc, filtered to high+medium confidence
- **Duplicates** (dedup type) — same pet posted on multiple sources

**Each match card shows:**
- Both pets side-by-side (photo, name, breed, color, date, source)
- Match score + confidence badge
- Signals that fired (e.g., "Same ZIP • Same breed • 2 days apart • Same gender")
- "View both" button

**Routes:**
- `GET /matches` → full matches page
- `GET /matches?type=lost_found&confidence=high,medium&page=1` — filtered

### 5.5 Admin Dashboard — `/admin`

Internal status page (no auth required initially — add basic HTTP auth later if needed).

**Panels:**
- **Scraper status** — last run time, success/fail, records fetched/new for each source
- **Database stats** — total records by source, by type, by animal; records missing geocoding; match counts
- **Recent errors** — last N errors per source
- **Actions** — "Trigger geocode batch" button (fires `geocode_batch.py` as a subprocess)

**Routes:**
- `GET /admin` → dashboard page
- `GET /admin/stats` → JSON stats (for HTMX auto-refresh every 30s)

---

## 6. API Endpoints

FastAPI exposes both HTML pages (for browsers) and JSON endpoints (for the map JS and future use).

```
GET  /                          → redirect to /map

# Pages (HTML)
GET  /map                       → map view page
GET  /pets                      → search/list page
GET  /pets/results              → HTMX partial (list results)
GET  /pets/{id}                 → pet detail page
GET  /pets/{id}/matches         → HTMX partial (match cards)
GET  /matches                   → matches page
GET  /admin                     → admin dashboard

# JSON API
GET  /api/map/geojson           → GeoJSON FeatureCollection for map pins
GET  /api/pets                  → paginated JSON pet list
GET  /api/pets/{id}             → single pet JSON
GET  /api/matches               → paginated JSON match list
GET  /api/admin/stats           → scraper + DB stats JSON
GET  /api/health                → {"status": "ok", "db": "ok"}
```

---

## 7. Key Implementation Details

### Database session dependency

```python
# web/dependencies.py
from contextlib import asynccontextmanager
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from k9overwatch.db.connection import get_session_factory

async def get_db() -> AsyncSession:
    factory = get_session_factory()
    async with factory() as session:
        yield session
```

### Startup / lifespan

```python
# web/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from k9overwatch.db.connection import init_db
from k9overwatch.utils.logging_config import configure_logging

@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    await init_db()           # create tables if not exist
    yield

app = FastAPI(title="K9-Overwatch", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="src/k9overwatch/web/static"), name="static")
templates = Jinja2Templates(directory="src/k9overwatch/web/templates")
```

### GeoJSON endpoint (core map query)

```python
# web/routers/map.py
@router.get("/api/map/geojson")
async def get_map_geojson(
    sw_lat: float, sw_lng: float, ne_lat: float, ne_lng: float,
    record_type: list[str] = Query(default=["lost", "found"]),
    animal_type: list[str] = Query(default=[]),
    days: int = Query(default=90),
    db: AsyncSession = Depends(get_db),
):
    # Bounding box query against pets table
    # Returns GeoJSON FeatureCollection with properties for popup rendering
    ...
```

### HTMX search results

```python
# web/routers/pets.py
@router.get("/pets/results")
async def pet_results_partial(
    request: Request,
    record_type: list[str] = Query(default=["lost"]),
    animal_type: list[str] = Query(default=[]),
    zip: str = Query(default=""),
    radius: int = Query(default=25),
    days: int = Query(default=30),
    page: int = Query(default=1),
    db: AsyncSession = Depends(get_db),
):
    pets, total = await search_pets(db, ...)
    return templates.TemplateResponse(
        "pets/list.html",
        {"request": request, "pets": pets, "total": total, "page": page}
    )
```

### Image handling

Pet images are hotlinked directly from source CDNs. No proxy is needed for most sources. Exception: IndyLostPetAlert photos are ~2.7 MB smartphone photos — add a `?w=400` resize parameter or a simple proxy endpoint if bandwidth is a concern.

```html
<!-- In templates: always use thumbnail_url for list views, photos[] for detail -->
<img src="{{ pet.thumbnail_url or '/static/img/no-photo.png' }}"
     loading="lazy" alt="{{ pet.name or 'Unknown pet' }}">
```

### Matched record display

The `pet_matches` table stores both directions. When displaying a pet's matches, query for rows where `pet_a_id = id OR pet_b_id = id`, then load the counterpart record for display.

```python
async def get_pet_with_matches(db, pet_id: str):
    pet = await db.get(PetRow, pet_id)
    matches = await repo.get_matches_for_pet(pet_id)
    # For each match, load the "other" pet
    match_pairs = []
    for m in matches:
        other_id = m.pet_b_id if m.pet_a_id == pet_id else m.pet_a_id
        other = await db.get(PetRow, other_id)
        match_pairs.append({"match": m, "other": other})
    return pet, match_pairs
```

---

## 8. Pydantic Response Schemas

Define these in `web/schemas/pet.py` to decouple the API response from the ORM model:

```python
class PetSummary(BaseModel):
    id: str
    source: str
    record_type: str
    animal_type: Optional[str]
    name: Optional[str]
    breed: Optional[str]
    color_primary: Optional[str]
    gender: Optional[str]
    date_event: Optional[date]
    location_text: Optional[str]
    city: Optional[str]
    state: Optional[str]
    zip: Optional[str]
    lat: Optional[float]
    lon: Optional[float]
    thumbnail_url: Optional[str]
    active: bool
    match_count: int = 0        # injected by query

class PetDetail(PetSummary):
    breed_secondary: Optional[str]
    color_secondary: Optional[str]
    age: Optional[str]
    size: Optional[str]
    distinctive_features: Optional[str]
    description: Optional[str]
    contact_phone: Optional[str]   # masked in template
    contact_email: Optional[str]   # masked in template
    contact_name: Optional[str]
    photos: list[str]
    source_url: Optional[str]
    date_posted: Optional[datetime]
    shelter_name: Optional[str]

class GeoJSONFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: dict              # {"type": "Point", "coordinates": [lon, lat]}
    properties: PetSummary

class GeoJSONCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[GeoJSONFeature]
    total: int
```

---

## 9. Leaflet Map Implementation

The map page uses Leaflet.js loaded from CDN. JavaScript lives in `static/js/map.js`.

```javascript
// static/js/map.js — core logic outline

const map = L.map('map').setView([39.7684, -86.1581], 11);  // Indianapolis center

L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '© OpenStreetMap contributors'
}).addTo(map);

// Pin icons by record_type
const icons = {
    lost:      L.divIcon({ className: 'pin-lost',      html: '🔴' }),
    found:     L.divIcon({ className: 'pin-found',     html: '🟢' }),
    sighting:  L.divIcon({ className: 'pin-sighting',  html: '🔵' }),
    adoptable: L.divIcon({ className: 'pin-adoptable', html: '🟠' }),
};

let layerGroup = L.layerGroup().addTo(map);

async function loadPins() {
    const bounds = map.getBounds();
    const params = new URLSearchParams({
        sw_lat: bounds.getSouth(), sw_lng: bounds.getWest(),
        ne_lat: bounds.getNorth(), ne_lng: bounds.getEast(),
        // ... active filters from panel
    });
    const resp = await fetch(`/api/map/geojson?${params}`);
    const data = await resp.json();

    layerGroup.clearLayers();
    L.geoJSON(data, {
        pointToLayer: (feature, latlng) => {
            const p = feature.properties;
            return L.marker(latlng, { icon: icons[p.record_type] || icons.lost });
        },
        onEachFeature: (feature, layer) => {
            const p = feature.properties;
            layer.bindPopup(`
                <div class="popup">
                    ${p.thumbnail_url ? `<img src="${p.thumbnail_url}" class="popup-thumb">` : ''}
                    <strong>${p.name || 'Unknown'}</strong><br>
                    ${p.breed || ''} ${p.animal_type}<br>
                    ${p.record_type.toUpperCase()} · ${p.date_event}<br>
                    <a href="/pets/${p.id}">View details →</a>
                </div>
            `);
        }
    }).addTo(layerGroup);
}

map.on('moveend', debounce(loadPins, 400));
loadPins();  // initial load
```

---

## 10. Phased Build Order

Build in this order to maintain a working state at each step:

### Step 1 — App skeleton + health endpoint
- `web/main.py` with lifespan, static files, Jinja2
- `GET /api/health` returning `{"status": "ok"}`
- `GET /` redirecting to `/map`
- `base.html` template with nav
- Confirm it runs on Replit at `0.0.0.0:8080`

### Step 2 — Map page
- `GET /map` renders `map.html`
- `GET /api/map/geojson` with bounding box + filter query
- Leaflet + `map.js` rendering pins
- Basic filter panel (record type, species, days)

### Step 3 — Pet list + search
- `GET /pets` full page with filter sidebar
- `GET /pets/results` HTMX partial
- `pets/card.html` partial template

### Step 4 — Pet detail
- `GET /pets/{id}` full detail page
- `GET /pets/{id}/matches` HTMX partial for match cards
- Mini-map on detail page (Leaflet, single pin)

### Step 5 — Matches view
- `GET /matches` with lost→found tab as default
- Match card template (two pets side-by-side)

### Step 6 — Admin dashboard
- `GET /admin` with scraper status table
- `GET /api/admin/stats` JSON
- HTMX auto-refresh every 30s

### Step 7 — Production hardening
- Replit Secrets for all env vars
- PostgreSQL `DATABASE_URL` (migrate from SQLite)
- `replit.nix` + `.replit` files committed
- CHROMIUM_PATH env var for Playwright scrapers
- Error pages (404, 500)
- Basic rate limiting on search endpoints

---

## 11. Non-Goals for Phase 3

The following are **explicitly out of scope** for this phase:

- User accounts / authentication / saved searches
- Email or push notifications to pet owners
- Admin login (dashboard is internal, IP-restricted if needed)
- Visual similarity matching (CLIP embeddings) — Phase 4
- Additional data sources beyond the current 5 — Phase 4
- Mobile app — not planned

---

## 12. Environment Variables Reference

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Yes | Full SQLAlchemy URL. SQLite for dev, PostgreSQL for prod |
| `SEARCH_LAT` | Yes | Center latitude for scrapers (default: 39.7684) |
| `SEARCH_LON` | Yes | Center longitude for scrapers (default: -86.1581) |
| `SEARCH_RADIUS_MILES` | No | Search radius in miles (default: 25) |
| `SEARCH_ZIP` | No | ZIP code for LostMyDoggie searches (default: 46201) |
| `GEOCODE_PROVIDER` | No | `nominatim` or `google` (default: nominatim) |
| `GOOGLE_MAPS_API_KEY` | No | Required only if `GEOCODE_PROVIDER=google` |
| `CHROMIUM_PATH` | No | Path to Chromium binary for Playwright on Replit |
| `LOG_LEVEL` | No | `DEBUG`, `INFO`, `WARNING` (default: INFO) |
| `LOG_FORMAT` | No | `json` or `text` (default: text) |

---

## 13. Files the Architect Needs to Create

Summary of new files to be written:

```
src/k9overwatch/web/
├── __init__.py
├── main.py
├── dependencies.py
├── routers/
│   ├── __init__.py
│   ├── pets.py
│   ├── map.py
│   ├── matches.py
│   └── admin.py
├── schemas/
│   ├── __init__.py
│   └── pet.py
├── templates/
│   ├── base.html
│   ├── map.html
│   ├── pets/list.html
│   ├── pets/card.html
│   ├── pets/detail.html
│   ├── matches/list.html
│   └── admin/dashboard.html
└── static/
    ├── css/app.css
    └── js/map.js

.replit                    # run command + deployment config
replit.nix                 # Nix deps: python312, chromium, nodejs_20
```

### Existing files to modify

| File | Change needed |
|---|---|
| `pyproject.toml` | Add `fastapi`, `uvicorn[standard]`, `jinja2`, `python-multipart` to dependencies |
| `src/k9overwatch/scrapers/browser/base_browser.py` | Read `CHROMIUM_PATH` env var for `executable_path` on Replit |
| `src/k9overwatch/db/connection.py` | Ensure `DATABASE_URL` supports both SQLite and PostgreSQL (already does via env var) |

---

## 14. Dependencies to Add

```toml
# In pyproject.toml [project] dependencies:
"fastapi>=0.111",
"uvicorn[standard]>=0.29",
"jinja2>=3.1",
"python-multipart>=0.0.9",   # for form data parsing
"asyncpg>=0.29",              # PostgreSQL async driver (prod)
```

---

*This document is the complete handoff spec. The implementing agent should read the existing codebase starting with `src/k9overwatch/db/repository.py` and `src/k9overwatch/db/models.py` to understand the data layer before writing any web code.*
