# API Analysis: 24petconnect.com

**Date Analyzed:** 2026-03-24
**Base URL:** https://24petconnect.com
**Purpose:** Lost, found, and adoptable pet listings powered by the PetHarbor backend

---

## Technology Stack

| Component | Details |
|---|---|
| Backend | ASP.NET MVC 4 |
| Server | Microsoft IIS 10 |
| JS Framework | jQuery + Bootstrap 4 |
| Analytics | Google Analytics 4 (`G-4Y8GCJHPKB`) |
| API Style | POST AJAX endpoints returning **HTML fragments** (no JSON API) |
| Auth Required | None for read operations |

---

## Architecture Overview

The site is a white-label product built on the **PetHarbor** backend system, which also powers many municipal shelter websites and petango.com. All search results are returned as server-rendered HTML fragments injected into the DOM — there is no public JSON REST API.

The site recently integrated with **PetPlace** (petplace.com) for adoption search alerts.

---

## Endpoints

### Primary Search Endpoint
```
POST /PetHarbor/getAdoptableAnimalsByLatLon
```
Returns HTML fragment of animal listing cards (30 per page).

**Request Body (form-urlencoded):**
```
model[AnimalType]         = "" | "dogs" | "cats" | "other"
model[SearchType]         = "ADOPT" | "LOST" | "FOUND"
model[Latitude]           = 33.749          (decimal degrees)
model[Longitude]          = -84.388         (decimal degrees)
model[Miles]              = 25              (1–200)
model[LocationChanged]    = true | false
model[URLName]            = "Adopt" | "LostFound"
model[AnimalFilter][AnimalType]    = "" | "dogs" | "cats" | "other"
model[AnimalFilter][SearchType]    = "ADOPT" | "LOST" | "FOUND"
model[AnimalFilter][URLName]       = "Adopt" | "LostFound"
model[AnimalFilter][ShelterList]   = "" | "('SHELTERCODE1','SHELTERCODE2')"
model[AnimalFilter][BreedList]     = "" | "('Labrador Retriever','Poodle')"
model[AnimalFilter][SimilarBreeds] = false | true
model[AnimalFilter][Gender]        = "" | "M" | "F"
model[AnimalFilter][Age]           = "" | "young" | "adult"
model[AnimalFilter][Size]          = ""
model[AnimalFilter][SortBy]        = "" | "days" | "breed" | "id"
BreedReqId                         = ""
```

**Response:** HTML fragment injected into `#indexFeaturedAnimals`

**Response includes:**
- JavaScript: `filterMiles = 25; globalAnimalCount = 2488;`
- 30 `<div class="gridResult">` blocks per page
- Each card contains: animal ID, shelter code, name, gender, breed, animal type, age, days lost/at shelter, status, location lost (street address), distance, shelter name, photo URL

---

### Shelter List Endpoint
```
POST /Utility/getShelterListByLatLon
```
Returns HTML table of nearby shelters for the filter UI.

**Request Body:**
```
model[AnimalType]   = ""
model[SearchType]   = "adopt" | "LOST" | "FOUND"
model[Latitude]     = 33.749
model[Longitude]    = -84.388
model[Miles]        = 25
```

**Response fields per shelter:**
- Shelter code (e.g., `PP20149`, `RR2070673466`)
- Shelter name (e.g., "Fulton County Animal Services")
- Type (e.g., "Rescue", "Municipal")
- Distance in miles from search point

---

### Other Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `POST /Utility/getBreedList` | POST | Returns breed checkbox list filtered by animal type |
| `POST /Utility/getChangeLocation` | POST | Resolves ZIP/postal code to lat/lon |
| `POST /PetHarbor/SubmitWebInterest` | POST | Submit adoption interest form |
| `POST /Contact/SendRequestEmail` | POST | Contact poster of lost pet |
| `POST /Utility/ReportImageContent` | POST | Report inappropriate image |

---

### Detail Pages (Server-Rendered)

```
GET /LostFound/Details/{ShelterCode}/{AnimalId}
GET /Adopt/Details/{ShelterCode}/{AnimalId}
GET /DetailsMain/{ShelterCode}/{AnimalId}
```

**Available fields on detail page:**
- Animal ID
- Name
- Breed
- Gender
- Age / Description
- Located At (shelter name or "PUBLIC POST")
- Date lost / Date brought to shelter
- Location Lost (full street address, e.g., "1369 Iron Gate Blvd, Jonesboro, GA")
- Status (e.g., "Reported Lost by the Owner")
- Multiple photos (at `/image/{imageId}`)
- Contact form (email, name, phone, message)
- Social share links (Facebook, Twitter)

**Example detail (Animal 3055840):**
```
Name:          Chase
Breed:         Yorkshire Terrier
Gender:        Male
Lost since:    2026-03-22
Location Lost: 1369 Iron Gate Blvd, Jonesboro, GA
Description:   Chase is male Yorkie and he is Black and Tan
Photos:        /image/688554025, /image/688554024, /image/688554023
```

---

### Photo Endpoint
```
GET /image/{imageId}
```
Direct image URL, no authentication required.

---

## Data Available by Search Type

### ADOPT
- Name, breed, gender, animal type, age
- Days at shelter / date brought in
- Shelter name + distance
- Photos

### LOST (owner-reported)
- Breed, gender
- Days since lost
- Status: "Reported Lost by the Owner"
- **Location Lost: street-level address** (geocodable)
- Distance from search point
- Photos

### FOUND (shelter intake)
- Breed, gender
- Days at shelter
- Status: "Found and in Shelter Care ({Shelter Name})"
- Shelter name + distance
- Photos

---

## Pagination

- **Page size:** 30 animals per page
- **Pagination param:** `model[AnimalFilter]` or URL param `?index=30&index=60` etc.
- **Total count:** Returned in JavaScript: `globalAnimalCount = {N};`
- **More Animals:** `POST /PetHarbor/getMoreAnimals` (appends next page to grid)

---

## Geographic Data Strategy

Since the API returns HTML (not coordinates), the geographic pipeline for lost pets is:

```
Location Lost field (street address)
        ↓
Geocoding API (Google Maps / Nominatim)
        ↓
Lat/Lon coordinate
        ↓
Map pin
```

For shelter animals: shelter name → lookup shelter address → geocode.

---

## Scraping Notes

- **No API key required**
- **Rate limiting:** Not detected during testing; recommend respectful delays (1–2s between requests)
- **CORS:** Site does not serve JSON; all requests should be server-side
- **robots.txt:** Returns 404 (no restrictions documented)
- **Headers required:** `X-Requested-With: XMLHttpRequest`, `Referer: https://24petconnect.com/`, browser `User-Agent`

### Minimal working scraper pattern:
```python
import requests
from bs4 import BeautifulSoup

def search_lost_pets(lat, lon, miles=25):
    payload = {
        "model[SearchType]": "LOST",
        "model[Latitude]": lat,
        "model[Longitude]": lon,
        "model[Miles]": miles,
        "model[LocationChanged]": "true",
        "model[URLName]": "LostFound",
        "model[AnimalFilter][SearchType]": "LOST",
        "model[AnimalFilter][URLName]": "LostFound",
    }
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://24petconnect.com/LostFound",
        "User-Agent": "Mozilla/5.0 ...",
    }
    r = requests.post(
        "https://24petconnect.com/PetHarbor/getAdoptableAnimalsByLatLon",
        data=payload,
        headers=headers
    )
    soup = BeautifulSoup(r.text, "html.parser")
    animals = []
    for card in soup.select("div.gridResult"):
        onclick = card.get("onclick", "")
        # onclick="Details('ShelterCode', 'AnimalId')"
        ids = re.findall(r"'([^']+)'", onclick)
        shelter_code = ids[0] if ids else ""
        animal_id = ids[1] if len(ids) > 1 else ""
        spans = {s.text.split(":")[0].strip(): s.text.split(":", 1)[1].strip()
                 for s in card.find_all("span") if ":" in s.text}
        animals.append({
            "source": "24petconnect",
            "animal_id": animal_id,
            "shelter_code": shelter_code,
            "detail_url": f"https://24petconnect.com/LostFound/Details/{shelter_code}/{animal_id}",
            **spans
        })
    return animals
```

---

## Standardized Data Schema (for aggregation)

```json
{
  "source": "24petconnect",
  "source_id": "3055840",
  "shelter_code": "Public",
  "type": "lost",
  "animal_type": "dog",
  "name": "Chase",
  "breed": "Yorkshire Terrier",
  "gender": "male",
  "age": null,
  "color": "Black and Tan",
  "status": "Reported Lost by the Owner",
  "days_missing": 2,
  "date_lost": "2026-03-22",
  "location_text": "1369 Iron Gate Blvd, Jonesboro, GA",
  "lat": null,
  "lon": null,
  "shelter_name": null,
  "photos": [
    "https://24petconnect.com/image/688554025",
    "https://24petconnect.com/image/688554024"
  ],
  "detail_url": "https://24petconnect.com/LostFound/Details/Public/3055840",
  "description": "Chase is male Yorkie and he is Black and Tan",
  "scraped_at": "2026-03-24T00:00:00Z"
}
```
