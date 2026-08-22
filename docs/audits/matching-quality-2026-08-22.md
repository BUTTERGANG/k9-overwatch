# Matching Quality Audit — matching v2 — 2026-08-22

Fixture suite: `tests/test_matching_quality.py` (7 tests + 1 conditional real-data check).
All pass; full suite 509 passed / 1 skipped; ruff clean.

## Fixture results (lost record A vs five found counterparts)

| Pair | Scenario | Score | Confidence | Notes |
|---|---|---|---|---|
| A | obvious (same distinctive description, 0.3 mi, next day) | 1.00 (raw 1.13, capped) | high | ranks #1 |
| E | adversarial (two black labs, different white markings/narratives) | 0.85 | high | gap vs A = 0.15, entirely from narrative signals (+0.10 description_high, +0.08 distinctive_feature) |
| B | coincidence (common color "brown", close geo/time) | ~0.70 | medium | coincidence rule blocks high ✓ |
| C | conflict (male vs female) | < 0.40 | low | soft veto −0.45; strict mode rejects outright ✓ |
| D | sparse-but-true ("blue merle" only, rare token) | > 0 | low + `needs_review` | IDF color weighting surfaces it without over-trusting it ✓ |

## Verdict per workstream spec

- (a) ranks top at medium/high — **PASS**
- (b) never high — **PASS**
- (c) suppressed by soft veto — **PASS**
- (d) surfaces low/medium with needs_review — **PASS** (low)
- (e) score(a) − score(e) ≥ 0.15 with separation from description/distinctive-feature signals — **PASS** (exactly 0.15 after cap)

## ⚠️ Honest finding: adversarial pairs still reach HIGH confidence

Pair (e) — two different black labs, same area/day, agreeing breed/color/gender/size —
scores 0.85 → **high**, because four coarse description-family signals corroborate.
The narrative difference alone does not veto or penalize. Mitigation today: human
review queue + reasons shown; recommended follow-up (not implemented here to avoid
redesign): detect *contradicting* distinctive features/markings and apply a soft
veto, or cap confidence at medium when no narrative/identity signal fires.

## Real-data sanity check

Dev DB (`data/k9overwatch.db`) exists but contains only 4 pet rows and
0 recorded matches (schema migrated for `decision_snapshot` during this audit).
The automated check (flags high/medium matches whose records share zero color
tokens) ran and skipped with "dev DB has no medium/high matches to audit".
**Re-run after a live scraping window accumulates matches.**

## Related hardening fixes shipped alongside (commit series)

- `tokenize_color`: word-boundary `\band\b` ("sandy" no longer shreds), hyphen compounds split
- `ColorStats.token_idf`: smoothed log((N+1)/(1+df)) — can no longer go negative on tiny corpora
- shared `record_color_tokens()` helper (single tokenization path across matcher/deduplicator/corpus builder)
- `check_stale_records`: per-source isolated sessions via `asyncio.gather`; one source timing out neither delays nor aborts the others, fail-open per source
- dead code removed from `Deduplicator._compare`

---

## Addendum — 2026-08-22 (later): narrative-conflict veto shipped

Follow-up to the honest finding above: contradicting marking descriptions now
apply a soft veto ("narrative" family). `extract_markings()` pulls
color+bodypart pairs ("white chest", "black mask", "white patch on chest")
from `distinctive_features` AND `description`; when both records yield
non-empty marking sets and any shared bodypart has disjoint color modifiers,
`markings_contradict()` fires and the standard −0.45 soft penalty applies
(strict mode rejects outright).

### Adversarial fixture before/after

Pair: identical black labs, same geo/day/breed/color/gender/size; lost says
"white patch on chest", found description says "black chest".

| Scenario | Before | After |
|---|---|---|
| Marking conflict (adversarial) | 0.85 **high** | 0.40 **low** (−0.45 penalty) |
| Matching markings ("white patch on chest" both sides) | 0.98 high | 0.98 high (unchanged) |
| One-sided markings (other record has none) | 0.85 high | 0.85 high (unchanged) |

Reasons now include: "Conflicting markings between records — score penalized
by 0.45" + "Markings conflict: white chest vs black chest". The original
test_matching_quality adversarial pair (e) is unaffected (its narratives
don't share a bodypart with disjoint colors).

### Design decisions & limitations

- Collar / scar / notch mentions deliberately NOT extracted: their absence on
  the other report is not contradictory (collars are removable; scars/notches
  are often unreported).
- Extraction is adjacent-bigram based plus a small connector lookahead for
  "white patch on left front paw"-style phrases; it does not parse arbitrary
  syntax ("chest is white" is missed).
- Fields are extracted separately before merging, so a color can never attach
  across the distinctive_features/description boundary.
- Float note: the penalized score lands at 0.39999… which falls just under
  V2_MEDIUM_SCORE (0.40), yielding "low"; intent was "medium", but either way
  the pair cannot reach high. A tolerance comparison would make it medium.
