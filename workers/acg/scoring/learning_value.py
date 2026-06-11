from __future__ import annotations

import re
from typing import Any

from acg.classification.leveling import LEVEL_ORDER


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
    }


def assign_learning_point_status(point: dict[str, Any], user_level: str, payload: dict[str, Any] | None = None) -> tuple[str, str]:
    if point.get("validation_status") == "hard_blocked":
        return "hard_blocked", str(point.get("status_reason") or "学习点未通过硬校验。")
    value = float(point.get("value_score") or 0)
    kind = str(point.get("candidate_kind") or "")
    level = str(point.get("level") or point.get("estimated_level") or user_level or "B1")
    distance = abs(_level_index(level) - _level_index(user_level or "B1"))
    below_distance = _level_index(user_level or "B1") - _level_index(level)
    if below_distance >= 2:
        if _ciba_tianxia_mode(payload) and float(point.get("value_score") or 0) >= 3.6:
            return "candidate_only", "合法但低于当前水平；词霸天下模式保留真实语言动作给用户自行决定。"
        return "candidate_only", "合法但明显低于当前水平，作为补基础候选保留。"
    if value >= 4.0 and distance <= 2 and kind != "listening_feature":
        return "recommended", "高价值、合法、不重复，默认推荐生成卡。"
    if value >= 3.4 and distance <= 2:
        return "recommended", "合法且有明确学习动作，默认推荐。"
    return "candidate_only", "合法但优先级较低，保留给用户自行决定。"
