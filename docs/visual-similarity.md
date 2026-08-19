# Optional visual similarity matching

K9-Overwatch has a small visual-similarity seam, but it does **not** generate image
embeddings by itself and does not add a heavyweight ML dependency.

`k9overwatch.matching.visual_similarity` provides:

- `EmbeddingProvider`, a protocol with `embed(image_ref) -> sequence[float] | None`;
- `cosine_similarity` for deterministic comparison of provider-supplied vectors;
- `score_visual_similarity`, which emits the `visual_similarity` match signal only
  when a provider is injected and at least one photo pair exceeds the threshold.

`LostFoundMatcher(visual_provider=provider)` injects the adapter. The provider is
responsible for image access, authentication, model/runtime dependencies, vector
versioning, and error handling. `image_ref` can be a URL, object-store key, or
local path according to that provider's policy. The application never treats a
photo URL or filename as an embedding.

## Disabled/default behavior

No provider is configured in the default application wiring. In that state the
visual helper returns `{}` and the existing metadata and description signals are
unchanged. Missing photos, unavailable embeddings, malformed vectors, and
provider errors fail closed without creating a visual match signal.

## Enabling a provider

A deployment must implement an adapter around its approved embedding service or
model and inject it where the matcher is constructed. The adapter should be
configured outside this module, for example with a service endpoint/model name
and credentials supplied through the deployment's secret/configuration system.
Do not place credentials in source or pass untrusted remote URLs to a model
service without an explicit access policy.

Before enabling the signal in production, choose and validate a model/vector
version, embedding dimension, similarity threshold, and signal weight against a
reviewed evaluation set. Install the provider's dependencies in a separate,
explicit deployment extra; they are intentionally not part of the base
`k9overwatch` dependencies. The fallback behavior remains deterministic when the
provider is absent or unavailable.

The default threshold is `0.85` and the default score contribution is `0.10`.
These are conservative integration defaults, not a claim that the provider is
accurate. A visual signal is supporting evidence only and must not replace human
review for reunification decisions.

## Example adapter shape

```python
class MyEmbeddingProvider:
    def embed(self, image_ref: str) -> list[float] | None:
        # Call the approved provider; do not hash or otherwise fake an embedding.
        return approved_service.embed(image_ref)

matcher = LostFoundMatcher(visual_provider=MyEmbeddingProvider())
```

The example is intentionally illustrative: application wiring and provider
configuration are deployment-specific and are not enabled by this repository.

## Verification

The provider-independent contract is covered by `tests/test_visual_similarity.py`.
Those tests use supplied deterministic vectors and do not download models or
images.

**Privacy note:** image references and images may contain sensitive information.
Use a provider and retention policy appropriate for user-submitted pet photos.

This seam is intentionally opt-in and provider-neutral.
