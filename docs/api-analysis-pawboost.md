# API Analysis: PawBoost (pawboost.com)

**Date Analyzed:** 2026-03-24
**Base URL:** https://www.pawboost.com
**Purpose:** Lost, found, and stray pet listings with social alert distribution

---

## Technology Stack

| Component | Details |
|---|---|
| CDN/WAF | **Cloudflare (Managed Bot Challenge)** — blocks all non-browser HTTP clients |
| Backend | PHP (likely Symfony based on form naming conventions `LfdbFeedStatusForm`) |
| Frontend | Server-rendered HTML + jQuery, Bootstrap |
| Analytics | Amplitude (`amplitude.logEvent(...)`) |
| Image CDN | `img-cdn.pawboost.com` |
| Auth Required | None for read — but Cloudflare blocks automated requests |
| Bot Protection | **Strict** — requires JS execution + TLS fingerprint matching |

---

## ⚠️ Access Constraint

The entire `www.pawboost.com` domain is behind **Cloudflare's Managed Challenge**, which requires JavaScript execution to pass. Standard `curl` / `requests` / `fetch` calls all return HTTP 403 with a Cloudflare challenge page.

**To access programmatically, options are:**
1. **Playwright/Puppeteer** with stealth plugins (`playwright-stealth`)
2. **Selenium + undetected-chromedriver** (cloud or local)
3. **Proxy scraping services**: Zyte, Bright Data, ScraperAPI (Cloudflare bypass tier)
4. **Partner API** (for shelters — contact shelter-support@pawboost.com)

**One exception:** `https://www.pawboost.com/js/pawboost.js` is publicly accessible without the challenge (no Cloudflare on static JS), confirming the full widget parameter structure.

---

## URL Structures

### Listing / Search Pages
```
GET /lost-found-pets/{city-slug}-{state}-{zip}/{status-slug}/page-{N}?{filters}
```

**Examples:**
```
# All lost pets in Fishers, IN
/lost-found-pets/fishers-in-46038/all-lost-pets/page-9
  ?LfdbFeedStatusForm[status]=100
  &LfdbFeedStatusForm[address]=46038

# All found/stray pets with full filters
/lost-found-pets/albuquerque-nm-87112/all-found-stray-pets/page-1
  ?LfdbFeedStatusForm[zip]=87112
  &LfdbFeedStatusForm[status]=101
  &LfdbFeedStatusForm[address]=Albuquerque, NM 87112
  &LfdbFeedStatusForm[radius]=25
  &LfdbFeedStatusForm[species]=
  &LfdbFeedStatusForm[gender]=
  &LfdbFeedStatusForm[sortAttribute]=recency
  &LfdbFeedStatusForm[dateRange]=90
  &LfdbFeedStatusForm[organizationId]=16224

# Shelter-specific listing
/lost-found-pets?LfdbFeedStatusForm[zip]=27539
  &LfdbFeedStatusForm[status]=101
  &LfdbFeedStatusForm[organizationId]=7128

# Lost cats only
/lost-found-pets/lake-worth-fl-33460/all-lost-cats/page-1
  ?LfdbFeedStatusForm[status]=100
  &LfdbFeedStatusForm[species]=Cat
  &LfdbFeedStatusForm[address]=33460
```

### Status Path Slugs
| Slug | Meaning |
|---|---|
| `all-lost-pets` | Lost (owner-reported) |
| `all-found-stray-pets` | Found / stray (shelter intake) |
| `all-lost-found-stray-pets` | All statuses combined |
| `all-lost-cats` | Lost cats only |
| `all-lost-dogs` | Lost dogs only |

---

### Individual Pet Detail Page
```
GET /landing/pet/{HASH_ID}/{status}-{pet-name}-{city}-{state}-{zip}
```

**Example:**
```
/landing/pet/JL_GQjwu8xUKeVNzSwCgL5b75fW1-4Q7/lost-karma-indianapolis-in-46222
/landing/pet/K7f08qJAypH7fksx4a50BQ49enaYZr1g/lost-alex-greenfield-in-46140
```

**Hash ID:** Unique alphanumeric token per pet report (used in all share/flag URLs).

### Short URL
```
GET /nd/{PawBoost-numeric-ID}     # Nextdoor share redirect
```

---

## `LfdbFeedStatusForm` Query Parameters

| Parameter | Values | Notes |
|---|---|---|
| `status` | `100` = Lost, `101` = Found/Stray | Required for filtering |
| `zip` | ZIP code string | Search center point |
| `address` | City/State/ZIP string | Display label |
| `radius` | Miles integer (e.g., `25`) | Search radius |
| `species` | `Dog`, `Cat`, `""` (all) | Species filter |
| `gender` | `Male`, `Female`, `""` (all) | Gender filter |
| `sortAttribute` | `recency` | Sort order |
| `dateRange` | Days integer (e.g., `90`) | Only show pets within N days |
| `organizationId` | Numeric shelter ID | Filter to specific shelter |
| `attributeSearch` | Text search string | Free text search |

---

## Widget Embed System

PawBoost offers an **embeddable iframe widget** for third-party websites:

**Widget JS:** `https://www.pawboost.com/js/pawboost.js` *(publicly accessible)*

**Embed code:**
```html
<script async src="https://www.pawboost.com/js/pawboost.js" charset="utf-8"></script>
<div id="pawboost-widget"
     data-url="https://www.pawboost.com/frame/lost-found-widget?"
     data-zip="46038"
     data-distance="25"
     data-status="100"
     data-animal-type="Dog"
     data-sort="recency"
     data-within-past="90"
     data-per-page="8"
     data-height="700px">
</div>
```

**Widget JS parameter mapping (from source):**
```javascript
data-status        → LfdbFeedStatusForm[status]
data-zip           → LfdbFeedStatusForm[zip]
data-distance      → LfdbFeedStatusForm[radius]
data-animal-type   → LfdbFeedStatusForm[species]
data-sort          → LfdbFeedStatusForm[sortAttribute]
data-within-past   → LfdbFeedStatusForm[dateRange]
data-per-page      → per-page
```

The widget also passes `parentUrl` (base64 of the embedding page's URL) so PawBoost can validate the origin.

**Frame endpoint:**
```
GET /frame/lost-found-widget?parentUrl={base64_url}&LfdbFeedStatusForm[...]&per-page=8
```

---

## Data Fields (from Widget HTML)

Confirmed from actual widget HTML shared by user:

### Listing Card Fields
| Field | Source | Example |
|---|---|---|
| PawBoost ID | `pet-feed-id` span | `72699791` |
| Hash ID | URL path | `JL_GQjwu8xUKeVNzSwCgL5b75fW1-4Q7` |
| Name | `pet-feed-name` h2 | `Karma` |
| Gender | `pet-feed-details` small | `Female` |
| Species | `pet-feed-details` small | `Dog` |
| Status badge | `label-danger` / `label-success` | `LOST` / `FOUND` |
| Location | `pet-feed-location` h3 | `Indianapolis, IN 46222` |
| Last Seen Address | img `alt` attribute | `Sherburne lane, Indianapolis, IN 46222` |
| Description | `pet-feed-description` p | `Tan small dog very friendly. Yorkie Pomeranian mix breed` |
| Reported | relative timestamp | `56 mins ago` |
| Thumbnail | `img-cdn.pawboost.com` | `img_{id}_{hash}-thumb.jpeg` |
| Facebook Post URL | button href | `https://www.facebook.com/{page}/posts/{id}` |
| Detail Page URL | link href | `/landing/pet/{hash}/{slug}` |

### Additional Fields in Nextdoor Share URL (decoded)
- Date lost: `March 23, 2026`
- Neighborhood/area: `Abney Lake apmts`, `Indianapolis West side`
- Full owner message

### Image CDN Pattern
```
https://img-cdn.pawboost.com/{unix_timestamp}/img_{numeric_id}_{md5_hash}-thumb.jpeg
https://img-cdn.pawboost.com/{unix_timestamp}/img_{numeric_id}_{md5_hash}.jpeg
```

---

## Shelter Integration

PawBoost auto-syncs stray intakes from major shelter management systems:

| Software | Integration Method |
|---|---|
| **Shelterluv** | Native API — PawBoost pulls from Shelterluv API every 1–2 hours |
| **PetPoint** | Native feed via Intake Type configuration |
| **Chameleon** | SFTP upload (Crystal Report format) |
| **Shelter Buddy** | Supported |
| **Animal Shelter Manager** | Supported |

**Data shared from shelters:**
- Photo, sex, species, date found, area found, description

**Geo-location for shelter animals:** The shelter's own zip code (not the exact location found). Address field currently not available in Shelterluv API.

**Auto-removal triggers:** Pet is removed when status changes to adopted, transferred, returned home; or if intake was >90 days ago.

---

## Scale & Coverage

- 2,000+ pets posted per day
- 7M+ community members ("Rescue Squad")
- 2.5M+ monthly site visits
- 2M+ pets reunited (all-time)
- Facebook alert network: 25M+ reach/month
- Integrations with Nextdoor and Craigslist

---

## Robots.txt

```
User-agent: *
Disallow:
```
*(No restrictions — but Cloudflare blocks bots regardless)*

---

## Scraping Strategy for K9-Overwatch

### Recommended Approach: Playwright + Stealth

```python
from playwright.async_api import async_playwright

async def scrape_pawboost(zip_code, status=100, species="", radius=25):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)..."
        )
        page = await context.new_page()

        url = (
            f"https://www.pawboost.com/lost-found-pets/{zip_code}/all-lost-pets/page-1"
            f"?LfdbFeedStatusForm[zip]={zip_code}"
            f"&LfdbFeedStatusForm[status]={status}"
            f"&LfdbFeedStatusForm[radius]={radius}"
            f"&LfdbFeedStatusForm[species]={species}"
            f"&LfdbFeedStatusForm[sortAttribute]=recency"
            f"&LfdbFeedStatusForm[dateRange]=90"
        )
        await page.goto(url, wait_until="networkidle")

        # Parse listing cards
        cards = await page.query_selector_all(".pet-search-result")
        pets = []
        for card in cards:
            pet = {
                "id": await (await card.query_selector(".pet-feed-id")).inner_text(),
                "name": await (await card.query_selector(".pet-feed-name")).inner_text(),
                "location": await (await card.query_selector(".pet-feed-location")).inner_text(),
                "description": await (await card.query_selector(".pet-feed-description")).inner_text(),
                # ...
            }
            pets.append(pet)
        return pets
```

### Alternative: Widget Embed Parsing
Host the PawBoost widget on a simple webpage, then use Playwright to load that page and parse the iframe content — this mimics legitimate widget usage.

---

## Standardized Data Schema (for aggregation)

```json
{
  "source": "pawboost",
  "source_id": "72699791",
  "hash_id": "JL_GQjwu8xUKeVNzSwCgL5b75fW1-4Q7",
  "type": "lost",
  "animal_type": "dog",
  "name": "Karma",
  "breed": "Yorkie Pomeranian mix",
  "gender": "female",
  "age": null,
  "color": "Tan",
  "status": "lost",
  "date_lost": "2026-03-23",
  "reported_at": "2026-03-24T...",
  "location_text": "Sherburne lane, Indianapolis, IN 46222",
  "city": "Indianapolis",
  "state": "IN",
  "zip": "46222",
  "lat": null,
  "lon": null,
  "shelter_name": null,
  "photos": [
    "https://img-cdn.pawboost.com/1774384502/img_72699791_7498fc3488eea9cc4e113caf3d072d79.jpeg"
  ],
  "thumbnail": "https://img-cdn.pawboost.com/1774384502/img_72699791_7498fc3488eea9cc4e113caf3d072d79-thumb.jpeg",
  "detail_url": "https://www.pawboost.com/landing/pet/JL_GQjwu8xUKeVNzSwCgL5b75fW1-4Q7/lost-karma-indianapolis-in-46222",
  "facebook_post_url": "https://www.facebook.com/849773468482624/posts/1373995221421103",
  "description": "Tan small dog very friendly. Yorkie Pomeranian mix breed",
  "scraped_at": "2026-03-24T00:00:00Z"
}
```
