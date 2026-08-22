# K9-Overwatch — Product Roadmap

_Last reviewed: 2026-08-19 · grounded in the current codebase, tests, README, and browser smoke checks._

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

**Owner reports & contact (Phase 4, shipped 2026-08-19)**
- **Report editing** — owners can edit their submitted report fields (name, breed, color,
  location, description, contact info). Location changes trigger automatic re-geocoding.
- **Threaded contact relay** — participants can send replies within a contact request
  conversation, with the status auto-advancing to "in conversation" on first reply.
- **Block user** — any participant can block the other party on a contact request, which
  closes the request and prevents future contact from that person.
- **Flag for moderation** — logged-in users can flag pet reports and contact requests with
  a reason. Flagged content appears in the admin panel for review.
- **Admin moderation panel** (`/admin/reports`) — moderators can view pending flags by
  type, dismiss them, or take action (warn, deactivate report, close contact request).
- **Saved search enable/disable toggle** — users can enable/disable saved searches from
  the account page without deleting them.

**Production readiness (2026-08-19)**
- **Tailwind production build** — migrated from CDN to a locally-built 53KB minified CSS
  artifact. Custom brand/accent/status color theme and shadows preserved.
- **CSP tightened** — Tailwind CDN removed from Content-Security-Policy; `style-src 'self' 'unsafe-inline'`
  for Tailwind utility classes. Leaflet/HTMX CDN sources retained.
- **Accessibility pass** — skip-to-content link, `<main role="main">`, `aria-label` on map
  container, `aria-live="polite"` on filter/results areas, proper `alt` text on pet photos.

**Quality**
- 345 tests pass (328 original + 17 new for contact messages, content reports), 1 skipped;
  Ruff clean; JavaScript syntax check passes; map browser smoke checks cover initialization,
  empty state, filter summary, report-panel open/close, and console cleanliness.
- Two pre-existing UI-killing bugs found and fixed (Starlette TemplateResponse signature,
  conditional `{% extends %}` in list.html).

---

## 2. Remaining gaps (the honest part)

These are things that will quietly hurt the user experience or reliability as the
dataset grows. Listed roughly by impact on "find animals faster."

### A. Critical — matching/UX gaps that block a real reunion
1. **Notification delivery is only an initial email slice.** Owner-submitted lost reports
   can receive instant or daily-digest email alerts with confidence thresholds, opt-out,
   and unsubscribe support. Durable delivery state, retries, SMS, push, and multi-process
   digest storage remain before public launch.
2. **Owner-submitted reports: admin direct edit/deactivate DONE (2026-08-22).** Admins can
   edit or deactivate flagged owner reports directly from `/admin/reports`. Remaining:
   automated abuse detection, rate limiting on flags.
3. **Contact / handoff is now a threaded conversation system** with reply, block, and flag
   controls. Both participants can advance the handoff state (open → in conversation →
   handoff arranged → reunited → closed). Notification delivery for replies remains via
   email — SMS/push not yet built. Admin moderation of flagged contacts is live.

### B. High — data freshness & scale
4. **Re-match is O(n²) and will get slow.** `run_matching_pass(rematch=True)` loads up
   to 120 days of active records (capped at 1000 rows via `get_matchable_records`) and
   compares each against geo-temporal candidates. The cap keeps today's Indy-metro
   scale bounded, but with thousands of records this is the daily job that will
   eventually time out or hammer the DB. Needs spatial indexing (PostGIS `&&` /
   `ST_DWithin`) and/or candidate pre-bucketing before the dataset grows — not urgent yet.
5. **DONE (2026-08-22): `find_match_candidates` now pre-filters by lat/lon bounding box in SQL**
   (`db/repository.py`, Haversine comprehension over the date-window pool). Unlike
   `find_within_radius`, which does have a `lat`/`lon.between()` bounding-box pre-filter,
   the matching-candidate query has none. Same "not urgent at current scale" caveat as
   #4 — move filtering into SQL (or PostGIS `ST_DWithin`) as the same piece of work.
6. **Staleness check only covers ONE source** (IndyLostPetAlert). The other 4 sources
   rely on the source-agnostic age-based expiry job (`expire_stale_listings`, 120-day
   cutoff, runs every 24h) as a backstop rather than a same-day check. Expand
   per-source `check_active()` heuristics, or shorten the age-based cutoff, to close
   the freshness gap between "resolved on the source site" and "expired here."
7. **One-time geocode backfill not run on existing DB.** A periodic `regeocode_pending_records`
   job (every 20 min, source-agnostic) now retries records left uncoordinated by a failed
   geocode. A one-off `geocode_batch.py` run is still worth doing for any pre-existing backlog.

### C. Medium — trust, correctness, polish
8. **DONE (2026-08-22): image proxy cache now TTL'd (7 days) and size-capped (512MB, oldest-first eviction).** `/img` proxies and caches source images,
   content-hashed, capped at 8MB each. The on-disk cache grows unbounded with no TTL or cleanup.
9. **Match counts are not yet fully surfaced in the report-list experience.** The map
   API and marker popups can expose potential-match counts, but the synchronized list
   still needs a dedicated match badge/link treatment.
10. **Feedback loop: labeled data groundwork DONE (2026-08-22).** Match review now stores a
    decision-time snapshot (`decision_snapshot`: confirmed/score/signals/decided_at) that
    survives re-match updates. Remaining: actually re-weight signals from the labels.
11. **Matching is text-only; no visual signal.** Perceptual hash is the lightweight first
    step; CLIP is the heavy step.
12. **Date handling fragility.** Several sources parse dates inconsistently; temporal
    signals in matching can be noisy.
13. **Matching redesign v2 — sparse-record-tolerant scoring DONE (2026-08-22).**
    The lost/found matcher now follows "filter first, rank second, explain always":

    - **Conflict vetoes** (`signals.detect_conflicts`): known-value conflicts
      (gender M≠F, size >1 step apart on S<M<L<XL, primary-color token-set
      contradiction with rapidfuzz near-token tolerance) are detected before
      additive scoring. Default **soft** mode subtracts `VETO_PENALTY=0.45`
      per conflict family from the final score (floored at 0); **strict** mode
      rejects the pair. Missing/"unknown" values never veto.
    - **Informativeness-weighted color** (`matching/color_stats.py`): color
      tokens are IDF-weighted over the whole DB corpus, so "black" counts for
      little while "merle"/"brown patch" count a lot
      (`score_color_match_v2`, overlap normalized to `COLOR_MAX_WEIGHT=0.20`,
      plus a `color_rare_token=0.08` bonus when a shared token appears in <5%
      of records). Falls back to uniform scoring when stats are unavailable;
      `ColorStats` serializes to JSON so a scheduler job can rebuild it.
    - **Corroboration-based confidence** (`MatchResult.from_signals_v2`):
      evidence is grouped into families {circumstance, description, identity,
      narrative, visual}. Identity hits (microchip/phone/name) are high
      outright; otherwise high needs score ≥ 0.65 across ≥ 2 families, medium
      needs ≥ 0.40 in ≥ 1 family (single-family matches need ≥ 2 distinct
      signals), and lone weak evidence lands low with a `needs_review` label.
      Generic circumstance+common-description stacks ("black lab near where/when
      expected") are capped below high as coincidences.
    - Every MatchResult now carries human-readable `reasons`
      (`SIGNAL_REASON_MAP`) and `labels`.
    - The Deduplicator adopts the same soft vetoes and v2 confidence at its own
      thresholds (`DEDUP_V2_THRESHOLDS = (0.55, 0.75)`).

    Tunables: `VETO_PENALTY`, `veto_mode`, `veto_penalty`, `color_max_weight`,
    `RARE_TOKEN_FRACTION`, `V2_HIGH_SCORE=0.65`, `V2_MEDIUM_SCORE=0.40`,
    `COINCIDENCE_MAX_GENERIC_DESC_SIGNALS=2`.

### D. Low / hygiene
14. **Rate limiting covers auth + report only.** Contact requests, flagging, and other
    mutation endpoints are unguarded, and the limiter is in-process only (needs a shared
    store for multi-worker).
15. **Docs DONE (2026-08-22):** `docs/dev-scripts.md` documents both scripts; docstrings
    cover usage inline. Scripts remain dev-only by design.
15. **Tailwind CDN → local build DONE (2026-08-19).** CSP tightened for production.
16. **Accessibility initial pass DONE (2026-08-19).** Skip-to-content, aria roles, labels,
    and live regions added. Remaining: full keyboard navigation audit, screen-reader testing,
    color-contrast verification on custom status colors.

---

## 3. Nice-to-have (Phase 4 and beyond)

- **Email / SMS / push alerts for new matches** — the killer feature for the mission.
- **Visual-similarity matching** (perceptual hash → CLIP) as a matching signal.
- **Adoption listings integration** (Petfinder official API) — broaden "found" surface.
- **More sources**: Petco Love Lost (facial recognition), Finding Rover, local municipal
  shelters (many run PetHarbor = same backend as 24petconnect).
- **Mobile-friendly "report a lost pet" flow** (photo-first, 3 taps) for owners in panic.
- **Public gallery of "recently reunited"** to build trust and encourage reporting.
- **Multi-region search** (currently hardcoded to Indianapolis metro via env vars).

---

## 4. Backlog

| Item | Status | Why it's backlogged |
|---|---|---|
| User-submitted lost/found reports | Complete | Editing, report status lifecycle, moderation flagging, admin panel all shipped |
| Match notifications (email/SMS/push) | Email slice shipped | Instant/daily digest, confidence threshold, opt-out, unsubscribe; durable delivery, SMS, and push remain |
| Threaded contact relay | Complete | Reply, block, flag, admin moderation all shipped |
| Map/report synchronized discovery | Shipped initial slice | Match badges and mobile bottom sheet remain |
| Image proxy + cache | Shipped (bug fixed) | Cache TTL/eviction still unbounded — hygiene, not correctness |
| Re-geocode backstop for failed geocodes | Shipped | Periodic job; one-off `geocode_batch.py` run for pre-existing backlog |
| Auth/report rate limiting | Shipped | In-process only; broader route coverage + shared store remain. Flags/replies/status/block rate-limited 2026-08-22 (`7d2fc48`) |
| Production Tailwind build + CSP | Complete (2026-08-19) | Local 53KB minified output.css, CSP tightened |
| Accessibility pass | Initial pass complete (2026-08-19) | Skip-to-content, aria roles, live regions; full keyboard/screen-reader audit remains |
| Visual similarity signal | Groundwork shipped (2026-08-22) | Opt-in pure-Python dHash provider behind `VISUAL_SIMILARITY_ENABLED` (default off); `visual_embeddings` cache table; Pillow as optional `[visual]` extra (`a20cfbc`). CLIP remains the heavy future step |
| Public Recently-Reunited gallery | Shipped (2026-08-22) | `GET /reunited` shows only owner-marked user-submitted reports + empty state; `user_reunifications` added to `/api/stats` (`635932c`) |
| Additional sources (Petfinder etc.) | Listed | Scoping/API keys |
| PostGIS spatial index for matching | Not started | Needs prod DB + query rewrite |
| Match feedback → signal re-weighting | Not started | Needs labeled outcomes |

---

## 5. Recommended sequencing

**Now (highest ROI, low risk):**
1. Add match badges and direct match links to synchronized map report cards. (hours)
2. Run `geocode_batch.py` on the existing DB — unlocks currently-invisible matches. (hours)
3. Expand per-source staleness/inactive logic beyond IndyLostPetAlert. (days)

**Next (the reunion gap):**
4. Harden match notifications with durable delivery tracking, retries, and provider isolation.
5. Surface + populate contact info so a match is actionable.

**Then (scale + precision):**
6. Move candidate filtering into SQL / add PostGIS; make re-match sub-linear.
7. Visual-similarity signal (perceptual hash first).
8. Feedback loop to re-weight signals and cut false positives.

**Before public launch:**
9. Full accessibility audit (keyboard, screen reader, contrast).
10. Abuse guard hardening (flag rate limits, auto-moderation).
11. More sources + multi-region.

---

## 6. Definition of done for "good experience"

A user can: (a) post or find their pet in < 3 taps, (b) see clustered, recency-colored
results without clutter, (c) get a match **pushed to them**, not discovered by luck,
(d) reach the finder/shelter directly, and (e) trust the result because low-confidence
matches are clearly labeled and false positives shrink over time.

Today we deliver (a) partially, (b) yes, (c) **email for eligible owner-submitted lost reports**, (d) **via threaded contact relay with block/flag controls**, (e) partially.
That gap — between "we computed a match" and "the owner knows and can act" — is the
roadmap's center of gravity.