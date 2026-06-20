from __future__ import annotations

from typing import Any

from acg.phrases.lexicon import CEFR_ORDER


LANGUAGE_FOCUS_ORDER = ["phrases", "vocabulary", "grammar", "listening"]
LANGUAGE_FOCUS_LABELS = {
    "phrases": "词伙表达",
    "vocabulary": "单词用法",
    "grammar": "语法框架",
    "listening": "听力难点",
}
LANGUAGE_FOCUS_RULES = {
    "phrases": "优先选择可迁移的词伙、搭配、口语块和话语标记；phrase 必须来自原句且不能是整句。",
    "vocabulary": "可以选择原句里的一个核心单词或短搭配，但必须训练真实语境里的词义、搭配或用法，不做脱离原句的词典式生词卡。",
    "grammar": "可以选择原句里的可替换句型、结构或语法框架；重点解释它怎么换场景复用，而不是讲抽象语法术语。",
    "listening": "只在弱读、连读、缩读、停顿切分或听音辨义明显时强化听力点；不要把所有句子都硬做听力卡。",
}
STUDY_DEPTHS = {"standard", "deep"}
SELECTION_STRATEGIES = {"catch_all", "curated", "exhaustive"}
SELECTION_STRATEGY_LABELS = {
    "catch_all": "智能筛选",
    "curated": "智能筛选",
    "exhaustive": "智能筛选",
}


def normalize_collection_levels(value: Any, current_level: str) -> list[str]:
    if not isinstance(value, list):
        value = []
    selected = [str(item).upper() for item in value if str(item).upper() in CEFR_ORDER]
    unique = list(dict.fromkeys(selected))
    if unique:
        return sorted(unique, key=CEFR_ORDER.index)
    cutoff = max(CEFR_ORDER.index(current_level), 0) if current_level in CEFR_ORDER else 2
    lower = max(0, cutoff - 1)
    return CEFR_ORDER[lower : cutoff + 1]


def normalized_level_mode(payload: dict[str, Any]) -> str:
    return "manual" if str(payload.get("level_mode") or "").strip().lower() == "manual" else "auto"


def collection_levels_from_payload(payload: dict[str, Any], current_level: str) -> list[str]:
    if normalized_level_mode(payload) == "auto":
        return list(CEFR_ORDER)
    return normalize_collection_levels(payload.get("collection_levels"), current_level)


def normalized_language_focus(payload: dict[str, Any]) -> list[str]:
    raw = payload.get("language_focus")
    if not isinstance(raw, list):
        return ["phrases", "vocabulary", "listening"]
    selected = [str(item) for item in raw if str(item) in LANGUAGE_FOCUS_ORDER]
    unique = list(dict.fromkeys(selected))
    return unique or ["phrases", "vocabulary", "listening"]


def normalized_document_reading_focus(payload: dict[str, Any]) -> list[str]:
    focus = [item for item in normalized_language_focus(payload) if item in {"phrases", "vocabulary", "grammar"}]
    return focus or ["phrases"]


def language_focus_instruction(payload: dict[str, Any]) -> str:
    focus = normalized_language_focus(payload)
    labels = " / ".join(LANGUAGE_FOCUS_LABELS[item] for item in focus)
    rules = "".join(f"{LANGUAGE_FOCUS_LABELS[item]}：{LANGUAGE_FOCUS_RULES[item]}" for item in focus)
    return (
        f"本次用户选择的学习重点：{labels}。请只围绕这些重点判断和制卡。"
        "如果某个片段只有未选择的学习价值，降低优先级或放入候选库；不要因为类型占比或水平偏好硬过滤合法学习点。"
        f"{rules}"
    )


def normalized_study_depth(payload: dict[str, Any]) -> str:
    value = str(payload.get("study_depth") or "").strip()
    return value if value in STUDY_DEPTHS else "deep"


def normalized_selection_strategy(payload: dict[str, Any]) -> str:
    value = str(payload.get("selection_strategy") or "").strip()
    return "catch_all" if value in SELECTION_STRATEGIES or not value else "catch_all"


def discovery_collection_levels(payload: dict[str, Any], current_level: str) -> list[str]:
    strategy = normalized_selection_strategy(payload)
    if strategy in {"catch_all", "exhaustive"}:
        return list(CEFR_ORDER)
    return collection_levels_from_payload(payload, current_level)


def selection_candidate_multiplier(payload: dict[str, Any]) -> int:
    return 4


def max_learning_points_per_source(payload: dict[str, Any]) -> int:
    return 4


def max_reviewable_cards_per_source(payload: dict[str, Any]) -> int:
    return 6


def normalized_source_expansion_mode(payload: dict[str, Any]) -> str:
    value = str(payload.get("source_expansion_mode") or payload.get("catch_all_expansion") or "auto").strip().lower()
    return value if value in {"auto", "full", "off"} else "auto"


def max_source_expansion_groups(payload: dict[str, Any]) -> int:
    raw = payload.get("max_source_expansion_groups")
    try:
        explicit = int(raw)
    except (TypeError, ValueError):
        explicit = 0
    if explicit > 0:
        return max(1, min(160, explicit))
    return 24


def learning_point_confidence(value_score: Any, default: str = "medium") -> str:
    try:
        score = float(value_score)
    except (TypeError, ValueError):
        score = 0
    if score >= 4:
        return "high"
    if score >= 3:
        return "medium"
    return default if default in {"high", "medium", "low"} else "medium"
