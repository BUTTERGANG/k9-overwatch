# API Analysis: Helping Lost Pets (helpinglostpets.com)

**Date Analyzed:** 2026-08-22
**Base URL:** https://www.helpinglostpets.com
**Status:** ❌ **NOT INTEGRABLE — source no longer exists as a distinct registry**
**Purpose (historical):** Free national lost/found pet registry with state/city browsable listings and a volunteer cross-poster network

---

## Verdict

Helping Lost Pets has been **fully absorbed by Pet FBI**. Every request to any path on
`helpinglostpets.com` (including the classic `/v2/` app URLs such as
`/v2/?sort=age&slt=…&sln=…` and `/v2/lost-found/?state=IN`) returns an **HTTP 301 to
https://petfbi.org/** served from CloudFront:

```
HTTP/2 301
location: https://petfbi.org/
server: CloudFront
cache-control: max-age=31536000
```

Pet FBI itself confirms the merger ("Pet FBI and Helping Lost Pets Working Together
to Bring More Pets Home", petfbi.org blog) and lists HelpingLostPets as a partner
brand under its Lost Dogs of America umbrella. There is no remaining
helpinglostpets-specific API, database, or listing surface.

**Consequence:** all HLP lost/found reports now live in Pet FBI's GraphQL backend,
which K9-Overwatch already scrapes via `src/k9overwatch/scrapers/browser/petfbi.py`.
Adding a `helpinglostpets` source would only duplicate `petfbi` records 1:1.
No scraper or normalizer was implemented — this is the correct outcome, not a gap.

## Technology Stack

| Component | Details |
|---|---|
| Frontend | None of its own — domain is a redirect stub |
| Redirect Target | https://petfbi.org (VitePress SPA + AWS WAF) |
| Data Backend | Pet FBI GraphQL (`api.petfbi.org/v3prod/public`) |
| CDN | CloudFront |

See `docs/api-analysis-petfbi.md` for the live target's full stack, endpoints, and
access constraints (AWS WAF CAPTCHA, Playwright required).

## Endpoints

None survive. All paths 301-redirect to `petfbi.org`. Detail-style URLs such as
`/petdetail/?id=…` resolve to Pet FBI pages (or 404 at the Pet FBI side); no JSON
endpoint remains exposed under the helpinglostpets.com hostname.

## Field Mapping to PetRecord

N/A — no payload exists. The underlying report schema is now exactly Pet FBI's;
coverage is already realized through the `petfbi` normalizer
(`src/k9overwatch/normalizers/petfbi.py`), including native lat/lon.

## Access Method

Not applicable for HLP itself. For the merged data, use the existing Playwright-based
Pet FBI scraper (HTTP clients are blocked by AWS WAF — see petfbi analysis).

---

# Pivot Investigation: FidoAlert (fidoalert.com)

The designated fallback was also investigated and found **not integrable**, for a
different reason: FidoAlert is a **push-alert network, not a public registry**.

| Component | Details |
|---|---|
| Marketing site | www.fidoalert.com — static Webflow, content pages only (about, blog, success stories). Sitemap contains **zero listing pages** |
| App | app.fidoalert.com — React SPA (Vite build), no server-rendered HTML |
| Backend | Supabase project `cyaiuhmuhugklkaacogf.supabase.co` (PostgREST) |
| Anon access | The anon JWT embedded in the JS bundle is accepted, but **row-level security filters every table to zero rows** (`content-range: */0` for `found_pet_reports`, `LostPetLocation`, `Pet`, `Bundle`) |
| Public data flow | A lost pet becomes publicly viewable **only via a per-owner `publicToken`** minted after authentication (`publicToken → publicPetInfo`). Tokens are scoped to the authenticated owner's own pets — there is no enumeration path |
| Listing surface | None. Found-pet reports trigger SMS/text alerts to nearby members; they are never published to a browsable index |

**Conclusion:** there is no legitimate scrapeable listing surface at FidoAlert. Its
Supabase tables are RLS-locked for anonymous callers, and scraping behind member
authentication would require accounts and violate the intent of the access model.

---

# Recommendations

1. **Do not add** a `helpinglostpets` or `fidoalert` source. Both were verified dead
   ends against the live sites on 2026-08-22.
2. HLP coverage is already subsumed by the existing `petfbi` pipeline — no action needed.
3. Candidate replacement sources with genuinely public listings for future expansion:
   Petco Love Lost (Next.js + heavy bot protection, needs evaluation), PawMaw
   (pawmaw.com, server-rendered listings), PetKey.org (found-pet listings).
4. This document intentionally ships without a scraper/normalizer/tests: writing a
   client for a redirect stub or an empty RLS-locked dataset would produce dead code
   that silently fetches nothing in production.

## Summary

| Property | Helping Lost Pets | FidoAlert |
|---|---|---|
| Public listings | ❌ domain 301s to petfbi.org | ❌ none (auth-gated alert network) |
| Integration difficulty | Pointless — duplicate of `petfbi` | Infeasible — RLS-locked Supabase |
| Action taken | Documented; covered by existing petfbi source | Documented; recommend alternative sources |
