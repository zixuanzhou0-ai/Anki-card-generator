from __future__ import annotations

import re
from typing import Any

from acg.documents.chunking import clip_words
from acg.phrases.lexicon import FILLER_TEXTS
from acg.subtitles.core import Cue, fmt_time, strip_subtitle_text
from acg.text_cleaning import clean_study_text

MEDIA_SUBTITLE_PARTIAL_EXPORT_BLOCK_THRESHOLD = 0.55
MEDIA_ALIGNMENT_PHRASE_NOT_FOUND_REASON = "phrase_not_found_in_media_alignment_text"
SOURCE_SENTENCE_QUALITY_MEDIA_BLOCK_FLAGS = {
    "possible_bad_join",
    "rolling_caption_uncertain",
    "rolling_caption_overlap",
    "too_long",
}


def overlap_words(value: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9']+", value.lower())


def looks_complete_sentence(text: str) -> bool:
    stripped = text.strip()
    words = overlap_words(stripped)
    return len(words) >= 4 and bool(re.search(r"[.?!]$|[.?!][\"']?$", stripped))


def is_filler_text(text: str) -> bool:
    words = overlap_words(text)
    return bool(words) and len(words) <= 2 and " ".join(words).strip(".?!") in FILLER_TEXTS


def merge_subtitle_parts(parts: list[str]) -> str:
    merged = ""
    for raw_part in parts:
        part = strip_subtitle_text(raw_part)
        if not part:
            continue
        if not merged:
            merged = part
            continue

        merged_norm = " ".join(overlap_words(merged))
        part_norm = " ".join(overlap_words(part))
        if not part_norm:
            continue
        if part_norm in merged_norm:
            continue
        if merged_norm and merged_norm in part_norm:
            merged = part
            continue

        merged_words = overlap_words(merged)
        part_words = overlap_words(part)
        overlap = 0
        max_overlap = min(len(merged_words), len(part_words))
        for size in range(max_overlap, 0, -1):
            if merged_words[-size:] == part_words[:size]:
                overlap = size
                break
        if overlap >= 2:
            merged = f"{merged} {' '.join(part_words[overlap:])}".strip()
        else:
            merged = f"{merged} {part}".strip()
    return strip_subtitle_text(merged)


def clean_candidate_text(text: str) -> str:
    text = strip_subtitle_text(text)
    if not text:
        return ""
    if re.search(r"[.?!][\"']?$", text):
        return text
    complete_parts = re.findall(r"[^.?!]+[.?!]", text)
    if not complete_parts:
        return text
    cleaned = " ".join(part.strip() for part in complete_parts if part.strip())
    if len(overlap_words(cleaned)) >= 4:
        return cleaned
    return text


def clean_adjacent_caption_repeats(text: str) -> str:
    """Remove obvious adjacent subtitle leftovers without changing source timing."""
    tokens = text.split()
    if len(tokens) < 2:
        return text.strip()
    cleaned: list[str] = []
    for token in tokens:
        norm = re.sub(r"^[^\w']+|[^\w']+$", "", token).lower()
        prev_token = cleaned[-1] if cleaned else ""
        prev_norm = re.sub(r"^[^\w']+|[^\w']+$", "", prev_token).lower() if prev_token else ""
        if norm and prev_norm:
            if norm == prev_norm and len(norm) >= 3:
                continue
            if len(prev_norm) >= 4 and len(norm) > len(prev_norm) and norm.startswith(prev_norm):
                cleaned[-1] = token
                continue
            if len(norm) >= 4 and len(prev_norm) > len(norm) and prev_norm.startswith(norm):
                continue
        cleaned.append(token)
    return " ".join(cleaned).strip()


def phrase_word_indices(text: str, phrase: str) -> tuple[int, int] | None:
    phrase_words = overlap_words(phrase)
    if not phrase_words or phrase == "key expression":
        return None
    text_words = overlap_words(text)
    if len(phrase_words) > len(text_words):
        return None
    for index in range(0, len(text_words) - len(phrase_words) + 1):
        if text_words[index : index + len(phrase_words)] == phrase_words:
            return index, index + len(phrase_words) - 1
    return None


def segment_media_bounds(start: float, end: float, text: str, phrase: str, review_mode: bool) -> tuple[float, float]:
    duration = max(0.1, end - start)
    words = overlap_words(text)
    if duration <= 3.8 or len(words) < 5:
        return max(0.0, start - 0.12), end + 0.18

    indices = phrase_word_indices(text, phrase)
    if not indices:
        return max(0.0, start - 0.12), end + 0.18

    first, last = indices
    before_words = 7 if review_mode else 5
    after_words = 7 if review_mode else 5
    window_first = max(0, first - before_words)
    window_after_last = min(len(words), last + 1 + after_words)
    media_start = start + duration * (window_first / max(1, len(words))) - 0.2
    media_end = start + duration * (window_after_last / max(1, len(words))) + 0.28
    media_start = max(0.0, media_start)
    media_end = min(end + 0.35, media_end)

    if media_end - media_start < 2.1:
        center = (media_start + media_end) / 2
        media_start = max(0.0, center - 1.05)
        media_end = center + 1.05
    if media_end - media_start > 6.2:
        max_duration = 6.2
        phrase_start = start + duration * (first / max(1, len(words))) - 0.08
        phrase_end = start + duration * ((last + 1) / max(1, len(words))) + 0.12
        center = (media_start + media_end) / 2
        proposed_start = max(0.0, center - (max_duration / 2))
        proposed_end = proposed_start + max_duration
        if proposed_start > phrase_start:
            proposed_start = max(0.0, phrase_start)
            proposed_end = proposed_start + max_duration
        if proposed_end < phrase_end:
            proposed_end = phrase_end
            proposed_start = max(0.0, proposed_end - max_duration)
        upper_bound = end + 0.35
        if proposed_end > upper_bound:
            proposed_end = upper_bound
            proposed_start = max(0.0, proposed_end - max_duration)
        media_start = proposed_start
        media_end = proposed_end
    return round(media_start, 3), round(media_end, 3)


def _word_sequence_indices(words: list[str], needle: list[str]) -> tuple[int, int] | None:
    if not words or not needle or len(needle) > len(words):
        return None
    for index in range(0, len(words) - len(needle) + 1):
        if words[index : index + len(needle)] == needle:
            return index, index + len(needle) - 1
    return None


def sentence_window_media_bounds(
    start: float,
    end: float,
    full_text: str,
    display_text: str,
) -> tuple[float, float, str]:
    """Return a media window that covers the card sentence, not only the answer phrase."""
    duration = max(0.1, end - start)
    full_words = overlap_words(full_text)
    display_words = overlap_words(display_text)
    if not full_words or not display_words:
        return round(max(0.0, start - 0.12), 3), round(end + 0.18, 3), "source_sentence_window"

    status = "source_sentence_window"
    first = 0
    last = len(full_words) - 1
    if display_words != full_words:
        indices = _word_sequence_indices(full_words, display_words)
        if indices:
            first, last = indices
            status = "display_sentence_window"
        else:
            status = "source_sentence_fallback"

    leading_pad = 0.2 if status == "display_sentence_window" else 0.12
    trailing_pad = 0.28 if status == "display_sentence_window" else 0.18
    media_start = start + duration * (first / max(1, len(full_words))) - leading_pad
    media_end = start + duration * ((last + 1) / max(1, len(full_words))) + trailing_pad
    media_start = max(0.0, media_start)
    media_end = min(end + 0.35, media_end)

    if media_end - media_start < 1.8:
        center = (media_start + media_end) / 2
        media_start = max(0.0, center - 0.9)
        media_end = min(end + 0.35, center + 0.9)
    if media_end <= media_start:
        media_start = max(0.0, start - 0.12)
        media_end = end + 0.18
        status = "source_sentence_fallback"
    return round(media_start, 3), round(media_end, 3), status


def align_segment_media_to_display_sentence(segment: dict[str, Any]) -> dict[str, Any]:
    display_text = clean_candidate_text(str(segment.get("text") or ""))
    full_text = clean_candidate_text(
        str(
            segment.get("full_source_sentence")
            or segment.get("source_sentence")
            or segment.get("source_evidence")
            or display_text
        )
    )
    display_words = overlap_words(display_text)
    full_words = overlap_words(full_text)
    if display_words and full_words and display_words != full_words and _word_sequence_indices(full_words, display_words):
        display_text = full_text
    if not display_text:
        return segment
    try:
        start = float(segment.get("start") or 0)
        end = float(segment.get("end") or start)
    except (TypeError, ValueError):
        return segment
    if end <= start:
        return segment
    media_start, media_end, status = sentence_window_media_bounds(start, end, full_text or display_text, display_text)
    return {
        **segment,
        "media_start": media_start,
        "media_end": media_end,
        "media_source_time": f"{fmt_time(media_start)} - {fmt_time(media_end)}",
        "media_alignment_status": status,
        "media_alignment_text": display_text,
        "media_alignment_source_text": full_text or display_text,
    }


def learning_point_media_alignment_fields(
    point: dict[str, Any],
    *,
    start: float,
    end: float,
    display_sentence: str,
) -> dict[str, Any]:
    """Return media fields for a selected learning point using full-source sentence alignment."""
    full_sentence = clean_adjacent_caption_repeats(
        clean_candidate_text(str(point.get("source_sentence") or display_sentence or ""))
    )
    media_text = full_sentence or display_sentence
    phrase = str(point.get("answer_core") or point.get("exact_span") or point.get("normalized_answer") or "").strip()
    phrase_located = bool(phrase and phrase_word_indices(media_text, phrase))
    review_status = "needs_review" if phrase and not phrase_located else "ok"
    review_reason = MEDIA_ALIGNMENT_PHRASE_NOT_FOUND_REASON if review_status == "needs_review" else ""
    aligned = align_segment_media_to_display_sentence(
        {
            "start": start,
            "end": end,
            "source_time": f"{fmt_time(start)} - {fmt_time(end)}",
            "text": display_sentence or media_text,
            "full_source_sentence": media_text,
            "source_sentence": media_text,
        }
    )
    return {
        "media_start": aligned.get("media_start"),
        "media_end": aligned.get("media_end"),
        "media_source_time": aligned.get("media_source_time") or f"{fmt_time(start)} - {fmt_time(end)}",
        "media_alignment_status": aligned.get("media_alignment_status") or "source_sentence_fallback",
        "media_alignment_phrase": phrase,
        "media_alignment_phrase_located": phrase_located,
        "media_alignment_review_status": review_status,
        "media_alignment_review_reason": review_reason,
        "media_alignment_text": aligned.get("media_alignment_text") or media_text,
        "media_alignment_source_text": aligned.get("media_alignment_source_text") or media_text,
    }


def refine_segment_media_for_phrase(
    segment: dict[str, Any],
    phrase: str,
    review_mode: bool = False,
) -> dict[str, Any]:
    """Keep exported media centered on the final learning phrase."""
    if not phrase or not phrase_word_indices(str(segment.get("text") or ""), phrase):
        return segment
    try:
        start = float(segment.get("start") or 0)
        end = float(segment.get("end") or start)
    except (TypeError, ValueError):
        return segment
    media_start, media_end = segment_media_bounds(
        start,
        end,
        str(segment.get("text") or ""),
        phrase,
        review_mode,
    )
    return {
        **segment,
        "media_start": media_start,
        "media_end": media_end,
        "media_source_time": f"{fmt_time(media_start)} - {fmt_time(media_end)}",
    }


def _counted_word_overlap_ratio(expected_text: str, actual_text: str) -> float:
    expected_words = overlap_words(expected_text)
    actual_words = overlap_words(actual_text)
    if not expected_words:
        return 0.0
    actual_counts: dict[str, int] = {}
    for word in actual_words:
        actual_counts[word] = actual_counts.get(word, 0) + 1
    matched = 0
    for word in expected_words:
        remaining = actual_counts.get(word, 0)
        if remaining <= 0:
            continue
        actual_counts[word] = remaining - 1
        matched += 1
    return matched / max(1, len(expected_words))


def media_subtitle_alignment_diagnostic(
    cues: list[Cue],
    media_start: float,
    media_end: float,
    expected_text: str,
) -> dict[str, Any]:
    if not cues:
        return {
            "media_subtitle_alignment_status": "unknown",
            "media_subtitle_alignment_reason": "subtitle_cues_unavailable",
        }
    overlap_cues = [
        cue
        for cue in cues
        if cue.end >= media_start - 0.05 and cue.start <= media_end + 0.05
    ]
    if not overlap_cues:
        return {
            "media_subtitle_alignment_status": "mismatch",
            "media_subtitle_alignment_reason": "no_subtitle_cues_overlap_media_window",
            "media_subtitle_overlap_score": 0.0,
        }
    subtitle_text = merge_subtitle_parts([cue.text for cue in overlap_cues])
    score = round(_counted_word_overlap_ratio(expected_text, subtitle_text), 3)
    if score >= 0.68:
        status = "matched"
    elif score >= 0.38:
        status = "partial"
    else:
        status = "mismatch"
    return {
        "media_subtitle_alignment_status": status,
        "media_subtitle_alignment_reason": "subtitle_window_overlap",
        "media_subtitle_overlap_score": score,
        "media_subtitle_time": f"{fmt_time(overlap_cues[0].start)} - {fmt_time(overlap_cues[-1].end)}",
        "media_subtitle_cue_count": len(overlap_cues),
        "media_window_subtitle_text": clip_words(subtitle_text, 90),
    }


def export_subtitle_alignment_diagnostics(
    export_segments: list[dict[str, Any]],
    subtitle_cues: list[Cue],
    export_subtitle_status: str,
    export_subtitle_path: str = "",
) -> dict[str, dict[str, Any]]:
    diagnostics: dict[str, dict[str, Any]] = {}
    for segment in export_segments:
        segment_id = str(segment.get("id") or "")
        try:
            media_start_for_diag = float(segment.get("media_start", segment.get("start", 0)) or 0)
            media_end_for_diag = float(segment.get("media_end", segment.get("end", media_start_for_diag)) or media_start_for_diag)
        except (TypeError, ValueError):
            media_start_for_diag = 0.0
            media_end_for_diag = 0.0
        expected_media_text = clean_candidate_text(
            str(
                segment.get("media_alignment_text")
                or segment.get("text")
                or segment.get("source_sentence")
                or segment.get("full_source_sentence")
                or ""
            )
        )
        if export_subtitle_status == "loaded":
            diagnostic = media_subtitle_alignment_diagnostic(
                subtitle_cues,
                media_start_for_diag,
                media_end_for_diag,
                expected_media_text,
            )
        else:
            diagnostic = {
                "media_subtitle_alignment_status": "unknown",
                "media_subtitle_alignment_reason": export_subtitle_status,
            }
        if export_subtitle_path:
            diagnostic["subtitle_path"] = export_subtitle_path
        diagnostics[segment_id] = diagnostic
    return diagnostics


def media_subtitle_alignment_blocks_export(diagnostic: dict[str, Any], segment: dict[str, Any]) -> bool:
    status = str(diagnostic.get("media_subtitle_alignment_status") or "").strip()
    if status == "mismatch":
        return True
    if status != "partial":
        return False
    try:
        score = float(diagnostic.get("media_subtitle_overlap_score") or 0)
    except (TypeError, ValueError):
        score = 0.0
    if score < MEDIA_SUBTITLE_PARTIAL_EXPORT_BLOCK_THRESHOLD:
        return True
    flags = {str(flag) for flag in segment.get("source_sentence_quality_flags") or []}
    return bool(flags & SOURCE_SENTENCE_QUALITY_MEDIA_BLOCK_FLAGS)


def media_subtitle_alignment_failure_reason(diagnostic: dict[str, Any], segment: dict[str, Any]) -> str:
    status = str(diagnostic.get("media_subtitle_alignment_status") or "").strip()
    if status == "mismatch":
        return str(diagnostic.get("media_subtitle_alignment_reason") or "media_subtitle_mismatch")
    flags = {str(flag) for flag in segment.get("source_sentence_quality_flags") or []}
    risky_flags = sorted(flags & SOURCE_SENTENCE_QUALITY_MEDIA_BLOCK_FLAGS)
    if risky_flags:
        return "partial_overlap_with_unreliable_source_sentence:" + ",".join(risky_flags)
    return "partial_overlap_below_export_threshold"


def segment_display_source_time(segment: dict[str, Any]) -> str:
    """Prefer the actual exported media window when showing a card time."""
    return clean_study_text(segment.get("media_source_time")) or clean_study_text(segment.get("source_time"))


def video_media_subtitle_mismatch_items(
    export_segments: list[dict[str, Any]],
    subtitle_alignment_by_segment: dict[str, dict[str, Any]],
    *,
    max_items: int = 20,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for segment in export_segments:
        segment_id = str(segment.get("id") or "")
        diagnostic = subtitle_alignment_by_segment.get(segment_id, {})
        if not media_subtitle_alignment_blocks_export(diagnostic, segment):
            continue
        expected_text = clean_candidate_text(
            str(
                segment.get("media_alignment_text")
                or segment.get("text")
                or segment.get("source_sentence")
                or segment.get("full_source_sentence")
                or ""
            )
        )
        if not expected_text:
            continue
        enabled_cards = [card for card in segment.get("cards", []) if card.get("enabled", True)]
        learning_point_ids = [
            str(card.get("learning_point_id") or card.get("id") or "")
            for card in enabled_cards
            if str(card.get("learning_point_id") or card.get("id") or "")
        ]
        card_titles = [
            clean_study_text(card.get("answer_core") or card.get("phrase") or card.get("english") or "")
            for card in enabled_cards[:3]
        ]
        items.append(
            {
                "segment_id": segment_id,
                "card_ids": [str(card.get("id") or "") for card in enabled_cards if str(card.get("id") or "")],
                "learning_point_ids": learning_point_ids,
                "card_titles": [title for title in card_titles if title],
                "source_time": str(segment.get("source_time") or ""),
                "media_source_time": str(segment.get("media_source_time") or ""),
                "expected_text": clip_words(expected_text, 40),
                "media_subtitle_time": str(diagnostic.get("media_subtitle_time") or ""),
                "media_subtitle_alignment_status": str(diagnostic.get("media_subtitle_alignment_status") or ""),
                "media_subtitle_overlap_score": diagnostic.get("media_subtitle_overlap_score"),
                "media_subtitle_alignment_reason": media_subtitle_alignment_failure_reason(diagnostic, segment),
                "media_window_subtitle_text": str(diagnostic.get("media_window_subtitle_text") or ""),
                "subtitle_path": str(diagnostic.get("subtitle_path") or ""),
                "source_sentence_quality_flags": segment.get("source_sentence_quality_flags") or [],
                "source_sentence_quality_status": str(segment.get("source_sentence_quality_status") or ""),
            }
        )
    return items[:max_items]
