from __future__ import annotations

from typing import Any

from acg import legacy_worker


def card_counts_as_generated(card: Any) -> bool:
    return (
        isinstance(card, dict)
        and bool(card.get("enabled"))
        and legacy_worker.card_quality_status(card) != "reject"
        and not legacy_worker.card_has_export_blocking_content(card)
    )


def generated_card_count_from_segments(segments: list[dict[str, Any]]) -> int:
    return sum(
        1
        for segment in segments
        if isinstance(segment, dict)
        for card in segment.get("cards") or []
        if card_counts_as_generated(card)
    )


def generated_learning_point_ids_from_segment(segment: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    segment_id = str(segment.get("learning_point_id") or "")
    for card in segment.get("cards") or []:
        if not card_counts_as_generated(card):
            continue
        card_id = str(card.get("learning_point_id") or "")
        if card_id:
            ids.add(card_id)
        elif segment_id:
            ids.add(segment_id)
    return ids


def generated_learning_point_ids_from_project(project: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for segment in project.get("segments") or []:
        if not isinstance(segment, dict):
            continue
        ids.update(generated_learning_point_ids_from_segment(segment))
    return ids


def segment_has_generated_learning_point_card(segment: dict[str, Any]) -> bool:
    return bool(generated_learning_point_ids_from_segment(segment))


def card_generation_diagnostic_items(
    selected_points: list[dict[str, Any]],
    eligible_segments: list[dict[str, Any]],
    pre_filter_segments: list[dict[str, Any]],
    output_segments: list[dict[str, Any]],
    model_missing_segment_ids: set[str],
) -> list[dict[str, Any]]:
    point_by_id = {str(point.get("id") or ""): point for point in selected_points}
    segment_by_point_id = {str(segment.get("learning_point_id") or ""): segment for segment in eligible_segments}
    generated_ids: set[str] = set()
    for segment in output_segments:
        if isinstance(segment, dict):
            generated_ids.update(generated_learning_point_ids_from_segment(segment))
    pre_filter_by_point_id = {str(segment.get("learning_point_id") or ""): segment for segment in pre_filter_segments}
    items: list[dict[str, Any]] = []
    for point in selected_points:
        point_id = str(point.get("id") or "")
        if not point_id or point_id in generated_ids:
            continue
        segment = segment_by_point_id.get(point_id)
        if not segment:
            items.append(
                {
                    "learning_point_id": point_id,
                    "answer_core": point.get("answer_core") or point.get("exact_span") or "",
                    "status": "skipped",
                    "reason": "学习点状态不可制卡，已跳过。",
                }
            )
            continue
        segment_id = str(segment.get("id") or "")
        if segment_id in model_missing_segment_ids:
            reason = "AI 未覆盖该学习点，且保底生成未完成。"
            status = "hard_failed"
        else:
            status = "filtered"
            reason = "生成后未通过硬性导出检查。"
            pre_segment = pre_filter_by_point_id.get(point_id) or {}
            issues: list[str] = []
            for card in pre_segment.get("cards", []) or []:
                quality = card.get("quality") if isinstance(card.get("quality"), dict) else {}
                issues.extend(str(issue) for issue in quality.get("issues") or [] if issue)
            if issues:
                reason = "；".join(list(dict.fromkeys(issues))[:3])
        items.append(
            {
                "learning_point_id": point_id,
                "answer_core": point_by_id.get(point_id, {}).get("answer_core")
                or point_by_id.get(point_id, {}).get("exact_span")
                or "",
                "status": status,
                "reason": reason,
            }
        )
    return items


def card_generation_diagnostic_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"skipped": 0, "model_missing": 0, "hard_failed": 0, "filtered": 0}
    for item in items:
        status = str(item.get("status") or "")
        if status in counts:
            counts[status] += 1
    return counts
