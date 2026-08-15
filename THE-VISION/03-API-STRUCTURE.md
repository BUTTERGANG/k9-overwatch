# API Structure

## Overview

K9-Overwatch uses FastAPI to serve both server-rendered HTML pages (via Jinja2 templates) and JSON API endpoints. The application uses HTMX for dynamic page updates without a full JavaScript framework.

---

## Route Map

### Public Pages (HTML)

| Method | Path | Description | Template |
|--------|------|-------------|----------|
| GET | `/map` | Interactive map with pet pins | `map.html` |
| GET | `/pets` | Pet listing with filters and pagination | `pets/list.html` |
| GET | `/pets/results` | HTMX partial for filtered results | `pets/_results.html` |
| GET | `/pets/{pet_id}` | Individual pet detail page | `pets/detail.html` |
| GET | `/matches` | Lost/Found match pairs for review | `matches/list.html` |

### Public API (JSON)

| Method | Path | Description | Response |
|--------|------|-------------|----------|
| GET | `/api/health` | Health check (DB connectivity) | `{"status": "ok"}` |
| GET | `/api/map/geojson` | Pet locations as GeoJSON | `GeoJSONCollection` |
| GET | `/proxy/image` | Proxied pet images with caching | Image bytes or 302 redirect |

### Protected Admin (HTML + JSON)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/admin` | HTTP Basic | Admin dashboard |
| GET | `/admin/stats-partial` | HTTP Basic | HTMX stats partial |
| GET | `/api/admin/stats` | HTTP Basic | System stats JSON |
| POST | `/api/matches/{match_id}/review` | None* | Confirm/reject a match |

*Match review currently has no auth - this is a candidate for future protection.

---

## Endpoint Details

### GET `/api/map/geojson`

Returns pet locations within a geographic bounding box as GeoJSON.

**Query Parameters:**

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `sw_lat` | float | Yes | Southwest corner latitude |
| `sw_lng` | float | Yes | Southwest corner longitude |
| `ne_lat` | float | Yes | Northeast corner latitude |
| `ne_lng` | float | Yes | Northeast corner longitude |
| `record_type[]` | list[str] | No | Filter: "lost", "found", "sighting" |
| `animal_type[]` | list[str] | No | Filter: "dog", "cat", etc. |
| `days` | int | No | Records from last N days (default: 90) |

**Response:**
```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": {
        "type": "Point",
        "coordinates": [-86.1581, 39.7684]
      },
      "properties": {
        "id": "uuid-string",
        "source": "pawboost",
        "record_type": "lost",
        "animal_type": "dog",
        "name": "Max",
        "breed": "Labrador Retriever",
        "color_primary": "yellow",
        "gender": "male",
        "date_event": "2026-03-15",
        "city": "Indianapolis",
        "state": "IN",
        "thumbnail_url": "/proxy/image?url=...",
        "match_count": 2
      }
    }
  ],
  "total": 147
}
```

### GET `/pets`

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `record_type[]` | list[str] | all | Filter by record type |
| `animal_type[]` | list[str] | all | Filter by animal type |
| `days` | int | 90 | Records from last N days |
| `page` | int | 1 | Pagination (24 per page) |

### GET `/pets/results`

Same parameters as `/pets`. Returns HTML fragment for HTMX replacement.

### GET `/matches`

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `match_type` | str | "lost_found" | "lost_found" or "dedup" |
| `confidence[]` | list[str] | all | Filter: "high", "medium", "low" |
| `page` | int | 1 | Pagination (20 per page) |

### POST `/api/matches/{match_id}/review`

**Auth:** HTTP Basic (ADMIN_USER / ADMIN_PASSWORD)

**Query Parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `confirmed` | bool | `true` to confirm the match, `false` to dismiss |

**Response:** HTML fragment (`matches/_review_badge.html`) for direct HTMX `outerHTML` swap. Returns the appropriate Confirmed / Dismissed badge. Non-admin requests receive 401; the matches page toasts a warning to the user via `window.showToast()`.

### GET `/proxy/image`

**Query Parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `url` | str | URL-encoded image URL to proxy |

**Behavior:**
- Validates URL against domain allowlist (31 known pet listing domains)
- Returns cached image bytes if available (1hr TTL, max 500 entries)
- Fetches and streams image if not cached (max 5MB)
- Returns 302 redirect to placeholder on any error

### GET `/api/health`

**Response:**
```json
{
  "status": "ok"
}
```

Returns 503 if database is unreachable.

### GET `/api/admin/stats`

**Auth:** HTTP Basic (ADMIN_USER / ADMIN_PASSWORD)

**Response:**
```json
{
  "scrapers": [
    {
      "source": "pawboost",
      "last_run_at": "2026-03-30T10:15:00Z",
      "last_run_success": true,
      "records_fetched": 45,
      "records_new": 3,
      "consecutive_errors": 0
    }
  ],
  "total_pets": 12450,
  "active_pets": 8320,
  "lost_count": 4100,
  "found_count": 3850,
  "no_geocode": 127,
  "total_matches": 892,
  "reunification_matches": 234,
  "generated_at": "2026-03-30T10:30:00Z"
}
```

---

## Router Organization

```
web/routers/
├── map.py           # /map, /api/map/geojson
├── pets.py          # /pets, /pets/results, /pets/{id}
├── matches.py       # /matches, /api/matches/{id}/review
├── admin.py         # /admin, /admin/stats-partial, /api/admin/stats
└── image_proxy.py   # /proxy/image
```

Each router is a `fastapi.APIRouter` instance included in the main app via `app.include_router()`.

---

## Response Models (Pydantic Schemas)

```
web/schemas/pet.py
├── PetSummary        # List/card view fields (id, breed, color, location, thumbnail)
├── PetDetail         # Full detail (extends PetSummary with photos, contact, description)
├── GeoJSONFeature    # Single map point with PetSummary properties
└── GeoJSONCollection # FeatureCollection wrapper with total count
```

---

## HTMX Integration

The frontend uses HTMX attributes for dynamic updates:

```html
<!-- Filter form triggers partial reload -->
<form hx-get="/pets/results" hx-target="#results" hx-trigger="change">
  <select name="record_type[]">...</select>
  <select name="animal_type[]">...</select>
</form>

<!-- Results container replaced on filter change -->
<div id="results">
  {% include "pets/_results.html" %}
</div>
```

This pattern provides SPA-like interactivity with server-rendered HTML, avoiding the complexity of a JavaScript framework.
