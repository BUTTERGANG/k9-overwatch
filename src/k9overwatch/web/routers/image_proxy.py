"""
Image proxy — fetches pet photos from source domains and streams them back.

Benefits:
- Broken/removed images fail gracefully server-side (clients get 302 → placeholder)
- Hides source domain directly from page source (minor privacy improvement)
- Single place to add resizing, CDN caching, or rate limiting later

Security:
- Only allowed domains are proxied to prevent open-proxy abuse.
- Resolved IP is validated against RFC 1918 / loopback / link-local ranges to
  prevent DNS rebinding attacks where an allowed domain resolves to an internal
  address after the domain check passes.
"""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import logging
import socket
import time
from urllib.parse import unquote, urlparse

import aiohttp
from fastapi import APIRouter, Query
from fastapi.responses import RedirectResponse, Response

logger = logging.getLogger(__name__)

router = APIRouter()

# Only proxy images from known pet listing sources — prevents open-proxy abuse.
_ALLOWED_DOMAINS = frozenset({
    "www.pawboost.com",
    "pawboost.com",
    "images.pawboost.com",
    "cdn.pawboost.com",
    "photos.petfbi.org",
    "petfbi.org",
    "api.petfbi.org",
    "www.lostmydoggie.com",
    "lostmydoggie.com",
    "www.24petconnect.com",
    "24petconnect.com",
    "indylostpetalert.com",
    "www.indylostpetalert.com",
    "i0.wp.com",   # WordPress image CDN used by IndyLostPetAlert
    "i1.wp.com",
    "i2.wp.com",
    "i3.wp.com",
})

# Simple in-process cache: url_hash → (content_type, body, expires_at)
_CACHE: dict[str, tuple[str, bytes, float]] = {}
_CACHE_TTL_SECONDS = 3600  # 1 hour
_MAX_CACHE_ENTRIES = 500   # evict oldest when full

# Module-level aiohttp session — reused across requests per aiohttp best practice.
# Lazily initialised on first use and recreated if closed.
_http_session: aiohttp.ClientSession | None = None

_PLACEHOLDER = "/static/img/pet-placeholder.svg"
_MAX_BODY_BYTES = 5 * 1024 * 1024  # 5 MB


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _get_http_session() -> aiohttp.ClientSession:
    """Return the shared ClientSession, creating it if necessary."""
    global _http_session
    if _http_session is None or _http_session.closed:
        _http_session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10),
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; K9-Overwatch/1.0; image proxy)",
                "Accept": "image/*,*/*;q=0.8",
            },
        )
    return _http_session


def _is_private_address(ip_str: str) -> bool:
    """Return True if the IP string belongs to a non-routable range.

    Covers RFC 1918 private ranges, loopback, and link-local to block DNS
    rebinding attacks.
    """
    try:
        addr = ipaddress.ip_address(ip_str)
        return (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_reserved
            or addr.is_unspecified
        )
    except ValueError:
        # Unparseable — treat as unsafe
        return True


def _resolve_hostname(hostname: str) -> list[str]:
    """Resolve hostname to IP strings (blocking — must be called in executor)."""
    try:
        results = socket.getaddrinfo(hostname, None)
        return [r[4][0] for r in results]
    except socket.gaierror:
        return []


def _cache_get(key: str) -> tuple[str, bytes] | None:
    entry = _CACHE.get(key)
    if entry and entry[2] > time.monotonic():
        return entry[0], entry[1]
    if entry:
        del _CACHE[key]
    return None


def _cache_set(key: str, content_type: str, body: bytes) -> None:
    if len(_CACHE) >= _MAX_CACHE_ENTRIES:
        # Evict the oldest 10% by expiry time
        oldest = sorted(_CACHE.items(), key=lambda kv: kv[1][2])[: _MAX_CACHE_ENTRIES // 10]
        for k, _ in oldest:
            del _CACHE[k]
    _CACHE[key] = (content_type, body, time.monotonic() + _CACHE_TTL_SECONDS)


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.get("/proxy/image", include_in_schema=False)
async def proxy_image(url: str = Query(..., description="URL of the pet photo to proxy")):
    """
    Proxy a pet photo from a known source domain.
    On any error (403, 404, timeout, disallowed domain, private IP) redirects to
    the static placeholder so the browser always shows something.
    """
    decoded = unquote(url)

    # --- 1. Domain allowlist check -------------------------------------------
    try:
        parsed = urlparse(decoded)
        if parsed.scheme not in ("http", "https") or parsed.netloc not in _ALLOWED_DOMAINS:
            return RedirectResponse(_PLACEHOLDER, status_code=302)
    except Exception:
        return RedirectResponse(_PLACEHOLDER, status_code=302)

    hostname = parsed.hostname  # strips port if present

    # --- 2. SSRF guard: reject private/internal IPs after DNS resolution ------
    # Run blocking getaddrinfo in the default thread-pool executor so we do not
    # stall the event loop.
    try:
        loop = asyncio.get_event_loop()
        resolved_ips: list[str] = await loop.run_in_executor(
            None, _resolve_hostname, hostname
        )
    except Exception as exc:
        logger.debug("Image proxy: DNS resolution failed for %s: %s", hostname, exc)
        return RedirectResponse(_PLACEHOLDER, status_code=302)

    if not resolved_ips:
        logger.debug("Image proxy: no IPs resolved for %s", hostname)
        return RedirectResponse(_PLACEHOLDER, status_code=302)

    for ip in resolved_ips:
        if _is_private_address(ip):
            logger.warning(
                "Image proxy: SSRF attempt blocked — %s resolved to private IP %s",
                hostname,
                ip,
            )
            return RedirectResponse(_PLACEHOLDER, status_code=302)

    # --- 3. Cache lookup (SHA256 key) ----------------------------------------
    cache_key = hashlib.sha256(decoded.encode()).hexdigest()
    cached = _cache_get(cache_key)
    if cached:
        content_type, body = cached
        return Response(content=body, media_type=content_type)

    # --- 4. Fetch via shared session -----------------------------------------
    try:
        session = _get_http_session()
        per_request_headers = {"Referer": f"{parsed.scheme}://{parsed.netloc}/"}

        async with session.get(
            decoded,
            headers=per_request_headers,
            allow_redirects=True,
            max_redirects=3,
        ) as resp:
            if resp.status != 200:
                logger.debug("Image proxy: HTTP %s for %s", resp.status, decoded[:80])
                return RedirectResponse(_PLACEHOLDER, status_code=302)

            content_type = resp.headers.get("Content-Type", "image/jpeg")
            if not content_type.startswith("image/"):
                return RedirectResponse(_PLACEHOLDER, status_code=302)

            # --- 4a. Content-Length pre-flight check -------------------------
            # Reject before reading the body when the server advertises a size
            # that already exceeds our limit — avoids buffering a huge stream.
            content_length_header = resp.headers.get("Content-Length")
            if content_length_header is not None:
                try:
                    declared_size = int(content_length_header)
                    if declared_size > _MAX_BODY_BYTES:
                        logger.debug(
                            "Image proxy: Content-Length %d exceeds limit for %s",
                            declared_size,
                            decoded[:80],
                        )
                        return RedirectResponse(_PLACEHOLDER, status_code=302)
                except ValueError:
                    pass  # Malformed header — fall through to body-size check

            # --- 4b. Read body with size guard (handles chunked responses) ---
            body = await resp.read()
            if len(body) > _MAX_BODY_BYTES:
                logger.debug(
                    "Image proxy: body %d bytes exceeds limit for %s",
                    len(body),
                    decoded[:80],
                )
                return RedirectResponse(_PLACEHOLDER, status_code=302)

            _cache_set(cache_key, content_type, body)
            return Response(
                content=body,
                media_type=content_type,
                headers={"Cache-Control": "public, max-age=3600"},
            )

    except Exception as exc:
        logger.debug("Image proxy fetch failed for %s: %s", decoded[:80], exc)
        return RedirectResponse(_PLACEHOLDER, status_code=302)
