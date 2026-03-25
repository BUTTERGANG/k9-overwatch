"""Shared aiohttp session factory with sensible defaults for scraping."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Optional

import aiohttp

# Browser-like User-Agent used across HTTP scrapers to avoid 403s
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS = {
    "User-Agent": BROWSER_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=30, connect=10)


@asynccontextmanager
async def scraping_session(
    headers: Optional[dict] = None,
    timeout: Optional[aiohttp.ClientTimeout] = None,
    **kwargs,
):
    """
    Async context manager yielding an aiohttp.ClientSession configured for scraping.

    Usage::

        async with scraping_session() as session:
            async with session.get(url) as resp:
                html = await resp.text()
    """
    merged_headers = {**DEFAULT_HEADERS, **(headers or {})}
    connector = aiohttp.TCPConnector(limit=10, ttl_dns_cache=300)
    async with aiohttp.ClientSession(
        headers=merged_headers,
        timeout=timeout or DEFAULT_TIMEOUT,
        connector=connector,
        **kwargs,
    ) as session:
        yield session


async def fetch_text(
    url: str,
    method: str = "GET",
    headers: Optional[dict] = None,
    data: Optional[dict] = None,
    retries: int = 2,
    retry_delay: float = 1.0,
) -> Optional[str]:
    """
    Fetch a URL and return the response body as text.
    Returns None on error after exhausting retries.
    """
    for attempt in range(retries + 1):
        try:
            async with scraping_session(headers=headers) as session:
                if method.upper() == "POST":
                    resp_ctx = session.post(url, data=data)
                else:
                    resp_ctx = session.get(url)
                async with resp_ctx as resp:
                    resp.raise_for_status()
                    return await resp.text()
        except Exception:
            if attempt < retries:
                await asyncio.sleep(retry_delay * (attempt + 1))
    return None
