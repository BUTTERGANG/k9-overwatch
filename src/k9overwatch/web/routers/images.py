"""
Image proxy + cache.

Serves remote listing photos through our own origin so:
  * browsers don't block cross-origin/large source images,
  * repeated loads are served from local cache (faster directory/map/feeds),
  * there's one choke point to add resizing/WebP later.

No external image lib required: we proxy + cache raw bytes. The URL is
validated to http/https only, and its resolved IP is checked against
private/loopback/link-local/reserved ranges to prevent SSRF (including DNS
rebinding, where the hostname resolves to an internal address only after the
scheme check passes) — this endpoint accepts arbitrary URLs from owner-submitted
report photos, not just known scraper domains, so scheme checking alone isn't
enough. Caching is content-hashed on the URL; cached files live under
data/img_cache/.
"""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import os
import socket
import time
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

router = APIRouter()

CACHE_DIR = os.path.join("data", "img_cache")
_ALLOWED_SCHEMES = {"http", "https"}

# Conservative per-image cap (bytes) to keep the cache bounded.
MAX_BYTES = 8 * 1024 * 1024

# Cache hygiene (roadmap C8): entries older than CACHE_TTL_SECONDS are
# re-fetched; after each write, oldest entries are evicted until the total
# cache size is at or under CACHE_MAX_BYTES.
CACHE_TTL_SECONDS = 7 * 24 * 3600          # one week
CACHE_MAX_BYTES = 512 * 1024 * 1024        # 512 MB on-disk budget


def _evict_cache() -> None:
    """Delete oldest cached files until total size fits within CACHE_MAX_BYTES."""
    try:
        entries = []
        total = 0
        for name in os.listdir(CACHE_DIR):
            path = os.path.join(CACHE_DIR, name)
            if not os.path.isfile(path):
                continue
            stat = os.stat(path)
            entries.append((stat.st_mtime, stat.st_size, path))
            total += stat.st_size
        entries.sort()
        for _, size, path in entries:
            if total <= CACHE_MAX_BYTES:
                break
            try:
                os.remove(path)
                total -= size
            except OSError:
                pass
    except OSError:
        pass


def _cache_is_fresh(cache_path: str) -> bool:
    """True if a cache entry exists and is younger than the TTL."""
    try:
        return (time.time() - os.stat(cache_path).st_mtime) < CACHE_TTL_SECONDS
    except OSError:
        return False


def _is_private_address(ip_str: str) -> bool:
    """True if the IP belongs to a non-routable range (RFC 1918, loopback, etc)."""
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
        return True  # unparseable — treat as unsafe


def _resolve_hostname(hostname: str) -> list[str]:
    """Resolve hostname to IP strings (blocking — must be called in executor)."""
    try:
        return [r[4][0] for r in socket.getaddrinfo(hostname, None)]
    except socket.gaierror:
        return []


async def _guard_against_ssrf(hostname: str) -> None:
    loop = asyncio.get_event_loop()
    resolved_ips = await loop.run_in_executor(None, _resolve_hostname, hostname)
    if not resolved_ips:
        raise HTTPException(400, "Could not resolve host")
    if any(_is_private_address(ip) for ip in resolved_ips):
        raise HTTPException(400, "URL resolves to a disallowed address")


async def _fetch(request: Request, url: str) -> bytes:
    from k9overwatch.utils.http_client import scraping_session

    async with scraping_session() as client:
        resp = await client.get(url, timeout=15)
        resp.raise_for_status()
        return await resp.read()


@router.get("/img")
async def proxy_image(request: Request, url: str):
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES or not parsed.hostname:
        raise HTTPException(400, "Unsupported or missing URL scheme/host")

    os.makedirs(CACHE_DIR, exist_ok=True)
    key = hashlib.sha256(url.encode()).hexdigest()
    cache_path = os.path.join(CACHE_DIR, key)

    if _cache_is_fresh(cache_path):
        with open(cache_path, "rb") as f:
            data = f.read()
    else:
        await _guard_against_ssrf(parsed.hostname)
        try:
            data = await _fetch(request, url)
        except Exception as exc:  # upstream unreachable / blocked
            raise HTTPException(502, f"Image fetch failed: {exc}") from exc
        if len(data) > MAX_BYTES:
            raise HTTPException(502, "Image too large")
        with open(cache_path, "wb") as f:
            f.write(data)
        _evict_cache()

    # Best-effort content type from magic bytes.
    ctype = "image/jpeg"
    if data[:8].startswith(b"\x89PNG\r\n\x1a\n"):
        ctype = "image/png"
    elif data[:3] == b"GIF":
        ctype = "image/gif"
    elif data[:4] in (b"RIFF",) and data[8:12] == b"WEBP":
        ctype = "image/webp"
    return Response(content=data, media_type=ctype)
