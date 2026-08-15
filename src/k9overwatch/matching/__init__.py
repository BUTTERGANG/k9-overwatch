from .breed_normalizer import normalize_breed
from .deduplicator import Deduplicator
from .lost_found_matcher import LostFoundMatcher
from .signals import Confidence, MatchResult, MatchType

__all__ = [
    "MatchResult", "MatchType", "Confidence",
    "normalize_breed", "Deduplicator", "LostFoundMatcher",
]
