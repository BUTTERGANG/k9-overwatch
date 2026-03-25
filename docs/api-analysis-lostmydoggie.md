# API Analysis: Lost My Doggie (lostmydoggie.com)

**Date Analyzed:** 2026-03-24
**Base URL:** https://www.lostmydoggie.com
**Purpose:** Lost and found pet database with phone/email alert broadcasting to neighbors and shelters

---

## Technology Stack

| Component | Details |
|---|---|
| Backend | **ColdFusion** (`.cfm` file extensions) |
| Frontend | Server-rendered HTML |
| CDN/WAF | **Cloudflare (Managed Bot Challenge)** — blocks all non-browser HTTP clients |
| Auth Required | None for browsing public listings |
| Bot Protection | **Strict** — same Cloudflare challenge as PawBoost |

---

## ⚠️ Access Constraint

The entire `www.lostmydoggie.com` domain is behind **Cloudflare's Managed Challenge**. Standard `curl`/`requests`/`fetch` calls return HTTP 403 with the JS challenge page.

**To access programmatically:** Same approach as PawBoost — Playwright with stealth plugins or proxy scraping services (Zyte, Bright Data Cloudflare bypass tier).

---

## URL Structure

### Public Listing / Search Page

```
GET /missing-pets.cfm?petkindid={pet}&alerttypeid={type}&zipcode={zip}&radius={miles}
```

**Example URLs:**
```
# Lost dogs near Indianapolis
https://www.lostmydoggie.com/missing-pets.cfm?petkindid=1&alerttypeid=1&zipcode=46201&radius=50

# Lost cats near Indianapolis
https://www.lostmydoggie.com/missing-pets.cfm?petkindid=2&alerttypeid=1&zipcode=46201&radius=50

# Both lost and found dogs
https://www.lostmydoggie.com/missing-pets.cfm?petkindid=1&alerttypeid=1,3&zipcode=46201&radius=50

# Page 2, sorted by date
https://www.lostmydoggie.com/missing-pets.cfm?petkindid=1&alerttypeid=1&zipcode=46201&radius=50&page_number=2&startr1=21&sort=OrderDate
```

---

## Query Parameters

| Parameter | Values | Notes |
|---|---|---|
| `petkindid` | `1` = Dog, `2` = Cat | Required — species filter |
| `alerttypeid` | `1` = Lost, `3` = Found | Comma-separated for multiple: `1,3` |
| `zipcode` | ZIP code string | Search center point |
| `radius` | Miles integer | e.g., `15`, `25`, `50` |
| `page_number` | Integer (1-based) | Pagination page number |
| `startr1` | Integer | Record start offset (page_number - 1) × per_page |
| `sort` | `OrderDate` | Sort order (default is unclear) |

**Pagination math:**
- Default appears to be ~20 records per page
- `startr1 = (page_number - 1) × 20` (e.g., page 2 → `startr1=21`, page 3 → `startr1=41`)

---

## HTML Card Structure (confirmed from live page)

20 cards per page. Selector: `.box_icon`

```html
<div class="box_icon">
  <div class="icon">
    <div class="image">
      <a href="details.cfm?petid=473213">         <!-- pet ID in href -->
        <img src="pet_images/thumbs/473213.jpg" class="img-responsive">
      </a>
    </div>
    <div class="info">
      <h4>Draco</h4>                               <!-- name -->
      <p>ID# 473213</p>
      <h6>Lost &nbsp;Male Dog</h6>                <!-- status + gender + type -->
      <h6>INDIANAPOLIS, IN<br>46254</h6>           <!-- city/state + ZIP (separate lines) -->
      <ul class="custom">
        <li>Siberian Husky</li>                    <!-- breed -->
        <li>White, Brown</li>                      <!-- color(s), comma-separated -->
        <li>Lost: 2025-12-05</li>                  <!-- event date YYYY-MM-DD -->
      </ul>
    </div>
  </div>
</div>
```

**Extraction selectors:**
| Field | Selector |
|---|---|
| Card container | `.box_icon` (20 per page) |
| Pet ID | `a[href*='petid=']` → regex `petid=(\d+)` |
| Name | `h4` inner text |
| Status/gender/type | first `h6` inner text |
| Location (city/state) | second `h6` inner text, line 1 |
| ZIP | second `h6` inner text, line 2 |
| Breed | `ul.custom li:nth-child(1)` |
| Color(s) | `ul.custom li:nth-child(2)` (comma-separated) |
| Event date | `ul.custom li:nth-child(3)` → regex `(\d{4}-\d{2}-\d{2})` |
| Photo | `img.img-responsive` src (relative — prepend site base URL) |
| Detail URL | `https://www.lostmydoggie.com/details.cfm?petid={ID}` |

**Data Fields Available:**
| Field | Notes |
|---|---|
| Pet name | Displayed in `h4` |
| Species | Dog / Cat (from search URL `petkindid` parameter) |
| Breed | Structured text in first `li` |
| Color | Comma-separated in second `li` |
| Gender | Male / Female in first `h6` |
| Event date | `YYYY-MM-DD` in third `li` |
| Location | City, State — ZIP code level only |
| Photo | Thumbnail image, relative URL |
| Pet ID | Numeric site-specific ID |
| Status | Lost / Found (from search URL `alerttypeid`) |

---

## Service Model

LostMyDoggie.com is primarily a **paid alert broadcasting service**, not a free database. This affects integration:

### Free Tier ("WOOF")
- Listing appears in the public database
- Notification sent to registered shelters/rescues in area
- **Database is public and browsable without payment**

### Paid Tiers ("BARK" / "HOWL")
- Automated phone alerts to up to 10,000 neighbors
- Fax/email to 25+ shelters and vet offices in 20-mile radius
- Optional Facebook ad placement
- Under $100 per alert

### Key Stats
- **35,000+** shelters and rescue groups in network
- **350,000+** registered members
- **210M+** US phone numbers in alert database
- Operational since **2008**

---

## Geographic Coverage

- **USA-wide** (ZIP code based)
- All states covered
- Radius-based search (not city/county based)

---

## Robots.txt

```
User-agent: *
Disallow: /admin/
Disallow: /members/
```
*(Public listing pages are allowed, but Cloudflare blocks bots regardless)*

---

## Scraping Strategy for K9-Overwatch

### Recommended Approach: Playwright + Stealth

Same approach as PawBoost — requires headless Chromium with stealth plugins:

```python
from playwright.async_api import async_playwright

async def scrape_lostmydoggie(zip_code, pet_kind=1, alert_type=1, radius=50):
    """
    pet_kind: 1=dogs, 2=cats
    alert_type: 1=lost, 3=found (comma-separated: "1,3" for both)
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36..."
        )
        page = await context.new_page()

        url = (
            f"https://www.lostmydoggie.com/missing-pets.cfm"
            f"?petkindid={pet_kind}"
            f"&alerttypeid={alert_type}"
            f"&zipcode={zip_code}"
            f"&radius={radius}"
            f"&sort=OrderDate"
        )
        await page.goto(url, wait_until="networkidle")

        # Parse listing cards
        # (card structure to be confirmed with actual page HTML)
        cards = await page.query_selector_all(".pet-listing-card")  # selector TBD
        pets = []
        for card in cards:
            pet = {
                # Extract fields from card HTML
            }
            pets.append(pet)

        # Check for pagination
        total_text = await page.text_content(".results-count")  # selector TBD

        await browser.close()
        return pets
```

### Pagination Loop

```python
async def scrape_all_pages(zip_code, pet_kind=1, alert_type=1, radius=50):
    page_num = 1
    start_r1 = 1
    per_page = 20  # confirm from actual response
    all_pets = []

    while True:
        pets = await scrape_lostmydoggie(
            zip_code, pet_kind, alert_type, radius,
            page_number=page_num, start_r1=start_r1
        )
        if not pets:
            break
        all_pets.extend(pets)
        page_num += 1
        start_r1 += per_page

    return all_pets
```

---

## Assessment for K9-Overwatch Integration

| Property | Details |
|---|---|
| **Coverage** | USA-wide |
| **API Type** | HTML scraping (server-rendered ColdFusion) |
| **Bot Protection** | Cloudflare (Managed Challenge — strict) |
| **Auth Required** | None for public listings |
| **Coordinates** | ❌ ZIP/city level only — geocoding required |
| **Record Types** | Lost, Found |
| **Pagination** | Page number + record offset |
| **Free data?** | ✅ Public database viewable without payment |
| **Integration Difficulty** | Hard (same as PawBoost — Playwright required) |
| **Unique Value** | 35K shelter network, phone alert capability (not relevant for aggregation) |

### Recommendation

**Lower priority** relative to other sources because:
1. Cloudflare protection requires Playwright (same effort as PawBoost)
2. Location data is ZIP/city level, less precise than IndyLostPetAlert's street addresses
3. Primary value proposition is phone alerts (not the database itself)
4. PawBoost, IndyLostPetAlert, and 24petconnect already cover the same lost/found data

**Best approached in Phase 2** after core three sources are running.

---

## Standardized Data Schema (for aggregation)

```json
{
  "source": "lostmydoggie",
  "source_id": "LMD-12345",
  "source_url": "https://www.lostmydoggie.com/missing-pets.cfm?...",
  "record_type": "lost",
  "animal_type": "dog",
  "name": "Buddy",
  "breed": "Labrador Mix",
  "color_primary": "Black",
  "gender": "male",
  "age": "4 years",
  "status": "lost",
  "date_event": "2026-03-20",
  "location_text": "Indianapolis, IN 46201",
  "city": "Indianapolis",
  "state": "IN",
  "zip": "46201",
  "lat": null,
  "lon": null,
  "geocode_source": null,
  "description": "Black lab mix, very friendly...",
  "photos": ["https://www.lostmydoggie.com/images/pets/12345.jpg"],
  "scraped_at": "2026-03-24T00:00:00Z"
}
```
