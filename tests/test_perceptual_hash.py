"""Perceptual-hash visual-similarity groundwork (roadmap C11).

Pure-Python dHash/aHash over downscaled grayscale grids, a Pillow-backed
EmbeddingProvider adapter, a DB side-table cache keyed by photo-URL hash, and
env-gated wiring (VISUAL_SIMILARITY_ENABLED, default off).
"""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from k9overwatch.matching.perceptual_hash import (
    PerceptualHashProvider,
    ahash_bits,
    bits_to_embedding,
    build_visual_provider,
    dhash_bits,
    hamming_distance,
)
from k9overwatch.matching.visual_similarity import cosine_similarity

try:  # Pillow is an optional extra ("visual"); tests degrade gracefully without it.
    from PIL import Image  # noqa: F401

    HAS_PIL = True
except ImportError:
    HAS_PIL = False


def _gradient_grid(w: int = 8, h: int = 8) -> list[list[int]]:
    return [[(x * 255) // max(w - 1, 1) for x in range(w)] for _ in range(h)]


def _uniform_grid(value: int = 128, w: int = 8, h: int = 8) -> list[list[int]]:
    return [[value] * w for _ in range(h)]


def test_ahash_uniform_and_gradient():
    assert sum(ahash_bits(_uniform_grid())) == 0  # nothing above mean → all zero bits
    grad = ahash_bits(_gradient_grid())
    assert len(grad) == 64
    assert any(grad)


def test_dhash_shape_and_sensitivity():
    bits = dhash_bits(_gradient_grid())
    assert len(bits) == 64
    flat = dhash_bits(_uniform_grid())
    assert sum(flat) == 0  # no horizontal gradient → all zero bits


def test_hamming_distance():
    assert hamming_distance([0] * 8, [0] * 8) == 0
    assert hamming_distance([0] * 8, [1] * 8) == 8


def test_identical_grids_have_identical_embeddings():
    e1 = bits_to_embedding(ahash_bits(_gradient_grid()))
    e2 = bits_to_embedding(ahash_bits(_gradient_grid()))
    assert cosine_similarity(e1, e2) == pytest.approx(1.0)
    assert len(e1) == 64


def test_different_grids_are_less_similar_than_identical():
    e1 = bits_to_embedding(dhash_bits(_gradient_grid()))
    inverted = [[255 - v for v in row] for row in _gradient_grid()]
    e2 = bits_to_embedding(dhash_bits(inverted))
    same = bits_to_embedding(dhash_bits(_gradient_grid()))
    assert cosine_similarity(e1, same) == pytest.approx(1.0)
    assert cosine_similarity(e1, e2) < 0.5


async def _png_bytes(width: int, height: int, painter) -> bytes:
    from PIL import Image

    img = Image.new("L", (width, height))
    img.putdata([painter(x, y) for y in range(height) for x in range(width)])
    import io

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.mark.skipif(not HAS_PIL, reason="Pillow not installed")
async def test_provider_embeds_image_bytes():
    png = await _png_bytes(32, 32, lambda x, y: (x * 7) % 256)

    def fake_fetch(url: str) -> bytes:
        return png

    provider = PerceptualHashProvider(fetch=fake_fetch)
    emb = provider.embed("https://example.com/dog.png")
    assert emb is not None and len(emb) == 64
    again = provider.embed("https://example.com/dog.png")
    assert cosine_similarity(emb, again) == pytest.approx(1.0)


@pytest.mark.skipif(not HAS_PIL, reason="Pillow not installed")
async def test_provider_fails_closed_on_bad_bytes():
    def fake_fetch(url: str) -> bytes:
        return b"not-an-image"

    provider = PerceptualHashProvider(fetch=fake_fetch)
    assert provider.embed("https://example.com/junk.png") is None
    assert provider.embed("") is None


async def test_embedding_cache_roundtrip(db_session: AsyncSession):
    from k9overwatch.matching.perceptual_hash import (
        ALGORITHM_NAME,
        get_cached_embedding,
        store_embedding,
    )

    url = "https://example.com/rex.jpg"
    assert await get_cached_embedding(db_session, url) is None
    vec = [0.5] * 64
    await store_embedding(db_session, url, vec)
    hit = await get_cached_embedding(db_session, url)
    assert hit == vec
    assert ALGORITHM_NAME == "dhash64-v1"


def test_build_visual_provider_env_gated(monkeypatch):
    monkeypatch.delenv("VISUAL_SIMILARITY_ENABLED", raising=False)
    assert build_visual_provider() is None
    if HAS_PIL:
        monkeypatch.setenv("VISUAL_SIMILARITY_ENABLED", "1")
        provider = build_visual_provider()
        assert isinstance(provider, PerceptualHashProvider)
