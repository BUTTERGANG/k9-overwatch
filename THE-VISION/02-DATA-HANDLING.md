# Data Handling Methods

## Overview

K9-Overwatch aggregates pet listing data from 5 external sources, normalizes it into a canonical format, geocodes locations, stores it in a relational database, and runs matching algorithms to identify duplicates and potential lost/found reunifications.

---

## 1. Data Acquisition (Scrapers)

### Source Inventory

| Source | Type | Method | Schedule | Incremental | Coverage |
|--------|------|--------|----------|-------------|----------|
| IndyLostPetAlert | HTTP | WordPress REST API | 15 min | Yes (date filter) | Indianapolis metro |
| 24PetConnect | HTTP | HTML POST endpoint | 30 min | No (full re-fetch) | National (US + CA) |
| PawBoost | Browser | Cloudflare-protected | 35 min | Yes | National (US) |
| PetFBI | Browser | GraphQL + AWS WAF | 40 min | Yes | National (US) |
| LostMyDoggie | Browser | Cloudflare-protected | 45 min | Yes | National (US) |

### Scraper Architecture

**Base Classes:**
- `BaseScraper` - Abstract class defining the scraper interface
  - `scrape(after: Optional[datetime])` -> AsyncIterator[PetRecord]
  - `check_active(source_id)` -> bool (verify listing still exists)
  - Properties: `SOURCE_NAME`, `SUPPORTS_INCREMENTAL`

- `BrowserBaseScraper(BaseScraper)` - Adds Playwright browser lifecycle
  - Manages headless Chromium with stealth mode (bypasses Cloudflare)
  - Custom viewport (1280x800), realistic User-Agent
  - Supports custom Chromium executable path

### HTTP Scrapers
- Use `aiohttp` for async HTTP requests
- Rate limited via `HTTP_RATE_LIMIT_SECONDS` (default 1.5s between requests)
- Retry logic via `tenacity` library

### Browser Scrapers
- Use Playwright for JavaScript-rendered pages
- `playwright-stealth` package for Cloudflare bypass
- Single browser instance per scraper, one page per scrape cycle
- `PLAYWRIGHT_HEADLESS=true` by default

### Incremental vs Full Scraping
- **Incremental:** Pass `after` datetime to only fetch new/updated records since last scrape. Uses high-water mark stored in `ScraperState` table.
- **Full:** Fetch all records, then run staleness sweep to mark unseen records as inactive.

---

## 2. Data Normalization

Each source has a dedicated normalizer that converts raw source data into the canonical `PetRecord` pydantic model.

### Canonical PetRecord Fields

```python
class PetRecord(BaseModel):
    source: str              # e.g., "indylostpetalert"
    source_id: str           # unique ID within source
    source_url: str          # link back to original listing
    record_type: RecordType  # lost, found, sighting, adoptable
    animal_type: AnimalType  # dog, cat, bird, rabbit, other

    # Animal details
    name: Optional[str]
    breed: Optional[str]
    breed_secondary: Optional[str]
    color_primary: Optional[str]
    color_secondary: Optional[str]
    gender: Optional[Gender]
    age: Optional[str]
    size: Optional[Size]
    size_lbs: Optional[float]
    microchipped: Optional[bool]
    microchip_number: Optional[str]
    distinctive_features: Optional[str]

    # Location
    location_text: Optional[str]
    city: Optional[str]
    state: Optional[str]
    zip: Optional[str]
    lat: Optional[float]
    lon: Optional[float]

    # Timing
    date_event: Optional[date]
    date_posted: Optional[datetime]

    # Content
    description: Optional[str]
    photos: list[str] = []
    thumbnail_url: Optional[str]

    # Contact
    contact_phone: Optional[str]
    contact_email: Optional[str]
    contact_name: Optional[str]
```

### Key Methods
- `unique_key()` -> `(source, source_id)` - Used for upsert dedup
- `needs_geocoding()` -> bool - Has address text but no coordinates
- `geocoding_address()` -> str - Best available address for geocoder
- `to_match_fingerprint()` -> dict - Only matching-relevant fields

### Normalizer Responsibilities
1. Map source-specific field names to canonical fields
2. Parse record type (lost/found/sighting) from source categories
3. Extract structured data (breed, color, size) from free-text descriptions
4. Parse dates into standard format
5. Extract photo URLs
6. Clean and normalize text fields

---

## 3. Geocoding

### GeocodingService

Converts address text to latitude/longitude coordinates using a cascade strategy:

```
1. Check GeocodeCache table (DB-backed cache)
   |-- HIT: return cached coords (increment hit_count)
   |-- MISS: continue
   |
2. Try configured provider (Google Maps or Nominatim)
   |-- SUCCESS: cache result, return coords
   |-- FAIL: continue
   |
3. ZIP centroid fallback (built-in zipcodes package)
   |-- Returns approximate center of ZIP code area
   |-- Confidence: LOW
```

### Providers
- **Google Maps** - High accuracy, requires API key + billing
- **Nominatim** (OpenStreetMap) - Free, no auth, 1 req/sec rate limit

### Cache
- **GeocodeCache table** stores: address_key, lat, lon, source, confidence, hit_count
- Address key is normalized (lowercase, punctuation stripped)
- Process-level LRU cache for ZIP centroids

### Confidence Levels
- **HIGH** - Street-level geocode from Google/Nominatim
- **MEDIUM** - Partial match or interpolated address
- **LOW** - ZIP centroid or approximate

---

## 4. Database Storage

### Upsert Strategy

`PetRepository.upsert(record)` handles record storage:

1. Check if record exists by `(source, source_id)` unique key
2. **New record:** INSERT with all fields
3. **Existing record:** UPDATE only changed fields, preserve `scraped_at`
4. Returns `(PetRow, created: bool)` tuple

### Staleness Management

Records can become stale when removed from source sites:

- **Staleness sweep** (after full scrapes): Compare fetched source_ids against DB, mark unseen records as `active=False`
- **Periodic check** (every 6 hours): For each source, get records not checked in 48+ hours, verify they still exist via `scraper.check_active()`, mark inactive if gone
- **`last_checked_at`** timestamp tracks when each record was last verified

### Scraper State Tracking

`ScraperState` table tracks operational health per source:
- Last run time and success status
- Records fetched and new count
- High-water mark (for incremental polling)
- Error message and consecutive error count
- Triggers webhook alert at 3+ consecutive errors

---

## 5. Matching Engine

### Architecture

Two matching algorithms run against new records:

#### A. Deduplicator
Identifies the same pet listed on multiple platforms.
- **Candidates:** Same animal_type, within search radius, within date window
- **Min score:** 0.35
- **Key signals:** geo proximity, breed match, color match, phone match, cross-source bonus

#### B. Lost/Found Matcher
Matches lost pet reports against found/sighting records.
- **Candidates:** Same animal_type, found date within window (-3 to +60 days of lost date)
- **Min score:** 0.30
- **Key signals:** geo proximity, breed match, color match, date proximity, microchip match

### Signal-Based Scoring

Each comparison evaluates a set of weighted signals:

| Signal | Weight | Description |
|--------|--------|-------------|
| `microchip_match` | 0.50 | Conclusive - same microchip number |
| `contact_phone_match` | 0.35 | Same phone number (strong for dedup) |
| `geo_very_close` | 0.25 | < 1 mile apart |
| `breed_exact` | 0.15 | Exact normalized breed match |
| `name_exact` | 0.15 | Same pet name |
| `color_primary_match` | 0.10-0.15 | Primary color matches |
| `gender_match` | 0.12 | Same gender |
| `date_same_day` | 0.12 | Events on same day |
| `desc_high_similarity` | 0.10 | Description text overlap > 60% |
| `zip_match` | 0.08 | Same ZIP code |
| `size_match` | 0.08 | Same size category |
| `geo_close` | 0.15 | 1-5 miles apart |
| `geo_nearby` | 0.08 | 5-15 miles apart |

### Confidence Levels

**Dedup matches:**
- HIGH: score >= 0.80
- MEDIUM: score >= 0.60
- LOW: score < 0.60

**Lost/Found matches:**
- HIGH: score >= 0.65
- MEDIUM: score >= 0.40
- LOW: score < 0.40

### Breed Normalization

The `breed_normalizer` maps ~50 canonical breeds with aliases:
- Handles compound breeds ("Lab / Pit" -> sorted canonical pair)
- Fuzzy matching via `rapidfuzz` (88% similarity cutoff)
- LRU cache (2048 entries) for performance
- Discards non-specific terms ("mixed", "unknown", "other")

### Match Storage

`PetMatch` records store:
- Both pet IDs, match type (dedup/lost_found)
- Score (0.0-1.0) and confidence level
- `signals_fired` JSON dict showing which signals contributed
- `reviewed` / `confirmed` flags for human review workflow

---

## 6. Alerting

### Webhook Alerts (`utils/alerts.py`)

Sends notifications to Discord or Slack when:
- A scraper has 3+ consecutive errors
- Triggered automatically during `run_scraper()` job

Configured via `ALERT_WEBHOOK_URL` environment variable.
