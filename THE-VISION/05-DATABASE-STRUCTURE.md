# Database Structure

## Overview

K9-Overwatch uses SQLAlchemy 2.0 async ORM with support for SQLite (development) and PostgreSQL (production). The database layer follows a repository pattern with all access through `PetRepository`.

---

## Database Configuration

```env
# Development (SQLite)
DATABASE_URL=sqlite+aiosqlite:///data/k9overwatch.db

# Production (PostgreSQL)
DATABASE_URL=postgresql+asyncpg://user:password@host:5432/k9overwatch
```

The connection layer (`db/connection.py`) auto-detects the driver and handles async driver configuration, including SQLite's `check_same_thread=False` and PostgreSQL's `asyncpg` connect_args translation.

---

## Table Definitions

### 1. `pet_rows` (Primary Data Table)

The main table storing all pet listings from all sources.

```sql
CREATE TABLE pet_rows (
    -- Identity
    id              TEXT PRIMARY KEY,           -- UUID string
    source          TEXT NOT NULL,              -- e.g., "pawboost", "petfbi"
    source_id       TEXT NOT NULL,              -- unique ID within source
    source_url      TEXT,                       -- link to original listing
    record_type     TEXT NOT NULL,              -- "lost", "found", "sighting", "adoptable"

    -- Animal Details
    animal_type     TEXT NOT NULL,              -- "dog", "cat", "bird", "rabbit", "other"
    name            TEXT,
    breed           TEXT,
    breed_secondary TEXT,
    breed_normalized TEXT,                      -- canonical breed after normalization
    color_primary   TEXT,
    color_secondary TEXT,
    gender          TEXT,                       -- "male", "female", "unknown"
    age             TEXT,
    size            TEXT,                       -- "xsmall" to "xxlarge"
    size_lbs        REAL,
    microchipped    BOOLEAN,
    microchip_number TEXT,
    distinctive_features TEXT,

    -- Status & Timing
    status          TEXT,
    date_event      DATE,                      -- when lost/found/seen
    time_event      TEXT,
    days_since_event INTEGER,
    date_posted     DATETIME,                  -- when posted to source
    date_updated    DATETIME,
    active          BOOLEAN DEFAULT TRUE,

    -- Location
    location_text   TEXT,                      -- raw address string
    neighborhood    TEXT,
    city            TEXT,
    county          TEXT,
    state           TEXT,                      -- 2-letter code
    zip             TEXT,                      -- up to 10 chars
    country         TEXT DEFAULT 'US',
    lat             REAL,
    lon             REAL,
    geocode_source  TEXT,                      -- "google", "nominatim", "zip_centroid"
    geocode_confidence TEXT,                   -- "high", "medium", "low"

    -- Shelter
    shelter_name    TEXT,
    shelter_code    TEXT,
    shelter_id      TEXT,

    -- Contact
    contact_phone   TEXT,
    contact_email   TEXT,
    contact_name    TEXT,
    contact_method  TEXT,

    -- Content
    description     TEXT,
    owner_message   TEXT,
    photos          JSON,                      -- list of photo URLs
    thumbnail_url   TEXT,
    facebook_post_url TEXT,
    nextdoor_url    TEXT,
    alert_number    TEXT,

    -- Audit
    scraped_at      DATETIME,                  -- when first scraped
    last_checked_at DATETIME,                  -- last staleness check
    raw             JSON,                      -- raw source payload

    UNIQUE (source, source_id)
);
```

**Indexes:**
```sql
CREATE INDEX ix_pet_rows_source ON pet_rows(source);
CREATE INDEX ix_pet_rows_record_type ON pet_rows(record_type);
CREATE INDEX ix_pet_rows_animal_type ON pet_rows(animal_type);
CREATE INDEX ix_pet_rows_breed_normalized ON pet_rows(breed_normalized);
CREATE INDEX ix_pet_rows_state ON pet_rows(state);
CREATE INDEX ix_pet_rows_zip ON pet_rows(zip);
CREATE INDEX ix_pet_rows_date_event ON pet_rows(date_event);
CREATE INDEX ix_pet_rows_date_posted ON pet_rows(date_posted);
CREATE INDEX ix_pet_rows_active ON pet_rows(active);
CREATE INDEX ix_pet_rows_active_date ON pet_rows(active, date_event);
CREATE INDEX ix_pet_rows_active_type_date ON pet_rows(active, animal_type, date_event);
```

### 2. `pet_matches` (Match Results)

Stores matching results between pet records (both dedup and lost/found).

```sql
CREATE TABLE pet_matches (
    id              TEXT PRIMARY KEY,           -- UUID
    pet_a_id        TEXT NOT NULL,              -- references pet_rows.id
    pet_b_id        TEXT NOT NULL,              -- references pet_rows.id
    match_type      TEXT NOT NULL,              -- "dedup" or "lost_found"
    score           REAL NOT NULL,              -- 0.0 to 1.0
    confidence      TEXT NOT NULL,              -- "low", "medium", "high"
    signals_fired   JSON,                       -- {"signal_name": weight, ...}
    created_at      DATETIME NOT NULL,
    reviewed        BOOLEAN DEFAULT FALSE,
    confirmed       BOOLEAN,                    -- NULL until reviewed

    UNIQUE (pet_a_id, pet_b_id, match_type)
);
```

**Indexes:**
```sql
CREATE INDEX ix_pet_matches_pet_a ON pet_matches(pet_a_id, match_type);
CREATE INDEX ix_pet_matches_pet_b ON pet_matches(pet_b_id, match_type);
```

### 3. `scraper_state` (Operational Health)

Tracks the health and progress of each scraper source.

```sql
CREATE TABLE scraper_state (
    source              TEXT PRIMARY KEY,        -- e.g., "pawboost"
    last_run_at         DATETIME,
    last_run_success    BOOLEAN,
    records_fetched     INTEGER DEFAULT 0,
    records_new         INTEGER DEFAULT 0,
    last_record_at      DATETIME,               -- high-water mark for incremental polling
    error_message       TEXT,
    consecutive_errors  INTEGER DEFAULT 0        -- triggers alert at 3+
);
```

### 4. `geocode_cache` (Geocoding Results Cache)

Caches geocoding results to avoid redundant API calls.

```sql
CREATE TABLE geocode_cache (
    address_key         TEXT PRIMARY KEY,        -- normalized address string
    lat                 REAL NOT NULL,
    lon                 REAL NOT NULL,
    geocode_source      TEXT,                    -- "google", "nominatim"
    geocode_confidence  TEXT,                    -- "high", "medium", "low"
    cached_at           DATETIME,
    hit_count           INTEGER DEFAULT 0        -- tracks cache effectiveness
);
```

---

## Entity Relationship Diagram

```
+------------------+       +------------------+
|    pet_rows      |       |   pet_matches    |
+------------------+       +------------------+
| id (PK)          |<------| pet_a_id (FK)    |
| source           |<------| pet_b_id (FK)    |
| source_id        |       | match_type       |
| record_type      |       | score            |
| animal_type      |       | confidence       |
| breed, color,    |       | signals_fired    |
| location, etc.   |       | reviewed         |
+------------------+       | confirmed        |
                           +------------------+

+------------------+       +------------------+
|  scraper_state   |       |  geocode_cache   |
+------------------+       +------------------+
| source (PK)      |       | address_key (PK) |
| last_run_at      |       | lat, lon         |
| records_fetched  |       | geocode_source   |
| consecutive_errors|       | hit_count        |
+------------------+       +------------------+
```

---

## Repository Pattern

All database access goes through `PetRepository` (`db/repository.py`).

### Key Operations

**Record Management:**
```python
upsert(record: PetRecord) -> (PetRow, created: bool)
get_by_key(source, source_id) -> PetRow | None
mark_inactive(source, source_id) -> None
mark_inactive_bulk(source, seen_ids: set) -> int
```

**Spatial Queries:**
```python
find_within_radius(lat, lon, miles, **filters) -> list[PetRow]
# Uses Haversine formula with bounding box pre-filter
# Filters: record_type, animal_type, active_only, days
```

**Match Candidate Discovery:**
```python
find_match_candidates(record, search_radius_miles=15,
                      date_window_days=60,
                      max_record_age_days=365) -> list[PetRow]
# Pre-filters for matching engine
# Handles both event dates and scrape dates
# 1-year hard cap prevents stale matches
```

**Match Operations:**
```python
save_match(match: MatchResult) -> bool          # True if new
get_matches_for_pet(pet_id) -> list[PetMatch]   # Sorted by score DESC
get_unmatched_records(source, limit=500) -> list[PetRow]
```

**Scraper State:**
```python
get_scraper_state(source) -> ScraperState | None
update_scraper_state(source, success, records_fetched,
                     records_new, last_record_at, error_message)
```

**Staleness:**
```python
get_stale_records(source, older_than_hours=48) -> list[PetRow]
```

---

## Query Patterns

### Haversine Distance (Spatial Query)

Used in `find_within_radius()` for geographic searches:

```python
# Bounding box pre-filter (fast, index-friendly)
lat_min = lat - delta_lat
lat_max = lat + delta_lat
lon_min = lon - delta_lon
lon_max = lon + delta_lon

# Haversine formula (accurate, applied to pre-filtered set)
# R = 3958.8 miles (Earth radius)
distance = R * acos(sin(lat1)*sin(lat2) + cos(lat1)*cos(lat2)*cos(lon2-lon1))
```

### GeoJSON with Match Counts

The map endpoint uses a JOIN + UNION ALL query to efficiently include match counts:

```sql
SELECT p.*, COUNT(m.id) as match_count
FROM pet_rows p
LEFT JOIN (
    SELECT pet_a_id as pet_id, id FROM pet_matches
    UNION ALL
    SELECT pet_b_id as pet_id, id FROM pet_matches
) m ON m.pet_id = p.id
WHERE p.lat BETWEEN ? AND ?
  AND p.lon BETWEEN ? AND ?
  AND p.active = 1
GROUP BY p.id
LIMIT 500
```

### Unmatched Records (Efficient NOT EXISTS)

```sql
SELECT * FROM pet_rows p
WHERE p.active = 1
  AND NOT EXISTS (
      SELECT 1 FROM pet_matches m
      WHERE m.pet_a_id = p.id OR m.pet_b_id = p.id
  )
LIMIT 500
```

---

## Migration Strategy

Currently using SQLAlchemy's `create_all()` for schema creation. For production with schema evolution:

1. Add Alembic for migrations (`alembic init`)
2. Generate migration scripts from model changes
3. Run migrations as part of deployment pipeline
4. Support both SQLite and PostgreSQL in migration scripts
