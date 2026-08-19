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
| PLAN.md created | Development plan at repo root |

## 🔄 In Progress

| Feature | Owner | Notes |
|---------|-------|-------|
| Cross-source deduplication | — | Same pet on different sources = duplicate pins |
| Petfinder.com API integration | — | Official structured JSON API |

## 📋 Backlog

| Feature | Priority | Notes |
|---------|----------|-------|
| Contact relay email delivery | Medium | Actually send emails for scraped tips |
| Petfinder.com scraper | High | Cleanest data source available |
| Cross-source dedup | High | Most visible user-facing issue |
| Saved search radius queries | Medium | Already have SavedSearch model with lat/lon/radius |
| Google Maps geocoding provider | Low | Env var exists, needs testing |
| Bulk geocode for existing null-coord records | Low | One-time backfill script |
| Mobile app | Low | Responsive web works; no demand yet |

---

## How to use this board

Update the tables above as work progresses. Move items between columns by editing this file. Create a new Sprint section when the current one ends.