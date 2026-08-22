"""Tests for /img proxy cache TTL + size-capped eviction (roadmap C8)."""

from __future__ import annotations

import hashlib
import os
import time

import httpx
import pytest

from k9overwatch.web.routers import images


@pytest.fixture(autouse=True)
def _tmp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(images, "CACHE_DIR", str(tmp_path / "img_cache"))
    monkeypatch.setattr(images, "_guard_against_ssrf", _fake_guard)


async def _fake_guard(hostname: str) -> None:
    return None


def _cache_path(url: str) -> str:
    return os.path.join(images.CACHE_DIR, hashlib.sha256(url.encode()).hexdigest())


async def test_expired_entry_is_refetched(client_with_images, monkeypatch):
    """A cache file older than the TTL is ignored and re-fetched."""
    url = "https://example.com/a.jpg"
    path = _cache_path(url)
    os.makedirs(images.CACHE_DIR, exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"stale-bytes")
    old = time.time() - images.CACHE_TTL_SECONDS - 10
    os.utime(path, (old, old))

    calls = []

    async def fake_fetch(request, u):
        calls.append(u)
        return b"fresh-bytes"

    monkeypatch.setattr(images, "_fetch", fake_fetch)
    resp = await client_with_images.get("/img", params={"url": url})
    assert resp.status_code == 200
    assert resp.content == b"fresh-bytes"
    assert calls == [url]


async def test_fresh_entry_served_from_cache(client_with_images, monkeypatch):
    url = "https://example.com/b.jpg"
    path = _cache_path(url)
    os.makedirs(images.CACHE_DIR, exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"cached-bytes")

    async def boom(request, u):  # pragma: no cover - must not be called
        raise AssertionError("fetch called for fresh cache entry")

    monkeypatch.setattr(images, "_fetch", boom)
    resp = await client_with_images.get("/img", params={"url": url})
    assert resp.content == b"cached-bytes"


async def test_eviction_caps_total_cache_size(client_with_images, monkeypatch):
    """Writing a new entry evicts oldest files until under the byte cap."""
    monkeypatch.setattr(images, "CACHE_MAX_BYTES", 3000)

    async def fake_fetch(request, u):
        return b"x" * 1000

    monkeypatch.setattr(images, "_fetch", fake_fetch)

    urls = [f"https://example.com/{i}.jpg" for i in range(5)]
    for i, url in enumerate(urls):
        # Backdate earlier entries so eviction order is deterministic.
        resp = await client_with_images.get("/img", params={"url": url})
        assert resp.status_code == 200
        path = _cache_path(url)
        age = 1000 - i
        old = time.time() - age
        os.utime(path, (old, old))

    total = sum(
        os.path.getsize(os.path.join(images.CACHE_DIR, n))
        for n in os.listdir(images.CACHE_DIR)
    )
    assert total <= images.CACHE_MAX_BYTES
    # Oldest entries were evicted; the newest survives.
    assert not os.path.exists(_cache_path(urls[0]))
    assert os.path.exists(_cache_path(urls[-1]))


@pytest.fixture
async def client_with_images(client: httpx.AsyncClient) -> httpx.AsyncClient:
    return client
