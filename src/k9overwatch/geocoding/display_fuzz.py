"""Display-layer coordinate fuzzing for low-precision (ZIP-centroid) geocodes.

ZIP centroids place a pin at the geographic center of a ZIP code, which can
falsely imply street-level knowledge of where an animal was found. This module
offsets such pins by a deterministic 0.5–1 km within an annulus so the pin
doesn't sit exactly on the centroid, without moving it every page reload.

CRITICAL: fuzzing is display-only. The matching engine
(k9overwatch/matching/) must keep reading the TRUE record coordinates. Never
pass fuzzed coordinates into matching — see the comment in
matching/lost_found_matcher.py.
"""
from __future__ import annotations

import hashlib
import math

# Annulus bounds in meters.
MIN_OFFSET_M = 500.0
MAX_OFFSET_M = 1000.0

_EARTH_RADIUS_M = 6_371_000.0


def fuzz_offset_meters(source_id: str) -> tuple[float, float]:
    """Deterministic (dlat_m, dlon_m) offset for a record's source_id.

    Same input always yields the same offset, so a pin stays put across
    reloads but differs across records.
    """
    digest = hashlib.sha256(source_id.encode("utf-8")).digest()
    angle = (int.from_bytes(digest[:8], "big") / 2**64) * 2 * math.pi
    # Radius uniform in [MIN, MAX) annulus.
    frac = int.from_bytes(digest[8:16], "big") / 2**64
    radius = MIN_OFFSET_M + frac * (MAX_OFFSET_M - MIN_OFFSET_M)
    return (radius * math.sin(angle), radius * math.cos(angle))


def fuzz_lat_lon(
    lat: float, lon: float, source_id: str
) -> tuple[float, float]:
    """Offset (lat, lon) by the deterministic annulus offset for source_id."""
    dlat_m, dlon_m = fuzz_offset_meters(source_id)
    new_lat = lat + (dlat_m / _EARTH_RADIUS_M) * (180.0 / math.pi)
    cos_lat = max(abs(math.cos(math.radians(lat))), 1e-9)
    new_lon = lon + (dlon_m / (_EARTH_RADIUS_M * cos_lat)) * (180.0 / math.pi)
    # Clamp to valid ranges (Indy-area data will never hit this; belt & braces).
    new_lat = max(-90.0, min(90.0, new_lat))
    new_lon = max(-180.0, min(180.0, new_lon))
    return (new_lat, new_lon)


def offset_distance_m(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """Great-circle distance in meters (for tests)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(a))
