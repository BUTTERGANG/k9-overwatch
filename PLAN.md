# K9-Overwatch — Development Plan

> **Version**: Pre-release  
> **Last Updated**: 2026-08-19  

A lost & found pet aggregation platform. Consolidates pet listings from multiple external sources, provides an interactive map, intelligent lost↔found matching, and an admin dashboard.

**This is the executive summary.** Detailed technical docs live in `THE-VISION/` — see the navigation table below.

---

## Quick Navigation

| Document | What It Covers |
|----------|---------------|
| `THE-VISION/01-APPLICATION-ARCHITECTURE.md` | High-level system architecture, directory structure, data flow, technology choices |
| `THE-VISION/02-DATA-HANDLING.md` | Scrapers, normalizers, geocoding, database storage, matching engine, alerting |
| `THE-VISION/03-API-STRUCTURE.md` | All endpoints, request/response formats, HTMX integration, router organization |
| `THE-VISION/04-SECURITY.md` | Current security measures, identified gaps, recommendations |
| `THE-VISION/05-DATABASE-STRUCTURE.md` | Table definitions, indexes, ER diagram, repository pattern, query patterns |
| `THE-VISION/06-USER-ACCOUNTS.md` | User registration, auth, self-service listings, moderation, messaging, photo uploads |
| `docs/PRODUCT_ROADMAP.md` | Product roadmap, feature prioritization |
| `docs/web-app-architecture-plan.md` | Web app architecture expansion plan |

---

## Current State

**Working prototype** — scrapers, geocoding, matching engine, and web map are functional. Pre-production — user accounts and moderation are in progress.

### What's Built
- **Scrapers** — 5 pet listing sources (IndyLostPetAlert, 24PetConnect, PawBoost, PetFBI, LostMyDoggie) via aiohttp HTTP scrapers + Playwright browser scrapers
- **Normalizer layer** — source-specific parsers producing canonical `PetRecord` format
- **Geocoding** — cascade of Google Maps → Nominatim → ZIP centroid fallback with DB-backed cache
- **Matching engine** — deduplicator (cross-source), lost↔found matcher with signal-based scoring
- **Web layer** — FastAPI + Jinja2 + HTMX + Leaflet.js map + GeoJSON API
- **Admin dashboard** — system stats, match review, HTTP Basic Auth
- **Scheduler** — APScheduler for scraper intervals, matching passes, staleness checks
- **Image proxy** — domain-allowlisted, size-limited, content-type validated, cached proxy for pet photos
- **User accounts** — registration, login, session management, owner self-service (report lost/found pets, manage listings)
- **Admin moderation** — listing review/moderation, user management
- **Messaging** — contact form between finders and pet owners

### What's Deployed
- FastAPI server (Python 3.11+)
- SQLite in dev, PostgreSQL in production
- No production domain confirmed in repo

### Test Health
- No dedicated test suite visible at repo root (pytest config not confirmed)
- Web layer tested implicitly through HTMX rendering

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Language** | Python 3.11+ |
| **Web Framework** | FastAPI |
| **Templating** | Jinja2 + HTMX (no JS framework) |
| **Map** | Leaflet.js + GeoJSON API |
| **Database** | SQLAlchemy 2.0 async ORM (SQLite dev / PostgreSQL prod) |
| **Scraping** | aiohttp (HTTP), Playwright (browser) |
| **Geocoding** | Google Maps API → Nominatim (OSM) → ZIP centroid |
| **Scheduling** | APScheduler (in-process) |
| **Auth** | HTTP Basic Auth (admin), HMAC-signed cookie sessions (user accounts) |
| **Validation** | Pydantic models |
| **Image cache** | In-process LRU cache (SHA1 key, 1hr TTL, 500 entries) |

---

## API Implementation

### Public Pages (HTML via HTMX)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/map` | Interactive map with pet pins |
| GET | `/pets` | Pet listing with filters + pagination |
| GET | `/pets/{pet_id}` | Individual pet detail page |
| GET | `/matches` | Lost/Found match pairs for review |

### Public API (JSON)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check (DB connectivity) |
| GET | `/api/map/geojson` | Pet locations as GeoJSON (bbox-filtered) |
| GET | `/proxy/image` | Proxied pet images with caching |

### Protected (Auth Required)
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/admin` | HTTP Basic | Admin dashboard |
| GET | `/admin/stats-partial` | HTTP Basic | HTMX stats partial |
| GET | `/api/admin/stats` | HTTP Basic | System stats JSON |
| POST | `/api/matches/{match_id}/review` | None* | Confirm/reject a match |

> *Match review currently has no auth — candidate for future protection.

### Data Flow
```
External Sources → Scrapers → Normalizers → Geocoding → DB (upsert) → Matching Engine
                                                                           ↓
Browser ← Jinja2 Templates ← FastAPI ← Repository ← DB (query)
                ↓
          Leaflet.js Map ← GeoJSON API
```

### Auth Patterns
- **Admin**: HTTP Basic Auth with `secrets.compare_digest()` timing-safe comparison
- **User accounts**: HMAC-signed cookie sessions (`HttpOnly`, `SameSite=Lax`, `Secure` in production)
- **CSRF**: Signed, user-bound tokens required for authenticated POST/PUT/PATCH/DELETE
- Production startup rejects missing or default `ADMIN_PASSWORD` and `SESSION_SECRET`

---

## Security Posture

### Implemented
- **HTTP Basic Auth** on admin routes with timing-safe comparison
- **HMAC-signed cookies** for user sessions (`HttpOnly`, `SameSite=Lax`, `Secure` in prod)
- **SQL injection prevention** — SQLAlchemy ORM with parameterized queries, no raw SQL
- **Pydantic input validation** — type-constrained query params, enum validation
- **Image proxy**: domain allowlist (31 known domains), 5MB file size limit, `image/*` content-type validation, in-process LRU cache
- **CSRF**: signed, user-bound tokens on cookie-authenticated mutations
- **Upload validation**: 3 files max, 5MB each, JPEG/PNG/WebP only, container signature verified
- **Same-origin policy**: no CORS headers configured
- **Async DB safety**: SQLAlchemy async sessions with automatic commit/rollback
- **Scraper rate limiting**: 1.5s between requests

### Known Gaps
- Match review endpoint (`POST /api/matches/{match_id}/review`) has no auth
- No rate limiting on public API endpoints besides scraper-level
- APScheduler runs in-process — state lost on restart
- No structured logging (Pino or equivalent)
- In-memory image cache (lost on restart, 500-entry cap)
- No monitoring / error tracking
- No automated backup strategy for PostgreSQL

---

## MVP / Roadmap

### What's Done
- ✅ 5-source pet listing scraper pipeline
- ✅ Normalizer layer with canonical PetRecord
- ✅ Geocoding with multi-provider cascade + DB cache
- ✅ Cross-source deduplicator + lost↔found matcher
- ✅ Interactive Leaflet map with GeoJSON API
- ✅ Pet listing with filters, pagination, detail pages
- ✅ Admin dashboard with stats
- ✅ Image proxy with domain allowlist + cache
- ✅ User accounts (registration, login, sessions, CSRF)
- ✅ Owner self-service (report lost/found, manage listings)
- ✅ Admin moderation (review/approve/reject listings, manage users)
- ✅ Messaging between finders and pet owners
- ✅ Photo uploads with validation

### Short-Term (Next)
- [ ] Auth on match review endpoint
- [ ] Rate limiting on public API endpoints
- [ ] Structured logging (Pino or structlog)
- [ ] Test suite (pytest for scrapers, normalizers, matching, API)
- [ ] PostgreSQL migration automation (Alembic or similar)
- [ ] Email notifications for matches
- [ ] Alert subscriptions (user gets notified when matching pet is found)
- [ ] Staging environment

### Medium-Term
- [ ] Push notifications / SMS alerts
- [ ] Mobile app (React Native or PWA)
- [ ] API rate limiting with Redis-backed store
- [ ] WebSocket for real-time match notifications
- [ ] Sentry/error tracking
- [ ] Automated backup and restore
- [ ] User-submitted photos directly to app (not just source proxy)

### Long-Term
- [ ] Multi-region support (expand beyond Indianapolis)
- [ ] Shelter integration API
- [ ] Volunteer / foster network coordination
- [ ] AI-powered breed/color matching improvements
- [ ] Community features (success stories, lost pet prevention tips)
- [ ] OpenAPI/Swagger documentation