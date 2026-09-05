# Location Precision Audit — 2026-08-22

Live-fetched sample per scraped source (no DB writes). Location
precision classified from `location_text` shape: full street address >
intersection > city-only / zip-only (geocode to city/ZIP-center level)
> missing. BLOCKED sources are marked honestly.

| Source | Status | Sampled | full addr | intersection | city-only | zip-only | missing | coarse% |
|---|---|---|---|---|---|---|---|---|
| indylostpetalert | OK | 40 | 8% | 78% | 15% | 0% | 0% | 15% |
| 24petconnect | OK | 40 | 12% | 15% | 12% | 0% | 60% | 12% |
| petfinder | ERROR (RuntimeError: PETFINDER_API_KEY and PETFINDER_API_SECRET mus) | 0 | — | — | — | — | — | — |
| pawboost | OK | 20 | 0% | 50% | 50% | 0% | 0% | 50% |
| petfbi | OK | 5 | 0% | 40% | 60% | 0% | 0% | 60% |
| lostmydoggie | OK | 20 | 0% | 0% | 100% | 0% | 0% | 100% |

## Map-accuracy offenders

- **pawboost**: 10/20 sampled records (50%) carry only city- or ZIP-level location text → their pins land on city/ZIP centroids. These records are display-fuzzed on the map (see `src/k9overwatch/geocoding/display_fuzz.py`) and flagged with the "ZIP code area" badge.
- **lostmydoggie**: 20/20 sampled records (100%) carry only city- or ZIP-level location text → their pins land on city/ZIP centroids. These records are display-fuzzed on the map (see `src/k9overwatch/geocoding/display_fuzz.py`) and flagged with the "ZIP code area" badge.

**Verdict:** coarse% = city-only + zip-only share of the sample.
Sources ≥50% coarse (with n≥10) systematically produce city-center-level
geocodes.
