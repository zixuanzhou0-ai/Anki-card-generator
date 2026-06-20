from __future__ import annotations

import re
from typing import Any

from acg.card_quality import allows_function_start_phrase, is_too_basic_for_level, phrase_guide_key
from acg.language_text import overlap_words
from acg.learning_spans import normalize_candidate_span, normalized_phrase_key, phrase_in_text
from acg.learning_types import candidate_kind_for_phrase_type, candidate_kind_for_segment
from acg.phrase_discovery import is_low_value_standalone_phrase, is_non_transferable_phrase, usable_phrase
from acg.phrases.lexicon import COMMON_FUNCTION_STARTS


def requested_card_types(card_types: list[str]) -> list[str]:
    requested = [str(card_type) for card_type in card_types if card_type in {"listening", "phrase", "cloze"}]
    return requested or ["phrase"]


def has_listening_training_value(text: str) -> bool:
    lower = str(text or "").lower()
    words = overlap_words(text)
    return bool(
        len(words) >= 8
        and (
            re.search(r"\b(?:i'm|you're|we're|they're|don't|can't|won't|i've|let's)\b", lower)
            or re.search(r"\b(?:gonna|wanna|gotta)\b", lower)
        )
    )


def has_output_training_value(phrase: str, level: str) -> bool:
    lower = re.sub(r"\s+", " ", str(phrase or "").strip().lower())
    if is_too_basic_for_level(lower, level):
        return False
    low_value_output_phrases = {
        "by the way",
        "make sure",
        "talk about",
        "talking about",
        "what about",
        "how about",
    }
    if lower in low_value_output_phrases:
        return False
    output_worthy_phrases = {"in the mood for", "end up", "turn out", "figure out", "make sense", "i see what you mean"}
    return bool(lower in output_worthy_phrases or phrase_guide_key(lower) in output_worthy_phrases)


def usable_learning_point_span(
    text: str,
    span: str,
    candidate_kind: str = "expression",
    phrase_type: str = "",
) -> bool:
    normalized = normalize_candidate_span(span)
    if not normalized or normalized.lower() == "key expression":
        return False
    words = overlap_words(normalized)
    if not words:
        return phrase_in_text(text, normalized)
    if not phrase_in_text(text, normalized) and len(words) >= 2:
        return False
    kind = candidate_kind or candidate_kind_for_phrase_type(phrase_type)
    if kind == "contextual_vocab":
        return 1 <= len(words) <= 3
    if kind in {"grammar_pattern", "listening_feature"}:
        return len(words) <= 12
    if kind in {"expression", "pragmatic_risk"} and phrase_type in {"collocation", "idiom", "spoken_phrase"}:
        if 2 <= len(words) <= 7 and phrase_in_text(text, normalized):
            if not is_non_transferable_phrase(normalized) and not is_low_value_standalone_phrase(normalized):
                if words[0] not in COMMON_FUNCTION_STARTS or allows_function_start_phrase(normalized):
                    return True
    return usable_phrase(text, normalized)


def plan_card_types(segment: dict[str, Any], card_types: list[str], level: str) -> dict[str, Any]:
    requested = requested_card_types(card_types)
    phrase = re.sub(r"\s+", " ", str(segment.get("phrase") or "").strip())
    text = str(segment.get("text") or "")
    candidate_kind = candidate_kind_for_segment(segment)

    if candidate_kind == "listening_feature" and "listening" in requested:
        primary = "listening"
        reason = "这个片段的核心价值是听懂真实语速下的弱读、连读或缩读。"
    elif "phrase" in requested and usable_learning_point_span(text, phrase, candidate_kind, str(segment.get("phrase_type") or "")):
        primary = "phrase"
        if candidate_kind == "contextual_vocab":
            reason = "这个片段的核心价值是掌握一个词在原句里的真实语境义。"
        elif candidate_kind == "grammar_pattern":
            reason = "这个片段的核心价值是掌握一个可迁移的语法/句法框架。"
        elif candidate_kind == "pragmatic_risk":
            reason = "这个片段的核心价值是理解表达的语气、边界和冒犯风险。"
        else:
            reason = "这个片段的核心价值是把自然表达迁移到自己的口语里。"
    elif "listening" in requested:
        primary = "listening"
        reason = "这个片段更适合先做听音辨句，表达本身不够适合作为主词伙。"
    else:
        primary = requested[0]
        reason = "按用户选择的卡型保留一张主训练卡。"

    planned = [primary]
    optional: list[str] = []
    skipped: dict[str, str] = {}

    if "listening" in requested and primary != "listening":
        if has_listening_training_value(text):
            optional.append("listening")
        else:
            skipped["listening"] = "听力难点不明显，合并到主卡里即可。"
    if "cloze" in requested and primary != "cloze":
        if has_output_training_value(phrase, level):
            optional.append("cloze")
        else:
            skipped["cloze"] = "表达偏基础或输出价值不足，不单独做填空卡。"
    if "phrase" in requested and primary != "phrase":
        skipped["phrase"] = "没有稳定、完整、可迁移的表达，不单独做表达卡。"

    if optional:
        planned.extend(card_type for card_type in optional if card_type not in planned)

    for card_type in requested:
        if card_type not in planned and card_type not in skipped:
            skipped[card_type] = "训练目标已被主卡覆盖。"

    return {
        "primary": primary,
        "types": planned,
        "reason": reason,
        "skipped": skipped,
    }


def card_type_for_learning_point(point: dict[str, Any], requested: list[str]) -> str:
    kind = str(point.get("kind") or "")
    suggested = str(point.get("suggested_card_type") or "")
    answer = normalized_phrase_key(str(point.get("answer_core") or point.get("normalized_answer") or point.get("exact_span") or ""))
    if answer in {"", "key expression"} and "listening" in requested:
        return "listening"
    if suggested in requested:
        return suggested
    if kind == "listening_feature" and "listening" in requested:
        return "listening"
    if "phrase" in requested:
        return "phrase"
    if "cloze" in requested:
        return "cloze"
    if "listening" in requested:
        return "listening"
    return requested[0] if requested else "phrase"
