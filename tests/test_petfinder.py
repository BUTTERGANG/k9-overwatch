"""Tests for the Petfinder API normalizer."""
from __future__ import annotations

from datetime import datetime

from k9overwatch.models.enums import AnimalType, Gender, RecordType, Size
from k9overwatch.normalizers.petfinder import (
    PetfinderNormalizer,
    _normalize_animal_type,
    _normalize_gender,
    _normalize_record_type,
    _normalize_size,
)

# ── Sample Petfinder API animal dict ──────────────────────────────────────────

PETFINDER_ANIMAL = {
    "id": 123456,
    "name": "Buddy",
    "type": "Dog",
    "breeds": {
        "primary": "Labrador Retriever",
        "secondary": "Mix",
    },
    "colors": {
        "primary": "Golden",
        "secondary": "White",
    },
    "gender": "Male",
    "size": "Large",
    "age": "Adult",
    "description": "Friendly dog who loves walks and belly rubs.",
    "photos": [
        {
            "small": "https://dl5zpyw5k3jeb.cloudfront.net/photos/small/123.jpg",
            "full": "https://dl5zpyw5k3jeb.cloudfront.net/photos/full/123.jpg",
        },
        {
            "small": "https://dl5zpyw5k3jeb.cloudfront.net/photos/small/124.jpg",
            "full": "https://dl5zpyw5k3jeb.cloudfront.net/photos/full/124.jpg",
        },
    ],
    "contact": {
        "email": "shelter@example.com",
        "phone": "555-0100",
    },
    "location": "Indianapolis, IN 46201",
    "status": "adoptable",
    "published_at": "2026-08-15T12:00:00Z",
    "status_changed_at": "2026-08-16T08:00:00Z",
    "distance": 5.2,
}

PETFINDER_LOST = {
    "id": 789012,
    "name": "Whiskers",
    "type": "Cat",
    "breeds": {"primary": "Domestic Shorthair", "secondary": None},
    "colors": {"primary": "Black", "secondary": None},
    "gender": "Female",
    "size": "Small",
    "age": "Senior",
    "description": "Black cat, last seen near downtown.",
    "photos": [],
    "contact": {"email": "owner@example.com", "phone": None},
    "location": "Indianapolis, IN",
    "status": "lost",
    "published_at": "2026-08-14T18:30:00Z",
    "status_changed_at": None,
    "distance": None,
}

PETFINDER_NO_PHOTOS = {
    "id": 345678,
    "name": None,
    "type": None,
    "breeds": {"primary": None, "secondary": None},
    "colors": {"primary": None, "secondary": None},
    "gender": None,
    "size": None,
    "age": None,
    "description": None,
    "photos": None,
    "contact": None,
    "location": None,
    "status": "adoptable",
    "published_at": None,
    "status_changed_at": None,
    "distance": None,
}


class TestPetfinderNormalizer:
    def setup_method(self):
        self.normalizer = PetfinderNormalizer()

    # ── Basic identity ──────────────────────────────────────────────────────

    def test_source_name(self):
        record = self.normalizer.normalize(PETFINDER_ANIMAL)
        assert record.source == "petfinder"

    def test_source_id(self):
        record = self.normalizer.normalize(PETFINDER_ANIMAL)
        assert record.source_id == "123456"

    def test_source_url(self):
        record = self.normalizer.normalize(PETFINDER_ANIMAL)
        assert record.source_url == "https://www.petfinder.com/animal/123456"

    # ── Animal characteristics ──────────────────────────────────────────────

    def test_name(self):
        record = self.normalizer.normalize(PETFINDER_ANIMAL)
        assert record.name == "Buddy"

    def test_animal_type(self):
        record = self.normalizer.normalize(PETFINDER_ANIMAL)
        assert record.animal_type == "dog"

    def test_breed(self):
        record = self.normalizer.normalize(PETFINDER_ANIMAL)
        assert record.breed == "Labrador Retriever"

    def test_breed_secondary(self):
        record = self.normalizer.normalize(PETFINDER_ANIMAL)
        assert record.breed_secondary == "Mix"

    def test_color_primary(self):
        record = self.normalizer.normalize(PETFINDER_ANIMAL)
        assert record.color_primary == "Golden"

    def test_color_secondary(self):
        record = self.normalizer.normalize(PETFINDER_ANIMAL)
        assert record.color_secondary == "White"

    def test_gender(self):
        record = self.normalizer.normalize(PETFINDER_ANIMAL)
        assert record.gender == "male"

    def test_size(self):
        record = self.normalizer.normalize(PETFINDER_ANIMAL)
        assert record.size == "large"

    def test_age(self):
        record = self.normalizer.normalize(PETFINDER_ANIMAL)
        assert record.age == "Adult"

    # ── Record type ─────────────────────────────────────────────────────────

    def test_record_type_adoptable(self):
        record = self.normalizer.normalize(PETFINDER_ANIMAL)
        assert record.record_type == "adoptable"

    def test_record_type_lost(self):
        record = self.normalizer.normalize(PETFINDER_LOST)
        assert record.record_type == "lost"

    # ── Contact ─────────────────────────────────────────────────────────────

    def test_contact_email(self):
        record = self.normalizer.normalize(PETFINDER_ANIMAL)
        assert record.contact_email == "shelter@example.com"

    def test_contact_phone(self):
        record = self.normalizer.normalize(PETFINDER_ANIMAL)
        assert record.contact_phone == "555-0100"

    # ── Location ────────────────────────────────────────────────────────────

    def test_location_text(self):
        record = self.normalizer.normalize(PETFINDER_ANIMAL)
        assert record.location_text == "Indianapolis, IN 46201"

    def test_location_city_state_zip(self):
        record = self.normalizer.normalize(PETFINDER_ANIMAL)
        assert record.city == "Indianapolis"
        assert record.state == "IN"
        assert record.zip == "46201"

    def test_location_city_state_only(self):
        record = self.normalizer.normalize(PETFINDER_LOST)
        assert record.city == "Indianapolis"
        assert record.state == "IN"
        assert record.zip is None

    # ── Photos ──────────────────────────────────────────────────────────────

    def test_photos(self):
        record = self.normalizer.normalize(PETFINDER_ANIMAL)
        assert len(record.photos) == 2
        assert "full/123.jpg" in record.photos[0]

    def test_thumbnail_url(self):
        record = self.normalizer.normalize(PETFINDER_ANIMAL)
        assert record.thumbnail_url is not None
        assert "small/123.jpg" in record.thumbnail_url

    def test_no_photos(self):
        record = self.normalizer.normalize(PETFINDER_LOST)
        assert record.photos == []
        assert record.thumbnail_url is None

    # ── Dates ───────────────────────────────────────────────────────────────

    def test_date_posted(self):
        record = self.normalizer.normalize(PETFINDER_ANIMAL)
        assert record.date_posted == datetime(2026, 8, 15, 12, 0, 0)

    def test_date_updated(self):
        record = self.normalizer.normalize(PETFINDER_ANIMAL)
        assert record.date_updated == datetime(2026, 8, 16, 8, 0, 0)

    # ── Description ─────────────────────────────────────────────────────────

    def test_description(self):
        record = self.normalizer.normalize(PETFINDER_ANIMAL)
        assert record.description is not None
        assert "Friendly dog" in record.description

    # ── Status ──────────────────────────────────────────────────────────────

    def test_status(self):
        record = self.normalizer.normalize(PETFINDER_ANIMAL)
        assert record.status == "adoptable"

    # ── Cat type ────────────────────────────────────────────────────────────

    def test_cat_type(self):
        record = self.normalizer.normalize(PETFINDER_LOST)
        assert record.animal_type == "cat"
        assert record.gender == "female"
        assert record.size == "small"

    # ── Edge case: sparse data ──────────────────────────────────────────────

    def test_sparse_record(self):
        record = self.normalizer.normalize(PETFINDER_NO_PHOTOS)
        assert record.source_id == "345678"
        assert record.name is None
        assert record.animal_type is None
        assert record.breed is None
        assert record.gender is None
        assert record.size is None
        assert record.photos == []
        assert record.thumbnail_url is None
        assert record.contact_email is None
        assert record.contact_phone is None
        assert record.location_text is None
        assert record.date_posted is None

    # ── Raw payload ─────────────────────────────────────────────────────────

    def test_raw_payload_preserved(self):
        record = self.normalizer.normalize(PETFINDER_ANIMAL)
        assert record.raw == PETFINDER_ANIMAL


# ── Helper function tests ─────────────────────────────────────────────────────


class TestNormalizeHelpers:
    def test_animal_type_dog(self):
        assert _normalize_animal_type("Dog") == AnimalType.DOG

    def test_animal_type_cat(self):
        assert _normalize_animal_type("Cat") == AnimalType.CAT

    def test_animal_type_none(self):
        assert _normalize_animal_type(None) is None

    def test_animal_type_unknown(self):
        assert _normalize_animal_type("Lizard") == AnimalType.OTHER

    def test_gender_male(self):
        assert _normalize_gender("Male") == Gender.MALE

    def test_gender_female(self):
        assert _normalize_gender("Female") == Gender.FEMALE

    def test_gender_unknown(self):
        assert _normalize_gender("Unknown") == Gender.UNKNOWN

    def test_gender_none(self):
        assert _normalize_gender(None) is None

    def test_size_small(self):
        assert _normalize_size("Small") == Size.SMALL

    def test_size_large(self):
        assert _normalize_size("Large") == Size.LARGE

    def test_size_none(self):
        assert _normalize_size(None) is None

    def test_record_type_adoptable(self):
        assert _normalize_record_type("adoptable", "Dog") == RecordType.ADOPTABLE

    def test_record_type_lost(self):
        assert _normalize_record_type("lost", "Cat") == RecordType.LOST

    def test_record_type_found(self):
        assert _normalize_record_type("found", "Dog") == RecordType.FOUND

    def test_record_type_none(self):
        assert _normalize_record_type(None, None) == RecordType.ADOPTABLE