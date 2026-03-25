# Unified Pet Record Schema

**Version:** 1.0
**Date:** 2026-03-24
**Purpose:** Canonical data structure for all pet records ingested from any source

All scrapers normalize their source data into this schema before storage.

---

## Core Pet Record

```json
{
  "id": "uuid-v4",
  "source": "24petconnect | pawboost | indylostpetalert | petfbi | lostmydoggie | petfinder | ...",
  "source_id": "string — unique ID within the source system",
  "source_url": "https://... — canonical link back to the original listing",

  "record_type": "lost | found | sighting | adoptable",

  "animal_type": "dog | cat | bird | rabbit | other",
  "name": "string | null",
  "breed": "string | null",
  "breed_secondary": "string | null",
  "color_primary": "string | null",
  "color_secondary": "string | null",
  "gender": "male | female | unknown",
  "age": "string | null",
  "size": "xsmall | small | medium | large | xlarge | xxlarge | null",
  "size_lbs": "string | null",
  "microchipped": "true | false | null",
  "microchip_number": "string | null",
  "distinctive_features": "string | null",

  "status": "string — source-specific status label",
  "date_event": "ISO8601 date — date lost/found/seen",
  "time_event": "string | null — approximate time",
  "days_since_event": "integer | null",
  "date_posted": "ISO8601 datetime — when posted to source",
  "date_updated": "ISO8601 datetime | null",
  "active": "boolean — false if reunited/removed/expired",

  "location_text": "string — raw address/intersection as provided",
  "neighborhood": "string | null",
  "city": "string | null",
  "county": "string | null",
  "state": "string — 2-letter code",
  "zip": "string | null",
  "country": "US | CA",
  "lat": "float | null — geocoded",
  "lon": "float | null — geocoded",
  "geocode_source": "google | nominatim | zip_centroid | null",
  "geocode_confidence": "high | medium | low | null",

  "shelter_name": "string | null",
  "shelter_code": "string | null",
  "shelter_id": "string | null",

  "contact_phone": "string | null",
  "contact_email": "string | null",
  "contact_method": "form | phone | email | message",

  "description": "string | null — free-text description",
  "owner_message": "string | null — additional message from owner",

  "photos": ["url1", "url2"],
  "thumbnail_url": "string | null",

  "facebook_post_url": "string | null",
  "nextdoor_url": "string | null",
  "alert_number": "string | null — source-specific alert ID",

  "scraped_at": "ISO8601 datetime",
  "last_checked_at": "ISO8601 datetime",

  "raw": {}
}
```

---

## Field Definitions

### `record_type`

| Value | Meaning |
|---|---|
| `lost` | Owner reports their pet is missing |
| `found` | Someone found a stray or reports a found pet |
| `sighting` | A pet matching a lost description was spotted but not caught |
| `adoptable` | Pet available for adoption at a shelter or rescue |

### `animal_type`

Normalized from each source's animal classification:

| Normalized | 24petconnect | PawBoost | IndyLostPetAlert |
|---|---|---|---|
| `dog` | "dogs" / "Dog" | "Dog" | cat ID=24/27/33 |
| `cat` | "cats" / "Cat" | "Cat" | cat ID=25/28/34 |
| `bird` | "other" | — | cat ID=166/172 |
| `rabbit` | "other" | — | — |
| `other` | "other" | — | cat ID=26/29/35 |

### `size`

Normalized size bucket from each source's weight/size labels:

| Normalized | Weight Range | 24petconnect | PawBoost | IndyLostPetAlert |
|---|---|---|---|---|
| `xsmall` | < 10 lbs | — | — | cat ID 182/180 |
| `small` | 10–25 lbs | — | — | cat ID 127/138 |
| `medium` | 25–50 lbs | — | — | cat ID 128/139 |
| `large` | 50–75 lbs | — | — | cat ID 129/140 |
| `xlarge` | 75–90 lbs | — | — | cat ID 130/141 |
| `xxlarge` | 90+ lbs | — | — | cat ID 183/179 |

### `gender`

| Normalized | 24petconnect | PawBoost | IndyLostPetAlert |
|---|---|---|---|
| `male` | "M" | "Male" | "Male" in content |
| `female` | "F" | "Female" | "Female" in content |
| `unknown` | "" | "" | absent |

---

## Source Mapping Tables

### 24petconnect → Unified Schema

| Unified Field | 24petconnect Source | Notes |
|---|---|---|
| `source` | `"24petconnect"` | static |
| `source_id` | `AnimalId` from onclick | e.g., `"3055840"` |
| `source_url` | `/LostFound/Details/{ShelterCode}/{AnimalId}` | constructed |
| `record_type` | `SearchType` param | LOST→`lost`, FOUND→`found`, ADOPT→`adoptable` |
| `animal_type` | span "Animal type : Dog" | parsed from listing card |
| `name` | span "Name : Chase" | adopt only; null for lost/found |
| `breed` | span "Breed : Yorkshire Terrier" | |
| `gender` | span "Gender : Male" | normalize to lowercase |
| `age` | span "Age : 8 months old" | free text |
| `status` | span "Status : Reported Lost by the Owner" | |
| `days_since_event` | span "Days Since Lost : 2" | |
| `date_posted` | span "Brought to shelter : YYYY.MM.DD" | adopt/found |
| `date_event` | detail page only | not in listing card |
| `location_text` | span "Location Lost : 1300 Block Iron Gate Blvd" | lost only |
| `shelter_name` | span "Located at : K9 Coop" | found/adopt |
| `shelter_code` | first arg of `Details()` onclick | e.g., `"Public"` |
| `description` | detail page "Description" field | requires extra request |
| `photos` | `/image/{imageId}` | from `<img>` src |
| `lat` / `lon` | null — geocode `location_text` | |
| `contact_phone` | detail page contact form only | |

### PawBoost → Unified Schema

| Unified Field | PawBoost Source | Notes |
|---|---|---|
| `source` | `"pawboost"` | static |
| `source_id` | numeric PawBoost ID | e.g., `"72699791"` |
| `source_url` | `/landing/pet/{hash}/{slug}` | full detail URL |
| `record_type` | status badge | `label-danger`→`lost`, `label-success`→`found` |
| `animal_type` | `.pet-feed-details` small tag | "Dog" / "Cat" |
| `name` | `.pet-feed-name` h2 | |
| `breed` | `.pet-feed-description` text | extract from description |
| `gender` | `.pet-feed-details` small tag | "Male" / "Female" |
| `location_text` | img `alt` attribute | "Sherburne lane, Indianapolis, IN 46222" |
| `city` | `.pet-feed-location` h3 | "Indianapolis, IN 46222" |
| `zip` | URL slug last segment | e.g., `46222` |
| `date_event` | Nextdoor share URL decode | "March 23, 2026" |
| `description` | `.pet-feed-description` p | |
| `owner_message` | Nextdoor share URL decode | |
| `photos` | `img-cdn.pawboost.com` src | `-thumb.jpeg` suffix → full |
| `thumbnail_url` | `img-cdn.pawboost.com` `-thumb.jpeg` | |
| `facebook_post_url` | `.btn-facebook` href | |
| `alert_number` | numeric PawBoost ID | `"72699791"` |
| `lat` / `lon` | null — geocode `location_text` | |

### IndyLostPetAlert → Unified Schema

| Unified Field | IndyLostPetAlert Source | Notes |
|---|---|---|
| `source` | `"indylostpetalert"` | static |
| `source_id` | WordPress post `id` | e.g., `"269782"` |
| `source_url` | post `link` | |
| `record_type` | category IDs | 19→`lost`, 20→`found`, 21→`sighting` |
| `animal_type` | category IDs | 24/27/33→`dog`, 25/28/34→`cat`, 26/29/35→`other` |
| `name` | content "Pet's Name:" | regex parsed |
| `breed` | content description | free-text, no structured field |
| `color_primary` | tag IDs + "Color of Pet:" | both structured tag and text |
| `gender` | content "Gender:" | regex parsed |
| `size` | content "Pet Size:" + category | structured + text |
| `size_lbs` | category slug | e.g., "Small (10-25 lbs)" |
| `date_event` | content "Date Pet Went Missing:" | regex parsed, MM/DD/YYYY |
| `time_event` | content "Approximate Time..." | regex parsed |
| `date_posted` | post `date` field | ISO8601 |
| `location_text` | content "Location Information:" | regex parsed |
| `county` | location_text last segment | "Marion County" |
| `city` | location_text city segment | |
| `contact_phone` | content "Phone:" | regex parsed — direct phone number |
| `description` | content after "Gender:" line | free-text |
| `photos` | `jetpack_featured_media_url` | direct URL |
| `alert_number` | title "Alert #XXXXX" | regex parsed |
| `lat` / `lon` | null — geocode `location_text` | |

### Pet FBI → Unified Schema

| Unified Field | Pet FBI Source | Notes |
|---|---|---|
| `source` | `"petfbi"` | static |
| `source_id` | `report_id` | integer, cast to string |
| `source_url` | `https://petfbi.org/report/{report_id}` | constructed |
| `record_type` | `report_type` | `"lost"` / `"found"` / `"sighting"` |
| `animal_type` | `species` | normalize to lowercase |
| `name` | `animal_name` | |
| `breed` | `breedlabel1` | |
| `breed_secondary` | `breedlabel2` | |
| `color_primary` | `colorlabel1` | |
| `color_secondary` | `colorlabel2` | |
| `gender` | `gender` | normalize to lowercase |
| `age` | `age` | free text |
| `distinctive_features` | `markings` | |
| `status` | `status` | |
| `date_event` | `event_date` | ISO8601 |
| `date_updated` | `last_updated` | ISO8601 |
| `location_text` | `location_comments` | |
| `lat` | `geo_latitude` | **provided directly — no geocoding needed** |
| `lon` | `geo_longitude` | **provided directly — no geocoding needed** |
| `geocode_source` | `"petfbi_native"` | when lat/lon present |
| `geocode_confidence` | `"high"` | when lat/lon present |
| `contact_email` | `public_email` | |
| `contact_name` | `contact_name` | |
| `description` | `comments` | |
| `photos` | `picture_file` | single URL (wrap in array) |

### Lost My Doggie → Unified Schema

| Unified Field | Lost My Doggie Source | Notes |
|---|---|---|
| `source` | `"lostmydoggie"` | static |
| `source_id` | alert ID from listing | extracted from URL or card |
| `source_url` | listing detail URL | constructed |
| `record_type` | `alerttypeid` | `1`→`lost`, `3`→`found` |
| `animal_type` | `petkindid` | `1`→`dog`, `2`→`cat` |
| `name` | card title | parsed |
| `breed` | card description | free text |
| `color_primary` | card description | free text |
| `gender` | card description | parsed |
| `date_event` | card date field | parsed |
| `location_text` | city/state shown | ZIP/city precision only |
| `city` | card location | parsed |
| `state` | card location | parsed |
| `zip` | URL param `zipcode` | search ZIP (not exact location) |
| `lat` / `lon` | null — geocode `location_text` | |
| `photos` | card image | |

---

## Size Normalization

```python
SIZE_MAP = {
    # IndyLostPetAlert category slugs
    "x-small-lost-dog":      "xsmall",
    "x-small-dog-found-pet": "xsmall",
    "xsmall-under-10-lbs":   "xsmall",
    "small":                 "small",
    "small-dog-found-pet":   "small",
    "small-under-25-lbs":    "small",
    "medium":                "medium",
    "medium-dog-found-pet":  "medium",
    "large":                 "large",
    "large-dog-found-pet":   "large",
    "x-large":               "xlarge",
    "x-large-dog-found-pet": "xlarge",
    "xx-large-dog":          "xxlarge",
    "xx-large-dog-found-pet":"xxlarge",
    # Cat sizes
    "small-cat":             "xsmall",
    "small-cat-found-pet":   "xsmall",
    "medium-cat":            "small",
    "medium-cat-found-pet":  "small",
    "large-cat":             "medium",
    "large-cat-found-pet":   "medium",
    "x-large-cat":           "large",
    # Text labels (24petconnect, PawBoost)
    "x-small (10 lbs & under)": "xsmall",
    "small (10-25 lbs)":        "small",
    "medium (25-50 lbs)":       "medium",
    "large (50-75 lbs)":        "large",
    "x-large (75-90 lbs)":      "xlarge",
    "xx-large (90+ lbs)":       "xxlarge",
}
```

---

## Color Normalization

```python
# IndyLostPetAlert tag IDs → canonical color names
COLOR_TAG_MAP = {
    223: "Black",
    224: "Brown",
    234: "White",
    228: "Grey",
    232: "Tan",
    233: "Tri-Color",
    237: "Tabby",
    226: "Brindle",
    241: "Orange",
    231: "Spotted",
    230: "Red",
    236: "Calico",
    227: "Golden",
    229: "Merle",
    248: "Tortoise",
    235: "Yellow",
    239: "Blue",
    240: "Green",
}
```

---

## Deduplication

**Primary key per record:** `(source, source_id)`

**Cross-source deduplication** (same pet on multiple platforms) is a Phase 2 concern. Candidate matching signals:
- ZIP code match
- Animal type match
- Date event within ±3 days
- Color + breed similarity (fuzzy)
- Photo similarity (image hash or ML embedding)

---

## Database Schema (PostgreSQL + PostGIS)

```sql
CREATE TABLE pets (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source              TEXT NOT NULL,
    source_id           TEXT NOT NULL,
    source_url          TEXT,
    record_type         TEXT NOT NULL CHECK (record_type IN ('lost','found','sighting','adoptable')),

    animal_type         TEXT,
    name                TEXT,
    breed               TEXT,
    breed_secondary     TEXT,
    color_primary       TEXT,
    color_secondary     TEXT,
    gender              TEXT CHECK (gender IN ('male','female','unknown')),
    age                 TEXT,
    size                TEXT CHECK (size IN ('xsmall','small','medium','large','xlarge','xxlarge')),
    size_lbs            TEXT,
    microchipped        BOOLEAN,
    microchip_number    TEXT,
    distinctive_features TEXT,

    status              TEXT,
    date_event          DATE,
    time_event          TEXT,
    days_since_event    INTEGER,
    date_posted         TIMESTAMPTZ,
    date_updated        TIMESTAMPTZ,
    active              BOOLEAN DEFAULT TRUE,

    location_text       TEXT,
    neighborhood        TEXT,
    city                TEXT,
    county              TEXT,
    state               CHAR(2),
    zip                 TEXT,
    country             CHAR(2) DEFAULT 'US',
    location            GEOMETRY(Point, 4326),       -- PostGIS point (lon, lat)
    geocode_source      TEXT,
    geocode_confidence  TEXT,

    shelter_name        TEXT,
    shelter_code        TEXT,
    shelter_id          TEXT,

    contact_phone       TEXT,
    contact_email       TEXT,
    contact_method      TEXT,

    description         TEXT,
    owner_message       TEXT,
    photos              TEXT[],
    thumbnail_url       TEXT,

    facebook_post_url   TEXT,
    nextdoor_url        TEXT,
    alert_number        TEXT,

    scraped_at          TIMESTAMPTZ DEFAULT NOW(),
    last_checked_at     TIMESTAMPTZ DEFAULT NOW(),

    raw                 JSONB,

    UNIQUE (source, source_id)
);

-- Spatial index for geo queries
CREATE INDEX pets_location_idx ON pets USING GIST (location);

-- Fast lookup by type + date
CREATE INDEX pets_type_date_idx ON pets (record_type, date_posted DESC);

-- Active records only
CREATE INDEX pets_active_idx ON pets (active, source, date_posted DESC);
```

### Example Geo Query (find lost dogs within 10 miles of a point)

```sql
SELECT *,
    ST_Distance(
        location::geography,
        ST_MakePoint(-86.1581, 39.7684)::geography
    ) / 1609.34 AS distance_miles
FROM pets
WHERE record_type = 'lost'
  AND animal_type = 'dog'
  AND active = TRUE
  AND ST_DWithin(
      location::geography,
      ST_MakePoint(-86.1581, 39.7684)::geography,
      16093.4   -- 10 miles in meters
  )
ORDER BY distance_miles ASC
LIMIT 50;
```
