from __future__ import annotations

import re
from typing import Any

from acg.text_cleaning import clean_study_text
from acg.tts_text import clean_tts_input_text


def front_fields_for_export_media(
    front_fields: dict[str, str],
    *,
    repetition_mode: bool,
    has_original_audio: bool,
    has_tts_audio: bool,
) -> dict[str, str]:
    if not repetition_mode or has_original_audio or not has_tts_audio:
        return front_fields
    adjusted = dict(front_fields)
    if adjusted.get("front_prompt") == "听原声，跟读这一句。":
        adjusted["front_prompt"] = "听慢读，跟读这一句。"
    if adjusted.get("front_content") == "先听一遍，再模仿语气和节奏。":
        adjusted["front_content"] = "先听慢读，再模仿语气和节奏。"
    return adjusted


def card_sentence_tts_text(segment: dict[str, Any], cards: list[dict[str, Any]]) -> str:
    phrase_texts: list[str] = []
    for card in cards:
        for value in [card.get("answer_core"), card.get("phrase"), card.get("normalized_answer")]:
            text = clean_study_text(value).lower()
            if text:
                phrase_texts.append(text)

    candidates: list[tuple[int, str]] = []
    for priority, value in [
        (100, segment.get("sentence_tts_text")),
        (96, segment.get("full_source_sentence")),
        (92, segment.get("source_sentence")),
        (88, segment.get("source_evidence")),
        (84, segment.get("media_alignment_source_text")),
        (10, segment.get("text")),
    ]:
        candidates.append((priority, clean_study_text(value)))
    for card in cards:
        for priority, value in [
            (82, card.get("full_source_sentence")),
            (78, card.get("source_sentence")),
            (74, card.get("source_evidence")),
            (70, card.get("english")),
        ]:
            candidates.append((priority, clean_study_text(value)))

    best_text = ""
    best_score = -10_000
    seen: set[str] = set()
    for priority, text in candidates:
        if not text:
            continue
        normalized = re.sub(r"\s+", " ", text).strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        try:
            tts_text = clean_tts_input_text(text)
        except RuntimeError:
            continue
        word_count = len(re.findall(r"[\w']+", normalized))
        phrase_hit = any(phrase and phrase in normalized for phrase in phrase_texts)
        phrase_exact = any(phrase and phrase == normalized for phrase in phrase_texts)
        score = priority + min(word_count, 40)
        if phrase_hit:
            score += 12
        if word_count >= 6:
            score += 16
        if phrase_exact and word_count <= 5:
            score -= 90
        if score > best_score:
            best_score = score
            best_text = tts_text
    return best_text
