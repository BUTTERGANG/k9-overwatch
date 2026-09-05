"""Unit tests for EXIF GPS extraction and stripping (geocoding/exif_gps.py)."""
from __future__ import annotations

import io

import pytest
from PIL import Image

from k9overwatch.geocoding.exif_gps import extract_gps, strip_gps


def _jpeg_with_gps(lat: tuple, lon: tuple, lat_ref=b"N", lon_ref=b"E") -> bytes:
    """Craft a tiny JPEG carrying a known GPS EXIF block."""
    img = Image.new("RGB", (4, 4), color=(10, 20, 30))
    exif = Image.Exif()
    gps_ifd = {
        1: lat_ref.decode(),   # GPSLatitudeRef
        2: lat,                # GPSLatitude (DMS rationals)
        3: lon_ref.decode(),   # GPSLongitudeRef
        4: lon,                # GPSLongitude
    }
    exif[0x8825] = gps_ifd
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


def _plain_jpeg() -> bytes:
    img = Image.new("RGB", (4, 4))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


INDY_LAT = (39, 46, 6.0)      # 39.768333...
INDY_LON = (86, 9, 29.0)      # 86.158055...


class TestExtractGps:
    def test_extracts_north_east_coordinates(self):
        result = extract_gps(_jpeg_with_gps(INDY_LAT, INDY_LON))
        assert result is not None
        lat, lon = result
        assert lat == pytest.approx(39.76833, abs=1e-4)
        assert lon == pytest.approx(86.15806, abs=1e-4)

    def test_south_and_west_hemispheres_are_negative(self):
        result = extract_gps(
            _jpeg_with_gps((33, 52, 3.0), (151, 12, 26.0), b"S", b"W")
        )
        assert result is not None
        lat, lon = result
        assert lat == pytest.approx(-33.8675, abs=1e-4)
        assert lon == pytest.approx(-151.2072, abs=1e-4)

    def test_image_without_gps_returns_none(self):
        assert extract_gps(_plain_jpeg()) is None

    def test_corrupt_bytes_return_none(self):
        assert extract_gps(b"\xff\xd8corrupt-garbage") is None
        assert extract_gps(b"") is None

    def test_non_jpeg_data_returns_none(self):
        img = Image.new("RGB", (4, 4))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        assert extract_gps(buf.getvalue()) is None
        assert extract_gps(b"totally not an image") is None

    def test_out_of_bounds_coordinates_rejected(self):
        bogus = _jpeg_with_gps((91, 0, 0.0), (200, 0, 0.0))
        assert extract_gps(bogus) is None

    def test_partial_gps_tags_return_none(self):
        img = Image.new("RGB", (4, 4))
        exif = Image.Exif()
        exif[0x8825] = {1: "N", 2: INDY_LAT}  # no longitude tags
        buf = io.BytesIO()
        img.save(buf, format="JPEG", exif=exif)
        assert extract_gps(buf.getvalue()) is None


class TestStripGps:
    def test_strips_gps_from_jpeg(self):
        data = _jpeg_with_gps(INDY_LAT, INDY_LON)
        assert extract_gps(data) is not None
        stripped = strip_gps(data)
        assert extract_gps(stripped) is None
        # Still a decodable JPEG.
        img = Image.open(io.BytesIO(stripped))
        assert img.format == "JPEG"

    def test_plain_image_survives_roundtrip(self):
        data = _plain_jpeg()
        stripped = strip_gps(data)
        assert Image.open(io.BytesIO(stripped)).format == "JPEG"

    def test_undecodable_bytes_returned_unchanged(self):
        assert strip_gps(b"\x00\x01\x02") == b"\x00\x01\x02"
