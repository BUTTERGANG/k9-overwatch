"""Optional visual-similarity matching seam.

This module deliberately does not create embeddings or depend on an ML package.
A deployment may inject an :class:`EmbeddingProvider` backed by its approved
image-embedding service/model. Until then, visual matching fails closed and the
existing deterministic metadata/description signals remain authoritative.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Protocol

Embedding = Sequence[float]


class EmbeddingProvider(Protocol):
    """Adapter contract for a real image-embedding provider.

    ``image_ref`` is intentionally opaque: callers may pass a URL, object-store
    key, or local path according to the provider's security and access policy.
    The adapter, not this module, owns image loading and model dependencies.
    """

    def embed(self, image_ref: str) -> Embedding | None:
        """Return an embedding for ``image_ref``, or ``None`` if unavailable."""
        ...


def cosine_similarity(left: Embedding, right: Embedding) -> float:
    """Return cosine similarity for two finite, same-sized embeddings.

    Raises ``ValueError`` for malformed vectors rather than silently producing a
    misleading score. Zero vectors have no direction and are also rejected.
    """
    if not left or not right or len(left) != len(right):
        raise ValueError("embeddings must be non-empty and have equal dimensions")

    try:
        values = [(*left, *right)]
        if not all(math.isfinite(float(value)) for pair in values for value in pair):
            raise ValueError("embeddings must contain only finite values")
        dot = sum(float(a) * float(b) for a, b in zip(left, right, strict=True))
        left_norm = math.sqrt(sum(float(value) ** 2 for value in left))
        right_norm = math.sqrt(sum(float(value) ** 2 for value in right))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("embeddings must contain finite numeric values") from exc

    if left_norm == 0.0 or right_norm == 0.0:
        raise ValueError("zero vectors do not have a cosine similarity")
    return dot / (left_norm * right_norm)


def score_visual_similarity(
    left_photos: Sequence[str] | None,
    right_photos: Sequence[str] | None,
    *,
    provider: EmbeddingProvider | None,
    threshold: float = 0.85,
    weight: float = 0.10,
) -> dict[str, float]:
    """Return a visual match signal only for a configured provider and match.

    The strongest valid photo-pair similarity is used. Provider failures and
    malformed/unavailable embeddings are ignored so matching safely falls back
    to its deterministic non-visual signals. No provider means no signal.
    """
    if provider is None:
        return {}
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("threshold must be between 0 and 1")
    if weight < 0.0:
        raise ValueError("weight must be non-negative")

    left_refs = [ref for ref in (left_photos or ()) if isinstance(ref, str) and ref]
    right_refs = [ref for ref in (right_photos or ()) if isinstance(ref, str) and ref]
    if not left_refs or not right_refs:
        return {}

    def embeddings(refs: Sequence[str]) -> list[Embedding]:
        result: list[Embedding] = []
        for ref in refs:
            try:
                embedding = provider.embed(ref)
                if embedding is not None:
                    # Validate now; invalid provider output is not a match.
                    cosine_similarity(embedding, embedding)
                    result.append(embedding)
            except Exception:  # provider is optional; base matching must survive it
                continue
        return result

    left_vectors = embeddings(left_refs)
    right_vectors = embeddings(right_refs)
    if not left_vectors or not right_vectors:
        return {}

    similarities: list[float] = []
    for left in left_vectors:
        for right in right_vectors:
            try:
                similarities.append(cosine_similarity(left, right))
            except ValueError:
                # Providers must agree on dimensions; mixed versions fail closed.
                continue
    best = max(similarities, default=None)
    if best is None or best < threshold:
        return {}
    return {"visual_similarity": weight}
