# K9-Overwatch — Product Roadmap

_Last reviewed: 2026-07-18 · grounded in a full read of the codebase (src + templates + tests + README), not a generic template._

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
- **"See similar photos" → Google Lens** reverse image search on every photo (no ML dependency).
- Admin dashboard: scraper health, match stats, ungeocoded counts.
- CI (GitHub Actions ruff + pytest) + Dependabot.

**Quality**
- 210 tests pass; ruff clean; live smoke test (opt-in) proves scrape→bucket ingestion.
- Two pre-existing UI-killing bugs found and fixed (Starlette TemplateResponse signature,
  conditional `{% extends %}` in list.html).

---

## 2. Design flaws & gaps we've accumulated (the honest part)

These are things that will quietly hurt the user experience or reliability as the
dataset grows. Listed roughly by impact on "find animals faster."

### A. Critical — matching/UX gaps that block a real reunion
1. **Matches are computed but never delivered.** There is NO notification path —
   no email, no SMS, no push, no saved-search alert. A `PetMatch` exists in the DB,
   the detail page shows it, but an owner only sees it if they happen to visit their
   pet's page. For a worried owner, "we found a match but didn't tell you" is a miss.
   _This is the single biggest gap between the engine and the mission._
2. **No owner-submitted reports.** Every record comes from shelters/aggregators.
   There is no way for an owner (or a good samaritan who found a dog) to _post_ a
   lost/found notice themselves. That cuts the dataset and the reunion surface in half.
3. **No contact / handoff mechanism.** Detail pages show "source attribution" but no
   direct path to reach the finder/shelter. `other.contact_info` exists on the model
   but is not surfaced or even populated by scrapers. A match that can't be acted on
   isn't a reunion.
4. **No user accounts / saved searches.** Can't watch a specific pet or area. Phase 4
   item, but it's foundational for notifications (#1) and for repeat visitors.

### B. High — data freshness & scale
5. **Re-match is O(n²) and will get slow.** `run_matching_pass(rematch=True)` loads up
   to 120 days of active records and compares each against geo-temporal candidates.
   With thousands of records this is the daily-job that will eventually time out or
   hammer the DB. Needs spatial indexing (PostGIS `&&` / `ST_DWithin`) and/or candidate
   pre-bucketing before the dataset grows.
6. **`find_match_candidates` likely does geo filtering in Python, not SQL.** If candidate
   selection isn't done with a bounding-box / spatial index at the DB layer, the matching
   pass reads far more rows than it should. Verify and move filtering into SQL.
7. **Staleness check only covers ONE source** (IndyLostPetAlert). The other 4 sources can
   hold onto resolved/found pets forever, cluttering the map and the match pool. The
   README's own note: "Only runs against IndyLostPetAlert." Expand or add per-source
   active-window heuristics.
8. **`batch geocode` never run on the existing DB** (README still has it unchecked).
   Records with no coordinates can't match geographically and don't appear on the map.
   This directly reduces match recall.

### C. Medium — trust, correctness, polish
9. **No image proxy / cache** (README unchecked). Large source images (IndyLostPetAlert)
   load slowly or get blocked (we saw this in testing — thumbnail didn't render in the
   sandbox). A proxy that resizes + caches would speed up cards, popups, and the detail page.
10. **`match_count` on map pins is hardcoded to 0** (`Could query matching table for this
    later`). The recency bar and buckets are great, but a pin can't show "3 possible
    matches" yet. Cheap win.
11. **No confidence calibration / feedback loop.** We store human `confirmed`/`rejected`
    but never USE rejections to tune signal weights. A learning loop (re-weight signals by
    accepted/rejected outcomes) would steadily cut false positives — the user's original
    complaint.
12. **Matching is text-only; no visual signal.** Already deferred (Phase 4 / D1). "Brown
    mutt" vs "tan terrier" same-dog listings with mismatched text won't match. Perceptual
    hash is the lightweight first step (no torch); CLIP is the heavy step.
13. **No search-by-text across descriptions / breeds** on the pet directory beyond filters.
    A simple "describe your dog" free-text search would help owners who don't know breed names.
14. **Date handling fragility.** `days_since_event` bucketing gracefully falls back when
    `date_event` is missing (good), but several sources parse dates inconsistently; the
    temporal signals in matching can be noisy. Worth a normalization pass + tests.

### D. Low / hygiene
15. **Tailwind via CDN** ("for now") — fine for dev, but no production build, no CSP,
    slower first paint. Move to a built asset before public launch.
16. **No rate-limit / abuse guard on the web app** (no auth on any route). Acceptable while
    internal, risky if public.
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
| User-submitted lost/found reports | Not started | Needs accounts + moderation |
| Match notifications (email/SMS/push) | Not started | Needs accounts + provider |
| Image proxy + cache | Planned, unchecked | Perf, not correctness |
| Batch geocode existing DB | Planned, unchecked | One-off script exists, not run |
| Visual similarity signal | Deferred (D1) | New dependency (imagehash/CLIP) |
| Additional sources (Petfinder etc.) | Listed | Scoping/API keys |
| PostGIS spatial index for matching | Not started | Needs prod DB + query rewrite |
| Match feedback → signal re-weighting | Not started | Needs labeled outcomes |
| Accessibility pass | Not started | Polish before public launch |
| Production Tailwind build + CSP | Not started | Launch hygiene |

---

## 5. Recommended sequencing (to maximize "find animals faster" per unit effort)

**Now (highest ROI, low risk):**
1. Run `geocode_batch.py` on the existing DB — unlocks currently-invisible matches. (hours)
2. Populate + show `match_count` on pins. (hours)
3. Expand staleness/inactive logic beyond IndyLostPetAlert. (days)
4. Add an image proxy. (days) — faster loads = owners browse more.

**Next (the reunion gap):**
5. Owner-submitted reports + minimal accounts. (the big one)
6. Match notifications (start with email) — closes flaw #1.
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

Today we deliver (a) partially, (b) yes, (c) **no**, (d) **no**, (e) partially.
That gap — between "we computed a match" and "the owner knows and can act" — is the
roadmap's center of gravity.
