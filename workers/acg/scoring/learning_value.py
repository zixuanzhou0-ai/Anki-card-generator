from __future__ import annotations

import re
from typing import Any

from acg.classification.leveling import LEVEL_ORDER



LOW_TRANSFER_ANSWERS = {
    "talk about",
    "talking about",
    "do something",
    "good thing",
    "things like that",
    "something like that",
    "this thing",
    "that thing",
    "very good",
    "really good",
}

VAGUE_LEARNING_ACTIONS = {
    "学习这个表达",
    "训练这个表达",
    "学习这个词",
    "学习词汇",
    "理解这句话",
    "学习这个句子",
}


TRANSFER_SIGNAL_TERMS = [
    "搭配",
    "语境",
    "语气",
    "边界",
    "连读",
    "弱读",
    "缩读",
    "框架",
    "迁移",
    "自然",
    "口语",
    "用法",
    "辨",
    "复用",
    "委婉",
]

WEAK_NOUN_CHUNK_ENDINGS = {
    "group",
    "groups",
    "people",
    "person",
    "thing",
    "things",
    "stuff",
    "topic",
    "topics",
    "example",
    "examples",
    "class",
    "classes",
    "lesson",
    "lessons",
    "boy",
    "boys",
    "girl",
    "girls",
    "student",
    "students",
}

SOURCE_REVIEW_FLAGS = {
    "possible_bad_join",
    "too_long",
    "rolling_caption_uncertain",
    "repeated_adjacent_words",
}

ASR_GRAMMAR_SUSPECT_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bhave\s+break\b",
        r"\btake\s+break\b",
        r"\bgo\s+school\b",
        r"\bgo\s+work\b",
    )
]


def _normalized_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _source_text_for_point(point: dict[str, Any]) -> str:
    return _normalized_text(
        " ".join(
            str(point.get(key) or "")
            for key in ("source_sentence", "source_evidence", "sentence", "text", "english", "context")
        )
    )


def _answer_locatable(point: dict[str, Any], answer: str, words: list[str]) -> bool:
    source_text = _source_text_for_point(point)
    if not source_text:
        return True
    normalized_answer = _normalized_text(answer)
    if not normalized_answer:
        return False
    if normalized_answer in source_text:
        return True
    if len(words) == 1:
        return bool(re.search(rf"\b{re.escape(words[0].lower())}\b", source_text))
    return False


def _source_quality_flags(point: dict[str, Any]) -> set[str]:
    raw_flags = point.get("source_sentence_quality_flags") or point.get("quality_flags") or []
    if isinstance(raw_flags, str):
        raw_flags = [raw_flags]
    return {str(flag) for flag in raw_flags if str(flag) and str(flag) != "clean"}


def _has_transfer_signal(action_text: str) -> bool:
    return any(term in action_text for term in TRANSFER_SIGNAL_TERMS)


def _looks_like_weak_noun_chunk(answer: str, words: list[str], action_text: str) -> bool:
    if not 2 <= len(words) <= 4:
        return False
    lowered = [word.lower().strip("'") for word in words]
    if not lowered or lowered[-1] not in WEAK_NOUN_CHUNK_ENDINGS:
        return False
    if any(word in {"of", "for", "with", "to", "into", "out"} for word in lowered):
        return False
    if re.search(r"\b(?:get|make|take|have|go|come|run|turn|look|work|figure|end)\b", answer, re.IGNORECASE):
        return False
    return True


def _looks_like_asr_grammar_suspect(answer: str, source_text: str) -> bool:
    text = " ".join(part for part in [answer, source_text] if part)
    return any(pattern.search(text) for pattern in ASR_GRAMMAR_SUSPECT_PATTERNS)


def _strong_expression_from_noisy_source(point: dict[str, Any], words: list[str], action_text: str) -> bool:
    phrase_type = str(point.get("phrase_type") or "")
    if phrase_type not in {
        "spoken_phrase",
        "sentence_frame",
        "collocation",
        "discourse_marker",
        "idiom",
        "grammar_pattern",
        "phrasal_verb",
    }:
        return False
    return 2 <= len(words) <= 6 and _has_transfer_signal(action_text)


def _recommendation_flags(point: dict[str, Any], answer: str, words: list[str]) -> set[str]:
    flags: set[str] = set()
    normalized_answer = _normalized_text(answer)
    learning_action = str(point.get("learning_action") or "").strip()
    action_text = _normalized_text(
        " ".join(
            str(point.get(key) or "")
            for key in ("learning_action", "reason", "usage_boundary", "confusable_note", "teacher_note")
        )
    )
    source_text = _source_text_for_point(point)
    if not _answer_locatable(point, answer, words):
        flags.add("answer_not_locatable")
    if normalized_answer in LOW_TRANSFER_ANSWERS:
        flags.add("low_transfer_answer")
    if learning_action in VAGUE_LEARNING_ACTIONS or not learning_action:
        flags.add("vague_learning_action")
    if len(words) > 8:
        flags.add("answer_too_long")
    if re.search(r"[\u4e00-\u9fff/]{2,}", answer):
        flags.add("answer_not_clean_target")
    if len(words) <= 2 and not _has_transfer_signal(action_text):
        flags.add("weak_transfer_signal")
    if _looks_like_weak_noun_chunk(normalized_answer, words, action_text):
        flags.add("weak_noun_chunk")
    if _looks_like_asr_grammar_suspect(normalized_answer, source_text):
        flags.add("asr_grammar_suspect")
    if _source_quality_flags(point) & SOURCE_REVIEW_FLAGS and not _strong_expression_from_noisy_source(
        point, words, action_text
    ):
        flags.add("source_sentence_needs_review")
    return flags


def _level_index(level: Any) -> int:
    try:
        return LEVEL_ORDER.index(str(level or "B1"))
    except ValueError:
        return LEVEL_ORDER.index("B1")


def _ciba_tianxia_mode(payload: dict[str, Any] | None) -> bool:
    return str((payload or {}).get("template_id") or "").strip() == "ciba_tianxia_v1"


def _ciba_tianxia_value_delta(point: dict[str, Any], answer: str, words: list[str]) -> float:
    kind = str(point.get("candidate_kind") or "")
    phrase_type = str(point.get("phrase_type") or "")
    learning_action = str(point.get("learning_action") or "")
    reason = str(point.get("reason") or "")
    boundary = str(point.get("usage_boundary") or "")
    confusable = str(point.get("confusable_note") or "")
    answer_lower = answer.lower().strip()
    action_text = " ".join([learning_action, reason, boundary, confusable]).lower()
    delta = 0.0

    if 2 <= len(words) <= 6 and phrase_type in {
        "spoken_phrase",
        "sentence_frame",
        "collocation",
        "discourse_marker",
        "idiom",
        "grammar_pattern",
        "phrasal_verb",
    }:
        delta += 0.35
    if kind == "contextual_vocab" and len(words) == 1 and ("语境" in learning_action or "搭配" in learning_action):
        delta += 0.25
    if kind == "listening_feature" and any(term in action_text for term in ["weak", "link", "连读", "弱读", "缩读", "吞音", "重音"]):
        delta += 0.3
    if kind == "pragmatic_risk" and any(term in action_text for term in ["语气", "冒犯", "正式", "边界", "风险"]):
        delta += 0.3
    if any(term in action_text for term in ["词块", "搭配边界", "语境义", "概念视角", "为说而思考", "迁移"]):
        delta += 0.25
    if boundary.strip() or confusable.strip():
        delta += 0.15

    if len(words) > 8:
        delta -= 0.35
    if answer_lower in {"talk about", "do something", "good thing", "things like that", "something like that"}:
        delta -= 0.45
    if re.search(r"[\u4e00-\u9fff/]{2,}", answer):
        delta -= 0.75
    if learning_action.strip() in {"学习这个表达", "训练这个表达", "学习这个词", "学习词汇"}:
        delta -= 0.35
    return delta


def score_learning_point(point: dict[str, Any], user_level: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    kind = str(point.get("candidate_kind") or "")
    answer = str(point.get("answer_core") or point.get("exact_span") or "")
    words = re.findall(r"[A-Za-z']+", answer)
    value = float(point.get("value_score") or 3.0)
    flags = _recommendation_flags(point, answer, words)

    if kind == "expression":
        value += 0.25
    elif kind == "contextual_vocab":
        value += 0.15
    elif kind == "grammar_pattern":
        value += 0.2
    elif kind == "listening_feature":
        value += 0.05
    elif kind == "pragmatic_risk":
        value += 0.1

    if 2 <= len(words) <= 6:
        value += 0.2
    if len(words) > 10:
        value -= 0.35
    if "answer_not_locatable" in flags:
        value -= 0.75
    if "low_transfer_answer" in flags:
        value -= 0.55
    if "vague_learning_action" in flags:
        value -= 0.45
    if "weak_transfer_signal" in flags:
        value -= 0.2
    if "weak_noun_chunk" in flags:
        value -= 0.65
    if "asr_grammar_suspect" in flags:
        value -= 0.9
    if "source_sentence_needs_review" in flags:
        value -= 0.35
    if not str(point.get("learning_action") or "").strip():
        value -= 0.6
    if point.get("validation_status") == "repaired":
        value -= 0.15
    if _ciba_tianxia_mode(payload):
        value += _ciba_tianxia_value_delta(point, answer, words)

    level = str(point.get("level") or point.get("estimated_level") or user_level or "B1")
    distance = abs(_level_index(level) - _level_index(user_level or "B1"))
    level_fit = max(1.0, 5.0 - distance * 1.1)
    final_score = round(max(1.0, min(10.0, value + level_fit * 0.75)), 2)
    value_score = round(max(1.0, min(5.0, value)), 2)
    return {
        "value_score": value_score,
        "level_fit_score": round(level_fit, 2),
        "final_score": final_score,
        "reason": point.get("reason") or "原句里有明确学习动作，可按类型和难度筛选。",
        "recommendation_flags": sorted(flags),
    }


def assign_learning_point_status(point: dict[str, Any], user_level: str, payload: dict[str, Any] | None = None) -> tuple[str, str]:
    if point.get("validation_status") == "hard_blocked":
        return "hard_blocked", str(point.get("status_reason") or "学习点未通过硬校验。")
    value = float(point.get("value_score") or 0)
    kind = str(point.get("candidate_kind") or "")
    answer = str(point.get("answer_core") or point.get("exact_span") or "")
    words = re.findall(r"[A-Za-z']+", answer)
    flags = set(point.get("recommendation_flags") or _recommendation_flags(point, answer, words))
    level = str(point.get("level") or point.get("estimated_level") or user_level or "B1")
    distance = abs(_level_index(level) - _level_index(user_level or "B1"))
    below_distance = _level_index(user_level or "B1") - _level_index(level)
    if below_distance >= 2:
        if _ciba_tianxia_mode(payload) and float(point.get("value_score") or 0) >= 3.6:
            return "candidate_only", "合法但低于当前水平；词霸天下模式保留真实语言动作给用户自行决定。"
        return "candidate_only", "合法但明显低于当前水平，作为补基础候选保留。"
    if flags & {
        "answer_not_locatable",
        "low_transfer_answer",
        "answer_too_long",
        "answer_not_clean_target",
        "weak_noun_chunk",
        "asr_grammar_suspect",
    }:
        return "candidate_only", "合法但不够适合作为默认推荐：目标泛、过长或无法在原句中清楚定位。"
    if "source_sentence_needs_review" in flags and value < 4.6:
        return "candidate_only", "字幕边界或拼接质量需要复查，先保留为候选。"
    if "vague_learning_action" in flags and value < 4.3:
        return "candidate_only", "学习动作还不够具体，先作为候选保留。"
    if value >= 4.0 and distance <= 2 and kind != "listening_feature":
        return "recommended", "高价值、合法、不重复，默认推荐生成卡。"
    if value >= 3.4 and distance <= 2:
        return "recommended", "合法且有明确学习动作，默认推荐。"
    return "candidate_only", "合法但优先级较低，保留给用户自行决定。"
