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
    # v0.9.6 keeps legacy phrase-compatible fields but exports one unified learning card per learning point.
    return ["phrase"]


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
    candidate_kind = candidate_kind_for_segment(segment)
    reason_by_kind = {
        "contextual_vocab": "统一学习卡会聚焦这个词在原句里的真实语境义。",
        "grammar_pattern": "统一学习卡会聚焦这个可迁移的语法/句法框架。",
        "listening_feature": "统一学习卡会把听辨提醒合并到同一张卡里，避免额外重复听力卡。",
        "pragmatic_risk": "统一学习卡会聚焦表达的语气、边界和使用风险。",
    }
    skipped = {
        str(card_type): "已合并到统一学习卡，避免为同一学习点生成重复卡。"
        for card_type in card_types
        if str(card_type) in {"listening", "cloze"}
    }
    return {
        "primary": "phrase",
        "types": requested_card_types(card_types),
        "reason": reason_by_kind.get(candidate_kind, "统一学习卡会聚焦这句里最值得复习的核心学习动作。"),
        "skipped": skipped,
    }


def card_type_for_learning_point(point: dict[str, Any], requested: list[str]) -> str:
    return "phrase"
