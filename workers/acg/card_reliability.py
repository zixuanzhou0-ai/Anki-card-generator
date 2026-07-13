from __future__ import annotations

import time
from typing import Any

from acg import legacy_worker
from acg.card_generation_diagnostics import card_counts_as_generated

RELIABILITY_SCHEMA_VERSION = 1
VERIFICATION_PROFILE = "structural_v1"

FALLBACK_CARD_REQUIRES_REVIEW = "FALLBACK_CARD_REQUIRES_REVIEW"
MODEL_RESULT_MISSING = "MODEL_RESULT_MISSING"
CARD_CONTENT_BLOCKED = "CARD_CONTENT_BLOCKED"
CARD_QUALITY_REVIEW_REQUIRED = "CARD_QUALITY_REVIEW_REQUIRED"
SELECTED_POINT_NOT_AVAILABLE = "SELECTED_POINT_NOT_AVAILABLE"
CARD_GENERATION_MISSING = "CARD_GENERATION_MISSING"
SELECTED_POINT_ACCOUNTING_INCOMPLETE = "SELECTED_POINT_ACCOUNTING_INCOMPLETE"
SOURCE_EVIDENCE_UNRELIABLE = "SOURCE_EVIDENCE_UNRELIABLE"


def _source_evidence_unreliable(card: dict[str, Any]) -> bool:
    english = str(card.get("english") or "").strip()
    return (
        str(card.get("source_sentence_quality_status") or "").strip() == "needs_review"
        or bool(english and legacy_worker.ends_like_fragment(english))
    )


def _unique(values: list[Any]) -> list[str]:
    return list(dict.fromkeys(str(value or "").strip() for value in values if str(value or "").strip()))


def _card_point_id(segment: dict[str, Any], card: dict[str, Any]) -> str:
    return str(card.get("learning_point_id") or segment.get("learning_point_id") or "").strip()


def _cards_by_point(segments: list[dict[str, Any]]) -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
    result: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        for card in segment.get("cards") or []:
            if not isinstance(card, dict):
                continue
            point_id = _card_point_id(segment, card)
            if point_id and point_id not in result:
                result[point_id] = (segment, card)
    return result


def selected_point_outcomes(
    selected_points: list[dict[str, Any]],
    review_segments: list[dict[str, Any]],
    exportable_segments: list[dict[str, Any]],
    *,
    model_missing_segment_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    review_by_point = _cards_by_point(review_segments)
    exportable_by_point = {
        point_id: pair
        for point_id, pair in _cards_by_point(exportable_segments).items()
        if card_counts_as_generated(pair[1])
    }
    eligible_point_ids = {
        str(segment.get("learning_point_id") or "").strip()
        for segment in review_segments
        if isinstance(segment, dict)
    }
    model_missing_segment_ids = model_missing_segment_ids or set()
    outcomes: list[dict[str, Any]] = []

    for point in selected_points:
        point_id = str(point.get("id") or "").strip()
        if point_id in exportable_by_point:
            _segment, card = exportable_by_point[point_id]
            outcomes.append(
                {
                    "learning_point_id": point_id,
                    "status": "verified",
                    "card_id": str(card.get("id") or ""),
                    "blocker_codes": [],
                    "reason": "卡片已通过当前结构、来源与导出硬门禁。",
                }
            )
            continue

        review_pair = review_by_point.get(point_id)
        if review_pair:
            segment, card = review_pair
            blockers: list[str] = []
            generation_source = str(card.get("generation_source") or "")
            if generation_source in {"fallback_from_selected_learning_point", "basic_from_selected_learning_point"}:
                blockers.append(FALLBACK_CARD_REQUIRES_REVIEW)
            if str(segment.get("id") or "") in model_missing_segment_ids:
                blockers.append(MODEL_RESULT_MISSING)
            if _source_evidence_unreliable(card):
                blockers.append(SOURCE_EVIDENCE_UNRELIABLE)
            if legacy_worker.card_has_export_blocking_content(card):
                blockers.append(CARD_CONTENT_BLOCKED)
            quality = card.get("quality") if isinstance(card.get("quality"), dict) else {}
            if str(quality.get("status") or "") != "recommended":
                blockers.append(CARD_QUALITY_REVIEW_REQUIRED)
            outcomes.append(
                {
                    "learning_point_id": point_id,
                    "status": "needs_review",
                    "card_id": str(card.get("id") or ""),
                    "blocker_codes": _unique(blockers or [CARD_QUALITY_REVIEW_REQUIRED]),
                    "reason": "卡片草稿已保留，但未通过可靠性门禁，不能自动导出。",
                }
            )
            continue

        blockers = [
            SELECTED_POINT_NOT_AVAILABLE if point_id not in eligible_point_ids else CARD_GENERATION_MISSING
        ]
        outcomes.append(
            {
                "learning_point_id": point_id,
                "status": "hard_failed",
                "blocker_codes": blockers,
                "reason": "选中的学习点没有生成可复核卡片。",
            }
        )

    return outcomes


def build_reliability_manifest(
    selected_points: list[dict[str, Any]],
    review_segments: list[dict[str, Any]],
    exportable_segments: list[dict[str, Any]],
    *,
    model_missing_segment_ids: set[str] | None = None,
    source_fingerprint: str = "",
    model_provider: str = "",
    model_name: str = "",
) -> dict[str, Any]:
    outcomes = selected_point_outcomes(
        selected_points,
        review_segments,
        exportable_segments,
        model_missing_segment_ids=model_missing_segment_ids,
    )
    selected_ids = [str(point.get("id") or "").strip() for point in selected_points]
    outcome_ids = [str(outcome.get("learning_point_id") or "").strip() for outcome in outcomes]
    accounting_complete = (
        len(outcomes) == len(selected_points)
        and all(selected_ids)
        and selected_ids == outcome_ids
        and len(set(outcome_ids)) == len(outcome_ids)
    )
    verified_count = sum(1 for outcome in outcomes if outcome["status"] == "verified")
    needs_review_count = sum(1 for outcome in outcomes if outcome["status"] == "needs_review")
    hard_failed_count = sum(1 for outcome in outcomes if outcome["status"] == "hard_failed")
    blocker_codes = _unique(
        [
            *(
                code
                for outcome in outcomes
                for code in outcome.get("blocker_codes") or []
            ),
            *([] if accounting_complete else [SELECTED_POINT_ACCOUNTING_INCOMPLETE]),
        ]
    )
    decision = "pass" if accounting_complete and needs_review_count == 0 and hard_failed_count == 0 else "block"
    return {
        "schema_version": RELIABILITY_SCHEMA_VERSION,
        "verification_profile": VERIFICATION_PROFILE,
        "decision": decision,
        "accounting_complete": accounting_complete,
        "selected_point_count": len(selected_points),
        "verified_count": verified_count,
        "needs_review_count": needs_review_count,
        "hard_failed_count": hard_failed_count,
        "selected_point_outcomes": outcomes,
        "blocker_codes": blocker_codes,
        "source_fingerprint": source_fingerprint,
        "model_provider": model_provider,
        "model_name": model_name,
        "created_at": int(time.time() * 1000),
    }


def apply_outcome_verification_status(
    segments: list[dict[str, Any]],
    outcomes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    status_by_point = {
        str(outcome.get("learning_point_id") or ""): str(outcome.get("status") or "")
        for outcome in outcomes
    }
    updated: list[dict[str, Any]] = []
    for segment in segments:
        point_id = str(segment.get("learning_point_id") or "")
        cards: list[dict[str, Any]] = []
        for card in segment.get("cards") or []:
            if not isinstance(card, dict):
                continue
            card_point_id = str(card.get("learning_point_id") or point_id)
            outcome_status = status_by_point.get(card_point_id)
            verification_status = "verified" if outcome_status == "verified" else "needs_review"
            cards.append({**card, "verification_status": verification_status})
        updated.append({**segment, "cards": cards})
    return updated


def export_reliability_blockers(project: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    manifest = project.get("reliability_manifest")
    if isinstance(manifest, dict):
        outcomes = [
            outcome
            for outcome in manifest.get("selected_point_outcomes") or []
            if isinstance(outcome, dict)
        ]
        selected_count = int(manifest.get("selected_point_count") or 0)
        outcome_ids = [str(outcome.get("learning_point_id") or "").strip() for outcome in outcomes]
        counts_match = (
            len(outcomes) == selected_count
            and len(set(outcome_ids)) == selected_count
            and all(outcome_ids)
        )
        if not bool(manifest.get("accounting_complete")) or not counts_match:
            blockers.append(SELECTED_POINT_ACCOUNTING_INCOMPLETE)
        if str(manifest.get("decision") or "") != "pass":
            blockers.append("RELIABILITY_GATE_NOT_PASSED")
        if int(manifest.get("needs_review_count") or 0) > 0:
            blockers.append(CARD_QUALITY_REVIEW_REQUIRED)
        if int(manifest.get("hard_failed_count") or 0) > 0:
            blockers.append(CARD_GENERATION_MISSING)
        blockers.extend(manifest.get("blocker_codes") or [])

    for segment in project.get("segments") or []:
        if not isinstance(segment, dict):
            continue
        for card in segment.get("cards") or []:
            if not isinstance(card, dict) or not bool(card.get("enabled", True)):
                continue
            generation_source = str(card.get("generation_source") or "")
            if generation_source in {"fallback_from_selected_learning_point", "basic_from_selected_learning_point"}:
                blockers.append(FALLBACK_CARD_REQUIRES_REVIEW)
            verification_status = str(card.get("verification_status") or "")
            if verification_status and verification_status != "verified":
                blockers.append("CARD_VERIFICATION_NOT_PASSED")
            if _source_evidence_unreliable(card):
                blockers.append(SOURCE_EVIDENCE_UNRELIABLE)
            if legacy_worker.card_has_export_blocking_content(card):
                blockers.append(CARD_CONTENT_BLOCKED)

    return _unique(blockers)


__all__ = [
    "apply_outcome_verification_status",
    "build_reliability_manifest",
    "export_reliability_blockers",
    "selected_point_outcomes",
]
