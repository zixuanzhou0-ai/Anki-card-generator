from __future__ import annotations

import re
from typing import Any

from acg.card_quality import (
    has_generic_definition,
    has_generic_teacher_note,
    has_template_noise,
    is_specific_study_text,
    normalized_action_text,
)
from acg.language_text import has_cjk
from acg.text_cleaning import clean_study_text


LEARNING_ACTION_VALUES = {
    "contextual_meaning",
    "expression_recall",
    "listening_discrimination",
    "collocation_boundary",
    "chinese_learner_trap",
    "conceptual_action",
    "grammar_pattern",
}


_FORM_OPINION_PATTERN = re.compile(r"\bform\s+(?:an\s+)?opinions?\b", re.IGNORECASE)
_GIVE_OPINION_PATTERN = re.compile(r"\bgive\s+(?:an\s+)?opinions?\b", re.IGNORECASE)
_FALSE_ERROR_CUES = (
    "别说",
    "不要说",
    "不自然",
    "错误",
    "中式英语",
    "正确是",
    "应改为",
    "instead",
    "incorrect",
    "wrong",
    "unnatural",
    "chinglish",
)
_FORM_GIVE_OPINION_BOUNDARY = (
    "make opinions 不自然；give an opinion / give opinions 表示“表达或提出意见”，"
    "form an opinion / form opinions 强调“形成看法”；后两者都可用，但含义不同。"
)


def _mislabels_give_opinion_as_wrong(value: Any, target: str) -> bool:
    text = clean_study_text(value)
    if not text or not _FORM_OPINION_PATTERN.search(target) or not _GIVE_OPINION_PATTERN.search(text):
        return False
    lowered = text.lower()
    return any(cue in lowered for cue in _FALSE_ERROR_CUES)


def sanitize_known_valid_contrasts(card: dict[str, Any]) -> None:
    """Repair deterministic false-error claims that would teach a valid contrast as bad English."""
    target = clean_study_text(card.get("answer_core") or card.get("phrase") or "")
    if not _FORM_OPINION_PATTERN.search(target):
        return

    repaired = False
    for key in ("chinese_learner_trap", "confusable_note"):
        if _mislabels_give_opinion_as_wrong(card.get(key), target):
            card[key] = _FORM_GIVE_OPINION_BOUNDARY
            repaired = True

    teacher_note = clean_study_text(card.get("teacher_note"))
    if _mislabels_give_opinion_as_wrong(teacher_note, target):
        parts = [part.strip() for part in re.split(r"[；;]+", teacher_note) if part.strip()]
        kept = [part for part in parts if not _mislabels_give_opinion_as_wrong(part, target)]
        kept.append(f"易混表达：{_FORM_GIVE_OPINION_BOUNDARY}")
        card["teacher_note"] = "；".join(dict.fromkeys(kept))
        repaired = True

    if repaired:
        repairs = card.setdefault("content_repair_history", [])
        if isinstance(repairs, list):
            message = "已修复把 give an opinion / give opinions 错判为不自然英语的语义边界。"
            if message not in repairs:
                repairs.append(message)


def normalized_contains_text(haystack: Any, needle: Any) -> bool:
    haystack_marker = re.sub(r"[\s\W_]+", "", clean_study_text(haystack).lower(), flags=re.UNICODE)
    needle_marker = re.sub(r"[\s\W_]+", "", clean_study_text(needle).lower(), flags=re.UNICODE)
    return bool(needle_marker and needle_marker in haystack_marker)


def learning_action_for_card(card: dict[str, Any]) -> str:
    explicit = str(card.get("learning_action") or "").strip()
    if explicit in LEARNING_ACTION_VALUES:
        return explicit
    candidate_kind = str(card.get("candidate_kind") or card.get("kind") or "").strip()
    phrase_type = str(card.get("phrase_type") or "").strip()
    content_kind = str(card.get("content_kind") or "").strip()
    if candidate_kind == "contextual_vocab" or content_kind == "vocabulary" or phrase_type == "vocabulary_usage":
        return "contextual_meaning"
    if candidate_kind == "listening_feature" or content_kind == "listening" or phrase_type == "listening_sentence":
        return "listening_discrimination"
    if candidate_kind == "grammar_pattern" or content_kind == "grammar" or phrase_type == "grammar_pattern":
        return "grammar_pattern"
    if candidate_kind == "pragmatic_risk":
        return "chinese_learner_trap"
    if phrase_type in {"collocation", "idiom"}:
        return "collocation_boundary"
    return "expression_recall"


def normalize_learning_action_fields(card: dict[str, Any]) -> None:
    sanitize_known_valid_contrasts(card)
    learning_target = normalized_action_text(card.get("learning_target"))
    why_it_matters = normalized_action_text(card.get("why_it_matters"))
    how_to_use_it = normalized_action_text(card.get("how_to_use_it"))
    natural_chinese = normalized_action_text(card.get("natural_chinese"))
    replacement_examples = normalized_action_text(card.get("replacement_examples"))
    avoid_reason = normalized_action_text(card.get("avoid_reason"))
    usage_boundary = normalized_action_text(card.get("usage_boundary"))
    confusable_note = normalized_action_text(card.get("confusable_note"))
    conceptual_action = normalized_action_text(card.get("conceptual_action"))
    chinese_learner_trap = normalized_action_text(card.get("chinese_learner_trap"))
    card["learning_action"] = learning_action_for_card(card)

    if not chinese_learner_trap and confusable_note:
        card["chinese_learner_trap"] = confusable_note
        chinese_learner_trap = normalized_action_text(card.get("chinese_learner_trap"))
    if not conceptual_action and is_specific_study_text(card.get("learning_target")):
        card["conceptual_action"] = clean_study_text(card.get("learning_target"))
        conceptual_action = normalized_action_text(card.get("conceptual_action"))

    if (not natural_chinese or has_template_noise(natural_chinese)) and is_specific_study_text(card.get("chinese")):
        card["natural_chinese"] = clean_study_text(card.get("chinese"))
        natural_chinese = normalized_action_text(card.get("natural_chinese"))
    if (not how_to_use_it or has_template_noise(how_to_use_it)) and is_specific_study_text(card.get("definition")):
        card["how_to_use_it"] = clean_study_text(card.get("definition"))
        how_to_use_it = normalized_action_text(card.get("how_to_use_it"))
    if (not why_it_matters or has_template_noise(why_it_matters)) and is_specific_study_text(card.get("why")):
        card["why_it_matters"] = clean_study_text(card.get("why"))
        why_it_matters = normalized_action_text(card.get("why_it_matters"))
    if (not replacement_examples or has_template_noise(replacement_examples)) and is_specific_study_text(card.get("collocations")):
        card["replacement_examples"] = clean_study_text(card.get("collocations"))
        replacement_examples = normalized_action_text(card.get("replacement_examples"))

    if natural_chinese and (not str(card.get("chinese") or "").strip() or not has_cjk(str(card.get("chinese") or ""))):
        card["chinese"] = natural_chinese
    learning_goal = str(card.get("learning_goal") or "").strip()
    if learning_target and (
        not learning_goal
        or "核心价值" in learning_goal
        or "额外能力点" in learning_goal
        or "这张卡训练什么" in learning_goal
        or "围绕这个学习点制卡" in learning_goal
    ):
        card["learning_goal"] = learning_target
    why = str(card.get("why") or "").strip()
    if why_it_matters and (
        not why
        or "本地 fallback" in why
        or "正式导出前" in why
        or "为什么值得学" in why
    ):
        card["why"] = why_it_matters
    context = str(card.get("context") or "").strip()
    if how_to_use_it and (
        not context
        or "本地待审字段" in context
        or "review page" in context.lower()
    ):
        card["context"] = how_to_use_it
    collocations = str(card.get("collocations") or "").strip()
    if replacement_examples and (
        not collocations
        or "natural object" in collocations.lower()
        or "complete sentence" in collocations.lower()
        or collocations.lower().startswith("use ")
    ):
        card["collocations"] = replacement_examples
    if avoid_reason and not str(card.get("phrase_reject_reason") or "").strip():
        card["phrase_reject_reason"] = avoid_reason

    teacher_note = str(card.get("teacher_note") or "").strip()
    if (not teacher_note or has_generic_teacher_note(teacher_note)) and how_to_use_it:
        card["teacher_note"] = how_to_use_it
        teacher_note = str(card.get("teacher_note") or "").strip()
    extra_notes = []
    if usage_boundary and not normalized_contains_text(teacher_note, usage_boundary):
        extra_notes.append(f"使用边界：{usage_boundary}")
    if confusable_note and not normalized_contains_text(teacher_note, confusable_note):
        extra_notes.append(f"易错提醒：{confusable_note}")
    if chinese_learner_trap and not normalized_contains_text(teacher_note, chinese_learner_trap):
        extra_notes.append(f"易混表达：{chinese_learner_trap}")
    if extra_notes:
        merged_note = "；".join(extra_notes)
        if teacher_note and merged_note not in teacher_note:
            card["teacher_note"] = f"{teacher_note}；{merged_note}"
        elif not teacher_note:
            card["teacher_note"] = merged_note
    if has_generic_definition(str(card.get("definition", ""))) and learning_target:
        card["definition"] = learning_target

    comparable_teacher_note = re.sub(r"\s+", " ", str(card.get("teacher_note") or "").strip())
    for key, replacement in [
        ("why", learning_target or how_to_use_it),
        ("context", learning_target or why_it_matters),
        ("chinese_feel", how_to_use_it or why_it_matters),
    ]:
        comparable_value = re.sub(r"\s+", " ", str(card.get(key, "") or "").strip())
        if comparable_teacher_note and comparable_value and comparable_teacher_note == comparable_value and replacement:
            card["teacher_note"] = replacement
            break
