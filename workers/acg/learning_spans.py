from __future__ import annotations

import re
from typing import Any

from acg.language_text import expanded_overlap_words


def normalize_candidate_span(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip(" \t\r\n\"'“”‘’.,?!"))


def normalized_phrase_key(phrase: Any) -> str:
    return re.sub(r"\s+", " ", str(phrase or "").strip().lower())


def expression_span_from_text(text: str, pattern: str) -> str:
    match = re.search(pattern, text, re.IGNORECASE)
    return normalize_candidate_span(match.group(0)) if match else ""


def exact_span_offsets(text: str, span: str) -> tuple[int | None, int | None]:
    source = str(text or "")
    target = str(span or "").strip()
    if not source or not target:
        return None, None
    direct = source.lower().find(target.lower())
    if direct >= 0:
        return direct, direct + len(target)
    pattern = r"\s+".join(re.escape(part) for part in target.split())
    if not pattern:
        return None, None
    match = re.search(pattern, source, flags=re.IGNORECASE)
    if not match:
        return None, None
    return match.start(), match.end()


def phrase_in_text(text: str, phrase: str) -> bool:
    raw_text = normalize_candidate_span(text).casefold()
    raw_phrase = normalize_candidate_span(phrase).casefold()
    if raw_phrase and raw_phrase in raw_text:
        return True
    has_gap_marker = bool(re.search(r"\.{2,}|…", str(phrase or "")))
    normalized_text = " ".join(expanded_overlap_words(text))
    normalized_phrase = " ".join(expanded_overlap_words(re.sub(r"\.{2,}|…", " ", str(phrase or ""))))
    if not normalized_phrase:
        return False
    if normalized_phrase in normalized_text:
        return True

    phrase_words = normalized_phrase.split()
    text_words = normalized_text.split()
    if len(phrase_words) < 2:
        return False

    def word_matches(pattern_word: str, text_word: str) -> bool:
        if pattern_word in {"someone", "somebody"}:
            return text_word in {"me", "you", "him", "her", "us", "them", "someone", "somebody"}
        if pattern_word == "something":
            return text_word in {"it", "this", "that", "things", "something", "everything"}
        return pattern_word == text_word

    max_extra_words = 8 if has_gap_marker else 2
    for first in [index for index, word in enumerate(text_words) if word_matches(phrase_words[0], word)]:
        position = first
        extra_words = 0
        matched = 1
        for phrase_word in phrase_words[1:]:
            found = -1
            scan_end = min(len(text_words), position + max_extra_words + 3)
            for index in range(position + 1, scan_end):
                if word_matches(phrase_word, text_words[index]):
                    found = index
                    break
            if found == -1:
                break
            extra_words += found - position - 1
            if extra_words > max_extra_words:
                break
            position = found
            matched += 1
        if matched == len(phrase_words):
            return True
    return False
