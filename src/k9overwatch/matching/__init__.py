from .signals import MatchResult, MatchType, Confidence
from .breed_normalizer import normalize_breed
from .deduplicator import Deduplicator
from .lost_found_matcher import LostFoundMatcher

__all__ = [
    "MatchResult", "MatchType", "Confidence",
    "normalize_breed", "Deduplicator", "LostFoundMatcher",
]
