from __future__ import annotations

import json
import time
import re
from pathlib import Path
from typing import Any

from acg import legacy_worker
from acg.protocol import emit_progress, fail

CARD_GENERATION_PROMPT_VERSION = 2


def _card_type_for_point(point: dict[str, Any], requested: list[str]) -> str:
    if str(point.get("candidate_kind") or "") == "listening_feature" and "listening" in requested:
        return "listening"
    if str(point.get("candidate_kind") or "") == "grammar_pattern" and "cloze" in requested:
        return "cloze"
    return "phrase" if "phrase" in requested else (requested[0] if requested else "phrase")


def _point_selection_score(point: dict[str, Any]) -> float:
    try:
        base = float(point.get("final_score") or point.get("ai_value_score") or point.get("value_score") or 0)
    except (TypeError, ValueError):
        base = 0.0
    candidate_kind = str(point.get("candidate_kind") or "")
    if candidate_kind == "expression":
        base += 0.08
    elif candidate_kind == "contextual_vocab":
        base += 0.04
    return base


def _default_selected_learning_points(points: list[dict[str, Any]], payload: dict[str, Any]) -> list[dict[str, Any]]:
    recommended = [point for point in points if str(point.get("status") or "") == "recommended"]
    if legacy_worker.normalize_review_density(payload.get("review_density")) != "fast":
        return recommended
    best_by_source: dict[str, dict[str, Any]] = {}
    for point in recommended:
        source_id = str(point.get("source_segment_id") or point.get("source_sentence") or point.get("id") or "")
        current = best_by_source.get(source_id)
        if current is None or _point_selection_score(point) > _point_selection_score(current):
            best_by_source[source_id] = point
    return list(best_by_source.values())


def _cloze(sentence: str, exact_span: str) -> str:
    if exact_span and legacy_worker.phrase_in_text(sentence, exact_span):
        return re.sub(re.escape(exact_span), f"{{{{c1::{exact_span}}}}}", sentence, count=1, flags=re.IGNORECASE)
    return sentence


def _default_card(point: dict[str, Any], card_type: str, index: int) -> dict[str, Any]:
    sentence = str(point.get("source_sentence") or "")
    answer = str(point.get("answer_core") or point.get("exact_span") or "")
    level = str(point.get("level") or point.get("estimated_level") or "B1")
    reason = str(point.get("reason") or point.get("status_reason") or "原句中有明确学习价值。")
    return {
        "id": f"card_{index:04d}",
        "type": card_type,
        "type_label": legacy_worker.CARD_TYPE_LABELS.get(card_type, "表达卡"),
        "enabled": True,
        "learning_point_id": point.get("id"),
        "candidate_kind": point.get("candidate_kind"),
        "phrase_type": point.get("phrase_type"),
        "exact_span": point.get("exact_span"),
        "answer_core": answer,
        "normalized_answer": point.get("normalized_answer") or answer,
        "learning_action": point.get("learning_action"),
        "learning_action_key": point.get("learning_action_key"),
        "confidence": point.get("confidence"),
        "validation_status": point.get("validation_status"),
        "repair_history": point.get("repair_history") or [],
        "english": sentence,
        "chinese": "",
        "phrase": answer,
        "definition": reason,
        "collocations": "",
        "context": sentence,
        "example": "",
        "chinese_feel": "",
        "why": reason,
        "difficulty": level,
        "estimated_level": level,
        "difficulty_reason": point.get("level_reason") or "",
        "teacher_note": point.get("learning_action") or reason,
        "cloze": _cloze(sentence, str(point.get("exact_span") or answer)),
        "quality": {"score": int(round(float(point.get("value_score") or 4))), "status": "recommended", "issues": []},
    }


def _card_generation_cache_path(payload: dict[str, Any], segments: list[dict[str, Any]], requested_card_types: list[str]) -> tuple[Path, str]:
    api = payload.get("api_config") or {}
    cache_key = legacy_worker.stable_cache_key(
        {
            "version": CARD_GENERATION_PROMPT_VERSION,
            "kind": "selected_learning_point_card_generation",
            "provider": legacy_worker.provider_name(api),
            "base_url": str(api.get("base_url") or "").strip().rstrip("/"),
            "model": str(api.get("model") or "").strip(),
            "language": legacy_worker.normalize_learning_language(payload.get("language", "en")),
            "level_mode": legacy_worker.normalized_level_mode(payload),
            "level": str(payload.get("level") or "B1"),
            "template_id": str(payload.get("template_id") or "immersive_v11"),
            "review_density": legacy_worker.normalize_review_density(payload.get("review_density")),
            "card_types": requested_card_types,
            "prompt_version": CARD_GENERATION_PROMPT_VERSION,
            "learning_points": [
                {
                    "id": str(segment.get("learning_point_id") or ""),
                    "source_segment_id": str(segment.get("source_segment_id") or ""),
                    "source_sentence": str(segment.get("text") or ""),
                    "exact_span": str(segment.get("exact_span") or ""),
                    "answer_core": str(segment.get("answer_core") or ""),
                    "candidate_kind": str(segment.get("candidate_kind") or ""),
                    "phrase_type": str(segment.get("phrase_type") or ""),
                    "learning_action_key": str(segment.get("learning_action_key") or ""),
                    "learning_action": str(segment.get("learning_action") or ""),
                }
                for segment in segments
            ],
        }
    )
    return legacy_worker.persistent_cache_root() / "card_generation" / f"{cache_key}.json", cache_key


def _load_card_generation_cache(cache_path: Path) -> dict[str, Any] | None:
    if not cache_path.exists() or cache_path.stat().st_size <= 0:
        return None
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    payload = cached.get("payload") if isinstance(cached, dict) else None
    if isinstance(payload, dict) and payload.get("segments"):
        return payload
    return None


def _store_card_generation_cache(cache_path: Path, cache_key: str, ai_payload: dict[str, Any]) -> None:
    if ai_payload.get("error") or not ai_payload.get("segments"):
        return
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = cache_path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "cache_key": cache_key,
                    "created_at": int(time.time() * 1000),
                    "payload": ai_payload,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        temp_path.replace(cache_path)
    except OSError:
        return


def _card_generation_diagnostic_items(
    selected_points: list[dict[str, Any]],
    eligible_segments: list[dict[str, Any]],
    pre_filter_segments: list[dict[str, Any]],
    output_segments: list[dict[str, Any]],
    model_missing_segment_ids: set[str],
) -> list[dict[str, Any]]:
    point_by_id = {str(point.get("id") or ""): point for point in selected_points}
    segment_by_point_id = {str(segment.get("learning_point_id") or ""): segment for segment in eligible_segments}
    generated_ids = {str(segment.get("learning_point_id") or "") for segment in output_segments}
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
            reason = "模型没有返回这个学习点的完整卡片内容。"
            status = "model_missing"
        else:
            status = "filtered"
            reason = "模型返回后未通过质量 gate 或重复过滤。"
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


def _card_generation_diagnostic_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"skipped": 0, "model_missing": 0, "filtered": 0}
    for item in items:
        status = str(item.get("status") or "")
        if status in counts:
            counts[status] += 1
    return counts


def handle_generate_cards_from_learning_points(payload: dict[str, Any]) -> dict[str, Any]:
    if not legacy_worker.phrase_review_available(payload):
        fail(
            "生成完整卡片需要可用的模型 API。请先在“模型 API”里测试连接，不能使用预览模式制卡。",
            error_code="MODEL_API_REQUIRED",
            stage="model_api",
            retryable=True,
        )
    all_points = [point for point in payload.get("learning_points") or [] if isinstance(point, dict)]
    if "selected_learning_point_ids" in payload:
        selected_ids = {str(item) for item in payload.get("selected_learning_point_ids") or []}
        selected = [point for point in all_points if str(point.get("id")) in selected_ids]
    else:
        selected = _default_selected_learning_points(all_points, payload)
    requested_card_types = [str(item) for item in payload.get("card_types") or ["phrase"]]
    segments: list[dict[str, Any]] = []
    for index, point in enumerate(selected, start=1):
        if str(point.get("status") or "") in {"hard_blocked", "hidden_duplicate"}:
            continue
        start = float(point.get("start") or 0)
        end = float(point.get("end") or start)
        card_type = _card_type_for_point(point, requested_card_types)
        card = _default_card(point, card_type, index)
        segments.append(
            {
                "id": f"seg_lp_{index:04d}",
                "source_segment_id": point.get("source_segment_id"),
                "learning_point_id": point.get("id"),
                "learning_points": [point],
                "start": start,
                "end": end,
                "source_time": point.get("source_time") or f"{legacy_worker.fmt_time(start)} - {legacy_worker.fmt_time(end)}",
                "media_start": start,
                "media_end": end,
                "media_source_time": point.get("source_time") or f"{legacy_worker.fmt_time(start)} - {legacy_worker.fmt_time(end)}",
                "text": point.get("source_sentence") or "",
                "duration": round(max(0.0, end - start), 2),
                "recommendation": int(round(float(point.get("value_score") or 4))),
                "phrase": point.get("answer_core") or point.get("exact_span") or "",
                "answer_core": point.get("answer_core") or point.get("exact_span") or "",
                "exact_span": point.get("exact_span") or "",
                "candidate_kind": point.get("candidate_kind"),
                "phrase_type": point.get("phrase_type"),
                "learning_action": point.get("learning_action"),
                "learning_action_key": point.get("learning_action_key"),
                "phrase_value_score": point.get("ai_value_score") or point.get("value_score") or 4,
                "phrase_review_status": "recommended" if point.get("status") == "recommended" else "needs_review",
                "phrase_review_source": "ai",
                "phrase_decision_reason": point.get("ai_reason") or point.get("reason") or point.get("status_reason") or "",
                "phrase_card_focus": point.get("learning_action") or point.get("reason") or "",
                "contract_source": point.get("review_source") or "ai",
                "language": payload.get("language") or "en",
                "score": float(point.get("final_score") or point.get("ai_value_score") or point.get("value_score") or 4),
                "cards": [],
            }
        )
    if not segments:
        fail("没有可生成的学习点。请至少选择一个推荐或候选学习点。", error_code="NO_SELECTED_LEARNING_POINTS", stage="cards")
    eligible_segments = [
        {"id": str(segment.get("id") or ""), "learning_point_id": str(segment.get("learning_point_id") or "")}
        for segment in segments
    ]

    emit_progress(
        "generate_cards_from_learning_points",
        "ai",
        20,
        f"正在把 {len(segments)} 个 AI 精筛学习点交给模型生成完整卡片。",
    )
    cache_path, cache_key = _card_generation_cache_path(payload, segments, requested_card_types)
    cache_disabled = bool(payload.get("disable_card_generation_cache") or (payload.get("api_config") or {}).get("disable_card_generation_cache"))
    ai_payload = None if cache_disabled else _load_card_generation_cache(cache_path)
    card_generation_cache_hit = bool(ai_payload)
    if ai_payload:
        emit_progress(
            "generate_cards_from_learning_points",
            "ai",
            82,
            f"卡片正文缓存命中：{len(segments)} 个学习点 · {cache_key[:8]}。",
        )
    else:
        ai_payload = legacy_worker.call_model_batches({**payload, "_progress_command": "generate_cards_from_learning_points"}, segments)
        if ai_payload and not cache_disabled:
            _store_card_generation_cache(cache_path, cache_key, ai_payload)
    if not ai_payload:
        fail(
            "生成完整卡片失败：模型没有返回可用卡片内容。",
            error_code="MODEL_CARD_GENERATION_FAILED",
            stage="ai",
            retryable=True,
        )
    partial_generation_warning = ""
    if ai_payload.get("error") and not ai_payload.get("segments"):
        message = str((ai_payload or {}).get("error") or "模型没有返回可用卡片内容。")
        fail(
            f"生成完整卡片失败：{message}",
            error_code=str((ai_payload or {}).get("error_code") or "MODEL_CARD_GENERATION_FAILED"),
            stage=str((ai_payload or {}).get("stage") or "ai"),
            retryable=bool((ai_payload or {}).get("retryable")),
        )
    if ai_payload.get("error"):
        partial_generation_warning = (
            "部分学习点制卡失败，已先保留成功生成的卡片；失败学习点后续应回到候选库："
            + str(ai_payload.get("error") or "")
        )
    ai_segments = ai_payload.get("segments", []) if isinstance(ai_payload.get("segments"), list) else []
    ai_segments_with_usable_cards = {
        str(item.get("id") or "")
        for item in ai_segments
        if any(card.get("phrase") or card.get("chinese") or card.get("definition") for card in item.get("cards", []) or [])
    }
    model_missing_segment_ids = {str(segment.get("id") or "") for segment in segments if str(segment.get("id") or "") not in ai_segments_with_usable_cards}

    emit_progress("generate_cards_from_learning_points", "cards", 84, "正在整理 AI 卡片字段。")
    segments, warning = legacy_worker.merge_ai_cards(
        segments,
        ai_payload,
        requested_card_types,
        str(payload.get("level") or "B1"),
        payload.get("language") or "en",
    )
    segments = legacy_worker.enforce_reviewable_cards_per_source(segments, payload)
    segments = legacy_worker.apply_default_generated_card_selection(segments, payload)
    segments = legacy_worker.slim_fast_review_segments(segments, payload)
    pre_filter_segments = segments
    segments, output_filter_stats = legacy_worker.filter_usable_segments_for_output(segments, [])
    selected_count = sum(1 for segment in segments for card in segment.get("cards", []) if card.get("enabled"))
    if selected_count <= 0:
        fail("模型返回后没有可用卡片。请减少学习点数量或检查模型输出质量。", error_code="NO_USABLE_AI_CARDS", stage="cards", retryable=True)
    generated_learning_point_ids = {str(segment.get("learning_point_id") or "") for segment in segments if segment.get("cards")}
    eligible_learning_point_ids = {str(segment.get("learning_point_id") or "") for segment in pre_filter_segments}
    card_generation_diagnostic_items = _card_generation_diagnostic_items(
        selected,
        eligible_segments,
        pre_filter_segments,
        segments,
        model_missing_segment_ids,
    )
    card_generation_diagnostic_counts = _card_generation_diagnostic_counts(card_generation_diagnostic_items)
    quality_funnel = legacy_worker.build_quality_funnel(
        segments,
        subtitle_cues=0,
        candidate_segments=len(all_points),
        reviewed_keep=len(segments),
        mimo_kept=len(segments),
        max_learning_points=legacy_worker.max_learning_points_per_source(payload),
        filter_stats=output_filter_stats,
        level_mode=legacy_worker.normalized_level_mode(payload),
        learning_point_inventory=[],
    )
    upstream_funnel = payload.get("quality_funnel") if isinstance(payload.get("quality_funnel"), dict) else {}
    for key in [
        "source_sentence_count",
        "ai_reviewed_source_count",
        "ai_reviewed_candidate_count",
        "local_candidate_count",
        "ai_recommended_count",
        "ai_candidate_count",
        "ai_rejected_count",
        "ai_model_errors",
        "ai_review_cache_hits",
        "ai_review_cache_misses",
        "learning_point_count",
        "recommended_learning_point_count",
        "candidate_only_learning_point_count",
        "hidden_duplicate_learning_point_count",
        "hard_blocked_learning_point_count",
    ]:
        value = upstream_funnel.get(key)
        if value not in (None, ""):
            quality_funnel[key] = value
    quality_funnel["card_generation_cache_hit"] = card_generation_cache_hit
    quality_funnel["card_generation_cache_key"] = cache_key if card_generation_cache_hit else ""
    quality_funnel["selected_learning_point_count"] = len(selected)
    quality_funnel["eligible_learning_point_count"] = len(eligible_learning_point_ids)
    quality_funnel["successful_learning_point_count"] = len(generated_learning_point_ids)
    quality_funnel["card_generation_missing_learning_point_count"] = card_generation_diagnostic_counts["model_missing"]
    quality_funnel["card_generation_filtered_card_count"] = card_generation_diagnostic_counts["filtered"]
    quality_funnel["card_generation_skipped_learning_point_count"] = card_generation_diagnostic_counts["skipped"]
    emit_progress("generate_cards_from_learning_points", "done", 100, f"AI 卡片生成完成：{selected_count} 张可用卡。")
    return {
        "id": str(payload.get("project_id") or f"project_{int(time.time())}"),
        "title": payload.get("title") or "学习点制卡",
        "source_mode": payload.get("source_mode") or "local",
        "video_path": payload.get("video_path") or "",
        "subtitle_path": payload.get("subtitle_path") or "",
        "language": payload.get("language") or "en",
        "level_mode": payload.get("level_mode") or "auto",
        "level": payload.get("level") or "B1",
        "template_id": payload.get("template_id") or "immersive_v11",
        "card_style": legacy_worker.normalize_card_style(payload.get("card_style")),
        "review_density": legacy_worker.normalize_review_density(payload.get("review_density")),
        "content_toggles": payload.get("content_toggles") or {},
        "language_focus": payload.get("language_focus") or ["phrases", "vocabulary", "grammar", "listening"],
        "study_depth": payload.get("study_depth") or "standard",
        "selection_strategy": "catch_all",
        "card_types": requested_card_types,
        "review_basis": payload.get("review_basis") or "ai_reviewed",
        "ai_model_provider": payload.get("ai_model_provider") or legacy_worker.provider_name(payload.get("api_config") or {}),
        "ai_model_name": payload.get("ai_model_name") or str((payload.get("api_config") or {}).get("model") or ""),
        "ai_reviewed_source_count": payload.get("ai_reviewed_source_count") or quality_funnel.get("ai_reviewed_source_count") or 0,
        "ai_reviewed_candidate_count": payload.get("ai_reviewed_candidate_count")
        or quality_funnel.get("ai_reviewed_candidate_count")
        or 0,
        "local_candidate_count": payload.get("local_candidate_count") or quality_funnel.get("local_candidate_count") or 0,
        "quality_funnel": quality_funnel,
        "card_generation_diagnostics": {
            "selected_learning_point_count": len(selected),
            "eligible_learning_point_count": len(eligible_learning_point_ids),
            "successful_learning_point_count": len(generated_learning_point_ids),
            "model_missing_learning_point_count": quality_funnel["card_generation_missing_learning_point_count"],
            "filtered_learning_point_count": quality_funnel["card_generation_filtered_card_count"],
            "skipped_learning_point_count": quality_funnel["card_generation_skipped_learning_point_count"],
            "items": card_generation_diagnostic_items[:100],
        },
        "learning_point_inventory": [],
        "segments": segments,
        "warning": " / ".join(item for item in [partial_generation_warning, warning] if item),
        "created_at": int(time.time() * 1000),
    }


__all__ = ["handle_generate_cards_from_learning_points"]
