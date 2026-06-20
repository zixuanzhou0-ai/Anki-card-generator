from __future__ import annotations

import re
from typing import Any

from acg.contracts.learning_point import SOURCE_SENTENCE_PROVENANCE_FIELDS
from acg.media_alignment import clean_candidate_text
from acg.subtitles.sentences import sentence_quality_flags, sentence_quality_status


def normalized_source_text_key(value: Any) -> str:
    text = clean_candidate_text(str(value or ""))
    return re.sub(r"\s+", " ", text).strip().casefold()


def source_sentence_indexes(
    source_sentences: list[dict[str, Any]] | tuple[dict[str, Any], ...] | Any,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_id: dict[str, dict[str, Any]] = {}
    by_text: dict[str, dict[str, Any]] = {}
    for item in source_sentences or []:
        if not isinstance(item, dict):
            continue
        for key in ("id", "source_segment_id"):
            item_id = str(item.get(key) or "").strip()
            if item_id:
                by_id[item_id] = item
        text_key = normalized_source_text_key(item.get("source_sentence") or item.get("text") or "")
        if text_key:
            by_text[text_key] = item
    return by_id, by_text


def source_sentence_for_point(
    point: dict[str, Any],
    by_id: dict[str, dict[str, Any]],
    by_text: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    source_id = str(point.get("source_segment_id") or "").strip()
    if source_id and source_id in by_id:
        return by_id[source_id]
    text_key = normalized_source_text_key(point.get("source_sentence") or "")
    return by_text.get(text_key, {})


def point_with_source_sentence_provenance(
    point: dict[str, Any],
    by_id: dict[str, dict[str, Any]],
    by_text: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    source_sentence = source_sentence_for_point(point, by_id, by_text) or {}
    merged = dict(point)
    for key in SOURCE_SENTENCE_PROVENANCE_FIELDS:
        if merged.get(key) in (None, "", []) and source_sentence.get(key) not in (None, "", []):
            merged[key] = source_sentence.get(key)
    if merged.get("start") in (None, "") and source_sentence.get("start") not in (None, ""):
        merged["start"] = source_sentence.get("start")
    if merged.get("end") in (None, "") and source_sentence.get("end") not in (None, ""):
        merged["end"] = source_sentence.get("end")
    if merged.get("start") in (None, "") and source_sentence.get("source_cue_start") not in (None, ""):
        merged["start"] = source_sentence.get("source_cue_start")
    if merged.get("end") in (None, "") and source_sentence.get("source_cue_end") not in (None, ""):
        merged["end"] = source_sentence.get("source_cue_end")
    if merged.get("source_sentence") in (None, "") and source_sentence.get("source_sentence"):
        merged["source_sentence"] = source_sentence.get("source_sentence")
    if merged.get("source_time") in (None, ""):
        merged["source_time"] = source_sentence.get("source_time") or source_sentence.get("source_cue_time") or ""

    text = str(merged.get("source_sentence") or source_sentence.get("source_sentence") or source_sentence.get("text") or "")
    cue_texts = merged.get("source_cue_texts") or source_sentence.get("source_cue_texts") or []
    if merged.get("source_sentence_quality_flags") in (None, "", []):
        flags = sentence_quality_flags(text, cue_texts if isinstance(cue_texts, list) else [])
        merged["source_sentence_quality_flags"] = flags
    if merged.get("source_sentence_quality_status") in (None, ""):
        flags = merged.get("source_sentence_quality_flags") or []
        merged["source_sentence_quality_status"] = sentence_quality_status([str(flag) for flag in flags])
    return merged
