from __future__ import annotations

import re

from acg.phrase_discovery import phrase_pool
from acg.phrases.lexicon import CONTENT_PATTERNS, VIDEO_INTRO_PATTERNS


def contains_any(text: str, patterns: list[str]) -> bool:
    lower = text.lower()
    return any(pattern in lower for pattern in patterns)


def content_allowed(text: str, toggles: dict[str, bool]) -> bool:
    if not toggles.get("profanity", False) and contains_any(text, CONTENT_PATTERNS["profanity"]):
        return False
    if not toggles.get("romance", False) and contains_any(text, CONTENT_PATTERNS["romance"]):
        return False
    if not toggles.get("slang", True) and contains_any(text, CONTENT_PATTERNS["slang"]):
        return False
    if not toggles.get("sarcasm", True) and contains_any(text, CONTENT_PATTERNS["sarcasm"]):
        return False
    return True


def looks_like_video_intro(text: str) -> bool:
    lower = re.sub(r"\s+", " ", str(text or "").strip().lower())
    return any(re.search(pattern, lower) for pattern in VIDEO_INTRO_PATTERNS)


def score_text(text: str, level: str, toggles: dict[str, bool], collection_levels: list[str] | None = None) -> float:
    lower = text.lower()
    words = re.findall(r"[A-Za-z']+", text)
    score = 2.0

    if 5 <= len(words) <= 12:
        score += 2.0
    elif 13 <= len(words) <= 14:
        score += 0.7
    if "?" in text or "!" in text:
        score += 0.4
    if contains_any(lower, phrase_pool(level, collection_levels)):
        score += 3.0
    if toggles.get("slang", True) and contains_any(lower, CONTENT_PATTERNS["slang"]):
        score += 0.6
    if toggles.get("sarcasm", True) and contains_any(lower, CONTENT_PATTERNS["sarcasm"]):
        score += 0.7
    if toggles.get("culture", True) and contains_any(lower, CONTENT_PATTERNS["culture"]):
        score += 0.5
    if toggles.get("business", True) and contains_any(lower, CONTENT_PATTERNS["business"]):
        score += 0.5
    if len(words) > 14:
        score -= 1.4
    if len(words) > 18:
        score -= 1.4
    if looks_like_video_intro(text):
        score -= 3.4
    if re.search(r"\[[^\]]+\]|\([^\)]*(music|applause|laugh)[^\)]*\)", lower):
        score -= 2.0
    return max(0.1, score)
