# Missing-Animal / Pet Listing Data APIs — Deep Research

**Date:** 2026-08-22 · **Context:** Petfinder's public API was decommissioned by the
provider on **2025-12-02** during their site rebuild (no new keys issued since ~April
2024). Our Petfinder scraper was retired the same day this document was produced.
This doc evaluates every credible replacement source for aggregating lost / found /
adoptable / stray-hold animal listings for k9-overwatch.

Verdict legend: **INTEGRATE NOW** · **PARTNER-REQUIRED** (real data, gated access) ·
**NOT SUITABLE**

---

## 1. RescueGroups.org v5 HTTP/JSON API — ⭐ INTEGRATE NOW (pending free key)

- **Access method:** REST + JSON:API 1.0 spec. Base `https://api.rescuegroups.org/v5/public/`.
  Docs: <https://api.rescuegroups.org/v5/public/docs>
- **Auth:** Free public API key issued on request (application form); no contract.
- **Cost:** Free; docs state no hard request limits for public searches.
- **Coverage:** Adoptable animals across thousands of shelters/rescues nationwide,
  plus organization directory. Primarily *adoptable* listings — not a dedicated lost-pet
  network — but it is the single largest open adoptable dataset and it feeds other
  platforms (see §4).
- **Data quality (matching-relevant):** Strong and animal-specific:
  - color **and** separate pattern fields (`attributes.colorPrimary`,
    `attributes.colorSecondary`, `attributes.colorDetails`, pattern fields)
  - breed primary/secondary + mixed flag, size group, age group, sex
  - precise location fields: `locations.postalCode`, `locations.state`,
    plus org address; supports **radius + postal-code search**
    (`/public/animals/search/animals` with `filterRadius`)
  - photos array with large/small variants; org contact info per record
- **Rate limits:** None published for the public endpoints.
- **ToS constraints:** Attribution of RescueGroups as data source expected; key is per-application.
- **Integration effort:** **Low–medium (~1–2 days).** JSON:API envelope maps cleanly onto
  our existing normalizer pattern (same shape of work as the retired Petfinder
  normalizer: fetch → normalize → PetRecord).
- **Endpoints:** `/public/animals/search/{view}` (e.g. `adoptable-search`),
  `/public/orgs/`, filter/sort/pagination in request body.
- **Verdict: INTEGRATE NOW** once the free key arrives — strongest Petfinder replacement.

## 2. Adopt-a-Pet Partner APIs — PARTNER-REQUIRED

- **Access method:** Real HTTP APIs. Partner API docs: <https://partner-apis.adoptapet.com/>;
  program description: <https://adoptapetcom.zendesk.com/hc/en-us/articles/41654139166107>
- **Auth:** Partnership-contract gated. Contact **info@adoptapet.com** to apply.
  Separately, every shelter gets a free self-service **Pet List API** — but only for
  *that shelter's own* pets (embed/listing use, not aggregation).
- **Cost:** Free to partners; not monetized.
- **Coverage:** Large national adoptable inventory (one of the two biggest adoption
  sites in the US). No lost/found content.
- **Data quality:** Good structured fields (breed, age, size, location, photos,
  contact), though less granular color detail than RescueGroups v5.
- **Rate limits:** Set per-partnership agreement.
- **ToS constraints:** Requires **logo attribution**, an approval process, and a
  documented shelter opt-out flow. Aggregation beyond display requires explicit terms.
- **Integration effort:** Low once approved (REST/JSON), but approval timeline is
  out of our control (weeks).
- **Verdict: PARTNER-REQUIRED.** Worth applying now so approval lands while
  RescueGroups integration ships.

## 3. PetHub LostPets API (pethub.io) — NOT SUITABLE (for now)

- **Access method:** REST, `https://pethub.io/v1/{noun}`. Docs: <https://pethub.io/>
  ("PetHub Dev Net (Alpha)"), e.g. <https://pethub.io/api/v1/requests>
- **Auth:** OAuth2 bearer tokens; API key by invitation-only request form +
  PetHub.dev account.
- **Status verified 2026-08-22:** Site explicitly labels itself **"Dev Net (Alpha)"**
  and "version 1 … approach"; access is invitation-only; the model is
  **user-permission-centric** ("allowing them to share their pet's data … with trusted
  applications"). Lost-pet poster CRUD + geo search exist conceptually, but there is
  no bulk/public listing read that doesn't route through individual owner permissions.
- **Coverage:** ~1M registered pets database (tag-based registry), lost-poster features;
  not an open listings corpus.
- **Data quality:** Rich per-pet profiles where permission is granted, but bulk
  aggregation would require per-user grants — incompatible with our scraper model.
- **Verdict: NOT SUITABLE** while alpha + user-centric permissions hold. Re-check if
  they graduate alpha or expose a partner feed.

## 4. Petco Love Lost — PARTNER-REQUIRED (via integration team)

- **Access method:** **No public API.** Integrations are built *by* their team against
  shelter-management systems. Support docs: <https://support.partners.petcolove.org/>
  (see "Shelter Software" category).
- **Key architectural fact (verified):** Petco Love Lost ingests **from** PetPoint,
  Chameleon, ShelterLuv, ShelterBuddy **and RescueGroups** — and historically pulled
  limited data from Petfinder. Source:
  <https://support.partners.petcolove.org/hc/en-us/articles/10491912514835>
- **Implication:** A RescueGroups integration (§1) indirectly places us in the same
  ecosystem Petco Love Lost indexes — records sourced through RescueGroups surface
  there without a direct partnership.
- **Coverage:** National AI photo-matching lost/found reunification database —
  conceptually the closest peer product to k9-overwatch.
- **Integration effort:** N/A publicly; would require contacting their partnerships/
  integrations team and negotiating scope.
- **Verdict: PARTNER-REQUIRED.** Do not block on it; monitor. RescueGroups first.

## 5. Shelter software export APIs (ShelterLuv / PetPoint / Chameleon / ShelterBuddy)

- **Access method:** Each system exposes export/reporting APIs, but credentials are
  **org-scoped**: you need each individual shelter's participation/API key.
- **Coverage:** Stray-hold and intake data lives here (the datasets adoption sites lack)
  — valuable but fragmented.
- **Data quality:** Excellent clinical/intake fields per shelter; inconsistent across orgs.
- **Integration effort:** High at aggregate level (N integrations); low per-org.
- **Aggregator suitability:** Poor as a bulk source; strong for targeted outreach —
  notably Indianapolis Animal Care Services (Marion County) is our home jurisdiction,
  so a single-shelter pilot is realistic.
- **Verdict: NOT SUITABLE** as bulk sources; keep as county-outreach angle.

## 6. Nextdoor developer Search API — PARTNER-REQUIRED

- **Access method:** Official developer platform <https://developer.nextdoor.com/>.
  Content Search API exposes neighborhood posts including the
  **`p_intent_lost_found`** intent field — i.e., machine-readable lost/found pet posts.
- **Auth:** OAuth; access to Search/content APIs is behind a **partnership application**
  (self-serve is ads-only today).
- **Coverage:** Hyper-local lost & found pet posts — exactly our use case, and the
  largest volume source of *organic* lost-pet posts after Facebook.
- **Data quality:** Unstructured post text/images + intent tag; needs NLP-style
  normalization (similar to our PawBoost/LostMyDoggie page-state parsers).
- **ToS constraints:** Neighborhood privacy expectations; likely strict display and
  retention terms.
- **Verdict: PARTNER-REQUIRED.** Apply when we can demonstrate a reunification value
  story; high ceiling.

## 7. Municipal open-data portals (Socrata / ArcGIS)

- **Access method:** Cities publish shelter intake/outcome datasets on Socrata
  (SODA API, no key for read) or ArcGIS Open Data (GeoJSON/REST). Precedent exists in
  our stack: the homeward project already normalizes Socrata/ArcGIS civic feeds.
- **Local check (2026-08-22):** data.indy.gov (OpenIndy Data Portal, Socrata) hosts
  city datasets (<https://data.indy.gov>); Indy ACS publishes statistics at
  <https://www.indy.gov/activity/shelter-statistics> but a dedicated live animal-intake
  dataset could not be confirmed reachable from this environment (catalog API returned
  404 here — recheck interactively before building).
- **Coverage:** Intake/stray-hold/outcome counts and sometimes individual animal
  records; varies wildly by municipality; rarely photos.
- **Data quality:** Thin for matching (often aggregate tables, few photos, coarse
  breed/color strings), but authoritative for stray-hold status.
- **Integration effort:** Very low per dataset (SODA is trivially scrapeable);
  discovery/maintenance cost is the real cost.
- **Verdict: NOT SUITABLE** as a primary matching source; opportunistic supplement
  where a rich per-animal dataset exists.

## 8. Other sources surveyed (credible but weaker)

| Source | Notes | Verdict |
|---|---|---|
| **Shelter Animals Count** (<https://www.shelteranimalscount.org/about-the-data>) | National statistical DB of intakes/outcomes; aggregates only, no individual animals | NOT SUITABLE |
| **Finding Rover** | Facial-recognition reunification app; API status unclear/app-defocused since Petco Love Lost absorbed mindshare | NOT SUITABLE |
| **Craigslist / Facebook groups** | High lost-pet volume, but ToS prohibit scraping; no API | NOT SUITABLE (policy) |

---

## Recommended sequencing

1. **Now:** Request the free RescueGroups.org v5 public API key; build the
   `rescuegroups` HTTP scraper + normalizer mirroring the retired Petfinder module
   (JSON:API → PetRecord). This restores the adoptable-listings surface Petfinder
   provided, with better color/location fields.
2. **In parallel (zero code):** Email **info@adoptapet.com** to open the Partner API
   conversation; note attribution + opt-out obligations up front.
3. **After RescueGroups ships:** County outreach — approach Indianapolis Animal Care
   Services about a ShelterLuv/PetPoint export pilot (stray-hold coverage, which no
   national API gives us).
4. **When leverage justifies it:** Apply to Nextdoor's developer partnership program
   (`p_intent_lost_found`) and Petco Love Lost's integration team; both are
   relationship-gated, not engineering-gated.
5. **Re-evaluate quarterly:** PetHub alpha graduation; any new public lost-pet API;
   data.indy.gov intake dataset publication.

*Research date: 2026-08-22. URLs cited inline; Petfinder decommission facts per
provider announcements captured in git history of `docs/api-analysis-petfinder*`
and README.*
