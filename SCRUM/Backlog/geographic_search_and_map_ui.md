---
status: backlog
priority: P2
agent_claimed: null
claimed_at: null
updated: 2026-08-19
---

# Geographic Search and Map UI

> **Repo:** k9-overwatch
> **Description:** Build location-based search with interactive map view of nearby listings

---

## Context

Users need to see animals near them — zip code radius search, map pins, quick-filter by species/breed/size/status.

---

## Acceptance Criteria

- [ ] Radius search by zip code with configurable distance
- [ ] Interactive map (MapLibre/Leaflet) with clustering for dense areas
- [ ] Filter bar with species, breed, size, color, and status toggles
- [ ] Pin detail popup with photo thumbnail and link to full listing

---

## Technical Notes

- PostGIS for geo queries; MapLibre GL JS for map; lazy-load pins on pan
