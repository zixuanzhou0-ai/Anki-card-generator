from __future__ import annotations

import re
import zlib
from collections.abc import Callable
from collections import Counter
from typing import Any

from acg.subtitles.core import Cue, fmt_time, strip_subtitle_text


SENTENCE_QUALITY_CLEAN = "clean"
SENTENCE_QUALITY_NEEDS_REVIEW = "needs_review"

SOURCE_SENTENCE_QUALITY_DEMOTE_FLAGS = {
    "fragment",
    "possible_bad_join",
    "repeated_adjacent_words",
    "too_long",
    "rolling_caption_uncertain",
    "rolling_caption_overlap",
}

RESTART_WORDS = {
    "I",
    "I'm",
    "I’m",
    "I'll",
    "I’ll",
    "I've",
    "I’ve",
    "I'd",
    "I’d",
    "You",
    "You're",
    "You’re",
    "You've",
    "You’ve",
    "You'll",
    "You’ll",
    "He",
    "He's",
    "She",
    "She's",
    "It",
    "It's",
    "We",
    "We're",
    "They",
    "They're",
    "This",
    "That",
    "These",
    "Those",
    "There",
    "Here",
    "Now",
    "First",
    "Second",
    "Third",
    "But",
    "So",
    "And",
    "The",
    "A",
    "An",
}

QUESTION_RESTART_WORDS = {
    "What",
    "What's",
    "What’s",
    "When",
    "Where",
    "Who",
    "Who's",
    "Who’s",
    "Whom",
    "Whose",
    "Why",
    "How",
    "Do",
    "Does",
    "Did",
    "Can",
    "Could",
    "Would",
    "Will",
    "Should",
    "Is",
    "Are",
    "Was",
    "Were",
    "Have",
    "Has",
    "Had",
}

RESTART_PREVIOUS_WORD_ALLOWLIST = {
    "if",
    "when",
    "where",
    "why",
    "how",
    "what",
    "that",
    "which",
    "who",
    "because",
    "since",
    "as",
    "and",
    "or",
    "but",
    "so",
    "english",
}

FRAGMENT_STARTS = {
    "than",
    "because",
    "but",
    "and",
    "or",
    "so",
    "then",
    "to",
    "for",
    "of",
    "with",
    "from",
    "at",
    "which",
}

REPEATED_DISFLUENCY_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "but",
    "he",
    "her",
    "him",
    "his",
    "i",
    "in",
    "is",
    "it",
    "its",
    "of",
    "or",
    "she",
    "that",
    "the",
    "their",
    "they",
    "this",
    "to",
    "um",
    "uh",
    "we",
    "you",
    "your",
}


def sentence_words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9']+", text)


def word_spans(text: str) -> list[re.Match[str]]:
    return list(re.finditer(r"[A-Za-z0-9']+", text))


def _caption_overlap_words(text: str) -> list[str]:
    return [word.lower() for word in sentence_words(text)]


def incremental_caption_text(previous_text: str, current_text: str) -> tuple[str, bool]:
    previous_words = _caption_overlap_words(previous_text)
    current_words = _caption_overlap_words(current_text)
    max_overlap = min(len(previous_words), len(current_words))
    overlap = 0
    for size in range(max_overlap, 1, -1):
        if previous_words[-size:] == current_words[:size]:
            overlap = size
            break
    if overlap < 2:
        return current_text, False

    spans = word_spans(current_text)
    if len(spans) < overlap:
        return current_text, False
    suffix = current_text[spans[overlap - 1].end() :].strip(" \t\r\n,")
    return suffix, True


def split_caption_fragment(text: str, start: float, end: float) -> list[tuple[str, float, float]]:
    text = strip_subtitle_text(text)
    if not text:
        return []
    parts: list[tuple[str, float, float]] = []
    cursor = 0
    duration = max(0.01, end - start)
    for match in re.finditer(r"[^.?!]+[.?!]+", text):
        fragment = strip_subtitle_text(match.group(0))
        if fragment:
            part_start = start + duration * (match.start() / max(1, len(text)))
            part_end = start + duration * (match.end() / max(1, len(text)))
            parts.append((fragment, part_start, part_end))
        cursor = match.end()
    tail = strip_subtitle_text(text[cursor:])
    if tail:
        part_start = start + duration * (cursor / max(1, len(text)))
        parts.append((tail, part_start, end))
    return parts


def append_caption_text(left: str, right: str) -> str:
    left = strip_subtitle_text(left)
    right = strip_subtitle_text(right)
    if not left:
        return right
    if not right:
        return left
    if re.search(r"[-/([{]$", left):
        return f"{left}{right}"
    return f"{left} {right}"


def stitch_sentence_cues(chunks: list[Cue]) -> list[Cue]:
    sentences: list[Cue] = []
    buffer = ""
    buffer_start = 0.0
    buffer_end = 0.0
    index = 1

    def flush_buffer() -> None:
        nonlocal buffer, buffer_start, buffer_end, index
        clean = strip_subtitle_text(buffer)
        if len(_caption_overlap_words(clean)) >= 3:
            sentences.append(Cue(index, buffer_start, buffer_end, clean))
            index += 1
        buffer = ""

    for cue in chunks:
        for fragment, frag_start, frag_end in split_caption_fragment(cue.text, cue.start, cue.end):
            if not buffer:
                buffer_start = frag_start
            buffer = append_caption_text(buffer, fragment)
            buffer_end = frag_end
            clean = strip_subtitle_text(buffer)
            words = _caption_overlap_words(clean)
            if re.search(r"[.?!][\"']?$", fragment):
                flush_buffer()
            elif len(words) >= 12 or (len(words) >= 7 and buffer_end - buffer_start >= 3.2):
                flush_buffer()

    tail = strip_subtitle_text(buffer)
    if len(_caption_overlap_words(tail)) >= 3:
        sentences.append(Cue(index, buffer_start, buffer_end, tail))

    return sentences or chunks


def normalize_rolling_cues(cues: list[Cue]) -> list[Cue]:
    chunks: list[Cue] = []
    previous_text = ""
    rolling_hits = 0

    for cue in cues:
        incremental, overlapped = incremental_caption_text(previous_text, cue.text)
        if overlapped:
            rolling_hits += 1
        clean = strip_subtitle_text(incremental)
        if clean:
            chunks.append(Cue(len(chunks) + 1, cue.start, cue.end, clean))
        previous_text = cue.text

    if cues and rolling_hits / max(1, len(cues)) >= 0.18:
        return stitch_sentence_cues(chunks)
    return cues


def has_unbalanced_quotes(text: str) -> bool:
    value = str(text or "")
    return value.count('"') % 2 == 1 or value.count("“") != value.count("”")


def starts_like_fragment(text: str) -> bool:
    words = [word.lower() for word in sentence_words(text)]
    if not words:
        return True
    if text.strip()[:1] in {".", "?", "!", ",", ";", ":"}:
        return True
    if words[0] in {"about", "of", "for", "to", "with", "from", "because", "and", "or", "but", "so"}:
        return True
    first_char = text.strip()[:1]
    return bool(first_char and first_char.islower() and words[0] not in {"i"} and not text.lower().startswith(("i ", "i'm", "i've")))


def has_terminal_punctuation(text: str) -> bool:
    return bool(re.search(r"[.?!][\"'”’)]*$", str(text or "").strip()))


def has_unpunctuated_sentence_restart(text: str) -> bool:
    """Detect likely cue joins such as "everyday You're confident".

    This is intentionally conservative: it only flags a restart-looking
    capitalized token after a lowercase word and ignores common embedded forms
    such as "when I" or "the English I use".
    """
    if not text:
        return False
    restart_pattern = "|".join(re.escape(word) for word in sorted(RESTART_WORDS, key=len, reverse=True))
    pattern = re.compile(r"\b([a-z][a-z']{2,})\s+(" + restart_pattern + r")\b")
    for match in pattern.finditer(text):
        previous = match.group(1).casefold()
        if previous in RESTART_PREVIOUS_WORD_ALLOWLIST:
            continue
        return True
    return False


def has_unpunctuated_question_restart(text: str) -> bool:
    """Detect likely joins where a new question starts mid sentence.

    YouTube rolling captions often produce fragments like
    ``rehearsed a How did you know...`` when two speaker turns were joined.
    The generic restart detector intentionally ignores very short previous
    words to avoid noise, so question restarts get a narrower rule here.
    """
    if not text:
        return False
    restart_pattern = "|".join(
        re.escape(word) for word in sorted(QUESTION_RESTART_WORDS, key=len, reverse=True)
    )
    pattern = re.compile(r"\b([A-Za-z][A-Za-z']*)\s+(" + restart_pattern + r")\b")
    for match in pattern.finditer(text):
        previous = match.group(1).casefold()
        if previous in RESTART_PREVIOUS_WORD_ALLOWLIST:
            continue
        # Lowercase/short previous token followed by a capitalized question
        # opener is a strong signal that cue boundaries were incorrectly
        # merged. Proper embedded questions are usually lowercased ("how").
        if previous and match.group(2)[0].isupper():
            return True
    return False


def repeated_adjacent_caption_tokens(cue_texts: list[str]) -> bool:
    if len(cue_texts) < 2:
        return False
    normalized = [sentence_words(strip_subtitle_text(text).lower()) for text in cue_texts]
    for left, right in zip(normalized, normalized[1:]):
        if not left or not right:
            continue
        max_overlap = min(len(left), len(right), 8)
        for size in range(max_overlap, 1, -1):
            if left[-size:] == right[:size]:
                return True
    return False


def starts_with_lowercase_fragment(text: str) -> bool:
    stripped = str(text or "").lstrip(" \t\r\n\"'“‘(")
    return bool(re.match(r"^[a-z][a-z']{2,},\s+(?:and|but|or|because|which|that|when|while|as)\b", stripped))


def has_adjacent_disfluency_repetition(text: str) -> bool:
    words = [word.casefold() for word in sentence_words(text)]
    for left, right in zip(words, words[1:]):
        if left == right and left in REPEATED_DISFLUENCY_WORDS:
            return True
    return False


def sentence_quality_flags(text: str, cue_texts: list[str] | None = None) -> list[str]:
    clean_text = strip_subtitle_text(text)
    cue_texts = cue_texts or []
    words = sentence_words(clean_text)
    flags: list[str] = []

    if len(words) >= 24 or len(clean_text) >= 170:
        flags.append("too_long")
    if words and (words[0].casefold() in FRAGMENT_STARTS or starts_with_lowercase_fragment(clean_text)):
        flags.append("fragment")
    if len(cue_texts) > 1 and (
        has_unpunctuated_sentence_restart(clean_text)
        or has_unpunctuated_question_restart(clean_text)
    ):
        flags.append("possible_bad_join")
    if len(cue_texts) > 1 and not has_terminal_punctuation(clean_text) and len(words) >= 14:
        flags.append("rolling_caption_uncertain")
    if repeated_adjacent_caption_tokens(cue_texts):
        flags.append("rolling_caption_overlap")
    if has_adjacent_disfluency_repetition(clean_text):
        flags.append("repeated_adjacent_words")

    return flags or [SENTENCE_QUALITY_CLEAN]


def sentence_quality_status(flags: list[str]) -> str:
    actionable = {flag for flag in flags if flag != SENTENCE_QUALITY_CLEAN}
    if actionable & {
        "fragment",
        "possible_bad_join",
        "repeated_adjacent_words",
        "too_long",
        "rolling_caption_uncertain",
        "rolling_caption_overlap",
    }:
        return SENTENCE_QUALITY_NEEDS_REVIEW
    return SENTENCE_QUALITY_CLEAN


def source_sentence_provenance(cues: list[Cue], text: str, merge_reason: str) -> dict[str, Any]:
    cue_texts = [cue.text for cue in cues]
    flags = sentence_quality_flags(text, cue_texts)
    return {
        "source_cue_ids": [cue.index for cue in cues],
        "source_cue_count": len(cues),
        "source_cue_start": round(cues[0].start, 3) if cues else None,
        "source_cue_end": round(cues[-1].end, 3) if cues else None,
        "source_cue_time": f"{fmt_time(cues[0].start)} - {fmt_time(cues[-1].end)}" if cues else "",
        "source_cue_texts": cue_texts,
        "source_merge_reason": merge_reason,
        "source_sentence_quality_flags": flags,
        "source_sentence_quality_status": sentence_quality_status(flags),
    }


def source_segment_key(start: float, end: float, text: str) -> str:
    normalized_text = re.sub(r"\s+", " ", str(text or "").strip().lower())[:96]
    source_seed = f"{start:.3f}:{end:.3f}:{normalized_text}"
    return f"src_{zlib.crc32(source_seed.encode('utf-8')) & 0xFFFFFFFF:08x}"


def source_sentences_from_cues(
    cues: list[Cue],
    *,
    language: Any = "en",
    merge_subtitle_parts: Callable[[list[str]], str],
    clean_candidate_text: Callable[[str], str],
    looks_complete_sentence: Callable[[str], bool],
    source_segment_key: Callable[[float, float, str], str] = source_segment_key,
    normalize_language: Callable[[Any], str] = lambda value: str(value or "en"),
    max_gap_seconds: float = 0.9,
    max_window_seconds: float = 7.5,
) -> list[dict[str, Any]]:
    sentences: list[dict[str, Any]] = []
    i = 0
    while i < len(cues):
        start = cues[i].start
        end = cues[i].end
        parts = [cues[i].text]
        j = i
        while j + 1 < len(cues):
            current = merge_subtitle_parts(parts)
            gap = cues[j + 1].start - end
            if looks_complete_sentence(current) or gap > max_gap_seconds or (end - start) >= max_window_seconds:
                break
            j += 1
            end = cues[j].end
            parts.append(cues[j].text)
        text = clean_candidate_text(merge_subtitle_parts(parts))
        if text:
            source_id = source_segment_key(start, end, text)
            cue_window = cues[i : j + 1]
            merge_reason = "single_cue" if j == i else "merged_until_sentence_boundary"
            sentences.append(
                {
                    "id": source_id,
                    "source_segment_id": source_id,
                    "source_sentence": text,
                    "text": text,
                    "start": round(start, 3),
                    "end": round(end, 3),
                    "source_time": f"{fmt_time(start)} - {fmt_time(end)}",
                    "language": normalize_language(language),
                    **source_sentence_provenance(cue_window, text, merge_reason),
                }
            )
        i = max(j + 1, i + 1)
    for index, sentence in enumerate(sentences):
        sentence["previous_sentence"] = sentences[index - 1]["source_sentence"] if index > 0 else ""
        sentence["next_sentence"] = sentences[index + 1]["source_sentence"] if index + 1 < len(sentences) else ""
    return sentences


def sentence_quality_counts(source_sentences: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for sentence in source_sentences:
        for flag in sentence.get("source_sentence_quality_flags") or [SENTENCE_QUALITY_CLEAN]:
            counts[str(flag)] += 1
    return dict(counts)


def apply_source_sentence_quality_gate(point: dict[str, Any]) -> dict[str, Any]:
    flags = {str(flag) for flag in point.get("source_sentence_quality_flags") or []}
    if str(point.get("status") or "") != "recommended":
        return point
    if not (flags & SOURCE_SENTENCE_QUALITY_DEMOTE_FLAGS):
        return point
    reason = str(point.get("status_reason") or point.get("reason") or "").strip()
    quality_reason = "字幕句子边界不够可靠，已从默认推荐降为候选；确认原句和视频对齐后仍可手动勾选。"
    return {
        **point,
        "status": "candidate_only",
        "status_reason": f"{reason} {quality_reason}".strip(),
        "source_sentence_quality_gate": "demoted_from_recommended",
    }
