# THE-VISION: K9-Overwatch Technical Documentation

## Documents

| # | Document | Description |
|---|----------|-------------|
| 01 | [Application Architecture](01-APPLICATION-ARCHITECTURE.md) | High-level system architecture, directory structure, data flow, technology choices |
| 02 | [Data Handling](02-DATA-HANDLING.md) | Scrapers, normalizers, geocoding, database storage, matching engine, alerting |
| 03 | [API Structure](03-API-STRUCTURE.md) | All endpoints, request/response formats, HTMX integration, router organization |
| 04 | [Security](04-SECURITY.md) | Current security measures, identified gaps, recommendations for user accounts |
| 05 | [Database Structure](05-DATABASE-STRUCTURE.md) | Table definitions, indexes, ER diagram, repository pattern, query patterns |
| 06 | [User Accounts](06-USER-ACCOUNTS.md) | User registration, authentication, self-service listings, moderation, messaging, photo uploads |

---

## Quick Reference

**Stack:** Python 3.11+ / FastAPI / SQLAlchemy (async) / Jinja2 + HTMX / Tailwind CSS / Leaflet.js

**Data Sources:** IndyLostPetAlert, 24PetConnect, PawBoost, PetFBI, LostMyDoggie

**Database:** SQLite (dev) / PostgreSQL (prod) — 4 tables: pet_rows, pet_matches, scraper_state, geocode_cache

**Key Flows:**
- Scrape -> Normalize -> Geocode -> Upsert -> Match
- Browser -> FastAPI -> Repository -> Jinja2 Template -> HTML
- Map -> GeoJSON API -> Leaflet.js pins
