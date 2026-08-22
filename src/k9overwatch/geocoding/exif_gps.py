"""EXIF GPS extraction for owner-submitted photos.

Privacy contract (non-negotiable):
- Raw extracted coordinates are used ONLY to set the report's lat/lon fields,
  which then flow through the existing display rules (the "Exact location"
  badge treatment). They are never rendered at any higher precision than that
  treatment allows and never exposed as raw numbers beyond the standard pin.
- GPS EXIF tags are stripped from ALL stored photo bytes regardless of the
  user's consent choice (see strip_gps). Consent only controls whether the
  coordinates are *used* for geocoding, never whether they are retained.
"""
from __future__ import annotations

import io

from PIL import Image

# EXIF GPS IFD tag ids
_GPS_IFD_ID = 0x8825
_LAT_REF = 1
_LAT = 2
_LON_REF = 3
_LON = 4


def _dms_to_degrees(dms: tuple) -> float | None:
    """Convert an EXIF rational DMS triple to signed-capable decimal degrees.

    Accepts both (numerator, denominator) rationals and plain numbers.
    """
    try:
        values = []
        for component in dms[:3]:
            try:
                values.append(float(component))
                continue
            except TypeError:
                pass
            num, den = component
            if not den:
                return None
            values.append(float(num) / float(den))
        return values[0] + values[1] / 60.0 + values[2] / 3600.0
    except (TypeError, ValueError, IndexError):
        return None


def _signed(degrees: float | None, ref: object) -> float | None:
    if degrees is None:
        return None
    ref_text = str(ref).strip().upper() if ref is not None else ""
    if ref_text in {"S", "W"}:
        return -degrees
    return degrees


def extract_gps(data: bytes) -> tuple[float, float] | None:
    """Extract (lat, lon) from JPEG EXIF GPS data.

    Returns None cleanly for missing/corrupt data, non-JPEG images, images
    without GPS tags, or out-of-bounds coordinates.
    """
    if not data or not data.startswith(b"\xff\xd8"):
        return None
    try:
        img = Image.open(io.BytesIO(data))
        exif = img.getexif()
        gps_ifd = exif.get_ifd(_GPS_IFD_ID)
    except Exception:
        return None

    if not gps_ifd:
        return None

    lat = _signed(_dms_to_degrees(gps_ifd.get(_LAT, ())), gps_ifd.get(_LAT_REF))
    lon = _signed(_dms_to_degrees(gps_ifd.get(_LON, ())), gps_ifd.get(_LON_REF))
    if lat is None or lon is None:
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    return (lat, lon)


def strip_gps(data: bytes) -> bytes:
    """Return image bytes with all EXIF (including GPS) removed.

    Applied unconditionally to every stored upload. Re-encoding through Pillow
    without an ``exif=`` kwarg drops the full EXIF block, which guarantees no
    GPS metadata survives storage even if extraction heuristics miss a tag.
    If the bytes cannot be parsed as an image they are returned unchanged
    (callers have already run container signature validation).
    """
    try:
        img = Image.open(io.BytesIO(data))
        fmt = (img.format or "").upper()
        if fmt not in {"JPEG", "PNG", "WEBP"}:
            return data
        buffer = io.BytesIO()
        save_kwargs: dict = {}
        if fmt == "JPEG":
            save_kwargs["quality"] = 92
        img.save(buffer, format=fmt, **save_kwargs)  # no exif kwarg → EXIF dropped
        return buffer.getvalue()
    except Exception:
        return data
