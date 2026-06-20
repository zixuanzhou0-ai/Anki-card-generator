from __future__ import annotations

import re
from typing import Any

from acg.language_text import has_cjk
from acg.learning_actions import normalized_contains_text
from acg.text_cleaning import clean_study_text


VALID_TEMPLATE_IDS = {"immersive_v11", "ciba_tianxia_v1", "immersive", "dictionary", "minimal"}
VALID_CARD_STYLES = {"warm_paper", "minimal_white", "dark_immersive"}
VALID_REVIEW_DENSITIES = {"full", "fast"}
CIBA_CARD_STYLE_LABELS = {
    "warm_paper": "暖色纸感",
    "minimal_white": "极简白卡",
    "dark_immersive": "深色沉浸",
}


def normalize_template_id(template_id: Any = "immersive_v11") -> str:
    value = str(template_id or "").strip()
    return value if value in VALID_TEMPLATE_IDS else "immersive_v11"


def ciba_tianxia_mode(payload: dict[str, Any] | None) -> bool:
    return normalize_template_id((payload or {}).get("template_id")) == "ciba_tianxia_v1"


def normalize_card_style(card_style: Any = "warm_paper") -> str:
    value = str(card_style or "").strip()
    return value if value in VALID_CARD_STYLES else "warm_paper"


def normalize_review_density(review_density: Any = "full") -> str:
    value = str(review_density or "").strip()
    return value if value in VALID_REVIEW_DENSITIES else "full"


def fast_review_density(project: dict[str, Any]) -> bool:
    return normalize_review_density(project.get("review_density")) == "fast"


def fast_review_prompt_instruction(project: dict[str, Any]) -> str:
    if not fast_review_density(project):
        return ""
    return (
        "【快速复读模式：真正减少 token】"
        "用户选择的是快速复读，不是完整复读精学卡。"
        "每张卡只生成最小复习字段：retrieval_prompt、answer_core、phrase、chinese、english/source_evidence、chinese_feel、teacher_note。"
        "teacher_note 最多一句，优先 18-36 个中文字；definition 最多一句，优先 20-40 个中文字。"
        "不要输出长段落，不要把边界、易错、为什么值得学、例句和迁移句都塞进 teacher_note。"
        "definition/context/example/collocations/why/why_it_matters/how_to_use_it/usage_boundary/confusable_note/replacement_examples "
        "这些字段能留空就留空；确实必须写时也只能短句。"
        "同一个 learning_point 只做一张 phrase 主卡；除非用户明确选择听力/填空且该点不可替代，否则不要额外生成 listening 或 cloze。"
        "目标是减少 token、减少审核负担，让背面只留下：答案、当前语境义、原句、一个很短提醒。"
    )


def short_fast_text(value: Any, limit: int) -> str:
    text = clean_study_text(value)
    if not text:
        return ""
    first = re.split(r"[。.!！?？；;]\s*", text, maxsplit=1)[0].strip()
    text = first or text
    return text[: max(0, limit)].rstrip()


def fast_review_card_quality(card: dict[str, Any], segment: dict[str, Any] | None = None) -> dict[str, Any]:
    segment = segment or {}
    issues: list[str] = []
    answer = clean_study_text(card.get("answer_core") or card.get("phrase"))
    english = clean_study_text(card.get("english") or segment.get("text"))
    chinese = clean_study_text(card.get("chinese"))
    definition = clean_study_text(card.get("definition"))
    teacher_note = clean_study_text(card.get("teacher_note"))
    retrieval_prompt = clean_study_text(card.get("retrieval_prompt"))
    if not answer:
        issues.append("缺少核心答案")
    if not english:
        issues.append("缺少原句")
    if answer and english and not normalized_contains_text(english, answer):
        issues.append("核心答案不在原句")
    if not chinese or not has_cjk(chinese):
        issues.append("缺少中文语境义")
    if not (definition or teacher_note):
        issues.append("缺少短释义或老师提醒")
    if not retrieval_prompt:
        issues.append("缺少正面回忆题")
    score = max(0, 88 - 16 * len(issues))
    status = "recommended" if score >= 72 and not issues else "needs_review" if score >= 42 else "reject"
    return {"score": score, "status": status, "issues": issues}


def slim_fast_review_card(card: dict[str, Any], segment: dict[str, Any] | None = None) -> dict[str, Any]:
    slim = dict(card)
    slim["teacher_note"] = short_fast_text(slim.get("teacher_note") or slim.get("how_to_use_it") or slim.get("definition"), 48)
    slim["definition"] = short_fast_text(slim.get("definition") or slim.get("learning_target"), 48)
    slim["chinese_feel"] = short_fast_text(slim.get("chinese_feel") or slim.get("natural_chinese"), 40)
    for key in [
        "collocations",
        "example",
        "why",
        "why_it_matters",
        "how_to_use_it",
        "usage_boundary",
        "confusable_note",
        "replacement_examples",
        "conceptual_action",
        "chinese_learner_trap",
    ]:
        slim[key] = ""
    slim["quality"] = fast_review_card_quality(slim, segment)
    slim["enabled"] = slim["quality"]["status"] == "recommended"
    return slim


def slim_fast_review_segments(segments: list[dict[str, Any]], project: dict[str, Any]) -> list[dict[str, Any]]:
    if not fast_review_density(project):
        return segments
    slimmed: list[dict[str, Any]] = []
    for segment in segments:
        slimmed.append({**segment, "cards": [slim_fast_review_card(card, segment) for card in segment.get("cards", []) or []]})
    return slimmed
