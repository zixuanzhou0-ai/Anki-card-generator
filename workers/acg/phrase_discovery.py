from __future__ import annotations

import re

from acg.language_text import overlap_words
from acg.learning_settings import normalize_collection_levels
from acg.learning_spans import phrase_in_text
from acg.phrases.lexicon import (
    CEFR_ORDER,
    COMMON_FUNCTION_STARTS,
    DISCOVERY_EXPRESSION_PATTERNS,
    DISCOVERY_PHRASE_PARTICLES,
    DISCOVERY_PHRASE_VERBS,
    DISCOVERY_PREPOSITION_STARTS,
    DISCOVERY_SIGNAL_WORDS,
    EXPRESSION_PATTERNS,
    LOW_VALUE_STANDALONE_PHRASES,
    NON_TRANSFERABLE_PHRASES,
    PHRASES_BY_LEVEL,
    TRANSFERABLE_FUNCTION_FRAME_PHRASES,
    VIDEO_INTRO_PATTERNS,
    WEAK_PHRASE_STARTS,
)
from acg.card_quality import allows_function_start_phrase, phrase_allows_trailing_preposition


def phrase_pool(level: str, collection_levels: list[str] | None = None) -> list[str]:
    order = CEFR_ORDER
    if collection_levels:
        selected_levels = normalize_collection_levels(collection_levels, level)
    else:
        cutoff = max(order.index(level), 0) if level in order else 2
        lower = max(0, cutoff - 1)
        upper = min(len(order), cutoff + 2)
        selected_levels = order[lower:upper]
    pool: list[str] = []
    for item in selected_levels:
        pool.extend(PHRASES_BY_LEVEL[item])
    return pool


def normalize_phrase_candidate(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip(" \t\r\n.,!?;:\"“”‘’")).strip()


def has_adjacent_duplicate_words(words: list[str]) -> bool:
    return any(left == right for left, right in zip(words, words[1:]))


def trim_discovery_phrase_words(words: list[str]) -> list[str]:
    if len(words) >= 2 and words[0] in DISCOVERY_PHRASE_VERBS and words[1] in DISCOVERY_PHRASE_PARTICLES:
        return words[:2]
    if (
        len(words) >= 3
        and words[0] in DISCOVERY_PHRASE_VERBS
        and words[1] in {"it", "this", "that", "things", "something", "someone", "me", "you", "him", "her", "us", "them"}
        and words[2] in DISCOVERY_PHRASE_PARTICLES
    ):
        return words[:3]
    return words


def discovery_ngram_has_signal(words: list[str]) -> bool:
    phrase = " ".join(words)
    if phrase in TRANSFERABLE_FUNCTION_FRAME_PHRASES:
        return True
    if any(phrase == f"{item} that" for item in TRANSFERABLE_FUNCTION_FRAME_PHRASES):
        return True
    if len(words) == 2 and words[0] in {"feel", "feels", "felt", "look", "looks", "looked", "sound", "sounds", "sounded"} and words[1] == "like":
        return True
    if words[0] in DISCOVERY_PHRASE_VERBS and (
        words[1] in DISCOVERY_PHRASE_PARTICLES
        or (
            len(words) >= 3
            and words[1] in {"it", "this", "that", "things", "something", "someone", "me", "you", "him", "her", "us", "them"}
            and words[2] in DISCOVERY_PHRASE_PARTICLES
        )
    ):
        return True
    if (
        words[0] in DISCOVERY_PREPOSITION_STARTS
        and words[-1] in {"end", "middle", "mood", "place", "point", "run", "start", "time", "way"}
        and any(word in DISCOVERY_SIGNAL_WORDS for word in words[1:])
    ):
        return True
    if len(words) >= 3 and words[0] == "such" and words[1] in {"a", "an"}:
        return True
    if len(words) >= 3 and words[0] in {"more", "less"} and "than" in words:
        return True
    if len(words) >= 4 and words[0] == "as" and words[-1] == "possible":
        return True
    if len(words) >= 3 and "kind" in words and "of" in words:
        return True
    if len(words) >= 3 and "sort" in words and "of" in words:
        return True
    return False


def structurally_safe_discovery_phrase(phrase: str) -> bool:
    words = overlap_words(phrase)
    if len(words) < 2 or len(words) > 6:
        return False
    key = " ".join(words)
    if key in {"key expression", *LOW_VALUE_STANDALONE_PHRASES}:
        return False
    if has_adjacent_duplicate_words(words):
        return False
    if sum(1 for word in words if any(char.isdigit() for char in word)) > 1:
        return False
    if words[0] in COMMON_FUNCTION_STARTS and key not in TRANSFERABLE_FUNCTION_FRAME_PHRASES:
        return False
    if words[0] in WEAK_PHRASE_STARTS and words[0] not in DISCOVERY_PREPOSITION_STARTS and not discovery_ngram_has_signal(words):
        return False
    if words[-1] in {"the", "a", "an", "and", "or", "but", "as", "because", "if", "than", "to", "with"}:
        return False
    return discovery_ngram_has_signal(words)


def is_non_transferable_phrase(phrase: str) -> bool:
    lower = re.sub(r"\s+", " ", str(phrase or "").strip().lower())
    return bool(lower and (lower in NON_TRANSFERABLE_PHRASES or any(re.search(pattern, lower) for pattern in VIDEO_INTRO_PATTERNS)))


def is_low_value_standalone_phrase(phrase: str) -> bool:
    lower = re.sub(r"\s+", " ", str(phrase or "").strip().lower())
    return lower in LOW_VALUE_STANDALONE_PHRASES


def usable_phrase(text: str, phrase: str) -> bool:
    words = overlap_words(phrase)
    text_words = overlap_words(text)
    if not phrase or phrase == "key expression":
        return False
    if len(words) < 2 or len(words) > 6:
        return False
    if len(words) >= max(4, len(text_words) - 1) and len(text_words) >= 5:
        return False
    if is_non_transferable_phrase(phrase):
        return False
    if is_low_value_standalone_phrase(phrase):
        return False
    if (words[0] in COMMON_FUNCTION_STARTS or words[0] in WEAK_PHRASE_STARTS) and not allows_function_start_phrase(phrase):
        return False
    trailing_prepositions = {"about", "of", "for", "to", "with", "from", "by", "at"}
    if words[-1] in trailing_prepositions and not phrase_allows_trailing_preposition(phrase):
        return False
    return phrase_in_text(text, phrase)


def candidate_phrases_from_text(text: str) -> list[str]:
    lower = str(text or "").lower()
    candidates: list[str] = []
    seen: set[str] = set()

    def add(value: str, trusted: bool = False) -> None:
        candidate = normalize_phrase_candidate(value)
        if not trusted:
            words = trim_discovery_phrase_words(overlap_words(candidate))
            candidate = " ".join(words)
        key = " ".join(overlap_words(candidate))
        if not key or key in seen:
            return
        words = key.split()
        if trusted and 2 <= len(words) <= 6 and key not in LOW_VALUE_STANDALONE_PHRASES and not has_adjacent_duplicate_words(words):
            candidates.append(candidate)
            seen.add(key)
        elif structurally_safe_discovery_phrase(candidate):
            candidates.append(candidate)
            seen.add(key)

    for pattern in DISCOVERY_EXPRESSION_PATTERNS:
        for match in re.finditer(pattern, lower):
            add(match.group(0), trusted=True)

    words = overlap_words(lower)
    for length in (5, 4, 3, 2):
        if len(candidates) >= 8:
            break
        for index in range(0, max(0, len(words) - length + 1)):
            add(" ".join(words[index : index + length]))
            if len(candidates) >= 8:
                break

    return candidates


def find_phrase(text: str, level: str, collection_levels: list[str] | None = None) -> str:
    lower = text.lower()
    for pattern in EXPRESSION_PATTERNS:
        match = re.search(pattern, lower)
        if match:
            return re.sub(r"\s+", " ", match.group(0)).strip()

    pool = sorted(phrase_pool(level, collection_levels), key=len, reverse=True)
    for phrase in pool:
        if phrase in lower:
            return phrase

    for phrase in candidate_phrases_from_text(text):
        return phrase

    # Do not invent a phrase from arbitrary adjacent words. Bad fallback chunks like
    # "can we figure" or "ai model price" are worse than returning no phrase.
    return "key expression"


def choose_best_phrase(text: str, proposed: str, fallback: str, level: str, collection_levels: list[str] | None = None) -> str:
    candidates = [proposed, fallback, find_phrase(text, level, collection_levels)]
    seen: set[str] = set()
    for candidate in candidates:
        normalized = re.sub(r"\s+", " ", str(candidate or "")).strip()
        key = normalized.lower()
        if not normalized or key in seen:
            continue
        seen.add(key)
        if usable_phrase(text, normalized):
            return normalized
    return ""
