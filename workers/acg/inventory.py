from __future__ import annotations

from typing import Any

from acg.text_cleaning import clean_study_text


LEARNING_POINT_INVENTORY_STATUSES = {"card_generated", "candidate_only", "hidden_duplicate", "hard_blocked"}


def card_quality_status(card: dict[str, Any]) -> str:
    quality = card.get("quality") if isinstance(card.get("quality"), dict) else {}
    return str(quality.get("status") or "").strip()


def inventory_status_for_filtered_item(item: dict[str, Any], reason: str = "") -> str:
    status = str(item.get("phrase_review_status") or "").strip()
    reason_text = f"{reason} {item.get('phrase_reject_reason') or ''} {item.get('validation_issues') or ''}".lower()
    if status == "duplicate" or "duplicate" in reason_text or "重复" in reason_text:
        return "hidden_duplicate"
    hard_signals = [
        "exact_span",
        "answer_core",
        "不在原句",
        "中文",
        "ipa",
        "发音说明",
        "语法解释",
        "幻觉",
        "乱码",
        "bad json",
        "坏 json",
    ]
    if status == "reject" and any(signal in reason_text for signal in hard_signals):
        return "hard_blocked"
    return "candidate_only"


def inventory_status_for_rejected_card(card: dict[str, Any], segment: dict[str, Any]) -> str:
    quality = card.get("quality") if isinstance(card.get("quality"), dict) else {}
    reason = " / ".join(str(issue) for issue in quality.get("issues") or [])
    return inventory_status_for_filtered_item({**segment, **card}, reason)


def inventory_learning_action(item: dict[str, Any], card: dict[str, Any] | None = None) -> str:
    source = card or item
    return clean_study_text(
        source.get("learning_action")
        or item.get("learning_action")
        or source.get("learning_target")
        or source.get("learning_goal")
        or source.get("phrase_card_focus")
        or source.get("why_it_matters")
        or source.get("why")
        or source.get("teacher_note")
        or item.get("phrase_card_focus")
        or "确认这个学习点是否值得做成卡。"
    )


def learning_point_inventory_stats(inventory: list[dict[str, Any]] | None) -> dict[str, int]:
    counts = {
        "candidate_only_learning_point_count": 0,
        "hidden_duplicate_learning_point_count": 0,
        "hard_blocked_learning_point_count": 0,
    }
    for item in inventory or []:
        status = str(item.get("status") or "")
        if status == "candidate_only":
            counts["candidate_only_learning_point_count"] += 1
        elif status == "hidden_duplicate":
            counts["hidden_duplicate_learning_point_count"] += 1
        elif status == "hard_blocked":
            counts["hard_blocked_learning_point_count"] += 1
    return counts


def apply_default_generated_card_selection(segments: list[dict[str, Any]], project: dict[str, Any]) -> list[dict[str, Any]]:
    for segment in segments:
        for card in segment.get("cards", []) or []:
            card["enabled"] = card_quality_status(card) in {"recommended", "needs_review"}
    return segments
