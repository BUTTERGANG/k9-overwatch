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
_SESSION_SECRET = os.getenv("SESSION_SECRET", "dev-insecure-secret-change-me")


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


def new_unsubscribe_token() -> str:
    return secrets.token_urlsafe(24)
