"""Tests for all five source normalizers."""
from __future__ import annotations

from datetime import date

import pytest
from bs4 import BeautifulSoup

from k9overwatch.models.enums import AnimalType, Gender, RecordType
from k9overwatch.normalizers.indy_lost_pet_alert import IndyNormalizer, _strip_html, _parse_date
from k9overwatch.normalizers.petconnect24 import PetConnect24Normalizer, _infer_animal_type_from_breed
from k9overwatch.normalizers.pawboost import PawBoostNormalizer, _parse_city_state_zip
from k9overwatch.normalizers.petfbi import PetFBINormalizer, _normalize_animal_type, _normalize_record_type
from k9overwatch.normalizers.lostmydoggie import LostMyDoggieNormalizer


# ── IndyLostPetAlert ──────────────────────────────────────────────────────────

INDY_POST = {
    "id": 12345,
    "title": {"rendered": "Alert #96891 — Lost Dog"},
    "content": {
        "rendered": (
            # Location block (terminated by Contact Information header)
            "<p>Location Information : 4521 N. Keystone Ave, Indianapolis, Marion County</p>"
            "<p>Contact Information :</p>"
            # Pet detail fields
            "<p>Pet\u2019s Name : Buddy Color of Pet : Black, White</p>"
            "<p>Breed : Labrador Mix Size : Medium</p>"
            "<p>Date Pet Went Missing : 03/20/2026</p>"
            "<p>Approximate Time Pet Went Missing : 6:30 pm</p>"
            "<p>Gender : Male Buddy is very friendly and responds to his name.</p>"
            # Phone as last field so \s*$ lookahead fires
            "<p>Phone : 317-555-0199</p>"
        )
    },
    "categories": [19, 24],  # lost, dog
    "tags": [223, 234],       # Black, White
    "date": "2026-03-20T18:00:00",
    "modified": "2026-03-21T08:00:00",
    "link": "https://indylostpetalert.com/?p=12345",
    "jetpack_featured_media_url": "https://indylostpetalert.com/wp-content/uploads/buddy.jpg",
}


class TestIndyNormalizer:
    def setup_method(self):
        self.normalizer = IndyNormalizer()

    def test_basic_normalization(self):
        record = self.normalizer.normalize(INDY_POST)
        assert record.source == "indylostpetalert"
        assert record.source_id == "12345"
        assert record.record_type == "lost"
        assert record.animal_type == "dog"

    def test_alert_number(self):
        record = self.normalizer.normalize(INDY_POST)
        assert record.alert_number == "96891"

    def test_name_parsing(self):
        record = self.normalizer.normalize(INDY_POST)
        assert record.name == "Buddy"

    def test_breed_parsing(self):
        record = self.normalizer.normalize(INDY_POST)
        assert record.breed == "Labrador Mix"

    def test_gender_parsing(self):
        record = self.normalizer.normalize(INDY_POST)
        assert record.gender == "male"

    def test_date_parsing(self):
        record = self.normalizer.normalize(INDY_POST)
        assert record.date_event == date(2026, 3, 20)

    def test_location_parsing(self):
        record = self.normalizer.normalize(INDY_POST)
        assert record.location_text is not None
        assert "4521" in record.location_text
        assert record.county == "Marion County"
        assert record.state == "IN"

    def test_phone_parsing(self):
        record = self.normalizer.normalize(INDY_POST)
        assert record.contact_phone is not None
        assert "317" in record.contact_phone

    def test_color_from_tags(self):
        record = self.normalizer.normalize(INDY_POST)
        assert record.color_primary == "Black"
        assert record.color_secondary == "White"

    def test_photo_url(self):
        record = self.normalizer.normalize(INDY_POST)
        assert len(record.photos) == 1
        assert "buddy.jpg" in record.photos[0]

    def test_dates_posted(self):
        record = self.normalizer.normalize(INDY_POST)
        assert record.date_posted is not None
        assert record.date_updated is not None

    def test_strip_html_removes_tags(self):
        html = "<p>Hello <b>World</b></p>"
        assert _strip_html(html) == "Hello World"

    def test_strip_html_normalizes_curly_apostrophe(self):
        html = "<p>Pet\u2019s Name</p>"
        assert "Pet's Name" in _strip_html(html)

    def test_parse_date_slash_format(self):
        assert _parse_date("03/20/2026") == date(2026, 3, 20)

    def test_parse_date_iso_format(self):
        assert _parse_date("2026-03-20") == date(2026, 3, 20)

    def test_parse_date_invalid(self):
        assert _parse_date("not-a-date") is None
        assert _parse_date(None) is None

    def test_found_record_type(self):
        post = dict(INDY_POST)
        post["categories"] = [20, 27]  # found, found dog
        record = self.normalizer.normalize(post)
        assert record.record_type == "found"

    def test_sighting_record_type(self):
        post = dict(INDY_POST)
        post["categories"] = [21, 33]  # sighting, dog sighting
        record = self.normalizer.normalize(post)
        assert record.record_type == "sighting"

    def test_cat_animal_type(self):
        post = dict(INDY_POST)
        post["categories"] = [19, 25]  # lost, cat
        record = self.normalizer.normalize(post)
        assert record.animal_type == "cat"


# ── 24petconnect ──────────────────────────────────────────────────────────────

CARD_HTML_LOST = """
<div class="gridResult" id="Result_654321"
     onclick="goToDetails('INDY01', '654321')">
  <img src="/image/abc123" alt="Pet photo" />
  <div>
    <span>Name : Chase</span>
    <span>Breed : German Shepherd</span>
    <span>Gender : M</span>
    <span>Days Since Lost : 5</span>
    <span>Location Lost : Near Fall Creek, Indianapolis IN</span>
  </div>
</div>
"""

CARD_HTML_ADOPT = """
<div class="gridResult" id="Result_111222"
     onclick="goToDetails('SHELT1', '111222')">
  <img src="/image/xyz789" alt="Pet photo" />
  <div>
    <span>Name : Whiskers</span>
    <span>Animal type : Cat</span>
    <span>Breed : Domestic Shorthair</span>
    <span>Gender : F</span>
    <span>Age : 2 years</span>
    <span>Size : Medium (25-50 lbs)</span>
    <span>Located at : Happy Paws Shelter</span>
  </div>
</div>
"""


class TestPetConnect24Normalizer:
    def setup_method(self):
        self.normalizer = PetConnect24Normalizer()

    def _card(self, html: str):
        return BeautifulSoup(html, "html.parser").find("div")

    def test_source_name(self):
        record = self.normalizer.normalize(self._card(CARD_HTML_LOST), "LOST")
        assert record.source == "24petconnect"

    def test_source_id_from_onclick(self):
        record = self.normalizer.normalize(self._card(CARD_HTML_LOST), "LOST")
        assert record.source_id == "654321"

    def test_shelter_code_from_onclick(self):
        record = self.normalizer.normalize(self._card(CARD_HTML_LOST), "LOST")
        assert record.shelter_code == "INDY01"

    def test_source_url_built(self):
        record = self.normalizer.normalize(self._card(CARD_HTML_LOST), "LOST")
        assert "INDY01" in record.source_url
        assert "654321" in record.source_url

    def test_name_field(self):
        record = self.normalizer.normalize(self._card(CARD_HTML_LOST), "LOST")
        assert record.name == "Chase"

    def test_breed_field(self):
        record = self.normalizer.normalize(self._card(CARD_HTML_LOST), "LOST")
        assert record.breed == "German Shepherd"

    def test_gender_male(self):
        record = self.normalizer.normalize(self._card(CARD_HTML_LOST), "LOST")
        assert record.gender == "male"

    def test_gender_female(self):
        record = self.normalizer.normalize(self._card(CARD_HTML_ADOPT), "ADOPT")
        assert record.gender == "female"

    def test_record_type_lost(self):
        record = self.normalizer.normalize(self._card(CARD_HTML_LOST), "LOST")
        assert record.record_type == "lost"

    def test_record_type_adoptable(self):
        record = self.normalizer.normalize(self._card(CARD_HTML_ADOPT), "ADOPT")
        assert record.record_type == "adoptable"

    def test_animal_type_from_field(self):
        record = self.normalizer.normalize(self._card(CARD_HTML_ADOPT), "ADOPT")
        assert record.animal_type == "cat"

    def test_animal_type_inferred_from_breed(self):
        record = self.normalizer.normalize(self._card(CARD_HTML_LOST), "LOST")
        # German Shepherd → dog via breed fragments
        assert record.animal_type == "dog"

    def test_days_since_lost(self):
        record = self.normalizer.normalize(self._card(CARD_HTML_LOST), "LOST")
        assert record.days_since_event == 5

    def test_photo_url(self):
        record = self.normalizer.normalize(self._card(CARD_HTML_LOST), "LOST")
        assert record.photos
        assert "/image/abc123" in record.photos[0]

    def test_location_lost(self):
        record = self.normalizer.normalize(self._card(CARD_HTML_LOST), "LOST")
        assert record.location_text is not None
        assert "Fall Creek" in record.location_text

    def test_infer_cat_from_shorthair(self):
        assert _infer_animal_type_from_breed("Domestic Shorthair") == AnimalType.CAT

    def test_infer_dog_from_retriever(self):
        assert _infer_animal_type_from_breed("Golden Retriever") == AnimalType.DOG

    def test_infer_none_from_unknown(self):
        assert _infer_animal_type_from_breed("Unknown Breed") is None


# ── PawBoost ──────────────────────────────────────────────────────────────────

PAWBOOST_RAW = {
    "pet_id": "PB-7890",
    "name": "Max",
    "details": ["Dog", "Male"],
    "location_city": "Indianapolis, IN 46220",
    "location_text": "Near Broad Ripple, Indianapolis IN",
    "date_lost_text": "March 19, 2026",
    "description": "Golden Retriever, friendly, wearing blue collar.",
    "full_photo_url": "https://img-cdn.pawboost.com/full/123.jpg",
    "thumbnail_url": "https://img-cdn.pawboost.com/thumb/123.jpg",
    "detail_url": "https://www.pawboost.com/landing/pet/abc123/lost-max-indianapolis-in-46220",
    "facebook_post_url": "https://fb.com/post/123",
}


class TestPawBoostNormalizer:
    def setup_method(self):
        self.normalizer = PawBoostNormalizer()

    def test_source_name(self):
        record = self.normalizer.normalize(PAWBOOST_RAW, "lost")
        assert record.source == "pawboost"

    def test_source_id(self):
        record = self.normalizer.normalize(PAWBOOST_RAW, "lost")
        assert record.source_id == "PB-7890"

    def test_name(self):
        record = self.normalizer.normalize(PAWBOOST_RAW, "lost")
        assert record.name == "Max"

    def test_animal_type_from_details(self):
        record = self.normalizer.normalize(PAWBOOST_RAW, "lost")
        assert record.animal_type == "dog"

    def test_gender_from_details(self):
        record = self.normalizer.normalize(PAWBOOST_RAW, "lost")
        assert record.gender == "male"

    def test_record_type_lost(self):
        record = self.normalizer.normalize(PAWBOOST_RAW, "lost")
        assert record.record_type == "lost"

    def test_record_type_found(self):
        record = self.normalizer.normalize(PAWBOOST_RAW, "found")
        assert record.record_type == "found"

    def test_date_parsing(self):
        record = self.normalizer.normalize(PAWBOOST_RAW, "lost")
        assert record.date_event == date(2026, 3, 19)

    def test_location_parsed(self):
        record = self.normalizer.normalize(PAWBOOST_RAW, "lost")
        assert record.city == "Indianapolis"
        assert record.state == "IN"
        assert record.zip == "46220"

    def test_photo_url(self):
        record = self.normalizer.normalize(PAWBOOST_RAW, "lost")
        assert len(record.photos) == 1
        assert "full" in record.photos[0]

    def test_thumbnail_url(self):
        record = self.normalizer.normalize(PAWBOOST_RAW, "lost")
        assert record.thumbnail_url is not None
        assert "thumb" in record.thumbnail_url

    def test_parse_city_state_zip(self):
        city, state, zip_code = _parse_city_state_zip("Indianapolis, IN 46220")
        assert city == "Indianapolis"
        assert state == "IN"
        assert zip_code == "46220"

    def test_parse_city_state_no_zip(self):
        # The regex requires whitespace after the 2-letter state code before the (optional) ZIP.
        # "City, ST" with no ZIP and no trailing space falls through to the else branch.
        city, state, zip_code = _parse_city_state_zip("Carmel, IN")
        # Raw string returned; state/zip not parsed without a space+ZIP present
        assert city == "Carmel, IN"
        assert state is None
        assert zip_code is None

    def test_parse_city_state_none(self):
        city, state, zip_code = _parse_city_state_zip(None)
        assert city is None

    def test_female_gender(self):
        raw = dict(PAWBOOST_RAW)
        raw["details"] = ["Cat", "Female"]
        record = self.normalizer.normalize(raw, "found")
        assert record.gender == "female"
        assert record.animal_type == "cat"


# ── PetFBI ────────────────────────────────────────────────────────────────────

PETFBI_REPORT = {
    "report_id": 987654,
    "animal_name": "Rex",
    "species": 2,             # dog (integer)
    "report_type": 1,         # lost (integer)
    "status": 0,
    "event_date": "2026-03-15",
    "last_updated": "2026-03-16T10:00:00",
    "breedlabel1": "Golden Retriever",
    "breedlabel2": None,
    "colorlabel1": "Golden",
    "colorlabel2": None,
    "colorlabel3": None,
    "markings": "White patch on chest",
    "collar": "Red collar",
    "gender": "male",
    "age": "3 years",
    "comments": "Very friendly, responds to Rex.",
    "location_comments": "Near Broad Ripple Park",
    "picture_file": "/wp-content/uploads/rex.jpg",
    "public_email": "owner@example.com",
    "contact_name": "John Smith",
    "geo_latitude": 39.8689,
    "geo_longitude": -86.1397,
}


class TestPetFBINormalizer:
    def setup_method(self):
        self.normalizer = PetFBINormalizer()

    def test_source_name(self):
        record = self.normalizer.normalize(PETFBI_REPORT)
        assert record.source == "petfbi"

    def test_source_id(self):
        record = self.normalizer.normalize(PETFBI_REPORT)
        assert record.source_id == "987654"

    def test_name(self):
        record = self.normalizer.normalize(PETFBI_REPORT)
        assert record.name == "Rex"

    def test_species_integer(self):
        record = self.normalizer.normalize(PETFBI_REPORT)
        assert record.animal_type == "dog"

    def test_report_type_integer(self):
        record = self.normalizer.normalize(PETFBI_REPORT)
        assert record.record_type == "lost"

    def test_report_type_found_integer(self):
        report = dict(PETFBI_REPORT)
        report["report_type"] = 2
        record = self.normalizer.normalize(report)
        assert record.record_type == "found"

    def test_sighting_integer(self):
        report = dict(PETFBI_REPORT)
        report["report_type"] = 3
        record = self.normalizer.normalize(report)
        assert record.record_type == "sighting"

    def test_cat_species_integer(self):
        report = dict(PETFBI_REPORT)
        report["species"] = 1
        record = self.normalizer.normalize(report)
        assert record.animal_type == "cat"

    def test_date_event(self):
        record = self.normalizer.normalize(PETFBI_REPORT)
        assert record.date_event == date(2026, 3, 15)

    def test_coordinates_preserved(self):
        record = self.normalizer.normalize(PETFBI_REPORT)
        assert record.lat == 39.8689
        assert record.lon == -86.1397

    def test_geocode_source_native(self):
        record = self.normalizer.normalize(PETFBI_REPORT)
        assert record.geocode_source == "petfbi_native"
        assert record.geocode_confidence == "high"

    def test_no_coordinates(self):
        report = dict(PETFBI_REPORT)
        report["geo_latitude"] = None
        report["geo_longitude"] = None
        record = self.normalizer.normalize(report)
        assert record.lat is None
        assert record.geocode_source is None

    def test_breed(self):
        record = self.normalizer.normalize(PETFBI_REPORT)
        assert record.breed == "Golden Retriever"

    def test_color_primary(self):
        record = self.normalizer.normalize(PETFBI_REPORT)
        assert record.color_primary == "Golden"

    def test_gender(self):
        record = self.normalizer.normalize(PETFBI_REPORT)
        assert record.gender == "male"

    def test_description_combined(self):
        record = self.normalizer.normalize(PETFBI_REPORT)
        assert "Very friendly" in record.description
        assert "Red collar" in record.description
        assert "Broad Ripple" in record.description

    def test_photo_url_absolute(self):
        record = self.normalizer.normalize(PETFBI_REPORT)
        assert record.photos[0].startswith("https://petfbi.org")

    def test_contact_email(self):
        record = self.normalizer.normalize(PETFBI_REPORT)
        assert record.contact_email == "owner@example.com"

    def test_status_as_string(self):
        record = self.normalizer.normalize(PETFBI_REPORT)
        assert record.status == "0"

    def test_normalize_animal_type_string_fallback(self):
        assert _normalize_animal_type("dog") == AnimalType.DOG
        assert _normalize_animal_type("cat") == AnimalType.CAT
        assert _normalize_animal_type(2) == AnimalType.DOG

    def test_normalize_record_type_string_fallback(self):
        assert _normalize_record_type("lost") == RecordType.LOST
        assert _normalize_record_type("found") == RecordType.FOUND
        assert _normalize_record_type(1) == RecordType.LOST


# ── LostMyDoggie ─────────────────────────────────────────────────────────────

LOSTMYDOGGIE_DATA = {
    "pet_id": "473213",
    "name": "Draco",
    "status_line": "Lost \xa0Male Dog",
    "location_raw": "INDIANAPOLIS, IN\n46254",
    "details": ["Siberian Husky", "White, Brown", "Lost: 2025-12-05"],
    "thumbnail_url": "https://www.lostmydoggie.com/pet_images/thumbs/473213.jpg",
    "full_photo_url": "https://www.lostmydoggie.com/pet_images/473213.jpg",
    "detail_url": "https://www.lostmydoggie.com/details.cfm?petid=473213",
}


class TestLostMyDoggieNormalizer:
    def setup_method(self):
        self.normalizer = LostMyDoggieNormalizer()

    def test_source_name(self):
        record = self.normalizer.normalize(LOSTMYDOGGIE_DATA, "dog", "lost")
        assert record.source == "lostmydoggie"

    def test_source_id(self):
        record = self.normalizer.normalize(LOSTMYDOGGIE_DATA, "dog", "lost")
        assert record.source_id == "473213"

    def test_name(self):
        record = self.normalizer.normalize(LOSTMYDOGGIE_DATA, "dog", "lost")
        assert record.name == "Draco"

    def test_animal_type_dog(self):
        record = self.normalizer.normalize(LOSTMYDOGGIE_DATA, "dog", "lost")
        assert record.animal_type == "dog"

    def test_animal_type_cat(self):
        record = self.normalizer.normalize(LOSTMYDOGGIE_DATA, "cat", "lost")
        assert record.animal_type == "cat"

    def test_record_type_lost(self):
        record = self.normalizer.normalize(LOSTMYDOGGIE_DATA, "dog", "lost")
        assert record.record_type == "lost"

    def test_record_type_found(self):
        record = self.normalizer.normalize(LOSTMYDOGGIE_DATA, "dog", "found")
        assert record.record_type == "found"

    def test_gender_from_status_line(self):
        record = self.normalizer.normalize(LOSTMYDOGGIE_DATA, "dog", "lost")
        assert record.gender == "male"

    def test_female_gender(self):
        data = dict(LOSTMYDOGGIE_DATA)
        data["status_line"] = "Lost \xa0Female Dog"
        record = self.normalizer.normalize(data, "dog", "lost")
        assert record.gender == "female"

    def test_location_text(self):
        record = self.normalizer.normalize(LOSTMYDOGGIE_DATA, "dog", "lost")
        assert record.location_text == "INDIANAPOLIS, IN"

    def test_zip_code(self):
        record = self.normalizer.normalize(LOSTMYDOGGIE_DATA, "dog", "lost")
        assert record.zip == "46254"

    def test_breed(self):
        record = self.normalizer.normalize(LOSTMYDOGGIE_DATA, "dog", "lost")
        assert record.breed == "Siberian Husky"

    def test_primary_color(self):
        record = self.normalizer.normalize(LOSTMYDOGGIE_DATA, "dog", "lost")
        assert record.color_primary == "White"

    def test_secondary_color(self):
        record = self.normalizer.normalize(LOSTMYDOGGIE_DATA, "dog", "lost")
        assert record.color_secondary == "Brown"

    def test_date_event(self):
        record = self.normalizer.normalize(LOSTMYDOGGIE_DATA, "dog", "lost")
        assert record.date_event == date(2025, 12, 5)

    def test_full_photo_url(self):
        record = self.normalizer.normalize(LOSTMYDOGGIE_DATA, "dog", "lost")
        assert record.photos[0] == "https://www.lostmydoggie.com/pet_images/473213.jpg"

    def test_thumbnail_url(self):
        record = self.normalizer.normalize(LOSTMYDOGGIE_DATA, "dog", "lost")
        assert "thumbs" in record.thumbnail_url

    def test_country_us(self):
        record = self.normalizer.normalize(LOSTMYDOGGIE_DATA, "dog", "lost")
        assert record.country == "US"

    def test_no_pet_id_returns_none(self):
        data = dict(LOSTMYDOGGIE_DATA)
        data["pet_id"] = None
        result = self.normalizer.normalize(data, "dog", "lost")
        assert result is None

    def test_detail_url(self):
        record = self.normalizer.normalize(LOSTMYDOGGIE_DATA, "dog", "lost")
        assert "petid=473213" in record.source_url
