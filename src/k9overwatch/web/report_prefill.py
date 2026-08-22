"""
Ephemeral signed prefill tokens for one-tap "report via link" inbound flow.

A group admin builds a link like /report?prefill=<token> from a Facebook
post; the token carries a tiny prefill payload (record type, animal type,
primary color, location hint) that populates — but does not lock — the
report form fields.

Format: base64url(JSON).hex_hmac, signed with the same session-signing
secret as auth cookies. Tokens carry their issue time and expire after
PREFILL_TOKEN_TTL_DAYS days (default 7). Invalid/expired tokens are
silently ignored by the form.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

_ALLOWED_KEYS = ("record_type", "animal_type", "color_primary", "location_hint")
_MAX_AGE_SECONDS_DEFAULT = 7 * 24 * 3600


def _secret() -> bytes:
    from k9overwatch.web.auth import _SESSION_SECRET

    return _SESSION_SECRET.encode("utf-8")


def _max_age_seconds() -> int:
    try:
        return int(os.getenv("PREFILL_TOKEN_TTL_DAYS", "7")) * 24 * 3600
    except ValueError:
        return _MAX_AGE_SECONDS_DEFAULT


def make_prefill_token(data: dict[str, str]) -> str:
    """Sign a minimal prefill payload into an opaque URL-safe token."""
    clean = {k: str(data[k])[:200] for k in _ALLOWED_KEYS if data.get(k)}
    body = base64.urlsafe_b64encode(
        json.dumps({"d": clean, "iat": int(time.time())}, separators=(",", ":")).encode("utf-8")
    ).decode("ascii").rstrip("=")
    sig = hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def parse_prefill_token(token: str | None) -> dict[str, str] | None:
    """Return the prefill dict if the token is valid and unexpired, else None."""
    if not token or "." not in token:
        return None
    body, sig = token.rsplit(".", 1)
    expected = hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        padded = body + "=" * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        iat = int(payload["iat"])
        data = payload["d"]
        if not isinstance(data, dict):
            return None
    except Exception:
        return None
    if time.time() - iat > _max_age_seconds():
        return None
    return {k: str(data[k]) for k in _ALLOWED_KEYS if k in data}
