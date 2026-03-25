# API Analysis: Indy Lost Pet Alert (indylostpetalert.com)

**Date Analyzed:** 2026-03-24
**Base URL:** https://www.indylostpetalert.com
**Purpose:** Indianapolis/central Indiana community lost, found, and sighting reports for pets
**Coverage:** Marion County and surrounding Indiana counties (Indianapolis metro area)

---

## Technology Stack

| Component | Details |
|---|---|
| CMS | **WordPress** (with Enfold theme by Kriesi) |
| Page Builder | Avia Template Builder |
| SEO Plugin | Yoast SEO v27.0 |
| Security | iThemes Security |
| Analytics | Google Analytics 4 (GT-WFFK9XKL), Google Tag Manager (GTM-K4KLHT6J) |
| Stats | Jetpack Stats |
| Hosting | WP Engine |
| Bot Protection | **None** — WordPress REST API fully open, no Cloudflare |
| Auth Required | None for read |

---

## ⭐ Key Finding: Open WordPress REST API

The site exposes the **full WordPress REST API (`/wp-json/wp/v2/`)** with **no authentication required**. All pet posts are retrievable as structured JSON. This is the cleanest, most reliable integration of the three services analyzed.

**API root:** `https://www.indylostpetalert.com/wp-json/wp/v2/`

---

## Database Scale

| Category | Post Count |
|---|---|
| Lost Pet (all) | **12,748** |
| Found Pet (all) | **16,619** |
| Pet Sighting (all) | **4,643** |
| Lost Dogs | 7,216 |
| Lost Cats | 5,422 |
| Found Dogs | 13,065 |
| Found Cats | 3,382 |

---

## Primary Endpoint: Posts

```
GET /wp-json/wp/v2/posts
```

### Key Query Parameters

| Parameter | Type | Example | Notes |
|---|---|---|---|
| `categories` | int (CSV) | `19` or `19,24` | Filter by category ID(s) |
| `tags` | int (CSV) | `223,234` | Filter by tag (color) IDs |
| `per_page` | int | `10` (max `100`) | Results per page |
| `page` | int | `2` | Page number |
| `orderby` | string | `date` | Sort field |
| `order` | string | `desc` | `asc` or `desc` |
| `after` | ISO8601 | `2026-03-20T00:00:00` | Posts after date |
| `before` | ISO8601 | `2026-03-24T23:59:59` | Posts before date |
| `search` | string | `missing+golden` | Full-text search |
| `_embed` | flag | `true` | Include featured image, terms |
| `_fields` | string (CSV) | `id,date,title,excerpt` | Limit response fields |

### Pagination Headers (from response)

```
X-WP-Total: 12748         # total posts matching query
X-WP-TotalPages: 1275     # total pages at 10/page
```

---

## Category Taxonomy

Categories encode **post type**, **animal type**, and **size** simultaneously.

### Top-Level Post Type Categories

| ID | Slug | Name |
|---|---|---|
| `19` | `lost-pet` | Lost Pet |
| `20` | `found-pet` | Found Pet |
| `21` | `pet-sighting` | Pet Sighting |
| `221` | `deceased-rainbow-bridge` | Deceased: Rainbow Bridge |

### Animal Type Categories (Lost)

| ID | Slug | Name |
|---|---|---|
| `24` | `dog` | Dog (lost) |
| `25` | `cat` | Cat (lost) |
| `26` | `other` | Other Pet (lost) |

### Animal Type Categories (Found)

| ID | Slug | Name |
|---|---|---|
| `27` | `dog-found-pet` | Dog (found) |
| `28` | `cat-found-pet` | Cat (found) |
| `29` | `other-found-pet` | Other Pet (found) |
| `172` | `bird-other` | Bird (found) |
| `174` | `ferret-other` | Ferret (found) |

### Animal Type Categories (Sighting)

| ID | Slug | Name |
|---|---|---|
| `33` | `dog-pet-sighting` | Dog sighting |
| `34` | `cat-pet-sighting` | Cat sighting |
| `35` | `other-pet-sighting` | Other sighting |

### Size Categories (Lost Dogs)

| ID | Slug | Size Range |
|---|---|---|
| `182` | `x-small-lost-dog` | X-Small (10 lbs & under) |
| `127` | `small` | Small (10-25 lbs) |
| `128` | `medium` | Medium (25-50 lbs) |
| `129` | `large` | Large (50-75 lbs) |
| `130` | `x-large` | X-Large (75-90 lbs) |
| `183` | `xx-large-dog` | XX-Large (90+ lbs) |

### Size Categories (Found Dogs)

| ID | Slug | Size Range |
|---|---|---|
| `180` | `x-small-dog-found-pet` | X-Small |
| `138` | `small-dog-found-pet` | Small (10-25 lbs) |
| `139` | `medium-dog-found-pet` | Medium (25-50 lbs) |
| `140` | `large-dog-found-pet` | Large (50-75 lbs) |
| `141` | `x-large-dog-found-pet` | X-Large (75-90 lbs) |
| `179` | `xx-large-dog-found-pet` | XX-Large (90+ lbs) |

### Size Categories (Cats)

| ID | Slug | Size Range |
|---|---|---|
| `134` | `small-cat` | Small (5 lbs & under) |
| `135` | `medium-cat` | Medium (6-8 lbs) |
| `136` | `large-cat` | Large (9-11 lbs) |
| `137` | `x-large-cat` | X-Large (12+ lbs) |

---

## Tag Taxonomy (Colors)

Tags are used exclusively for **pet color** filtering.

| ID | Color |
|---|---|
| `223` | Black |
| `224` | Brown |
| `234` | White |
| `228` | Grey |
| `232` | Tan |
| `233` | Tri-Color |
| `237` | Tabby |
| `226` | Brindle |
| `241` | Orange |
| `231` | Spotted |
| `230` | Red |
| `236` | Calico |
| `227` | Golden |
| `229` | Merle |
| `248` | Tortoise |
| `235` | Yellow |
| `239` | Blue |
| `240` | Green |

---

## Post Object Structure

Full fields returned per post:

```json
{
  "id": 269782,
  "date": "2026-03-24T10:46:16",
  "date_gmt": "2026-03-24T15:46:16",
  "modified": "2026-03-24T10:46:16",
  "slug": "lost-dog-alert-96891-eli-missing-near-1222-north-tacoma-avenue-indianapolis46201",
  "status": "publish",
  "type": "post",
  "link": "https://www.indylostpetalert.com/2026/03/24/lost-dog-alert-...",
  "title": { "rendered": "Lost Dog, Alert #96891 Eli missing near 1222 North Tacoma Avenue, Indianapolis46201" },
  "content": { "rendered": "<p>Location Information: ...</p>" },
  "excerpt": { "rendered": "<p>Location Information: ...</p>" },
  "featured_media": 269783,
  "categories": [19, 24, 127],
  "tags": [234],
  "jetpack_featured_media_url": "https://www.indylostpetalert.com/wp-content/uploads/2026/03/photo.jpg"
}
```

### Alert Number in Slug/Title

Every post has an **alert number** embedded in the title and slug:
```
Title: "Lost Dog, Alert #96891 Eli missing near 1222 North Tacoma Avenue..."
Slug:  "lost-dog-alert-96891-eli-missing-near-1222-north-tacoma-avenue-..."
```

Extract with: `re.search(r'Alert #(\d+)', title)`

---

## Content Field Structure (Post Body)

Post content is **plain-text structured** within an HTML paragraph. Field labels are consistent across all post types:

### Lost Pet Content Template
```
Location Information: {street address}, {neighborhood}, {city}, {county}
Nearest Address of Where Pet went missing: {address}
Contact Information: Phone: {phone}
Lost Pet Information:
  Type of Pet: {Dog|Cat|Other}
  Pet's Name: {name}
  Pet Size: {size range}
  Color of Pet: {color}
  Date Pet Went Missing: {MM/DD/YYYY}
  Approximate Time Pet Went Missing: {HH:MM am/pm}
  Gender: {Male|Female}
{free-text description}
```

### Found Pet Content Template
```
Location Information: {street address}, {neighborhood}, {city}, {county}
Contact Information: Phone: {phone}
Found Pet Information:
  Date Pet Was Found: {MM/DD/YYYY}
  Type of Pet: {Dog|Cat|Other}
  Size of Pet: {size range}
  Color of Pet: {color}
  Approximate Time Pet Was Found: {HH:MM am/pm}
  Gender: {Male|Female}
{free-text description}
```

### Sighting Content Template
```
Location Information: {street/intersection}, {neighborhood}, {city}, {county}
Nearest Address of Where Pet was sighted: {address}
Contact Information: Phone: {phone}
Pet Sighting Information:
  Date Pet Was Seen: {MM/DD/YYYY}
  Pet Type: {Dog-sight|Cat-sight|Other}
  Pet Size: {size range}
  Pet Color: {color}
  Approximate Time Pet Was Seen: {HH:MM am/pm}
{free-text description}
```

---

## Images

### Featured Image
Retrieved via `_embed=true` or the `jetpack_featured_media_url` field.

```
GET /wp-json/wp/v2/media/{featured_media_id}
```

Available sizes per image:
`thumbnail`, `medium`, `medium_large`, `large`, `featured`, `featured_large`,
`extra_large`, `full`, `square`, `widget`, `gallery`, `portfolio`, `portfolio_small`

Direct URL pattern:
```
https://www.indylostpetalert.com/wp-content/uploads/{YYYY}/{MM}/{filename}.jpg
```

---

## Efficient Query Recipes

### Get latest lost dogs (last 7 days)
```
GET /wp-json/wp/v2/posts
  ?categories=19,24
  &per_page=100
  &orderby=date
  &order=desc
  &after=2026-03-17T00:00:00
  &_fields=id,date,slug,title,excerpt,link,categories,tags,jetpack_featured_media_url
```

### Get latest found cats with image
```
GET /wp-json/wp/v2/posts
  ?categories=20,28
  &per_page=50
  &orderby=date
  &order=desc
  &_embed=true
```

### Search by color (black dogs, lost)
```
GET /wp-json/wp/v2/posts
  ?categories=19,24
  &tags=223
  &per_page=20
```

### Paginate through full dataset
```python
page = 1
while True:
    r = requests.get(
        "https://www.indylostpetalert.com/wp-json/wp/v2/posts",
        params={"categories": "19", "per_page": 100, "page": page,
                "orderby": "date", "order": "desc",
                "_fields": "id,date,slug,title,excerpt,categories,tags,jetpack_featured_media_url"}
    )
    total_pages = int(r.headers.get("X-WP-TotalPages", 1))
    posts = r.json()
    # process posts...
    if page >= total_pages:
        break
    page += 1
```

---

## Field Parsing (Python)

```python
import re
from html import unescape

def parse_pet_post(post):
    raw = unescape(re.sub(r'<[^>]+>', ' ', post['content']['rendered']))
    raw = re.sub(r'\s+', ' ', raw).strip()

    def extract(pattern):
        m = re.search(pattern, raw, re.IGNORECASE)
        return m.group(1).strip() if m else None

    # Alert number from title
    alert_match = re.search(r'Alert #(\d+)', post['title']['rendered'])

    return {
        "source":          "indylostpetalert",
        "source_id":       str(post['id']),
        "alert_number":    alert_match.group(1) if alert_match else None,
        "wp_post_date":    post['date'],
        "detail_url":      post['link'],
        "title":           post['title']['rendered'],
        "categories":      post.get('categories', []),
        "color_tags":      post.get('tags', []),
        "photo_url":       post.get('jetpack_featured_media_url'),

        # Parsed from content body
        "location_text":   extract(r'Location Information:\s*(.+?)(?=Contact Information)'),
        "phone":           extract(r'Phone:\s*([\d\s\-\(\)]+)'),
        "pet_name":        extract(r"Pet'?s? Name:\s*([^\n]+?)(?=\s+Pet|\s+Color|\s+Date|\s+Approx|\s+Gender)"),
        "pet_type":        extract(r'Type of Pet:\s*(\w+)'),
        "size":            extract(r'(?:Pet Size|Size of Pet):\s*(.+?)(?=Color of Pet)'),
        "color":           extract(r'Color of Pet:\s*(.+?)(?=Date Pet)'),
        "date_event":      extract(r'Date Pet (?:Went Missing|Was Found|Was Seen):\s*([\d/]+)'),
        "time_event":      extract(r'Approximate Time Pet (?:Went Missing|Was Found|Was Seen):\s*([\d:apm ]+)'),
        "gender":          extract(r'Gender:\s*(\w+)'),
    }
```

---

## Geo Notes

- **Location text** is street address/intersection level: `"1222 North Tacoma Avenue, Springdale, Indianapolis, Marion County"`
- All posts are Indianapolis metro area (Marion, Hamilton, Hendricks, Johnson, Hancock counties)
- No lat/lon in the API — addresses must be geocoded
- County name is always included (useful for sub-regional filtering)

---

## RSS Feed

The site also exposes a **standard WordPress RSS feed** as an alternative polling mechanism:

```
GET /feed/               # all posts
GET /lost-pets/lost-dogs/feed/   # category-specific feed
```

Less useful than the REST API (XML, no field control, 10 posts max) but good as a change-detection webhook.

---

## Robots.txt

Standard WordPress robots.txt — no relevant restrictions on public post content.

---

## Standardized Data Schema (for aggregation)

```json
{
  "source": "indylostpetalert",
  "source_id": "269782",
  "alert_number": "96891",
  "type": "lost",
  "animal_type": "dog",
  "name": "Eli",
  "breed": null,
  "gender": "male",
  "size": "Small (10-25 lbs)",
  "color": "White",
  "status": "lost",
  "date_event": "03/24/2026",
  "time_event": "08:30 am",
  "location_text": "1222 North Tacoma Avenue, Springdale, Indianapolis, Marion County",
  "city": "Indianapolis",
  "state": "IN",
  "zip": "46201",
  "county": "Marion County",
  "lat": null,
  "lon": null,
  "phone": "(317) 217-9739",
  "photos": [
    "https://www.indylostpetalert.com/wp-content/uploads/2026/03/photo.jpg"
  ],
  "detail_url": "https://www.indylostpetalert.com/2026/03/24/lost-dog-alert-96891-eli-...",
  "description": "Black and white French bulldog/beagle mix. Very friendly.",
  "wp_post_id": 269782,
  "wp_categories": [19, 24, 127],
  "wp_tags": [234],
  "scraped_at": "2026-03-24T00:00:00Z"
}
```

---

## Summary

This is the **easiest source to integrate** of all three analyzed:
- Full structured JSON via open WordPress REST API
- No bot protection, no auth, no scraping needed
- Rich filtering by type, size, color, date range
- Street-level addresses for geocoding
- Consistent content template for reliable field parsing
- 33,000+ total records across lost/found/sightings
