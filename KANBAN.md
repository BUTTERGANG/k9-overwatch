# K9-Overwatch — Scrum Board

> **Sprint 1** — Aug 19 – Sep 2, 2026
> Repo: https://github.com/BUTTERGANG/k9-overwatch

---

## ✅ Done (Sprint 1)

| Feature | Notes |
|---------|-------|
| Auto-stale flagging (two-phase) | User reports notified first, deactivated 24h later |
| Geocode confidence on map pins | "Exact location" / "Neighborhood" / "ZIP code area" badges |
| Reunited status path | Owner can mark report as reunited; deactivates + counterpart |
| Reactivation path | Owner can re-activate auto-deactivated reports |
| Source health dashboard | Per-source pet counts, geocode fill rate, record-type breakdown |
| Contact relay for scraped listings | "Submit a tip" form for scraped pets with no owner contact |
| Reunification success metrics | `/api/stats` endpoint + landing page counter |
| PostGIS migration plan | `docs/postgis-migration.md` + migration script |
| PR #4 merged | Scheduler cadence fix (interval triggers) |
| PLAN.md + KANBAN.md created | Development plan + sprint board |
| Cross-source deduplication | In progress |
| Petfinder.com API integration | In progress |
| Rate-limited mutation endpoints (D13) | Flags 10/hr; contact reply/status/block 30/hr — `7d2fc48` |
| Public "Recently Reunited" gallery (§3) | `GET /reunited`, user-submitted reunited reports only, empty state, `user_reunifications` in `/api/stats` — `635932c` |
| Perceptual-hash visual similarity groundwork (C11) | dHash provider behind `VISUAL_SIMILARITY_ENABLED` (default off), `visual_embeddings` cache table, optional `[visual]` extra (Pillow) — `a20cfbc` |

## 📋 Backlog

| Feature | Priority | Notes |
|---------|----------|-------|
| Saved search radius queries | Medium | Already have SavedSearch model with lat/lon/radius |
| Google Maps geocoding provider | Low | Env var exists, needs testing |
| Mobile app | Low | Responsive web works; no demand yet |

---

## How to use this board

Update the tables above as work progresses. Move items between columns by editing this file.