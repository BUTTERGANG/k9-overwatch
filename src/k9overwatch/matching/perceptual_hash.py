"""Perceptual-hash visual-similarity groundwork (roadmap C11).

A concrete, dependency-light :class:`EmbeddingProvider` for the existing
``k9overwatch.matching.visual_similarity`` seam. Images are fetched, decoded
(via Pillow — an *optional* ``visual`` extra), downscaled to a tiny grayscale
grid, and hashed with dHash into a 64-bit fingerprint. The 64 bits are emitted
as ±1 floats so the existing ``cosine_similarity`` works unchanged: identical
hashes score 1.0, each differing bit subtracts an equal share.

Everything here is OFF by default: ``build_visual_provider()`` returns ``None``
unless ``VISUAL_SIMILARITY_ENABLED=1`` (and Pillow is importable). Perceptual
hashes are coarse supporting evidence only — they must not decide reunifications.
"""
from __future__ import annotations

import hashlib
import os
from collections.abc import Callable, Sequence

FetchFunc = Callable[[str], "bytes | None"]  # sync: returns raw image bytes or None

ALGORITHM_NAME = "dhash64-v1"
GRID_W = 9  # dHash sliding window: 9 wide → 8 comparisons per row
GRID_H = 8

EmbeddingCacheFunc = Callable[[str], "float | None"]


# ── Pure hash math (no image dependencies; operates on grayscale grids) ──────


def _mean(values: list[int]) -> float:
    return sum(values) / len(values)


def _to_grids(pixels: Sequence[Sequence[int]], w: int, h: int) -> list[list[int]]:
    """Nearest-neighbour downscale of any integer grid to w×h."""
    src_h, src_w = len(pixels), len(pixels[0]) if pixels else 0
    if src_h == 0 or src_w == 0:
        return [[0] * w for _ in range(h)]
    grid = []
    for gy in range(h):
        row = []
        for gx in range(w):
            # Sample the centre of each destination cell.
            sx = min(src_w - 1, (gx * src_w) // w)
            sy = min(src_h - 1, (gy * src_h) // h)
            row.append(int(pixels[sy][sx]))
        grid.append(row)
    return grid


def ahash_bits(grid: Sequence[Sequence[int]]) -> list[int]:
    """Average hash over an 8×8 view: bit=1 when pixel > mean."""
    small = _to_grids(grid, 8, 8)
    flat = [v for row in small for v in row]
    mean = _mean(flat)
    return [1 if v > mean else 0 for v in flat]


def dhash_bits(grid: Sequence[Sequence[int]]) -> list[int]:
    """Difference hash over a 9×8 view: bit=1 when pixel[x] < pixel[x+1]."""
    small = _to_grids(grid, GRID_W, GRID_H)
    bits: list[int] = []
    for row in small:
        for x in range(GRID_W - 1):
            bits.append(1 if row[x] < row[x + 1] else 0)
    return bits


def hamming_distance(left: Sequence[int], right: Sequence[int]) -> int:
    if len(left) != len(right):
        raise ValueError("hash lengths must match")
    return sum(1 for a, b in zip(left, right, strict=True) if a != b)


def bits_to_embedding(bits: Sequence[int]) -> list[float]:
    """Map 64 bits to ±1 floats so cosine_similarity ≒ bit agreement."""
    return [1.0 if b else -1.0 for b in bits]


def hamming_to_cosine(distance: int, n_bits: int = 64) -> float:
    """Cosine similarity of two ±1 embeddings whose hashes differ by ``distance``."""
    return 1.0 - 2.0 * distance / n_bits


# ── Provider adapter ─────────────────────────────────────────────────────────


def _decode_grayscale(data: bytes, width: int, height: int):
    """Decode image bytes to a width×height grayscale grid via Pillow.

    Returns None when Pillow is missing or the bytes aren't a decodable image.
    """
    try:
        import io

        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(io.BytesIO(data)) as img:  # Pillow accepts file-like buffers
            gray = img.convert("L").resize((width, height))
            return list(gray.getdata())
    except Exception:
        return None


class PerceptualHashProvider:
    """Sync ``embed`` per the EmbeddingProvider protocol.

    ``fetch`` is an async callable returning raw image bytes (injected so tests
    can avoid network I/O; production wiring uses the shared scraping client).
    Results are memoised per image ref within this provider instance.
    """

    def __init__(self, fetch: FetchFunc | None = None) -> None:
        self._fetch = fetch
        self._memo: dict[str, list[float] | None] = {}

    def embed(self, image_ref: str) -> list[float] | None:
        if not image_ref:
            return None
        if image_ref in self._memo:
            return self._memo[image_ref]
        embedding: list[float] | None = None
        if self._fetch is not None:
            try:
                data = self._fetch(image_ref)
            except Exception:
                data = None
            if data:
                pixels = _decode_grayscale(data, GRID_W, GRID_H)
                if pixels:
                    embedding = bits_to_embedding(dhash_bits([pixels[i:i + GRID_W] for i in range(0, len(pixels), GRID_W)]))
        self._memo[image_ref] = embedding
        return embedding


def url_hash(image_url: str) -> str:
    """Stable cache key for a photo URL."""
    return hashlib.sha256(image_url.encode("utf-8")).hexdigest()


def build_visual_provider() -> PerceptualHashProvider | None:
    """Env-gated factory: None unless VISUAL_SIMILARITY_ENABLED=1 and Pillow exists."""
    if os.getenv("VISUAL_SIMILARITY_ENABLED", "0").lower() not in ("1", "true", "yes"):
        return None
    try:
        import PIL  # noqa: F401
    except ImportError:
        return None

    def _fetch(url: str) -> bytes:
        import requests

        resp = requests.get(url, timeout=15, stream=True)
        resp.raise_for_status()
        return resp.raw.read(5_000_000)

    return PerceptualHashProvider(fetch=_fetch)


# ── DB side-table cache helpers (used by async callers, e.g. scheduler jobs) ──


async def get_cached_embedding(session, image_url: str) -> list[float] | None:
    """Return the cached embedding for a photo URL, or None (miss/stale algo)."""
    import json

    from sqlalchemy import select

    from ..db.models import VisualEmbedding

    row = (
        await session.execute(
            select(VisualEmbedding).where(
                VisualEmbedding.ref_hash == url_hash(image_url),
                VisualEmbedding.algorithm == ALGORITHM_NAME,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    try:
        vec = json.loads(row.embedding)
        return vec if isinstance(vec, list) else None
    except (TypeError, ValueError):
        return None


async def store_embedding(session, image_url: str, embedding: Sequence[float]) -> None:
    """Upsert the cached embedding for a photo URL."""
    import json

    from sqlalchemy import select

    from ..db.models import VisualEmbedding

    ref_hash = url_hash(image_url)
    row = (
        await session.execute(
            select(VisualEmbedding).where(
                VisualEmbedding.ref_hash == ref_hash,
                VisualEmbedding.algorithm == ALGORITHM_NAME,
            )
        )
    ).scalar_one_or_none()
    payload = json.dumps(list(embedding))
    if row is None:
        session.add(VisualEmbedding(ref_hash=ref_hash, algorithm=ALGORITHM_NAME, embedding=payload))
    else:
        row.embedding = payload
    await session.commit()
