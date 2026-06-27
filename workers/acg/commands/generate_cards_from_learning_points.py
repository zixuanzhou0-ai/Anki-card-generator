from __future__ import annotations

import time
import re
from pathlib import Path
from typing import Any

from acg import legacy_worker
from acg.card_generation_cache import (
    ai_payload_has_usable_cards,
    card_generation_cache_path,
    card_generation_cache_policy,
    load_card_generation_cache,
    single_card_generation_cache_paths,
    source_fingerprint,
    store_card_generation_cache,
)
from acg.card_generation_diagnostics import (
    card_generation_diagnostic_counts as _card_generation_diagnostic_counts,
    card_generation_diagnostic_items as _card_generation_diagnostic_items,
    generated_card_count_from_segments as _generated_card_count_from_segments,
    generated_learning_point_ids_from_project as _generated_learning_point_ids_from_project,
    generated_learning_point_ids_from_segment as _generated_learning_point_ids_from_segment,
    segment_has_generated_learning_point_card as _segment_has_generated_learning_point_card,
)
from acg.generation_timing import add_generation_timing_aliases as _add_generation_timing_aliases
from acg.learning_settings import max_learning_points_per_source
from acg.learning_types import card_label_for_learning_card, content_kind_for_phrase_type
from acg.learning_spans import phrase_in_text
from acg.media_alignment import (
    clean_adjacent_caption_repeats,
    learning_point_media_alignment_fields,
)
from acg.protocol import emit_progress, fail
from acg.subtitles.provenance import point_with_source_sentence_provenance, source_sentence_indexes

MAX_CARD_SOURCE_SENTENCE_WORDS = 18
MEDIA_ALIGNMENT_REVIEW_ISSUE = "媒体对齐未在原句中定位到目标表达，需复查。"


def _card_type_for_point(point: dict[str, Any], requested: list[str]) -> str:
    return "phrase"


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
    phrase_type = str(point.get("phrase_type") or "").lower()
    answer = str(point.get("answer_core") or point.get("exact_span") or "").strip()
    word_count = len([part for part in answer.split() if part])
    base += {
        "sentence_frame": 0.35,
        "spoken_phrase": 0.32,
        "phrasal_verb": 0.30,
        "listening_sentence": 0.18,
        "vocabulary_usage": 0.08,
    }.get(phrase_type, 0.0)
    if phrase_type == "collocation" and word_count <= 2:
        base -= 0.22
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
    if exact_span and phrase_in_text(sentence, exact_span):
        return re.sub(re.escape(exact_span), f"{{{{c1::{exact_span}}}}}", sentence, count=1, flags=re.IGNORECASE)
    return sentence


def _source_sentence_for_card(point: dict[str, Any], *, max_words: int = MAX_CARD_SOURCE_SENTENCE_WORDS) -> str:
    text = clean_adjacent_caption_repeats(legacy_worker.clean_candidate_text(str(point.get("source_sentence") or "")))
    words = list(re.finditer(r"\S+", text))
    if len(words) <= max_words:
        return text

    span_start = point.get("exact_span_start")
    span_end = point.get("exact_span_end")
    if not isinstance(span_start, (int, float)) or not isinstance(span_end, (int, float)) or span_end <= span_start:
        phrase = str(point.get("exact_span") or point.get("answer_core") or "").strip()
        match = re.search(re.escape(phrase), text, flags=re.IGNORECASE) if phrase else None
        if not match:
            return text
        span_start, span_end = match.start(), match.end()

    target_start: int | None = None
    target_end = 0
    for index, word in enumerate(words):
        if word.end() > float(span_start) and target_start is None:
            target_start = index
        if word.start() < float(span_end):
            target_end = index
    if target_start is None:
        target_start = 0
    target_word_count = max(1, target_end - target_start + 1)
    extra = max(0, max_words - target_word_count)
    left = max(0, target_start - extra // 2)
    right = min(len(words), left + max_words)
    left = max(0, right - max_words)
    return clean_adjacent_caption_repeats(" ".join(word.group(0) for word in words[left:right]).strip() or text)


def _default_card(point: dict[str, Any], card_type: str, index: int) -> dict[str, Any]:
    sentence = _source_sentence_for_card(point)
    answer = str(point.get("answer_core") or point.get("exact_span") or "")
    level = str(point.get("level") or point.get("estimated_level") or "B1")
    reason = str(point.get("reason") or point.get("status_reason") or "原句中有明确学习价值。")
    return {
        "id": f"card_{index:04d}",
        "type": card_type,
        "type_label": "学习卡",
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


def _media_alignment_needs_review(fields: dict[str, Any]) -> bool:
    return str(fields.get("media_alignment_review_status") or "").strip() == "needs_review"


def _with_media_alignment_review_reason(reason: str, fields: dict[str, Any]) -> str:
    diagnostic = str(fields.get("media_alignment_review_reason") or "").strip()
    reason = str(reason or "").strip()
    if not diagnostic or diagnostic in reason:
        return reason
    return f"{reason} / {diagnostic}" if reason else diagnostic


def _phrase_review_status_for_media_alignment(point: dict[str, Any], media_fields: dict[str, Any]) -> str:
    if _media_alignment_needs_review(media_fields):
        return "needs_review"
    return "recommended" if point.get("status") == "recommended" else "needs_review"


def _apply_media_alignment_review_to_card(card: dict[str, Any], segment: dict[str, Any]) -> dict[str, Any]:
    if not _media_alignment_needs_review(segment):
        return card
    next_card = dict(card)
    next_card["phrase_review_status"] = "needs_review"
    next_card["phrase_decision_reason"] = _with_media_alignment_review_reason(
        str(next_card.get("phrase_decision_reason") or ""),
        segment,
    )
    quality = dict(next_card.get("quality") or {})
    issues = [str(issue) for issue in quality.get("issues", []) or []]
    if MEDIA_ALIGNMENT_REVIEW_ISSUE not in issues:
        issues.append(MEDIA_ALIGNMENT_REVIEW_ISSUE)
    try:
        score = int(quality.get("score") or 58)
    except (TypeError, ValueError):
        score = 58
    quality["score"] = min(score, 70)
    quality["status"] = "needs_review"
    quality["issues"] = issues
    next_card["quality"] = quality
    return next_card


def _card_generation_cache_context(payload: dict[str, Any]) -> dict[str, Any]:
    api = payload.get("api_config") or {}
    return {
        "cache_root": legacy_worker.persistent_cache_root(),
        "provider_name": legacy_worker.provider_name(api),
        "normalized_language": legacy_worker.normalize_learning_language(payload.get("language", "en")),
        "normalized_level_mode": legacy_worker.normalized_level_mode(payload),
        "normalized_review_density": legacy_worker.normalize_review_density(payload.get("review_density")),
    }


STALE_ASR_HARD_GATE_KEYS = {
    "tts_semantic_verification",
    "asr_provider",
    "require_pass_for_export",
    "enable_asr_quality_gate",
}


def _without_stale_asr_hard_gate_fields(project: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in project.items() if key not in STALE_ASR_HARD_GATE_KEYS}


def _cached_or_generated_card_payload(
    payload: dict[str, Any],
    segments: list[dict[str, Any]],
    requested_card_types: list[str],
    *,
    cache_read_enabled: bool,
    cache_write_enabled: bool,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    cache_context = _card_generation_cache_context(payload)
    whole_cache_path, whole_cache_key = card_generation_cache_path(
        payload,
        segments,
        requested_card_types,
        **cache_context,
    )
    stats: dict[str, Any] = {
        "cache_hits": 0,
        "cache_misses": 0,
        "cache_keys": [],
        "whole_cache_key": whole_cache_key,
        "whole_cache_hit": False,
        "cache_read_enabled": cache_read_enabled,
        "cache_write_enabled": cache_write_enabled,
    }
    if cache_read_enabled:
        whole_payload = load_card_generation_cache(whole_cache_path)
        if whole_payload:
            stats["cache_hits"] = len(segments)
            stats["whole_cache_hit"] = True
            stats["cache_keys"] = [whole_cache_key]
            return whole_payload, stats

    single_paths = single_card_generation_cache_paths(
        payload,
        segments,
        requested_card_types,
        **cache_context,
    )
    cached_by_segment_id: dict[str, dict[str, Any]] = {}
    missing_segments: list[dict[str, Any]] = []
    if not cache_read_enabled:
        missing_segments = segments
        stats["cache_misses"] = len(segments)
    else:
        for segment in segments:
            segment_id = str(segment.get("id") or "")
            cache_path, cache_key = single_paths.get(segment_id, (Path(), ""))
            cached = load_card_generation_cache(cache_path) if cache_path else None
            cached_segments = cached.get("segments") if isinstance(cached, dict) else None
            if isinstance(cached_segments, list) and cached_segments:
                cached_by_segment_id[segment_id] = cached_segments[0]
                stats["cache_hits"] += 1
                stats["cache_keys"].append(cache_key)
            else:
                missing_segments.append(segment)
                stats["cache_misses"] += 1

    generated_payload: dict[str, Any] | None = None
    if missing_segments:
        generated_payload = legacy_worker.call_model_batches(
            {**payload, "_progress_command": "generate_cards_from_learning_points"},
            missing_segments,
        )
        if not generated_payload:
            return None, stats
        if generated_payload.get("segments") and cache_write_enabled:
            generated_by_segment_id = {
                str(segment.get("id") or ""): segment
                for segment in generated_payload.get("segments") or []
                if isinstance(segment, dict)
            }
            for segment in missing_segments:
                segment_id = str(segment.get("id") or "")
                generated_segment = generated_by_segment_id.get(segment_id)
                cache_path, cache_key = single_paths.get(segment_id, (Path(), ""))
                if generated_segment and cache_path:
                    store_card_generation_cache(cache_path, cache_key, {"segments": [generated_segment]})

    generated_by_segment_id = {
        str(segment.get("id") or ""): segment
        for segment in (generated_payload or {}).get("segments", []) or []
        if isinstance(segment, dict)
    }
    merged_segments = []
    for segment in segments:
        segment_id = str(segment.get("id") or "")
        if segment_id in cached_by_segment_id:
            merged_segments.append(cached_by_segment_id[segment_id])
        elif segment_id in generated_by_segment_id:
            merged_segments.append(generated_by_segment_id[segment_id])

    ai_payload: dict[str, Any] = {"segments": merged_segments}
    if generated_payload and generated_payload.get("error"):
        ai_payload["error"] = generated_payload.get("error")
        for key in ["error_code", "stage", "retryable", "fallbacks"]:
            if key in generated_payload:
                ai_payload[key] = generated_payload[key]
    if merged_segments and cache_write_enabled:
        store_card_generation_cache(whole_cache_path, whole_cache_key, ai_payload)
    return ai_payload, stats


def _learning_point_answer_tokens(item: dict[str, Any]) -> set[str]:
    values = [
        item.get("answer_core"),
        item.get("exact_span"),
        item.get("normalized_answer"),
        item.get("phrase"),
    ]
    tokens: set[str] = set()
    for value in values:
        text = legacy_worker.answer_display_text(value)
        if text:
            tokens.add(re.sub(r"\s+", " ", text).strip().casefold())
    return {token for token in tokens if token}


def _card_belongs_to_learning_point(card: dict[str, Any], segment: dict[str, Any]) -> bool:
    target_id = str(segment.get("learning_point_id") or "").strip()
    card_point_id = str(card.get("learning_point_id") or "").strip()
    if card_point_id and target_id and card_point_id != target_id:
        return False
    target_tokens = _learning_point_answer_tokens(segment)
    if not target_tokens:
        return True
    return bool(_learning_point_answer_tokens(card) & target_tokens)


def _filter_cards_to_selected_learning_points(segments: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    filtered_segments: list[dict[str, Any]] = []
    dropped = 0
    for segment in segments:
        cards = [card for card in segment.get("cards", []) or [] if isinstance(card, dict)]
        if not cards:
            filtered_segments.append(segment)
            continue
        kept = [card for card in cards if _card_belongs_to_learning_point(card, segment)]
        dropped += len(cards) - len(kept)
        filtered_segments.append({**segment, "cards": kept})
    return filtered_segments, dropped


def _selected_card_fallback_text(segment: dict[str, Any], key: str, default: str = "") -> str:
    point = (segment.get("learning_points") or [{}])[0]
    for source in (point, segment):
        value = legacy_worker.clean_study_text(str(source.get(key) or ""))
        if value and not legacy_worker.contains_internal_placeholder(value):
            return value
    return default


def _user_selected_fallback_card(
    segment: dict[str, Any],
    requested_card_types: list[str],
    level: str,
    language: str,
) -> dict[str, Any]:
    point = dict((segment.get("learning_points") or [{}])[0])
    answer = legacy_worker.clean_study_text(
        point.get("answer_core")
        or point.get("normalized_answer")
        or point.get("exact_span")
        or segment.get("answer_core")
        or segment.get("exact_span")
        or segment.get("phrase")
        or ""
    )
    sentence = legacy_worker.clean_study_text(str(segment.get("text") or point.get("source_sentence") or ""))
    if not answer or answer == "key expression":
        answer = sentence
    card_type = _card_type_for_point({**point, "candidate_kind": point.get("kind") or segment.get("candidate_kind")}, requested_card_types)
    phrase_type = str(point.get("phrase_type") or segment.get("phrase_type") or "")
    content_kind = str(point.get("content_kind") or content_kind_for_phrase_type(phrase_type))
    reason = _selected_card_fallback_text(
        segment,
        "reason",
        _selected_card_fallback_text(segment, "learning_action", f"围绕“{answer}”复习这句里的意思和用法。"),
    )
    learning_action = _selected_card_fallback_text(segment, "learning_action", reason)
    chinese = _selected_card_fallback_text(
        segment,
        "natural_chinese",
        _selected_card_fallback_text(segment, "chinese", f"结合原句理解“{answer}”。"),
    )
    definition = _selected_card_fallback_text(segment, "definition", reason)
    teacher_note = _selected_card_fallback_text(segment, "teacher_note", learning_action)
    card = {
        "id": f"{segment['id']}_{segment.get('learning_point_id') or 'selected'}_{card_type}",
        "type": card_type,
        "type_label": "学习卡",
        "enabled": False,
        "english": sentence,
        "chinese": chinese,
        "phrase": answer,
        "definition": definition,
        "collocations": _selected_card_fallback_text(segment, "collocations", answer),
        "context": sentence,
        "example": _selected_card_fallback_text(segment, "example", sentence),
        "chinese_feel": chinese,
        "why": reason,
        "difficulty": str(point.get("level") or point.get("estimated_level") or level),
        "estimated_level": str(point.get("level") or point.get("estimated_level") or level),
        "difficulty_reason": str(point.get("level_reason") or "根据学习点和原句上下文估计。"),
        "teacher_note": teacher_note,
        "cloze": _cloze(sentence, answer),
        "card_role": "user_selected",
        "learning_goal": learning_action,
        "decision_reason": reason,
        "learning_target": learning_action,
        "learning_action": learning_action,
        "conceptual_action": str(point.get("conceptual_action") or ""),
        "chinese_learner_trap": str(point.get("chinese_learner_trap") or point.get("confusable_note") or ""),
        "why_it_matters": reason,
        "how_to_use_it": teacher_note,
        "natural_chinese": chinese,
        "replacement_examples": _selected_card_fallback_text(segment, "replacement_examples", ""),
        "avoid_reason": "",
        "phrase_value_score": segment.get("phrase_value_score"),
        "phrase_decision_reason": segment.get("phrase_decision_reason") or reason,
        "phrase_reject_reason": "",
        "phrase_card_focus": learning_action,
        "phrase_review_status": "needs_review",
        "phrase_type": phrase_type,
        "learning_point_id": segment.get("learning_point_id"),
        "content_kind": content_kind,
        "candidate_kind": point.get("kind") or segment.get("candidate_kind") or "",
        "exact_span": point.get("exact_span") or segment.get("exact_span") or answer,
        "normalized_answer": point.get("normalized_answer") or segment.get("normalized_answer") or answer,
        "candidate_source": segment.get("candidate_source", ""),
        "learning_point_schema_version": segment.get("learning_point_schema_version") or legacy_worker.LEARNING_POINT_SCHEMA_VERSION,
        "source_evidence": point.get("source_evidence") or segment.get("source_evidence") or sentence,
        "retrieval_prompt": f"这句里要复习的表达是什么？",
        "answer_core": answer,
        "language": legacy_worker.normalize_learning_language(language),
        "usage_boundary": str(point.get("usage_boundary") or ""),
        "confusable_note": str(point.get("confusable_note") or ""),
        "phonetic_ipa": str(point.get("phonetic_ipa") or ""),
        "spoken_ipa": str(point.get("spoken_ipa") or ""),
        "source_spoken_ipa": str(point.get("source_spoken_ipa") or ""),
        "pronunciation_note": str(point.get("pronunciation_note") or ""),
        "pronunciation_confidence": str(point.get("pronunciation_confidence") or ""),
        "pronunciation_status": str(point.get("pronunciation_status") or ""),
        "source_pronunciation_status": str(point.get("source_pronunciation_status") or ""),
        "pronunciation_meta": point.get("pronunciation_meta") or None,
        "quality": {
            "score": 58,
            "status": "needs_review",
            "issues": ["用户已勾选，模型未完整返回时由系统保底生成。"],
        },
        "generation_source": "fallback_from_selected_learning_point",
        "missing_ai_fields": ["card"],
        "fallback_fields_filled": [
            "english",
            "chinese",
            "phrase",
            "definition",
            "teacher_note",
            "answer_core",
        ],
    }
    legacy_worker.normalize_learning_action_fields(card)
    legacy_worker.repair_card_fields(card, segment, level)
    legacy_worker.sanitize_pronunciation_fields(card, language)
    card["type_label"] = "学习卡"
    return card


def _missing_selected_card_fields(card: dict[str, Any]) -> list[str]:
    required_fields = ["english", "phrase", "answer_core", "chinese", "definition", "teacher_note"]
    missing: list[str] = []
    for key in required_fields:
        value = str(card.get(key) or "")
        if not value.strip() or legacy_worker.contains_internal_placeholder(value):
            missing.append(key)
    return missing


def _make_selected_card_exportable(
    card: dict[str, Any],
    segment: dict[str, Any],
    fallback_card: dict[str, Any],
    original_missing_fields: list[str] | None = None,
) -> dict[str, Any]:
    next_card = dict(card)
    missing_fields = list(dict.fromkeys([*_missing_selected_card_fields(next_card), *(original_missing_fields or [])]))
    fallback_fields_filled: list[str] = list(original_missing_fields or [])
    text_keys = ["chinese", "definition", "teacher_note"]
    for key in text_keys:
        value = str(next_card.get(key) or "")
        if not value.strip() or legacy_worker.contains_internal_placeholder(value):
            next_card[key] = fallback_card.get(key) or value
            fallback_fields_filled.append(key)
    for key in [
        "phrase",
        "answer_core",
        "exact_span",
        "normalized_answer",
        "learning_point_id",
        "candidate_kind",
        "phrase_type",
        "content_kind",
    ]:
        if next_card.get(key) in (None, "") and fallback_card.get(key) not in (None, ""):
            next_card[key] = fallback_card.get(key)
            fallback_fields_filled.append(key)
    if not str(next_card.get("english") or "").strip():
        next_card["english"] = fallback_card.get("english") or segment.get("text") or ""
        fallback_fields_filled.append("english")
    next_card["enabled"] = True
    quality = dict(next_card.get("quality") or {})
    issues = [
        str(issue)
        for issue in quality.get("issues", []) or []
        if str(issue) not in legacy_worker.EXPORT_BLOCKING_QUALITY_ISSUES
    ]
    if legacy_worker.card_has_export_blocking_content(next_card):
        next_card = dict(fallback_card)
        quality = dict(next_card.get("quality") or {})
        issues = list(quality.get("issues") or [])
        fallback_fields_filled = list(fallback_card.get("fallback_fields_filled") or fallback_fields_filled or ["card"])
        missing_fields = list(dict.fromkeys([*missing_fields, "card"]))
    quality["status"] = "recommended" if quality.get("status") == "recommended" else "needs_review"
    quality["score"] = max(50, int(quality.get("score") or 0))
    if "用户已勾选，保证生成。" not in issues:
        issues.append("用户已勾选，保证生成。")
    quality["issues"] = issues
    next_card["quality"] = quality
    source = str(next_card.get("generation_source") or "")
    if source == "fallback_from_selected_learning_point":
        next_card["enabled"] = False
    elif fallback_fields_filled or missing_fields:
        next_card["generation_source"] = "ai_repaired"
    else:
        next_card["generation_source"] = "ai_complete"
    if source != "fallback_from_selected_learning_point":
        next_card["enabled"] = quality.get("status") == "recommended" and not legacy_worker.card_has_export_blocking_content(next_card)
    if missing_fields:
        next_card["missing_ai_fields"] = list(dict.fromkeys([str(item) for item in missing_fields if item]))
    if fallback_fields_filled:
        next_card["fallback_fields_filled"] = list(dict.fromkeys([str(item) for item in fallback_fields_filled if item]))
    return next_card


def _ensure_user_selected_learning_point_cards(
    segments: list[dict[str, Any]],
    requested_card_types: list[str],
    level: str,
    language: str,
    ai_missing_fields_by_segment_id: dict[str, list[str]] | None = None,
) -> tuple[list[dict[str, Any]], int, int]:
    ensured_segments: list[dict[str, Any]] = []
    fallback_count = 0
    repaired_count = 0
    for segment in segments:
        fallback_card = _user_selected_fallback_card(segment, requested_card_types, level, language)
        cards = [card for card in segment.get("cards", []) or [] if isinstance(card, dict)]
        usable_cards = [
            card
            for card in cards
            if _card_belongs_to_learning_point(card, segment)
            and not legacy_worker.card_has_export_blocking_content(card)
        ]
        selected_card = usable_cards[0] if usable_cards else fallback_card
        if selected_card is fallback_card or not usable_cards:
            fallback_count += 1
        ensured_card = _make_selected_card_exportable(
            selected_card,
            segment,
            fallback_card,
            (ai_missing_fields_by_segment_id or {}).get(str(segment.get("id") or ""), []),
        )
        ensured_card = _apply_media_alignment_review_to_card(ensured_card, segment)
        if str(ensured_card.get("generation_source") or "") == "ai_repaired":
            repaired_count += 1
        phrase_review_status = (
            "needs_review"
            if _media_alignment_needs_review(segment)
            else str(segment.get("phrase_review_status") or "recommended")
        )
        ensured_segments.append({**segment, "cards": [ensured_card], "phrase_review_status": phrase_review_status})
    return ensured_segments, fallback_count, repaired_count


def handle_generate_cards_from_learning_points(payload: dict[str, Any]) -> dict[str, Any]:
    timing_started = time.perf_counter()
    source_started = timing_started
    timing_ms: dict[str, int] = {}
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
    requested_selected_ids = {str(point.get("id") or "") for point in selected if str(point.get("id") or "").strip()}
    requested_selected_count = len(selected)
    existing_project = payload.get("existing_project") if isinstance(payload.get("existing_project"), dict) else {}
    existing_segments = [
        segment
        for segment in existing_project.get("segments", []) or []
        if isinstance(segment, dict) and _segment_has_generated_learning_point_card(segment)
    ]
    payload_existing_generated_ids = {
        str(item)
        for item in payload.get("existing_generated_ids", []) or []
        if str(item).strip()
    }
    verified_existing_generated_ids = _generated_learning_point_ids_from_project(existing_project)
    existing_generated_ids = (
        set(verified_existing_generated_ids)
        if existing_project
        else set(payload_existing_generated_ids)
    )
    existing_generated_selected_ids = requested_selected_ids & existing_generated_ids
    if existing_generated_ids:
        selected = [point for point in selected if str(point.get("id") or "") not in existing_generated_ids]
    requested_card_types = legacy_worker.requested_card_types([str(item) for item in payload.get("card_types") or ["phrase"]])
    segments: list[dict[str, Any]] = []
    source_by_id, source_by_text = source_sentence_indexes(payload.get("source_sentences") or [])
    for index, point in enumerate(selected, start=1 + len(existing_segments)):
        point = point_with_source_sentence_provenance(point, source_by_id, source_by_text)
        if str(point.get("status") or "") in {"hard_blocked", "hidden_duplicate"}:
            continue
        start = float(point.get("start") or 0)
        end = float(point.get("end") or start)
        card_type = _card_type_for_point(point, requested_card_types)
        source_sentence = _source_sentence_for_card(point)
        point_for_card = {**point, "source_sentence": source_sentence}
        card = _default_card(point_for_card, card_type, index)
        media_fields = learning_point_media_alignment_fields(
            point,
            start=start,
            end=end,
            display_sentence=source_sentence,
        )
        phrase_review_status = _phrase_review_status_for_media_alignment(point, media_fields)
        phrase_decision_reason = _with_media_alignment_review_reason(
            point.get("ai_reason") or point.get("reason") or point.get("status_reason") or "",
            media_fields,
        )
        segments.append(
            {
                "id": f"seg_lp_{index:04d}",
                "source_segment_id": point.get("source_segment_id"),
                "learning_point_id": point.get("id"),
                "learning_points": [point],
                "start": start,
                "end": end,
                "source_time": point.get("source_time") or f"{legacy_worker.fmt_time(start)} - {legacy_worker.fmt_time(end)}",
                **media_fields,
                "source_cue_ids": point.get("source_cue_ids") or [],
                "source_cue_count": point.get("source_cue_count"),
                "source_cue_start": point.get("source_cue_start"),
                "source_cue_end": point.get("source_cue_end"),
                "source_cue_time": point.get("source_cue_time") or "",
                "source_cue_texts": point.get("source_cue_texts") or [],
                "source_merge_reason": point.get("source_merge_reason") or "",
                "source_sentence_quality_flags": point.get("source_sentence_quality_flags") or [],
                "source_sentence_quality_status": point.get("source_sentence_quality_status") or "",
                "text": source_sentence,
                "full_source_sentence": point.get("source_sentence") or source_sentence,
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
                "phrase_review_status": phrase_review_status,
                "phrase_review_source": "ai",
                "phrase_decision_reason": phrase_decision_reason,
                "phrase_card_focus": point.get("learning_action") or point.get("reason") or "",
                "contract_source": point.get("review_source") or "ai",
                "language": payload.get("language") or "en",
                "score": float(point.get("final_score") or point.get("ai_value_score") or point.get("value_score") or 4),
                "cards": [],
            }
        )
    if not segments:
        if existing_segments:
            quality_funnel = dict(existing_project.get("quality_funnel") or {})
            timing_ms["source_prepare"] = int((time.perf_counter() - source_started) * 1000)
            timing_ms["total"] = int((time.perf_counter() - timing_started) * 1000)
            _add_generation_timing_aliases(timing_ms)
            existing_success_count = len(existing_generated_selected_ids)
            missing_learning_point_count = max(0, requested_selected_count - existing_success_count)
            quality_funnel["generation_timing_ms"] = timing_ms
            quality_funnel["card_generation_cache_hits"] = 0
            quality_funnel["card_generation_cache_misses"] = 0
            quality_funnel["generation_queue_count"] = requested_selected_count
            quality_funnel["generation_success_count"] = existing_success_count
            quality_funnel["generation_missing_count"] = missing_learning_point_count
            quality_funnel["generation_reconciliation_status"] = "partial" if missing_learning_point_count else "ok"
            quality_funnel["new_successful_learning_point_count"] = 0
            quality_funnel["existing_generated_selected_count"] = existing_success_count
            exportable_existing_count = _generated_card_count_from_segments(existing_segments)
            card_generation_diagnostics = dict(existing_project.get("card_generation_diagnostics") or {})
            card_generation_diagnostics.update(
                {
                    "processed_learning_point_count": requested_selected_count,
                    "selected_learning_point_count": 0,
                    "eligible_learning_point_count": 0,
                    "successful_learning_point_count": existing_success_count,
                    "new_successful_learning_point_count": 0,
                    "existing_generated_selected_count": existing_success_count,
                    "generated_card_count": 0,
                    "exportable_card_count": exportable_existing_count,
                    "missing_learning_point_count": missing_learning_point_count,
                    "items": [],
                }
            )
            returned_project = _without_stale_asr_hard_gate_fields(existing_project)
            explicit_tts_semantic = payload.get("tts_semantic_verification")
            explicit_tts_semantic = explicit_tts_semantic if isinstance(explicit_tts_semantic, dict) else {}
            return {
                **returned_project,
                "api_config": existing_project.get("api_config") or payload.get("api_config") or {},
                "tts_config": existing_project.get("tts_config") or payload.get("tts_config") or {},
                "tts_semantic_verification": explicit_tts_semantic,
                "quality_funnel": quality_funnel,
                "card_generation_diagnostics": card_generation_diagnostics,
                "generated_learning_point_ids": sorted(existing_generated_ids),
                "source_fingerprint": existing_project.get("source_fingerprint") or source_fingerprint(payload),
            }
        fail("没有可生成的学习点。请至少选择一个推荐或候选学习点。", error_code="NO_SELECTED_LEARNING_POINTS", stage="cards")
    source_mode = str(payload.get("source_mode") or "").strip().lower()
    source_info = payload.get("source_info") if isinstance(payload.get("source_info"), dict) else {}
    if source_mode in {"local", "document"}:
        legacy_worker.require_confirmed_local_path_access(
            payload,
            stage="document" if source_mode == "document" else "source",
        )
    if source_mode == "url" and (not payload.get("video_path") or not payload.get("subtitle_path")):
        emit_progress(
            "generate_cards_from_learning_points",
            "source",
            8,
            "正在准备 URL 视频和字幕。",
        )
        source_info = legacy_worker.download_url_source(payload)
        skip_video_slicing = bool(source_info.get("skip_video_slicing")) or (
            bool(payload.get("skip_video_slicing")) and not legacy_worker.url_video_mode_requested(payload)
        )
        payload = {
            **payload,
            "video_path": source_info.get("video_path", ""),
            "subtitle_path": source_info.get("subtitle_path", ""),
            "title": payload.get("title") or source_info.get("title") or "",
            "source_info": source_info,
            "skip_video_slicing": skip_video_slicing,
        }
    timing_ms["source_prepare"] = int((time.perf_counter() - source_started) * 1000)
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
    model_started = time.perf_counter()
    _cache_path, cache_key = card_generation_cache_path(
        payload,
        segments,
        requested_card_types,
        **_card_generation_cache_context(payload),
    )
    card_generation_cache_read_enabled, card_generation_cache_write_enabled = card_generation_cache_policy(payload)
    ai_payload, card_generation_cache_stats = _cached_or_generated_card_payload(
        payload,
        segments,
        requested_card_types,
        cache_read_enabled=card_generation_cache_read_enabled,
        cache_write_enabled=card_generation_cache_write_enabled,
    )
    card_generation_cache_hits = int(card_generation_cache_stats.get("cache_hits") or 0)
    card_generation_cache_misses = int(card_generation_cache_stats.get("cache_misses") or 0)
    card_generation_cache_hit = bool(card_generation_cache_hits and card_generation_cache_misses == 0)
    if card_generation_cache_hit:
        emit_progress(
            "generate_cards_from_learning_points",
            "ai",
            82,
            f"卡片正文缓存命中：{card_generation_cache_hits} 个学习点 · {cache_key[:8]}。",
        )
    else:
        emit_progress(
            "generate_cards_from_learning_points",
            "ai",
            82,
            f"卡片正文缓存：命中 {card_generation_cache_hits} 个，实时生成 {card_generation_cache_misses} 个。",
        )
    timing_ms["card_model"] = int((time.perf_counter() - model_started) * 1000)
    if not ai_payload:
        fail(
            "生成完整卡片失败：模型没有返回可导出卡片内容。",
            error_code="MODEL_CARD_GENERATION_FAILED",
            stage="ai",
            retryable=True,
        )
    partial_generation_warning = ""
    if ai_payload.get("error") and not ai_payload.get("segments"):
        message = str((ai_payload or {}).get("error") or "模型没有返回可导出卡片内容。")
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
    card_generation_retry_count = 0
    if not ai_segments_with_usable_cards and card_generation_cache_misses > 0:
        card_generation_retry_count = 1
        emit_progress(
            "generate_cards_from_learning_points",
            "ai",
            83,
            "卡片正文首次结果不可用，正在按原质量标准重试 1/1。",
        )
        retry_payload = legacy_worker.call_model_batches(
            {**payload, "_progress_command": "generate_cards_from_learning_points"},
            segments,
        )
        if ai_payload_has_usable_cards(retry_payload):
            ai_payload = retry_payload
            if card_generation_cache_write_enabled:
                store_card_generation_cache(_cache_path, cache_key, retry_payload)
            ai_segments = ai_payload.get("segments", []) if isinstance(ai_payload.get("segments"), list) else []
            ai_segments_with_usable_cards = {
                str(item.get("id") or "")
                for item in ai_segments
                if any(card.get("phrase") or card.get("chinese") or card.get("definition") for card in item.get("cards", []) or [])
            }
        timing_ms["card_model"] = int((time.perf_counter() - model_started) * 1000)
    model_missing_segment_ids = {str(segment.get("id") or "") for segment in segments if str(segment.get("id") or "") not in ai_segments_with_usable_cards}
    ai_missing_fields_by_segment_id: dict[str, list[str]] = {}
    for ai_segment in ai_segments:
        if not isinstance(ai_segment, dict):
            continue
        segment_id = str(ai_segment.get("id") or "")
        if not segment_id:
            continue
        for card in ai_segment.get("cards", []) or []:
            if not isinstance(card, dict):
                continue
            missing_fields = _missing_selected_card_fields(card)
            if missing_fields:
                ai_missing_fields_by_segment_id[segment_id] = missing_fields
            break

    emit_progress("generate_cards_from_learning_points", "cards", 84, "正在整理 AI 卡片字段。")
    field_started = time.perf_counter()
    segments, warning = legacy_worker.merge_ai_cards(
        segments,
        ai_payload,
        requested_card_types,
        str(payload.get("level") or "B1"),
        payload.get("language") or "en",
    )
    segments, off_target_card_count = _filter_cards_to_selected_learning_points(segments)
    segments = legacy_worker.apply_default_generated_card_selection(segments, payload)
    segments = legacy_worker.slim_fast_review_segments(segments, payload)
    segments, user_selected_fallback_count, ai_repaired_card_count = _ensure_user_selected_learning_point_cards(
        segments,
        requested_card_types,
        str(payload.get("level") or "B1"),
        payload.get("language") or "en",
        ai_missing_fields_by_segment_id,
    )
    pre_filter_segments = segments
    review_segments = segments
    output_segments, output_filter_stats = legacy_worker.filter_usable_segments_for_output(
        review_segments,
        [],
        dedupe_cards=False,
    )
    segments = [*existing_segments, *review_segments] if existing_segments else review_segments
    exportable_segments = [*existing_segments, *output_segments] if existing_segments else output_segments
    selected_count = _generated_card_count_from_segments(exportable_segments)
    reviewable_output_card_count = sum(
        1
        for segment in output_segments
        if isinstance(segment, dict)
        for card in segment.get("cards", []) or []
        if isinstance(card, dict)
        and legacy_worker.card_quality_status(card) in {"recommended", "needs_review"}
        and not legacy_worker.card_has_export_blocking_content(card)
    )
    review_card_count = sum(
        1
        for segment in segments
        if isinstance(segment, dict)
        for card in segment.get("cards", []) or []
        if isinstance(card, dict)
    )
    card_generation_diagnostic_items = _card_generation_diagnostic_items(
        selected,
        eligible_segments,
        pre_filter_segments,
        output_segments,
        model_missing_segment_ids,
    )
    card_generation_diagnostic_counts = _card_generation_diagnostic_counts(card_generation_diagnostic_items)
    if selected_count <= 0 and reviewable_output_card_count <= 0:
        fail(
            "模型返回后没有可导出卡片。请减少学习点数量或检查模型输出质量。",
            error_code="NO_USABLE_AI_CARDS",
            stage="cards",
            retryable=True,
            details={
                "failed_learning_points": card_generation_diagnostic_items,
                "card_generation_diagnostic_counts": card_generation_diagnostic_counts,
                "output_filter_stats": output_filter_stats,
            },
        )
    current_generated_learning_point_ids: set[str] = set()
    for segment in output_segments:
        if isinstance(segment, dict):
            current_generated_learning_point_ids.update(_generated_learning_point_ids_from_segment(segment))
    generated_learning_point_ids = set(current_generated_learning_point_ids)
    generated_learning_point_ids.update(existing_generated_ids)
    successful_selected_learning_point_ids = set(current_generated_learning_point_ids) | existing_generated_selected_ids
    eligible_learning_point_ids = {str(segment.get("learning_point_id") or "") for segment in pre_filter_segments}
    generated_card_count = _generated_card_count_from_segments(output_segments)
    review_only_card_count = max(0, review_card_count - selected_count)
    missing_learning_point_count = max(0, requested_selected_count - len(successful_selected_learning_point_ids))
    quality_funnel = legacy_worker.build_quality_funnel(
        segments,
        subtitle_cues=0,
        candidate_segments=len(all_points),
        reviewed_keep=len(segments),
        mimo_kept=len(segments),
        max_learning_points=max_learning_points_per_source(payload),
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
    timing_ms["field_merge"] = int((time.perf_counter() - field_started) * 1000)
    timing_ms["total"] = int((time.perf_counter() - timing_started) * 1000)
    _add_generation_timing_aliases(timing_ms)
    quality_funnel["card_generation_cache_hit"] = card_generation_cache_hit
    quality_funnel["card_generation_cache_key"] = cache_key if card_generation_cache_hit else ""
    quality_funnel["card_generation_cache_hits"] = card_generation_cache_hits
    quality_funnel["card_generation_cache_misses"] = card_generation_cache_misses
    quality_funnel["card_generation_cache_read_enabled"] = card_generation_cache_read_enabled
    quality_funnel["card_generation_cache_write_enabled"] = card_generation_cache_write_enabled
    quality_funnel["card_generation_cache_namespace"] = str(
        payload.get("card_generation_cache_namespace")
        or (payload.get("api_config") or {}).get("card_generation_cache_namespace")
        or ""
    ).strip()
    quality_funnel["off_target_learning_point_cards_dropped"] = off_target_card_count
    quality_funnel["user_selected_fallback_card_count"] = user_selected_fallback_count
    quality_funnel["ai_repaired_card_count"] = ai_repaired_card_count
    quality_funnel["card_generation_retry_count"] = card_generation_retry_count
    quality_funnel["review_only_card_count"] = review_only_card_count
    quality_funnel["generation_timing_ms"] = timing_ms
    quality_funnel["selected_learning_point_count"] = len(selected)
    quality_funnel["eligible_learning_point_count"] = len(eligible_learning_point_ids)
    quality_funnel["successful_learning_point_count"] = len(successful_selected_learning_point_ids)
    quality_funnel["new_successful_learning_point_count"] = len(current_generated_learning_point_ids)
    quality_funnel["existing_generated_selected_count"] = len(existing_generated_selected_ids)
    quality_funnel["generation_queue_count"] = requested_selected_count
    quality_funnel["generation_success_count"] = len(successful_selected_learning_point_ids)
    quality_funnel["generation_missing_count"] = missing_learning_point_count
    quality_funnel["generation_reconciliation_status"] = "partial" if missing_learning_point_count else "ok"
    quality_funnel["card_generation_missing_learning_point_count"] = (
        card_generation_diagnostic_counts["model_missing"] + card_generation_diagnostic_counts["hard_failed"]
    )
    quality_funnel["card_generation_filtered_card_count"] = card_generation_diagnostic_counts["filtered"]
    quality_funnel["card_generation_skipped_learning_point_count"] = card_generation_diagnostic_counts["skipped"]
    done_message = f"AI 卡片生成完成：{selected_count} 张可导出卡。"
    if review_only_card_count > 0:
        done_message = f"AI 卡片生成完成：{selected_count} 张可导出卡，{review_only_card_count} 张需修复。"
    emit_progress("generate_cards_from_learning_points", "done", 100, done_message)
    return {
        "id": str(payload.get("project_id") or f"project_{int(time.time())}"),
        "title": payload.get("title") or "学习点制卡",
        "source_mode": source_mode or payload.get("source_mode") or "local",
        "source_url": payload.get("source_url") or "",
        "url_import_mode": payload.get("url_import_mode") or ("video" if source_mode == "url" else ""),
        "video_path": payload.get("video_path") or "",
        "subtitle_path": payload.get("subtitle_path") or "",
        "document_path": payload.get("document_path") or "",
        "skip_video_slicing": bool(
            payload.get("skip_video_slicing")
            or (bool(source_info.get("transcript_only")) and not bool(payload.get("video_path")))
        ),
        "source_info": source_info,
        "batch_enabled": bool(payload.get("batch_enabled")),
        "batch_items": payload.get("batch_items") or [],
        "language": payload.get("language") or "en",
        "level_mode": payload.get("level_mode") or "auto",
        "level": payload.get("level") or "B1",
        "template_id": payload.get("template_id") or "immersive_v11",
        "card_style": legacy_worker.normalize_card_style(payload.get("card_style")),
        "review_density": legacy_worker.normalize_review_density(payload.get("review_density")),
        "content_toggles": payload.get("content_toggles") or {},
        "language_focus": payload.get("language_focus") or ["phrases", "vocabulary", "grammar", "listening"],
        "study_depth": payload.get("study_depth") or "standard",
        "api_config": payload.get("api_config") or {},
        "tts_config": payload.get("tts_config") or {},
        "tts_semantic_verification": payload.get("tts_semantic_verification") or {},
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
        "generated_learning_point_ids": sorted(generated_learning_point_ids),
        "source_fingerprint": source_fingerprint(payload, source_info),
        "card_generation_diagnostics": {
            "processed_learning_point_count": requested_selected_count,
            "selected_learning_point_count": len(selected),
            "eligible_learning_point_count": len(eligible_learning_point_ids),
            "successful_learning_point_count": len(successful_selected_learning_point_ids),
            "new_successful_learning_point_count": len(current_generated_learning_point_ids),
            "existing_generated_selected_count": len(existing_generated_selected_ids),
            "generated_card_count": generated_card_count,
            "exportable_card_count": selected_count,
            "missing_learning_point_count": missing_learning_point_count,
            "model_missing_learning_point_count": quality_funnel["card_generation_missing_learning_point_count"],
            "filtered_learning_point_count": quality_funnel["card_generation_filtered_card_count"],
            "skipped_learning_point_count": quality_funnel["card_generation_skipped_learning_point_count"],
            "items": card_generation_diagnostic_items,
        },
        "learning_point_inventory": [],
        "segments": segments,
        "warning": " / ".join(item for item in [partial_generation_warning, warning] if item),
        "created_at": int(time.time() * 1000),
    }


__all__ = ["handle_generate_cards_from_learning_points"]
