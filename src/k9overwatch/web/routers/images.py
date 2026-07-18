"""
Image proxy + cache.

Serves remote listing photos through our own origin so:
  * browsers don't block cross-origin/large source images,
  * repeated loads are served from local cache (faster directory/map/feeds),
  * there's one choke point to add resizing/WebP later.

No external image lib required: we proxy + cache raw bytes. The URL is
validated to http/https only to avoid SSRF via file:// or internal schemes.
Caching is content-hashed on the URL; cached files live under data/img_cache/.
"""
from __future__ import annotations

import hashlib
import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

router = APIRouter()

CACHE_DIR = os.path.join("data", "img_cache")
_ALLOWED_SCHEMES = {"http", "https"}

# Conservative per-image cap (bytes) to keep the cache bounded.
MAX_BYTES = 8 * 1024 * 1024


async def _fetch(request: Request, url: str) -> bytes:
    from k9overwatch.utils.http_client import scraping_session

    async with scraping_session() as client:
        resp = await client.get(url, timeout=15)
        resp.raise_for_status()
        return resp.content


@router.get("/img")
async def proxy_image(request: Request, url: str):
    if "://" not in url:
        raise HTTPException(400, "Missing URL scheme")
    scheme = url.split("://", 1)[0].lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise HTTPException(400, "Unsupported URL scheme")

    os.makedirs(CACHE_DIR, exist_ok=True)
    key = hashlib.sha256(url.encode()).hexdigest()
    cache_path = os.path.join(CACHE_DIR, key)

    if os.path.exists(cache_path):
        with open(cache_path, "rb") as f:
            data = f.read()
    else:
        try:
            data = await _fetch(request, url)
        except Exception as exc:  # upstream unreachable / blocked
            raise HTTPException(502, f"Image fetch failed: {exc}") from exc
        if len(data) > MAX_BYTES:
            raise HTTPException(502, "Image too large")
        with open(cache_path, "wb") as f:
            f.write(data)

    # Best-effort content type from magic bytes.
    ctype = "image/jpeg"
    if data[:8].startswith(b"\x89PNG\r\n\x1a\n"):
        ctype = "image/png"
    elif data[:3] == b"GIF":
        ctype = "image/gif"
    elif data[:4] in (b"RIFF",) and data[8:12] == b"WEBP":
        ctype = "image/webp"
    return Response(content=data, media_type=ctype)
