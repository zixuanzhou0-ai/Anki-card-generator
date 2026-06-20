from __future__ import annotations

import re
from typing import Any

from acg.language_text import normalize_learning_language, overlap_words
from acg.learning_spans import normalize_candidate_span
from acg.phrases.lexicon import (
    CEFR_ORDER,
    PHRASE_GUIDE_ALIASES,
    TEMPLATE_NOISE_PATTERNS,
    TOO_BASIC_FOR_INTERMEDIATE_PHRASES,
    TRANSFERABLE_FUNCTION_FRAME_PHRASES,
)
from acg.text_cleaning import clean_study_text


GENERIC_DEFINITION_PATTERNS = [
    r"\bthis phrase is useful\b",
    r"\buseful in daily english\b",
    r"\bcommon(?:ly)? used\b",
    r"\bvery common\b",
    r"这个表达很常见",
    r"常用表达",
    r"高频表达",
    r"日常英语.*有用",
]

GENERIC_TEACHER_NOTE_PATTERNS = [
    r"^很常见[。.!]?$",
    r"^真实口语常用[。.!]?$",
    r"^高频口语表达[。.!]?$",
    r"^这个表达很常用[。.!]?$",
    r"^适合日常交流[。.!]?$",
    r"\buse it in daily english\b",
    r"\bthis is a common expression\b",
]


def has_generic_definition(value: str) -> bool:
    text = re.sub(r"\s+", " ", str(value or "").strip().lower())
    return bool(text and any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in GENERIC_DEFINITION_PATTERNS))


def has_generic_teacher_note(value: str) -> bool:
    text = re.sub(r"\s+", " ", str(value or "").strip().lower())
    return bool(text and any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in GENERIC_TEACHER_NOTE_PATTERNS))


def has_template_noise(value: Any) -> bool:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    return bool(text and any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in TEMPLATE_NOISE_PATTERNS))


def is_specific_study_text(value: Any) -> bool:
    text = clean_study_text(value)
    return bool(text and not has_template_noise(text))


def normalized_action_text(value: Any) -> str:
    if isinstance(value, list):
        return " / ".join(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, dict):
        return " / ".join(f"{key}: {item}" for key, item in value.items() if str(item).strip())
    return str(value or "").strip()


def cefr_rank(value: str) -> int:
    match = re.search(r"\b(A1|A2|B1|B2|C1|C2)\b", str(value or "").upper())
    if not match:
        return -1
    return CEFR_ORDER.index(match.group(1))


def is_too_basic_for_level(phrase: str, target_level: str) -> bool:
    level_rank = cefr_rank(target_level)
    if level_rank < cefr_rank("B1"):
        return False
    lower = re.sub(r"\s+", " ", str(phrase or "").strip().lower())
    return lower in TOO_BASIC_FOR_INTERMEDIATE_PHRASES


INCOMPLETE_FINAL_WORDS = {
    "because",
    "if",
    "than",
    "when",
    "where",
    "which",
    "who",
    "whom",
    "whose",
    "with",
}
INCOMPLETE_FINAL_CONTRACTIONS = {
    "where's",
    "who's",
}
SHORT_WH_FRAGMENT_STARTS = {
    "how",
    "what",
    "what'd",
    "where",
    "who",
    "why",
}
SHORT_FRAGMENT_PRONOUN_ENDS = {"he", "her", "him", "it", "me", "she", "them", "they", "us", "we", "you"}
ACCEPTABLE_FRAGMENT_ANSWERS = {
    "apply heat to",
    "be willing to",
    "go first",
    "how do you feel about",
    "i do not like it when",
    "i'd be willing to",
    "i seen",
    "in style",
    "in the presence of",
    "in the mood for",
    "not really",
    "prefer to see it as",
    "right now",
    "such a nice",
    "that answers that",
    "was thinking of",
    "we'll see about that",
    "what do you think about",
    "what do you call that",
    "what tells you",
    "worked out of",
}
BAD_INCOMPLETE_ANSWERS = {
    "it when",
    "what'd you",
    "what did you",
    "what do you",
    "what are you",
    "where did you",
    "who did you",
}


def normalized_answer_key(value: Any) -> str:
    return re.sub(r"\s+", " ", normalize_candidate_span(value).lower())


def allows_function_start_phrase(phrase: str) -> bool:
    lower = re.sub(r"\s+", " ", str(phrase or "").strip().lower())
    return lower in TRANSFERABLE_FUNCTION_FRAME_PHRASES or any(
        lower.startswith(f"{item} ") for item in TRANSFERABLE_FUNCTION_FRAME_PHRASES
    )


def phrase_allows_trailing_preposition(phrase: str) -> bool:
    phrase_lower = phrase.lower()
    return bool(
        re.search(r"\btell\s+\w+\s+about\b", phrase_lower)
        or phrase_lower
        in {
            "working with",
            "deal with",
            "talk about",
            "look for",
            "come up with",
            "get away with",
            "opening doors to",
            "connect with",
            "full of",
            "get used to",
            "feel free to",
            "in the mood for",
            "what do you think about",
            "how do you feel about",
            "prefer to see it as",
            "was thinking of",
            "apply heat to",
            "worked out of",
            "in the presence of",
            "i'd be willing to",
            "be willing to",
            "what's up for",
        }
    )


def looks_like_incomplete_answer_fragment(value: Any, card: dict[str, Any]) -> bool:
    lower = normalized_answer_key(value)
    if not lower or lower in ACCEPTABLE_FRAGMENT_ANSWERS or allows_function_start_phrase(lower):
        return False
    if normalize_learning_language(card.get("language_code") or card.get("language") or "en") != "en":
        return False
    if lower in BAD_INCOMPLETE_ANSWERS:
        return True
    candidate_kind = str(card.get("candidate_kind") or "")
    if candidate_kind == "contextual_vocab":
        return False
    words = overlap_words(lower)
    if not words:
        return False
    last = words[-1]
    if last in INCOMPLETE_FINAL_CONTRACTIONS:
        return True
    if last in INCOMPLETE_FINAL_WORDS and not phrase_allows_trailing_preposition(lower):
        return True
    if len(words) <= 3 and words[0] in SHORT_WH_FRAGMENT_STARTS and last in SHORT_FRAGMENT_PRONOUN_ENDS:
        return True
    return False


def looks_like_truncated_listening_answer(value: Any, source_text: Any) -> bool:
    lower = normalized_answer_key(value)
    if not lower or lower in ACCEPTABLE_FRAGMENT_ANSWERS:
        return False
    if lower in BAD_INCOMPLETE_ANSWERS:
        return True
    source_words = overlap_words(source_text)
    answer_words = overlap_words(lower)
    if len(answer_words) < 2 or len(source_words) <= len(answer_words) + 1:
        return False
    last = answer_words[-1]
    if last in INCOMPLETE_FINAL_CONTRACTIONS:
        return True
    if last in INCOMPLETE_FINAL_WORDS and not phrase_allows_trailing_preposition(lower):
        return True
    if len(answer_words) <= 3 and answer_words[0] in SHORT_WH_FRAGMENT_STARTS and last in SHORT_FRAGMENT_PRONOUN_ENDS:
        return True
    return False


def phrase_guide_key(phrase: str) -> str:
    lower = re.sub(r"\s+", " ", str(phrase or "").strip().lower())
    return PHRASE_GUIDE_ALIASES.get(lower, lower)
