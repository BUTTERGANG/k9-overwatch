# K9-Overwatch — Product Roadmap

_Last reviewed: 2026-08-18 · grounded in the current codebase, tests, README, and browser smoke checks._

The mission is simple and emotionally loaded: **help a stressed, often non-technical
person find their lost animal faster.** Every item below is scored against that mission.
The core engine is strong; the gaps are around the things a real owner actually needs
once a match exists (notification, contact, trust) and around keeping the data fresh.

---

## 1. What we HAVE today (shipped)

**Data pipeline (Phase 1–2, solid)**
- 5 live sources scraped: IndyLostPetAlert (WP REST), 24petconnect (HTML POST),
  PawBoost + Pet FBI (Playwright + stealth), Lost My Doggie (Playwright + stealth).
- Unified `PetRecord` schema (Pydantic v2) + per-source normalizers.
- Incremental polling via high-water marks; per-source state + consecutive-error alerts.
- Geocoding cascade: Google → Nominatim → ZIP-centroid fallback.

**Storage & matching (Phase 2, strong)**
- SQLAlchemy ORM, SQLite dev / Postgres+PostGIS target. Idempotent upsert by `source`+`source_id`.
- Signal-weighted matching engine: geo, zip, breed, color, gender, size, name, microchip,
  description overlap, distinctive features.
- **Lost→Found reunification in BOTH directions** (new found reports surface old lost pets).
- **Daily re-match pass** (idempotent upsert — scores improve as geocoding/data fills in;
  preserves human-rejected matches).
- Cross-source dedup so the same pet isn't 5 dots on the map.

**Application (Phase 3, working)**
- FastAPI REST: map / pets / matches / admin.
- Leaflet map with **marker clustering** (de-cluttered), recency-colored pins, recency rings.
- **Recency buckets** (≤7d / 8–14d / 15–30d / >30d) with a plain-language summary bar
  + `/api/map/buckets` endpoint (robust even when `date_event` is missing).
- Pet directory (HTMX filters) + detail pages with source attribution.
- Map UX includes an actionable empty state, active-filter summary, clear-all recovery,
  prominent report CTA, and a synchronized report-list panel. List cards can focus the
  corresponding map marker and open its popup; potential-match badges link to the match
  review page; the list is also available as a map-free accessible alternative.
- **"See similar photos" → Google Lens** reverse image search on every photo (no ML dependency).
- **Image proxy with cache** (`/img`) — content-hashed cache keys, 8MB size cap.
- **Per-IP rate limiting** on login/register/password-reset/report (fixed-window, in-process).
- Admin dashboard: scraper health, match stats, ungeocoded counts.
- CI (GitHub Actions ruff + pytest) + Dependabot.

**Quality**
- 260 tests pass, 1 skipped; Ruff clean; JavaScript syntax check passes; map browser smoke
  checks cover initialization, empty state, filter summary, report-panel open/close, and
  console cleanliness. Live scrape smoke remains opt-in.
- Two pre-existing UI-killing bugs found and fixed (Starlette TemplateResponse signature,
  conditional `{% extends %}` in list.html).

---

## 2. Design flaws & gaps we've accumulated (the honest part)

These are things that will quietly hurt the user experience or reliability as the
dataset grows. Listed roughly by impact on "find animals faster."

### A. Critical — matching/UX gaps that block a real reunion
1. **Notification delivery is only an initial email slice.** Owner-submitted lost reports
   can receive instant or daily-digest email alerts with confidence thresholds, opt-out,
   and unsubscribe support. Durable delivery state, retries, SMS, push, and multi-process
   digest storage remain open before public launch.
2. **Owner-submitted reports exist, but the workflow is incomplete.** Authenticated users
   can post lost/found/sighting reports with photos and geocoded locations. Owners can now
   mark their reports resolved, reunited, or closed; moderation, editing, and abuse controls remain.
3. **Contact / handoff is an initial relay slice, not a complete conversation system.**
   Authenticated users can send a privacy-preserving message to an owner-submitted
   report, owners see the request in their account inbox, eligible owners receive an
   email notification, and either participant can advance the request through open,
   conversation, handoff-arranged, reunited, and closed states. Full two-way threaded
   messaging, block/report controls, durable notification delivery, and moderation
   remain before public launch.
4. **No saved searches or watch areas.** Accounts exist for submitted reports and alert
   preferences, but users cannot yet watch a specific pet, area, or search query.

### B. High — data freshness & scale
5. **Re-match is O(n²) and will get slow.** `run_matching_pass(rematch=True)` loads up
   to 120 days of active records (capped at 1000 rows via `get_matchable_records`) and
   compares each against geo-temporal candidates. The cap keeps today's Indy-metro
   scale bounded, but with thousands of records this is the daily job that will
   eventually time out or hammer the DB. Needs spatial indexing (PostGIS `&&` /
   `ST_DWithin`) and/or candidate pre-bucketing before the dataset grows — not urgent yet.
6. **Confirmed: `find_match_candidates` does geo filtering in Python, not SQL**
   (`db/repository.py`, Haversine comprehension over the date-window pool). Unlike
   `find_within_radius`, which does have a `lat`/`lon.between()` bounding-box pre-filter,
   the matching-candidate query has none. Same "not urgent at current scale" caveat as
   #5 — move filtering into SQL (or PostGIS `ST_DWithin`) as the same piece of work.
7. **Staleness check only covers ONE source** (IndyLostPetAlert). The other 4 sources
   rely on the source-agnostic age-based expiry job (`expire_stale_listings`, 120-day
   cutoff, runs every 24h) as a backstop rather than a same-day check. Expand
   per-source `check_active()` heuristics, or shorten the age-based cutoff, to close
   the freshness gap between "resolved on the source site" and "expired here."
8. **`batch geocode` never run on the existing DB** (README still has it unchecked).
   Records with no coordinates can't match geographically and don't appear on the map.
   A periodic `regeocode_pending_records` job (every 20 min, source-agnostic) now
   retries records left uncoordinated by a failed geocode — this covers the *ongoing*
   leak, but a one-time `geocode_batch.py` run is still worth doing for any pre-existing
   backlog in a live database.

### C. Medium — trust, correctness, polish
9. **Image proxy shipped, cache has no TTL/eviction.** `/img` (`web/routers/images.py`)
   proxies and caches source images, content-hashed, capped at 8MB each. The proxy
   itself was broken until 2026-08-18 (returned an unconsumed `aiohttp` `StreamReader`
   instead of bytes — every uncached image 500'd); that's fixed. Remaining gap is
   hygiene, not correctness: the on-disk cache grows unbounded with no TTL or cleanup.
10. **Match counts are not yet fully surfaced in the report-list experience.** The map
    API and marker popups can expose potential-match counts, but the synchronized list
    still needs a dedicated match badge/link treatment so users can scan likely reunions
    quickly.
11. **No confidence calibration / feedback loop.** We store human `confirmed`/`rejected`
    but never USE rejections to tune signal weights. A learning loop (re-weight signals by
    accepted/rejected outcomes) would steadily cut false positives — the user's original
    complaint.
12. **Matching is text-only; no visual signal.** Already deferred (Phase 4 / D1). "Brown
    mutt" vs "tan terrier" same-dog listings with mismatched text won't match. Perceptual
    hash is the lightweight first step (no torch); CLIP is the heavy step.
13. **Text search is now available** on the pet directory across names, breeds, colors,
    descriptions, distinctive features, and location fields. It is intentionally a simple
    word-based SQL search, not a relevance-ranked search.
14. **Date handling fragility.** `days_since_event` bucketing gracefully falls back when
    `date_event` is missing (good), but several sources parse dates inconsistently; the
    temporal signals in matching can be noisy. Worth a normalization pass + tests.

### D. Low / hygiene
15. **Tailwind via CDN** ("for now") — fine for dev, but no production build, no CSP,
    slower first paint. Move to a built asset before public launch.
16. **Rate limiting covers auth + report only.** `web/rate_limit.py` (in-process,
    per-IP, fixed-window) now guards login/register/password-reset/report. The rest
    of the app — map/pets/matches reads, contact requests — is still unguarded, and
    the limiter is in-process only (fine for the current single-worker deployment;
    needs a shared store — e.g. Redis — if this ever runs multi-worker/multi-replica).
17. **`scripts/scrape_one.py` and `geocode_batch.py` are dev-only** and lack docs; onboarding
    a contributor means reverse-engineering them.
18. **No accessibility pass** — map markers, color-only recency encoding, and the Lens link
    need keyboard/contrast/screen-reader checks for the non-tech users we care about.

### E. Things we said we'd "look at" and should close out
- Commit + push the 4 commits currently only local (re-match, CI, map-UX, lint fix).
- Confirm version pins (`starlette>=0.37`) hold on the Replit deploy (no lockfile there).
- The live smoke test is opt-in (`RUN_LIVE_SMOKE=1`); consider a recorded/offline fixture
  so CI guards real ingestion shape without network.

---

## 3. Nice-to-have (Phase 4 and beyond)

- **User accounts + saved searches + watch areas** (foundation for everything below).
- **Email / SMS / push alerts for new matches** — the killer feature for the mission.
- **Visual-similarity matching** (perceptual hash → CLIP) as a matching signal.
- **Adoption listings integration** (Petfinder official API) — broaden "found" surface.
- **More sources**: Petco Love Lost (facial recognition), Finding Rover, local municipal
  shelters (many run PetHarbor = same backend as 24petconnect).
- **Mobile-friendly "report a lost pet" flow** (photo-first, 3 taps) for owners in panic.
- **Public gallery of "recently reunited"** to build trust and encourage reporting.
- **Multi-region search** (currently hardcoded to Indianapolis metro via env vars).

---

## 4. Backlog (not yet started / explicitly deferred)

| Item | Status | Why it's backlogged |
|---|---|---|
| User-submitted lost/found reports | Owner lifecycle slice shipped | Authenticated reports, photos, geocoding, immediate matching, and owner resolution/reunited/closed states; moderation/editing/abuse controls remain |
| Match notifications (email/SMS/push) | Email slice shipped | Instant/daily digest, confidence threshold, opt-out, unsubscribe; durable delivery, SMS, and push remain |
| Map/report synchronized discovery | Shipped initial slice | Empty-state recovery, filter summary, report panel, and card-to-marker focus are live; match badges and mobile bottom sheet remain |
| Image proxy + cache | Shipped (bug fixed 2026-08-18) | Cache TTL/eviction still unbounded — hygiene, not correctness |
| Re-geocode backstop for failed geocodes | Shipped 2026-08-18 | Periodic job; one-off `geocode_batch.py` run still worth doing for a pre-existing backlog |
| Auth/report rate limiting | Shipped 2026-08-18 | In-process only; broader route coverage + shared store remain |
| Visual similarity signal | Deferred (D1) | New dependency (imagehash/CLIP) |
| Additional sources (Petfinder etc.) | Listed | Scoping/API keys |
| PostGIS spatial index for matching | Not started | Needs prod DB + query rewrite |
| Match feedback → signal re-weighting | Not started | Needs labeled outcomes |
| Accessibility pass | Not started | Polish before public launch |
| Production Tailwind build + CSP | Not started | Launch hygiene |

---

## 5. Recommended sequencing (to maximize "find animals faster" per unit effort)

**Now (highest ROI, low risk):**
1. Add match badges and direct match links to synchronized map report cards. (hours)
2. Run `geocode_batch.py` on the existing DB — unlocks currently-invisible matches
   left over from before the re-geocode backstop shipped. (hours)
3. Expand per-source staleness/inactive logic beyond IndyLostPetAlert, so resolved
   listings on the other 4 sources don't wait out the 120-day age-based backstop. (days)

**Next (the reunion gap):**
5. Complete owner reports with moderation, editing, and resolution states.
6. Harden match notifications with durable delivery tracking, retries, and provider isolation.
7. Surface + populate contact info so a match is actionable.

**Then (scale + precision):**
8. Move candidate filtering into SQL / add PostGIS; make re-match sub-linear.
9. Visual-similarity signal (perceptual hash first).
10. Feedback loop to re-weight signals and cut false positives.

**Before public launch:**
11. Production Tailwind build + CSP, accessibility pass, abuse guards.
12. More sources + multi-region.

---

## 6. Definition of done for "good experience"

A user can: (a) post or find their pet in < 3 taps, (b) see clustered, recency-colored
results without clutter, (c) get a match **pushed to them**, not discovered by luck,
(d) reach the finder/shelter directly, and (e) trust the result because low-confidence
matches are clearly labeled and false positives shrink over time.

Today we deliver (a) partially, (b) yes, (c) **email for eligible owner-submitted lost reports**, (d) **no**, (e) partially.
That gap — between "we computed a match" and "the owner knows and can act" — is the
roadmap's center of gravity.
