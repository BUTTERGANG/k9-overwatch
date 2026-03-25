from enum import StrEnum


class RecordType(StrEnum):
    LOST = "lost"
    FOUND = "found"
    SIGHTING = "sighting"
    ADOPTABLE = "adoptable"


class AnimalType(StrEnum):
    DOG = "dog"
    CAT = "cat"
    BIRD = "bird"
    RABBIT = "rabbit"
    OTHER = "other"


class Gender(StrEnum):
    MALE = "male"
    FEMALE = "female"
    UNKNOWN = "unknown"


class Size(StrEnum):
    XSMALL = "xsmall"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    XLARGE = "xlarge"
    XXLARGE = "xxlarge"


class GeocodeSource(StrEnum):
    GOOGLE = "google"
    NOMINATIM = "nominatim"
    ZIP_CENTROID = "zip_centroid"
    PETFBI_NATIVE = "petfbi_native"


class GeocodeConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
