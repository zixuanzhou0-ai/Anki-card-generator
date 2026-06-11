from __future__ import annotations

import re
from typing import Any


LEVEL_ORDER = ["A1", "A2", "B1", "B2", "C1", "C2"]

KNOWN_LEVELS: dict[str, str] = {
    "right now": "A1",
    "not really": "A2",
    "kind of": "A2",
    "sort of": "A2",
    "by the way": "A2",
    "make sure": "A2",
    "in the mood for": "B1",
    "it turns out": "B1",
    "figure out": "B1",
    "come up with": "B1",
    "run into": "B1",
    "run the register": "B1",
    "register": "B1",
    "get away with": "B2",
    "messing with us": "B2",
    "it's not that": "B2",
    "what i don't understand is": "B2",
    "with all due respect": "C1",
}


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def estimate_learning_point_level(point: dict[str, Any], source_segment: dict[str, Any], payload: dict[str, Any] | None = None) -> tuple[str, str]:
    answer = _norm(point.get("normalized_answer") or point.get("answer_core") or point.get("exact_span"))
    kind = str(point.get("candidate_kind") or "")
    for key, level in KNOWN_LEVELS.items():
        if key in answer:
            return level, f"{level}：该学习点是常见可迁移用法，按整体表达难度分级。"
    words = re.findall(r"[A-Za-z']+", answer)
    word_count = len(words)
    if kind == "listening_feature":
        return "B1", "B1：听力点依赖弱读/连读识别，比单词本身略高。"
    if kind == "grammar_pattern":
        return ("B2", "B2：这是可迁移句型框架，需要掌握句子功能。") if word_count >= 5 else ("B1", "B1：常见语法框架。")
    if kind == "pragmatic_risk":
        return "C1", "C1：重点在语气、礼貌和使用边界。"
    if kind == "contextual_vocab":
        return "B1", "B1：不是孤立词义，而是原句里的语境用法。"
    if word_count <= 1:
        return "A2", "A2：单个高频词或短语，需要结合语境学习。"
    if word_count <= 3:
        return "B1", "B1：高频口语词伙，可迁移到日常表达。"
    if word_count <= 7:
        return "B2", "B2：多词表达，包含更自然的口语组织方式。"
    return "C1", "C1：较长表达，学习重点在语篇功能和细微语气。"

