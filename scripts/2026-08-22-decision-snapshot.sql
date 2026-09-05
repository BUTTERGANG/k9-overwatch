-- 2026-08-22: decision-time signal snapshot for match review (roadmap C10).
-- Stores score/signals as they were when a human confirmed/rejected a match,
-- so future signal re-weighting has labeled data even after re-match updates.
ALTER TABLE pet_matches ADD COLUMN decision_snapshot JSON;
