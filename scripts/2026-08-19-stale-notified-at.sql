-- Add stale_notified_at column to pets table for auto-stale notification tracking.
-- Added 2026-08-19 as part of the stale-flagging improvement pass.
-- Run against the database once:
--   sqlite3 data/k9overwatch.db < scripts/2026-08-19-stale-notified-at.sql
-- For PostgreSQL:
--   ALTER TABLE pets ADD COLUMN stale_notified_at TIMESTAMP;

ALTER TABLE pets ADD COLUMN stale_notified_at TIMESTAMP;