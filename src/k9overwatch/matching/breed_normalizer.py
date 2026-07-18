"""
Breed name normalization — canonicalizes breed strings before matching.

Without this, "Yorkie" and "Yorkshire Terrier" never match,
"Lab Mix" and "Labrador Mix" never match, etc.
"""
from __future__ import annotations

import re
from functools import lru_cache

# Canonical name → list of aliases (all lowercase)
_BREED_ALIASES: dict[str, list[str]] = {
    "yorkshire terrier": ["yorkie", "york terrier"],
    "labrador retriever": ["lab", "labrador", "labrador retriever mix", "lab mix"],
    "pit bull terrier": ["pit bull", "pitbull", "pit", "bully", "amstaff", "american staffordshire terrier"],
    "german shepherd": ["gsd", "german shepherd dog", "german shepard"],
    "golden retriever": ["golden", "gold retriever"],
    "chihuahua": ["chi", "chi mix"],
    "dachshund": ["doxie", "weiner dog", "wiener dog", "dachs"],
    "poodle": ["poodle mix"],
    "french bulldog": ["frenchie", "french bull"],
    "beagle": [],
    "bulldog": ["english bulldog", "british bulldog"],
    "rottweiler": ["rottie", "rott"],
    "pomeranian": ["pom", "pom mix"],
    "shih tzu": ["shih-tzu", "shitzu"],
    "boxer": [],
    "husky": ["siberian husky", "sibe"],
    "great dane": [],
    "doberman pinscher": ["doberman", "dobe", "dobie"],
    "border collie": [],
    "australian shepherd": ["aussie"],
    "cocker spaniel": ["cocker"],
    "maltese": [],
    "bichon frise": ["bichon"],
    "shetland sheepdog": ["sheltie", "shetland"],
    "boston terrier": ["boston"],
    "pug": [],
    "miniature schnauzer": ["min schnauzer", "mini schnauzer", "schnauzer"],
    "cavalier king charles spaniel": ["cavalier", "king charles"],
    "havanese": [],
    "lhasa apso": ["lhasa"],
    "jack russell terrier": ["jack russell", "jrt"],
    "shiba inu": ["shiba"],
    "corgi": ["pembroke welsh corgi", "cardigan welsh corgi", "welsh corgi"],
    "persian": [],  # cat
    "siamese": [],  # cat
    "maine coon": [],  # cat
    "bengal": [],   # cat
    "ragdoll": [],  # cat
    "mixed breed": ["mixed", "mix", "mutt", "cross", "crossbreed", "unknown breed"],
}

# Build reverse lookup: alias → canonical
_ALIAS_TO_CANONICAL: dict[str, str] = {}
for canonical, aliases in _BREED_ALIASES.items():
    _ALIAS_TO_CANONICAL[canonical] = canonical
    for alias in aliases:
        _ALIAS_TO_CANONICAL[alias] = canonical


def _preprocess(breed: str) -> str:
    """Lowercase, strip punctuation, normalize whitespace."""
    b = breed.lower().strip()
    b = re.sub(r"[/\\]", " / ", b)       # normalize slashes to space-slash-space
    b = re.sub(r"[^a-z0-9/ ]+", " ", b)  # remove non-alphanumeric except / and space
    b = re.sub(r"\s+", " ", b).strip()
    return b


@lru_cache(maxsize=2048)
def normalize_breed(breed: str | None) -> str | None:
    """
    Normalize a breed string to its canonical form.
    Returns None for missing/unknown breeds (not useful for matching).
    """
    if not breed or not breed.strip():
        return None

    processed = _preprocess(breed)

    # Discard obviously non-specific breeds
    if processed in ("unknown", "unknown breed", "mixed", "mix", "mutt", "other"):
        return None

    # Handle compound breeds (e.g., "Lab / Pit")
    if " / " in processed:
        parts = [p.strip() for p in processed.split(" / ")]
        normalized_parts = []
        for part in parts:
            norm = _ALIAS_TO_CANONICAL.get(part, part)
            normalized_parts.append(norm)
        return " / ".join(sorted(normalized_parts))  # sort for consistent comparison

    # Direct alias lookup
    if processed in _ALIAS_TO_CANONICAL:
        return _ALIAS_TO_CANONICAL[processed]

    # Fuzzy lookup for unmapped breeds (rapidfuzz)
    try:
        from rapidfuzz import process
        match = process.extractOne(
            processed,
            _ALIAS_TO_CANONICAL.keys(),
            score_cutoff=88,
        )
        if match:
            return _ALIAS_TO_CANONICAL[match[0]]
    except ImportError:
        pass

    # Return processed form if no alias found
    return processed
