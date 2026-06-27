from __future__ import annotations

import re
from typing import Any

from acg.learning_settings import normalized_language_focus
from acg.learning_spans import normalized_phrase_key
from acg.text_cleaning import clean_study_text


PHRASE_TYPE_CARD_LABELS = {
    "spoken_phrase": "学习卡",
    "sentence_frame": "学习卡",
    "collocation": "学习卡",
    "discourse_marker": "学习卡",
    "idiom": "学习卡",
    "listening_sentence": "学习卡",
    "vocabulary_usage": "学习卡",
    "grammar_pattern": "学习卡",
}

PHRASE_TYPE_CONTENT_KIND = {
    "spoken_phrase": "phrase",
    "sentence_frame": "grammar",
    "collocation": "phrase",
    "discourse_marker": "phrase",
    "idiom": "phrase",
    "listening_sentence": "listening",
    "vocabulary_usage": "vocabulary",
    "grammar_pattern": "grammar",
}

CANDIDATE_KIND_TO_PHRASE_TYPE = {
    "expression": "spoken_phrase",
    "contextual_vocab": "vocabulary_usage",
    "grammar_pattern": "grammar_pattern",
    "listening_feature": "listening_sentence",
    "pragmatic_risk": "idiom",
}

PHRASE_TYPE_TO_CANDIDATE_KIND = {
    "spoken_phrase": "expression",
    "sentence_frame": "grammar_pattern",
    "collocation": "expression",
    "discourse_marker": "expression",
    "idiom": "expression",
    "listening_sentence": "listening_feature",
    "vocabulary_usage": "contextual_vocab",
    "grammar_pattern": "grammar_pattern",
}


def card_label_for_phrase_type(phrase_type: str, fallback: str = "学习卡") -> str:
    return PHRASE_TYPE_CARD_LABELS.get(str(phrase_type or "").strip(), fallback)


def card_label_for_learning_card(phrase_type: str, content_kind: str, fallback: str = "学习卡") -> str:
    return "学习卡"


def content_kind_for_phrase_type(phrase_type: str, fallback: str = "phrase") -> str:
    return PHRASE_TYPE_CONTENT_KIND.get(str(phrase_type or "").strip(), fallback)


def candidate_kind_for_phrase_type(phrase_type: str, fallback: str = "expression") -> str:
    return PHRASE_TYPE_TO_CANDIDATE_KIND.get(str(phrase_type or "").strip(), fallback)


def phrase_type_for_candidate_kind(candidate_kind: str, fallback: str = "spoken_phrase") -> str:
    return CANDIDATE_KIND_TO_PHRASE_TYPE.get(str(candidate_kind or "").strip(), fallback)


def candidate_kind_for_segment(segment: dict[str, Any]) -> str:
    explicit = str(segment.get("candidate_kind") or "").strip()
    if explicit:
        return explicit
    content_kind = str(segment.get("content_kind") or "").strip()
    if content_kind == "vocabulary":
        return "contextual_vocab"
    if content_kind == "grammar":
        return "grammar_pattern"
    if content_kind == "listening":
        return "listening_feature"
    return candidate_kind_for_phrase_type(str(segment.get("phrase_type") or ""), "expression")


def normalize_candidate_kind(value: Any, fallback: str = "expression") -> str:
    kind = str(value or "").strip()
    return kind if kind in CANDIDATE_KIND_TO_PHRASE_TYPE else fallback


def normalize_phrase_type(value: Any, candidate_kind: str = "expression") -> str:
    phrase_type = str(value or "").strip()
    if phrase_type in PHRASE_TYPE_TO_CANDIDATE_KIND:
        return phrase_type
    return phrase_type_for_candidate_kind(candidate_kind)


def candidate_kind_allowed_by_focus(candidate_kind: str, payload: dict[str, Any]) -> bool:
    focus = set(normalized_language_focus(payload))
    if candidate_kind in {"expression", "pragmatic_risk"}:
        return "phrases" in focus
    if candidate_kind == "contextual_vocab":
        return "vocabulary" in focus
    if candidate_kind == "listening_feature":
        return "listening" in focus
    if candidate_kind == "grammar_pattern":
        # Spoken ellipsis/non-standard grammar often behaves like an expression.
        return bool({"grammar", "phrases"} & focus)
    return True


def learning_action_key_for_contract(item: dict[str, Any]) -> str:
    focus = clean_study_text(
        item.get("learning_action")
        or item.get("phrase_card_focus")
        or item.get("card_focus")
        or item.get("reason")
        or ""
    )
    parts = [
        normalize_candidate_kind(item.get("candidate_kind") or item.get("kind")),
        normalized_phrase_key(
            str(
                item.get("normalized_answer")
                or item.get("answer_core")
                or item.get("exact_span")
                or item.get("phrase")
                or ""
            )
        ),
        re.sub(r"\s+", " ", focus.lower()).strip()[:96],
    ]
    return "::".join(part for part in parts if part)
