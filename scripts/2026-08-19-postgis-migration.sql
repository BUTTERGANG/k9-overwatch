-- PostGIS migration: add spatial geometry + index to the pets table.
-- Added 2026-08-19 as part of the geo-query optimisation pass.
--
-- PRODUCTION ONLY — do NOT run against a local SQLite dev database.
-- SQLite has no PostGIS support; skip this file entirely in dev.
-- -------------------------------------------------------------------
--   # PostgreSQL (production):
--     psql "$DATABASE_URL" < scripts/2026-08-19-postgis-migration.sql
--
--   # To preview before running:
--     psql "$DATABASE_URL" -f scripts/2026-08-19-postgis-migration.sql --dry-run
--
-- Rollback (undo everything):
--   DROP INDEX IF EXISTS ix_pets_location_gist;
--   ALTER TABLE pets DROP COLUMN IF EXISTS location;
--   -- Do NOT drop the postgis extension — other tables may depend on it.
-- -------------------------------------------------------------------

-- 1. Enable PostGIS (idempotent — safe to re-run).
CREATE EXTENSION IF NOT EXISTS postgis;

-- 2. Add a geography/geometry column for the pet's location.
--    SRID 4326 = WGS 84 (lat/lon on the Earth's spheroid).
--    We store using the geometry type (planar) for performance but cast to
--    geography in queries when true spherical distance is needed.
ALTER TABLE pets ADD COLUMN IF NOT EXISTS location geometry(Point, 4326);

-- 3. Backfill the geometry column from existing lat/lon columns.
--    ST_MakePoint(lon, lat) — note coordinate order: X=longitude, Y=latitude.
UPDATE pets
SET location = ST_SetSRID(ST_MakePoint(lon, lat), 4326)
WHERE lat IS NOT NULL
  AND lon IS NOT NULL
  AND location IS NULL;

-- 4. Create a GIST spatial index on the geography cast for fast
--    ST_DWithin / ST_Intersects queries.
--    The index on the geography cast (rather than geometry) enables
--    true spherical distance lookups without per-query casts.
CREATE INDEX IF NOT EXISTS ix_pets_location_gist
    ON pets
    USING GIST (geography(location));

-- 5. Ensure future inserts automatically populate the geometry column.
--    (Optional — uncomment if you prefer a trigger.)
-- CREATE OR REPLACE FUNCTION trg_pets_set_location()
-- RETURNS trigger AS $$
-- BEGIN
--     IF NEW.lat IS NOT NULL AND NEW.lon IS NOT NULL THEN
--         NEW.location = ST_SetSRID(ST_MakePoint(NEW.lon, NEW.lat), 4326);
--     END IF;
--     RETURN NEW;
-- END;
-- $$ LANGUAGE plpgsql;
--
-- DROP TRIGGER IF EXISTS trg_pets_location ON pets;
-- CREATE TRIGGER trg_pets_location
--     BEFORE INSERT OR UPDATE OF lat, lon
--     ON pets
--     FOR EACH ROW
--     EXECUTE FUNCTION trg_pets_set_location();

-- 6. (Optional) Drop the old composite indexes on (lat, lon) since the
--    spatial index covers those queries and more.
--    Only drop after verifying the new index is used in production queries.
-- DROP INDEX IF EXISTS ix_pets_active_lat_lon;
-- DROP INDEX IF EXISTS ix_pets_active_date_lat_lon;