from __future__ import annotations

import hashlib
import re
from typing import Any

from acg import legacy_worker

ALLOWED_TYPES = {
    "phrase",
    "spoken",
    "vocab_usage",
    "grammar",
    "listening",
    "pragmatic",
}

TYPE_TO_CANDIDATE_KIND = {
    "phrase": "expression",
    "spoken": "expression",
    "vocab_usage": "contextual_vocab",
    "grammar": "grammar_pattern",
    "listening": "listening_feature",
    "pragmatic": "pragmatic_risk",
}

CANDIDATE_KIND_TO_TYPE = {
    "expression": "phrase",
    "contextual_vocab": "vocab_usage",
    "grammar_pattern": "grammar",
    "listening_feature": "listening",
    "pragmatic_risk": "pragmatic",
}

VALID_STATUSES = {"recommended", "candidate_only", "hidden_duplicate", "hard_blocked"}


def _stable_hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8", errors="ignore")).hexdigest()[:12]


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _source_id(source_segment: dict[str, Any]) -> str:
    existing = str(source_segment.get("id") or source_segment.get("source_segment_id") or "").strip()
    if existing:
        return existing
    start = float(source_segment.get("start") or 0)
    end = float(source_segment.get("end") or start)
    text = _clean_text(source_segment.get("text") or source_segment.get("source_sentence") or "")
    return legacy_worker.source_segment_key(start, end, text)


def learning_action_key(point: dict[str, Any]) -> str:
    kind = str(point.get("candidate_kind") or TYPE_TO_CANDIDATE_KIND.get(str(point.get("type") or ""), "expression"))
    answer = legacy_worker.normalized_phrase_key(
        str(point.get("normalized_answer") or point.get("answer_core") or point.get("exact_span") or "")
    )
    action = legacy_worker.normalized_phrase_key(str(point.get("learning_action") or point.get("reason") or ""))
    if action:
        action = re.sub(r"\b(训练|掌握|理解|使用|表达|识别|听辨)\b", "", action, flags=re.IGNORECASE).strip()
    return ":".join(part for part in [kind, answer, action[:48]] if part)


def learning_point_id(source_segment: dict[str, Any], point: dict[str, Any]) -> str:
    source_id = _source_id(source_segment)
    key = learning_action_key(point) or _clean_text(point.get("answer_core") or point.get("exact_span"))
    return f"lp_{_stable_hash(f'{source_id}:{key}')}"


def repair_learning_point_if_safe(point: dict[str, Any], source_segment: dict[str, Any]) -> dict[str, Any]:
    repaired = dict(point)
    source_sentence = _clean_text(source_segment.get("text") or source_segment.get("source_sentence") or "")
    exact_span = _clean_text(repaired.get("exact_span") or repaired.get("answer_core") or repaired.get("phrase") or "")
    if exact_span and not legacy_worker.phrase_in_text(source_sentence, exact_span):
        match = re.search(re.escape(exact_span), source_sentence, re.IGNORECASE)
        if match:
            repaired["exact_span"] = source_sentence[match.start() : match.end()]
            repaired.setdefault("repair_history", []).append(
                {"field": "exact_span", "action": "normalized", "reason": "按原句大小写修正 exact_span。"}
            )
    if not _clean_text(repaired.get("answer_core")):
        repaired["answer_core"] = repaired.get("normalized_answer") or repaired.get("exact_span") or repaired.get("phrase") or ""
        repaired.setdefault("repair_history", []).append(
            {"field": "answer_core", "action": "repaired", "reason": "用原句学习点回填 answer_core。"}
        )
    return repaired


def validate_learning_point_contract(point: dict[str, Any], source_segment: dict[str, Any]) -> tuple[bool, list[str]]:
    source_sentence = _clean_text(source_segment.get("text") or source_segment.get("source_sentence") or "")
    is_valid, reason, _ = legacy_worker.sanitize_learning_point_contract(
        dict(point),
        source_sentence,
        language=source_segment.get("language") or point.get("language") or "en",
    )
    return is_valid, [] if is_valid else [reason]


def normalize_learning_point(raw: dict[str, Any], source_segment: dict[str, Any], *, source: str) -> dict[str, Any]:
    source_sentence = _clean_text(source_segment.get("text") or source_segment.get("source_sentence") or "")
    candidate_kind = legacy_worker.normalize_candidate_kind(
        raw.get("candidate_kind") or TYPE_TO_CANDIDATE_KIND.get(str(raw.get("type") or ""), "expression")
    )
    point_type = str(raw.get("type") or CANDIDATE_KIND_TO_TYPE.get(candidate_kind, "phrase"))
    if point_type not in ALLOWED_TYPES:
        point_type = CANDIDATE_KIND_TO_TYPE.get(candidate_kind, "phrase")

    candidate = repair_learning_point_if_safe(
        {
            **raw,
            "candidate_kind": candidate_kind,
            "kind": candidate_kind,
            "type": point_type,
            "phrase_type": raw.get("phrase_type") or legacy_worker.phrase_type_for_candidate_kind(candidate_kind),
            "source": "local" if source in {"local", "local_rule"} else "model",
        },
        source_segment,
    )
    is_valid, reason, normalized = legacy_worker.sanitize_learning_point_contract(
        candidate,
        source_sentence,
        language=source_segment.get("language") or candidate.get("language") or "en",
    )

    short_spoken_allowlist = {"just"}
    allow_discourse_marker = (
        candidate_kind == "expression"
        and str(candidate.get("phrase_type") or "") == "discourse_marker"
        and legacy_worker.normalized_phrase_key(str(candidate.get("answer_core") or candidate.get("exact_span") or ""))
        in short_spoken_allowlist
    )
    if not is_valid and (candidate_kind in {"grammar_pattern", "listening_feature", "pragmatic_risk"} or allow_discourse_marker):
        exact_span = legacy_worker.normalize_candidate_span(candidate.get("exact_span") or "")
        answer_core = legacy_worker.answer_display_text(candidate.get("answer_core") or candidate.get("normalized_answer") or exact_span)
        safe_target = (
            exact_span
            and legacy_worker.phrase_in_text(source_sentence, exact_span)
            and legacy_worker.looks_like_target_language_text(answer_core or exact_span, source_segment.get("language") or candidate.get("language") or "en")
            and not legacy_worker.has_cjk(answer_core)
            and not re.search(r"/[^/]{1,80}/|[\u0250-\u02af]", answer_core)
        )
        if safe_target:
            span_start, span_end = legacy_worker.exact_span_offsets(source_sentence, exact_span)
            normalized = {
                **candidate,
                "exact_span": exact_span,
                "answer_core": answer_core or exact_span,
                "normalized_answer": legacy_worker.answer_display_text(candidate.get("normalized_answer")) or answer_core or exact_span,
                "kind": candidate_kind,
                "candidate_kind": candidate_kind,
                "phrase_type": candidate.get("phrase_type") or legacy_worker.phrase_type_for_candidate_kind(candidate_kind),
                "content_kind": legacy_worker.content_kind_for_phrase_type(
                    candidate.get("phrase_type") or legacy_worker.phrase_type_for_candidate_kind(candidate_kind)
                ),
                "language": legacy_worker.normalize_learning_language(source_segment.get("language") or candidate.get("language") or "en"),
                "learning_action": _clean_text(
                    candidate.get("learning_action")
                    or candidate.get("reason")
                    or "训练这个原句中的可迁移语言功能。"
                ),
                "source": "repaired",
                "confidence": "medium",
                "validation_status": "repaired",
                "validation_issues": [reason],
                "repair_history": [
                    *([*candidate.get("repair_history")] if isinstance(candidate.get("repair_history"), list) else []),
                    {"field": "answer_core", "action": "downgraded", "reason": "按学习点类型放宽短语式校验。"},
                ],
            }
            if span_start is not None and span_end is not None:
                normalized["exact_span_start"] = span_start
                normalized["exact_span_end"] = span_end
            is_valid = True

    if not is_valid:
        blocked = {
            **candidate,
            "id": str(candidate.get("id") or learning_point_id(source_segment, candidate)),
            "source_segment_id": _source_id(source_segment),
            "source_sentence": source_sentence,
            "source_time": str(source_segment.get("source_time") or ""),
            "type": point_type,
            "candidate_kind": candidate_kind,
            "status": "hard_blocked",
            "status_reason": reason,
            "validation_status": "hard_blocked",
            "validation_issues": [reason],
            "source": source,
        }
        return blocked

    point = {
        **normalized,
        "id": str(normalized.get("id") or learning_point_id(source_segment, normalized)),
        "source_segment_id": _source_id(source_segment),
        "source_sentence": source_sentence,
        "source_time": str(source_segment.get("source_time") or ""),
        "start": source_segment.get("start"),
        "end": source_segment.get("end"),
        "type": point_type,
        "candidate_kind": candidate_kind,
        "source": source,
        "status": "candidate_only",
        "status_reason": "",
    }
    point["learning_action_key"] = str(point.get("learning_action_key") or learning_action_key(point))
    point.setdefault("validation_issues", [])
    point.setdefault("repair_history", [])
    return point
