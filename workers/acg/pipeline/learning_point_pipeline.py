from __future__ import annotations

import time
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from acg import legacy_worker
from acg.classification.leveling import estimate_learning_point_level
from acg.contracts.learning_point import learning_action_key, normalize_learning_point
from acg.generation_timing import add_learning_point_extraction_timing_aliases
from acg.learning_types import normalize_candidate_kind, phrase_type_for_candidate_kind
from acg.media_alignment import (
    clean_candidate_text as media_clean_candidate_text,
    looks_complete_sentence as media_looks_complete_sentence,
    merge_subtitle_parts as media_merge_subtitle_parts,
)
from acg.protocol import emit_progress, fail
from acg.recall.local_learning_points import recall_local_learning_points
from acg.scoring.learning_value import assign_learning_point_status, score_learning_point
from acg.subtitles.core import Cue
from acg.subtitles.sentences import (
    SOURCE_SENTENCE_QUALITY_DEMOTE_FLAGS,
    apply_source_sentence_quality_gate,
    sentence_quality_counts,
    source_sentences_from_cues as build_source_sentences_from_cues,
)


AI_REVIEW_BATCH_SIZE = 16
AI_REVIEW_PROMPT_VERSION = 2
AI_REVIEW_DEFAULT_CONCURRENCY = 2
AI_REVIEW_MAX_CONCURRENCY = 4
AI_REVIEW_DISCOVERY_BUDGET_TRIGGER = 160
AI_REVIEW_DEFAULT_DISCOVERY_SOURCE_BUDGET = 64


class AIReviewPayloadError(ValueError):
    def __init__(self, message: str, *, error_code: str = "MODEL_REVIEW_BAD_JSON", retryable: bool = True) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.retryable = retryable


def _model_label(payload: dict[str, Any]) -> str:
    api = payload.get("api_config") or {}
    provider = str(api.get("provider") or "local")
    model = str(api.get("model") or "")
    return f"{provider} · {model}".strip(" ·")


def _ai_review_batch_percent(batch_index: int | str, total_batches: int) -> int:
    try:
        numeric_index = int(str(batch_index).split(".", 1)[0])
    except ValueError:
        numeric_index = 1
    return min(70, 52 + int((max(1, numeric_index) - 1) / max(1, total_batches) * 18))


def _ensure_ai_review_available(payload: dict[str, Any]) -> None:
    api = payload.get("api_config") or {}
    if not legacy_worker.phrase_review_available(payload):
        provider = str(api.get("provider") or "local")
        model = str(api.get("model") or "")
        if provider == "local":
            message = "学习点正式抽取需要先配置并测试模型 API，不能使用预览模式。"
        elif not model:
            message = "学习点正式抽取需要模型名，请先在“模型 API”里保存并测试连接。"
        else:
            message = "学习点正式抽取需要可用的模型 API。请先在“模型 API”里测试连接。"
        fail(message, error_code="MODEL_API_REQUIRED", stage="model_api", retryable=True)


def _ai_review_concurrency(payload: dict[str, Any], total_batches: int) -> int:
    api = payload.get("api_config") or {}
    raw_value = payload.get("ai_review_concurrency") or api.get("ai_review_concurrency") or AI_REVIEW_DEFAULT_CONCURRENCY
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        value = AI_REVIEW_DEFAULT_CONCURRENCY
    return max(1, min(AI_REVIEW_MAX_CONCURRENCY, value, max(1, total_batches)))


def _new_ai_review_stats() -> dict[str, Any]:
    return {
        "lock": threading.Lock(),
        "hits": 0,
        "misses": 0,
        "timing_ms": {},
    }


def _record_ai_review_cache_stat(payload: dict[str, Any], stats: dict[str, Any] | None, field: str) -> None:
    payload_key = f"_ai_review_cache_{field}"
    if stats is None:
        payload[payload_key] = int(payload.get(payload_key) or 0) + 1
        return
    lock = stats.get("lock")
    if lock is None:
        payload[payload_key] = int(payload.get(payload_key) or 0) + 1
        return
    with lock:
        stats[field] = int(stats.get(field) or 0) + 1
        payload[payload_key] = int(stats[field])


def _record_ai_review_timing(stats: dict[str, Any] | None, batch_index: int, duration_ms: int) -> None:
    if stats is None:
        return
    lock = stats.get("lock")
    if lock is None:
        stats.setdefault("timing_ms", {})[str(batch_index)] = duration_ms
        return
    with lock:
        stats.setdefault("timing_ms", {})[str(batch_index)] = duration_ms


def _points_for_source(points: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for point in points:
        grouped.setdefault(str(point.get("source_segment_id") or ""), []).append(point)
    return grouped


def _ciba_tianxia_learning_point_review_instruction() -> str:
    return (
        "词霸天下实验 V1 额外精筛规则："
        "你现在不是按传统单词表制卡，而是筛选“真实语言动作”。"
        "优先推荐能训练为说而思考的学习点：词块、搭配边界、语境义、概念视角、真实听辨、语气风险和可替换句型。"
        "不要因为某个点看似基础就直接 reject；如果它在真实口语中有高频迁移价值、听辨价值或容易误用，应至少保留为 candidate。"
        "推荐优先级从高到低："
        "1) 2-6 个词的可复用词块/搭配/短语动词；"
        "2) 单词在本句里的语境义、角色义或搭配对象；"
        "3) 能迁移到其他句子的句型框架或概念视角；"
        "4) 真实听辨点，包括弱读、连读、缩读、吞音或重音；"
        "5) 语气、冒犯风险、正式度和使用边界。"
        "降低优先级：主题名、专有名词堆叠、离开原句无法训练的碎片、过长整句、泛泛的 talk about/do something/good thing。"
        "如果同一句里同时存在 register 的语境义、run the register 的搭配、以及 gonna 的听辨点，三者训练动作不同，可以共存。"
        "learning_action 必须写清楚训练动作，例如“训练 run + the register 表示负责收银的搭配”，不要写“学习这个表达”。"
        "reason/status_reason 要解释为什么推荐或为什么仅候选，尤其说明搭配边界、语境义或听辨证据。"
    )


def _build_ai_learning_point_review_prompt(
    payload: dict[str, Any],
    source_batch: list[dict[str, Any]],
    local_by_source: dict[str, list[dict[str, Any]]],
) -> str:
    level = str(payload.get("level") or "B1")
    language = legacy_worker.normalize_learning_language(payload.get("language", "en"))
    compact = []
    for source in source_batch:
        source_id = str(source.get("source_segment_id") or source.get("id") or "")
        local_candidates = []
        for point in local_by_source.get(source_id, []):
            if str(point.get("validation_status") or "") == "hard_blocked":
                continue
            local_candidates.append(
                {
                    "id": point.get("id"),
                    "type": point.get("type"),
                    "candidate_kind": point.get("candidate_kind"),
                    "phrase_type": point.get("phrase_type"),
                    "exact_span": point.get("exact_span"),
                    "answer_core": point.get("answer_core"),
                    "normalized_answer": point.get("normalized_answer"),
                    "learning_action": point.get("learning_action"),
                    "local_value_score": point.get("value_score"),
                    "local_level": point.get("level") or point.get("estimated_level"),
                }
            )
        compact.append(
            {
                "source_segment_id": source_id,
                "source_time": source.get("source_time"),
                "previous_sentence": source.get("previous_sentence") or "",
                "sentence": source.get("source_sentence") or source.get("text"),
                "next_sentence": source.get("next_sentence") or "",
                "local_candidates": local_candidates,
            }
        )
    prompt = (
        "你是中文母语者的多语言 Anki 学习点精筛老师。"
        "请根据字幕原句、上下文和本地候选，评审哪些学习点值得进入用户选择列表，并补充明显遗漏的学习点。"
        "不要生成完整卡片内容。"
        "硬规则："
        "1) exact_span 必须连续出现在 sentence 中，answer_core 只能是目标语言答案本体。"
        "2) 禁止把中文解释、IPA、发音说明、语法说明写进 answer_core。"
        "3) 对每个 local_candidate 必须给一个 review，decision 只能是 recommend/candidate/reject/duplicate。"
        "4) 即使 local_candidates 为空，也必须判断 sentence 中是否有值得学的词伙、单词语境义、语法框架、听力点或语气风险；没有就返回空 reviews 和空 new_learning_points。"
        "5) 每个输入 source_segment_id 都必须返回一个 sources 项。"
        "6) recommend 是默认勾选的高价值学习点；candidate 是合法但不默认勾选；reject/duplicate 只进诊断。"
        "7) 可以在 new_learning_points 里补充本地漏掉的不同训练动作。"
        "8) 同一句里词伙、单词语境义、语法框架、听力点、语气风险可以共存，但训练动作重复必须 duplicate。"
        "9) 用户水平只影响推荐优先级，不作为硬过滤。"
        "10) value_score 1-5；4-5 通常 recommend，3 通常 candidate，1-2 reject。"
        "11) estimated_level 用 A1/A2/B1/B2/C1/C2。"
        "12) recommend 必须通过迁移测试：学习者能把 answer_core 放进另一个新句子里使用；主题名、纯名词块、专有名词堆叠或离开原句没有训练动作的片段只能 candidate/reject。"
        "13) 如果字幕疑似缺词、自动字幕拼接或语法明显不自然（例如 have break 而不是 have a break），不要 recommend；只能 candidate 并在 status_reason 提醒复查。"
        "14) 优先推荐 2-6 词的可复用词伙、搭配、短语动词、句型框架、真实听辨或语气风险；不要为了凑数量推荐低价值表达。"
        "只返回严格 JSON，不要 Markdown。结构："
        '{"sources":[{"source_segment_id":"src","reviews":[{'
        '"id":"local id","decision":"recommend|candidate|reject|duplicate","value_score":4,'
        '"estimated_level":"B1","exact_span":"原句连续片段","answer_core":"答案本体",'
        '"normalized_answer":"标准化答案","candidate_kind":"expression|contextual_vocab|grammar_pattern|listening_feature|pragmatic_risk",'
        '"phrase_type":"spoken_phrase|sentence_frame|collocation|discourse_marker|idiom|listening_sentence|vocabulary_usage|grammar_pattern",'
        '"learning_action":"中文短句说明训练什么","reason":"为什么这样判断","status_reason":"给用户看的状态原因"}],'
        '"new_learning_points":[{"decision":"recommend|candidate","value_score":4,"estimated_level":"B1",'
        '"exact_span":"原句连续片段","answer_core":"答案本体","normalized_answer":"标准化答案",'
        '"candidate_kind":"expression|contextual_vocab|grammar_pattern|listening_feature|pragmatic_risk",'
        '"phrase_type":"spoken_phrase|sentence_frame|collocation|discourse_marker|idiom|listening_sentence|vocabulary_usage|grammar_pattern",'
        '"learning_action":"中文短句说明训练什么","reason":"为什么值得补充","status_reason":"给用户看的状态原因"}]}]}。'
        f"\n学习语言代码：{language}。用户当前水平：{level}。"
        f"\n字幕和候选_JSON_START\n{json.dumps(compact, ensure_ascii=False)}"
    )
    if legacy_worker.ciba_tianxia_mode(payload):
        prompt = prompt.replace(
            "只返回严格 JSON，不要 Markdown。结构：",
            _ciba_tianxia_learning_point_review_instruction() + "只返回严格 JSON，不要 Markdown。结构：",
        )
    return prompt


def _ai_review_cache_path(
    payload: dict[str, Any],
    source_batch: list[dict[str, Any]],
    local_by_source: dict[str, list[dict[str, Any]]],
) -> tuple[Path, str]:
    api = payload.get("api_config") or {}
    cache_namespace = str(payload.get("ai_review_cache_namespace") or api.get("ai_review_cache_namespace") or "").strip()
    batch_fingerprint: list[dict[str, Any]] = []
    for source in source_batch:
        source_id = str(source.get("source_segment_id") or source.get("id") or "")
        batch_fingerprint.append(
            {
                "id": source_id,
                "sentence": str(source.get("source_sentence") or source.get("text") or ""),
                "previous": str(source.get("previous_sentence") or ""),
                "next": str(source.get("next_sentence") or ""),
                "local_candidates": [
                    {
                        "id": str(point.get("id") or ""),
                        "exact_span": str(point.get("exact_span") or ""),
                        "answer_core": str(point.get("answer_core") or ""),
                        "candidate_kind": str(point.get("candidate_kind") or ""),
                        "learning_action_key": str(point.get("learning_action_key") or ""),
                    }
                    for point in local_by_source.get(source_id, [])
                    if str(point.get("validation_status") or "") != "hard_blocked"
                ],
            }
        )
    cache_key_payload = {
        "version": AI_REVIEW_PROMPT_VERSION,
        "kind": "learning_point_ai_review",
        "language": legacy_worker.normalize_learning_language(payload.get("language", "en")),
        "level_mode": legacy_worker.normalized_level_mode(payload),
        "level": str(payload.get("level") or "B1"),
        "study_depth": str(payload.get("study_depth") or ""),
        "language_focus": payload.get("language_focus") or [],
        "provider": legacy_worker.provider_name(api),
        "base_url": str(api.get("base_url") or "").strip().rstrip("/"),
        "model": str(api.get("model") or "").strip(),
        "prompt_version": AI_REVIEW_PROMPT_VERSION,
        "batch": batch_fingerprint,
    }
    if cache_namespace:
        cache_key_payload["cache_namespace"] = cache_namespace
    cache_key = legacy_worker.stable_cache_key(cache_key_payload)
    return legacy_worker.persistent_cache_root() / "learning_point_review" / f"{cache_key}.json", cache_key


def _load_ai_review_cache(cache_path: Path) -> dict[str, Any] | None:
    if not cache_path.exists() or cache_path.stat().st_size <= 0:
        return None
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    payload = cached.get("payload") if isinstance(cached, dict) else None
    return payload if isinstance(payload, dict) else None


def _store_ai_review_cache(cache_path: Path, cache_key: str, ai_payload: dict[str, Any]) -> None:
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


def _ai_review_cache_disabled(payload: dict[str, Any], api: dict[str, Any], field: str) -> bool:
    legacy_disabled = bool(payload.get("disable_ai_review_cache") or api.get("disable_ai_review_cache"))
    return legacy_disabled or bool(payload.get(field) or api.get(field))


def _ai_review_cache_policy(payload: dict[str, Any], api: dict[str, Any]) -> tuple[bool, bool]:
    read_disabled = _ai_review_cache_disabled(payload, api, "disable_ai_review_cache_read")
    write_disabled = _ai_review_cache_disabled(payload, api, "disable_ai_review_cache_write")
    read_enabled = bool(payload.get("reuse_ai_review_cache") or api.get("reuse_ai_review_cache")) and not read_disabled
    return read_enabled, not write_disabled


def _call_ai_learning_point_review_batch(
    payload: dict[str, Any],
    source_batch: list[dict[str, Any]],
    local_by_source: dict[str, list[dict[str, Any]]],
    *,
    batch_index: int | str,
    total_batches: int,
    stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    api = payload.get("api_config") or {}
    percent = _ai_review_batch_percent(batch_index, total_batches)
    batch_label = str(batch_index)
    cache_path, cache_key = _ai_review_cache_path(payload, source_batch, local_by_source)
    cache_read_enabled, cache_write_enabled = _ai_review_cache_policy(payload, api)
    payload["_ai_review_cache_read_enabled"] = cache_read_enabled
    payload["_ai_review_cache_write_enabled"] = cache_write_enabled
    if cache_read_enabled:
        cached_payload = _load_ai_review_cache(cache_path)
        if cached_payload is not None:
            _record_ai_review_cache_stat(payload, stats, "hits")
            emit_progress(
                "extract_learning_points",
                "ai_review",
                percent,
                f"AI 精筛缓存命中：第 {batch_label}/{total_batches} 批 · {cache_key[:8]}。",
            )
            return cached_payload
    _record_ai_review_cache_stat(payload, stats, "misses")
    emit_progress(
        "extract_learning_points",
        "ai_review",
        percent,
        f"AI 正在精筛学习点：第 {batch_label}/{total_batches} 批 · {_model_label(payload)}。本地候选只是待审学习点，不会直接制卡。",
    )
    prompt = _build_ai_learning_point_review_prompt(payload, source_batch, local_by_source)
    if legacy_worker.is_gemini_vertex_config(api):
        content = legacy_worker.gemini_vertex_generate_content(
            api,
            prompt,
            temperature=0.12,
            timeout=180 if legacy_worker.is_gemini_vertex_thinking_config(api) else 120,
            max_output_tokens=16000 if legacy_worker.is_gemini_vertex_thinking_config(api) else 8000,
        )
    elif api.get("provider") in legacy_worker.OPENAI_COMPATIBLE_PROVIDERS:
        response = legacy_worker.compatible_chat_completion(
            api,
            [
                {"role": "system", "content": "Return only valid JSON."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.12,
            timeout=180 if legacy_worker.is_thinking_model_config(api) else 120,
            max_tokens=6000,
            progress={
                "command": "extract_learning_points",
                "stage": "ai_review",
                "percent": percent,
                "message": "AI 正在精筛学习点",
            },
            work_unit_id=f"learning-point-review:{batch_label}",
        )
        content = legacy_worker.chat_completion_content(response)
    else:
        fail("当前模型 Provider 暂不支持学习点 AI 精筛。", error_code="MODEL_PROVIDER_UNSUPPORTED", stage="model_api", retryable=False)
    ai_payload = _extract_ai_review_payload(content or "")
    if cache_write_enabled:
        _store_ai_review_cache(cache_path, cache_key, ai_payload)
    return ai_payload


def _extract_ai_review_payload(content: str) -> dict[str, Any]:
    text = legacy_worker.strip_reasoning_text(content).strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].strip().startswith("```"):
            text = "\n".join(lines[1:]).strip()
        if text.endswith("```"):
            text = text[:-3].strip()
    try:
        payload = json.loads(text)
        if isinstance(payload, dict) and isinstance(payload.get("sources"), list):
            return payload
        if isinstance(payload, list):
            return {"sources": payload}
    except json.JSONDecodeError:
        pass
    try:
        payload = legacy_worker.extract_json_object(content or "")
    except ValueError as err:
        raise AIReviewPayloadError("AI 学习点精筛没有返回 sources JSON，不能用本地候选冒充正式结果。") from err
    if isinstance(payload, dict) and isinstance(payload.get("sources"), list):
        return payload
    raise AIReviewPayloadError("AI 学习点精筛没有返回 sources JSON，不能用本地候选冒充正式结果。")


def _ai_review_scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value).strip()
    if isinstance(value, dict):
        for key in ("value", "text", "label", "name", "kind", "type", "reason", "content"):
            if key in value:
                nested = _ai_review_scalar(value.get(key))
                if nested:
                    return nested
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if isinstance(value, list):
        parts = [_ai_review_scalar(item) for item in value]
        return " ".join(part for part in parts if part).strip()
    return str(value).strip()


def _sanitize_ai_review_item(item: dict[str, Any], *, source_id: str, ai_batch_id: str) -> dict[str, Any]:
    cleaned = {
        "source_segment_id": source_id,
        "ai_batch_id": ai_batch_id,
    }
    text_fields = (
        "id",
        "decision",
        "estimated_level",
        "exact_span",
        "answer_core",
        "normalized_answer",
        "candidate_kind",
        "phrase_type",
        "learning_action",
        "reason",
        "status_reason",
        "confidence",
        "level_reason",
    )
    for field in text_fields:
        if field in item:
            cleaned[field] = _ai_review_scalar(item.get(field))
    raw_score = item.get("value_score")
    try:
        cleaned["value_score"] = round(float(raw_score), 2)
    except (TypeError, ValueError):
        if "value_score" in item:
            cleaned["value_score"] = 0
    return cleaned


def _failed_ai_review_payload(source_batch: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "sources": [
            {
                "source_segment_id": str(source.get("source_segment_id") or source.get("id") or ""),
                "reviews": [],
                "new_learning_points": [],
            }
            for source in source_batch
        ]
    }


def _model_review_error_details(err: Exception) -> dict[str, Any]:
    if isinstance(err, AIReviewPayloadError):
        return {
            "message": str(err),
            "error_code": err.error_code,
            "retryable": err.retryable,
        }
    return legacy_worker.classify_service_error(err, kind="model")


def _fatal_ai_review_error(details: dict[str, Any]) -> bool:
    return str(details.get("error_code") or "") in {
        "MODEL_API_REQUIRED",
        "MODEL_AUTH_FAILED",
        "MODEL_NOT_FOUND",
        "MODEL_PROVIDER_UNSUPPORTED",
        "MODEL_QUOTA_EXCEEDED",
    }


def _call_ai_learning_point_review_batch_resilient(
    payload: dict[str, Any],
    source_batch: list[dict[str, Any]],
    local_by_source: dict[str, list[dict[str, Any]]],
    *,
    batch_index: str,
    total_batches: int,
    retry_attempt: int = 0,
    stats: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        return (
            _call_ai_learning_point_review_batch(
                payload,
                source_batch,
                local_by_source,
                batch_index=batch_index,
                total_batches=total_batches,
                stats=stats,
            ),
            [],
        )
    except Exception as err:
        if isinstance(err, SystemExit):
            raise
        details = _model_review_error_details(err)
        if _fatal_ai_review_error(details):
            fail(
                f"AI 学习点精筛第 {batch_index}/{total_batches} 批失败：{details['message']}",
                error_code=details.get("error_code") or "MODEL_REVIEW_FAILED",
                stage="ai_review",
                retryable=bool(details.get("retryable")),
            )
        should_retry = retry_attempt == 0 and (
            isinstance(err, AIReviewPayloadError) or bool(details.get("retryable", True))
        )
        if should_retry:
            emit_progress(
                "extract_learning_points",
                "ai_review",
                _ai_review_batch_percent(batch_index, total_batches),
                f"AI 精筛第 {batch_index}/{total_batches} 批返回异常，正在重试 1/1。",
            )
            return _call_ai_learning_point_review_batch_resilient(
                payload,
                source_batch,
                local_by_source,
                batch_index=batch_index,
                total_batches=total_batches,
                retry_attempt=1,
                stats=stats,
            )
        if len(source_batch) > 1:
            midpoint = max(1, len(source_batch) // 2)
            emit_progress(
                "extract_learning_points",
                "ai_review",
                _ai_review_batch_percent(batch_index, total_batches),
                f"AI 精筛第 {batch_index}/{total_batches} 批仍失败，已拆成 2 个小批继续。",
            )
            left_payload, left_errors = _call_ai_learning_point_review_batch_resilient(
                payload,
                source_batch[:midpoint],
                local_by_source,
                batch_index=f"{batch_index}.1",
                total_batches=total_batches,
                retry_attempt=1,
                stats=stats,
            )
            right_payload, right_errors = _call_ai_learning_point_review_batch_resilient(
                payload,
                source_batch[midpoint:],
                local_by_source,
                batch_index=f"{batch_index}.2",
                total_batches=total_batches,
                retry_attempt=1,
                stats=stats,
            )
            return (
                {
                    "sources": [
                        *(left_payload.get("sources") or []),
                        *(right_payload.get("sources") or []),
                    ]
                },
                [*left_errors, *right_errors],
            )
        source_ids = [str(source.get("source_segment_id") or source.get("id") or "") for source in source_batch]
        message = str(details.get("message") or "模型精筛失败。")
        emit_progress(
            "extract_learning_points",
            "ai_review",
            _ai_review_batch_percent(batch_index, total_batches),
            f"AI 精筛第 {batch_index}/{total_batches} 批失败，已转入诊断，不中断整轮任务。",
        )
        return _failed_ai_review_payload(source_batch), [
            {
                "batch": batch_index,
                "source_segment_ids": source_ids,
                "message": message,
                "error_code": details.get("error_code") or "MODEL_REVIEW_FAILED",
                "retryable": bool(details.get("retryable", True)),
            }
        ]


def _call_ai_learning_point_review(
    payload: dict[str, Any],
    source_sentences: list[dict[str, Any]],
    local_points: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    local_by_source = _points_for_source(local_points)
    reviews_by_id: dict[str, dict[str, Any]] = {}
    new_by_source: dict[str, list[dict[str, Any]]] = {}
    model_errors: list[dict[str, Any]] = []
    batches = [
        (start // AI_REVIEW_BATCH_SIZE + 1, source_sentences[start : start + AI_REVIEW_BATCH_SIZE])
        for start in range(0, len(source_sentences), AI_REVIEW_BATCH_SIZE)
    ]
    total_batches = max(1, len(batches))
    if not batches:
        payload["_ai_review_concurrency"] = 1
        payload["_ai_review_timing_ms"] = {}
        return reviews_by_id, new_by_source, model_errors

    stats = _new_ai_review_stats()
    concurrency = _ai_review_concurrency(payload, total_batches)
    payload["_ai_review_concurrency"] = concurrency
    batch_results: dict[int, tuple[dict[str, Any], list[dict[str, Any]]]] = {}

    def run_batch(batch_index: int, batch: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        started = time.perf_counter()
        try:
            return _call_ai_learning_point_review_batch_resilient(
                payload,
                batch,
                local_by_source,
                batch_index=str(batch_index),
                total_batches=total_batches,
                stats=stats,
            )
        finally:
            _record_ai_review_timing(stats, batch_index, int((time.perf_counter() - started) * 1000))

    completed_batches = 0
    if concurrency <= 1:
        for batch_index, batch in batches:
            batch_results[batch_index] = run_batch(batch_index, batch)
            completed_batches += 1
            emit_progress(
                "extract_learning_points",
                "ai_review",
                min(70, 52 + int(completed_batches / total_batches * 18)),
                f"AI 精筛已完成 {completed_batches}/{total_batches} 批。完成后会显示推荐和候选；只有用户勾选的学习点才会进入制卡。",
                completed_batches=completed_batches,
                total_batches=total_batches,
                cache_hits=int(payload.get("_ai_review_cache_hits") or 0),
                cache_misses=int(payload.get("_ai_review_cache_misses") or 0),
            )
    else:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {
                pool.submit(run_batch, batch_index, batch): batch_index
                for batch_index, batch in batches
            }
            for future in as_completed(futures):
                batch_index = futures[future]
                batch_results[batch_index] = future.result()
                completed_batches += 1
                emit_progress(
                    "extract_learning_points",
                    "ai_review",
                    min(70, 52 + int(completed_batches / total_batches * 18)),
                    f"AI 精筛已完成 {completed_batches}/{total_batches} 批。完成后会显示推荐和候选；只有用户勾选的学习点才会进入制卡。",
                    completed_batches=completed_batches,
                    total_batches=total_batches,
                    cache_hits=int(payload.get("_ai_review_cache_hits") or 0),
                    cache_misses=int(payload.get("_ai_review_cache_misses") or 0),
                )

    payload["_ai_review_timing_ms"] = dict(stats.get("timing_ms") or {})
    for batch_index in sorted(batch_results):
        ai_payload, batch_errors = batch_results[batch_index]
        model_errors.extend(batch_errors)
        for source in ai_payload.get("sources", []) if isinstance(ai_payload, dict) else []:
            if not isinstance(source, dict):
                continue
            source_id = str(source.get("source_segment_id") or "").strip()
            for review in source.get("reviews", []) or []:
                if isinstance(review, dict) and review.get("id"):
                    safe_review = _sanitize_ai_review_item(review, source_id=source_id, ai_batch_id=f"ai_review_{batch_index}")
                    if safe_review.get("id"):
                        reviews_by_id[str(safe_review["id"])] = safe_review
            additions = source.get("new_learning_points") or source.get("learning_points") or []
            if source_id and isinstance(additions, list):
                new_by_source.setdefault(source_id, []).extend(
                    _sanitize_ai_review_item(item, source_id=source_id, ai_batch_id=f"ai_review_{batch_index}")
                    for item in additions
                    if isinstance(item, dict)
                )
    return reviews_by_id, new_by_source, model_errors


def source_sentences_from_cues(cues: list[Cue], payload: dict[str, Any]) -> list[dict[str, Any]]:
    return build_source_sentences_from_cues(
        cues,
        language=payload.get("language", "en"),
        merge_subtitle_parts=media_merge_subtitle_parts,
        clean_candidate_text=media_clean_candidate_text,
        looks_complete_sentence=media_looks_complete_sentence,
        normalize_language=legacy_worker.normalize_learning_language,
    )


def _prepare_subtitle_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], str, dict[str, Any] | None]:
    source_mode = str(payload.get("source_mode") or "").strip().lower()
    if not source_mode:
        source_mode = "url" if str(payload.get("source_url") or "").strip() else "local"
    if source_mode == "url":
        emit_progress("extract_learning_points", "download", 12, "正在准备 URL 字幕。")
        source_info = legacy_worker.download_url_source({**payload, "skip_video_slicing": True, "url_import_mode": "subtitles"})
        subtitle_path = str(source_info.get("subtitle_path") or "")
        return {**payload, "source_mode": "url", "subtitle_path": subtitle_path, "title": payload.get("title") or source_info.get("title") or ""}, subtitle_path, source_info

    subtitle_path = legacy_worker.clean_input_path(payload.get("subtitle_path", ""))
    video_path = legacy_worker.clean_input_path(payload.get("video_path", ""))
    if video_path and (not subtitle_path or not Path(subtitle_path).exists()):
        discovered = legacy_worker.discover_local_subtitle(video_path, payload.get("language", "en"))
        if discovered:
            subtitle_path = str(discovered)
    if not subtitle_path or not Path(subtitle_path).exists():
        fail(
            f"字幕文件不存在：{subtitle_path or '未选择'}。学习点抽取需要字幕；请先选择 SRT/VTT 或让系统自动匹配同目录字幕。",
            error_code="LOCAL_SUBTITLE_MISSING",
            stage="subtitle",
            retryable=True,
        )
    return {**payload, "source_mode": source_mode or "local", "subtitle_path": subtitle_path}, subtitle_path, None


def _status_counts(points: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"recommended": 0, "candidate_only": 0, "hidden_duplicate": 0, "hard_blocked": 0}
    for point in points:
        status = str(point.get("status") or "candidate_only")
        if status in counts:
            counts[status] += 1
    return counts


def _distribution(points: list[dict[str, Any]], field: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for point in points:
        key = str(point.get(field) or "unknown")
        result[key] = result.get(key, 0) + 1
    return result


def _learning_point_duplicate_key(point: dict[str, Any]) -> str:
    answer = str(point.get("normalized_answer") or point.get("answer_core") or point.get("exact_span") or "").strip().lower()
    answer = re.sub(r"\s+", " ", answer)
    kind = str(point.get("candidate_kind") or point.get("type") or "").strip().lower()
    phrase_type = str(point.get("phrase_type") or "").strip().lower()
    action = str(point.get("learning_action_key") or learning_action_key(point)).strip().lower()
    return f"{kind}:{phrase_type}:{answer}:{action}"


def _decision_to_status(decision: Any, value_score: Any) -> str:
    normalized = str(decision or "").strip().lower()
    if normalized in {"recommend", "recommended", "keep"}:
        return "recommended"
    if normalized in {"candidate", "candidate_only", "needs_review", "review"}:
        return "candidate_only"
    if normalized in {"duplicate", "hidden_duplicate"}:
        return "hidden_duplicate"
    if normalized in {"reject", "skip", "hard_blocked"}:
        return "hard_blocked"
    try:
        score = float(value_score)
    except (TypeError, ValueError):
        score = 0
    if score >= 4:
        return "recommended"
    if score >= 3:
        return "candidate_only"
    return "hard_blocked"


def _soft_reject_reason(review: dict[str, Any]) -> bool:
    text = " ".join(
        str(review.get(key) or "")
        for key in ("reason", "status_reason", "ai_reason")
    ).lower()
    soft_markers = (
        "too basic",
        "overly basic",
        "below the user's level",
        "below current level",
        "low priority",
        "过于基础",
        "太基础",
        "低于当前水平",
        "明显低于",
        "优先级较低",
        "无需单独制卡",
    )
    return any(marker in text for marker in soft_markers)


def _status_from_ai_review(review: dict[str, Any]) -> str:
    status = _decision_to_status(review.get("decision"), review.get("value_score"))
    if status == "hard_blocked" and _soft_reject_reason(review):
        return "candidate_only"
    return status


def _with_ai_review_fields(point: dict[str, Any], review: dict[str, Any], status: str) -> dict[str, Any]:
    value_score = review.get("value_score", point.get("value_score"))
    try:
        value = round(float(value_score), 2)
    except (TypeError, ValueError):
        value = point.get("value_score") or 3
    level = str(review.get("estimated_level") or point.get("estimated_level") or point.get("level") or "")
    ai_decision = str(review.get("decision") or status)
    if status == "candidate_only" and ai_decision.lower() in {"reject", "skip", "hard_blocked"}:
        ai_decision = "candidate"
    return {
        **point,
        "status": status,
        "status_reason": str(review.get("status_reason") or review.get("reason") or point.get("status_reason") or ""),
        "reason": str(review.get("reason") or point.get("reason") or ""),
        "learning_action": str(review.get("learning_action") or point.get("learning_action") or point.get("reason") or ""),
        "value_score": value,
        "ai_value_score": value,
        "level": level or point.get("level"),
        "estimated_level": level or point.get("estimated_level"),
        "level_reason": str(review.get("level_reason") or point.get("level_reason") or ""),
        "ai_decision": ai_decision,
        "ai_reason": str(review.get("reason") or review.get("status_reason") or ""),
        "ai_batch_id": str(review.get("ai_batch_id") or ""),
        "review_source": "ai",
    }


def _reviewed_local_point(
    point: dict[str, Any],
    review: dict[str, Any],
    source_segment: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    status = _status_from_ai_review(review)
    if status in {"hard_blocked", "hidden_duplicate"}:
        return _with_ai_review_fields(point, review, status)
    merged = {
        **point,
        "exact_span": review.get("exact_span") or point.get("exact_span"),
        "answer_core": review.get("answer_core") or point.get("answer_core"),
        "normalized_answer": review.get("normalized_answer") or point.get("normalized_answer") or review.get("answer_core") or point.get("answer_core"),
        "candidate_kind": review.get("candidate_kind") or point.get("candidate_kind"),
        "phrase_type": review.get("phrase_type") or point.get("phrase_type"),
        "type": point.get("type"),
        "learning_action": review.get("learning_action") or point.get("learning_action"),
        "reason": review.get("reason") or point.get("reason"),
        "source": "model",
    }
    normalized = normalize_learning_point(merged, source_segment, source="model")
    if normalized.get("validation_status") == "hard_blocked":
        normalized["ai_decision"] = "reject"
        normalized["ai_reason"] = normalized.get("status_reason") or "AI 返回字段未通过校验。"
        normalized["ai_batch_id"] = str(review.get("ai_batch_id") or "")
        normalized["review_source"] = "ai"
        return normalized
    return _with_ai_review_fields(normalized, review, status)


def _reviewed_new_point(
    review: dict[str, Any],
    source_segment: dict[str, Any],
    payload: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    candidate_kind = normalize_candidate_kind(review.get("candidate_kind") or "expression")
    point_type = {
        "expression": "phrase",
        "contextual_vocab": "vocab_usage",
        "grammar_pattern": "grammar",
        "listening_feature": "listening",
        "pragmatic_risk": "pragmatic",
    }.get(candidate_kind, "phrase")
    normalized = normalize_learning_point(
        {
            **review,
            "id": str(review.get("id") or f"{source_segment.get('source_segment_id')}_ai_{index}"),
            "type": point_type,
            "candidate_kind": candidate_kind,
            "phrase_type": review.get("phrase_type") or phrase_type_for_candidate_kind(candidate_kind),
            "source": "model",
            "confidence": review.get("confidence") or "medium",
        },
        source_segment,
        source="model",
    )
    status = _status_from_ai_review(review)
    if normalized.get("validation_status") == "hard_blocked":
        status = "hard_blocked"
        review = {**review, "decision": "reject", "reason": normalized.get("status_reason") or review.get("reason") or ""}
    return _with_ai_review_fields(normalized, review, status)


def _source_id_for_sentence(source: dict[str, Any]) -> str:
    return str(source.get("source_segment_id") or source.get("id") or "")


TRIVIAL_REVIEW_SENTENCES = {
    "hi",
    "hey",
    "hello",
    "yeah",
    "yep",
    "yes",
    "no",
    "nope",
    "ok",
    "okay",
    "thanks",
    "thank you",
    "bye",
    "good night",
    "good morning",
}

def _apply_source_sentence_quality_gate(point: dict[str, Any]) -> dict[str, Any]:
    return apply_source_sentence_quality_gate(point)


def _reviewable_source_sentence(source: dict[str, Any], *, has_local_candidates: bool = False) -> bool:
    text = legacy_worker.clean_study_text(source.get("source_sentence") or source.get("text") or "")
    if not text:
        return False
    if has_local_candidates:
        return True
    normalized = re.sub(r"[\s.!?,;:'\"，。！？、；：]+", " ", text).strip().lower()
    if normalized in TRIVIAL_REVIEW_SENTENCES:
        return False
    tokens = re.findall(r"[A-Za-zÀ-ÿА-Яа-яЁё\u3040-\u30ff\u4e00-\u9fff]+", text)
    if not tokens:
        return False
    # Single-token interjections and pure names are usually not worth an AI review pass unless local recall found a seed.
    if len(tokens) == 1 and len(tokens[0]) <= 3:
        return False
    return True


def _ai_review_discovery_budget(payload: dict[str, Any], source_count: int, discovery_source_count: int) -> int:
    api = payload.get("api_config") or {}
    raw_value = (
        payload.get("ai_review_discovery_source_budget")
        or payload.get("learning_point_discovery_source_budget")
        or api.get("ai_review_discovery_source_budget")
        or 0
    )
    try:
        explicit_value = int(raw_value)
    except (TypeError, ValueError):
        explicit_value = 0
    if explicit_value > 0:
        return max(0, explicit_value)
    if source_count < AI_REVIEW_DISCOVERY_BUDGET_TRIGGER:
        return discovery_source_count
    return min(discovery_source_count, AI_REVIEW_DEFAULT_DISCOVERY_SOURCE_BUDGET)


def _discovery_source_score(source: dict[str, Any]) -> tuple[int, int, int]:
    text = legacy_worker.clean_study_text(source.get("source_sentence") or source.get("text") or "")
    words = re.findall(r"[A-Za-zÀ-ÿА-Яа-яЁё\u3040-\u30ff\u4e00-\u9fff]+", text)
    flags = {str(flag) for flag in source.get("source_sentence_quality_flags") or []}
    quality_score = 0 if flags & SOURCE_SENTENCE_QUALITY_DEMOTE_FLAGS else 3
    length_score = 2 if 5 <= len(words) <= 22 else (1 if 3 <= len(words) <= 30 else 0)
    punctuation_score = 1 if re.search(r"[.?!][\"'”’)]*$", text.strip()) else 0
    return quality_score, length_score, punctuation_score


def _select_representative_discovery_sources(
    sources: list[dict[str, Any]],
    budget: int,
) -> list[dict[str, Any]]:
    if budget <= 0:
        return []
    if len(sources) <= budget:
        return sources

    selected: dict[str, dict[str, Any]] = {}
    total = len(sources)
    for slot in range(budget):
        start = int(slot * total / budget)
        end = int((slot + 1) * total / budget)
        bucket = sources[start : max(start + 1, end)]
        center = start + (len(bucket) - 1) / 2
        best_offset, best_source = max(
            enumerate(bucket),
            key=lambda item: (*_discovery_source_score(item[1]), -abs((start + item[0]) - center)),
        )
        source_id = _source_id_for_sentence(best_source) or f"discovery-{start + best_offset}"
        selected[source_id] = best_source

    selected_ids = set(selected)
    return [source for source in sources if (_source_id_for_sentence(source) or "") in selected_ids]


def _ai_review_source_sentences(
    payload: dict[str, Any],
    source_sentences: list[dict[str, Any]],
    local_points: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    valid_by_source: dict[str, float] = {}
    for point in local_points:
        if point.get("validation_status") == "hard_blocked":
            continue
        source_id = str(point.get("source_segment_id") or "")
        if not source_id:
            continue
        try:
            score = float(point.get("value_score") or 0)
        except (TypeError, ValueError):
            score = 0.0
        valid_by_source[source_id] = max(valid_by_source.get(source_id, 0.0), score)

    reviewable_sources = [
        source
        for source in source_sentences
        if _reviewable_source_sentence(source, has_local_candidates=_source_id_for_sentence(source) in valid_by_source)
    ]
    local_candidate_sources = [
        source
        for source in reviewable_sources
        if _source_id_for_sentence(source) in valid_by_source
    ]
    discovery_sources = [
        source
        for source in reviewable_sources
        if _source_id_for_sentence(source) not in valid_by_source
    ]
    try:
        explicit_budget = int(
            payload.get("ai_review_source_budget")
            or payload.get("learning_point_review_budget")
            or payload.get("max_ai_review_source_sentences")
            or 0
        )
    except (TypeError, ValueError):
        explicit_budget = 0
    if explicit_budget > 0 and len(reviewable_sources) > explicit_budget:
        ranked = sorted(
            reviewable_sources,
            key=lambda source: (
                -valid_by_source.get(_source_id_for_sentence(source), 0.0),
                float(source.get("start") or 0),
            ),
        )[: max(3, explicit_budget)]
        selected_ids = {_source_id_for_sentence(source) for source in ranked}
        review_sources = [source for source in reviewable_sources if _source_id_for_sentence(source) in selected_ids]
        payload["_ai_review_local_candidate_source_count"] = len(
            [source for source in review_sources if _source_id_for_sentence(source) in valid_by_source]
        )
        payload["_ai_review_discovery_source_count"] = len(review_sources) - int(payload["_ai_review_local_candidate_source_count"])
        payload["_ai_review_discovery_source_budget"] = explicit_budget
        payload["_ai_review_discovery_source_deferred_count"] = max(0, len(reviewable_sources) - len(review_sources))
        return review_sources

    discovery_budget = _ai_review_discovery_budget(payload, len(source_sentences), len(discovery_sources))
    selected_discovery_sources = _select_representative_discovery_sources(discovery_sources, discovery_budget)
    selected_discovery_ids = {_source_id_for_sentence(source) for source in selected_discovery_sources}
    local_candidate_ids = {_source_id_for_sentence(source) for source in local_candidate_sources}
    review_sources = [
        source
        for source in reviewable_sources
        if _source_id_for_sentence(source) in local_candidate_ids or _source_id_for_sentence(source) in selected_discovery_ids
    ]
    payload["_ai_review_local_candidate_source_count"] = len(local_candidate_sources)
    payload["_ai_review_discovery_source_count"] = len(selected_discovery_sources)
    payload["_ai_review_discovery_source_budget"] = discovery_budget
    payload["_ai_review_discovery_source_deferred_count"] = max(0, len(discovery_sources) - len(selected_discovery_sources))
    return review_sources


def _apply_ai_learning_point_reviews(
    payload: dict[str, Any],
    source_sentences: list[dict[str, Any]],
    review_source_sentences: list[dict[str, Any]],
    local_points: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    reviews_by_id, new_by_source, model_errors = _call_ai_learning_point_review(payload, review_source_sentences, local_points)
    source_by_id = {str(source.get("source_segment_id") or source.get("id")): source for source in source_sentences}
    reviewed_source_ids = {str(source.get("source_segment_id") or source.get("id")) for source in review_source_sentences}
    failed_source_reasons: dict[str, str] = {}
    for error in model_errors:
        message = str(error.get("message") or "该句所在 AI 精筛批次失败。")
        for source_id in error.get("source_segment_ids") or []:
            failed_source_reasons[str(source_id)] = message
    reviewed_ids: set[str] = set()
    points: list[dict[str, Any]] = []
    for point in local_points:
        point_id = str(point.get("id") or "")
        review = reviews_by_id.get(point_id)
        source_id = str(point.get("source_segment_id") or "")
        source = source_by_id.get(source_id)
        if not source:
            next_point = {
                **point,
                "status": "hard_blocked",
                "status_reason": "缺少对应原句，无法进行 AI 精筛。",
                "ai_decision": "reject",
                "review_source": "local_seed",
            }
            points.append(next_point)
            continue
        if point.get("validation_status") == "hard_blocked":
            points.append({**point, "review_source": "local_seed", "ai_decision": "local_hard_blocked"})
            continue
        if not review:
            if source_id not in reviewed_source_ids:
                points.append(
                    {
                        **point,
                        "status": "hard_blocked",
                        "status_reason": "超出本轮 AI 精筛预算，未作为正式学习点展示。调大学习点预算后可重新抽取。",
                        "ai_decision": "ai_review_budget_deferred",
                        "review_source": "local_seed",
                    }
                )
                continue
            failed_reason = failed_source_reasons.get(source_id)
            points.append(
                {
                    **point,
                    "status": "hard_blocked",
                    "status_reason": failed_reason
                    or "AI 精筛没有返回这个本地候选，未作为正式学习点展示。",
                    "ai_decision": "model_batch_failed" if failed_reason else "missing_review",
                    "review_source": "local_seed",
                }
            )
            continue
        reviewed_ids.add(point_id)
        points.append(_reviewed_local_point(point, review, source, payload))

    for source_id, additions in new_by_source.items():
        source = source_by_id.get(source_id)
        if not source:
            continue
        for index, review in enumerate(additions, start=1):
            points.append(_reviewed_new_point(review, source, payload, index))
    return points, model_errors


def extract_learning_points_from_subtitles(payload: dict[str, Any], cues: list[Cue] | None = None) -> dict[str, Any]:
    timing_started = time.perf_counter()
    source_started = timing_started
    timing_ms: dict[str, int] = {}
    payload = {**payload, "language": legacy_worker.normalize_learning_language(payload.get("language", "en"))}
    _ensure_ai_review_available(payload)
    emit_progress("extract_learning_points", "source", 5, "正在准备字幕学习点抽取。")
    source_info = None
    if cues is None:
        payload, subtitle_path, source_info = _prepare_subtitle_payload(payload)
        emit_progress("extract_learning_points", "subtitle", 25, "正在解析字幕。")
        cues = legacy_worker.parse_srt(subtitle_path)
    else:
        subtitle_path = legacy_worker.clean_input_path(payload.get("subtitle_path", ""))

    timing_ms["source_prepare"] = int((time.perf_counter() - source_started) * 1000)
    extract_started = time.perf_counter()
    emit_progress("extract_learning_points", "sentences", 36, "正在把字幕整理成可分析句子。")
    source_sentences = source_sentences_from_cues(cues, payload)
    user_level = str(payload.get("level") or "B1")
    raw_points: list[dict[str, Any]] = []
    emit_progress("extract_learning_points", "local_recall", 48, f"正在本地召回学习点：{len(source_sentences)} 个句子。")
    for source_sentence in source_sentences:
        for raw in recall_local_learning_points(source_sentence, payload):
            raw_points.append(normalize_learning_point(raw, source_sentence, source=str(raw.get("source") or "local_rule")))

    local_candidate_count = len(raw_points)
    review_source_sentences = _ai_review_source_sentences(payload, source_sentences, raw_points)
    valid_local_candidate_count = len([point for point in raw_points if point.get("validation_status") != "hard_blocked"])
    timing_ms["learning_point_extract"] = int((time.perf_counter() - extract_started) * 1000)
    deferred_discovery_count = int(payload.get("_ai_review_discovery_source_deferred_count") or 0)
    discovery_note = (
        f" 长字幕已抽样普通句，跳过 {deferred_discovery_count} 个无本地候选的普通句。"
        if deferred_discovery_count > 0
        else ""
    )
    emit_progress(
        "extract_learning_points",
        "ai_review",
        50,
        f"本地召回 {local_candidate_count} 个待审候选（不是卡片数），AI 将扫描 {len(review_source_sentences)}/{len(source_sentences)} 句字幕。{discovery_note}",
    )
    ai_review_started = time.perf_counter()
    points, model_errors = _apply_ai_learning_point_reviews(payload, source_sentences, review_source_sentences, raw_points)
    timing_ms["ai_review"] = int((time.perf_counter() - ai_review_started) * 1000)

    seen: dict[str, dict[str, Any]] = {}
    deduped_points: list[dict[str, Any]] = []
    postprocess_started = time.perf_counter()
    emit_progress("extract_learning_points", "classify", 72, f"正在整理 AI 精筛结果：{len(points)} 个学习点。")
    for point in points:
        if point.get("validation_status") != "hard_blocked":
            if not point.get("level") or not point.get("estimated_level"):
                level, level_reason = estimate_learning_point_level(point, point, payload)
                point["level"] = level
                point["estimated_level"] = level
                point["level_reason"] = level_reason
            score = score_learning_point(point, user_level, payload)
            point.update(score)
            point["learning_action_key"] = str(point.get("learning_action_key") or learning_action_key(point))
            current_status = str(point.get("status") or "")
            demotion_flags = {
                "answer_not_locatable",
                "low_transfer_answer",
                "answer_too_long",
                "answer_not_clean_target",
                "weak_noun_chunk",
                "asr_grammar_suspect",
                "source_sentence_needs_review",
                "vague_learning_action",
            }
            should_recompute_status = current_status not in {"recommended", "candidate_only", "hidden_duplicate", "hard_blocked"}
            if current_status == "recommended" and set(point.get("recommendation_flags") or []) & demotion_flags:
                should_recompute_status = True
            if should_recompute_status:
                status, status_reason = assign_learning_point_status(point, user_level, payload)
                point["status"] = status
                point["status_reason"] = status_reason
            point = _apply_source_sentence_quality_gate(point)
        key = _learning_point_duplicate_key(point)
        if point.get("validation_status") == "hard_blocked":
            deduped_points.append(point)
            continue
        existing = seen.get(key)
        if not existing:
            seen[key] = point
            deduped_points.append(point)
            continue
        if float(point.get("final_score") or 0) > float(existing.get("final_score") or 0):
            existing["status"] = "hidden_duplicate"
            existing["status_reason"] = f"与 {point.get('answer_core')} 的训练动作重复，保留分数更高的学习点。"
            existing["ai_decision"] = existing.get("ai_decision") or "duplicate"
            seen[key] = point
            deduped_points.append(point)
        else:
            point["status"] = "hidden_duplicate"
            point["status_reason"] = f"与 {existing.get('answer_core')} 的训练动作重复。"
            point["ai_decision"] = point.get("ai_decision") or "duplicate"
            deduped_points.append(point)

    points = sorted(deduped_points, key=lambda item: (float(item.get("start") or 0), str(item.get("answer_core") or "")))
    status_counts = _status_counts(points)
    source_sentence_quality = sentence_quality_counts(source_sentences)
    ai_rejected_count = sum(1 for point in points if str(point.get("ai_decision") or "").lower() in {"reject", "skip", "missing_review"})
    summary = {
        "total": len(points),
        **status_counts,
        "by_type": _distribution(points, "type"),
        "by_level": _distribution(points, "level"),
        "by_candidate_kind": _distribution(points, "candidate_kind"),
    }
    emit_progress(
        "extract_learning_points",
        "done",
        100,
        f"AI 已扫描 {len(review_source_sentences)}/{len(source_sentences)} 句字幕：推荐 {status_counts['recommended']} 个（默认勾选），候选 {status_counts['candidate_only']} 个（可手动加入）。下一步只生成已选学习点。",
    )
    title = payload.get("title") or (Path(payload.get("video_path") or subtitle_path).stem if (payload.get("video_path") or subtitle_path) else "字幕素材")
    timing_ms["postprocess"] = int((time.perf_counter() - postprocess_started) * 1000)
    timing_ms["total"] = int((time.perf_counter() - timing_started) * 1000)
    add_learning_point_extraction_timing_aliases(timing_ms)
    return {
        "id": f"lp_project_{int(time.time())}",
        "title": title,
        "source_mode": payload.get("source_mode") or "local",
        "video_path": legacy_worker.clean_input_path(payload.get("video_path", "")),
        "subtitle_path": subtitle_path,
        "language": payload.get("language", "en"),
        "level_mode": legacy_worker.normalized_level_mode(payload),
        "level": user_level,
        "review_basis": "ai_reviewed",
        "ai_model_provider": str((payload.get("api_config") or {}).get("provider") or ""),
        "ai_model_name": str((payload.get("api_config") or {}).get("model") or ""),
        "local_candidate_count": local_candidate_count,
        "ai_reviewed_source_count": len(review_source_sentences),
        "ai_reviewed_candidate_count": len(
            [
                point
                for point in raw_points
                if point.get("validation_status") != "hard_blocked"
                and str(point.get("source_segment_id") or "") in {_source_id_for_sentence(source) for source in review_source_sentences}
            ]
        ),
        "ai_recommended_count": status_counts["recommended"],
        "ai_candidate_count": status_counts["candidate_only"],
        "ai_rejected_count": ai_rejected_count,
        "source_info": source_info,
        "source_sentences": source_sentences,
        "learning_points": points,
        "learning_point_summary": summary,
        "timing_ms": timing_ms,
        "quality_funnel": {
            "subtitle_cues": len(cues),
            "source_sentence_count": len(source_sentences),
            "source_sentence_quality_counts": source_sentence_quality,
            "ai_reviewed_source_count": len(review_source_sentences),
            "learning_point_count": len(points),
            "recommended_learning_point_count": status_counts["recommended"],
            "candidate_only_learning_point_count": status_counts["candidate_only"],
            "hidden_duplicate_learning_point_count": status_counts["hidden_duplicate"],
            "hard_blocked_learning_point_count": status_counts["hard_blocked"],
            "level_mode": legacy_worker.normalized_level_mode(payload),
            "review_basis": "ai_reviewed",
            "local_candidate_count": local_candidate_count,
            "valid_local_candidate_count": valid_local_candidate_count,
            "ai_reviewed_candidate_count": len(
                [
                    point
                    for point in raw_points
                    if point.get("validation_status") != "hard_blocked"
                    and str(point.get("source_segment_id") or "") in {_source_id_for_sentence(source) for source in review_source_sentences}
                ]
            ),
            "ai_recommended_count": status_counts["recommended"],
            "ai_candidate_count": status_counts["candidate_only"],
            "ai_rejected_count": ai_rejected_count,
            "ai_review_concurrency": int(payload.get("_ai_review_concurrency") or 1),
            "ai_review_timing_ms": dict(payload.get("_ai_review_timing_ms") or {}),
            "ai_review_cache_hits": int(payload.get("_ai_review_cache_hits") or 0),
            "ai_review_cache_misses": int(payload.get("_ai_review_cache_misses") or 0),
            "ai_review_cache_read_enabled": bool(payload.get("_ai_review_cache_read_enabled")),
            "ai_review_cache_write_enabled": bool(payload.get("_ai_review_cache_write_enabled")),
            "learning_point_timing_ms": timing_ms,
            "ai_review_local_candidate_source_count": int(payload.get("_ai_review_local_candidate_source_count") or 0),
            "ai_review_discovery_source_count": int(payload.get("_ai_review_discovery_source_count") or 0),
            "ai_review_discovery_source_budget": int(payload.get("_ai_review_discovery_source_budget") or 0),
            "ai_review_discovery_source_deferred_count": int(payload.get("_ai_review_discovery_source_deferred_count") or 0),
        },
        "ai_model_errors": model_errors,
        "warnings": [],
    }
