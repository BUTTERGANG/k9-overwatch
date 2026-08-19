# PostGIS Migration Plan

> **Status:** Planning document  
> **Target:** Production PostgreSQL only — no changes to dev SQLite setup  
> **Author:** Infrastructure  
> **Date:** 2026-08-19

---

## Why PostGIS?

The current map endpoint (`/api/map/geojson`) filters pets using raw bounding-box comparisons on `lat` / `lon` float columns:

```python
# src/k9overwatch/web/routers/map.py — current approach (lines 60–70)
longitude_filter = (
    PetRow.lon.between(sw_lng, ne_lng)
    if sw_lng <= ne_lng
    else or_(PetRow.lon >= sw_lng, PetRow.lon <= ne_lng)
)
stmt = select(PetRow).where(
    PetRow.active == True,
    PetRow.lat >= sw_lat,
    PetRow.lat <= ne_lat,
    longitude_filter,
)
```

This works correctly at low volume but has several drawbacks that grow with scale:

| Problem | Impact |
|---|---|
| **No true distance queries** | Cannot do radius-based ("find all pets within 5 km") searches efficiently |
| **Index inefficiency** | B-tree on `(lat, lon)` can only use the leading column for range scans; the second column (`lon`) is effectively useless for range predicates |
| **Date-line crossover hack** | The `sw_lng <= ne_lng` ternary is a manual workaround for bounding boxes that cross the ±180° meridian — PostGIS handles this natively |
| **No spherical geometry** | `lat >= X AND lat <= Y` treats the Earth as a flat grid, introducing distortion at high latitudes |

**PostGIS** is a mature, well-tested spatial extension for PostgreSQL that provides:

- **`ST_DWithin`** — true spherical distance queries with index acceleration
- **GIST spatial indexes** — significantly faster than B-tree for geographic range lookups
- **Native geometry types** — `geometry(Point, 4326)` stores lat/lon in a single indexed column
- **Date-line / pole handling** — all spatial predicates handle the Earth's curvature and antimeridian correctly
- **Rich geography functions** — `ST_Distance`, `ST_Area`, `ST_Intersects`, `ST_Within`, etc.

---

## When to Do This

Perform this migration when one or both conditions are met:

1. **Pet count exceeds ~50,000 active records** — the current bounding-box approach will start showing latency under concurrent user traffic.
2. **Radius-based queries are needed** — any feature like "notify me when a pet is found within X miles of my home" requires `ST_DWithin`, which PostGIS provides with index support. The `SavedSearch` model already has `latitude`, `longitude`, and `radius_miles` fields, suggesting this feature is on the roadmap.

---

## Migration Steps

### Step 1: Apply the SQL migration on PostgreSQL

```bash
# Production
psql "$DATABASE_URL" < scripts/2026-08-19-postgis-migration.sql
```

The migration script (`scripts/2026-08-19-postgis-migration.sql`) does the following:

1. **Creates the PostGIS extension** — `CREATE EXTENSION IF NOT EXISTS postgis;`
2. **Adds the geometry column** — `ALTER TABLE pets ADD COLUMN location geometry(Point, 4326);`
3. **Backfills existing data** — sets `location` from existing `lat` / `lon` for all non-null rows
4. **Creates a GIST spatial index** — `CREATE INDEX ON pets USING GIST (geography(location));`

The entire migration is idempotent — it can be re-run safely.

### Step 2: Verify the data

```sql
-- Count rows with location vs without
SELECT
    COUNT(*) FILTER (WHERE location IS NOT NULL) AS geocoded,
    COUNT(*) FILTER (WHERE location IS NULL)     AS missing_location
FROM pets;

-- Spot-check a sample
SELECT id, lat, lon,
       ST_AsText(location)                     AS location_wkt,
       ST_Distance(
           geography(location),
           geography(ST_MakePoint(-122.4194, 37.7749))
       )                                        AS distance_from_sf_meters
FROM pets
WHERE location IS NOT NULL
LIMIT 10;
```

### Step 3: Keep indexes clean (optional, after verification)

Once the spatial index is proven in production (monitor query plans with `EXPLAIN ANALYZE`), the old composite B-tree indexes on `(lat, lon)` can be dropped:

```sql
DROP INDEX IF EXISTS ix_pets_active_lat_lon;
DROP INDEX IF EXISTS ix_pets_active_date_lat_lon;
```

These indexes are now redundant — the GIST index on `geography(location)` covers all spatial lookups more efficiently.

---

## Updating the Map Query (Application Code)

> **Note:** This section describes what the *future* code change should look like. The actual code changes are **out of scope** for this planning document. Do not modify `map.py` yet.

### Option A: Replace bounding box with `ST_DWithin` (recommended)

Instead of computing a bounding box from the viewport corners and filtering with `>=` / `<=` comparisons, use the viewport centre and `ST_DWithin` to find all pets within the viewport's diagonal:

```python
# Future query — replaces the bounding-box filter
from sqlalchemy import func

centre_lat = (sw_lat + ne_lat) / 2.0
centre_lon = (sw_lng + ne_lng) / 2.0

# Approximate radius: half the viewport diagonal in metres
# (1° lat ≈ 111,320 m; 1° lon ≈ 111,320 * cos(lat) m)
dlat = (ne_lat - sw_lat) / 2.0
dlon = (ne_lng - sw_lng) / 2.0
radius_meters = int(
    ((dlat * 111_320) ** 2 + (dlon * 111_320 * abs(cos(radians(centre_lat)))) ** 2) ** 0.5
)

stmt = select(PetRow).where(
    PetRow.active == True,
    func.ST_DWithin(
        PetRow.location,
        func.ST_MakePoint(centre_lon, centre_lat),
        radius_meters,
    ),
)
```

### Option B: Keep bounding box but use PostGIS geometry

If you prefer to keep the bounding-box shape (simpler, no centre-point approximation), replace the raw column comparisons with PostGIS functions:

```python
# Future query — uses PostGIS bounding box
from geoalchemy2 import Geometry, WKTElement
from sqlalchemy import func

# Build a WKT polygon from viewport corners
# Note: PostGIS uses (lon lat) ordering, so the polygon is:
#   SW lon SW lat, NW lon NW lat, NE lon NE lat, SE lon SE lat, SW lon SW lat
bbox = func.ST_MakeEnvelope(sw_lng, sw_lat, ne_lng, ne_lat, 4326)

stmt = select(PetRow).where(
    PetRow.active == True,
    func.ST_Intersects(PetRow.location, bbox),
)
```

This still requires bounding-box computation on the client, but the server query benefits from the spatial index.

### Option C: True radius search (for saved-search alerts)

When implementing radius-based alerts (already modelled in `SavedSearch` with `latitude`, `longitude`, `radius_miles`):

```python
# Future query — radius search around a point
from sqlalchemy import func

# Convert miles to metres
radius_meters = saved_search.radius_miles * 1609.34

stmt = select(PetRow).where(
    PetRow.active == True,
    func.ST_DWithin(
        PetRow.location,
        func.ST_MakePoint(saved_search.longitude, saved_search.latitude),
        radius_meters,
    ),
)
```

---

## SQLAlchemy / ORM Considerations

When you're ready to update the application code, there are two approaches:

### Approach 1: `geoalchemy2` (recommended)

Add `geoalchemy2` to your dependencies and use its `Geometry` column type alongside (or replacing) the raw `lat` / `lon` Float columns:

```python
from geoalchemy2 import Geometry

class PetRow(Base):
    __tablename__ = "pets"

    # ... existing columns ...

    # Existing lat/lon — keep for SQLite dev compatibility
    lat = Column(Float, nullable=True)
    lon = Column(Float, nullable=True)

    # New PostGIS geometry — only populated on PostgreSQL
    location = Column(Geometry("POINT", srid=4326), nullable=True)
```

Install: `pip install geoalchemy2`

### Approach 2: Raw SQL / `func.*` without geoalchemy2

Use `sqlalchemy.func.ST_DWithin(…)` with raw column references. This works without additional dependencies but loses some type safety:

```python
from sqlalchemy import func

stmt = select(PetRow).where(
    func.ST_DWithin(
        PetRow.__table__.c.location,  # raw column reference
        func.ST_MakePoint(lon, lat),
        radius_meters,
    )
)
```

---

## Dev vs. Prod Strategy

| Environment | Database | Geo approach | Notes |
|---|---|---|---|
| **Development** | SQLite | Raw `lat` / `lon` float columns (current) | No changes needed. SQLite doesn't support PostGIS. Migration script should NOT be run in dev. |
| **Production** | PostgreSQL | PostGIS `geometry(Point, 4326)` column | Apply migration. Optionally keep `lat` / `lon` populated for fallback/backward compat. |

**Key principle:** The `lat` and `lon` float columns stay in the schema indefinitely. Application code that reads these columns continues to work. The PostGIS migration is additive — it adds a new `location` column but does not remove any columns.

This means:
- Dev keeps working with SQLite and the existing float-column approach
- Prod gets the faster PostGIS path
- A future refactor can optionally backfill `lat`/`lon` from `location` and deprecate the float columns

---

## Dependency & SQLAlchemy Version Compatibility

When enabling the code changes, confirm these package versions:

```
# requirements.txt / pyproject.toml
geoalchemy2>=0.15.0          # ORM integration
# (PostgreSQL adapter already required for prod)
psycopg2-binary>=2.9.9       # or psycopg (3.x)
```

GeoAlchemy2 0.15+ works with SQLAlchemy 2.0's async session pattern used in this project.

---

## Rollback Plan

If issues arise after the migration:

```sql
-- Emergency rollback (reversible)
DROP INDEX IF EXISTS ix_pets_location_gist;
ALTER TABLE pets DROP COLUMN IF EXISTS location;
-- Note: Do NOT drop the postgis extension — other tables may use it.
```

The app stays operational after rollback because the code path still uses `lat` / `lon` float columns — the PostGIS column is purely additive.

---

## Example Queries (for reference)

### Radius search — find pets within 5 miles of a point

```sql
SELECT id, name, record_type,
       ST_Distance(
           geography(location),
           geography(ST_MakePoint(-122.4194, 37.7749))
       ) AS distance_meters
FROM pets
WHERE active = true
  AND ST_DWithin(
      geography(location),
      geography(ST_MakePoint(-122.4194, 37.7749)),
      8047  -- 5 miles in metres
  )
ORDER BY distance_meters;
```

### Bounding-box (viewport) query

```sql
SELECT id, name, record_type
FROM pets
WHERE active = true
  AND ST_Intersects(
      location,
      ST_MakeEnvelope(-122.5, 37.7, -122.3, 37.9, 4326)
  );
```

### Count pets per neighbourhood with spatial aggregation

```sql
SELECT city, county, COUNT(*) AS pet_count
FROM pets
WHERE active = true
  AND ST_DWithin(
      geography(location),
      geography(ST_MakePoint(-122.4194, 37.7749)),
      16093  -- 10 miles
  )
GROUP BY city, county
ORDER BY pet_count DESC;
```

---

## References

- [PostGIS Documentation](https://postgis.net/documentation/)
- [GeoAlchemy2 Documentation](https://geoalchemy-2.readthedocs.io/)
- [ST_DWithin](https://postgis.net/docs/ST_DWithin.html)
- [ST_MakeEnvelope](https://postgis.net/docs/ST_MakeEnvelope.html)
- [ST_MakePoint](https://postgis.net/docs/ST_MakePoint.html)
- [Working with SRID 4326](https://postgis.net/workshops/postgis-intro/geography.html)