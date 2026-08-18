"""
Account auth: password hashing (stdlib scrypt — no external dependency) and
session-cookie helpers. Deliberately minimal and non-spammy by design.

Sessions are signed cookies holding the user id; the secret comes from
SESSION_SECRET (falls back to a dev default so local runs work without config).
For a public deploy, set SESSION_SECRET to a long random value.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets

COOKIE_NAME = "k9_session"
_DEFAULT_SESSION_SECRET = "dev-insecure-secret-change-me"
_ENVIRONMENT = os.getenv("ENVIRONMENT", os.getenv("APP_ENV", "development")).lower()
_IS_PRODUCTION = _ENVIRONMENT in {"production", "prod"}
_SESSION_SECRET = os.getenv("SESSION_SECRET", "")
if _IS_PRODUCTION and (not _SESSION_SECRET or _SESSION_SECRET == _DEFAULT_SESSION_SECRET):
    raise RuntimeError("SESSION_SECRET must be explicitly configured in production")
if not _SESSION_SECRET:
    _SESSION_SECRET = _DEFAULT_SESSION_SECRET


def is_production() -> bool:
    """Return whether the application is running in a production environment."""
    return _IS_PRODUCTION


def hash_password(password: str) -> str:
    """Return a scrypt hash string: scrypt$<n>:<r>:<p>$<salt_hex>$<hash_hex>."""
    salt = secrets.token_bytes(16)
    n, r, p = 16384, 8, 1
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=32)
    return f"scrypt${n}:{r}:{p}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, params, salt_hex, hash_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        n, r, p = (int(x) for x in params.split(":"))
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
        dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=32)
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


def make_session_token(user_id: str) -> str:
    """Signed cookie value: <user_id>.<hmac>."""
    sig = hmac.new(_SESSION_SECRET.encode(), user_id.encode(), hashlib.sha256).hexdigest()
    return f"{user_id}.{sig}"


def read_session_token(token: str | None) -> str | None:
    """Return the user_id if the token is valid, else None."""
    if not token or "." not in token:
        return None
    user_id, sig = token.rsplit(".", 1)
    expected = hmac.new(_SESSION_SECRET.encode(), user_id.encode(), hashlib.sha256).hexdigest()
    if hmac.compare_digest(sig, expected):
        return user_id
    return None


def make_csrf_token(subject: str) -> str:
    """Create a stateless CSRF token bound to a session subject."""
    payload = f"csrf:{subject}"
    signature = hmac.new(
        _SESSION_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return f"{subject}.{signature}"


def csrf_token_for(user_id: str) -> str:
    """Return the CSRF token to embed in forms for a logged-in user."""
    return make_csrf_token(user_id)


def validate_csrf_token(token: str | None, subject: str) -> bool:
    if not token or "." not in token:
        return False
    token_subject, signature = token.rsplit(".", 1)
    if token_subject != subject:
        return False
    payload = f"csrf:{token_subject}"
    expected = hmac.new(
        _SESSION_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(signature, expected)


def new_unsubscribe_token() -> str:
    return secrets.token_urlsafe(24)
