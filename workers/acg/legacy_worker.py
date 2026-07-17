from __future__ import annotations

import base64
import binascii
import hashlib
import functools
import ipaddress
import importlib.util
import json
import math
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

WORKER_DIR = Path(__file__).resolve().parents[1]
if str(WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(WORKER_DIR))

from acg import anki_model_contracts as anki_model_contracts_module
from acg import apkg_package_contract as apkg_package_contract_module
from acg import errors as worker_errors
from acg.anki_fields import (
    anki_card_deck_name,
    anki_card_model_name,
    anki_field_plain_text,
    anki_field_value,
    anki_import_pronunciation_meta_error,
    imported_model_template_mismatches,
    imported_corrupted_study_text_values,
    imported_tts_text_hash_mismatches,
    missing_document_required_text_fields,
    missing_video_required_text_fields,
)
from acg.anki_export import (
    anki_deck_name,
    anki_deck_part,
    batch_export_deck_specs,
    project_media_prefix,
    safe_filename,
    stable_id,
    windows_basename_key,
    windows_safe_basename,
)
from acg.anki_media import anki_audio_html, anki_video_html
from acg.anki_model_contracts import (
    COMPATIBILITY_CONTRACT_VERSION,
    note_model_field_specs,
    resolve_export_note_model_contract,
    validate_generated_note_model,
)
from acg.anki_note_identity import note_guid_for_model
from acg.anki_verify import verify_anki_import_failed_checks, verify_anki_import_message
from acg.audio_audit import (
    audio_audit_failure_details,
    audio_audit_manifest_entry,
    audio_audit_markdown,
    audio_audit_reasons_for_file,
    audio_audit_role_hashes,
    audio_audit_summary,
    audio_audit_tts_hashes,
    audio_audit_expected_refs_by_field,
    audio_audit_imported_text_mismatches,
    card_media_expected_refs_by_field,
    build_audio_audit_items,
    compare_expected_media_refs_by_field,
    items_by_card_id,
    load_audio_audit_from_export_result,
    media_text_hash,
    missing_expected_entry_mismatch,
    unique_clean_strings,
    write_audio_audit_files,
)
from acg.card_quality import (
    ACCEPTABLE_FRAGMENT_ANSWERS as card_quality_acceptable_fragment_answers,
    BAD_INCOMPLETE_ANSWERS as card_quality_bad_incomplete_answers,
    INCOMPLETE_FINAL_CONTRACTIONS as card_quality_incomplete_final_contractions,
    INCOMPLETE_FINAL_WORDS as card_quality_incomplete_final_words,
    SHORT_FRAGMENT_PRONOUN_ENDS as card_quality_short_fragment_pronoun_ends,
    SHORT_WH_FRAGMENT_STARTS as card_quality_short_wh_fragment_starts,
    allows_function_start_phrase as card_quality_allows_function_start_phrase,
    cefr_rank as card_quality_cefr_rank,
    has_generic_definition as card_quality_has_generic_definition,
    has_generic_teacher_note as card_quality_has_generic_teacher_note,
    has_template_noise as card_quality_has_template_noise,
    is_specific_study_text as card_quality_is_specific_study_text,
    is_too_basic_for_level as card_quality_is_too_basic_for_level,
    looks_like_incomplete_answer_fragment as card_quality_looks_like_incomplete_answer_fragment,
    looks_like_truncated_listening_answer as card_quality_looks_like_truncated_listening_answer,
    normalized_action_text as card_quality_normalized_action_text,
    normalized_answer_key as card_quality_normalized_answer_key,
    phrase_allows_trailing_preposition as card_quality_phrase_allows_trailing_preposition,
    phrase_guide_key as card_quality_phrase_guide_key,
)
from acg.card_planning import (
    card_type_for_learning_point as card_planning_card_type_for_learning_point,
    has_listening_training_value as card_planning_has_listening_training_value,
    has_output_training_value as card_planning_has_output_training_value,
    plan_card_types as card_planning_plan_card_types,
    requested_card_types as card_planning_requested_card_types,
    usable_learning_point_span as card_planning_usable_learning_point_span,
)
from acg.cache_identity import (
    MEDIA_FFMPEG_PROFILE_VERSION,
    TEXT_NORMALIZATION_CACHE_VERSION,
    TTS_PROVIDER_ADAPTER_VERSION,
    cached_media_file_valid,
    copy_cached_file,
    discard_cached_file,
    file_fingerprint,
    media_clip_cache_path as cache_media_clip_cache_path,
    persistent_cache_root as cache_persistent_cache_root,
    stable_cache_key,
    store_cached_file,
    tts_cache_path as cache_tts_cache_path,
    tts_provider_scope as cache_tts_provider_scope,
)
from acg.documents.chunking import clip_words, split_document_chunks
from acg.documents.readers import read_document_source
from acg.export_fields import card_sentence_tts_text, front_fields_for_export_media
from acg.export_text import anki_study_text, anki_text, audit_text_excerpt
from acg.generation_timing import add_export_timing_aliases, add_verify_anki_import_timing_aliases
from acg.imported_media import (
    audio_duration_seconds_from_bytes as imported_audio_duration_seconds_from_bytes,
    imported_media_exists_for_audit,
    imported_tts_audio_duration_issues as imported_tts_audio_duration_issues_core,
    numeric_manifest_value,
)
from acg.language_text import (
    CONTRACTION_WORD_EXPANSIONS,
    LEARNING_LANGUAGE_ALIASES,
    LEARNING_LANGUAGE_PROFILES,
    TTS_LANGUAGE_FALLBACKS,
    expanded_overlap_words as language_expanded_overlap_words,
    has_cjk as language_has_cjk,
    has_cyrillic as language_has_cyrillic,
    has_japanese_kana as language_has_japanese_kana,
    has_latin_letter as language_has_latin_letter,
    looks_like_target_language_text as language_looks_like_target_language_text,
    normalize_learning_language as language_normalize_learning_language,
    overlap_words as language_overlap_words,
    pronunciation_profile as language_pronunciation_profile,
    word_overlap_ratio as language_word_overlap_ratio,
)
from acg.learning_settings import (
    LANGUAGE_FOCUS_LABELS as learning_settings_language_focus_labels,
    LANGUAGE_FOCUS_ORDER as learning_settings_language_focus_order,
    LANGUAGE_FOCUS_RULES as learning_settings_language_focus_rules,
    SELECTION_STRATEGIES as learning_settings_selection_strategies,
    SELECTION_STRATEGY_LABELS as learning_settings_selection_strategy_labels,
    STUDY_DEPTHS as learning_settings_study_depths,
    collection_levels_from_payload as learning_settings_collection_levels_from_payload,
    discovery_collection_levels as learning_settings_discovery_collection_levels,
    language_focus_instruction as learning_settings_language_focus_instruction,
    learning_point_confidence as learning_settings_learning_point_confidence,
    max_learning_points_per_source as learning_settings_max_learning_points_per_source,
    max_reviewable_cards_per_source as learning_settings_max_reviewable_cards_per_source,
    max_source_expansion_groups as learning_settings_max_source_expansion_groups,
    normalize_collection_levels as learning_settings_normalize_collection_levels,
    normalized_document_reading_focus as learning_settings_normalized_document_reading_focus,
    normalized_language_focus as learning_settings_normalized_language_focus,
    normalized_level_mode as learning_settings_normalized_level_mode,
    normalized_selection_strategy as learning_settings_normalized_selection_strategy,
    normalized_source_expansion_mode as learning_settings_normalized_source_expansion_mode,
    normalized_study_depth as learning_settings_normalized_study_depth,
    selection_candidate_multiplier as learning_settings_selection_candidate_multiplier,
)
from acg.learning_actions import (
    learning_action_for_card as learning_actions_learning_action_for_card,
    normalize_learning_action_fields as learning_actions_normalize_learning_action_fields,
    normalized_contains_text as learning_actions_normalized_contains_text,
)
from acg.inventory import (
    LEARNING_POINT_INVENTORY_STATUSES as inventory_learning_point_inventory_statuses,
    apply_default_generated_card_selection as inventory_apply_default_generated_card_selection,
    card_quality_status as inventory_card_quality_status,
    inventory_learning_action as inventory_inventory_learning_action,
    inventory_status_for_filtered_item as inventory_inventory_status_for_filtered_item,
    inventory_status_for_rejected_card as inventory_inventory_status_for_rejected_card,
    learning_point_inventory_stats as inventory_learning_point_inventory_stats,
)
from acg.review_modes import (
    CIBA_CARD_STYLE_LABELS as review_modes_ciba_card_style_labels,
    VALID_CARD_STYLES as review_modes_valid_card_styles,
    VALID_REVIEW_DENSITIES as review_modes_valid_review_densities,
    VALID_TEMPLATE_IDS as review_modes_valid_template_ids,
    ciba_tianxia_mode as review_modes_ciba_tianxia_mode,
    fast_review_card_quality as review_modes_fast_review_card_quality,
    fast_review_density as review_modes_fast_review_density,
    fast_review_prompt_instruction as review_modes_fast_review_prompt_instruction,
    normalize_card_style as review_modes_normalize_card_style,
    normalize_review_density as review_modes_normalize_review_density,
    normalize_template_id as review_modes_normalize_template_id,
    short_fast_text as review_modes_short_fast_text,
    slim_fast_review_card as review_modes_slim_fast_review_card,
    slim_fast_review_segments as review_modes_slim_fast_review_segments,
)
from acg.learning_spans import (
    exact_span_offsets as learning_span_exact_span_offsets,
    expression_span_from_text as learning_span_expression_span_from_text,
    normalize_candidate_span as learning_span_normalize_candidate_span,
    normalized_phrase_key as learning_span_normalized_phrase_key,
    phrase_in_text as learning_span_phrase_in_text,
)
from acg.learning_types import (
    card_label_for_learning_card as learning_type_card_label_for_learning_card,
    card_label_for_phrase_type as learning_type_card_label_for_phrase_type,
    candidate_kind_allowed_by_focus as learning_type_candidate_kind_allowed_by_focus,
    candidate_kind_for_phrase_type as learning_type_candidate_kind_for_phrase_type,
    candidate_kind_for_segment as learning_type_candidate_kind_for_segment,
    content_kind_for_phrase_type as learning_type_content_kind_for_phrase_type,
    learning_action_key_for_contract as learning_type_learning_action_key_for_contract,
    normalize_candidate_kind as learning_type_normalize_candidate_kind,
    normalize_phrase_type as learning_type_normalize_phrase_type,
    phrase_type_for_candidate_kind as learning_type_phrase_type_for_candidate_kind,
)
from acg.phrases.lexicon import (
    CARD_TYPE_LABELS,
    CEFR_LABELS,
    CEFR_ORDER,
    COMMON_FUNCTION_STARTS,
    DISCOVERY_EXPRESSION_PATTERNS,
    DISCOVERY_PHRASE_PARTICLES,
    DISCOVERY_PHRASE_VERBS,
    DISCOVERY_PREPOSITION_STARTS,
    DISCOVERY_SIGNAL_WORDS,
    EXPRESSION_PATTERNS,
    PHRASE_GUIDES,
    PHRASES_BY_LEVEL,
)
from acg.phrase_discovery import (
    candidate_phrases_from_text as phrase_discovery_candidate_phrases_from_text,
    choose_best_phrase as phrase_discovery_choose_best_phrase,
    discovery_ngram_has_signal as phrase_discovery_discovery_ngram_has_signal,
    find_phrase as phrase_discovery_find_phrase,
    has_adjacent_duplicate_words as phrase_discovery_has_adjacent_duplicate_words,
    is_low_value_standalone_phrase as phrase_discovery_is_low_value_standalone_phrase,
    is_non_transferable_phrase as phrase_discovery_is_non_transferable_phrase,
    normalize_phrase_candidate as phrase_discovery_normalize_phrase_candidate,
    phrase_pool as phrase_discovery_phrase_pool,
    structurally_safe_discovery_phrase as phrase_discovery_structurally_safe_discovery_phrase,
    trim_discovery_phrase_words as phrase_discovery_trim_discovery_phrase_words,
    usable_phrase as phrase_discovery_usable_phrase,
)
from acg.provider_config import (
    DEEPSEEK_OPENAI_BASE_URL,
    DEEPSEEK_THINKING_MODELS,
    GEMINI_VERTEX_DEFAULT_MODEL,
    GEMINI_VERTEX_GLOBAL_BASE_URL,
    GEMINI_VERTEX_MODEL_ALIASES,
    GEMINI_VERTEX_PRO_PREVIEW_MODEL,
    GEMINI_VERTEX_PROVIDERS,
    GEMINI_VERTEX_TTS_DEFAULT_MODEL,
    GEMINI_VERTEX_TTS_DEFAULT_VOICE,
    GEMINI_VERTEX_TTS_GLOBAL_BASE_URL,
    GEMINI_VERTEX_TTS_PROVIDERS,
    GEMINI_VERTEX_UNAVAILABLE_MODEL_ALIASES,
    MIMO_OPENAI_BASE_URL,
    MIMO_PROVIDERS,
    MIMO_TOKEN_PLAN_SGP_BASE_URL,
    OPENAI_COMPATIBLE_PROVIDERS,
    QWEN_DASHSCOPE_CN_TTS_BASE_URL,
    QWEN_TTS_DEFAULT_MODEL,
    QWEN_TTS_DEFAULT_VOICE,
    QWEN_TTS_PROVIDERS,
    api_key_header as provider_api_key_header,
    compatible_base_url as provider_compatible_base_url,
    is_deepseek_config as provider_is_deepseek_config,
    is_deepseek_thinking_config as provider_is_deepseek_thinking_config,
    is_gemini_vertex_config as provider_is_gemini_vertex_config,
    is_gemini_vertex_thinking_config as provider_is_gemini_vertex_thinking_config,
    is_gemini_vertex_tts_config as provider_is_gemini_vertex_tts_config,
    is_mimo_config as provider_is_mimo_config,
    is_qwen_config as provider_is_qwen_config,
    is_thinking_model_config as provider_is_thinking_model_config,
    model_api_available as provider_model_api_available,
    provider_name as provider_provider_name,
    should_stream_reasoning as provider_should_stream_reasoning,
    thinking_budget as provider_thinking_budget,
)
from acg.managed_model_broker import (
    ManagedModelBrokerError,
    is_configured as managed_model_broker_is_configured,
    operation_available as managed_model_operation_available,
    request_model as managed_model_request,
)
from acg.managed_tts_broker import (
    ManagedTtsAudio,
    ManagedTtsBrokerError,
    is_configured as managed_tts_broker_is_configured,
    operation_available as managed_tts_operation_available,
    request_tts as managed_tts_request,
)
from acg.service_errors import (
    classify_service_error as service_errors_classify_service_error,
    classify_worker_exception as service_errors_classify_worker_exception,
    http_status_from_error_message as service_errors_http_status_from_error_message,
    service_error_codes as service_errors_service_error_codes,
    service_error_message as service_errors_service_error_message,
    service_label as service_errors_service_label,
    service_stage as service_errors_service_stage,
)
from acg.security_boundaries import (
    BLOCKED_URL_HOSTS as security_boundaries_blocked_url_hosts,
    LOOPBACK_HOSTS as security_boundaries_loopback_hosts,
    SENSITIVE_WINDOWS_ROOTS as security_boundaries_sensitive_windows_roots,
    SUPPORTED_INPUT_SUFFIXES as security_boundaries_supported_input_suffixes,
    host_is_loopback as security_boundaries_host_is_loopback,
    host_is_private_or_local as security_boundaries_host_is_private_or_local,
    ip_address_for_host as security_boundaries_ip_address_for_host,
    parsed_url_host as security_boundaries_parsed_url_host,
    require_confirmed_local_path_access as security_boundaries_require_confirmed_local_path_access,
    validate_anki_connect_url as security_boundaries_validate_anki_connect_url,
    validate_source_url_for_import as security_boundaries_validate_source_url_for_import,
)
from acg.scoring.source_text import (
    contains_any as source_text_contains_any,
    content_allowed as source_text_content_allowed,
    looks_like_video_intro as source_text_looks_like_video_intro,
    score_text as source_text_score_text,
)
from acg.ytdlp_support import (
    format_yt_dlp_failure as ytdlp_support_format_yt_dlp_failure,
    is_subtitle_rate_limited as ytdlp_support_is_subtitle_rate_limited,
    yt_dlp_failure_detail as ytdlp_support_yt_dlp_failure_detail,
    yt_dlp_failure_meta as ytdlp_support_yt_dlp_failure_meta,
    yt_dlp_js_runtime_args as ytdlp_support_yt_dlp_js_runtime_args,
    yt_dlp_network_args as ytdlp_support_yt_dlp_network_args,
    yt_dlp_needs_remote_components as ytdlp_support_yt_dlp_needs_remote_components,
)
from acg.subtitles.discovery import (
    TEXT_SUBTITLE_CODECS,
    compact_match_text as subtitle_discovery_compact_match_text,
    convert_vtt_to_srt as subtitle_discovery_convert_vtt_to_srt,
    discover_local_subtitle as subtitle_discovery_discover_local_subtitle,
    first_file_by_suffix as subtitle_discovery_first_file_by_suffix,
    pick_subtitle_file as subtitle_discovery_pick_subtitle_file,
    select_embedded_subtitle_stream as subtitle_discovery_select_embedded_subtitle_stream,
    subtitle_language_aliases as subtitle_discovery_subtitle_language_aliases,
    subtitle_language_args as subtitle_discovery_subtitle_language_args,
    subtitle_language_markers as subtitle_discovery_subtitle_language_markers,
)
from acg.subtitles.sentences import (
    append_caption_text as subtitle_append_caption_text,
    ends_like_fragment as subtitle_ends_like_fragment,
    has_unbalanced_quotes as subtitle_has_unbalanced_quotes,
    incremental_caption_text as subtitle_incremental_caption_text,
    normalize_rolling_cues as subtitle_normalize_rolling_cues,
    source_segment_key as subtitle_source_segment_key,
    split_caption_fragment as subtitle_split_caption_fragment,
    starts_like_fragment as subtitle_starts_like_fragment,
    stitch_sentence_cues as subtitle_stitch_sentence_cues,
    word_spans as subtitle_word_spans,
)
from acg.media_alignment import (
    MEDIA_SUBTITLE_PARTIAL_EXPORT_BLOCK_THRESHOLD,
    SOURCE_SENTENCE_QUALITY_MEDIA_BLOCK_FLAGS,
    _counted_word_overlap_ratio,
    align_segment_media_to_display_sentence,
    clean_candidate_text,
    export_subtitle_alignment_diagnostics,
    is_filler_text as media_is_filler_text,
    media_subtitle_alignment_blocks_export,
    media_subtitle_alignment_diagnostic,
    media_subtitle_alignment_failure_reason,
    merge_subtitle_parts,
    looks_complete_sentence as media_looks_complete_sentence,
    phrase_word_indices,
    refine_segment_media_for_phrase,
    segment_media_bounds,
    segment_display_source_time,
    sentence_window_media_bounds,
    video_media_subtitle_mismatch_items,
)
from acg.media_tool_policy import (
    MediaToolPolicyError,
    managed_tool_path as media_managed_tool_path,
    run_ffmpeg as media_policy_run_ffmpeg,
    run_ffprobe as media_policy_run_ffprobe,
    tool_version as media_tool_version,
)
from acg.media_manifest import (
    bytes_sha256,
    compare_media_manifest as compare_media_manifest_core,
    file_sha256,
    media_ledger_card_text_mismatches as media_ledger_card_text_mismatches_core,
    media_ledger_manifest_consistency,
    media_manifest as media_manifest_core,
)
from acg.media_refs import extract_media_references, missing_video_required_media_roles
from acg.presentation import build_card_presentation
from acg.model_json import (
    extract_json_object as model_json_extract_json_object,
    strip_reasoning_text as model_json_strip_reasoning_text,
)
from acg.protocol import PROGRESS_PREFIX, emit, emit_progress, fail, read_payload
from acg.secret_scrub import scrub_runtime_secrets
from acg.source_modes import (
    SUBTITLE_ONLY_IMPORT_MODES,
    normalized_url_import_mode,
    url_video_mode_requested,
    video_free_export_allowed,
    video_media_required_for_export,
    wants_subtitle_only,
)
from acg.subtitles.core import Cue, fmt_time, parse_timestamp, strip_subtitle_text
from acg.text_cleaning import (
    INTERNAL_PLACEHOLDER_PATTERNS,
    MANUAL_CONFIRMATION_ONLY_PLACEHOLDER_PATTERNS,
    clean_study_text,
    contains_internal_placeholder,
    internal_placeholder_patterns,
    internal_placeholder_patterns_for_quality_issue,
)
from acg.tts_text import (
    TTS_SMALL_NUMBER_WORDS,
    clean_tts_input_text,
    exact_tts_prompt,
    gemini_vertex_tts_text_variants,
    tts_ascii_punctuation_variant,
    tts_sentence_punctuation_variant,
    tts_small_number_words_variant,
    tts_speech_safe_variant,
)
from acg.tts_semantic import (
    build_asr_command_argv as semantic_build_asr_command_argv,
    normalize_tts_semantic_text,
    phrase_tts_max_duration_seconds,
    tts_manual_review_items,
    tts_semantic_config as semantic_tts_semantic_config,
    tts_semantic_base_reasons,
    tts_semantic_failure_items,
    tts_semantic_matches,
    tts_semantic_not_applicable,
    tts_semantic_requires_export_pass as semantic_tts_semantic_requires_export_pass,
    tts_semantic_verification_enabled as semantic_tts_semantic_verification_enabled,
    tts_semantic_verification_summary,
    unsafe_asr_command_reason as semantic_unsafe_asr_command_reason,
)


for stream in (sys.stdin, sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")

VALID_TEMPLATE_IDS = review_modes_valid_template_ids


def normalize_template_id(template_id: Any = "immersive_v11") -> str:
    return review_modes_normalize_template_id(template_id)


def ciba_tianxia_mode(payload: dict[str, Any] | None) -> bool:
    return review_modes_ciba_tianxia_mode(payload)


VALID_CARD_STYLES = review_modes_valid_card_styles
VALID_REVIEW_DENSITIES = review_modes_valid_review_densities
CIBA_CARD_STYLE_LABELS = review_modes_ciba_card_style_labels


def normalize_card_style(card_style: Any = "warm_paper") -> str:
    return review_modes_normalize_card_style(card_style)


def normalize_review_density(review_density: Any = "full") -> str:
    return review_modes_normalize_review_density(review_density)


def fast_review_density(project: dict[str, Any]) -> bool:
    return review_modes_fast_review_density(project)


def fast_review_prompt_instruction(project: dict[str, Any]) -> str:
    return review_modes_fast_review_prompt_instruction(project)


def short_fast_text(value: Any, limit: int) -> str:
    return review_modes_short_fast_text(value, limit)


def fast_review_card_quality(card: dict[str, Any], segment: dict[str, Any] | None = None) -> dict[str, Any]:
    return review_modes_fast_review_card_quality(card, segment)


def slim_fast_review_card(card: dict[str, Any], segment: dict[str, Any] | None = None) -> dict[str, Any]:
    return review_modes_slim_fast_review_card(card, segment)


def slim_fast_review_segments(segments: list[dict[str, Any]], project: dict[str, Any]) -> list[dict[str, Any]]:
    return review_modes_slim_fast_review_segments(segments, project)


def normalize_learning_language(language: Any = "en") -> str:
    return language_normalize_learning_language(language)


def pronunciation_profile(language: Any = "en") -> dict[str, str]:
    return language_pronunciation_profile(language)


def overlap_words(value: str) -> list[str]:
    return language_overlap_words(value)


def expanded_overlap_words(value: str) -> list[str]:
    return language_expanded_overlap_words(value)


def has_cjk(value: str) -> bool:
    return language_has_cjk(value)


def has_japanese_kana(value: Any) -> bool:
    return language_has_japanese_kana(value)


def has_cyrillic(value: Any) -> bool:
    return language_has_cyrillic(value)


def has_latin_letter(value: Any) -> bool:
    return language_has_latin_letter(value)


def looks_like_target_language_text(value: Any, language: Any = "en") -> bool:
    return language_looks_like_target_language_text(value, language)


def clean_input_path(value: Any) -> str:
    return str(value or "").strip().strip('"').strip("'")


def word_overlap_ratio(left: str, right: str) -> float:
    return language_word_overlap_ratio(left, right)


def parse_srt(path: str) -> list[Cue]:
    subtitle_path = Path(path)
    if not subtitle_path.exists():
        fail(f"SRT 文件不存在：{subtitle_path}")

    text = subtitle_path.read_text(encoding="utf-8-sig", errors="replace")
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    cues: list[Cue] = []
    i = 0

    while i < len(lines):
        line = lines[i].strip()
        if "-->" not in line:
            i += 1
            continue

        start_raw, end_raw = line.split("-->", 1)
        i += 1
        text_lines: list[str] = []
        while i < len(lines):
            current = lines[i].strip()
            if "-->" in current:
                break
            if current.isdigit():
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                if j < len(lines) and "-->" in lines[j]:
                    break
            if current:
                text_lines.append(current)
            i += 1

        clean_text = strip_subtitle_text(" ".join(text_lines))
        if not clean_text:
            continue
        cues.append(
            Cue(
                index=len(cues) + 1,
                start=parse_timestamp(start_raw),
                end=parse_timestamp(end_raw.split()[0]),
                text=clean_text,
            )
        )

    if not cues:
        fail("没有从 SRT 中解析出有效字幕。")
    return normalize_rolling_cues(cues)


def word_spans(text: str) -> list[re.Match[str]]:
    return subtitle_word_spans(text)


def incremental_caption_text(previous_text: str, current_text: str) -> tuple[str, bool]:
    return subtitle_incremental_caption_text(previous_text, current_text)


def split_caption_fragment(text: str, start: float, end: float) -> list[tuple[str, float, float]]:
    return subtitle_split_caption_fragment(text, start, end)


def append_caption_text(left: str, right: str) -> str:
    return subtitle_append_caption_text(left, right)


def stitch_sentence_cues(chunks: list[Cue]) -> list[Cue]:
    return subtitle_stitch_sentence_cues(chunks)


def normalize_rolling_cues(cues: list[Cue]) -> list[Cue]:
    return subtitle_normalize_rolling_cues(cues)


def contains_any(text: str, patterns: list[str]) -> bool:
    return source_text_contains_any(text, patterns)


def content_allowed(text: str, toggles: dict[str, bool]) -> bool:
    return source_text_content_allowed(text, toggles)


def normalize_collection_levels(value: Any, current_level: str) -> list[str]:
    return learning_settings_normalize_collection_levels(value, current_level)


def collection_levels_from_payload(payload: dict[str, Any], current_level: str) -> list[str]:
    return learning_settings_collection_levels_from_payload(payload, current_level)


def normalized_level_mode(payload: dict[str, Any]) -> str:
    return learning_settings_normalized_level_mode(payload)


LANGUAGE_FOCUS_ORDER = learning_settings_language_focus_order
LANGUAGE_FOCUS_LABELS = learning_settings_language_focus_labels
LANGUAGE_FOCUS_RULES = learning_settings_language_focus_rules
STUDY_DEPTHS = learning_settings_study_depths
SELECTION_STRATEGIES = learning_settings_selection_strategies
SELECTION_STRATEGY_LABELS = learning_settings_selection_strategy_labels
PHRASE_TYPE_CARD_LABELS = {
    "spoken_phrase": "学习卡",
    "sentence_frame": "学习卡",
    "collocation": "学习卡",
    "discourse_marker": "学习卡",
    "idiom": "学习卡",
    "listening_sentence": "学习卡",
    "vocabulary_usage": "学习卡",
    "grammar_pattern": "学习卡",
}
PHRASE_TYPE_CONTENT_KIND = {
    "spoken_phrase": "phrase",
    "sentence_frame": "grammar",
    "collocation": "phrase",
    "discourse_marker": "phrase",
    "idiom": "phrase",
    "listening_sentence": "listening",
    "vocabulary_usage": "vocabulary",
    "grammar_pattern": "grammar",
}
CANDIDATE_KIND_TO_PHRASE_TYPE = {
    "expression": "spoken_phrase",
    "contextual_vocab": "vocabulary_usage",
    "grammar_pattern": "grammar_pattern",
    "listening_feature": "listening_sentence",
    "pragmatic_risk": "idiom",
}
PHRASE_TYPE_TO_CANDIDATE_KIND = {
    "spoken_phrase": "expression",
    "sentence_frame": "grammar_pattern",
    "collocation": "expression",
    "discourse_marker": "expression",
    "idiom": "expression",
    "listening_sentence": "listening_feature",
    "vocabulary_usage": "contextual_vocab",
    "grammar_pattern": "grammar_pattern",
}
LEARNING_POINT_SCHEMA_VERSION = 3
TYPED_EXPRESSION_PATTERNS = [
    (r"\brun\s+the\s+register\b", "collocation", "expression", 1.6, "服务业场景搭配：负责收银/操作收银机。"),
    (r"\bhold\s+that\s+against\s+you\b", "idiom", "expression", 1.6, "把某事拿来责怪或记恨某人。"),
    (r"\bflat\s+as\s+a\s+washboard\b", "idiom", "pragmatic_risk", 1.7, "夸张比喻，带身体评价和冒犯风险。"),
    (r"\b(?:not\s+)?gonna\s+bite\s+you\b", "spoken_phrase", "expression", 1.2, "安抚别人别怕的口语句。"),
    (r"\b(?:add|adds|added|adding)\s+ten\s+pounds\b", "collocation", "expression", 1.4, "镜头让人显胖的非字面表达。"),
    (r"\bbounce\s+off\s+a\s+windshield\b", "collocation", "expression", 1.2, "撞到挡风玻璃后弹开的动作搭配。"),
    (r"\b(?:placed?|put)\s+(?:me|you|him|her|us|them|someone|somebody|people|[a-z']+)\s+into\s+custody\b", "collocation", "expression", 1.3, "法律/警务语境里的拘押搭配。"),
    (r"\bcould\s+use\s+a\s+hand\b", "spoken_phrase", "expression", 1.3, "表示需要帮忙的自然口语。"),
    (r"\btake\s+a\s+rain\s+check\b", "idiom", "expression", 1.4, "委婉改天再约的习语。"),
    (r"\bgetting\s+out\s+of\s+hand\b", "idiom", "expression", 1.4, "表示局面开始失控。"),
    (r"\bbetween\s+you\s+and\s+me\b", "discourse_marker", "expression", 1.1, "引出私下说法的话语标记。"),
    (r"\bno\s+offense,\s+but\b", "discourse_marker", "pragmatic_risk", 1.2, "带冒犯风险的缓冲开头。"),
]
CONTEXTUAL_VOCAB_PATTERNS = [
    (r"\bregister\b", "register", 1.1, "register 在服务业语境里可指收银机/收银台。"),
    (r"\bcustody\b", "custody", 1.0, "custody 在警务/法律语境里是羁押、拘留。"),
    (r"\bcritique\b", "critique", 1.0, "critique 是对作品或文本做专业点评。"),
    (r"\bfollowing\b", "following", 0.9, "following 在 I'm not following 里是跟上/听懂思路。"),
    (r"\b(?:add|adds|added|adding)\b", "add", 0.8, "add 在镜头/效果语境里可表示让人看起来增加。"),
]
GRAMMAR_PATTERN_RULES = [
    (r"\bi\s+seen\b", "I seen", 1.4, "非标准口语过去时，理解角色口音和方言色彩。"),
    (r"^\s*ever\s+want\s+me\s+to\b", "Ever want me to...", 1.5, "句首省略 If you 的口语条件框架。"),
    (r"\bit'?s\s+not\s+that\b.+\bit'?s\s+just\s+that\b", "It's not that..., it's just that...", 1.2, "解释原因时的可迁移框架。"),
    (r"\bnot\s+because\b.+\bbut\s+because\b", "not because..., but because...", 1.2, "纠正原因或对比原因的句型框架。"),
]
LISTENING_FEATURE_RE = re.compile(
    r"\b(?:i'm|you're|we're|they're|don't|can't|won't|let's|gonna|wanna|gotta|hafta|shoulda|coulda|woulda)\b(?:\s+[a-z']+){0,2}",
    re.IGNORECASE,
)


def normalized_language_focus(payload: dict[str, Any]) -> list[str]:
    return learning_settings_normalized_language_focus(payload)


def normalized_document_reading_focus(payload: dict[str, Any]) -> list[str]:
    return learning_settings_normalized_document_reading_focus(payload)


def language_focus_instruction(payload: dict[str, Any]) -> str:
    return learning_settings_language_focus_instruction(payload)


def normalized_study_depth(payload: dict[str, Any]) -> str:
    return learning_settings_normalized_study_depth(payload)


def normalized_selection_strategy(payload: dict[str, Any]) -> str:
    return learning_settings_normalized_selection_strategy(payload)


def discovery_collection_levels(payload: dict[str, Any], current_level: str) -> list[str]:
    return learning_settings_discovery_collection_levels(payload, current_level)


def selection_candidate_multiplier(payload: dict[str, Any]) -> int:
    return learning_settings_selection_candidate_multiplier(payload)


def max_learning_points_per_source(payload: dict[str, Any]) -> int:
    return learning_settings_max_learning_points_per_source(payload)


def max_reviewable_cards_per_source(payload: dict[str, Any]) -> int:
    return learning_settings_max_reviewable_cards_per_source(payload)


def normalized_source_expansion_mode(payload: dict[str, Any]) -> str:
    return learning_settings_normalized_source_expansion_mode(payload)


def max_source_expansion_groups(payload: dict[str, Any]) -> int:
    return learning_settings_max_source_expansion_groups(payload)


def card_label_for_phrase_type(phrase_type: str, fallback: str = "学习卡") -> str:
    return learning_type_card_label_for_phrase_type(phrase_type, fallback)


def card_label_for_learning_card(phrase_type: str, content_kind: str, fallback: str = "学习卡") -> str:
    return learning_type_card_label_for_learning_card(phrase_type, content_kind, fallback)


def content_kind_for_phrase_type(phrase_type: str, fallback: str = "phrase") -> str:
    return learning_type_content_kind_for_phrase_type(phrase_type, fallback)


def candidate_kind_for_phrase_type(phrase_type: str, fallback: str = "expression") -> str:
    return learning_type_candidate_kind_for_phrase_type(phrase_type, fallback)


def phrase_type_for_candidate_kind(candidate_kind: str, fallback: str = "spoken_phrase") -> str:
    return learning_type_phrase_type_for_candidate_kind(candidate_kind, fallback)


def candidate_kind_for_segment(segment: dict[str, Any]) -> str:
    return learning_type_candidate_kind_for_segment(segment)


def normalize_candidate_kind(value: Any, fallback: str = "expression") -> str:
    return learning_type_normalize_candidate_kind(value, fallback)


def normalize_phrase_type(value: Any, candidate_kind: str = "expression") -> str:
    return learning_type_normalize_phrase_type(value, candidate_kind)


def learning_point_confidence(value_score: Any, default: str = "medium") -> str:
    return learning_settings_learning_point_confidence(value_score, default)


def exact_span_offsets(text: str, span: str) -> tuple[int | None, int | None]:
    return learning_span_exact_span_offsets(text, span)


def learning_action_key_for_contract(item: dict[str, Any]) -> str:
    return learning_type_learning_action_key_for_contract(item)


def candidate_kind_allowed_by_focus(candidate_kind: str, payload: dict[str, Any]) -> bool:
    return learning_type_candidate_kind_allowed_by_focus(candidate_kind, payload)


DOCUMENT_FOCUS_ORDER = ["concepts", "arguments", "terms", "examples"]
DOCUMENT_FOCUS_LABELS = {
    "concepts": "核心概念",
    "arguments": "观点论证",
    "terms": "术语定义",
    "examples": "例子案例",
}
DOCUMENT_FOCUS_RULES = {
    "concepts": "抽取文档里必须理解的概念、机制或原则；问题要能训练主动回忆，不要把章节标题硬当概念。",
    "arguments": "抽取作者观点、理由、证据和推导链；要说明观点为什么成立，避免只写一句空泛结论。",
    "terms": "抽取术语、定义、边界和易混点；要能区分相关概念，不做词典式堆料。",
    "examples": "抽取真正能帮助记住概念的例子或案例；例子必须服务于一个明确知识点。",
}
DOCUMENT_STUDY_MODES = {"knowledge", "language_reading"}
DOCUMENT_ANSWER_LANGUAGES = {
    "zh": "答案、解释和老师提醒优先用自然中文；关键术语可以保留原文。",
    "en": "答案、解释和老师提醒优先用英文；避免中文长解释。",
    "bilingual": "保留文档原文语言的关键术语、短句或证据，同时用自然中文解释清楚；不要默认原文只能是英文。",
    "ja": "答案、解释和老师提醒优先用自然日语；关键术语可以保留原文。",
    "ko": "答案、解释和老师提醒优先用自然韩语；关键术语可以保留原文。",
    "es": "答案、解释和老师提醒优先用自然西班牙语；关键术语可以保留原文。",
    "fr": "答案、解释和老师提醒优先用自然法语；关键术语可以保留原文。",
    "de": "答案、解释和老师提醒优先用自然德语；关键术语可以保留原文。",
    "ru": "答案、解释和老师提醒优先用自然俄语；关键术语可以保留原文。",
    "pt": "答案、解释和老师提醒优先用自然葡萄牙语；关键术语可以保留原文。",
    "it": "答案、解释和老师提醒优先用自然意大利语；关键术语可以保留原文。",
    "ar": "答案、解释和老师提醒优先用自然阿拉伯语；关键术语可以保留原文。",
}
DOCUMENT_DEPTH_RULES = {
    "quick": "快速记忆：问题要短，答案尽量 1 句，避免展开过多背景。",
    "standard": "标准理解：答案 1-3 句，保留必要条件、原因或例子。",
    "deep": "深入掌握：强调边界、推理链、对比项和容易误解的点。",
}
DOCUMENT_LENGTH_RULES = {
    "short": "短答案：反面核心答案尽量 1 句。",
    "medium": "中等答案：反面核心答案 1-3 句。",
    "long": "详细答案：允许更多解释，但仍禁止照抄原文长段。",
}


def normalized_document_focus(payload: dict[str, Any]) -> list[str]:
    raw = payload.get("document_focus")
    if not isinstance(raw, list):
        return ["concepts", "arguments", "terms"]
    selected = [str(item) for item in raw if str(item) in DOCUMENT_FOCUS_ORDER]
    unique = list(dict.fromkeys(selected))
    return unique or ["concepts", "arguments", "terms"]


def normalized_document_study_mode(payload: dict[str, Any]) -> str:
    raw = str(payload.get("document_study_mode") or "knowledge")
    return raw if raw in DOCUMENT_STUDY_MODES else "knowledge"


def normalized_document_answer_language(payload: dict[str, Any]) -> str:
    raw = str(payload.get("document_answer_language") or "zh")
    return raw if raw in DOCUMENT_ANSWER_LANGUAGES else "zh"


def normalized_document_depth(payload: dict[str, Any]) -> str:
    raw = str(payload.get("document_depth") or "standard")
    return raw if raw in DOCUMENT_DEPTH_RULES else "standard"


def normalized_document_answer_length(payload: dict[str, Any]) -> str:
    raw = str(payload.get("document_answer_length") or "medium")
    return raw if raw in DOCUMENT_LENGTH_RULES else "medium"


def document_style_instruction(payload: dict[str, Any]) -> str:
    answer_language = normalized_document_answer_language(payload)
    depth = normalized_document_depth(payload)
    answer_length = normalized_document_answer_length(payload)
    return (
        f"讲解语言：{DOCUMENT_ANSWER_LANGUAGES[answer_language]}"
        "注意：JSON 字段名为了兼容 Anki 模型仍可能叫 chinese/chinese_feel，但字段内容必须遵守本次讲解语言；"
        "不要因为字段名包含 chinese 就强制写中文。"
        f"卡片深度：{DOCUMENT_DEPTH_RULES[depth]}"
        f"答案长度：{DOCUMENT_LENGTH_RULES[answer_length]}"
    )


def document_focus_instruction(payload: dict[str, Any]) -> str:
    focus = normalized_document_focus(payload)
    labels = " / ".join(DOCUMENT_FOCUS_LABELS[item] for item in focus)
    rules = "".join(f"{DOCUMENT_FOCUS_LABELS[item]}：{DOCUMENT_FOCUS_RULES[item]}" for item in focus)
    return (
        f"本次文档吸收目标：{labels}。请只围绕这些目标做知识卡。"
        "每张卡必须只有一个明确记忆动作：定义概念、解释观点、区分概念或记住例子。"
        f"{rules}"
    )


def phrase_pool(level: str, collection_levels: list[str] | None = None) -> list[str]:
    return phrase_discovery_phrase_pool(level, collection_levels)


def normalize_phrase_candidate(value: str) -> str:
    return phrase_discovery_normalize_phrase_candidate(value)


def has_adjacent_duplicate_words(words: list[str]) -> bool:
    return phrase_discovery_has_adjacent_duplicate_words(words)


def trim_discovery_phrase_words(words: list[str]) -> list[str]:
    return phrase_discovery_trim_discovery_phrase_words(words)


def discovery_ngram_has_signal(words: list[str]) -> bool:
    return phrase_discovery_discovery_ngram_has_signal(words)


def structurally_safe_discovery_phrase(phrase: str) -> bool:
    return phrase_discovery_structurally_safe_discovery_phrase(phrase)


def candidate_phrases_from_text(text: str) -> list[str]:
    return phrase_discovery_candidate_phrases_from_text(text)


def find_phrase(text: str, level: str, collection_levels: list[str] | None = None) -> str:
    return phrase_discovery_find_phrase(text, level, collection_levels)


def is_filler_text(text: str) -> bool:
    return media_is_filler_text(text)


def looks_complete_sentence(text: str) -> bool:
    return media_looks_complete_sentence(text)


def has_unbalanced_quotes(text: str) -> bool:
    return subtitle_has_unbalanced_quotes(text)


def starts_like_fragment(text: str) -> bool:
    return subtitle_starts_like_fragment(text)


def ends_like_fragment(text: str) -> bool:
    return subtitle_ends_like_fragment(text)


def looks_like_video_intro(text: str) -> bool:
    return source_text_looks_like_video_intro(text)


def is_non_transferable_phrase(phrase: str) -> bool:
    return phrase_discovery_is_non_transferable_phrase(phrase)


def is_low_value_standalone_phrase(phrase: str) -> bool:
    return phrase_discovery_is_low_value_standalone_phrase(phrase)


def has_generic_definition(value: str) -> bool:
    return card_quality_has_generic_definition(value)


def has_generic_teacher_note(value: str) -> bool:
    return card_quality_has_generic_teacher_note(value)


def has_template_noise(value: Any) -> bool:
    return card_quality_has_template_noise(value)


def is_specific_study_text(value: Any) -> bool:
    return card_quality_is_specific_study_text(value)


def normalized_action_text(value: Any) -> str:
    return card_quality_normalized_action_text(value)


def cefr_rank(value: str) -> int:
    return card_quality_cefr_rank(value)


def is_too_basic_for_level(phrase: str, target_level: str) -> bool:
    return card_quality_is_too_basic_for_level(phrase, target_level)


def allows_function_start_phrase(phrase: str) -> bool:
    return card_quality_allows_function_start_phrase(phrase)


INCOMPLETE_FINAL_WORDS = card_quality_incomplete_final_words
INCOMPLETE_FINAL_CONTRACTIONS = card_quality_incomplete_final_contractions
SHORT_WH_FRAGMENT_STARTS = card_quality_short_wh_fragment_starts
SHORT_FRAGMENT_PRONOUN_ENDS = card_quality_short_fragment_pronoun_ends
ACCEPTABLE_FRAGMENT_ANSWERS = card_quality_acceptable_fragment_answers
BAD_INCOMPLETE_ANSWERS = card_quality_bad_incomplete_answers


def normalized_answer_key(value: Any) -> str:
    return card_quality_normalized_answer_key(value)


def looks_like_incomplete_answer_fragment(value: Any, card: dict[str, Any]) -> bool:
    return card_quality_looks_like_incomplete_answer_fragment(value, card)


def looks_like_truncated_listening_answer(value: Any, source_text: Any) -> bool:
    return card_quality_looks_like_truncated_listening_answer(value, source_text)


def phrase_guide_key(phrase: str) -> str:
    return card_quality_phrase_guide_key(phrase)


def score_text(text: str, level: str, toggles: dict[str, bool], collection_levels: list[str] | None = None) -> float:
    return source_text_score_text(text, level, toggles, collection_levels)


def resolved_max_segments(payload: dict[str, Any], cues: list[Cue] | None = None, text: str = "") -> int:
    raw = payload.get("max_segments", 24)
    try:
        requested = int(raw)
    except (TypeError, ValueError):
        requested = 0
    if requested > 0:
        return max(3, min(120, requested))

    duration = 0.0
    source_info = payload.get("source_info") or {}
    try:
        duration = float(source_info.get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    if not duration and cues:
        duration = max(cue.end for cue in cues)
    if duration:
        minutes = max(1.0, duration / 60.0)
        target = round(18 + minutes * 3.1)
        if duration <= 300:
            target = max(20, target)
        elif duration <= 720:
            target = max(32, target)
        elif duration <= 1500:
            target = max(45, target)
        else:
            target = max(60, target)
        subtitle_cap = max(12, int((len(cues or []) or target) * 0.55))
        return max(12, min(80, target, subtitle_cap))

    word_count = len(overlap_words(text))
    if word_count:
        return max(8, min(60, round(word_count / 180)))
    return 35


def load_export_subtitle_cues(project: dict[str, Any]) -> tuple[list[Cue], str, str]:
    source_info = project.get("source_info") if isinstance(project.get("source_info"), dict) else {}
    subtitle_path = clean_input_path(project.get("subtitle_path") or source_info.get("subtitle_path"))
    if not subtitle_path:
        return [], "", "subtitle_path_missing"
    path = Path(subtitle_path)
    if not path.exists():
        return [], str(path), "subtitle_path_not_found"
    try:
        return parse_srt(str(path)), str(path), "loaded"
    except SystemExit:
        return [], str(path), "subtitle_parse_failed"
    except Exception:
        return [], str(path), "subtitle_parse_failed"


def normalize_candidate_span(value: Any) -> str:
    return learning_span_normalize_candidate_span(value)


def expression_span_from_text(text: str, pattern: str) -> str:
    return learning_span_expression_span_from_text(text, pattern)


def usable_learning_point_span(
    text: str,
    span: str,
    candidate_kind: str = "expression",
    phrase_type: str = "",
) -> bool:
    return card_planning_usable_learning_point_span(text, span, candidate_kind, phrase_type)


def typed_candidate_score(base_score: float, boost: float, kind: str) -> float:
    if kind == "contextual_vocab":
        return max(3.0, base_score + boost)
    if kind == "grammar_pattern":
        return max(3.2, base_score + boost)
    if kind == "listening_feature":
        return max(2.9, base_score + boost)
    if kind == "pragmatic_risk":
        return max(3.6, base_score + boost)
    return max(3.0, base_score + boost)


def source_segment_key(start: float, end: float, text: str) -> str:
    return subtitle_source_segment_key(start, end, text)


def typed_learning_point_candidates(
    text: str,
    phrase: str,
    base_score: float,
    level: str,
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add_candidate(
        span: str,
        *,
        candidate_kind: str,
        phrase_type: str = "",
        normalized_answer: str = "",
        boost: float = 0.0,
        focus: str = "",
        source: str = "rule",
    ) -> None:
        if not candidate_kind_allowed_by_focus(candidate_kind, payload):
            return
        final_phrase_type = phrase_type or phrase_type_for_candidate_kind(candidate_kind)
        answer = normalize_candidate_span(normalized_answer or span)
        exact_span = normalize_candidate_span(span)
        if not usable_learning_point_span(text, exact_span, candidate_kind, final_phrase_type):
            return
        key = (answer.lower(), candidate_kind)
        if key in seen:
            return
        seen.add(key)
        content_kind = content_kind_for_phrase_type(final_phrase_type, "phrase")
        score = typed_candidate_score(base_score, boost, candidate_kind)
        candidates.append(
            {
                "phrase": answer,
                "exact_span": exact_span,
                "normalized_answer": answer,
                "answer_core": answer,
                "candidate_kind": candidate_kind,
                "phrase_type": final_phrase_type,
                "content_kind": content_kind,
                "candidate_source": source,
                "learning_point_schema_version": LEARNING_POINT_SCHEMA_VERSION,
                "phrase_card_focus": focus,
                "source_evidence": text,
                "score": score,
                "recommendation": min(5, max(1, round(score))),
            }
        )

    if phrase and usable_learning_point_span(text, phrase, "expression", ""):
        add_candidate(phrase, candidate_kind="expression", boost=0.2, focus="训练原句里的可迁移自然表达。", source="local_phrase")

    for pattern, phrase_type, kind, boost, focus in TYPED_EXPRESSION_PATTERNS:
        span = expression_span_from_text(text, pattern)
        if span:
            add_candidate(span, candidate_kind=kind, phrase_type=phrase_type, boost=boost, focus=focus)

    lower = text.lower()
    for pattern, answer, boost, focus in CONTEXTUAL_VOCAB_PATTERNS:
        if not re.search(pattern, lower, re.IGNORECASE):
            continue
        if answer == "register" and "run the register" not in lower:
            continue
        if answer == "add" and not re.search(r"\b(?:add|adds|added|adding)\s+ten\s+pounds\b", lower):
            continue
        exact = expression_span_from_text(text, pattern)
        add_candidate(
            exact or answer,
            candidate_kind="contextual_vocab",
            phrase_type="vocabulary_usage",
            normalized_answer=answer,
            boost=boost,
            focus=focus,
        )

    for pattern, answer, boost, focus in GRAMMAR_PATTERN_RULES:
        span = expression_span_from_text(text, pattern)
        if span:
            add_candidate(
                span,
                candidate_kind="grammar_pattern",
                phrase_type="grammar_pattern",
                normalized_answer=answer,
                boost=boost,
                focus=focus,
            )

    listening_match = LISTENING_FEATURE_RE.search(text)
    if listening_match and has_listening_training_value(text):
        add_candidate(
            listening_match.group(0),
            candidate_kind="listening_feature",
            phrase_type="listening_sentence",
            normalized_answer=normalize_candidate_span(listening_match.group(0)),
            boost=0.4,
            focus="训练弱读、缩读、连读或真实语速下的听辨。",
        )

    return sorted(candidates, key=lambda item: float(item.get("score") or 0), reverse=True)


def review_candidate_mode(payload: dict[str, Any], max_segments: int, candidate_limit: int) -> bool:
    return bool(payload.get("_candidate_limit") and candidate_limit > max_segments)


def learning_point_id_for_candidate(source_id: str, candidate: dict[str, Any]) -> str:
    kind = str(candidate.get("candidate_kind") or "expression")
    answer = str(candidate.get("normalized_answer") or candidate.get("phrase") or candidate.get("exact_span") or "")
    return f"lp_{stable_id(f'{source_id}:{kind}:{answer.lower()}') & 0xFFFFFFFF:08x}"


def build_segments(cues: list[Cue], payload: dict[str, Any]) -> list[dict[str, Any]]:
    language = normalize_learning_language(payload.get("language", "en"))
    level = payload.get("level", "B1")
    strategy = normalized_selection_strategy(payload)
    collection_levels = discovery_collection_levels(payload, level)
    toggles = payload.get("content_toggles", {})
    max_segments = resolved_max_segments(payload, cues)
    candidate_limit = int(payload.get("_candidate_limit", max_segments))
    review_mode = review_candidate_mode(payload, max_segments, candidate_limit)
    broad_discovery = strategy in {"catch_all", "exhaustive"}
    max_duration = 8.8 if strategy == "exhaustive" else 7.6 if broad_discovery else 6.4 if review_mode else 5.4
    max_words = 34 if strategy == "exhaustive" else 28 if broad_discovery else 22 if review_mode else 16
    min_discovery_score = 2.1 if strategy == "exhaustive" else 2.3 if broad_discovery else 2.6 if review_mode else 4.0
    min_candidate_score = 2.3 if strategy == "exhaustive" else 2.5 if broad_discovery else 2.8 if review_mode else 3.2
    min_context_score = 1.4 if strategy == "exhaustive" else 1.6 if broad_discovery else 1.8 if review_mode else 2.4

    candidates: list[dict[str, Any]] = []
    i = 0
    while i < len(cues):
        start = cues[i].start
        end = cues[i].end
        parts = [cues[i].text]
        j = i

        while end - start < 3.0 and j + 1 < len(cues):
            gap = cues[j + 1].start - end
            if gap > 0.9:
                break
            current_text = merge_subtitle_parts(parts)
            if looks_complete_sentence(current_text) and end - start >= 1.4:
                break
            next_text = strip_subtitle_text(cues[j + 1].text)
            if is_filler_text(next_text) and looks_complete_sentence(current_text):
                break
            j += 1
            end = cues[j].end
            parts.append(cues[j].text)

        text = clean_candidate_text(merge_subtitle_parts(parts))
        duration = end - start
        words = re.findall(r"[A-Za-z']+", text)
        unit_count = len(words)
        if unit_count == 0 and language != "en":
            compact_units = re.sub(r"\s+", "", text)
            unit_count = max(1, min(max_words, len(compact_units) // 2))
        if has_unbalanced_quotes(text):
            i = max(j + 1, i + 1)
            continue

        terminal_count = len(re.findall(r"[.?!]+", text))
        min_duration = 1.4 if looks_complete_sentence(text) else 2.5
        normal_window = min_duration <= duration <= max_duration and 4 <= unit_count <= max_words
        typed_window = 0.6 <= duration <= (8.8 if review_mode else 7.2) and 1 <= unit_count <= max(max_words, 30)
        if typed_window and terminal_count <= 1 and content_allowed(text, toggles):
            if looks_like_video_intro(text):
                i = max(j + 1, i + 1)
                continue
            if re.search(r"\[[^\]]+\]|\([^\)]*(music|applause|laugh)[^\)]*\)", text, re.IGNORECASE):
                i = max(j + 1, i + 1)
                continue
            if not re.search(r"[.?!][\"']?$", text) and any(mark in text for mark in ".?!"):
                i = max(j + 1, i + 1)
                continue
            score = score_text(text, level, toggles, collection_levels)
            phrase = find_phrase(text, level, collection_levels)
            phrase_is_usable = usable_phrase(text, phrase)
            typed_candidates = typed_learning_point_candidates(text, phrase, score, level, payload)
            if phrase_is_usable and is_too_basic_for_level(phrase, level):
                score -= 0.0 if strategy == "exhaustive" else 0.2 if strategy == "catch_all" else 0.4 if review_mode else 2.2
                typed_candidates = typed_learning_point_candidates(text, phrase, score, level, payload)
            if starts_like_fragment(text):
                if not review_mode and not phrase_is_usable and not typed_candidates:
                    i = max(j + 1, i + 1)
                    continue
                score -= 0.5
                typed_candidates = typed_learning_point_candidates(text, phrase, score, level, payload)
            if not normal_window and not typed_candidates:
                i = max(j + 1, i + 1)
                continue
            if score < min_context_score and not typed_candidates:
                i = max(j + 1, i + 1)
                continue
            if not phrase_is_usable:
                if phrase == "key expression" and score >= min_discovery_score:
                    # Vlogs and casual videos contain many useful spoken chunks that
                    # do not match our small local expression list. Keep strong short
                    # sentences and let the model decide whether a real phrase exists.
                    score = max(min_candidate_score, score - 0.6)
                else:
                    score -= 2.6
                if score < min_candidate_score and not typed_candidates:
                    i = max(j + 1, i + 1)
                    continue
            if not typed_candidates:
                typed_candidates = [
                    {
                        "phrase": phrase,
                        "exact_span": phrase,
                        "normalized_answer": phrase,
                        "answer_core": phrase if phrase != "key expression" else "",
                        "candidate_kind": "expression",
                        "phrase_type": "spoken_phrase",
                        "content_kind": "phrase",
                        "candidate_source": "legacy_phrase",
                        "learning_point_schema_version": LEARNING_POINT_SCHEMA_VERSION,
                        "phrase_card_focus": "围绕这个表达的真实语境和迁移用法制卡。",
                        "source_evidence": text,
                        "score": score,
                        "recommendation": min(5, max(1, round(score))),
                    }
                ]
            for typed in typed_candidates:
                segment_phrase = str(typed.get("exact_span") or typed.get("phrase") or phrase)
                media_start, media_end = segment_media_bounds(start, end, text, segment_phrase, review_mode)
                candidate_score = float(typed.get("score") or score)
                source_id = source_segment_key(start, end, text)
                learning_point_id = str(typed.get("id") or learning_point_id_for_candidate(source_id, typed))
                learning_point = {
                    "id": learning_point_id,
                    "kind": typed.get("candidate_kind") or "expression",
                    "exact_span": typed.get("exact_span") or segment_phrase,
                    "answer_core": typed.get("answer_core") or typed.get("normalized_answer") or typed.get("phrase") or segment_phrase,
                    "difficulty": level,
                    "value_score": round(candidate_score, 2),
                    "reason": typed.get("phrase_card_focus") or "",
                    "suggested_card_type": "listening" if typed.get("candidate_kind") == "listening_feature" else "phrase",
                    "content_kind": typed.get("content_kind") or "phrase",
                    "normalized_answer": typed.get("normalized_answer") or typed.get("phrase") or segment_phrase,
                    "source_evidence": typed.get("source_evidence") or text,
                    "language": language,
                }
                candidates.append(
                    {
                    "id": f"seg_{len(candidates) + 1:04d}",
                    "source_segment_id": source_id,
                    "learning_point_id": learning_point_id,
                    "learning_points": [learning_point],
                    "start": round(start, 3),
                    "end": round(end, 3),
                    "source_time": f"{fmt_time(start)} - {fmt_time(end)}",
                    "media_start": media_start,
                    "media_end": media_end,
                    "media_source_time": f"{fmt_time(media_start)} - {fmt_time(media_end)}",
                    "text": text,
                    "duration": round(duration, 2),
                    "recommendation": min(5, max(1, round(candidate_score))),
                    "phrase": typed.get("phrase") or segment_phrase,
                    "exact_span": typed.get("exact_span") or segment_phrase,
                    "normalized_answer": typed.get("normalized_answer") or typed.get("phrase") or segment_phrase,
                    "answer_core": typed.get("answer_core") or typed.get("normalized_answer") or typed.get("phrase") or segment_phrase,
                    "candidate_kind": typed.get("candidate_kind") or "expression",
                    "phrase_type": typed.get("phrase_type") or "spoken_phrase",
                    "content_kind": typed.get("content_kind") or "phrase",
                    "candidate_source": typed.get("candidate_source") or "rule",
                    "learning_point_schema_version": typed.get("learning_point_schema_version") or LEARNING_POINT_SCHEMA_VERSION,
                    "phrase_card_focus": typed.get("phrase_card_focus") or "",
                    "source_evidence": typed.get("source_evidence") or text,
                    "language": language,
                    "score": candidate_score,
                }
                )

        i = max(j + 1, i + 1)

    selected = sorted(candidates, key=lambda item: item["score"], reverse=True)[:candidate_limit]
    return sorted(selected, key=lambda item: item["start"])


def learning_point_from_segment(segment: dict[str, Any]) -> dict[str, Any]:
    source_id = str(segment.get("source_segment_id") or source_segment_key(float(segment.get("start") or 0), float(segment.get("end") or 0), str(segment.get("text") or "")))
    existing = segment.get("learning_points")
    if isinstance(existing, list) and existing:
        point = dict(existing[0])
    else:
        point = {}
    point_id = str(point.get("id") or segment.get("learning_point_id") or learning_point_id_for_candidate(source_id, segment))
    point.update(
        {
            "id": point_id,
            "kind": segment.get("candidate_kind") or point.get("kind") or "expression",
            "exact_span": segment.get("exact_span") or point.get("exact_span") or segment.get("phrase") or "",
            "answer_core": segment.get("answer_core")
            or point.get("answer_core")
            or segment.get("normalized_answer")
            or segment.get("phrase")
            or "",
            "difficulty": point.get("difficulty") or segment.get("difficulty") or "",
            "value_score": segment.get("phrase_value_score") or point.get("value_score") or segment.get("score"),
            "reason": point.get("reason") or segment.get("phrase_card_focus") or segment.get("phrase_decision_reason") or "",
            "suggested_card_type": point.get("suggested_card_type")
            or ("listening" if segment.get("candidate_kind") == "listening_feature" else "phrase"),
            "content_kind": segment.get("content_kind") or point.get("content_kind") or "phrase",
            "normalized_answer": segment.get("normalized_answer") or point.get("normalized_answer") or segment.get("phrase") or "",
            "source_evidence": segment.get("source_evidence") or point.get("source_evidence") or segment.get("text") or "",
        }
    )
    for key in PRONUNCIATION_FIELDS:
        if segment.get(key) not in (None, ""):
            point[key] = segment.get(key)
        elif point.get(key) not in (None, ""):
            point[key] = point.get(key)
    if segment.get("pronunciation_meta") not in (None, ""):
        point["pronunciation_meta"] = segment.get("pronunciation_meta")
    elif point.get("pronunciation_meta") not in (None, ""):
        point["pronunciation_meta"] = point.get("pronunciation_meta")
    is_valid, reason, normalized = sanitize_learning_point_contract(
        point,
        str(segment.get("text") or ""),
        language=segment.get("language", "English"),
    )
    if is_valid:
        point = normalized
    else:
        point["validation_status"] = "reject"
        point["validation_issues"] = [reason]
    return point


def group_segments_by_learning_points(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for segment in segments:
        key = str(segment.get("source_segment_id") or source_segment_key(float(segment.get("start") or 0), float(segment.get("end") or 0), str(segment.get("text") or "")))
        grouped.setdefault(key, []).append(segment)

    merged: list[dict[str, Any]] = []
    for source_id, items in grouped.items():
        ranked = sorted(items, key=lambda item: float(item.get("score") or 0), reverse=True)
        primary = dict(ranked[0])
        seen: set[tuple[str, str]] = set()
        points: list[dict[str, Any]] = []
        for item in ranked:
            point = learning_point_from_segment(item)
            if str(point.get("validation_status") or "") == "reject":
                continue
            key = (str(point.get("kind") or ""), normalized_phrase_key(str(point.get("answer_core") or point.get("exact_span") or "")))
            if key in seen:
                continue
            seen.add(key)
            points.append(point)
        primary["source_segment_id"] = source_id
        primary["learning_points"] = points
        if points:
            primary["learning_point_id"] = points[0]["id"]
        primary["recommendation"] = max(int(item.get("recommendation") or 1) for item in ranked)
        primary["score"] = max(float(item.get("score") or 0) for item in ranked)
        primary["cards"] = []
        merged.append(primary)
    return sorted(merged, key=lambda item: (float(item.get("start") or 0), str(item.get("id") or "")))


def fallback_phrase_fields(text: str, phrase: str, level: str) -> dict[str, str]:
    if not phrase or phrase == "key expression":
        return {
            "phrase": "",
            "chinese": "本地待审：这句需要先确认真正值得学习的表达。",
            "definition": "系统没有在原句中找到稳定、完整、可迁移的表达；建议用作听力待审，不要直接导出为表达卡。",
            "collocations": "",
            "context": "适合人工复核是否有听力难点或隐藏表达。",
            "example": text,
            "chinese_feel": "待精修：需要结合上下文改成自然中文。",
            "why": "缺少明确词伙时默认不推荐导出，避免把占位内容做成废卡。",
            "difficulty": CEFR_LABELS.get(level, level),
        }
    guide = PHRASE_GUIDES.get(phrase_guide_key(phrase), {})
    if guide:
        return {
            "phrase": phrase,
            "difficulty": CEFR_LABELS.get(level, level),
            "teacher_note": guide.get(
                "teacher_note",
                f"把 {phrase} 当作一个整体记；复习时先听懂原句，再换一个场景自己说一遍。",
            ),
            "_quality_source": "curated_fallback",
            **guide,
        }
    return {
        "phrase": phrase,
        "chinese": f"待精修：先把 {phrase} 当作本句目标表达。",
        "definition": f"本地待审：先把 {phrase} 当作本句目标表达，正式导出前需要用 AI 精修释义。",
        "collocations": f"{phrase} + natural object / use {phrase} in a complete sentence",
        "context": "本地待审字段：适合快速预览流程，不建议直接作为正式学习内容。",
        "example": text,
        "chinese_feel": "待精修：需要结合上下文改成自然中文。",
        "why": "本地 fallback 只保证结构完整；正式导出前应使用模型精修内容。",
        "difficulty": CEFR_LABELS.get(level, level),
    }


def phrase_in_text(text: str, phrase: str) -> bool:
    return learning_span_phrase_in_text(text, phrase)


def quality_issue_labels(
    card_type: str,
    text: str,
    phrase: str,
    cloze: str,
    source: str,
    content_kind: str = "",
    candidate_kind: str = "",
) -> tuple[int, list[str]]:
    is_listening = card_type == "listening"
    is_vocab = content_kind == "vocabulary" or candidate_kind == "contextual_vocab"
    is_grammar = content_kind == "grammar" or candidate_kind == "grammar_pattern"
    is_expression_like = not is_listening and not is_vocab and not is_grammar
    if source == "ai":
        score = 92
    elif source == "curated_fallback":
        score = 78
    else:
        score = 64 if is_listening else 52
    issues: list[str] = []
    words = overlap_words(phrase)
    text_words = overlap_words(text)
    trailing_prepositions = {"about", "of", "for", "to", "with", "from", "by", "at"}

    if source == "curated_fallback":
        issues.append("本地规则卡，需要人工确认")
        score -= 4
    elif source != "ai":
        issues.append("预览草稿，需要人工确认")
        score -= 18
    if not text_words:
        issues.append("缺少英文原句")
        score -= 34
    if not is_listening and (not phrase or phrase == "key expression"):
        issues.append("缺少明确目标表达")
        score -= 28
    if is_expression_like and len(words) < 2:
        issues.append("目标表达过短")
        score -= 14
    if is_expression_like and len(words) > 6:
        issues.append("目标表达偏长")
        score -= 24
    if is_expression_like and len(words) >= max(4, len(text_words) - 1) and len(text_words) >= 5:
        issues.append("目标表达像整句而不是词伙")
        score -= 28
    if len(text_words) > 15:
        issues.append("原句偏长")
        score -= 12
    if card_type in {"phrase", "cloze"} and len(text_words) > 12:
        issues.append("词伙任务原句太长")
        score -= 14
    if len(text_words) > 20:
        issues.append("原句太长，不适合做表达卡")
        score -= 18
    if starts_like_fragment(text):
        issues.append("原句像截断片段")
        score -= 18
    if ends_like_fragment(text):
        issues.append("原句疑似截断")
        score -= 54
    phrase_lower = phrase.lower()
    if is_expression_like and is_non_transferable_phrase(phrase_lower):
        issues.append("表达太像视频口播引入语")
        score -= 30
    if is_expression_like and is_low_value_standalone_phrase(phrase_lower):
        issues.append("目标表达太泛，学习价值低")
        score -= 26
    if looks_like_video_intro(text):
        issues.append("原句太像视频口播引入语")
        score -= 28
    allows_trailing_preposition = bool(
        re.search(r"\btell\s+\w+\s+about\b", phrase_lower)
        or phrase_lower
        in {
            "working with",
            "deal with",
            "talk about",
            "look for",
            "come up with",
            "get away with",
            "opening doors to",
            "connect with",
            "full of",
            "get used to",
            "feel free to",
            "in the mood for",
            "a bit of",
            "a couple of",
            "a lot of",
            "at the end of",
            "kind of",
            "sort of",
            "make the most of",
            "the kind of",
            "this kind of",
            "that kind of",
            "what do you think about",
            "how do you feel about",
            "prefer to see it as",
            "was thinking of",
            "apply heat to",
            "worked out of",
            "in the presence of",
            "i'd be willing to",
            "be willing to",
            "what's up for",
        }
    )
    if is_expression_like and words and words[-1] in trailing_prepositions and not allows_trailing_preposition:
        issues.append("表达像半截词串")
        score -= 18
    if is_expression_like and words and words[0] in COMMON_FUNCTION_STARTS and not allows_function_start_phrase(phrase):
        issues.append("表达可能从功能词开头")
        score -= 16
    if is_expression_like and words and words[0] == "about" and re.search(r"\babout\s+[A-Z0-9][A-Za-z0-9-]*", phrase):
        issues.append("表达像主题名而不是可迁移词伙")
        score -= 24
    if not is_listening and phrase and len(words) >= 2 and not phrase_in_text(text, phrase):
        issues.append("表达和原句不完全匹配")
        score -= 12
    if card_type == "cloze":
        blank_count = cloze.count("____")
        if blank_count != 1:
            issues.append("填空卡必须只有一个空")
            score -= 24
        if cloze.strip() == text.strip():
            issues.append("填空卡没有真正挖空")
            score -= 24
        if len(words) > 5:
            issues.append("填空答案偏长")
            score -= 10
    if is_filler_text(text):
        issues.append("句子太像 filler")
        score -= 30
    if len(text_words) < 4:
        issues.append("上下文太短")
        score -= 12

    return max(0, min(100, score)), issues


def quality_from_score(score: int, issues: list[str]) -> dict[str, Any]:
    serious_issues = {
        "缺少英文原句",
        "原句疑似截断",
        "原句证据边界需复核",
        "缺少明确目标表达",
        "表达像半截词串",
        "表达可能从功能词开头",
        "表达像主题名而不是可迁移词伙",
        "目标表达偏长",
        "目标表达像整句而不是词伙",
        "表达和原句不完全匹配",
        "填空卡必须只有一个空",
        "填空卡没有真正挖空",
        "字段疑似乱码",
        "缺少中文意思",
        "缺少释义",
        "句子太像 filler",
        "表达太像视频口播引入语",
        "原句太像视频口播引入语",
        "目标表达太泛，学习价值低",
        "字段像模板废话",
        "中文意思不是中文",
        "搭配不自然",
        "老师提示和学习理由重复",
        "老师提示缺少具体用法",
        "释义太泛",
        "AI 解释字段不足",
        "目标表达低于用户水平",
        "核心答案包含解释而不是英文答案",
        "核心答案像半截词串",
        "听力答案像截断片段",
        "词伙评审拒绝",
        "词伙重复合并",
    }
    has_serious_issue = any(issue in serious_issues for issue in issues)
    if score >= 78 and not issues:
        status = "recommended"
    elif score >= 72 and len(issues) <= 1 and not has_serious_issue:
        status = "recommended"
    elif score >= 42:
        status = "needs_review"
    else:
        status = "reject"
    return {"score": score, "status": status, "issues": issues}


def assess_card_quality(
    card: dict[str, Any],
    segment: dict[str, Any],
    source: str,
    target_level: str = "B1",
) -> dict[str, Any]:
    is_listening = card.get("type") == "listening"
    score, issues = quality_issue_labels(
        card.get("type", ""),
        card.get("english") or segment.get("text", ""),
        card.get("phrase", ""),
        card.get("cloze", ""),
        source,
        str(card.get("content_kind") or ""),
        str(card.get("candidate_kind") or ""),
    )
    source_quality_status = str(
        card.get("source_sentence_quality_status")
        or segment.get("source_sentence_quality_status")
        or ""
    ).strip()
    if source_quality_status == "needs_review" and "原句疑似截断" not in issues:
        issues.append("原句证据边界需复核")
        score -= 54
    text_fields = [
        card.get("english", ""),
        card.get("chinese", ""),
        card.get("phrase", ""),
        card.get("definition", ""),
        card.get("collocations", ""),
        card.get("context", ""),
        card.get("example", ""),
        card.get("chinese_feel", ""),
        card.get("why", ""),
        card.get("teacher_note", ""),
        card.get("learning_goal", ""),
        card.get("decision_reason", ""),
        card.get("learning_target", ""),
        card.get("why_it_matters", ""),
        card.get("how_to_use_it", ""),
    ]
    if any("???" in str(value) or "\ufffd" in str(value) for value in text_fields):
        issues.append("字段疑似乱码")
        score -= 36
    if str(card.get("validation_status") or "") == "reject":
        issues.append("学习点硬校验未通过")
        score -= 80
    answer_core = str(card.get("answer_core") or "").strip()
    displayed_answer_core = answer_display_text(answer_core)
    if (
        not is_listening
        and answer_core
        and (
            displayed_answer_core != clean_study_text(answer_core)
            or not is_answer_expression_candidate(displayed_answer_core, card)
        )
    ):
        issues.append("核心答案包含解释而不是英文答案")
        score -= 32
    if not is_listening and displayed_answer_core and looks_like_incomplete_answer_fragment(displayed_answer_core, card):
        issues.append("核心答案像半截词串")
        score -= 54
    if is_listening and displayed_answer_core and looks_like_truncated_listening_answer(
        displayed_answer_core,
        card.get("english") or segment.get("text", ""),
    ):
        issues.append("听力答案像截断片段")
        score -= 42
    field_blob = "\n".join(str(value or "") for value in text_fields)
    if has_template_noise(field_blob):
        issues.append("字段像模板废话")
        score -= 30
    chinese_value = str(card.get("chinese", "") or "").strip()
    if chinese_value and not has_cjk(chinese_value):
        issues.append("中文意思不是中文")
        score -= 22
    phrase_lower = re.sub(r"\s+", " ", str(card.get("phrase", "") or "").strip().lower())
    collocations_lower = str(card.get("collocations", "") or "").lower()
    if phrase_lower and f"not really {phrase_lower}" in collocations_lower and phrase_lower not in {"in the mood"}:
        issues.append("搭配不自然")
        score -= 24
    example_lower = re.sub(r"\s+", " ", str(card.get("example", "") or "").strip().lower())
    english_lower = re.sub(r"\s+", " ", str((card.get("english") or segment.get("text", "")) or "").strip().lower())
    if not is_listening and example_lower and english_lower and example_lower == english_lower:
        issues.append("例句只是照抄原句")
        score -= 14
    elif (
        not is_listening
        and example_lower
        and english_lower
        and len(overlap_words(example_lower)) >= 4
        and word_overlap_ratio(example_lower, english_lower) >= 0.82
    ):
        issues.append("例句和原句过于相似")
        score -= 14
    if not str(card.get("chinese", "")).strip():
        issues.append("缺少中文意思")
        score -= 22
    if card.get("type") in {"phrase", "cloze"} and not str(card.get("definition", "")).strip():
        issues.append("缺少释义")
        score -= 18
    if card.get("type") in {"phrase", "cloze"} and has_generic_definition(str(card.get("definition", ""))):
        issues.append("释义太泛")
        score -= 20
    if source == "ai" and card.get("type") in {"phrase", "cloze"}:
        has_specific_meaning = any(
            is_specific_study_text(value) and has_cjk(str(value))
            for value in [
                card.get("chinese", ""),
                card.get("natural_chinese", ""),
                card.get("chinese_feel", ""),
            ]
        )
        has_specific_usage = any(
            is_specific_study_text(value)
            for value in [
                card.get("definition", ""),
                card.get("how_to_use_it", ""),
                card.get("context", ""),
            ]
        )
        has_specific_guidance = any(
            is_specific_study_text(value)
            for value in [
                card.get("teacher_note", ""),
                card.get("usage_boundary", ""),
                card.get("confusable_note", ""),
                card.get("collocations", ""),
                card.get("replacement_examples", ""),
            ]
        )
        if not (has_specific_meaning and has_specific_usage and has_specific_guidance):
            issues.append("AI 解释字段不足")
            score = min(score, 66)
    teacher_note = str(card.get("teacher_note", "") or "").strip()
    if len(teacher_note) < 8:
        issues.append("老师提示太薄")
        score -= 8
    if teacher_note and has_generic_teacher_note(teacher_note):
        issues.append("老师提示缺少具体用法")
        score -= 18
    comparable_teacher_note = re.sub(r"\s+", " ", teacher_note)
    for key in ["why", "context", "chinese_feel"]:
        comparable_value = re.sub(r"\s+", " ", str(card.get(key, "") or "").strip())
        if not is_listening and comparable_teacher_note and comparable_value and comparable_teacher_note == comparable_value:
            issues.append("老师提示和学习理由重复")
            score -= 14
            break
        if (
            not is_listening
            and comparable_teacher_note
            and comparable_value
            and min(len(overlap_words(comparable_teacher_note)), len(overlap_words(comparable_value))) >= 6
            and word_overlap_ratio(comparable_teacher_note, comparable_value) >= 0.86
        ):
            issues.append("老师提示和学习理由重复")
            score -= 14
            break
    action_fields = [
        card.get("learning_goal", ""),
        card.get("decision_reason", ""),
        card.get("phrase_card_focus", ""),
        card.get("learning_target", ""),
        card.get("how_to_use_it", ""),
    ]
    if source == "ai" and not any(str(value or "").strip() for value in action_fields):
        issues.append("卡片训练点不明确")
        score -= 10
    if not is_listening and is_too_basic_for_level(phrase_lower, target_level):
        issues.append("目标表达低于用户水平")
        score -= 30
    difficulty_rank = cefr_rank(str(card.get("difficulty", "")))
    target_rank = cefr_rank(target_level)
    if target_rank >= cefr_rank("B1") and 0 <= difficulty_rank <= cefr_rank("A1"):
        issues.append("难度低于用户水平")
        score -= 18
    review_status = str(card.get("phrase_review_status") or segment.get("phrase_review_status") or "").strip()
    phrase_value_score = phrase_review_score(card.get("phrase_value_score", segment.get("phrase_value_score")))
    if review_status == "needs_review" or phrase_value_score == 3:
        issues.append("词伙评审待审")
        score = min(score, 70)
    elif review_status == "reject" or (0 < phrase_value_score < 3):
        issues.append("词伙评审拒绝")
        score = min(score, 34)
    elif review_status == "duplicate":
        issues.append("词伙重复合并")
        score = min(score, 34)
    elif phrase_value_score >= 4 and not issues:
        score = min(100, score + 4)
    return quality_from_score(score, issues)


def make_cloze(text: str, phrase: str) -> str:
    if not phrase:
        return text
    pattern = re.compile(re.escape(phrase), re.IGNORECASE)
    if pattern.search(text):
        return pattern.sub("____", text, count=1)
    words = re.findall(r"[A-Za-z']+", text)
    if words:
        return re.sub(re.escape(words[-1]), "____", text, count=1, flags=re.IGNORECASE)
    return "____"


def phrase_allows_trailing_preposition(phrase: str) -> bool:
    return card_quality_phrase_allows_trailing_preposition(phrase)


def usable_phrase(text: str, phrase: str) -> bool:
    return phrase_discovery_usable_phrase(text, phrase)


def choose_best_phrase(text: str, proposed: str, fallback: str, level: str, collection_levels: list[str] | None = None) -> str:
    return phrase_discovery_choose_best_phrase(text, proposed, fallback, level, collection_levels)


def repair_card_fields(card: dict[str, Any], segment: dict[str, Any], level: str) -> None:
    card["language"] = normalize_learning_language(segment.get("language", card.get("language") or "en"))
    text = card.get("english") or segment.get("text", "")
    reviewed_phrase = str(segment.get("phrase") or "").strip()
    candidate_kind = str(card.get("candidate_kind") or segment.get("candidate_kind") or "")
    phrase_type = str(card.get("phrase_type") or segment.get("phrase_type") or "")
    if not candidate_kind:
        candidate_kind = candidate_kind_for_phrase_type(phrase_type, candidate_kind_for_segment(segment))
    preferred_phrase = (
        str(card.get("normalized_answer") or "").strip()
        or str(card.get("answer_core") or "").strip()
        or str(card.get("phrase") or "").strip()
        or str(segment.get("normalized_answer") or "").strip()
        or reviewed_phrase
    )
    if usable_learning_point_span(text, preferred_phrase, candidate_kind, phrase_type):
        phrase = normalize_candidate_span(preferred_phrase)
    elif segment.get("phrase_review_source") in {"mimo", "ai"} and usable_learning_point_span(text, reviewed_phrase, candidate_kind, phrase_type):
        phrase = reviewed_phrase
    elif candidate_kind in {"contextual_vocab", "grammar_pattern", "listening_feature"}:
        phrase = normalize_candidate_span(reviewed_phrase or str(card.get("phrase") or ""))
    else:
        phrase = choose_best_phrase(text, card.get("phrase", ""), segment.get("phrase", ""), level)
    if phrase != card.get("phrase"):
        card["phrase"] = phrase
    if candidate_kind:
        card["candidate_kind"] = candidate_kind
    if not str(card.get("exact_span") or "").strip():
        card["exact_span"] = str(segment.get("exact_span") or phrase)
    if not str(card.get("normalized_answer") or "").strip():
        card["normalized_answer"] = str(segment.get("normalized_answer") or phrase)
    sanitized_answer = answer_display_text(card.get("answer_core"))
    if not is_answer_expression_candidate(sanitized_answer, card):
        sanitized_answer = phrase if is_answer_expression_candidate(phrase, card) else ""
    if sanitized_answer:
        card["answer_core"] = sanitized_answer
    elif str(card.get("type") or "") != "listening":
        existing_validation_issues = card.get("validation_issues")
        if isinstance(existing_validation_issues, list):
            validation_issues = existing_validation_issues
        elif existing_validation_issues:
            validation_issues = [str(existing_validation_issues)]
        else:
            validation_issues = []
        card["validation_status"] = "reject"
        card["validation_issues"] = list(dict.fromkeys([*validation_issues, "answer_core 不是目标语言学习对象"]))
    pronunciation_issues = sanitize_pronunciation_fields(card, segment.get("language", "English"))
    if pronunciation_issues:
        existing_issues = card.get("validation_issues")
        if isinstance(existing_issues, list):
            card["validation_issues"] = list(dict.fromkeys([*existing_issues, *pronunciation_issues]))
        elif existing_issues:
            card["validation_issues"] = [str(existing_issues), *pronunciation_issues]
        else:
            card["validation_issues"] = pronunciation_issues
    if str(card.get("type") or "") != "knowledge":
        contract = {
            "kind": card.get("candidate_kind") or segment.get("candidate_kind") or candidate_kind_for_segment(segment),
            "phrase_type": card.get("phrase_type") or segment.get("phrase_type") or "",
            "exact_span": card.get("exact_span") or phrase,
            "normalized_answer": card.get("normalized_answer") or phrase,
            "answer_core": card.get("answer_core") or phrase,
            "phrase": card.get("phrase") or phrase,
            "content_kind": card.get("content_kind") or "",
            "language": card.get("language"),
        }
        for key in PRONUNCIATION_FIELDS:
            if card.get(key):
                contract[key] = card.get(key)
        if card.get("pronunciation_meta"):
            contract["pronunciation_meta"] = card.get("pronunciation_meta")
        is_valid_contract, contract_reason, normalized_contract = sanitize_learning_point_contract(
            contract,
            str(text or ""),
            language=card.get("language", segment.get("language", "en")),
        )
        if is_valid_contract:
            for key in [
                "exact_span",
                "normalized_answer",
                "answer_core",
                "candidate_kind",
                "phrase_type",
                "content_kind",
                "phonetic_ipa",
                "spoken_ipa",
                "source_spoken_ipa",
                "pronunciation_note",
                "pronunciation_confidence",
                "pronunciation_status",
                "source_pronunciation_status",
                "pronunciation_meta",
                "validation_status",
            ]:
                if normalized_contract.get(key) not in (None, ""):
                    card[key] = normalized_contract[key]
            if normalized_contract.get("validation_issues"):
                card["validation_issues"] = normalized_contract["validation_issues"]
        else:
            existing_issues = card.get("validation_issues")
            if isinstance(existing_issues, list):
                validation_issues = existing_issues
            elif existing_issues:
                validation_issues = [str(existing_issues)]
            else:
                validation_issues = []
            card["validation_status"] = "reject"
            card["validation_issues"] = list(dict.fromkeys([*validation_issues, contract_reason]))
    estimated_level = str(card.get("estimated_level") or "").strip().upper()
    if estimated_level not in CEFR_ORDER:
        difficulty_match = re.search(r"\b(A1|A2|B1|B2|C1|C2)\b", str(card.get("difficulty") or "").upper())
        estimated_level = difficulty_match.group(1) if difficulty_match else (level if level in CEFR_ORDER else "B1")
    card["estimated_level"] = estimated_level
    if not str(card.get("difficulty_reason") or "").strip():
        card["difficulty_reason"] = "系统根据表达本身、语境和听力/迁移难度估计。"
    card["cloze"] = make_cloze(text, phrase)


def normalized_contains_text(haystack: Any, needle: Any) -> bool:
    return learning_actions_normalized_contains_text(haystack, needle)


def learning_action_for_card(card: dict[str, Any]) -> str:
    return learning_actions_learning_action_for_card(card)


def normalize_learning_action_fields(card: dict[str, Any]) -> None:
    learning_actions_normalize_learning_action_fields(card)


def requested_card_types(card_types: list[str]) -> list[str]:
    return card_planning_requested_card_types(card_types)


def has_listening_training_value(text: str) -> bool:
    return card_planning_has_listening_training_value(text)


def has_output_training_value(phrase: str, level: str) -> bool:
    return card_planning_has_output_training_value(phrase, level)


def plan_card_types(segment: dict[str, Any], card_types: list[str], level: str) -> dict[str, Any]:
    return card_planning_plan_card_types(segment, card_types, level)


def card_type_for_learning_point(point: dict[str, Any], requested: list[str]) -> str:
    return card_planning_card_type_for_learning_point(point, requested)


def fallback_cards(segment: dict[str, Any], card_types: list[str], level: str) -> list[dict[str, Any]]:
    requested = requested_card_types(card_types)
    points = segment.get("learning_points")
    if not isinstance(points, list) or not points:
        points = [learning_point_from_segment(segment)]
    cards: list[dict[str, Any]] = []
    for index, raw_point in enumerate(points):
        point = dict(raw_point)
        point_answer = normalized_phrase_key(
            str(point.get("answer_core") or point.get("normalized_answer") or point.get("exact_span") or segment.get("phrase") or "")
        )
        if point_answer in {"", "key expression"}:
            point["kind"] = "listening_feature"
            point["phrase_type"] = "listening_sentence"
            point["content_kind"] = "listening"
            point["suggested_card_type"] = "phrase"
            point["exact_span"] = segment.get("text", "")
            point["normalized_answer"] = segment.get("text", "")
            point["answer_core"] = segment.get("text", "")
        is_valid_point, point_reason, normalized_point = sanitize_learning_point_contract(
            point,
            str(segment.get("text") or ""),
            language=segment.get("language", "English"),
        )
        if is_valid_point:
            point = normalized_point
        else:
            segment.setdefault("learning_point_reject_reasons", []).append(point_reason)
            continue
        answer = str(point.get("answer_core") or point.get("normalized_answer") or point.get("exact_span") or segment.get("phrase") or "")
        fields = fallback_phrase_fields(segment["text"], answer, level)
        quality_source = fields.pop("_quality_source", "fallback")
        phrase_type = phrase_type_for_candidate_kind(str(point.get("kind") or segment.get("candidate_kind") or "expression"))
        content_kind = str(point.get("content_kind") or content_kind_for_phrase_type(phrase_type))
        card_type = card_type_for_learning_point(point, requested)
        learning_point_id = str(point.get("id") or segment.get("learning_point_id") or f"{segment['id']}_lp_{index + 1}")
        reason = str(point.get("reason") or segment.get("phrase_card_focus") or "围绕这个学习点制卡。")
        card = {
            "id": f"{segment['id']}_{learning_point_id}_{card_type}",
            "type": card_type,
            "type_label": CARD_TYPE_LABELS.get(card_type, card_type),
            "enabled": False,
            "english": segment["text"],
            "chinese": "预览草稿：请先用模型精修或手动改成自然中文。",
            "cloze": make_cloze(segment["text"], answer or fields["phrase"]),
            "teacher_note": fields.get("teacher_note") or fields["why"],
            "card_role": "primary" if index == 0 else "learning_point",
            "learning_goal": reason,
            "decision_reason": reason,
            "learning_target": reason,
            "learning_action": learning_action_for_card({**point, "candidate_kind": point.get("kind") or segment.get("candidate_kind") or candidate_kind_for_segment(segment), "phrase_type": phrase_type, "content_kind": content_kind}),
            "conceptual_action": point.get("conceptual_action") or "",
            "chinese_learner_trap": point.get("chinese_learner_trap") or point.get("confusable_note") or "",
            "why_it_matters": fields.get("why", ""),
            "how_to_use_it": fields.get("context", ""),
            "natural_chinese": fields.get("chinese", ""),
            "estimated_level": level if level in CEFR_ORDER else "B1",
            "difficulty_reason": "根据表达本身、原句语境和迁移难度估计。",
            "replacement_examples": fields.get("collocations", ""),
            "avoid_reason": "",
            "skipped_card_types": {},
            "phrase_value_score": segment.get("phrase_value_score"),
            "phrase_decision_reason": segment.get("phrase_decision_reason", ""),
            "phrase_reject_reason": segment.get("phrase_reject_reason", ""),
            "phrase_card_focus": reason,
            "phrase_review_status": segment.get("phrase_review_status", ""),
            "phrase_type": phrase_type,
            "learning_point_id": learning_point_id,
            "content_kind": content_kind,
            "candidate_kind": point.get("kind") or segment.get("candidate_kind") or candidate_kind_for_segment(segment),
            "exact_span": point.get("exact_span") or segment.get("exact_span") or answer,
            "normalized_answer": point.get("normalized_answer") or segment.get("normalized_answer") or answer,
            "candidate_source": segment.get("candidate_source", ""),
            "learning_point_schema_version": segment.get("learning_point_schema_version") or LEARNING_POINT_SCHEMA_VERSION,
            "source_evidence": point.get("source_evidence") or segment.get("source_evidence") or segment.get("text", ""),
            "source_sentence_quality_flags": segment.get("source_sentence_quality_flags") or [],
            "source_sentence_quality_status": segment.get("source_sentence_quality_status") or "",
            "retrieval_prompt": "",
            "answer_core": answer,
            "language": normalize_learning_language(segment.get("language", "en")),
            "usage_boundary": point.get("usage_boundary") or "",
            "confusable_note": point.get("confusable_note") or "",
            "phonetic_ipa": point.get("phonetic_ipa") or "",
            "spoken_ipa": point.get("spoken_ipa") or "",
            "source_spoken_ipa": point.get("source_spoken_ipa") or "",
            "pronunciation_note": point.get("pronunciation_note") or "",
            "pronunciation_confidence": point.get("pronunciation_confidence") or "",
            "pronunciation_status": point.get("pronunciation_status") or "",
            "source_pronunciation_status": point.get("source_pronunciation_status") or "",
            "pronunciation_meta": point.get("pronunciation_meta") or None,
            **fields,
        }
        sanitize_pronunciation_fields(card, segment.get("language", "English"))
        if card_type == "phrase":
            card["type_label"] = card_label_for_learning_card(
                str(card.get("phrase_type") or ""),
                str(card.get("content_kind") or ""),
                card["type_label"],
            )
        card_quality_source = quality_source if card_type == "phrase" else "fallback"
        card["quality"] = assess_card_quality(card, segment, card_quality_source, level)
        if card_quality_source == "fallback" and card["quality"]["status"] == "reject":
            local_draft_issues = {
                "本地草稿，需要人工确认",
                "预览草稿，需要人工确认",
                "字段像模板废话",
                "目标表达像整句而不是词伙",
                "例句只是照抄原句",
                "老师提示和学习理由重复",
            }
            if set(card["quality"].get("issues", [])) <= local_draft_issues:
                card["quality"]["status"] = "needs_review"
                card["quality"]["score"] = max(42, int(card["quality"].get("score") or 0))
        card["enabled"] = card_quality_source == "curated_fallback" and card["quality"]["status"] == "recommended"
        cards.append(card)
    return cards


def pronunciation_prompt_instruction(language_code: str) -> str:
    profile = pronunciation_profile(language_code)
    common = (
        "发音字段使用 legacy key，但 UI 会显示为标准读法/推测口语读法/推测原句读法："
        f"pronunciation_meta 必须包含 language_code={profile['code']}、accent_profile={profile['accent_profile']}、"
        f"notation_system={profile['notation_system']}、generation_basis、field_confidence、same_as_standard_reason、validation_issues。"
        "V1 没有音频实听/ASR/forced alignment；除非输入明确提供实听证据，否则 generation_basis 必须是 subtitle_inferred，"
        "spoken_ipa 和 source_spoken_ipa 的 confidence 不能为 high，不得声称“剧中实际读作”。"
        "如果只能给标准读法，generation_basis=dictionary_only，spoken_ipa 留空。"
        "source_spoken_ipa 必须覆盖完整原句的主要词/音节，不能只覆盖 answer_core。"
        "如果 spoken_ipa 与 phonetic_ipa 相同，必须填写 same_as_standard_reason。"
        "pronunciation_note 只写真正的发音教学内容，例如弱读、连读、重音、音变；"
        "不要把“未实听”“按字幕推测”“原句听感未可靠生成”“已隐藏”等系统状态写进 pronunciation_note。"
    )
    by_language = {
        "en": (
            "English：phonetic_ipa 用词典式美式 IPA；spoken_ipa 是字幕推测口语读法，可用 IPA + weak forms/linking/stress；"
            "source_spoken_ipa 不推荐只有一长串 IPA，最好体现学习者可读的弱读、连读和重音听感。"
        ),
        "fr": (
            "French：使用 API/IPA，标 liaison、enchaînement、e caduc；不要机械添加所有 liaison，区分必连、可连、禁连。"
        ),
        "es": (
            "Spanish：accent_profile 必须是 es-LatAm-general-MX-like；默认不用 /θ/；"
            "标准读法尽量给音节+重音，可附 IPA；s 弱化、d 省略、Rioplatense y/ll 只有 profile 或音频支持时才标。"
        ),
        "ja": (
            "Japanese：phonetic_ipa 字段实际存“假名+可选音高”；必须给假名。音高只在可靠时标，"
            "不确定则 pitch_confidence=unknown 或 low，不得硬标 ꜜ。"
        ),
        "ru": (
            "Russian：phonetic_ipa 字段实际存“带重音西里尔+可选 IPA”；多音节实词必须标重音，ё 视为有重音；"
            "重音不确定时仍可给最可能读法，但该字段 confidence 必须 low 并说明原因。"
        ),
    }
    return common + by_language.get(language_code, by_language["en"])


def build_fast_review_prompt(project: dict[str, Any], segments: list[dict[str, Any]]) -> str:
    requested_types = requested_card_types([str(card_type) for card_type in project.get("card_types", []) if card_type])
    current_level = str(project.get("level", "B1"))
    level_mode = normalized_level_mode(project)
    language_code = normalize_learning_language(project.get("language", "en"))
    profile = pronunciation_profile(language_code)
    material_context_instruction = material_context_for_prompt(project.get("material_context"))
    focus_instruction = language_focus_instruction(project)
    compact = [
        {
            "id": segment["id"],
            "source_time": segment["source_time"],
            "english": segment["text"],
            "phrase_hint": segment.get("phrase") or segment.get("answer_core") or "",
            "exact_span": segment.get("exact_span", ""),
            "answer_core": segment.get("answer_core") or segment.get("normalized_answer") or "",
            "candidate_kind": segment.get("candidate_kind", ""),
            "phrase_type": segment.get("phrase_type", ""),
            "learning_point_id": segment.get("learning_point_id", ""),
            "learning_points": [
                {
                    "id": point.get("id"),
                    "answer_core": point.get("answer_core") or point.get("exact_span") or "",
                    "exact_span": point.get("exact_span") or "",
                    "candidate_kind": point.get("candidate_kind") or "",
                    "phrase_type": point.get("phrase_type") or "",
                    "learning_action": point.get("learning_action") or "",
                    "reason": point.get("reason") or point.get("status_reason") or "",
                }
                for point in segment.get("learning_points", [])
                if isinstance(point, dict)
            ],
        }
        for segment in segments
    ]
    return (
        f"你是给中文母语者做 {profile['label']} Anki 卡的语言老师。"
        "【快速复读模式：真正减少 token】用户要的是沉浸复读的轻量版，不是完整复读精学卡。"
        "目标：减少 token、减少等待时间、减少审核负担。"
        "每张卡只生成最小复习字段：type、learning_point_id、candidate_kind、exact_span、phrase、answer_core、english、chinese、definition、chinese_feel、teacher_note、retrieval_prompt。"
        "不要输出长段落；teacher_note 最多一句 18-36 个中文字；definition 最多一句 20-40 个中文字。"
        "definition/context/example/collocations/why/why_it_matters/how_to_use_it/usage_boundary/confusable_note/replacement_examples 这些字段能不写就不写；不要为了填字段而扩写。"
        "优先让背面只有：答案、当前语境义、原句、一个很短提醒。"
        f"{material_context_instruction}"
        f"{focus_instruction}"
        "只围绕 learning_points[].id 制卡；同一个 learning_point 最多 1 张卡。"
        "phrase 必须逐词来自原句；answer_core 只写目标语言答案本体，不写中文解释。"
        "如果学习点低价值或无法做成清楚回忆题，返回该片段 cards: []。"
        f"学习语言：{profile['label']}（code={language_code}）。level_mode：{level_mode}。用户水平：{current_level}。"
        f"需要卡型：{', '.join(requested_types)}。快速模式默认优先 phrase 主卡，除非 learning_point 明确是听力或填空。"
        "每个输出 segment.id 必须逐字复制对应输入 segment.id；禁止从 seg_0001 或 seg_lp_0001 重新编号。"
        "每张卡的 learning_point_id 也必须逐字复制输入 learning_points[].id。"
        "输出 segment 数必须和输入 segment 数相同；不制卡也要保留原 id 并返回 cards: []。"
        "返回严格 JSON，不要 Markdown。JSON 结构："
        "{\"segments\":[{\"id\":\"COPY_EXACT_INPUT_SEGMENT_ID\",\"cards\":[{\"type\":\"phrase|listening|cloze\",\"learning_point_id\":\"对应 learning_points[].id\",\"candidate_kind\":\"expression|contextual_vocab|grammar_pattern|listening_feature|pragmatic_risk\",\"exact_span\":\"来自原句的片段\",\"phrase\":\"重点表达或单词\",\"answer_core\":\"核心答案\",\"english\":\"原句\",\"chinese\":\"语境中文义\",\"definition\":\"一句短释义\",\"chinese_feel\":\"一句中文语感\",\"teacher_note\":\"一句短提醒\",\"retrieval_prompt\":\"正面明确回忆题\"}]}]}。"
        "候选字幕_JSON_START\n"
        + json.dumps(compact, ensure_ascii=False)
    )


def build_immersive_v11_prompt(project: dict[str, Any], segments: list[dict[str, Any]]) -> str:
    if fast_review_density(project):
        return build_fast_review_prompt(project, segments)
    requested_types = requested_card_types([str(card_type) for card_type in project.get("card_types", []) if card_type])
    current_level = str(project.get("level", "B1"))
    level_mode = normalized_level_mode(project)
    language_code = normalize_learning_language(project.get("language", "en"))
    profile = pronunciation_profile(language_code)
    collection_levels = collection_levels_from_payload(project, current_level)
    selection_strategy = normalized_selection_strategy(project)
    focus_instruction = language_focus_instruction(project)
    material_context_instruction = material_context_for_prompt(project.get("material_context"))
    fast_review_instruction = fast_review_prompt_instruction(project)
    compact = [
        {
            "id": segment["id"],
            "source_time": segment["source_time"],
            "english": segment["text"],
            "phrase_hint": segment["phrase"],
            "exact_span": segment.get("exact_span", ""),
            "normalized_answer": segment.get("normalized_answer", ""),
            "candidate_kind": segment.get("candidate_kind", ""),
            "recommendation": segment["recommendation"],
            "phrase_value_score": segment.get("phrase_value_score"),
            "phrase_review_status": segment.get("phrase_review_status", ""),
            "phrase_decision_reason": segment.get("phrase_decision_reason", ""),
            "phrase_card_focus": segment.get("phrase_card_focus", ""),
            "phrase_type": segment.get("phrase_type", ""),
            "score_breakdown": segment.get("score_breakdown", {}),
            "learning_points": segment.get("learning_points", []),
        }
        for segment in segments
    ]
    return (
        f"你是给中文母语者做 {profile['label']} Anki 卡的资深老师。目标不是多写信息，而是让学习者翻面后立刻知道："
        "这句我该听懂什么、该记住哪个表达、以后怎么自己用。"
        "你不是字段填写器，而是语言学习卡片编辑老师：先判断学习价值，再决定是否制卡，最后自检这张卡是不是有明确训练动作。"
        "JSON 字段 english 是历史字段名，实际表示目标语言原句/source sentence。"
        f"{material_context_instruction}"
        f"{fast_review_instruction}"
        "制卡前请在心里回答四个问题：这句最值得学的是什么？它是词伙、句型、口语短句、语气表达还是听力句？"
        "中文学习者为什么容易忽略它？这张卡训练听懂、会用、会替换还是理解语气？如果回答不清楚，返回 cards: []。"
        f"{focus_instruction}"
        "候选现在按 typed learning point / learning_points 分组：同一句可能同时包含 expression/contextual_vocab/grammar_pattern/listening_feature/pragmatic_risk。"
        "制卡必须先尊重每个 learning_point 的 id、kind 和 exact_span，再生成对应卡片；不要把所有候选都当词伙。"
        "同一句的不同学习点可以共存；只有 exact_span、answer_core 和训练动作实质重复时才合并。"
        "contextual_vocab 允许 answer_core 是一个英文单词；grammar_pattern 允许 answer_core 是句型框架；"
        "listening_feature 的 answer_core 是要听辨的英文片段或原句，不是发音解释。"
        "请只为真正值得复习的片段生成卡；如果片段只是主题介绍、专有名词、技术名词堆叠或没有可迁移表达，返回该片段的 cards: []。"
        "内容标准："
        "1) phrase 必须来自原句：词伙通常 2-6 个词；单词用法可以是 1 个核心词；语法框架可以是原句里的可替换结构。"
        "它不能是整句、半截词串、产品名、主题名或 working with 这种孤立泛表达。"
        "如果候选里有 phrase_review_status 和 phrase_value_score，说明 AI 已经做过候选评审；正式制卡必须优先使用 phrase_hint，"
        "除非你能从同一句 english 里找到更完整、更可迁移的替代表达。替代表达仍必须逐词出现在原句里。"
        "如果 phrase_hint 是 key expression，说明本地规则没有识别出词伙；请你从 english 中自己选择最值得学的完整表达。"
        "如果句子里确实没有可迁移表达，返回该片段 cards: []，不要硬凑。"
        "如果用户水平是 B1 或更高，不要把 talk about 这类 A1/A2 基础短语当作重点；没有更具体表达就返回 cards: []。"
        "优先真实生活中可复用的短句、句型和口语框架，例如 it feels like、it turns out、what happens next、in the mood for、"
        "at some point、not because..., but because...、the thing is、I see what you mean、such a nice...。"
        "2) chinese 写 phrase 或单词在这句里的核心中文义，适合放在答案下方，例如“负责收银 / 操作收银机”；"
        "natural_chinese 写整句自然中文译文，例如“I’m gonna run the register.”=>“我来负责收银。”。"
        "3) definition 要写“怎么用”：这个表达通常用在什么动作/场景/对象上，面向学习者，不要词典腔，不要模板句。"
        "4) collocations 只能给自然搭配、句型框架或 1-2 个可直接模仿的新句子，用 ' / ' 分隔；不要编造不自然搭配，比如 not really + 任意 phrase。"
        "5) example 必须是新的短例句，不能照抄原句。"
        "6) context 说明什么场景会用；chinese_feel 说明中文语感；why 说明为什么值得学。每项 1 句即可。"
        "7) teacher_note 要服务同一张学习卡：把听辨提醒、迁移用法、挖空理由和边界提示合并成一句短提醒，不要拆成多张相似卡。"
        "8) 每张卡还必须给学习动作字段：learning_target=这张卡训练什么；why_it_matters=为什么值得学；"
        "how_to_use_it=下次怎么换场景使用；natural_chinese=原句自然中文译文；replacement_examples=1-2 个可替换例子；"
        "avoid_reason=不值得制卡时的原因。how_to_use_it 和 replacement_examples 必须是可以直接放进卡片背面的自然内容，"
        "不要写 natural object、complete sentence、use X in a sentence 这种占位说明。"
        "9) 每张卡必须给复习字段：retrieval_prompt=正面明确回忆题，不能写“判断最值得学”；"
        f"answer_core=翻面第一眼核对的核心答案，只能写 {profile['label']} 表达/单词本体，例如 hold that against you；"
        "禁止在 answer_core 写中文释义、IPA、发音融合、连读说明、语法解释或“X 是 Y”的说明；这些放 teacher_note 或 confusable_note。"
        f"{pronunciation_prompt_instruction(language_code)}"
        "pronunciation_note=一句中文听点说明；pronunciation_confidence=high|medium|low，必须等于发音字段最低置信度。"
        "读法标注只写在 phonetic_ipa/spoken_ipa/source_spoken_ipa/pronunciation_note/pronunciation_meta，不能写进 answer_core、phrase 或 TTS 文本。"
        "usage_boundary=什么时候能用/不能用，尤其是调侃、冒犯、正式度；"
        "confusable_note=中文学习者最容易误解或误用的点。usage_boundary 和 confusable_note 要具体到这句的语气、对象、场景，"
        "不要写“注意语境”“很常见”这类空话。"
        "10) 每张卡必须输出 estimated_level=A1|A2|B1|B2|C1|C2，以及 difficulty_reason=一句中文说明难点来源。"
        "如果 level_mode=auto，请根据表达本身、原句语境、听力难点和迁移难度估计每张卡难度；"
        "如果 level_mode=manual，用户水平只作为解释深度和筛选倾向，不是硬过滤。"
        "学习卡 retrieval_prompt 要问一个明确的主动回忆问题；表达、生词、听辨和填空提示都合并在同一张卡里。"
        "好卡样例：english=Honestly, it's such a nice Monday morning. phrase=such a nice；"
        "learning_target=训练 such a nice + 名词来表达自然赞叹；how_to_use_it=such a nice day / such a nice place；"
        "teacher_note=下次想夸天气、地方或体验时，用 such a nice + 名词，比 very nice 更像真实口语。"
        "废卡样例：english=Today we are going to talk about AI models. phrase=talk about；B1 用户不推荐，因为太基础且不是真正值得学的内容。"
        "重复卡样例：同一句同一个 learning_point 不要同时生成听力卡、表达卡、填空卡；只保留一张学习卡。"
        "卡片规划规则：每个 learning_point 最多生成 1 张统一学习卡；同一句允许多个不同 learning_point，但每个点只对应一张卡。"
        "统一学习卡使用 phrase 兼容类型，整合语义、中文感、例句、迁移、听辨和填空提示；不要额外输出 listening 或 cloze 卡。"
        "优先 5-12 个词的短句；超过 14 个词通常不要做精品卡。"
        f"可用卡型：{json.dumps(requested_types, ensure_ascii=False)}。"
        "如果只需要一张卡，就只返回一张；不要为了满足卡型列表而复制同一张卡。"
        "每张卡必须写 card_role: primary|specialist、learning_goal、decision_reason。"
        "每个输出 segment.id 必须逐字复制对应输入 segment.id；禁止从 seg_0001 或 seg_lp_0001 重新编号。"
        "每张卡的 learning_point_id 也必须逐字复制输入 learning_points[].id。"
        "输出 segment 数必须和输入 segment 数相同；不制卡也要保留原 id 并返回 cards: []。"
        "返回严格 JSON，不要 Markdown。JSON 结构："
        '{"segments":[{"id":"COPY_EXACT_INPUT_SEGMENT_ID","cards":[{"type":"phrase",'
        '"learning_point_id":"对应 learning_points[].id",'
        '"candidate_kind":"expression|contextual_vocab|grammar_pattern|listening_feature|pragmatic_risk",'
        '"exact_span":"逐词来自原句的片段","normalized_answer":"标准化英文答案",'
        '"phrase_type":"spoken_phrase|sentence_frame|collocation|discourse_marker|idiom|listening_sentence|vocabulary_usage|grammar_pattern",'
        '"content_kind":"phrase|vocabulary|grammar|listening",'
        '"source_evidence":"这张卡来自原句和上下文的证据",'
        '"chinese":"中文意思","phrase":"重点表达或生词","definition":"释义","collocations":"搭配",'
        '"context":"语境","example":"例句","chinese_feel":"中文感","why":"为什么值得学",'
        '"difficulty":"A1 入门|A2 基础|B1 日常交流|B2 独立表达|C1 高阶表达|C2 接近母语",'
        '"estimated_level":"A1|A2|B1|B2|C1|C2","difficulty_reason":"一句中文说明难点来源",'
        '"teacher_note":"一句老师评语","cloze":"挖空句","card_role":"primary|specialist",'
        '"learning_goal":"这张卡训练什么","decision_reason":"为什么生成这张卡",'
        '"learning_target":"这张卡训练什么","learning_action":"contextual_meaning|expression_recall|listening_discrimination|collocation_boundary|chinese_learner_trap|conceptual_action|grammar_pattern",'
        '"conceptual_action":"概念动作感","chinese_learner_trap":"中文学习者误区",'
        '"why_it_matters":"为什么值得学",'
        '"how_to_use_it":"下次怎么换场景使用","natural_chinese":"自然中文理解",'
        '"replacement_examples":"1-2 个可替换例子","avoid_reason":"不值得制卡时的原因",'
        '"retrieval_prompt":"正面明确回忆题","answer_core":"核心答案",'
        '"phonetic_ipa":"标准读法；按当前 language 的 notation_system 输出",'
        '"spoken_ipa":"字幕推测的 answer_core 口语读法；未实听时不得 high confidence",'
        '"source_spoken_ipa":"完整原句推测读法，覆盖目标语言原句主要词/音节，不要只写短语片段","pronunciation_note":"中文发音教学说明，不写未实听/已隐藏等系统状态",'
        '"pronunciation_confidence":"high|medium|low",'
        '"pronunciation_meta":{"language_code":"en|fr|es|ja|ru","accent_profile":"...","notation_system":"...",'
        '"generation_basis":"audio_verified|subtitle_inferred|dictionary_only","field_confidence":{"phonetic_ipa":"high|medium|low",'
        '"spoken_ipa":"high|medium|low","source_spoken_ipa":"high|medium|low","pronunciation_note":"high|medium|low"},'
        '"same_as_standard_reason":null,"pitch_confidence":"high|medium|low|unknown","validation_issues":[]},'
        '"usage_boundary":"使用边界/语气风险","confusable_note":"易错提醒"}]}]}。'
        f"学习语言：{profile['label']}（内部 code={language_code}）。"
        f"level_mode：{level_mode}。用户当前水平 legacy fallback：{current_level}。"
        "自动模式下请为每张卡自行判断 estimated_level；手动模式下只把用户水平当软偏好，不要硬过滤。"
        f"筛选策略：{SELECTION_STRATEGY_LABELS.get(selection_strategy, selection_strategy)}。"
        f"高级难度关注范围：{', '.join(collection_levels)}；可以参考这些等级，但不要因此漏掉地道高频表达、生词用法、语法或听力点。"
        f"需要卡型：{', '.join(requested_types)}。"
        f"候选字幕：{json.dumps(compact, ensure_ascii=False)}"
    )


def ciba_tianxia_card_prompt_instruction(project: dict[str, Any]) -> str:
    return (
        "【词霸天下实验 V1：语言动作卡模式】"
        "每张卡只训练一个真实语言动作，不做泛泛知识整理。"
        "你要帮助学习者把字幕里的词块、语境义、概念视角、搭配边界和真实听辨变成可复习动作。"
        "所谓为说而思考，是让学习者知道下次自己说话时何时替换、如何搭配、哪里不能乱用。"
        "优先制卡对象："
        "1) 词块和短语动词，例如 run the register 这种动词+对象搭配；"
        "2) 单词在本句里的语境义，而不是脱离上下文的词典义；"
        "3) 可迁移的句型框架、概念视角和表达立场；"
        "4) 有证据的听辨点，例如弱读、连读、缩读、吞音、重音变化；"
        "5) 搭配边界、正式度、冒犯风险和中文学习者容易误用的地方。"
        "降低或拒绝：主题标签、专有名词堆叠、过长整句、没有迁移价值的碎片、泛泛的 talk about/do something/good thing。"
        "answer_core 必须干净：只能是目标语言答案本体，不能包含中文、IPA、发音说明、语法说明或解释句。"
        "如果同一句有多个不同训练动作，可以分别制卡；如果只是同一个动作的听力/表达/填空重复，只保留最合适的一张。"
        "teacher_note 必须解释具体操作：这个表达怎么迁移、搭配边界是什么、中文学习者哪里容易误会。"
        "usage_boundary 和 confusable_note 不能写空话，必须结合本句说明对象、语气、场景或错误用法。"
        "新增三项必须服务于主动复习：learning_action 只能从 contextual_meaning|expression_recall|listening_discrimination|collocation_boundary|chinese_learner_trap|conceptual_action|grammar_pattern 中选一个；"
        "conceptual_action 写概念动作感，例如 hold back=把情绪往回压住，不让它出来；chinese_learner_trap 只写有可靠依据的母语迁移误区或近义表达差别，不能泛泛说注意语境。不得把语法正确、自然的近义表达称为错误或中式英语；若只是语义或语域不同，必须明确说明“都可用，但差别是……”，无法确认时留空。"
        "这两个字段都必须短：各 1 句，优先 20-36 个中文字，不要写成段落，避免背面过载。"
        f"当前模板 id={normalize_template_id(project.get('template_id'))}。"
    )


def build_ciba_tianxia_prompt(project: dict[str, Any], segments: list[dict[str, Any]]) -> str:
    base_prompt = build_immersive_v11_prompt(project, segments)
    return ciba_tianxia_card_prompt_instruction(project) + base_prompt


def build_prompt(project: dict[str, Any], segments: list[dict[str, Any]]) -> str:
    if ciba_tianxia_mode(project):
        return build_ciba_tianxia_prompt(project, segments)
    return build_immersive_v11_prompt(project, segments)


def material_context_for_prompt(context: Any) -> str:
    if not isinstance(context, dict) or not context:
        return ""
    useful = {
        key: value
        for key, value in context.items()
        if key in {"summary", "topic", "scene", "speakers_or_author", "tone", "key_points", "learning_opportunities"}
        and value not in (None, "", [])
    }
    if not useful:
        return ""
    return (
        "全局素材理解（用于判断上下文，不要照抄成卡片）："
        f"{json.dumps(useful, ensure_ascii=False)}。"
        "请用它理解人物关系、主题、语气和上下文，再判断哪个学习点真正值得复习。"
    )


def heuristic_material_context(project: dict[str, Any], segments: list[dict[str, Any]]) -> dict[str, Any]:
    title = str(project.get("title") or "").strip()
    sample = " ".join(str(item.get("text") or "").strip() for item in segments[:8]).strip()
    phrases = [
        str(item.get("phrase") or "").strip()
        for item in segments[:12]
        if str(item.get("phrase") or "").strip().lower() not in {"", "key expression", "n/a"}
    ]
    return {
        "summary": f"{title or '当前素材'}：系统根据字幕候选生成学习卡，需要以原句和时间轴为准。",
        "scene": sample[:280],
        "key_points": phrases[:6],
        "learning_opportunities": [LANGUAGE_FOCUS_LABELS[item] for item in normalized_language_focus(project)],
        "source": "heuristic",
    }


def build_material_context_prompt(project: dict[str, Any], segments: list[dict[str, Any]]) -> str:
    compact = [
        {
            "id": item.get("id"),
            "source_time": item.get("source_time"),
            "english": item.get("text"),
            "phrase_hint": item.get("phrase", ""),
        }
        for item in segments[:80]
    ]
    return (
        "你是中文母语者的英语学习材料分析老师。请先理解这段视频/字幕素材到底在讲什么，"
        "不要生成卡片内容。你的任务是给后续 Anki 制卡提供全局上下文：主题、场景、人物/说话者关系、"
        "语气、关键转折、反复出现的表达，以及最值得挖的学习机会。"
        f"{language_focus_instruction(project)}"
        "请特别关注：哪些表达必须依赖上下文才懂；哪些单词在这个场景里有特殊用法；哪些句型有迁移价值；"
        "哪些听力难点确实来自弱读/连读/缩读，而不是普通句子。"
        "只返回严格 JSON，不要 Markdown。结构："
        '{"material_context":{"summary":"这段素材的核心内容","topic":"主题",'
        '"scene":"场景或论点脉络","speakers_or_author":"人物关系或作者视角","tone":"语气",'
        '"key_points":["关键情节/论点"],"learning_opportunities":["值得制卡的语言机会"],"source":"ai"}}。'
        f"素材标题：{project.get('title') or 'Untitled'}。"
        f"候选字幕：{json.dumps(compact, ensure_ascii=False)}"
    )


def material_context_available(project: dict[str, Any]) -> bool:
    api = project.get("api_config") or {}
    return model_api_available(api)


def call_material_context(project: dict[str, Any], segments: list[dict[str, Any]]) -> dict[str, Any]:
    if normalized_study_depth(project) != "deep" or not segments:
        return heuristic_material_context(project, segments)
    if not material_context_available(project):
        return heuristic_material_context(project, segments)

    api = project.get("api_config") or {}
    provider = api.get("provider", "local")
    model = api.get("model", "").strip()
    prompt = build_material_context_prompt(project, segments)
    try:
        if provider in OPENAI_COMPATIBLE_PROVIDERS:
            token_budget = 3000 if is_deepseek_thinking_config(api) else 2200
            response = compatible_chat_completion(
                api,
                [
                    {"role": "system", "content": "Return only valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                timeout=180 if is_thinking_model_config(api) else 60,
                max_tokens=token_budget,
                progress={
                    "command": "generate",
                    "stage": "context",
                    "percent": 54,
                    "message": "模型正在理解整段素材，thinking 已保留。",
                },
                work_unit_id="material-context",
            )
            payload = extract_json_object(chat_completion_content(response))
        elif provider == "claude":
            response = model_anthropic_messages(
                api,
                {
                    "model": model,
                    "max_tokens": 2200,
                    "temperature": 0.2,
                    "system": "Return only valid JSON.",
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=90,
                work_unit_id="material-context",
            )
            payload = extract_json_object("".join(part.get("text", "") for part in response.get("content", [])))
        elif provider == "gemini":
            response = model_gemini_content(
                api,
                {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
                },
                timeout=90,
                work_unit_id="material-context",
            )
            payload = extract_json_object(response["candidates"][0]["content"]["parts"][0]["text"])
        elif is_gemini_vertex_config(api):
            content = gemini_vertex_generate_content(
                api,
                prompt,
                temperature=0.2,
                timeout=180 if is_gemini_vertex_thinking_config(api) else 90,
                max_output_tokens=6000 if is_gemini_vertex_thinking_config(api) else 3000,
            )
            payload = extract_json_object(content)
        else:
            return heuristic_material_context(project, segments)
        context = payload.get("material_context") if isinstance(payload, dict) else None
        if not isinstance(context, dict) and isinstance(payload, dict):
            direct_context_keys = {"summary", "topic", "scene", "speakers_or_author", "tone", "key_points"}
            if any(key in payload for key in direct_context_keys):
                context = payload
        if isinstance(context, dict) and context:
            return {**context, "source": context.get("source") or "ai"}
    except Exception as err:
        fallback = heuristic_material_context(project, segments)
        fallback["warning"] = f"深度理解失败，已回退到本地上下文：{err}"
        return fallback
    return heuristic_material_context(project, segments)


def strip_reasoning_text(text: str) -> str:
    return model_json_strip_reasoning_text(text)


def extract_json_object(text: str) -> dict[str, Any]:
    return model_json_extract_json_object(text)


ANKI_MEDIA_MAX_FILE_BYTES = 256 * 1024 * 1024
ANKI_MEDIA_MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
ANKI_MEDIA_MAX_ITEMS = 2000
ANKI_DIRECT_COPY_CHUNK_BYTES = 1024 * 1024
ANKI_CONNECT_MEDIA_MAX_RAW_BYTES = 8 * 1024 * 1024
ANKI_CONNECT_MEDIA_MAX_BASE64_CHARS = 4 * ((ANKI_CONNECT_MEDIA_MAX_RAW_BYTES + 2) // 3)
ANKI_CONNECT_RETRIEVE_MAX_JSON_BYTES = ANKI_CONNECT_MEDIA_MAX_BASE64_CHARS + 4096
ANKI_CONNECT_SMALL_RESPONSE_MAX_BYTES = 64 * 1024
ANKI_CONNECT_DEFAULT_RESPONSE_MAX_BYTES = 16 * 1024 * 1024
ANKI_CONNECT_RESPONSE_TOO_LARGE_MARKER = "ANKI_CONNECT_RESPONSE_TOO_LARGE"


def _read_http_response_bytes(response: Any, max_response_bytes: int | None) -> bytes:
    if max_response_bytes is None:
        return response.read()
    if max_response_bytes <= 0:
        raise ValueError("max_response_bytes must be positive")
    content_length = response.headers.get("Content-Length") if getattr(response, "headers", None) else None
    if content_length:
        try:
            if int(content_length) > max_response_bytes:
                raise RuntimeError(
                    f"{ANKI_CONNECT_RESPONSE_TOO_LARGE_MARKER}: HTTP response exceeds "
                    f"{max_response_bytes} bytes"
                )
        except ValueError:
            pass
    raw = response.read(max_response_bytes + 1)
    if len(raw) > max_response_bytes:
        raise RuntimeError(
            f"{ANKI_CONNECT_RESPONSE_TOO_LARGE_MARKER}: HTTP response exceeds "
            f"{max_response_bytes} bytes"
        )
    return raw


def http_json(
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    timeout: int = 60,
    max_response_bytes: int | None = None,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(_read_http_response_bytes(response, max_response_bytes).decode("utf-8"))
    except urllib.error.HTTPError as err:
        detail = _read_http_response_bytes(err, max_response_bytes).decode("utf-8", errors="replace")
        raise RuntimeError(f"API HTTP {err.code}: {detail}") from err


def http_sse_json_events(url: str, headers: dict[str, str], body: dict[str, Any], timeout: int = 120) -> list[dict[str, Any]]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "text/event-stream", **headers},
        method="POST",
    )
    events: list[dict[str, Any]] = []
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data_lines: list[str] = []
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    if data_lines:
                        data = "\n".join(data_lines).strip()
                        data_lines = []
                        if data == "[DONE]":
                            break
                        if data:
                            events.append(json.loads(data))
                    continue
                if line.startswith(":"):
                    continue
                if line.startswith("data:"):
                    data = line[len("data:") :].strip()
                    if data == "[DONE]":
                        break
                    data_lines.append(data)
            if data_lines:
                data = "\n".join(data_lines).strip()
                if data and data != "[DONE]":
                    events.append(json.loads(data))
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"API HTTP {err.code}: {detail}") from err
    return events


def stream_chat_completion(
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    timeout: int = 120,
    progress: dict[str, Any] | None = None,
) -> dict[str, Any]:
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    finish_reason: str | None = None
    last_emit = 0.0
    for event in http_sse_json_events(url, headers, body, timeout=timeout):
        for choice in event.get("choices") or []:
            delta = choice.get("delta") or {}
            if delta.get("reasoning_content"):
                reasoning_parts.append(str(delta["reasoning_content"]))
            if delta.get("content"):
                content_parts.append(str(delta["content"]))
            if choice.get("finish_reason"):
                finish_reason = str(choice["finish_reason"])
        if progress:
            now = time.time()
            if now - last_emit >= 3:
                content_chars = sum(len(part) for part in content_parts)
                reasoning_chars = sum(len(part) for part in reasoning_parts)
                phase = "正在输出最终 JSON" if content_chars else "正在思考"
                emit_progress(
                    str(progress.get("command") or "generate"),
                    str(progress.get("stage") or "ai"),
                    int(progress.get("percent") or 66),
                    f"{progress.get('message') or '模型正在生成'}：{phase}，已收到 {content_chars} 个答案字符 / {reasoning_chars} 个 thinking 字符。",
                )
                last_emit = now
    return {
        "choices": [
            {
                "finish_reason": finish_reason or "stop",
                "message": {
                    "role": "assistant",
                    "content": "".join(content_parts),
                    "reasoning_content": "".join(reasoning_parts),
                },
            }
        ]
    }


def http_binary(url: str, headers: dict[str, str], body: dict[str, Any], timeout: int = 90) -> bytes:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"TTS HTTP {err.code}: {detail}") from err


def http_get_binary(url: str, headers: dict[str, str] | None = None, timeout: int = 90) -> bytes:
    request = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"TTS download HTTP {err.code}: {detail}") from err


def http_status_from_error_message(message: str) -> int | None:
    return service_errors_http_status_from_error_message(message)


def service_error_codes(kind: str) -> dict[str, str]:
    return service_errors_service_error_codes(kind)


def service_stage(kind: str) -> str:
    return service_errors_service_stage(kind)


def service_label(kind: str) -> str:
    return service_errors_service_label(kind)


def service_error_message(kind: str, category: str, detail: str) -> str:
    return service_errors_service_error_message(kind, category, detail)


def classify_service_error(error: Exception, *, kind: str = "model") -> dict[str, Any]:
    return service_errors_classify_service_error(error, kind=kind)


def classify_worker_exception(error: Exception, *, command: str = "") -> dict[str, Any]:
    return service_errors_classify_worker_exception(error, command=command)


def anki_connect(action: str, params: dict[str, Any] | None = None, url: str = "http://127.0.0.1:8765") -> Any:
    validate_anki_connect_url(url)
    if action == "retrieveMediaFile":
        response_limit = ANKI_CONNECT_RETRIEVE_MAX_JSON_BYTES
    elif action == "storeMediaFile":
        response_limit = ANKI_CONNECT_SMALL_RESPONSE_MAX_BYTES
    else:
        response_limit = ANKI_CONNECT_DEFAULT_RESPONSE_MAX_BYTES
    response = http_json(
        url,
        {},
        {
            "action": action,
            "version": 6,
            "params": params or {},
        },
        timeout=30,
        max_response_bytes=response_limit,
    )
    if response.get("error"):
        raise RuntimeError(str(response["error"]))
    return response.get("result")


def decode_anki_media_base64(
    value: Any,
    *,
    max_raw_bytes: int = ANKI_CONNECT_MEDIA_MAX_RAW_BYTES,
) -> bytes:
    if not isinstance(value, str) or not value:
        raise ValueError("AnkiConnect 没有返回媒体内容。")
    max_base64_chars = 4 * ((max_raw_bytes + 2) // 3)
    if len(value) > max_base64_chars:
        raise RuntimeError(
            f"{ANKI_CONNECT_RESPONSE_TOO_LARGE_MARKER}: AnkiConnect media payload exceeds "
            f"{max_raw_bytes} raw bytes"
        )
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as err:
        raise ValueError(f"AnkiConnect 返回了无效的媒体 Base64：{err}") from err
    if len(decoded) > max_raw_bytes:
        raise RuntimeError(
            f"{ANKI_CONNECT_RESPONSE_TOO_LARGE_MARKER}: decoded AnkiConnect media exceeds "
            f"{max_raw_bytes} bytes"
        )
    return decoded


LOOPBACK_HOSTS = security_boundaries_loopback_hosts
BLOCKED_URL_HOSTS = security_boundaries_blocked_url_hosts
SENSITIVE_WINDOWS_ROOTS = security_boundaries_sensitive_windows_roots
SUPPORTED_INPUT_SUFFIXES = security_boundaries_supported_input_suffixes


def parsed_url_host(url: str) -> str:
    return security_boundaries_parsed_url_host(url)


def ip_address_for_host(host: str) -> ipaddress._BaseAddress | None:
    return security_boundaries_ip_address_for_host(host)


def host_is_loopback(host: str) -> bool:
    return security_boundaries_host_is_loopback(host)


def host_is_private_or_local(host: str) -> bool:
    return security_boundaries_host_is_private_or_local(host)


def validate_anki_connect_url(url: str) -> None:
    return security_boundaries_validate_anki_connect_url(url)


def validate_source_url_for_import(payload: dict[str, Any]) -> str:
    return security_boundaries_validate_source_url_for_import(payload)


def require_confirmed_local_path_access(payload: dict[str, Any], *, stage: str) -> None:
    return security_boundaries_require_confirmed_local_path_access(payload, stage=stage)


def yt_dlp_needs_remote_components(detail: str) -> bool:
    return ytdlp_support_yt_dlp_needs_remote_components(detail)


def fail_if_remote_components_confirmation_required(payload: dict[str, Any], detail: str) -> None:
    if yt_dlp_needs_remote_components(detail) and os.environ.get("ACG_MANAGED_RUNTIME") == "1":
        fail(
            "托管插件运行时禁止下载或执行 yt-dlp 远程组件。请改用仅字幕模式或上传本地字幕。",
            error_code="YTDLP_REMOTE_COMPONENTS_DISABLED",
            stage="download_video",
            retryable=False,
            fallbacks=["subtitle_only", "local_srt"],
        )
    if yt_dlp_needs_remote_components(detail) and not bool(payload.get("allow_ytdlp_remote_components")):
        fail(
            format_yt_dlp_failure(detail),
            error_code="YTDLP_REMOTE_COMPONENTS_CONFIRMATION_REQUIRED",
            stage="download_video",
            retryable=True,
            fallbacks=["allow_ytdlp_remote_components", "subtitle_only", "local_srt"],
        )


def compatible_base_url(config: dict[str, Any], default_url: str = "") -> str:
    return provider_compatible_base_url(config, default_url)


def provider_name(config: dict[str, Any]) -> str:
    return provider_provider_name(config)


def is_mimo_config(config: dict[str, Any]) -> bool:
    return provider_is_mimo_config(config)


def is_qwen_config(config: dict[str, Any]) -> bool:
    return provider_is_qwen_config(config)


def is_deepseek_config(config: dict[str, Any]) -> bool:
    return provider_is_deepseek_config(config)


def is_deepseek_thinking_config(config: dict[str, Any]) -> bool:
    return provider_is_deepseek_thinking_config(config)


def is_gemini_vertex_config(config: dict[str, Any]) -> bool:
    return provider_is_gemini_vertex_config(config)


def is_gemini_vertex_tts_config(config: dict[str, Any]) -> bool:
    return provider_is_gemini_vertex_tts_config(config)


def is_gemini_vertex_thinking_config(config: dict[str, Any]) -> bool:
    return provider_is_gemini_vertex_thinking_config(config)


def is_thinking_model_config(config: dict[str, Any]) -> bool:
    return provider_is_thinking_model_config(config)


def thinking_budget(config: dict[str, Any], default_value: int = 800) -> int:
    return provider_thinking_budget(config, default_value)


def should_stream_reasoning(config: dict[str, Any]) -> bool:
    return provider_should_stream_reasoning(config)


def api_key_header(config: dict[str, Any]) -> dict[str, str]:
    return provider_api_key_header(config)


def managed_model_operation(config: dict[str, Any]) -> str | None:
    provider = str(config.get("provider") or "local").strip().lower()
    if provider in OPENAI_COMPATIBLE_PROVIDERS:
        return "model.openai_chat"
    if provider == "claude":
        return "model.anthropic_messages"
    if provider == "gemini":
        return "model.gemini_content"
    return None


def model_api_available(api: dict[str, Any]) -> bool:
    if managed_model_broker_is_configured():
        operation = managed_model_operation(api)
        return bool(
            str(api.get("model") or "").strip()
            and operation
            and managed_model_operation_available(operation)
        )
    return provider_model_api_available(api)


def managed_model_response(
    operation: str,
    request: dict[str, Any],
    *,
    work_unit_id: str | None,
    attempt: str,
) -> dict[str, Any]:
    return managed_model_request(
        operation,
        request,
        work_unit_base=f"{work_unit_id or 'model'}:{attempt}",
    )


def hidden_subprocess_flags() -> dict[str, Any]:
    if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def gcloud_executable() -> str:
    found = shutil.which("gcloud") or shutil.which("gcloud.cmd")
    if found:
        return found
    candidates = [
        Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"))
        / "Google"
        / "Cloud SDK"
        / "google-cloud-sdk"
        / "bin"
        / "gcloud.cmd",
        Path(os.environ.get("ProgramFiles", "C:/Program Files"))
        / "Google"
        / "Cloud SDK"
        / "google-cloud-sdk"
        / "bin"
        / "gcloud.cmd",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    raise FileNotFoundError("gcloud")


def gcloud_value(args: list[str], timeout: int = 30) -> str:
    try:
        result = subprocess.run(
            [gcloud_executable(), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=True,
            **hidden_subprocess_flags(),
        )
    except FileNotFoundError as err:
        raise RuntimeError("Gemini Vertex 需要先安装 Google Cloud SDK，并确保 gcloud 在 PATH 中。") from err
    except subprocess.CalledProcessError as err:
        detail = (err.stderr or err.stdout or "").strip()
        raise RuntimeError(f"gcloud 调用失败：{detail or err}") from err
    value = result.stdout.strip()
    if not value or value == "(unset)":
        raise RuntimeError(f"gcloud {' '.join(args)} 没有返回可用值。")
    return value


def gemini_vertex_project(config: dict[str, Any]) -> str:
    explicit = str(config.get("project") or config.get("project_id") or "").strip()
    return explicit or gcloud_value(["config", "get-value", "core/project"])


def gemini_vertex_location(config: dict[str, Any]) -> str:
    explicit = str(config.get("location") or config.get("region") or "").strip()
    if explicit:
        return explicit
    base_url = str(config.get("base_url") or "").strip().rstrip("/")
    if base_url:
        try:
            host = urllib.parse.urlparse(base_url).hostname or ""
        except ValueError:
            host = ""
        if host == "aiplatform.googleapis.com":
            return "global"
        suffix = "-aiplatform.googleapis.com"
        if host.endswith(suffix):
            return host[: -len(suffix)]
    return "global"


def gemini_vertex_base_url(location: str) -> str:
    return GEMINI_VERTEX_GLOBAL_BASE_URL if location == "global" else f"https://{location}-aiplatform.googleapis.com"


def normalize_gemini_vertex_model(value: Any) -> str:
    model = str(value or "").strip()
    if not model:
        return GEMINI_VERTEX_DEFAULT_MODEL
    normalized = model.lower()
    if normalized in GEMINI_VERTEX_UNAVAILABLE_MODEL_ALIASES:
        return GEMINI_VERTEX_PRO_PREVIEW_MODEL
    return GEMINI_VERTEX_MODEL_ALIASES.get(normalized, model)


def gemini_content_text(response: dict[str, Any]) -> str:
    texts: list[str] = []
    for candidate in response.get("candidates", []) or []:
        content = candidate.get("content") or {}
        for part in content.get("parts", []) or []:
            text = part.get("text")
            if text:
                texts.append(str(text))
    return "\n".join(texts).strip()


def gemini_vertex_generate_content(
    config: dict[str, Any],
    prompt: str,
    *,
    temperature: float = 0.2,
    timeout: int = 180,
    max_output_tokens: int = 12000,
    response_mime_type: str = "application/json",
) -> str:
    if managed_model_broker_is_configured():
        raise ManagedModelBrokerError(
            "Gemini Vertex is blocked in the managed Worker until Service-owned OAuth egress is available"
        )
    model = normalize_gemini_vertex_model(config.get("model"))
    project = gemini_vertex_project(config)
    location = gemini_vertex_location(config)
    token = gcloud_value(["auth", "print-access-token"])
    url = (
        f"{gemini_vertex_base_url(location)}/v1/projects/{urllib.parse.quote(project, safe='')}"
        f"/locations/{urllib.parse.quote(location, safe='')}/publishers/google/models/"
        f"{urllib.parse.quote(model, safe='')}:generateContent"
    )
    generation_config: dict[str, Any] = {
        "temperature": temperature,
        "maxOutputTokens": max_output_tokens,
    }
    if response_mime_type:
        generation_config["responseMimeType"] = response_mime_type
    response = http_json(
        url,
        {"Authorization": f"Bearer {token}"},
        {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": generation_config,
        },
        timeout=timeout,
    )
    text = gemini_content_text(response)
    if text:
        return text
    finish = ""
    for candidate in response.get("candidates", []) or []:
        finish = str(candidate.get("finishReason") or finish)
    if finish == "MAX_TOKENS":
        raise RuntimeError("Gemini Vertex 没有返回正文：输出预算被 thinking 消耗完，请提高 maxOutputTokens。")
    raise RuntimeError(f"Gemini Vertex 没有返回可用正文：{finish or 'empty response'}")


def anthropic_messages_url(config: dict[str, Any]) -> str:
    base_url = str(config.get("base_url") or "").strip().rstrip("/")
    if not base_url:
        return "https://api.anthropic.com/v1/messages"
    if base_url.endswith("/messages"):
        return base_url
    if base_url.endswith("/v1"):
        return f"{base_url}/messages"
    return f"{base_url}/v1/messages"


def anthropic_headers(config: dict[str, Any], api_key: str) -> dict[str, str]:
    if is_mimo_config(config):
        return {"api-key": api_key}
    return {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }


def model_anthropic_messages(
    api: dict[str, Any],
    body: dict[str, Any],
    *,
    timeout: int = 60,
    work_unit_id: str | None = None,
) -> dict[str, Any]:
    if managed_model_broker_is_configured():
        return managed_model_response(
            "model.anthropic_messages",
            body,
            work_unit_id=work_unit_id,
            attempt="initial",
        )
    api_key = str(api.get("api_key") or "").strip()
    return http_json(
        anthropic_messages_url(api),
        anthropic_headers(api, api_key),
        body,
        timeout=timeout,
    )


def model_gemini_content(
    api: dict[str, Any],
    body: dict[str, Any],
    *,
    timeout: int = 60,
    work_unit_id: str | None = None,
) -> dict[str, Any]:
    if managed_model_broker_is_configured():
        return managed_model_response(
            "model.gemini_content",
            body,
            work_unit_id=work_unit_id,
            attempt="initial",
        )
    api_key = str(api.get("api_key") or "").strip()
    model = str(api.get("model") or "").strip()
    return http_json(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        {"x-goog-api-key": api_key},
        body,
        timeout=timeout,
    )


def compatible_chat_completion(
    api: dict[str, Any],
    messages: list[dict[str, str]],
    temperature: float,
    timeout: int = 60,
    max_tokens: int | None = None,
    progress: dict[str, Any] | None = None,
    work_unit_id: str | None = None,
) -> dict[str, Any]:
    brokered = managed_model_broker_is_configured()
    base_url = compatible_base_url(api)
    if not brokered and not base_url:
        raise RuntimeError("MIMO / OpenAI-compatible 需要 Base URL。")
    is_mimo = is_mimo_config(api)
    is_qwen = is_qwen_config(api)
    is_deepseek_thinking = is_deepseek_thinking_config(api)
    body: dict[str, Any] = {
        "model": str(api.get("model") or "").strip(),
        "messages": messages,
        "temperature": temperature,
    }
    stream_reasoning = should_stream_reasoning(api) and not brokered
    if not is_mimo:
        body["response_format"] = {"type": "json_object"}
    else:
        body["reasoning_effort"] = "low"
        body["thinking"] = {"type": "enabled"}
    if is_deepseek_thinking:
        body["thinking"] = {"type": "enabled"}
        body["reasoning_effort"] = str(api.get("reasoning_effort") or "high")
    if is_qwen:
        body["enable_thinking"] = True
        body["thinking_budget"] = thinking_budget(api)
        body["preserve_thinking"] = False
    if stream_reasoning:
        body["stream"] = True
        body["stream_options"] = {"include_usage": True}
    if max_tokens is not None:
        body["max_completion_tokens" if is_mimo else "max_tokens"] = max_tokens
    supports_response_retry = "response_format" in body
    endpoint = f"{base_url}/chat/completions" if base_url else ""

    def send(request_body: dict[str, Any], attempt: str) -> dict[str, Any]:
        if brokered:
            return managed_model_response(
                "model.openai_chat",
                request_body,
                work_unit_id=work_unit_id,
                attempt=attempt,
            )
        if request_body.get("stream"):
            return stream_chat_completion(
                endpoint,
                api_key_header(api),
                request_body,
                timeout=timeout,
                progress=progress,
            )
        return http_json(
            endpoint,
            api_key_header(api),
            request_body,
            timeout=timeout,
        )

    try:
        return send(body, "initial")
    except Exception as err:
        if is_mimo:
            retry_body = dict(body)
            if retry_body.get("stream"):
                retry_body["stream"] = False
                retry_body.pop("stream_options", None)
            try:
                return send(retry_body, "mimo-nonstream")
            except Exception as retry_err:
                if "max_completion_tokens" in retry_body:
                    fallback_body = dict(retry_body)
                    fallback_body["max_tokens"] = fallback_body.pop("max_completion_tokens")
                    try:
                        return send(fallback_body, "mimo-max-tokens")
                    except Exception as token_retry_err:
                        raise RuntimeError(
                            f"{err}; 保留 MIMO thinking 重试失败：{retry_err}; 改用 max_tokens 重试仍失败：{token_retry_err}"
                        ) from token_retry_err
                raise RuntimeError(f"{err}; 保留 MIMO thinking 重试仍失败：{retry_err}") from retry_err
        if stream_reasoning:
            retry_body = dict(body)
            retry_body["stream"] = False
            retry_body.pop("stream_options", None)
            try:
                return send(retry_body, "nonstream")
            except Exception as stream_retry_err:
                if supports_response_retry:
                    retry_body.pop("response_format", None)
                    try:
                        return send(retry_body, "nonstream-no-response-format")
                    except Exception as response_retry_err:
                        raise RuntimeError(
                            f"{err}; 去掉流式 thinking 重试失败：{stream_retry_err}; "
                            f"去掉 response_format 重试仍失败：{response_retry_err}"
                        ) from response_retry_err
                raise RuntimeError(f"{err}; 去掉流式 thinking 重试失败：{stream_retry_err}") from stream_retry_err
        # Some OpenAI-compatible providers, including Token Plan gateways, may not support
        # response_format even when they can reliably return JSON from the prompt.
        if not supports_response_retry:
            raise
        body.pop("response_format", None)
        try:
            return send(body, "no-response-format")
        except Exception as retry_err:
            raise RuntimeError(f"{err}; 去掉 response_format 重试仍失败：{retry_err}") from retry_err


def chat_completion_content(response: dict[str, Any]) -> str:
    message = response.get("choices", [{}])[0].get("message", {})
    content = message.get("content", "")
    if isinstance(content, list):
        return "".join(str(part.get("text", "")) if isinstance(part, dict) else str(part) for part in content)
    return str(content or "")


def call_model(
    project: dict[str, Any],
    segments: list[dict[str, Any]],
    *,
    work_unit_id: str | None = None,
) -> dict[str, Any] | None:
    api = project.get("api_config") or {}
    provider = api.get("provider", "local")
    model = api.get("model", "").strip()
    if provider == "local" or not model or not model_api_available(api):
        return None

    prompt = build_prompt(project, segments)

    try:
        if provider in OPENAI_COMPATIBLE_PROVIDERS:
            token_budget = 2200 if is_mimo_config(api) else 8000 if is_deepseek_thinking_config(api) else 4000 if is_qwen_config(api) else 6000
            response = compatible_chat_completion(
                api,
                [
                    {"role": "system", "content": "Return only valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                timeout=180 if is_thinking_model_config(api) else 60,
                max_tokens=token_budget,
                progress={
                    "command": "generate",
                    "stage": "ai",
                    "percent": 70,
                    "message": "模型保留 thinking 生成卡片字段",
                },
                work_unit_id=work_unit_id,
            )
            content = chat_completion_content(response)
            return extract_json_object(content)

        if provider == "claude":
            response = model_anthropic_messages(
                api,
                {
                    "model": model,
                    "max_tokens": 6000,
                    "temperature": 0.3,
                    "system": "Return only valid JSON.",
                    "messages": [{"role": "user", "content": prompt}],
                },
                work_unit_id=work_unit_id,
            )
            content = "".join(part.get("text", "") for part in response.get("content", []))
            return extract_json_object(content)

        if provider == "gemini":
            response = model_gemini_content(
                api,
                {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0.3,
                        "responseMimeType": "application/json",
                    },
                },
                work_unit_id=work_unit_id,
            )
            content = response["candidates"][0]["content"]["parts"][0]["text"]
            return extract_json_object(content)

        if is_gemini_vertex_config(api):
            content = gemini_vertex_generate_content(
                api,
                prompt,
                temperature=0.3,
                timeout=180 if is_gemini_vertex_thinking_config(api) else 120,
                max_output_tokens=32000 if is_gemini_vertex_thinking_config(api) else 8000,
            )
            return extract_json_object(content)
    except Exception as err:
        details = classify_service_error(err, kind="model")
        return {"error": details["message"], **details}

    return None


def final_card_batch_size(api: dict[str, Any], requested: int = 10) -> int:
    if is_hermes_local_config(api):
        return max(1, min(6, requested if requested > 0 else 6))
    if is_mimo_config(api):
        return 4
    if is_gemini_vertex_thinking_config(api):
        return 8
    if is_gemini_vertex_config(api):
        return 20
    if is_deepseek_thinking_config(api) or is_qwen_config(api):
        return max(10, min(16, requested if requested > 0 else 16))
    if is_thinking_model_config(api):
        return max(8, min(12, requested if requested > 0 else 12))
    return max(16, min(24, requested if requested > 0 else 20))


def final_card_generation_concurrency(api: dict[str, Any], total_batches: int) -> int:
    if total_batches <= 1:
        return 1
    if is_hermes_local_config(api):
        # The managed local Hermes proxy shares one OAuth-backed upstream
        # session. Serial requests avoid interleaved/truncated JSON responses.
        return 1
    if is_mimo_config(api):
        return min(2, total_batches)
    if is_gemini_vertex_thinking_config(api):
        return min(3, total_batches)
    if is_gemini_vertex_config(api):
        return min(4, total_batches)
    if api.get("provider") in OPENAI_COMPATIBLE_PROVIDERS:
        return min(3, total_batches)
    return 1


def is_hermes_local_config(config: dict[str, Any]) -> bool:
    model = str(config.get("model") or "").strip().lower()
    if model != "grok-4.5":
        return False
    try:
        parsed = urllib.parse.urlparse(str(config.get("base_url") or "").strip())
    except ValueError:
        return False
    return parsed.hostname in {"127.0.0.1", "localhost", "::1"} and parsed.port == 8645


def _segment_learning_point_ids(segment: dict[str, Any]) -> set[str]:
    ids = {str(segment.get("learning_point_id") or "").strip()}
    ids.update(
        str(point.get("id") or point.get("learning_point_id") or "").strip()
        for point in segment.get("learning_points", []) or []
        if isinstance(point, dict)
    )
    return {item for item in ids if item}


def _model_segment_learning_point_ids(segment: dict[str, Any]) -> set[str]:
    ids = _segment_learning_point_ids(segment)
    ids.update(
        str(card.get("learning_point_id") or "").strip()
        for card in segment.get("cards", []) or []
        if isinstance(card, dict)
    )
    return {item for item in ids if item}


def _alignment_values(segment: dict[str, Any]) -> set[str]:
    values = {
        str(segment.get(key) or "").strip().casefold()
        for key in ("phrase", "answer_core", "exact_span", "normalized_answer")
    }
    for point in segment.get("learning_points", []) or []:
        if not isinstance(point, dict):
            continue
        values.update(
            str(point.get(key) or "").strip().casefold()
            for key in ("answer_core", "exact_span", "normalized_answer", "phrase")
        )
    for card in segment.get("cards", []) or []:
        if not isinstance(card, dict):
            continue
        values.update(
            str(card.get(key) or "").strip().casefold()
            for key in ("phrase", "answer_core", "exact_span", "normalized_answer")
        )
    return {re.sub(r"\s+", " ", item) for item in values if item}


def _positionally_aligned_model_segment(model_segment: dict[str, Any], requested_segment: dict[str, Any]) -> bool:
    model_values = _alignment_values(model_segment)
    requested_values = _alignment_values(requested_segment)
    if model_values & requested_values:
        return True
    source_text = re.sub(r"\s+", " ", str(requested_segment.get("text") or "").strip().casefold())
    return bool(source_text and any(value in source_text for value in model_values if len(value) >= 2))


def reconcile_model_segment_ids(
    requested_segments: list[dict[str, Any]],
    model_segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Repair model-renumbered IDs only when the original learning point proves the mapping."""
    requested_by_id = {
        str(segment.get("id") or "").strip(): segment
        for segment in requested_segments
        if str(segment.get("id") or "").strip()
    }
    requested_ids_by_learning_point: dict[str, set[str]] = {}
    for segment_id, segment in requested_by_id.items():
        for learning_point_id in _segment_learning_point_ids(segment):
            requested_ids_by_learning_point.setdefault(learning_point_id, set()).add(segment_id)

    used_ids: set[str] = set()
    reconciled: list[dict[str, Any]] = []
    allow_positional_fallback = len(model_segments) == len(requested_segments)
    for index, model_segment in enumerate(model_segments):
        if not isinstance(model_segment, dict):
            continue
        original_id = str(model_segment.get("id") or "").strip()
        matched_ids: set[str] = set()
        model_learning_point_ids = _model_segment_learning_point_ids(model_segment)
        for learning_point_id in model_learning_point_ids:
            matched_ids.update(requested_ids_by_learning_point.get(learning_point_id, set()))

        target_id = ""
        if len(matched_ids) == 1:
            candidate_id = next(iter(matched_ids))
            if candidate_id not in used_ids:
                target_id = candidate_id
        if not target_id and original_id in requested_by_id and original_id not in used_ids:
            expected_learning_point_ids = _segment_learning_point_ids(requested_by_id[original_id])
            if not model_learning_point_ids or model_learning_point_ids & expected_learning_point_ids:
                target_id = original_id
        if not target_id and allow_positional_fallback and index < len(requested_segments):
            positional_segment = requested_segments[index]
            positional_id = str(positional_segment.get("id") or "").strip()
            if (
                positional_id
                and positional_id not in used_ids
                and _positionally_aligned_model_segment(model_segment, positional_segment)
            ):
                target_id = positional_id

        next_segment = dict(model_segment)
        if target_id:
            next_segment["id"] = target_id
            used_ids.add(target_id)
        reconciled.append(next_segment)
    return reconciled

def retryable_model_payload(payload: dict[str, Any]) -> bool:
    if payload.get("retryable") is True:
        return True
    code = str(payload.get("error_code") or "").upper()
    return any(signal in code for signal in ("TIMEOUT", "CONNECTION", "QUOTA", "HTTP_5", "REMOTE"))


def call_model_batch_with_retry(
    project: dict[str, Any],
    batch: list[dict[str, Any]],
    *,
    batch_index: str,
    total_batches: int,
    retry_count: int = 0,
) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]]]:
    payload = call_model(
        project,
        batch,
        work_unit_id=f"cards:{batch_index}:try{retry_count}",
    )
    if payload is None:
        return [], [f"{batch[0]['id']}..{batch[-1]['id']}: 模型不可用，已保留为候选。"], [
            {"error_code": "MODEL_UNAVAILABLE", "stage": "ai", "retryable": False}
        ]
    if "error" not in payload:
        model_segments = payload.get("segments")
        if isinstance(model_segments, list) and model_segments:
            return reconcile_model_segment_ids(batch, model_segments), [], []
        payload = {
            "error": "模型返回了 JSON，但缺少非空 segments 数组。",
            "error_code": "MODEL_INVALID_STRUCTURE",
            "stage": "ai",
            "retryable": True,
        }

    error_message = str(payload.get("error") or "模型批次失败")
    details = {
        "error_code": payload.get("error_code"),
        "stage": payload.get("stage"),
        "retryable": payload.get("retryable"),
    }
    if retry_count == 0 and retryable_model_payload(payload):
        progress_command = str(project.get("_progress_command") or "generate")
        emit_monotonic_model_progress(
            project,
            progress_command,
            "ai",
            70,
            f"模型连接中断，正在重试第 {batch_index}/{total_batches} 批 1/2。",
        )
        time.sleep(2)
        return call_model_batch_with_retry(
            project,
            batch,
            batch_index=batch_index,
            total_batches=total_batches,
            retry_count=1,
        )

    if len(batch) > 1 and retryable_model_payload(payload):
        midpoint = max(1, len(batch) // 2)
        progress_command = str(project.get("_progress_command") or "generate")
        emit_monotonic_model_progress(
            project,
            progress_command,
            "ai",
            72,
            f"第 {batch_index}/{total_batches} 批失败，已拆成 2 个小批继续生成。",
        )
        left_segments, left_errors, left_details = call_model_batch_with_retry(
            project,
            batch[:midpoint],
            batch_index=f"{batch_index}.1",
            total_batches=total_batches,
            retry_count=1,
        )
        right_segments, right_errors, right_details = call_model_batch_with_retry(
            project,
            batch[midpoint:],
            batch_index=f"{batch_index}.2",
            total_batches=total_batches,
            retry_count=1,
        )
        return left_segments + right_segments, left_errors + right_errors, left_details + right_details

    return [], [f"{batch[0]['id']}..{batch[-1]['id']}: {error_message}"], [details]


def emit_monotonic_model_progress(
    project: dict[str, Any],
    command: str,
    stage: str,
    percent: int,
    message: str,
) -> None:
    previous = int(project.get("_model_progress_percent") or 0)
    current = max(previous, int(percent))
    project["_model_progress_percent"] = current
    emit_progress(command, stage, current, message)


def card_generation_segment_weight(segment: dict[str, Any]) -> int:
    text = " ".join(
        str(segment.get(key) or "")
        for key in [
            "text",
            "answer_core",
            "exact_span",
            "learning_action",
            "phrase_card_focus",
            "phrase_decision_reason",
        ]
    )
    point_text = " ".join(
        str(point.get(key) or "")
        for point in segment.get("learning_points", []) or []
        if isinstance(point, dict)
        for key in ["source_sentence", "answer_core", "exact_span", "learning_action", "reason"]
    )
    return max(1, math.ceil((len(text) + len(point_text)) / 520))


def final_card_batch_weight(api: dict[str, Any], batch_size: int) -> int:
    raw_value = api.get("card_generation_batch_weight") or api.get("final_card_batch_weight")
    if raw_value in (None, ""):
        raw_value = max(8, batch_size * 2)
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        value = max(8, batch_size * 2)
    return max(1, min(80, value))


def weighted_card_generation_batches(
    segments: list[dict[str, Any]],
    *,
    batch_size: int,
    max_weight: int,
) -> list[tuple[int, list[dict[str, Any]]]]:
    batches: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_weight = 0
    for segment in segments:
        segment_weight = card_generation_segment_weight(segment)
        if current and (len(current) >= batch_size or current_weight + segment_weight > max_weight):
            batches.append(current)
            current = []
            current_weight = 0
        current.append(segment)
        current_weight += segment_weight
    if current:
        batches.append(current)
    return [(index + 1, batch) for index, batch in enumerate(batches)]


def call_model_batches(project: dict[str, Any], segments: list[dict[str, Any]], batch_size: int = 10) -> dict[str, Any] | None:
    if not segments:
        return None
    api = project.get("api_config") or {}
    if api.get("provider", "local") == "local" or not model_api_available(api):
        return None
    batch_size = final_card_batch_size(api, batch_size)
    merged: list[dict[str, Any]] = []
    errors: list[str] = []
    error_details: list[dict[str, Any]] = []
    any_called = False
    max_batch_weight = final_card_batch_weight(api, batch_size)
    batches = weighted_card_generation_batches(segments, batch_size=batch_size, max_weight=max_batch_weight)
    total_batches = max(1, len(batches))
    concurrency = final_card_generation_concurrency(api, total_batches)
    progress_command = str(project.get("_progress_command") or "generate")
    project["_model_progress_percent"] = 0
    progress_start = 24
    progress_span = 58

    def run_one(index: int, batch: list[dict[str, Any]]) -> tuple[int, list[dict[str, Any]], list[str], list[dict[str, Any]]]:
        provider_hint = "，thinking 已保留" if is_thinking_model_config(api) else ""
        if concurrency <= 1:
            percent = min(82, progress_start + int((index - 1) / total_batches * progress_span))
            emit_monotonic_model_progress(
                project,
                progress_command,
                "ai",
                percent,
                f"正在生成卡片正文：第 {index}/{total_batches} 批，每批最多 {batch_size} 个学习点，动态权重 {max_batch_weight}{provider_hint}。",
            )
        batch_segments, batch_errors, batch_error_details = call_model_batch_with_retry(
            project,
            batch,
            batch_index=str(index),
            total_batches=total_batches,
        )
        return index, batch_segments, batch_errors, batch_error_details

    if concurrency <= 1:
        for index, batch in batches:
            _, batch_segments, batch_errors, batch_error_details = run_one(index, batch)
            any_called = True
            merged.extend(batch_segments)
            errors.extend(batch_errors)
            error_details.extend(batch_error_details)
    else:
        emit_monotonic_model_progress(
            project,
            progress_command,
            "ai",
            progress_start,
            f"最终制卡启用 {concurrency} 路并发：{total_batches} 批，每批最多 {batch_size} 个学习点，动态权重 {max_batch_weight}。",
        )
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = [pool.submit(run_one, index, batch) for index, batch in batches]
            completed_batches = 0
            for future in as_completed(futures):
                index, batch_segments, batch_errors, batch_error_details = future.result()
                completed_batches += 1
                any_called = True
                merged.extend(batch_segments)
                errors.extend(batch_errors)
                error_details.extend(batch_error_details)
                percent = min(82, progress_start + int(completed_batches / total_batches * progress_span))
                emit_monotonic_model_progress(
                    project,
                    progress_command,
                    "ai",
                    percent,
                    f"卡片正文已完成 {completed_batches}/{total_batches} 批；最近完成批号 {index}。",
                )
    if errors and not merged:
        first_detail = next((item for item in error_details if item.get("error_code")), {})
        return {"error": "；".join(errors), **first_detail}
    result: dict[str, Any] = {"segments": merged}
    if errors:
        result["error"] = "部分批次失败：" + "；".join(errors)
        first_detail = next((item for item in error_details if item.get("error_code")), {})
        result.update(first_detail)
    return result if any_called else None


def phrase_review_available(project: dict[str, Any]) -> bool:
    api = project.get("api_config") or {}
    return bool(
        model_api_available(api)
        and (api.get("provider", "local") in OPENAI_COMPATIBLE_PROVIDERS or is_gemini_vertex_config(api))
    )


def build_phrase_review_prompt(project: dict[str, Any], segments: list[dict[str, Any]]) -> str:
    level = str(project.get("level", "B1"))
    collection_levels = collection_levels_from_payload(project, level)
    selection_strategy = normalized_selection_strategy(project)
    focus_instruction = language_focus_instruction(project)
    material_context_instruction = material_context_for_prompt(project.get("material_context"))
    compact = [
        {
            "id": segment["id"],
            "source_time": segment["source_time"],
            "english": segment["text"],
            "local_phrase": segment.get("phrase", "key expression"),
            "exact_span": segment.get("exact_span", ""),
            "normalized_answer": segment.get("normalized_answer", ""),
            "candidate_kind": segment.get("candidate_kind", ""),
            "phrase_type": segment.get("phrase_type", ""),
            "content_kind": segment.get("content_kind", ""),
            "candidate_source": segment.get("candidate_source", ""),
            "phrase_card_focus": segment.get("phrase_card_focus", ""),
            "local_score": round(float(segment.get("score", 0)), 2),
        }
        for segment in segments
    ]
    return (
        "你是中文母语者的英语学习点评审老师。请判断这些 typed learning points 是否值得做 Anki 卡，"
        "不要生成卡片内容。学习点可能是表达、语境生词、语法句法、听力难点或语气风险。目标是同时提高数量和质量："
        "保留真实可用的学习点，拒绝主题词、专有名词、"
        "半截词串、视频口播引入语和过基础表达。"
        "请像英语老师一样先判断学习动作：这个片段训练听懂、会用、会替换、理解语气，还是根本不值得制卡。"
        f"{material_context_instruction}"
        f"{focus_instruction}"
        "判断标准："
        "1) exact_span 必须逐词来自 english 原句；normalized_answer/answer_core 必须是英文答案本体。"
        "词伙通常 2-6 个词，单词用法可以是 1 个核心词，语法框架可以是原句里的可替换结构。它必须完整、自然、可换场景复用。"
        "2) keep 只给真正值得复习的表达；如果只是句子主题、名词堆叠、产品名、working with 这类泛短语，decision=skip。"
        "3) B1 或更高水平遇到 talk about、go home 这类 A1/A2 基础表达时降低 value_score；如果仍有明确训练动作，可保留为候选，不要仅因基础而硬过滤。"
        "4) value_score 用 1-5：5=非常值得学，4=推荐制卡，3=可待审，1-2=跳过。"
        "5) candidate_kind 从 expression、contextual_vocab、grammar_pattern、listening_feature、pragmatic_risk 中选一个。"
        "phrase_type 从 spoken_phrase、sentence_frame、collocation、discourse_marker、idiom、listening_sentence、vocabulary_usage、grammar_pattern 中选一个。"
        "6) score_breakdown 必须给 transferability、spoken_naturalness、level_fit、context_dependence、answer_clarity、card_uniqueness、learning_action、risk_boundary 八项 1-5 分。"
        "7) card_focus 用一句短中文说明这张卡应该训练什么；skip 时写 reject_reason。"
        "8) answer_core 禁止包含中文、IPA、发音说明、语法解释或“X 是 Y”的说明；这些只能放到后续字段里。"
        "9) 同一句可以 keep 多个学习点，但训练动作必须明显不同；expression、contextual_vocab、grammar_pattern、listening_feature 可以共存，重复训练目标不能共存。"
        "好例子：Honestly, it's such a nice Monday morning. -> keep, phrase=such a nice, phrase_type=sentence_frame, card_focus=训练 such a nice + 名词表达自然赞叹。"
        "低优先级例子：Today we are going to talk about AI models. -> candidate_only 或 low score, phrase=talk about, reason=基础表达且只是视频引入。"
        "只返回严格 JSON，不要 Markdown。结构："
        '{"candidates":[{"id":"seg_0001","decision":"keep|skip","phrase":"原句里的词伙",'
        '"candidate_kind":"expression|contextual_vocab|grammar_pattern|listening_feature|pragmatic_risk",'
        '"exact_span":"逐词来自原句","normalized_answer":"英文标准答案","answer_core":"英文答案本体",'
        '"phrase_type":"spoken_phrase|sentence_frame|collocation|discourse_marker|idiom|listening_sentence|vocabulary_usage|grammar_pattern",'
        '"value_score":1,"score_breakdown":{"transferability":1,"spoken_naturalness":1,"level_fit":1,"context_dependence":1,"answer_clarity":1,"card_uniqueness":1,"learning_action":1,"risk_boundary":1},'
        '"reason":"推荐理由","card_focus":"训练重点","reject_reason":"跳过原因"}]}。'
        f"用户当前水平：{level}，它只用于解释深度和质量判断，不要作为硬过滤。"
        f"筛选策略：{SELECTION_STRATEGY_LABELS.get(selection_strategy, selection_strategy)}。"
        f"高级难度关注范围：{', '.join(collection_levels)}。"
        f"候选字幕：{json.dumps(compact, ensure_ascii=False)}"
    )


def phrase_review_score(value: Any) -> int:
    try:
        score = int(round(float(value)))
    except (TypeError, ValueError):
        score = 0
    return max(0, min(5, score))


def normalized_phrase_key(phrase: str) -> str:
    return learning_span_normalized_phrase_key(phrase)


def is_placeholder_learning_phrase(value: Any) -> bool:
    return normalized_phrase_key(str(value or "")) in {"", "key expression", "n/a"}


def review_phrase_choice(
    text: str,
    proposed: str,
    fallback: str,
    level: str,
    collection_levels: list[str] | None = None,
    candidate_kind: str = "expression",
    phrase_type: str = "",
) -> str:
    candidates = [proposed, fallback, find_phrase(text, level, collection_levels)]
    seen: set[str] = set()
    for candidate in candidates:
        normalized = re.sub(r"\s+", " ", str(candidate or "").strip())
        key = normalized.lower()
        if not normalized or key in seen or key == "key expression":
            continue
        seen.add(key)
        if usable_learning_point_span(text, normalized, candidate_kind, phrase_type):
            return normalized
    return ""


def repair_review_segment_phrase(
    segment: dict[str, Any],
    level: str,
    collection_levels: list[str] | None = None,
) -> dict[str, Any] | None:
    candidate_kind = candidate_kind_for_segment(segment)
    phrase_type = str(segment.get("phrase_type") or phrase_type_for_candidate_kind(candidate_kind))
    phrase = review_phrase_choice(
        str(segment.get("text") or ""),
        str(segment.get("phrase") or ""),
        "",
        level,
        collection_levels,
        candidate_kind,
        phrase_type,
    )
    if not phrase:
        return None
    return {
        **segment,
        "phrase": phrase,
        "recommendation": max(3, int(segment.get("recommendation") or 3)),
    }


def skipped_review_segment(segment: dict[str, Any], status: str, reason: str, value_score: int = 0) -> dict[str, Any]:
    return {
        **segment,
        "cards": [],
        "phrase_value_score": value_score,
        "phrase_review_status": status,
        "phrase_review_source": "ai",
        "phrase_decision_reason": "",
        "phrase_reject_reason": reason,
        "phrase_card_focus": "",
    }


def source_learning_point_groups(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for segment in segments:
        grouped.setdefault(learning_point_source_key(segment), []).append(segment)

    groups: list[dict[str, Any]] = []
    for source_id, items in grouped.items():
        ranked = sorted(items, key=lambda item: float(item.get("score") or 0), reverse=True)
        primary = ranked[0]
        groups.append(
            {
                "source_segment_id": source_id,
                "start": primary.get("start"),
                "end": primary.get("end"),
                "source_time": primary.get("source_time"),
                "text": primary.get("text"),
                "local_candidates": [
                    {
                        "id": item.get("id"),
                        "candidate_kind": candidate_kind_for_segment(item),
                        "phrase_type": item.get("phrase_type") or phrase_type_for_candidate_kind(candidate_kind_for_segment(item)),
                        "exact_span": item.get("exact_span") or item.get("phrase") or "",
                        "answer_core": item.get("answer_core") or item.get("normalized_answer") or item.get("phrase") or "",
                        "normalized_answer": item.get("normalized_answer") or item.get("phrase") or "",
                        "card_focus": item.get("phrase_card_focus") or "",
                        "value_score": item.get("phrase_value_score") or item.get("score") or 0,
                    }
                    for item in ranked[:8]
                ],
            }
        )
    return sorted(groups, key=lambda item: (float(item.get("start") or 0), str(item.get("source_segment_id") or "")))


def build_source_learning_point_expansion_prompt(project: dict[str, Any], source_groups: list[dict[str, Any]]) -> str:
    level = str(project.get("level", "B1"))
    language = normalize_learning_language(project.get("language", "en"))
    selection_strategy = normalized_selection_strategy(project)
    focus_instruction = language_focus_instruction(project)
    material_context_instruction = material_context_for_prompt(project.get("material_context"))
    max_points = max_learning_points_per_source(project)
    compact_groups = [
        {
            "source_segment_id": group["source_segment_id"],
            "source_time": group.get("source_time"),
            "sentence": group.get("text"),
            "local_candidates": group.get("local_candidates", []),
        }
        for group in source_groups
    ]
    return (
        "你是中文母语者的多语言 Anki 学习点发现老师。请逐句补漏学习点，不要生成卡片内容。"
        "输入里的 local_candidates 是本地已经发现的候选，必须保留给后续评审；你的任务只是在同一句里补充遗漏的不同学习动作。"
        f"{material_context_instruction}"
        f"{focus_instruction}"
        "硬规则："
        "1) 每个新增 learning point 的 exact_span 必须逐字/逐词出现在 sentence 里；不能虚构、改写或跨句拼接。"
        "2) answer_core/normalized_answer 只能写目标语言答案本体，禁止写 IPA、中文释义、发音说明、语法解释或“X 是 Y”。"
        "3) candidate_kind 只能是 expression、contextual_vocab、grammar_pattern、listening_feature、pragmatic_risk。"
        "4) phrase_type 只能是 spoken_phrase、sentence_frame、collocation、discourse_marker、idiom、listening_sentence、vocabulary_usage、grammar_pattern。"
        "5) 同一句里不同训练动作可以共存，例如 collocation、单词语境义、语法框架、听力弱读；训练动作重复的不要新增。"
        "6) 不要为了数量硬凑低价值点；value_score 1-5，3=待审，4-5=值得进入后续评审。"
        f"7) 每句最多返回 {max_points} 个总学习点；如果本地候选已经覆盖，不要重复新增。"
        "只返回严格 JSON，不要 Markdown。结构："
        '{"sources":[{"source_segment_id":"src_xxx","learning_points":[{'
        '"candidate_kind":"expression|contextual_vocab|grammar_pattern|listening_feature|pragmatic_risk",'
        '"phrase_type":"spoken_phrase|sentence_frame|collocation|discourse_marker|idiom|listening_sentence|vocabulary_usage|grammar_pattern",'
        '"exact_span":"原句中的连续片段","answer_core":"目标语言答案本体","normalized_answer":"标准化答案",'
        '"card_focus":"中文短句说明训练动作","value_score":4,"reason":"为什么值得补充"}]}]}。'
        f"用户水平：{level}。学习语言代码：{language}。筛选策略：{SELECTION_STRATEGY_LABELS.get(selection_strategy, selection_strategy)}。"
        f"源句：{json.dumps(compact_groups, ensure_ascii=False)}"
    )


def call_source_learning_point_expansion(
    project: dict[str, Any],
    source_groups: list[dict[str, Any]],
    batch_size: int = 8,
) -> tuple[dict[str, list[dict[str, Any]]], str | None]:
    api = project.get("api_config") or {}
    if not phrase_review_available(project) or not source_groups:
        return {}, None

    expanded: dict[str, list[dict[str, Any]]] = {}
    try:
        total_batches = max(1, (len(source_groups) + batch_size - 1) // batch_size)
        for start in range(0, len(source_groups), batch_size):
            batch = source_groups[start : start + batch_size]
            batch_index = start // batch_size + 1
            percent = min(58, 54 + int((batch_index - 1) / total_batches * 4))
            emit_progress(
                "generate",
                "learning_point_expansion",
                percent,
                f"AI 正在逐句补漏学习点：第 {batch_index}/{total_batches} 批。",
            )
            prompt = build_source_learning_point_expansion_prompt(project, batch)
            if is_gemini_vertex_config(api):
                content = gemini_vertex_generate_content(
                    api,
                    prompt,
                    temperature=0.15,
                    timeout=180 if is_gemini_vertex_thinking_config(api) else 120,
                    max_output_tokens=9000 if is_gemini_vertex_thinking_config(api) else 4500,
                )
            else:
                response = compatible_chat_completion(
                    api,
                    [
                        {"role": "system", "content": "Return only valid JSON."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.15,
                    timeout=180 if is_thinking_model_config(api) else 120,
                    max_tokens=4500 if is_deepseek_thinking_config(api) else 3200,
                    progress={
                        "command": "generate",
                        "stage": "learning_point_expansion",
                        "percent": percent,
                        "message": "AI 逐句补漏学习点",
                    },
                    work_unit_id=f"learning-point-expansion:{batch_index}",
                )
                content = chat_completion_content(response)
            payload = extract_json_object(content or "")
            for source in payload.get("sources", []):
                if not isinstance(source, dict):
                    continue
                source_id = str(source.get("source_segment_id") or "").strip()
                points = source.get("learning_points")
                if source_id and isinstance(points, list):
                    expanded.setdefault(source_id, []).extend(point for point in points if isinstance(point, dict))
    except Exception as err:
        return {}, f"逐句补漏学习点失败，已回退到本地候选：{err}"

    return expanded, None


def expansion_point_to_segment(
    point: dict[str, Any],
    source_segment: dict[str, Any],
    project: dict[str, Any],
    index: int,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    source_id = learning_point_source_key(source_segment)
    kind = str(point.get("candidate_kind") or point.get("kind") or "").strip()
    if kind not in CANDIDATE_KIND_TO_PHRASE_TYPE:
        kind = candidate_kind_for_phrase_type(str(point.get("phrase_type") or ""), "expression")
    if not candidate_kind_allowed_by_focus(kind, project):
        rejected = skipped_review_segment(
            {
                **source_segment,
                "id": f"{source_segment.get('id', 'seg')}_expansion_reject_{index}",
                "source_segment_id": source_id,
                "candidate_kind": kind,
            },
            "reject",
            "模型补漏学习点不符合当前学习重点，已拒绝。",
            phrase_review_score(point.get("value_score")),
        )
        return None, rejected
    phrase_type = str(point.get("phrase_type") or phrase_type_for_candidate_kind(kind)).strip()
    if phrase_type not in PHRASE_TYPE_TO_CANDIDATE_KIND:
        phrase_type = phrase_type_for_candidate_kind(kind)
    try:
        value_score = float(point.get("value_score") or point.get("score") or 3)
    except (TypeError, ValueError):
        value_score = 3.0
    value_score = max(1.0, min(5.0, value_score))
    raw_candidate = {
        "kind": kind,
        "candidate_kind": kind,
        "phrase_type": phrase_type,
        "exact_span": point.get("exact_span") or point.get("phrase") or point.get("answer_core") or "",
        "normalized_answer": point.get("normalized_answer") or point.get("answer_core") or point.get("exact_span") or "",
        "answer_core": point.get("answer_core") or point.get("normalized_answer") or point.get("exact_span") or "",
        "phrase": point.get("phrase") or point.get("exact_span") or point.get("answer_core") or "",
        "content_kind": content_kind_for_phrase_type(phrase_type),
        "language": normalize_learning_language(project.get("language", source_segment.get("language", "en"))),
    }
    is_valid, reason, normalized_point = sanitize_learning_point_contract(
        raw_candidate,
        str(source_segment.get("text") or ""),
        language=project.get("language", source_segment.get("language", "en")),
    )
    reject_seed = {
        **source_segment,
        "id": f"{source_segment.get('id', 'seg')}_expansion_reject_{index}",
        "source_segment_id": source_id,
        "candidate_kind": kind,
        "phrase_type": phrase_type,
        "exact_span": raw_candidate["exact_span"],
        "normalized_answer": raw_candidate["normalized_answer"],
        "answer_core": raw_candidate["answer_core"],
        "candidate_source": "source_expansion",
    }
    if not is_valid:
        return None, skipped_review_segment(reject_seed, "reject", f"模型补漏{reason}", phrase_review_score(value_score))

    answer = str(normalized_point.get("answer_core") or normalized_point.get("normalized_answer") or normalized_point.get("exact_span") or "")
    learning_point = {
        "id": learning_point_id_for_candidate(source_id, normalized_point),
        "kind": normalized_point["candidate_kind"],
        "exact_span": normalized_point["exact_span"],
        "exact_span_start": normalized_point.get("exact_span_start"),
        "exact_span_end": normalized_point.get("exact_span_end"),
        "answer_core": answer,
        "difficulty": str(project.get("level", "B1")),
        "value_score": round(value_score, 2),
        "reason": str(point.get("card_focus") or point.get("reason") or "模型逐句补漏发现的学习点。"),
        "suggested_card_type": "listening" if normalized_point["candidate_kind"] == "listening_feature" else "phrase",
        "content_kind": normalized_point["content_kind"],
        "normalized_answer": normalized_point["normalized_answer"],
        "source_evidence": source_segment.get("text", ""),
        "language": normalize_learning_language(project.get("language", source_segment.get("language", "en"))),
        "learning_action": normalized_point.get("learning_action", ""),
        "learning_action_key": normalized_point.get("learning_action_key", ""),
        "source": normalized_point.get("source", "model"),
        "confidence": normalized_point.get("confidence", "medium"),
        "validation_status": normalized_point.get("validation_status", "valid"),
        "repair_history": normalized_point.get("repair_history", []),
    }
    media_start, media_end = segment_media_bounds(
        float(source_segment.get("start") or 0),
        float(source_segment.get("end") or 0),
        str(source_segment.get("text") or ""),
        normalized_point["exact_span"],
        True,
    )
    segment = {
        **source_segment,
        "id": f"{source_segment.get('id', 'seg')}_expansion_{stable_id(f'{source_id}:{answer}:{kind}:{index}') & 0xFFFF:04x}",
        "source_segment_id": source_id,
        "learning_point_id": learning_point["id"],
        "learning_points": [learning_point],
        "media_start": media_start,
        "media_end": media_end,
        "media_source_time": f"{fmt_time(media_start)} - {fmt_time(media_end)}",
        "recommendation": min(5, max(1, round(value_score))),
        "phrase": answer,
        "exact_span": normalized_point["exact_span"],
        "exact_span_start": normalized_point.get("exact_span_start"),
        "exact_span_end": normalized_point.get("exact_span_end"),
        "normalized_answer": normalized_point["normalized_answer"],
        "answer_core": answer,
        "candidate_kind": normalized_point["candidate_kind"],
        "phrase_type": normalized_point["phrase_type"],
        "content_kind": normalized_point["content_kind"],
        "candidate_source": "source_expansion",
        "learning_point_schema_version": LEARNING_POINT_SCHEMA_VERSION,
        "learning_action": normalized_point.get("learning_action", ""),
        "learning_action_key": normalized_point.get("learning_action_key", ""),
        "contract_source": normalized_point.get("source", "model"),
        "confidence": normalized_point.get("confidence", "medium"),
        "validation_status": normalized_point.get("validation_status", "valid"),
        "repair_history": normalized_point.get("repair_history", []),
        "phrase_card_focus": str(point.get("card_focus") or point.get("reason") or ""),
        "source_evidence": source_segment.get("text", ""),
        "score": float(source_segment.get("score") or 0) + max(0.0, value_score - 3.0),
    }
    return segment, None


def expand_learning_points_by_source(
    project: dict[str, Any],
    segments: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
    if normalized_selection_strategy(project) not in {"catch_all", "exhaustive"}:
        return segments, [], None
    mode = normalized_source_expansion_mode(project)
    if mode == "off":
        project["_source_expansion_stats"] = {
            "mode": mode,
            "eligible_source_groups": 0,
            "requested_source_groups": 0,
            "added_candidates": 0,
            "rejected_candidates": 0,
        }
        return segments, [], None
    groups = source_learning_point_groups(segments)
    eligible_count = len(groups)
    if mode == "auto":
        max_groups = max_source_expansion_groups(project)
        groups = sorted(
            groups,
            key=lambda group: (
                len({str(item.get("candidate_kind") or "") for item in group.get("local_candidates", [])}),
                max(float(item.get("value_score") or 0) for item in group.get("local_candidates", []) or [{"value_score": 0}]),
                len(str(group.get("text") or "")),
                -float(group.get("start") or 0),
            ),
            reverse=True,
        )[:max_groups]
        groups = sorted(groups, key=lambda item: (float(item.get("start") or 0), str(item.get("source_segment_id") or "")))
    project["_source_expansion_stats"] = {
        "mode": mode,
        "eligible_source_groups": eligible_count,
        "requested_source_groups": len(groups),
        "added_candidates": 0,
        "rejected_candidates": 0,
    }
    expanded, warning = call_source_learning_point_expansion(project, groups)
    if not expanded:
        return segments, [], warning

    source_primary: dict[str, dict[str, Any]] = {}
    for segment in segments:
        source_primary.setdefault(learning_point_source_key(segment), segment)

    additions: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for source_id, points in expanded.items():
        source_segment = source_primary.get(source_id)
        if not source_segment:
            continue
        for index, point in enumerate(points, start=1):
            addition, reject = expansion_point_to_segment(point, source_segment, project, index)
            if addition:
                additions.append(addition)
            if reject:
                rejected.append(reject)

    merged: list[dict[str, Any]] = list(segments)
    for addition in sorted(additions, key=lambda item: float(item.get("score") or 0), reverse=True):
        same_source = [item for item in merged if learning_point_source_key(item) == learning_point_source_key(addition)]
        if any(learning_actions_overlap(addition, existing) for existing in same_source):
            rejected.append(
                skipped_review_segment(
                    addition,
                    "duplicate",
                    "模型补漏学习点与同句已有训练动作重复，已合并。",
                    phrase_review_score(addition.get("score")),
                )
            )
            continue
        merged.append(addition)

    stats = project.setdefault("_source_expansion_stats", {})
    stats["added_candidates"] = len(additions)
    stats["rejected_candidates"] = len(rejected)
    return sorted(merged, key=lambda item: (float(item.get("start") or 0), str(item.get("id") or ""))), sorted(
        rejected,
        key=lambda item: (float(item.get("start") or 0), str(item.get("id") or "")),
    ), warning


def _score_breakdown_value(score_breakdown: dict[str, Any], key: str) -> int | None:
    if key not in score_breakdown:
        return None
    try:
        return int(round(float(score_breakdown.get(key))))
    except (TypeError, ValueError):
        return None


def validate_review_learning_point(
    review: dict[str, Any],
    segment: dict[str, Any],
    phrase: str,
    candidate_kind: str,
    phrase_type: str,
    score_breakdown: dict[str, Any],
) -> tuple[bool, str, dict[str, Any]]:
    text = str(segment.get("text") or "")
    final_kind = candidate_kind or candidate_kind_for_segment(segment)
    final_phrase_type = phrase_type or phrase_type_for_candidate_kind(final_kind)
    point_payload = {
        "kind": final_kind,
        "candidate_kind": final_kind,
        "phrase_type": final_phrase_type,
        "exact_span": review.get("exact_span") or segment.get("exact_span") or phrase,
        "normalized_answer": review.get("normalized_answer") or review.get("answer_core") or phrase or segment.get("normalized_answer"),
        "answer_core": review.get("answer_core") or review.get("normalized_answer") or phrase,
        "phrase": review.get("phrase") or phrase,
        "content_kind": content_kind_for_phrase_type(final_phrase_type),
        "language": normalize_learning_language(segment.get("language", "en")),
        "card_focus": review.get("card_focus") or segment.get("phrase_card_focus") or "",
        "reason": review.get("reason") or segment.get("phrase_decision_reason") or "",
        "value_score": review.get("value_score") or segment.get("phrase_value_score") or segment.get("recommendation") or 0,
        "candidate_source": segment.get("candidate_source") or "model",
    }
    for key in PRONUNCIATION_FIELDS:
        if review.get(key):
            point_payload[key] = review.get(key)
    if review.get("pronunciation_meta"):
        point_payload["pronunciation_meta"] = review.get("pronunciation_meta")
    is_valid, validation_reason, normalized_point = sanitize_learning_point_contract(
        point_payload,
        text,
        language=segment.get("language", "en"),
    )
    if not is_valid:
        return False, f"AI 评审{validation_reason}", {}
    for key, label in (("answer_clarity", "答案清晰度"), ("learning_action", "学习动作")):
        value = _score_breakdown_value(score_breakdown, key)
        if value is not None and value < 3:
            return False, f"AI 评审{label}低于 3 分。", {}

    return True, "", {
        "exact_span": normalized_point["exact_span"],
        "exact_span_start": normalized_point.get("exact_span_start"),
        "exact_span_end": normalized_point.get("exact_span_end"),
        "normalized_answer": normalized_point["normalized_answer"],
        "answer_core": normalized_point["answer_core"],
        "candidate_kind": normalized_point["candidate_kind"],
        "phrase_type": normalized_point["phrase_type"],
        "content_kind": normalized_point["content_kind"],
        "phonetic_ipa": normalized_point.get("phonetic_ipa", ""),
        "spoken_ipa": normalized_point.get("spoken_ipa", ""),
        "source_spoken_ipa": normalized_point.get("source_spoken_ipa", ""),
        "pronunciation_note": normalized_point.get("pronunciation_note", ""),
        "pronunciation_confidence": normalized_point.get("pronunciation_confidence", ""),
        "pronunciation_status": normalized_point.get("pronunciation_status", ""),
        "source_pronunciation_status": normalized_point.get("source_pronunciation_status", ""),
        "pronunciation_meta": normalized_point.get("pronunciation_meta") or None,
        "learning_action": normalized_point.get("learning_action", ""),
        "learning_action_key": normalized_point.get("learning_action_key", ""),
        "contract_source": normalized_point.get("source", "model"),
        "confidence": normalized_point.get("confidence", "medium"),
        "repair_history": normalized_point.get("repair_history", []),
        "validation_status": normalized_point.get("validation_status", "valid"),
        "validation_issues": " / ".join(normalized_point.get("validation_issues", [])),
    }


def apply_phrase_review_decisions(
    segments: list[dict[str, Any]],
    reviews: dict[str, dict[str, Any]],
    project: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    level = str(project.get("level", "B1"))
    collection_levels = discovery_collection_levels(project, level)
    kept: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for segment in segments:
        review = reviews.get(segment["id"])
        if not review:
            repaired = repair_review_segment_phrase(segment, level, collection_levels) or segment
            repaired = refine_segment_media_for_phrase(repaired, str(repaired.get("phrase") or ""))
            source_id = str(
                repaired.get("source_segment_id")
                or source_segment_key(float(repaired.get("start") or 0), float(repaired.get("end") or 0), str(repaired.get("text") or ""))
            )
            kept.append(
                {
                    **repaired,
                    "source_segment_id": source_id,
                    "phrase_value_score": 3,
                    "phrase_review_status": "needs_review",
                    "phrase_review_source": "ai",
                    "phrase_decision_reason": "AI 评审没有返回这个片段，保留为待审候选。",
                    "phrase_reject_reason": "",
                    "phrase_card_focus": "人工确认是否值得制卡。",
                    "content_kind": content_kind_for_phrase_type(str(repaired.get("phrase_type") or "")),
                    "candidate_kind": candidate_kind_for_segment(repaired),
                    "exact_span": repaired.get("exact_span") or repaired.get("phrase", ""),
                    "normalized_answer": repaired.get("normalized_answer") or repaired.get("phrase", ""),
                    "answer_core": repaired.get("answer_core") or repaired.get("normalized_answer") or repaired.get("phrase", ""),
                    "candidate_source": repaired.get("candidate_source", ""),
                    "learning_point_schema_version": repaired.get("learning_point_schema_version") or LEARNING_POINT_SCHEMA_VERSION,
                    "source_evidence": repaired.get("text", ""),
                }
            )
            continue

        value_score = phrase_review_score(review.get("value_score"))
        decision = str(review.get("decision") or "").strip().lower()
        proposed = str(review.get("phrase") or "").strip()
        exact_span = str(review.get("exact_span") or "").strip()
        normalized_answer = str(review.get("normalized_answer") or "").strip()
        answer_core = str(review.get("answer_core") or "").strip()
        reason = str(review.get("reason") or "").strip()
        reject_reason = str(review.get("reject_reason") or "").strip()
        card_focus = str(review.get("card_focus") or "").strip()
        candidate_kind = str(review.get("candidate_kind") or segment.get("candidate_kind") or "").strip()
        phrase_type = str(review.get("phrase_type") or segment.get("phrase_type") or "").strip()
        if not candidate_kind:
            candidate_kind = candidate_kind_for_phrase_type(phrase_type, candidate_kind_for_segment(segment))
        if not phrase_type:
            phrase_type = phrase_type_for_candidate_kind(candidate_kind)
        score_breakdown = review.get("score_breakdown") if isinstance(review.get("score_breakdown"), dict) else {}
        phrase = review_phrase_choice(
            segment["text"],
            normalized_answer or answer_core or exact_span or proposed,
            segment.get("normalized_answer") or segment.get("answer_core") or segment.get("exact_span") or segment.get("phrase", ""),
            level,
            collection_levels,
            candidate_kind,
            phrase_type,
        )

        if decision != "keep" or value_score < 3:
            skipped.append(
                skipped_review_segment(
                    segment,
                    "reject",
                    reject_reason or reason or "AI 认为这个片段没有值得做卡的可迁移表达。",
                    value_score,
                )
            )
            continue
        if not phrase:
            skipped.append(
                skipped_review_segment(
                    segment,
                    "reject",
                    reject_reason or "AI 推荐的词伙不在原句中，且本地没有可修复的完整词伙。",
                    value_score,
                )
            )
            continue
        if is_too_basic_for_level(phrase, level):
            value_score = min(value_score, 3)

        ok, validation_reason, normalized_fields = validate_review_learning_point(
            review,
            segment,
            phrase,
            candidate_kind,
            phrase_type,
            score_breakdown,
        )
        if not ok:
            skipped.append(
                skipped_review_segment(
                    segment,
                    "reject",
                    reject_reason or validation_reason,
                    value_score,
                )
            )
            continue

        status = "recommended" if value_score >= 4 else "needs_review"
        refined_segment = refine_segment_media_for_phrase(segment, phrase)
        source_id = str(
            refined_segment.get("source_segment_id")
            or source_segment_key(float(refined_segment.get("start") or 0), float(refined_segment.get("end") or 0), str(refined_segment.get("text") or ""))
        )
        kept.append(
            {
                **refined_segment,
                "source_segment_id": source_id,
                "phrase": phrase,
                "exact_span": normalized_fields["exact_span"],
                "exact_span_start": normalized_fields.get("exact_span_start"),
                "exact_span_end": normalized_fields.get("exact_span_end"),
                "normalized_answer": normalized_fields["normalized_answer"],
                "answer_core": normalized_fields["answer_core"],
                "candidate_kind": normalized_fields["candidate_kind"],
                "recommendation": min(5, max(1, value_score)),
                "phrase_value_score": value_score,
                "phrase_review_status": status,
                "phrase_review_source": "ai",
                "phrase_decision_reason": reason or card_focus or "AI 认为这个表达值得制卡。",
                "phrase_reject_reason": "" if status == "recommended" else "词伙价值分为 3，默认进入待审。",
                "phrase_card_focus": card_focus or "围绕这个表达的真实语境和迁移用法制卡。",
                "phrase_type": normalized_fields["phrase_type"],
                "content_kind": normalized_fields["content_kind"],
                "phonetic_ipa": normalized_fields.get("phonetic_ipa", ""),
                "spoken_ipa": normalized_fields.get("spoken_ipa", ""),
                "source_spoken_ipa": normalized_fields.get("source_spoken_ipa", ""),
                "pronunciation_note": normalized_fields.get("pronunciation_note", ""),
                "pronunciation_confidence": normalized_fields.get("pronunciation_confidence", ""),
                "pronunciation_status": normalized_fields.get("pronunciation_status", ""),
                "source_pronunciation_status": normalized_fields.get("source_pronunciation_status", ""),
                "pronunciation_meta": normalized_fields.get("pronunciation_meta") or None,
                "learning_action": normalized_fields.get("learning_action", ""),
                "learning_action_key": normalized_fields.get("learning_action_key", ""),
                "contract_source": normalized_fields.get("contract_source", "model"),
                "confidence": normalized_fields.get("confidence", "medium"),
                "repair_history": normalized_fields.get("repair_history", []),
                "validation_status": normalized_fields.get("validation_status", "valid"),
                "validation_issues": normalized_fields.get("validation_issues", ""),
                "candidate_source": segment.get("candidate_source", ""),
                "learning_point_schema_version": LEARNING_POINT_SCHEMA_VERSION,
                "source_evidence": segment.get("text", ""),
                "score_breakdown": score_breakdown,
            }
        )

    return kept, skipped


def ensure_min_review_candidates(
    original_segments: list[dict[str, Any]],
    kept: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
    project: dict[str, Any],
    rejected_ids: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    max_segments = resolved_max_segments(project)
    min_count = min(len(original_segments), max_segments, max(8, min(18, round(max_segments * 0.45))))
    if len(kept) >= min_count:
        return kept, skipped

    kept_ids = {str(item.get("id")) for item in kept}
    promoted_ids: set[str] = set()
    ranked = sorted(
        original_segments,
        key=lambda item: (
            normalized_phrase_key(item.get("phrase", "")) != "key expression",
            float(item.get("score") or 0),
            -float(item.get("start") or 0),
        ),
        reverse=True,
    )
    for segment in ranked:
        segment_id = str(segment.get("id"))
        if segment_id in kept_ids or (rejected_ids and segment_id in rejected_ids):
            continue
        repaired = repair_review_segment_phrase(
            segment,
            str(project.get("level", "B1")),
            collection_levels_from_payload(project, str(project.get("level", "B1"))),
        )
        if not repaired:
            continue
        repaired = refine_segment_media_for_phrase(repaired, str(repaired.get("phrase") or ""))
        source_id = str(
            repaired.get("source_segment_id")
            or source_segment_key(float(repaired.get("start") or 0), float(repaired.get("end") or 0), str(repaired.get("text") or ""))
        )
        kept.append(
            {
                **repaired,
                "source_segment_id": source_id,
                "cards": [],
                "phrase_value_score": 3,
                "phrase_review_status": "needs_review",
                "phrase_review_source": "ai",
                "phrase_decision_reason": "AI 评审保留过少，系统保留这个本地高分候选供复核。",
                "phrase_reject_reason": "待审候选默认不导出；请确认词伙值得学后再启用。",
                "phrase_card_focus": "人工确认这句里是否有可迁移表达。",
                "content_kind": content_kind_for_phrase_type(str(repaired.get("phrase_type") or "")),
                "candidate_kind": candidate_kind_for_segment(repaired),
                "exact_span": repaired.get("exact_span") or repaired.get("phrase", ""),
                "normalized_answer": repaired.get("normalized_answer") or repaired.get("phrase", ""),
                "answer_core": repaired.get("answer_core") or repaired.get("normalized_answer") or repaired.get("phrase", ""),
                "candidate_source": repaired.get("candidate_source", ""),
                "learning_point_schema_version": repaired.get("learning_point_schema_version") or LEARNING_POINT_SCHEMA_VERSION,
                "source_evidence": repaired.get("text", ""),
            }
        )
        kept_ids.add(segment_id)
        promoted_ids.add(segment_id)
        if len(kept) >= min_count:
            break

    if promoted_ids:
        skipped = [item for item in skipped if str(item.get("id")) not in promoted_ids]
    return kept, skipped


def learning_point_source_key(segment: dict[str, Any]) -> str:
    explicit = str(segment.get("source_segment_id") or "").strip()
    if explicit:
        return explicit
    return source_segment_key(
        float(segment.get("start") or 0),
        float(segment.get("end") or 0),
        str(segment.get("text") or ""),
    )


def candidate_kind_priority(segment: dict[str, Any]) -> int:
    priority = {
        "pragmatic_risk": 5,
        "grammar_pattern": 4,
        "expression": 3,
        "contextual_vocab": 2,
        "listening_feature": 1,
    }
    return priority.get(str(segment.get("candidate_kind") or ""), 0)


def learning_actions_overlap(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if str(left.get("candidate_kind") or "") != str(right.get("candidate_kind") or ""):
        return False
    left_action_key = str(left.get("learning_action_key") or "").strip()
    right_action_key = str(right.get("learning_action_key") or "").strip()
    if left_action_key and right_action_key and left_action_key == right_action_key:
        return True
    left_answer = normalized_phrase_key(str(left.get("normalized_answer") or left.get("phrase") or ""))
    right_answer = normalized_phrase_key(str(right.get("normalized_answer") or right.get("phrase") or ""))
    if left_answer and right_answer and (left_answer == right_answer or phrase_in_text(left_answer, right_answer) or phrase_in_text(right_answer, left_answer)):
        return True
    left_focus = str(left.get("phrase_card_focus") or "")
    right_focus = str(right.get("phrase_card_focus") or "")
    return bool(left_focus and right_focus and word_overlap_ratio(left_focus, right_focus) >= 0.62)


def enforce_max_learning_points_per_source(
    segments: list[dict[str, Any]],
    max_per_source: int = 2,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for segment in segments:
        grouped.setdefault(learning_point_source_key(segment), []).append(segment)

    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for items in grouped.values():
        ranked = sorted(
            items,
            key=lambda item: (
                int(item.get("phrase_value_score") or 0),
                float(item.get("score") or 0),
                candidate_kind_priority(item),
                -float(item.get("start") or 0),
            ),
            reverse=True,
        )
        selected: list[dict[str, Any]] = []
        for item in ranked:
            if any(learning_actions_overlap(item, existing) for existing in selected):
                rejected.append(
                    skipped_review_segment(
                        item,
                        "duplicate",
                        "同一句已有训练动作相近的学习点，已合并为重复候选。",
                        phrase_review_score(item.get("phrase_value_score")),
                    )
                )
                continue
            if len(selected) < max_per_source:
                selected.append(item)
            else:
                rejected.append(
                    skipped_review_segment(
                        item,
                        "reject",
                        f"同一句学习点预算已满，只保留最清晰的 0-{max_per_source} 个。",
                        phrase_review_score(item.get("phrase_value_score")),
                    )
                )
        kept.extend(selected)

    return sorted(kept, key=lambda item: (float(item.get("start") or 0), str(item.get("id") or ""))), sorted(
        rejected,
        key=lambda item: (float(item.get("start") or 0), str(item.get("id") or "")),
    )


def split_duplicate_phrase_segments(segments: list[dict[str, Any]], max_per_phrase: int = 2) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ranked = sorted(
        segments,
        key=lambda item: (
            int(item.get("phrase_value_score") or 0),
            float(item.get("score") or 0),
            -float(item.get("start") or 0),
        ),
        reverse=True,
    )
    counts: dict[str, int] = {}
    kept: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    for segment in ranked:
        answer_key = normalized_phrase_key(segment.get("normalized_answer") or segment.get("phrase", ""))
        if is_placeholder_learning_phrase(answer_key):
            key = f"key expression::{segment.get('id', '')}"
        else:
            key_parts = [
                answer_key,
                str(segment.get("candidate_kind") or candidate_kind_for_segment(segment)),
                re.sub(r"\s+", " ", str(segment.get("phrase_card_focus") or "").strip().lower())[:80],
            ]
            key = "::".join(part for part in key_parts if part)
        if not key:
            duplicates.append(skipped_review_segment(segment, "duplicate", "缺少稳定词伙，已从候选中移除。", 0))
            continue
        if counts.get(key, 0) >= max_per_phrase:
            duplicates.append(
                skipped_review_segment(
                    segment,
                    "duplicate",
                    f"词伙 {segment.get('phrase', '')} 已保留 {max_per_phrase} 个更好的语境，本片段合并为重复候选。",
                    phrase_review_score(segment.get("phrase_value_score")),
                )
            )
            continue
        counts[key] = counts.get(key, 0) + 1
        kept.append(segment)
    return sorted(kept, key=lambda item: item["start"]), sorted(duplicates, key=lambda item: item["start"])


def limit_reviewed_segments(
    segments: list[dict[str, Any]],
    max_segments: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ranked = sorted(
        segments,
        key=lambda item: (
            int(item.get("phrase_value_score") or 0),
            float(item.get("score") or 0),
            -float(item.get("start") or 0),
        ),
        reverse=True,
    )
    kept = ranked[:max_segments]
    overflow = [
        skipped_review_segment(
            item,
            "reject",
            "片段预算已满，已优先保留评分更高的候选。",
            phrase_review_score(item.get("phrase_value_score")),
        )
        for item in ranked[max_segments:]
    ]
    return sorted(kept, key=lambda item: item["start"]), sorted(overflow, key=lambda item: item["start"])


def review_phrase_candidates_with_mimo(
    project: dict[str, Any],
    segments: list[dict[str, Any]],
    batch_size: int = 16,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
    if not phrase_review_available(project) or not segments:
        return segments, [], None

    api = project.get("api_config") or {}
    reviews: dict[str, dict[str, Any]] = {}
    try:
        total_batches = max(1, (len(segments) + batch_size - 1) // batch_size)
        for start in range(0, len(segments), batch_size):
            batch = segments[start : start + batch_size]
            batch_index = start // batch_size + 1
            percent = min(64, 58 + int((batch_index - 1) / total_batches * 5))
            emit_progress(
                "generate",
                "phrase_review",
                percent,
                f"AI 正在评审学习候选：第 {batch_index}/{total_batches} 批，thinking 已保留。",
            )
            prompt = build_phrase_review_prompt(project, batch)
            if is_gemini_vertex_config(api):
                content = gemini_vertex_generate_content(
                    api,
                    prompt,
                    temperature=0.1,
                    timeout=180 if is_gemini_vertex_thinking_config(api) else 120,
                    max_output_tokens=9000 if is_gemini_vertex_thinking_config(api) else 4500,
                )
            else:
                response = compatible_chat_completion(
                    api,
                    [
                        {"role": "system", "content": "Return only valid JSON."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.1,
                    timeout=180 if is_thinking_model_config(api) else 120,
                    max_tokens=4500 if is_deepseek_thinking_config(api) else 3200,
                    progress={
                        "command": "generate",
                        "stage": "phrase_review",
                        "percent": percent,
                        "message": "AI 保留 thinking 评审学习候选",
                    },
                    work_unit_id=f"phrase-review:{batch_index}",
                )
                content = chat_completion_content(response)
            payload = extract_json_object(content or "")
            for item in payload.get("candidates", []):
                if isinstance(item, dict) and item.get("id"):
                    reviews[str(item["id"])] = item
    except Exception as err:
        return segments, [], f"AI 学习候选评审失败，已回退到原有候选流程：{err}"

    if not reviews:
        return segments, [], "AI 学习候选评审没有返回可用 JSON，已回退到原有候选流程。"

    kept, skipped = apply_phrase_review_decisions(segments, reviews, project)
    rejected_ids = {str(item.get("id")) for item in skipped if str(item.get("phrase_review_status") or "") == "reject"}
    kept, skipped = ensure_min_review_candidates(segments, kept, skipped, project, rejected_ids)
    kept, source_overflow = enforce_max_learning_points_per_source(kept, max_learning_points_per_source(project))
    kept, duplicates = split_duplicate_phrase_segments(kept)
    max_segments = resolved_max_segments(project) * selection_candidate_multiplier(project)
    kept, overflow = limit_reviewed_segments(kept, max_segments)
    skipped = [*skipped, *source_overflow, *duplicates, *overflow]
    return kept, sorted(skipped, key=lambda item: item["start"]), None


def api_test_prompt() -> str:
    return (
        "Return only valid JSON for an Anki card generation capability test. "
        "Use exactly this structure and no Markdown: "
        '{"segments":[{"id":"seg_test","cards":[{"type":"phrase","phrase":"in the mood",'
        '"chinese":"有心情","definition":"willing or wanting to do something",'
        '"collocations":"in the mood for; not in the mood to","context":"spoken reply",'
        '"example":"I am not in the mood to go out.","chinese_feel":"没那个心情",'
        '"why":"高频口语表达","difficulty":"B1 日常交流","teacher_note":"真实口语常用",'
        '"cloze":"I am not really ____ right now."}]}]}'
    )


def validate_api_test_payload(text: str) -> tuple[bool, str]:
    payload = extract_json_object(text)
    segments = payload.get("segments")
    if not isinstance(segments, list) or not segments:
        return False, "JSON 缺少 segments。"
    cards = segments[0].get("cards") if isinstance(segments[0], dict) else None
    if not isinstance(cards, list) or not cards:
        return False, "JSON 缺少 cards。"
    card = cards[0]
    required = ["type", "phrase", "chinese", "definition", "cloze"]
    missing = [key for key in required if not card.get(key)]
    if missing:
        return False, f"JSON 缺少字段：{', '.join(missing)}。"
    if str(card.get("cloze", "")).count("____") != 1:
        return False, "cloze 必须有且只有一个 ____。"
    return True, f"结构化 JSON 测试通过：{card.get('phrase')}"


def handle_test_api(payload: dict[str, Any]) -> dict[str, Any]:
    api = dict(payload.get("api_config") or {})
    provider = api.get("provider", "local")
    model = api.get("model", "").strip()
    api_key = api.get("api_key", "").strip()
    started = time.time()

    if is_gemini_vertex_config(api):
        api["model"] = normalize_gemini_vertex_model(model)
        model = str(api["model"])

    if provider == "local":
        return {
            "ok": True,
            "provider": provider,
            "model": model or "local-fallback",
            "message": "预览模式可用，不需要 API Key；正式抽取学习点和制卡仍需配置模型 API。",
            "latency_ms": 0,
        }

    if not model:
        return {
            "ok": False,
            "provider": provider,
            "model": model,
            "message": "缺少模型名。",
            "error_code": worker_errors.MODEL_NOT_FOUND,
            "stage": "model_api",
            "retryable": False,
        }
    if managed_model_broker_is_configured() and not model_api_available(api):
        return {
            "ok": False,
            "provider": provider,
            "model": model,
            "message": "当前任务没有获得这个模型 Provider 的 Service broker 授权。",
            "error_code": worker_errors.MODEL_AUTH_FAILED,
            "stage": "model_api",
            "retryable": False,
        }
    if not managed_model_broker_is_configured() and not api_key and not is_gemini_vertex_config(api):
        return {
            "ok": False,
            "provider": provider,
            "model": model,
            "message": "缺少 API Key。",
            "error_code": worker_errors.MODEL_AUTH_FAILED,
            "stage": "model_api",
            "retryable": False,
        }

    prompt = api_test_prompt()
    try:
        if provider in OPENAI_COMPATIBLE_PROVIDERS:
            response = compatible_chat_completion(
                api,
                [
                    {"role": "system", "content": "Return only valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0,
                timeout=90 if is_thinking_model_config(api) else 30,
                max_tokens=2000 if (is_mimo_config(api) or is_deepseek_thinking_config(api)) else 800,
                work_unit_id="api-test",
            )
            content = chat_completion_content(response)
            if content is None:
                content = ""

        elif provider == "claude":
            response = model_anthropic_messages(
                api,
                {
                    "model": model,
                    "max_tokens": 800,
                    "temperature": 0,
                    "system": "Return only valid JSON.",
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=30,
                work_unit_id="api-test",
            )
            content = "".join(part.get("text", "") for part in response.get("content", []))

        elif provider == "gemini":
            response = model_gemini_content(
                api,
                {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0,
                        "maxOutputTokens": 800,
                        "responseMimeType": "application/json",
                    },
                },
                timeout=30,
                work_unit_id="api-test",
            )
            content = response.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")

        elif is_gemini_vertex_config(api):
            content = gemini_vertex_generate_content(
                api,
                prompt,
                temperature=0,
                timeout=120 if is_gemini_vertex_thinking_config(api) else 45,
                max_output_tokens=2500 if is_gemini_vertex_thinking_config(api) else 1000,
            )

        else:
            return {
                "ok": False,
                "provider": provider,
                "model": model,
                "message": f"暂不支持测试这个 Provider：{provider}",
            }

        latency_ms = int((time.time() - started) * 1000)
        ok, message = validate_api_test_payload(str(content))
        return {
            "ok": ok,
            "provider": provider,
            "model": model,
            "message": message,
            "latency_ms": latency_ms,
        }
    except Exception as err:
        details = classify_service_error(err, kind="model")
        return {
            "ok": False,
            "provider": provider,
            "model": model,
            **details,
            "latency_ms": int((time.time() - started) * 1000),
        }


def normalized_tts_config(project_or_payload: dict[str, Any]) -> dict[str, Any]:
    api = project_or_payload.get("api_config") or project_or_payload
    tts = api.get("tts_config") or project_or_payload.get("tts_config") or {}
    legacy_provider = api.get("tts_provider", "")
    legacy_model = api.get("tts_model", "")
    provider = str(tts.get("provider") or legacy_provider or "disabled").strip().lower()
    base_url = str(tts.get("base_url") or "").strip()
    api_base_url = str(api.get("base_url") or "").strip()
    api_key = str(tts.get("api_key") or "").strip()
    main_api_key = str(api.get("api_key") or "").strip()
    main_is_mimo = provider_name(api) in MIMO_PROVIDERS or "xiaomimimo.com" in api_base_url.lower()
    main_is_qwen = provider_name(api) == "openai-compatible" and (
        "dashscope" in api_base_url.lower() or "qwencloud" in api_base_url.lower()
    )

    if provider in MIMO_PROVIDERS:
        stale_token_plan_key = (
            api_key.lower().startswith("tp-")
            and main_api_key.lower().startswith("tp-")
            and api_key != main_api_key
            and main_is_mimo
        )
        if (not api_key or stale_token_plan_key) and main_is_mimo:
            api_key = main_api_key
        if not base_url and main_is_mimo:
            base_url = api_base_url
        if not base_url:
            base_url = MIMO_TOKEN_PLAN_SGP_BASE_URL if api_key.lower().startswith("tp-") else MIMO_OPENAI_BASE_URL
        if api_key.lower().startswith("tp-") and "token-plan-" not in base_url.lower():
            base_url = MIMO_TOKEN_PLAN_SGP_BASE_URL

    if provider in QWEN_TTS_PROVIDERS:
        if not api_key and main_is_qwen:
            api_key = main_api_key
        if not base_url:
            base_url = QWEN_DASHSCOPE_CN_TTS_BASE_URL

    if provider in GEMINI_VERTEX_TTS_PROVIDERS and not base_url:
        base_url = GEMINI_VERTEX_TTS_GLOBAL_BASE_URL

    return {
        "enabled": bool(tts.get("enabled", False)),
        "provider": provider,
        "base_url": base_url,
        "api_key": api_key,
        "model": str(
            tts.get("model") or (GEMINI_VERTEX_TTS_DEFAULT_MODEL if provider in GEMINI_VERTEX_TTS_PROVIDERS else "")
        ).strip(),
        "voice": str(
            tts.get("voice") or legacy_model or (GEMINI_VERTEX_TTS_DEFAULT_VOICE if provider in GEMINI_VERTEX_TTS_PROVIDERS else "")
        ).strip(),
        "language": str(tts.get("language") or "auto").strip()
        or "auto",
        "sample_rate": int(tts.get("sample_rate") or 24000),
        "bit_rate": int(tts.get("bit_rate") or 128000),
        "output_volume": normalized_tts_output_volume(tts.get("output_volume")),
    }


def normalized_tts_output_volume(value: Any) -> float:
    try:
        volume = float(value)
    except (TypeError, ValueError):
        return 0.65
    if not math.isfinite(volume):
        return 0.65
    return min(1.0, max(0.4, volume))


def grok_tts_endpoint(base_url: str) -> str:
    return f"{(base_url or 'https://api.x.ai/v1').rstrip('/')}/tts"


def openai_speech_endpoint(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/audio/speech"


def qwen_tts_endpoint(base_url: str) -> str:
    base = (base_url or QWEN_DASHSCOPE_CN_TTS_BASE_URL).rstrip("/")
    if base.endswith("/services/aigc/multimodal-generation/generation"):
        return base
    return f"{base}/services/aigc/multimodal-generation/generation"


def gemini_vertex_tts_location(config: dict[str, Any]) -> str:
    explicit = str(config.get("location") or config.get("region") or "").strip()
    if explicit:
        return explicit
    base_url = str(config.get("base_url") or "").strip().rstrip("/")
    if base_url:
        try:
            host = urllib.parse.urlparse(base_url).hostname or ""
        except ValueError:
            host = ""
        if host == "aiplatform.googleapis.com":
            return "global"
        suffix = "-aiplatform.googleapis.com"
        if host.endswith(suffix):
            return host[: -len(suffix)]
    return "global"


def gemini_vertex_tts_base_url(config: dict[str, Any], location: str) -> str:
    base_url = str(config.get("base_url") or "").strip().rstrip("/")
    if base_url:
        return base_url
    return GEMINI_VERTEX_TTS_GLOBAL_BASE_URL if location == "global" else f"https://{location}-aiplatform.googleapis.com"


def gemini_vertex_tts_endpoint(config: dict[str, Any]) -> str:
    model = str(config.get("model") or GEMINI_VERTEX_TTS_DEFAULT_MODEL).strip()
    project = gemini_vertex_project(config)
    location = gemini_vertex_tts_location(config)
    base_url = gemini_vertex_tts_base_url(config, location)
    return (
        f"{base_url}/v1beta1/projects/{urllib.parse.quote(project, safe='')}"
        f"/locations/{urllib.parse.quote(location, safe='')}/publishers/google/models/"
        f"{urllib.parse.quote(model, safe='')}:generateContent"
    )


def wav_from_pcm_s16le(pcm: bytes, sample_rate: int = 24000, channels: int = 1) -> bytes:
    sample_width = 2
    data_size = len(pcm)
    byte_rate = sample_rate * channels * sample_width
    block_align = channels * sample_width
    return b"".join(
        [
            b"RIFF",
            (36 + data_size).to_bytes(4, "little"),
            b"WAVE",
            b"fmt ",
            (16).to_bytes(4, "little"),
            (1).to_bytes(2, "little"),
            channels.to_bytes(2, "little"),
            sample_rate.to_bytes(4, "little"),
            byte_rate.to_bytes(4, "little"),
            block_align.to_bytes(2, "little"),
            (sample_width * 8).to_bytes(2, "little"),
            b"data",
            data_size.to_bytes(4, "little"),
            pcm,
        ]
    )


def qwen_language_type(language: str) -> str:
    lower = str(language or "").strip().lower()
    if lower in {"auto", ""}:
        return "Auto"
    if lower.startswith("zh") or "中文" in lower or "chinese" in lower:
        return "Chinese"
    if lower.startswith("en") or "english" in lower:
        return "English"
    if lower.startswith("ja") or "japanese" in lower or "日本" in lower:
        return "Japanese"
    if lower.startswith("ko") or "korean" in lower:
        return "Korean"
    if lower.startswith("fr") or "french" in lower:
        return "French"
    if lower.startswith("de") or "german" in lower:
        return "German"
    if lower.startswith("es") or "spanish" in lower:
        return "Spanish"
    if lower.startswith("pt") or "portuguese" in lower:
        return "Portuguese"
    if lower.startswith("it") or "italian" in lower:
        return "Italian"
    if lower.startswith("ru") or "russian" in lower:
        return "Russian"
    return "Auto"


def normalize_bcp47_language_code(value: Any) -> str:
    lower = str(value or "").strip().lower()
    if not lower:
        return ""
    if re.fullmatch(r"[a-z]{2,3}-[a-z0-9]{2,4}", lower):
        left, right = lower.split("-", 1)
        return f"{left}-{right.upper()}"
    code = normalize_learning_language(lower)
    return TTS_LANGUAGE_FALLBACKS[code][0]


def resolve_tts_language_code(tts: dict[str, Any], language: Any) -> str:
    explicit = str(tts.get("language") or "").strip()
    if explicit and explicit.lower() != "auto":
        return normalize_bcp47_language_code(explicit)
    code = normalize_learning_language(language)
    return TTS_LANGUAGE_FALLBACKS[code][0]


def gemini_vertex_tts_language_code(language: str) -> str:
    lower = str(language or "").strip().lower()
    if lower in {"", "auto"}:
        return "en-US"
    if lower in {"en", "english", "english (united states)", "us english", "american english"}:
        return "en-US"
    if lower in {"zh", "chinese", "mandarin", "中文", "普通话"}:
        return "cmn-CN"
    if re.fullmatch(r"[a-z]{2,3}-[a-z0-9]{2,4}", lower):
        left, right = lower.split("-", 1)
        return f"{left}-{right.upper()}"
    return language


def gemini_vertex_tts_request_body(tts: dict[str, Any], speech_text: str, resolved_language: str) -> dict[str, Any]:
    # Vertex Gemini TTS rejects systemInstruction when responseModalities is AUDIO.
    # Keep the exact-read instruction in contents and rely on strict hash/duration checks after synthesis.
    return {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": exact_tts_prompt(speech_text)}],
            }
        ],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "languageCode": gemini_vertex_tts_language_code(resolved_language),
                "voiceConfig": {
                    "prebuiltVoiceConfig": {
                        "voiceName": str(tts.get("voice") or GEMINI_VERTEX_TTS_DEFAULT_VOICE).strip(),
                    }
                },
            },
        },
    }


def gemini_vertex_tts_inline_audio(response: dict[str, Any]) -> bytes | None:
    for candidate in response.get("candidates", []) or []:
        content = candidate.get("content") or {}
        for part in content.get("parts", []) or []:
            inline = part.get("inlineData") or part.get("inline_data") or {}
            data = inline.get("data")
            if data:
                return base64.b64decode(data)
    return None


def gemini_vertex_tts_response_diagnostic(response: dict[str, Any]) -> str:
    details: list[str] = []
    for candidate in response.get("candidates", []) or []:
        finish = candidate.get("finishReason") or candidate.get("finish_reason")
        if finish:
            details.append(f"finishReason={finish}")
        content = candidate.get("content") or {}
        texts = [
            str(part.get("text") or "").strip()
            for part in content.get("parts", []) or []
            if str(part.get("text") or "").strip()
        ]
        if texts:
            details.append(f"text={texts[0][:120]}")
        safety = candidate.get("safetyRatings") or candidate.get("safety_ratings") or []
        if safety:
            ratings = []
            for rating in safety[:3]:
                category = rating.get("category")
                probability = rating.get("probability")
                if category or probability:
                    ratings.append(f"{category}:{probability}")
            if ratings:
                details.append(f"safety={','.join(ratings)}")
    return "; ".join(details) or "no candidates/parts"


def mimo_tts_audio(tts: dict[str, Any], text: str, language: str) -> bytes:
    model = tts["model"] or "mimo-v2.5-tts"
    voice = (tts.get("voice") or "").strip()
    model_lower = model.lower()

    if "voicedesign" in model_lower:
        user_content = voice or "A clear, natural voice for language-learning flashcards."
        audio: dict[str, str] = {"format": "wav"}
    elif "voiceclone" in model_lower:
        user_content = ""
        audio = {"format": "wav"}
        if voice:
            audio["voice"] = voice
    else:
        user_content = (
            f"Read the assistant message aloud exactly for a {language or 'en'} language-learning Anki card. "
            "Do not explain, translate, expand, add words, or add a preface."
        )
        audio = {
            "format": "wav",
            "voice": voice or "mimo_default",
        }

    response = http_json(
        f"{compatible_base_url(tts)}/chat/completions",
        api_key_header(tts),
        {
            "model": model,
            "messages": [
                {"role": "user", "content": user_content},
                {"role": "assistant", "content": text},
            ],
            "audio": audio,
            "stream": False,
        },
        timeout=120,
    )
    message = response.get("choices", [{}])[0].get("message", {})
    data = (message.get("audio") or {}).get("data")
    if not data:
        raise RuntimeError("MIMO TTS 没有返回 audio.data。请检查模型、voice 和套餐权限。")
    return base64.b64decode(data)


def qwen_tts_audio(tts: dict[str, Any], text: str, language: str) -> bytes:
    model = tts["model"] or QWEN_TTS_DEFAULT_MODEL
    resolved_language = resolve_tts_language_code(tts, language)
    body = {
        "model": model,
        "input": {
            "text": text,
            "voice": tts.get("voice") or QWEN_TTS_DEFAULT_VOICE,
            "language_type": qwen_language_type(resolved_language),
        },
    }
    model_lower = model.lower()
    if "instruct" in model_lower:
        body["input"]["instructions"] = (
            "Read the input text aloud exactly for a language-learning Anki card. "
            "Do not explain, translate, expand, add words, or add a preface. "
            "Use steady pacing and accurate pronunciation."
        )
        body["input"]["optimize_instructions"] = True
    response = http_json(
        qwen_tts_endpoint(tts.get("base_url") or QWEN_DASHSCOPE_CN_TTS_BASE_URL),
        {"Authorization": f"Bearer {tts['api_key']}"},
        body,
        timeout=120,
    )
    audio = ((response.get("output") or {}).get("audio") or {})
    data = audio.get("data")
    if data:
        return base64.b64decode(data)
    url = audio.get("url")
    if url:
        return http_get_binary(str(url), timeout=120)
    raise RuntimeError("Qwen TTS 没有返回 output.audio.url 或 output.audio.data。请检查模型、voice、地域和 API Key。")


def gemini_vertex_tts_audio(tts: dict[str, Any], text: str, language: str) -> bytes:
    model = str(tts.get("model") or GEMINI_VERTEX_TTS_DEFAULT_MODEL).strip()
    if not model:
        raise RuntimeError("Gemini Vertex TTS 需要模型名。")
    project = gemini_vertex_project(tts)
    token = gcloud_value(["auth", "print-access-token"])
    resolved_language = resolve_tts_language_code(tts, language)
    endpoint = gemini_vertex_tts_endpoint({**tts, "model": model, "project": project})
    headers = {"Authorization": f"Bearer {token}", "x-goog-user-project": project}
    last_error: Exception | None = None
    last_diagnostic = ""

    for speech_text in gemini_vertex_tts_text_variants(text):
        try:
            response = http_json(
                endpoint,
                headers,
                gemini_vertex_tts_request_body(tts, speech_text, resolved_language),
                timeout=120,
            )
        except Exception as exc:
            last_error = exc
            continue

        pcm = gemini_vertex_tts_inline_audio(response)
        if pcm:
            return wav_from_pcm_s16le(pcm, sample_rate=int(tts.get("sample_rate") or 24000))
        last_diagnostic = gemini_vertex_tts_response_diagnostic(response)

    if last_error:
        raise RuntimeError(f"Gemini Vertex TTS 请求失败：{last_error}") from last_error
    detail = f"（{last_diagnostic}）" if last_diagnostic else ""
    raise RuntimeError(f"Gemini Vertex TTS 没有返回 inlineData 音频{detail}。请检查 Vertex AI 权限、模型、区域和 voice。")


def call_tts_audio(
    tts: dict[str, Any],
    text: str,
    language: str,
    *,
    work_unit_base: str = "tts",
) -> bytes:
    provider = tts["provider"]
    api_key = tts["api_key"]
    text = clean_tts_input_text(text)
    resolved_language = resolve_tts_language_code(tts, language)
    if managed_tts_broker_is_configured():
        return managed_tts_request(
            text,
            language=resolved_language,
            sample_rate=int(tts.get("sample_rate") or 24000),
            bit_rate=int(tts.get("bit_rate") or 128000),
            work_unit_base=work_unit_base,
        ).data
    if provider in {"grok", "xai"}:
        return http_binary(
            grok_tts_endpoint(tts["base_url"]),
            {"Authorization": f"Bearer {api_key}"},
            {
                "text": text,
                "voice_id": tts["voice"] or "eve",
                "language": resolved_language,
                "output_format": {
                    "codec": "mp3",
                    "sample_rate": tts["sample_rate"],
                    "bit_rate": tts["bit_rate"],
                },
            },
        )

    if is_mimo_config(tts):
        return mimo_tts_audio(tts, text, resolved_language)

    if provider in QWEN_TTS_PROVIDERS:
        return qwen_tts_audio({**tts, "language": resolved_language}, text, resolved_language)

    if is_gemini_vertex_tts_config(tts):
        return gemini_vertex_tts_audio({**tts, "language": resolved_language}, text, resolved_language)

    if provider in OPENAI_COMPATIBLE_PROVIDERS:
        return http_binary(
            openai_speech_endpoint(compatible_base_url(tts)),
            api_key_header(tts),
            {
                "model": tts["model"],
                "input": text,
                "voice": tts["voice"] or "alloy",
                "response_format": "mp3",
            },
        )

    raise RuntimeError(f"不支持这个 TTS Provider：{provider}")


def handle_test_tts(payload: dict[str, Any]) -> dict[str, Any]:
    tts = normalized_tts_config(payload)
    language = normalize_learning_language(payload.get("language") or "en")
    started = time.time()
    brokered = managed_tts_broker_is_configured()

    if not tts["enabled"] or tts["provider"] == "disabled":
        return {
            "ok": False,
            "provider": tts["provider"],
            "model": tts["model"],
            "voice": tts["voice"],
            "message": "TTS 当前是关闭状态。",
            "error_code": worker_errors.TTS_NOT_FOUND,
            "stage": "tts",
            "retryable": False,
        }
    if brokered and not managed_tts_operation_available():
        return {
            "ok": False,
            "provider": tts["provider"],
            "model": tts["model"],
            "voice": tts["voice"],
            "message": "当前任务没有获得 TTS Service broker 授权。",
            "error_code": worker_errors.TTS_AUTH_FAILED,
            "stage": "tts",
            "retryable": False,
        }
    if not brokered and not tts["api_key"] and not is_gemini_vertex_tts_config(tts):
        return {
            "ok": False,
            "provider": tts["provider"],
            "model": tts["model"],
            "voice": tts["voice"],
            "message": "缺少 TTS API Key。",
            "error_code": worker_errors.TTS_AUTH_FAILED,
            "stage": "tts",
            "retryable": False,
        }

    try:
        text = "This is a TTS test for your Anki cards."
        if brokered:
            resolved_language = resolve_tts_language_code(tts, language)
            audio = managed_tts_request(
                clean_tts_input_text(text),
                language=resolved_language,
                sample_rate=int(tts.get("sample_rate") or 24000),
                bit_rate=int(tts.get("bit_rate") or 128000),
                work_unit_base="tts-test",
            )
            audio_size = len(audio.data)
        elif tts["provider"] == "gemini":
            if not tts["model"]:
                return {
                    "ok": False,
                    "provider": tts["provider"],
                    "model": tts["model"],
                    "voice": tts["voice"],
                    "message": "Gemini TTS 需要模型名。",
                    "error_code": worker_errors.TTS_NOT_FOUND,
                    "stage": "tts",
                    "retryable": False,
                }
            response = http_json(
                f"https://generativelanguage.googleapis.com/v1beta/models/{tts['model']}:generateContent",
                {"x-goog-api-key": tts["api_key"]},
                {
                    "contents": [{"parts": [{"text": exact_tts_prompt(text)}]}],
                    "generationConfig": {
                        "responseModalities": ["AUDIO"],
                        "speechConfig": {
                            "voiceConfig": {
                                "prebuiltVoiceConfig": {
                                    "voiceName": tts["voice"] or "Kore",
                                }
                            }
                        },
                    },
                    "model": tts["model"],
                },
                timeout=45,
            )
            data = response["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
            audio_size = len(base64.b64decode(data))
        else:
            if is_gemini_vertex_tts_config(tts) and not tts["model"]:
                return {
                    "ok": False,
                    "provider": tts["provider"],
                    "model": tts["model"],
                    "voice": tts["voice"],
                    "message": "Gemini Vertex TTS 需要模型名。",
                    "error_code": worker_errors.TTS_NOT_FOUND,
                    "stage": "tts",
                    "retryable": False,
                }
            if tts["provider"] in OPENAI_COMPATIBLE_PROVIDERS and (not compatible_base_url(tts) or not tts["model"]):
                return {
                    "ok": False,
                    "provider": tts["provider"],
                    "model": tts["model"],
                    "voice": tts["voice"],
                    "message": "MIMO / OpenAI-compatible Speech 需要 Base URL 和模型名。",
                    "error_code": worker_errors.TTS_NOT_FOUND,
                    "stage": "tts",
                    "retryable": False,
                }
            audio_size = len(call_tts_audio(tts, text, language))

        return {
            "ok": True,
            "provider": tts["provider"],
            "model": tts["model"],
            "voice": tts["voice"],
            "message": f"测试音频生成成功，大小 {audio_size} bytes。",
            "latency_ms": int((time.time() - started) * 1000),
            "bytes": audio_size,
        }
    except Exception as err:
        details = classify_service_error(err, kind="tts")
        message = details["message"]
        if (
            is_mimo_config(tts)
            and tts["api_key"].lower().startswith("tp-")
            and "api.xiaomimimo.com" in compatible_base_url(tts).lower()
        ):
            message = (
                "你的 TTS Key 是 tp- 开头的 Token Plan Key，不能配公共 "
                "https://api.xiaomimimo.com/v1。请把 TTS Base URL 改成 "
                "https://token-plan-sgp.xiaomimimo.com/v1，或直接点 MIMO SGP TTS 预设。"
            )
        return {
            "ok": False,
            "provider": tts["provider"],
            "model": tts["model"],
            "voice": tts["voice"],
            **details,
            "message": message,
            "latency_ms": int((time.time() - started) * 1000),
        }


def merge_ai_cards(
    segments: list[dict[str, Any]],
    ai_payload: dict[str, Any] | None,
    card_types: list[str],
    level: str,
    language: str = "English",
) -> tuple[list[dict[str, Any]], str | None]:
    ai_by_segment: dict[str, dict[str, Any]] = {}
    warning = None
    if ai_payload:
        if "error" in ai_payload:
            warning = f"部分模型精修失败，未精修片段会保留为停用的预览草稿：{ai_payload['error']}"
        for item in ai_payload.get("segments", []):
            ai_by_segment[item.get("id", "")] = item

    for segment in segments:
        ai_segment = ai_by_segment.get(segment["id"])
        fallback = fallback_cards(segment, card_types, level)
        cards = fallback
        if ai_payload is None:
            warning = warning or "模型没有返回可用精修结果，预览草稿已默认停用，请人工检查后再导出。"
        if ai_segment:
            usable_ai_cards = [
                card
                for card in ai_segment.get("cards", [])
                if card.get("phrase") or card.get("chinese") or card.get("definition")
            ]
            ai_template_card = usable_ai_cards[0] if usable_ai_cards else None
            by_learning_point_type: dict[tuple[str, str], list[dict[str, Any]]] = {}
            by_span_kind_type: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
            by_type: dict[str, list[dict[str, Any]]] = {}
            consumed_ai_cards: set[int] = set()
            for ai_card in usable_ai_cards:
                card_type = str(ai_card.get("type") or "")
                learning_point_id = str(ai_card.get("learning_point_id") or "")
                exact_span = normalized_phrase_key(str(ai_card.get("exact_span") or ai_card.get("phrase") or ""))
                candidate_kind = str(ai_card.get("candidate_kind") or "")
                if learning_point_id and card_type:
                    by_learning_point_type.setdefault((learning_point_id, card_type), []).append(ai_card)
                if exact_span and card_type:
                    by_span_kind_type.setdefault((exact_span, candidate_kind, card_type), []).append(ai_card)
                    by_span_kind_type.setdefault((exact_span, "", card_type), []).append(ai_card)
                if card_type:
                    by_type.setdefault(card_type, []).append(ai_card)

            def pop_first(items: list[dict[str, Any]] | None) -> dict[str, Any] | None:
                while items:
                    item = items.pop(0)
                    item_id = id(item)
                    if item_id in consumed_ai_cards:
                        continue
                    consumed_ai_cards.add(item_id)
                    return item
                return None

            def match_ai_card(fallback_card: dict[str, Any]) -> dict[str, Any] | None:
                card_type = str(fallback_card.get("type") or "")
                learning_point_id = str(fallback_card.get("learning_point_id") or "")
                exact_span = normalized_phrase_key(str(fallback_card.get("exact_span") or fallback_card.get("phrase") or ""))
                candidate_kind = str(fallback_card.get("candidate_kind") or "")
                return (
                    pop_first(by_learning_point_type.get((learning_point_id, card_type)))
                    or pop_first(by_span_kind_type.get((exact_span, candidate_kind, card_type)))
                    or pop_first(by_span_kind_type.get((exact_span, "", card_type)))
                    or pop_first(by_type.get(card_type))
                    or (
                        ai_template_card
                        if ai_template_card is not None and id(ai_template_card) not in consumed_ai_cards
                        else None
                    )
                )

            cards = []
            for card in fallback:
                ai_card = match_ai_card(card)
                if not ai_card:
                    cards.append(card)
                    continue
                consumed_ai_cards.add(id(ai_card))
                for key in [
                    "chinese",
                    "phrase",
                    "definition",
                    "collocations",
                    "context",
                    "example",
                    "chinese_feel",
                    "why",
                    "difficulty",
                    "teacher_note",
                    "cloze",
                    "card_role",
                    "learning_goal",
                    "decision_reason",
                    "learning_target",
                    "learning_action",
                    "conceptual_action",
                    "chinese_learner_trap",
                    "why_it_matters",
                    "how_to_use_it",
                    "natural_chinese",
                    "replacement_examples",
                    "avoid_reason",
                    "phrase_value_score",
                    "phrase_decision_reason",
                    "phrase_reject_reason",
                    "phrase_card_focus",
                    "phrase_review_status",
                    "phrase_type",
                    "learning_point_id",
                    "content_kind",
                    "candidate_kind",
                    "exact_span",
                    "normalized_answer",
                    "candidate_source",
                    "learning_point_schema_version",
                    "source_evidence",
                    "retrieval_prompt",
                    "answer_core",
                    "usage_boundary",
                    "confusable_note",
                    "phonetic_ipa",
                    "spoken_ipa",
                    "source_spoken_ipa",
                    "pronunciation_note",
                    "pronunciation_confidence",
                    "pronunciation_status",
                    "source_pronunciation_status",
                ]:
                    if ai_card.get(key):
                        card[key] = str(ai_card[key])
                if ai_card.get("pronunciation_meta"):
                    card["pronunciation_meta"] = ai_card.get("pronunciation_meta")
                if card["type"] == "phrase":
                    phrase_type = str(card.get("phrase_type") or segment.get("phrase_type") or "")
                    if phrase_type:
                        card["phrase_type"] = phrase_type
                        card["content_kind"] = card.get("content_kind") or content_kind_for_phrase_type(phrase_type)
                    card["type_label"] = card_label_for_learning_card(
                        str(card.get("phrase_type") or ""),
                        str(card.get("content_kind") or ""),
                        card.get("type_label", "学习卡"),
                    )
                if ai_card is ai_template_card and not str(ai_card.get("learning_point_id") or ""):
                    card["teacher_note"] = (
                        card.get("teacher_note")
                        or "同片段 AI 已识别出重点表达，这张卡由系统补齐为对应训练任务。"
                    )
                normalize_learning_action_fields(card)
                repair_card_fields(card, segment, level)
                sanitize_pronunciation_fields(card, language)
                for key in [
                    "phrase_value_score",
                    "phrase_decision_reason",
                    "phrase_reject_reason",
                    "phrase_card_focus",
                    "phrase_review_status",
                    "phrase_type",
                    "learning_point_id",
                    "content_kind",
                    "candidate_kind",
                    "exact_span",
                    "normalized_answer",
                    "candidate_source",
                    "learning_point_schema_version",
                    "source_evidence",
                    "learning_action",
                    "conceptual_action",
                    "chinese_learner_trap",
                ]:
                    if card.get(key) in (None, "") and segment.get(key) not in (None, ""):
                        card[key] = segment.get(key)
                if card["type"] == "phrase":
                    phrase_type = str(card.get("phrase_type") or "")
                    if phrase_type:
                        card["content_kind"] = card.get("content_kind") or content_kind_for_phrase_type(phrase_type)
                    card["type_label"] = card_label_for_learning_card(
                        str(card.get("phrase_type") or ""),
                        str(card.get("content_kind") or ""),
                        card.get("type_label", "学习卡"),
                    )
                card["quality"] = assess_card_quality(card, segment, "ai", level)
                card["enabled"] = card["quality"]["status"] == "recommended"
                cards.append(card)
            requested_for_extra = set(requested_card_types(card_types))
            for extra_index, ai_card in enumerate(usable_ai_cards, start=1):
                if id(ai_card) in consumed_ai_cards:
                    continue
                card_type = str(ai_card.get("type") or "")
                if card_type not in requested_for_extra:
                    continue
                if not str(ai_card.get("definition") or "").strip():
                    continue
                if card_type == "cloze" and "____" not in str(ai_card.get("cloze") or ""):
                    continue
                if card_type == "listening" and not str(ai_card.get("teacher_note") or ai_card.get("learning_target") or "").strip():
                    continue
                card = dict(fallback[0]) if fallback else {}
                card.update(
                    {
                        "id": f"{segment['id']}_ai_extra_{extra_index}_{card_type}",
                        "type": card_type,
                        "type_label": CARD_TYPE_LABELS.get(card_type, card_type),
                        "enabled": False,
                        "english": segment.get("text", ""),
                        "card_role": str(ai_card.get("card_role") or "specialist"),
                    }
                )
                for key in [
                    "chinese",
                    "phrase",
                    "definition",
                    "collocations",
                    "context",
                    "example",
                    "chinese_feel",
                    "why",
                    "difficulty",
                    "estimated_level",
                    "difficulty_reason",
                    "teacher_note",
                    "cloze",
                    "learning_goal",
                    "decision_reason",
                    "learning_target",
                    "why_it_matters",
                    "how_to_use_it",
                    "natural_chinese",
                    "replacement_examples",
                    "avoid_reason",
                    "phrase_value_score",
                    "phrase_decision_reason",
                    "phrase_reject_reason",
                    "phrase_card_focus",
                    "phrase_review_status",
                    "phrase_type",
                    "learning_point_id",
                    "content_kind",
                    "candidate_kind",
                    "exact_span",
                    "normalized_answer",
                    "candidate_source",
                    "learning_point_schema_version",
                    "source_evidence",
                    "retrieval_prompt",
                    "answer_core",
                    "usage_boundary",
                    "confusable_note",
                    "phonetic_ipa",
                    "spoken_ipa",
                    "source_spoken_ipa",
                    "pronunciation_note",
                    "pronunciation_confidence",
                    "pronunciation_status",
                    "source_pronunciation_status",
                ]:
                    if ai_card.get(key):
                        card[key] = str(ai_card[key])
                own_phrase = clean_study_text(
                    ai_card.get("phrase")
                    or ai_card.get("exact_span")
                    or ai_card.get("normalized_answer")
                    or ai_card.get("answer_core")
                )
                own_answer = clean_study_text(ai_card.get("answer_core") or own_phrase)
                if own_phrase:
                    card["phrase"] = own_phrase
                    card["exact_span"] = clean_study_text(ai_card.get("exact_span") or own_phrase)
                    card["normalized_answer"] = clean_study_text(
                        ai_card.get("normalized_answer") or own_answer or own_phrase
                    )
                if own_answer:
                    card["answer_core"] = own_answer
                if ai_card.get("pronunciation_meta"):
                    card["pronunciation_meta"] = ai_card.get("pronunciation_meta")
                normalize_learning_action_fields(card)
                repair_card_fields(card, segment, level)
                sanitize_pronunciation_fields(card, language)
                if card["type"] == "phrase":
                    card["type_label"] = card_label_for_learning_card(
                        str(card.get("phrase_type") or ""),
                        str(card.get("content_kind") or ""),
                        card.get("type_label", "学习卡"),
                    )
                card["quality"] = assess_card_quality(card, segment, "ai", level)
                card["enabled"] = card["quality"]["status"] == "recommended"
                cards.append(card)
            if not cards and fallback:
                cards = [fallback[0]]
        segment["cards"] = cards
    return segments, warning


def card_quality_status(card: dict[str, Any]) -> str:
    return inventory_card_quality_status(card)


LEARNING_POINT_INVENTORY_STATUSES = inventory_learning_point_inventory_statuses


def inventory_status_for_filtered_item(item: dict[str, Any], reason: str = "") -> str:
    return inventory_inventory_status_for_filtered_item(item, reason)


def inventory_status_for_rejected_card(card: dict[str, Any], segment: dict[str, Any]) -> str:
    return inventory_inventory_status_for_rejected_card(card, segment)


def inventory_learning_action(item: dict[str, Any], card: dict[str, Any] | None = None) -> str:
    return inventory_inventory_learning_action(item, card)


def learning_point_inventory_item(
    segment: dict[str, Any],
    *,
    status: str,
    card: dict[str, Any] | None = None,
    reason: str = "",
    card_id: str | None = None,
) -> dict[str, Any]:
    source = card or segment
    source_id = str(segment.get("source_segment_id") or learning_point_source_key(segment))
    answer = clean_study_text(
        source.get("answer_core")
        or source.get("normalized_answer")
        or source.get("exact_span")
        or source.get("phrase")
        or segment.get("answer_core")
        or segment.get("normalized_answer")
        or segment.get("phrase")
        or ""
    )
    exact_span = clean_study_text(source.get("exact_span") or segment.get("exact_span") or answer)
    candidate_kind = str(source.get("candidate_kind") or segment.get("candidate_kind") or candidate_kind_for_segment(segment) or "expression")
    phrase_type = str(source.get("phrase_type") or segment.get("phrase_type") or phrase_type_for_candidate_kind(candidate_kind))
    value_score = phrase_review_score(source.get("phrase_value_score") or segment.get("phrase_value_score") or segment.get("recommendation") or 0)
    inventory_status = status if status in LEARNING_POINT_INVENTORY_STATUSES else "candidate_only"
    filter_reason = ""
    block_reason = ""
    if inventory_status in {"candidate_only", "hidden_duplicate"}:
        filter_reason = clean_study_text(reason or source.get("phrase_reject_reason") or segment.get("phrase_reject_reason") or "")
    if inventory_status == "hard_blocked":
        block_reason = clean_study_text(reason or source.get("phrase_reject_reason") or segment.get("phrase_reject_reason") or "")
    item_id_seed = f"{source_id}:{answer}:{candidate_kind}:{phrase_type}:{inventory_status}:{card_id or source.get('learning_point_id') or source.get('id') or ''}"
    item = {
        "id": str(source.get("learning_point_id") or source.get("id") or f"lp_inv_{stable_id(item_id_seed) & 0xFFFFFFFF:08x}"),
        "source_segment_id": source_id,
        "source_time": str(segment.get("source_time") or ""),
        "source_sentence": str(segment.get("text") or source.get("english") or ""),
        "exact_span": exact_span,
        "answer_core": answer,
        "normalized_answer": clean_study_text(source.get("normalized_answer") or answer),
        "candidate_kind": candidate_kind,
        "phrase_type": phrase_type,
        "estimated_level": str(source.get("estimated_level") or source.get("difficulty") or segment.get("difficulty") or ""),
        "value_score": value_score,
        "learning_action": inventory_learning_action(segment, card),
        "learning_action_key": str(source.get("learning_action_key") or segment.get("learning_action_key") or learning_action_key_for_contract(source)),
        "source": str(source.get("contract_source") or source.get("source") or source.get("candidate_source") or segment.get("candidate_source") or "local"),
        "confidence": str(source.get("confidence") or segment.get("confidence") or learning_point_confidence(value_score)),
        "validation_status": str(source.get("validation_status") or segment.get("validation_status") or ("valid" if inventory_status == "card_generated" else inventory_status)),
        "repair_history": source.get("repair_history") if isinstance(source.get("repair_history"), list) else [],
        "reason": clean_study_text(reason or source.get("phrase_decision_reason") or segment.get("phrase_decision_reason") or source.get("why") or ""),
        "status": inventory_status,
    }
    if source.get("exact_span_start") is not None:
        item["exact_span_start"] = source.get("exact_span_start")
    if source.get("exact_span_end") is not None:
        item["exact_span_end"] = source.get("exact_span_end")
    if card_id:
        item["card_id"] = card_id
    if filter_reason:
        item["filter_reason"] = filter_reason
    if block_reason:
        item["block_reason"] = block_reason
    return item


def build_learning_point_inventory(
    segments: list[dict[str, Any]],
    skipped_segments: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str]] = set()

    def append_item(item: dict[str, Any]) -> None:
        key = (
            str(item.get("source_segment_id") or ""),
            str(item.get("candidate_kind") or ""),
            str(item.get("learning_action_key") or normalized_phrase_key(str(item.get("answer_core") or item.get("exact_span") or ""))),
            str(item.get("status") or ""),
            str(item.get("card_id") or ""),
        )
        if key in seen:
            return
        seen.add(key)
        items.append(item)

    for segment in segments:
        original_cards = list(segment.get("cards", []) or [])
        usable_cards = [card for card in original_cards if card_quality_status(card) != "reject"]
        rejected_cards = [card for card in original_cards if card_quality_status(card) == "reject"]
        for card in usable_cards:
            append_item(
                learning_point_inventory_item(
                    segment,
                    status="card_generated",
                    card=card,
                    card_id=str(card.get("id") or ""),
                    reason=str(card.get("decision_reason") or card.get("phrase_decision_reason") or ""),
                )
            )
        for card in rejected_cards:
            quality = card.get("quality") if isinstance(card.get("quality"), dict) else {}
            reason = " / ".join(str(issue) for issue in quality.get("issues") or []) or str(card.get("phrase_reject_reason") or "")
            append_item(
                learning_point_inventory_item(
                    segment,
                    status=inventory_status_for_rejected_card(card, segment),
                    card=card,
                    reason=reason,
                )
            )
        if not original_cards:
            status = inventory_status_for_filtered_item(segment)
            append_item(learning_point_inventory_item(segment, status=status, reason=str(segment.get("phrase_reject_reason") or "")))

    for segment in skipped_segments or []:
        status = inventory_status_for_filtered_item(segment)
        append_item(learning_point_inventory_item(segment, status=status, reason=str(segment.get("phrase_reject_reason") or "")))

    status_order = {"card_generated": 0, "candidate_only": 1, "hidden_duplicate": 2, "hard_blocked": 3}
    return sorted(
        items,
        key=lambda item: (
            float(next((seg.get("start") for seg in segments if learning_point_source_key(seg) == item.get("source_segment_id")), 0) or 0),
            status_order.get(str(item.get("status") or ""), 9),
            str(item.get("answer_core") or ""),
        ),
    )


def learning_point_inventory_stats(inventory: list[dict[str, Any]] | None) -> dict[str, int]:
    return inventory_learning_point_inventory_stats(inventory)


def apply_default_generated_card_selection(segments: list[dict[str, Any]], project: dict[str, Any]) -> list[dict[str, Any]]:
    return inventory_apply_default_generated_card_selection(segments, project)


def final_output_card_duplicate_key(segment: dict[str, Any], card: dict[str, Any]) -> str:
    source_text = normalized_phrase_key(str(card.get("english") or segment.get("text") or ""))
    answer = normalized_phrase_key(
        str(card.get("answer_core") or card.get("phrase") or card.get("normalized_answer") or "")
    )
    card_type = str(card.get("type") or "").strip().lower()
    if not source_text or not answer or not card_type:
        return ""
    return f"{source_text}|{answer}|{card_type}"


EXPORT_BLOCKING_QUALITY_ISSUES = {
    "原句疑似截断",
    "原句证据边界需复核",
    "本地草稿，需要人工确认",
    "预览草稿，需要人工确认",
    "字段像模板废话",
    "AI 解释字段不足",
    "缺少中文意思",
    "缺少释义",
}


EXPORT_BLOCKING_TEXT_PATTERNS = (
    "待精修",
    "本地 fallback",
    "本地草稿",
    "预览草稿",
    "正式导出前应使用模型精修",
    "本地待审字段",
    "适合快速预览流程",
    "模型未完整返回",
    "模型未返回",
    "系统保底生成",
    "保底生成",
    "兜底生成",
    "不建议直接作为正式学习内容",
)


def card_has_export_blocking_content(card: dict[str, Any]) -> bool:
    if str(card.get("validation_status") or "").strip() == "reject":
        return True
    if str(card.get("source_sentence_quality_status") or "").strip() == "needs_review":
        return True
    english = str(card.get("english") or "").strip()
    if english and ends_like_fragment(english):
        return True
    quality = card.get("quality") if isinstance(card.get("quality"), dict) else {}
    issues = {str(issue) for issue in quality.get("issues") or []}
    if issues & EXPORT_BLOCKING_QUALITY_ISSUES:
        return True
    fields = [
        card.get("chinese", ""),
        card.get("definition", ""),
        card.get("teacher_note", ""),
        card.get("why", ""),
        card.get("context", ""),
        card.get("natural_chinese", ""),
        card.get("why_it_matters", ""),
        card.get("how_to_use_it", ""),
    ]
    issue_blob = "\n".join(str(issue or "") for issue in quality.get("issues") or [])
    blob = "\n".join([*(str(value or "") for value in fields), issue_blob])
    return any(pattern in blob for pattern in EXPORT_BLOCKING_TEXT_PATTERNS)


def filter_usable_segments_for_output(
    segments: list[dict[str, Any]],
    skipped_segments: list[dict[str, Any]] | None = None,
    *,
    block_export_drafts: bool = True,
    dedupe_cards: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    stats = {
        "filtered_learning_point_count": 0,
        "duplicate_learning_point_count": 0,
        "low_value_filtered_count": 0,
        "blocked_quality_issue_count": 0,
    }
    for segment in skipped_segments or []:
        stats["filtered_learning_point_count"] += 1
        if segment.get("phrase_review_status") == "duplicate":
            stats["duplicate_learning_point_count"] += 1
        elif segment.get("phrase_review_status") == "reject":
            stats["low_value_filtered_count"] += 1
            stats["blocked_quality_issue_count"] += 1
        else:
            stats["low_value_filtered_count"] += 1

    output_segments: list[dict[str, Any]] = []
    seen_card_keys: set[str] = set()
    for segment in segments:
        original_cards = list(segment.get("cards", []) or [])
        usable_cards = [
            card
            for card in original_cards
            if card_quality_status(card) != "reject"
            and (not block_export_drafts or not card_has_export_blocking_content(card))
        ]
        removed_cards = len(original_cards) - len(usable_cards)
        if removed_cards:
            stats["filtered_learning_point_count"] += removed_cards
            stats["blocked_quality_issue_count"] += removed_cards
        if not usable_cards:
            stats["filtered_learning_point_count"] += 1 if not removed_cards else 0
            status = str(segment.get("phrase_review_status") or "").strip()
            if status == "duplicate":
                stats["duplicate_learning_point_count"] += 1
            else:
                stats["low_value_filtered_count"] += 1
            continue
        next_segment = {**segment, "cards": []}
        if str(next_segment.get("phrase_review_status") or "") in {"reject", "duplicate"}:
            next_segment["phrase_review_status"] = "recommended"
        duplicate_cards_removed = 0
        for card in usable_cards:
            next_card = {**card, "enabled": card_quality_status(card) == "recommended"}
            duplicate_key = final_output_card_duplicate_key(next_segment, next_card)
            if dedupe_cards and duplicate_key and duplicate_key in seen_card_keys:
                stats["filtered_learning_point_count"] += 1
                stats["duplicate_learning_point_count"] += 1
                duplicate_cards_removed += 1
                continue
            if dedupe_cards and duplicate_key:
                seen_card_keys.add(duplicate_key)
            next_segment["cards"].append(next_card)
        if next_segment["cards"]:
            output_segments.append(next_segment)
        else:
            stats["filtered_learning_point_count"] += 1
            if not duplicate_cards_removed:
                stats["duplicate_learning_point_count"] += 1
    return output_segments, stats


def enforce_reviewable_cards_per_source(
    segments: list[dict[str, Any]],
    project: dict[str, Any],
) -> list[dict[str, Any]]:
    max_cards = max_reviewable_cards_per_source(project)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for segment in segments:
        grouped.setdefault(learning_point_source_key(segment), []).append(segment)

    for items in grouped.values():
        reviewable_cards: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for segment in items:
            for card in segment.get("cards", []) or []:
                if card_quality_status(card) in {"recommended", "needs_review"}:
                    reviewable_cards.append((segment, card))
        ranked = sorted(
            reviewable_cards,
            key=lambda pair: (
                int((pair[1].get("quality") or {}).get("score") or 0),
                phrase_review_score(pair[1].get("phrase_value_score") or pair[0].get("phrase_value_score")),
                -float(pair[0].get("start") or 0),
            ),
            reverse=True,
        )
        for _, card in ranked[max_cards:]:
            quality = dict(card.get("quality") or {})
            quality["status"] = "reject"
            issues = list(quality.get("issues") or [])
            issues.append(f"同一句可复习卡预算超过 {max_cards} 张，已从可导出卡列表过滤。")
            quality["issues"] = list(dict.fromkeys(issues))
            quality["score"] = min(int(quality.get("score") or 0), 39)
            card["quality"] = quality
            card["enabled"] = False
    return segments


def yt_dlp_base_command() -> list[str] | None:
    if os.environ.get("ACG_MANAGED_RUNTIME") == "1":
        try:
            return [str(media_managed_tool_path("yt-dlp"))]
        except MediaToolPolicyError:
            return None
    executable = shutil.which("yt-dlp")
    if executable:
        return [executable]

    completed = subprocess.run(
        [sys.executable, "-m", "yt_dlp", "--version"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        **hidden_subprocess_flags(),
    )
    if completed.returncode == 0:
        return [sys.executable, "-m", "yt_dlp"]
    return None


def yt_dlp_js_runtime_args(allow_remote_components: bool = False) -> list[str]:
    return ytdlp_support_yt_dlp_js_runtime_args(allow_remote_components, which_func=shutil.which)


def yt_dlp_network_args() -> list[str]:
    return ytdlp_support_yt_dlp_network_args(curl_cffi_available=importlib.util.find_spec("curl_cffi") is not None)


def yt_dlp_failure_detail(completed: subprocess.CompletedProcess[str]) -> str:
    return ytdlp_support_yt_dlp_failure_detail(completed)


def is_subtitle_rate_limited(detail: str) -> bool:
    return ytdlp_support_is_subtitle_rate_limited(detail)


def format_yt_dlp_failure(detail: str) -> str:
    return ytdlp_support_format_yt_dlp_failure(detail)


def yt_dlp_failure_meta(detail: str) -> dict[str, Any]:
    return ytdlp_support_yt_dlp_failure_meta(detail)


def run_yt_dlp(
    args: list[str],
    timeout: int = 900,
    check: bool = True,
    *,
    allow_remote_components: bool = False,
) -> subprocess.CompletedProcess[str]:
    command = yt_dlp_base_command()
    if not command:
        fail("找不到 yt-dlp。请运行：pip install yt-dlp，或把 yt-dlp 加入 PATH。")
    if os.environ.get("ACG_MANAGED_RUNTIME") == "1" and allow_remote_components:
        fail(
            "托管插件运行时禁止下载或执行 yt-dlp 远程组件。请改用仅字幕模式或上传本地字幕。",
            error_code="YTDLP_REMOTE_COMPONENTS_DISABLED",
            stage="download_video",
            retryable=False,
            fallbacks=["subtitle_only", "local_srt"],
        )
    safety_args = [
        "--ignore-config",
        "--no-plugin-dirs",
        "--no-exec",
        "--no-playlist",
        "--no-write-playlist-metafiles",
    ]
    if os.environ.get("ACG_MANAGED_RUNTIME") == "1":
        try:
            safety_args.extend(["--ffmpeg-location", str(media_managed_tool_path("ffmpeg").parent)])
        except MediaToolPolicyError as error:
            fail(f"托管 yt-dlp 缺少受信 FFmpeg：{error}", error_code=error.code, stage="download")
    completed = subprocess.run(
        [
            *command,
            *safety_args,
            *yt_dlp_js_runtime_args(allow_remote_components),
            *yt_dlp_network_args(),
            *args,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=max(1, min(int(timeout), 900)),
        shell=False,
        **hidden_subprocess_flags(),
    )
    if check and completed.returncode != 0:
        detail = yt_dlp_failure_detail(completed)
        fail(format_yt_dlp_failure(detail), **yt_dlp_failure_meta(detail))
    return completed


def subtitle_language_args(language: str) -> str:
    return subtitle_discovery_subtitle_language_args(language)


def first_file_by_suffix(directory: Path, suffixes: tuple[str, ...]) -> Path | None:
    return subtitle_discovery_first_file_by_suffix(directory, suffixes)


def convert_vtt_to_srt(path: Path) -> Path:
    return subtitle_discovery_convert_vtt_to_srt(path)


def pick_subtitle_file(directory: Path, language: str) -> Path | None:
    return subtitle_discovery_pick_subtitle_file(directory, language)


def compact_match_text(value: str) -> str:
    return subtitle_discovery_compact_match_text(value)


def subtitle_language_markers(language: str) -> set[str]:
    return subtitle_discovery_subtitle_language_markers(language)


def discover_local_subtitle(video_path: str, language: str = "English") -> Path | None:
    return subtitle_discovery_discover_local_subtitle(video_path, language)


def subtitle_language_aliases(language: str) -> set[str]:
    return subtitle_discovery_subtitle_language_aliases(language)


def run_ffprobe_json(video_path: Path) -> dict[str, Any] | None:
    try:
        completed = media_policy_run_ffprobe(
            ["-print_format", "json", "-show_streams"],
            video_path,
            timeout=30,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **hidden_subprocess_flags(),
        )
    except (MediaToolPolicyError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    try:
        return json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        return None


def select_embedded_subtitle_stream(probe: dict[str, Any] | None, language: str) -> dict[str, Any] | None:
    return subtitle_discovery_select_embedded_subtitle_stream(probe, language)


def extract_embedded_subtitle(video_path: str, language: str = "English") -> Path | None:
    video = Path(clean_input_path(video_path))
    if not video.exists():
        return None

    probe = run_ffprobe_json(video)
    stream = select_embedded_subtitle_stream(probe, language)
    if not stream:
        return None

    stream_index = stream.get("index")
    if stream_index is None:
        return None

    fingerprint_source = f"{video.resolve()}|{video.stat().st_mtime_ns}|{video.stat().st_size}|{stream_index}"
    fingerprint = hashlib.sha1(fingerprint_source.encode("utf-8", errors="ignore")).hexdigest()[:16]
    output_dir = Path.cwd() / "projects" / "local_subtitles"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{safe_filename(video.stem)}_stream_{stream_index}_{fingerprint}.srt"
    if output_path.exists() and output_path.stat().st_size > 0:
        return output_path

    try:
        completed = media_policy_run_ffmpeg(
            ["-i", str(video), "-map", f"0:{stream_index}", "-c:s", "srt", str(output_path)],
            timeout=120,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **hidden_subprocess_flags(),
        )
    except (MediaToolPolicyError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0 or not output_path.exists() or output_path.stat().st_size == 0:
        output_path.unlink(missing_ok=True)
        return None
    return output_path


def read_download_info(directory: Path) -> dict[str, Any]:
    info_files = sorted(directory.glob("*.info.json"))
    if not info_files:
        return {}
    info_file = info_files[0]
    try:
        data = json.loads(info_file.read_text(encoding="utf-8", errors="replace"))
        return {
            "title": data.get("title") or "",
            "webpage_url": data.get("webpage_url") or data.get("original_url") or "",
            "duration": data.get("duration"),
            "uploader": data.get("uploader") or "",
        }
    except Exception:
        return {}


def find_cached_url_source(cache_root: Path, url_hash: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    candidates = [path for path in cache_root.glob(f"url_*{url_hash}") if path.is_dir()]
    stable_candidate = cache_root / f"url_{url_hash}"
    if stable_candidate.exists() and stable_candidate not in candidates:
        candidates.insert(0, stable_candidate)
    candidates = sorted(candidates, key=lambda path: path.stat().st_mtime if path.exists() else 0, reverse=True)

    for directory in candidates:
        video_path = first_file_by_suffix(directory, (".mp4", ".mkv", ".webm", ".mov"))
        subtitle_path = pick_subtitle_file(directory, payload.get("language", "English"))
        if not subtitle_path or (not video_path and not wants_subtitle_only(payload)):
            continue
        info = read_download_info(directory)
        skip_video_slicing = not bool(video_path) or (
            bool(payload.get("skip_video_slicing")) and not url_video_mode_requested(payload)
        )
        return {
            "video_path": str(video_path) if video_path else "",
            "subtitle_path": str(subtitle_path),
            "download_dir": str(directory),
            "url": str(payload.get("source_url") or "").strip(),
            "cached": True,
            "transcript_only": not bool(video_path),
            "skip_video_slicing": skip_video_slicing,
            "download_mode": "subtitles" if not video_path else "video",
            **info,
        }
    return None


def download_url_subtitles_only(payload: dict[str, Any], download_dir: Path, output_template: str, sub_langs: str) -> dict[str, Any]:
    url = validate_source_url_for_import(payload)
    args = [
        "--no-playlist",
        "--windows-filenames",
        "--write-info-json",
        "--skip-download",
        "--sub-langs",
        sub_langs,
        "--convert-subs",
        "srt",
        "--output",
        output_template,
        "--write-subs",
        "--write-auto-subs",
        url,
    ]
    completed = run_yt_dlp(
        args,
        check=False,
        allow_remote_components=bool(payload.get("allow_ytdlp_remote_components")),
    )
    if completed.returncode != 0:
        detail = yt_dlp_failure_detail(completed)
        fail_if_remote_components_confirmation_required(payload, detail)
        fail(format_yt_dlp_failure(detail), **yt_dlp_failure_meta(detail))

    subtitle_path = pick_subtitle_file(download_dir, payload.get("language", "English"))
    if not subtitle_path:
        fail(
            "URL 字幕下载完成，但没有找到可用 SRT/VTT。请换一个带字幕的视频，或手动上传 SRT。",
            error_code="YOUTUBE_SUBTITLE_UNAVAILABLE",
            stage="download_subtitles",
            retryable=True,
            fallbacks=["local_srt"],
        )

    info = read_download_info(download_dir)
    return {
        "video_path": "",
        "subtitle_path": str(subtitle_path),
        "download_dir": str(download_dir),
        "url": url,
        "transcript_only": True,
        "skip_video_slicing": True,
        "download_mode": "subtitles",
        "warning": "本次只使用字幕生成卡片，导出的 APKG 不包含视频片段和原声音频。",
        **info,
    }


def download_url_source(payload: dict[str, Any]) -> dict[str, Any]:
    url = validate_source_url_for_import(payload)

    cache_root = Path.cwd() / "projects" / "url_cache"
    cache_root.mkdir(parents=True, exist_ok=True)
    url_hash = f"{zlib.crc32(url.encode('utf-8')) & 0xFFFFFFFF:x}"
    cached_source = find_cached_url_source(cache_root, url_hash, payload)
    if cached_source:
        return cached_source

    download_dir = cache_root / f"url_{url_hash}"
    download_dir.mkdir(parents=True, exist_ok=True)

    output_template = str(download_dir / "source.%(ext)s")
    sub_langs = subtitle_language_args(payload.get("language", "English"))
    if wants_subtitle_only(payload):
        return download_url_subtitles_only(payload, download_dir, output_template, sub_langs)

    common_args = [
        "--no-playlist",
        "--windows-filenames",
        "--write-info-json",
        "--sub-langs",
        sub_langs,
        "--convert-subs",
        "srt",
        "--format",
        "bv*[height<=480]+ba/b[height<=480]/best[height<=480]/best",
        "--merge-output-format",
        "mp4",
        "--output",
        output_template,
    ]
    download_args = [
        *common_args,
        "--write-subs",
        "--write-auto-subs",
        url,
    ]
    completed = run_yt_dlp(
        download_args,
        check=False,
        allow_remote_components=bool(payload.get("allow_ytdlp_remote_components")),
    )
    if completed.returncode != 0:
        detail = yt_dlp_failure_detail(completed)
        fail_if_remote_components_confirmation_required(payload, detail)
        if is_subtitle_rate_limited(detail):
            # If YouTube rate-limits official subtitles, try auto subtitles only once after a short pause.
            time.sleep(8)
            retry = run_yt_dlp(
                [
                    *common_args,
                    "--write-auto-subs",
                    url,
                ],
                check=False,
                allow_remote_components=bool(payload.get("allow_ytdlp_remote_components")),
            )
            if retry.returncode != 0:
                retry_detail = yt_dlp_failure_detail(retry) or detail
                fail_if_remote_components_confirmation_required(payload, retry_detail)
                if payload.get("url_auto_subtitle_fallback", True):
                    try:
                        return download_url_subtitles_only(payload, download_dir, output_template, sub_langs)
                    except SystemExit as err:
                        fail(
                            f"{format_yt_dlp_failure(retry_detail)}\n\n字幕下载 fallback 也失败，退出码：{err.code}",
                            **yt_dlp_failure_meta(retry_detail),
                        )
                fail(format_yt_dlp_failure(retry_detail), **yt_dlp_failure_meta(retry_detail))
        else:
            if payload.get("url_auto_subtitle_fallback", True):
                try:
                    return download_url_subtitles_only(payload, download_dir, output_template, sub_langs)
                except SystemExit as err:
                    fail(
                        f"{format_yt_dlp_failure(detail)}\n\n字幕下载 fallback 也失败，退出码：{err.code}",
                        **yt_dlp_failure_meta(detail),
                    )
            fail(format_yt_dlp_failure(detail), **yt_dlp_failure_meta(detail))

    video_path = first_file_by_suffix(download_dir, (".mp4", ".mkv", ".webm", ".mov"))
    if not video_path:
        fail("URL 已处理，但没有找到下载后的视频文件。")

    subtitle_path = pick_subtitle_file(download_dir, payload.get("language", "English"))
    if not subtitle_path:
        if payload.get("url_auto_subtitle_fallback", True):
            return download_url_subtitles_only(payload, download_dir, output_template, sub_langs)
        fail(
            "视频已下载，但没有下载到可用字幕。请换一个带字幕/自动字幕的视频，或改用本地 SRT。",
            error_code="YOUTUBE_SUBTITLE_UNAVAILABLE",
            stage="download_subtitles",
            retryable=True,
            fallbacks=["local_srt"],
        )

    info = read_download_info(download_dir)
    return {
        "video_path": str(video_path),
        "subtitle_path": str(subtitle_path),
        "download_dir": str(download_dir),
        "url": url,
        "transcript_only": False,
        "skip_video_slicing": False if url_video_mode_requested(payload) else bool(payload.get("skip_video_slicing")),
        "download_mode": "video",
        **info,
    }


def build_document_prompt(project: dict[str, Any], segments: list[dict[str, Any]]) -> str:
    focus_instruction = document_focus_instruction(project)
    style_instruction = document_style_instruction(project)
    study_mode = normalized_document_study_mode(project)
    material_context_instruction = material_context_for_prompt(project.get("material_context"))
    try:
        target_card_count = max(1, int(project.get("max_segments") or len(segments) or 1))
    except (TypeError, ValueError):
        target_card_count = max(1, len(segments) or 1)
    document_card_count_instruction = (
        f"本次最多输出 {target_card_count} 张卡。"
        "如果片段数量少但同一片段包含多个互不重复的高价值知识点，可以在同一个 segment.cards 里输出多张；"
        "短资料可以先做独立概念卡，再做一张有原文证据支撑的综合/对比卡，把两个概念的关系、边界或配合方式问清楚；"
        "每张卡必须训练不同的回忆动作，不能改写同一个问题来凑数量。"
        "如果资料确实不足，少于目标数量也可以。"
    )
    compact = [
        {
            "id": segment["id"],
            "source": segment["source_time"],
            "question_hint": segment["text"],
            "excerpt": segment.get("document_excerpt", ""),
        }
        for segment in segments
    ]
    if study_mode == "language_reading":
        reading_focus = normalized_document_reading_focus(project)
        focus_labels = {
            "phrases": "词伙表达：抽取可迁移短语、搭配和句型块，禁止整句当词伙。",
            "vocabulary": "单词用法：抽取真实语境里的词义、搭配和易错用法，不做孤立词典卡。",
            "grammar": "语法框架：抽取可替换句型、结构和语气功能，不做抽象语法定义。",
        }
        focus_instruction = "".join(focus_labels[item] for item in reading_focus)
        return (
            "你是中文母语者的英文文档精读老师和 Anki 卡片编辑老师。请从文档片段里抽取语言学习点，"
            "不是总结知识内容。重点是让学习者下次能读懂、会用或能辨认表达结构。"
            f"{material_context_instruction}"
            "文档没有原声，禁止生成听力卡，禁止提到原声/TTS/视频切片。"
            f"本次语言精读目标：{focus_instruction}"
            f"{style_instruction}"
            f"{document_card_count_instruction}"
            "制卡标准："
            "1) 每张卡只训练一个语言动作：理解一个表达、掌握一个词的用法、看懂一个语法框架。"
            "2) phrase 必须来自原文片段，不能是 key expression，不能是整句。"
            "3) english 写主动回忆问题或原文提示；chinese 写自然中文理解。"
            "4) definition 写怎么理解；collocations 写可替换框架/搭配；context 写文档语境。"
            "5) why 和 teacher_note 必须说明为什么这个语言点值得学、下次怎么辨认或复用。"
            "6) 弱卡默认待审：不要为了数量硬凑语言点。"
            "返回严格 JSON，不要 Markdown。JSON 结构："
            '{"segments":[{"id":"doc_0001","cards":[{"type":"knowledge",'
            '"knowledge_type":"terms|concepts|examples","english":"正面问题或原文提示","chinese":"自然中文理解",'
            '"phrase":"原文中的表达/单词/语法框架","definition":"怎么理解",'
            '"collocations":"替换框架/搭配","context":"文档语境","example":"原文例子或改写例子","chinese_feel":"中文直觉",'
            '"why":"为什么值得学","difficulty":"A1 入门|A2 基础|B1 日常交流|B2 独立表达|C1 高阶表达|C2 接近母语",'
            '"teacher_note":"一句老师提醒","learning_target":"这张卡练什么",'
            '"why_it_matters":"为什么值得学","how_to_use_it":"下次如何辨认或复用",'
            '"cloze":"挖空复习句，且只有一个 ____"}]}]}。'
            f"用户水平：{project.get('level', 'B1')}。"
            f"文档片段：{json.dumps(compact, ensure_ascii=False)}"
        )
    return (
        "你是中文母语者的读书笔记老师和 Anki 知识卡编辑老师。请把文档片段变成少而精的知识卡，"
        "不要把它当摘要任务。先判断这段到底值得记什么，再写卡片。"
        f"{material_context_instruction}"
        f"{focus_instruction}"
        f"{style_instruction}"
        f"{document_card_count_instruction}"
        "高质量知识卡原则：必须遵守最小信息原则，先理解再记忆；"
        "每张卡只保留一个可主动回忆的信息单元。"
        "必须保留原文依据或适用语境，避免脱离资料凭空解释。"
        "复杂概念先拆离散组件，再用少量综合卡连接。"
        "必须写清边界/反例或易混点，帮助复习时判断什么时候不能这么用。"
        "必须写迁移检查：复习时要知道下次遇到什么场景、判断题或例子时能用这张卡。"
        "不要把标题、目录、铺垫做成卡；不要为了数量把空泛背景硬拆成卡。"
        "cloze 只能有一个 ____，不能让多个空互相泄露答案。"
        "制卡标准："
        "1) 每张卡只训练一个知识动作：定义一个概念、解释一个观点、区分一组概念、记住一个例子。"
        "2) retrieval_task/english 必须是具体主动回忆问题；不要写“这段主要讲什么”这种泛问题。"
        "3) atomic_answer/chinese 是背面第一屏短答案，必须短而准，优先 1-3 句；不要照抄整段原文。"
        "4) phrase 是概念名、观点名或术语，必须短；禁止输出“核心知识点”“知识点”“章节标题”“N/A”。"
        "5) definition 写怎么理解；source_evidence 写原文依据；memory_hook 写帮助记住的类比或压缩提示。"
        "6) transfer_check 写复习时如何迁移/判断；boundary 写边界/反例/易混点。"
        "7) example 必须来自文档例子或基于文档改写，不能空泛编造。"
        "8) why 和 teacher_note 要解释为什么值得记、复习时怎么抓关键，不要写套话。"
        "9) 如果片段只有铺垫、目录、广告、空泛背景，cards 返回空数组。"
        "返回严格 JSON，不要 Markdown。JSON 结构："
        '{"segments":[{"id":"doc_0001","cards":[{"type":"knowledge",'
        '"knowledge_type":"concepts|arguments|terms|examples","retrieval_task":"正面主动回忆问题",'
        '"atomic_answer":"背面第一屏短答案","english":"正面问题","chinese":"反面核心答案",'
        '"phrase":"概念名/观点名/术语","definition":"概念解释",'
        '"source_evidence":"原文依据或原句线索","memory_hook":"记忆钩子",'
        '"transfer_check":"迁移检查","boundary":"边界/反例",'
        '"collocations":"相关概念/搭配","context":"适用语境",'
        '"example":"例子","chinese_feel":"中文理解",'
        '"why":"为什么值得记","difficulty":"A1 入门|A2 基础|B1 日常交流|B2 独立表达|C1 高阶表达|C2 接近母语",'
        '"teacher_note":"一句老师提醒","learning_target":"这张卡练什么",'
        '"why_it_matters":"为什么值得记","how_to_use_it":"复习时如何迁移或判断",'
        '"cloze":"挖空复习句，且只有一个 ____"}]}]}。'
        f"用户水平：{project.get('level', 'B1')}。"
        f"文档片段：{json.dumps(compact, ensure_ascii=False)}"
    )


def document_generation_cache_path(project: dict[str, Any], segment: dict[str, Any]) -> tuple[Path, str]:
    api = project.get("api_config") or {}
    cache_key = stable_cache_key(
        {
            "version": 5,
            "kind": "document_point_card_generation",
            "provider": provider_name(api),
            "base_url": str(api.get("base_url") or "").strip().rstrip("/"),
            "model": str(api.get("model") or "").strip(),
            "language": normalize_learning_language(project.get("language", "en")),
            "level_mode": normalized_level_mode(project),
            "level": str(project.get("level") or "B1"),
            "study_mode": normalized_document_study_mode(project),
            "document_focus": normalized_document_focus(project),
            "document_answer_language": normalized_document_answer_language(project),
            "document_depth": normalized_document_depth(project),
            "document_answer_length": normalized_document_answer_length(project),
            "study_depth": normalized_study_depth(project),
            "document_path": clean_input_path(project.get("document_path")),
            "segment": {
                "id": str(segment.get("id") or ""),
                "text": str(segment.get("text") or ""),
                "phrase": str(segment.get("phrase") or ""),
                "document_excerpt": str(segment.get("document_excerpt") or ""),
            },
        }
    )
    return persistent_cache_root() / "document_generation" / f"{cache_key}.json", cache_key


def document_ai_payload_has_usable_cards(ai_payload: dict[str, Any] | None) -> bool:
    if not isinstance(ai_payload, dict):
        return False
    usable_fields = {
        "retrieval_task",
        "atomic_answer",
        "english",
        "chinese",
        "phrase",
        "definition",
        "source_evidence",
        "why_it_matters",
    }
    for segment in ai_payload.get("segments") or []:
        if not isinstance(segment, dict):
            continue
        for card in segment.get("cards") or []:
            if not isinstance(card, dict):
                continue
            if any(str(card.get(field) or "").strip() for field in usable_fields):
                return True
    return False


def load_document_generation_cache(cache_path: Path) -> dict[str, Any] | None:
    if not cache_path.exists() or cache_path.stat().st_size <= 0:
        return None
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    payload = cached.get("payload") if isinstance(cached, dict) else None
    if document_ai_payload_has_usable_cards(payload):
        return payload
    return None


def store_document_generation_cache(cache_path: Path, cache_key: str, ai_payload: dict[str, Any]) -> None:
    if ai_payload.get("error") or not document_ai_payload_has_usable_cards(ai_payload):
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


def cached_or_generated_document_payload(
    project: dict[str, Any],
    segments: list[dict[str, Any]],
    *,
    cache_disabled: bool,
) -> tuple[dict[str, Any] | None, dict[str, int]]:
    stats = {"cache_hits": 0, "cache_misses": 0}
    cached_by_segment_id: dict[str, dict[str, Any]] = {}
    missing_segments: list[dict[str, Any]] = []
    cache_paths: dict[str, tuple[Path, str]] = {}
    for segment in segments:
        segment_id = str(segment.get("id") or "")
        cache_paths[segment_id] = document_generation_cache_path(project, segment)
        if cache_disabled:
            missing_segments.append(segment)
            stats["cache_misses"] += 1
            continue
        cache_path, _cache_key = cache_paths[segment_id]
        cached = load_document_generation_cache(cache_path)
        cached_segments = cached.get("segments") if isinstance(cached, dict) else None
        if isinstance(cached_segments, list) and cached_segments:
            cached_by_segment_id[segment_id] = cached_segments[0]
            stats["cache_hits"] += 1
        else:
            missing_segments.append(segment)
            stats["cache_misses"] += 1

    generated_payload: dict[str, Any] | None = None
    if missing_segments:
        generated_payload = call_document_model(project, missing_segments)
        if not generated_payload:
            return None, stats
        if generated_payload.get("segments") and not cache_disabled:
            generated_by_segment_id = {
                str(segment.get("id") or ""): segment
                for segment in generated_payload.get("segments") or []
                if isinstance(segment, dict)
            }
            for segment in missing_segments:
                segment_id = str(segment.get("id") or "")
                generated_segment = generated_by_segment_id.get(segment_id)
                cache_path, cache_key = cache_paths.get(segment_id, (Path(), ""))
                if generated_segment and cache_path:
                    store_document_generation_cache(cache_path, cache_key, {"segments": [generated_segment]})

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
    result: dict[str, Any] = {"segments": merged_segments}
    if generated_payload and generated_payload.get("error"):
        result["error"] = generated_payload.get("error")
    return result, stats


def call_document_model(project: dict[str, Any], segments: list[dict[str, Any]]) -> dict[str, Any] | None:
    api = project.get("api_config") or {}
    provider = api.get("provider", "local")
    model = api.get("model", "").strip()
    if provider == "local" or not model or not model_api_available(api):
        return None

    prompt = build_document_prompt(project, segments)
    try:
        if provider in OPENAI_COMPATIBLE_PROVIDERS:
            token_budget = 2200 if is_mimo_config(api) else 7000 if is_deepseek_thinking_config(api) else 4000 if is_qwen_config(api) else 5000
            response = compatible_chat_completion(
                api,
                [
                    {"role": "system", "content": "Return only valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.25,
                timeout=180 if is_thinking_model_config(api) else 60,
                max_tokens=token_budget,
                progress={
                    "command": "generate",
                    "stage": "ai",
                    "percent": 70,
                    "message": "模型保留 thinking 生成文档卡字段",
                },
                work_unit_id="document-cards",
            )
            content = chat_completion_content(response)
            return extract_json_object(content)

        if provider == "claude":
            response = model_anthropic_messages(
                api,
                {
                    "model": model,
                    "max_tokens": 5000,
                    "temperature": 0.25,
                    "system": "Return only valid JSON.",
                    "messages": [{"role": "user", "content": prompt}],
                },
                work_unit_id="document-cards",
            )
            content = "".join(part.get("text", "") for part in response.get("content", []))
            return extract_json_object(content)

        if provider == "gemini":
            response = model_gemini_content(
                api,
                {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0.25,
                        "responseMimeType": "application/json",
                    },
                },
                work_unit_id="document-cards",
            )
            content = response["candidates"][0]["content"]["parts"][0]["text"]
            return extract_json_object(content)

        if is_gemini_vertex_config(api):
            content = gemini_vertex_generate_content(
                api,
                prompt,
                temperature=0.25,
                timeout=180 if is_gemini_vertex_thinking_config(api) else 120,
                max_output_tokens=14000 if is_gemini_vertex_thinking_config(api) else 7000,
            )
            return extract_json_object(content)
    except Exception as err:
        return {"error": str(err)}
    return None


def fallback_document_card(segment: dict[str, Any], level: str, study_mode: str = "knowledge") -> dict[str, Any]:
    excerpt = segment.get("document_excerpt", "")
    phrase = segment.get("phrase") or "核心知识点"
    answer = clip_words(excerpt, 70)
    is_reading = study_mode == "language_reading"
    return {
        "id": f"{segment['id']}_knowledge",
        "type": "knowledge",
        "type_label": "文档精读卡" if is_reading else "知识卡",
        "enabled": False,
        "document_card_kind": "language_reading" if is_reading else "knowledge",
        "knowledge_type": "terms" if is_reading else "concepts",
        "content_kind": "phrase" if is_reading else "knowledge",
        "source_evidence": excerpt,
        "english": segment.get("text", ""),
        "chinese": answer or ("请根据原文补充语言点理解。" if is_reading else "请根据原文补充核心答案。"),
        "phrase": phrase,
        "definition": answer or "预览草稿：请用模型精修或手动补充定义。",
        "collocations": "替换框架；语境搭配；易混用法" if is_reading else "相关概念；关键原因；典型例子",
        "context": "来自导入文档的精读点，适合确认表达、词义或语法框架。" if is_reading else "来自导入文档的知识点，适合做概念理解和主动回忆。",
        "example": clip_words(excerpt, 42),
        "chinese_feel": "先用自己的话解释，再核对原文中的关键条件和例子。",
        "why": "这段内容被拆成可复习的问题，适合后续在 Anki 里主动回忆。",
        "learning_target": "确认这段文档里是否有明确语言点值得精读。" if is_reading else "确认这段文档里是否有明确概念或观点值得记。",
        "why_it_matters": "本地 fallback 只能保留原文线索，需要模型或人工把它改成具体精读动作。" if is_reading else "本地 fallback 只能保留原文线索，需要模型或人工把它改成具体知识动作。",
        "how_to_use_it": "先确认表达是否来自原文，再补充下次阅读时如何辨认或复用。" if is_reading else "先检查问题是否具体，再把答案压缩成自己的话。",
        "difficulty": CEFR_LABELS.get(level, level),
        "estimated_level": level if level in CEFR_ORDER else "B1",
        "difficulty_reason": "本地文档草稿按当前水平和文本复杂度估计。",
        "teacher_note": "本地待审精读卡：建议检查语言点是否来自原文且值得复习。" if is_reading else "本地待审卡：建议检查问题是否具体，答案是否过长。",
        "cloze": f"{phrase} 的核心是 ____。",
        "quality": {
            "score": 64,
            "status": "needs_review",
            "issues": ["本地文档精读草稿，需要人工确认"] if is_reading else ["本地文档草稿，需要人工确认"],
        },
    }


def document_card_quality(card: dict[str, Any], fallback: bool = False) -> dict[str, Any]:
    issues: list[str] = []
    phrase = str(card.get("phrase", "")).strip().lower()
    english = str(card.get("english", "")).strip()
    chinese = str(card.get("chinese", "")).strip()
    definition = str(card.get("definition", "")).strip()
    teacher_note = str(card.get("teacher_note", "")).strip()
    why = str(card.get("why_it_matters") or card.get("why") or "").strip()
    knowledge_type = str(card.get("knowledge_type", "")).strip()
    source_evidence = str(card.get("source_evidence") or card.get("context") or "").strip()
    transfer_text = str(card.get("transfer_check") or card.get("how_to_use_it") or "").strip()
    boundary_text = str(card.get("boundary") or "").strip()
    boundary_candidates = " ".join(
        str(card.get(key) or "") for key in ["teacher_note", "collocations", "context"]
    )
    if not boundary_text and any(
        marker in boundary_candidates for marker in ["不是", "不能", "反例", "边界", "易混", "区别", "不等于", "不同于"]
    ):
        boundary_text = boundary_candidates.strip()
    cloze = str(card.get("cloze", "")).strip()

    if fallback:
        issues.append("本地文档草稿，需要人工确认")
    if phrase in {"", "核心知识点", "知识点", "key point", "knowledge point", "n/a", "none"}:
        issues.append("概念名是占位词，需人工提炼")
    if any(marker in phrase for marker in ["章节标题", "标题", "目录", "前言", "铺垫"]):
        issues.append("概念名像标题，需提炼成可回忆知识点")
    if knowledge_type not in DOCUMENT_FOCUS_ORDER:
        issues.append("缺少明确知识类型")
    generic_questions = {"这段主要讲什么？", "这段内容的核心是什么？"}
    if not english or len(english) < 8 or english in generic_questions or any(
        marker in english for marker in ["这段主要", "这段内容", "本文主要", "本节主要"]
    ):
        issues.append("正面问题太泛")
    if not source_evidence:
        issues.append("缺少原文依据")
    if not transfer_text:
        issues.append("缺少迁移检查")
    if not boundary_text:
        issues.append("缺少边界/反例")
    if len(chinese) > 180:
        issues.append("答案过长，建议压缩成 1-3 句")
    if cloze and cloze.count("____") != 1:
        issues.append("cloze 只能有一个空")
    if not definition or definition == chinese:
        issues.append("缺少独立概念解释")
    if not why:
        issues.append("缺少为什么值得记")
    if not teacher_note or "很重要" == teacher_note:
        issues.append("老师提醒不够具体")

    severe_issues = {
        "概念名是占位词，需人工提炼",
        "正面问题太泛",
        "缺少独立概念解释",
        "缺少为什么值得记",
    }
    score = max(35, 86 - len(issues) * 10 - (10 if fallback else 0))
    if not fallback and len(severe_issues.intersection(issues)) >= 3:
        status = "reject"
    else:
        status = "recommended" if not issues and score >= 78 else "needs_review"
    return {"score": score, "status": status, "issues": issues}


def merge_document_cards(
    segments: list[dict[str, Any]],
    ai_payload: dict[str, Any] | None,
    level: str,
    study_mode: str = "knowledge",
    max_cards: int | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    ai_by_segment: dict[str, dict[str, Any]] = {}
    warning = None
    if ai_payload:
        if "error" in ai_payload:
            warning = f"模型总结失败，已生成待审文档草稿：{ai_payload['error']}"
        for item in ai_payload.get("segments", []):
            ai_by_segment[item.get("id", "")] = item
    else:
        warning = "未配置可用模型，已生成本地待审文档草稿。"

    def normalize_ai_document_card_defaults(card: dict[str, Any]) -> None:
        safe_defaults = {
            "why_it_matters": "这张卡帮助把原文信息转成可主动回忆的问题。",
            "difficulty_reason": "根据当前水平、原文密度和回答复杂度估计。",
            "teacher_note": "先用自己的话回答，再核对原文依据。",
        }
        for key, replacement in safe_defaults.items():
            if contains_internal_placeholder(card.get(key)):
                card[key] = replacement
        if contains_internal_placeholder(card.get("context")):
            card["context"] = "来自导入文档的可复习知识点。"
        if contains_internal_placeholder(card.get("definition")):
            card["definition"] = card.get("chinese") or "请根据原文回答这个问题。"

    def card_from_ai_card(segment: dict[str, Any], ai_card: dict[str, Any], index: int) -> dict[str, Any]:
        card = fallback_document_card(segment, level, study_mode=study_mode)
        if index > 1:
            card["id"] = f"{segment['id']}_knowledge_{index:02d}"
        for key in [
            "english",
            "chinese",
            "phrase",
            "knowledge_type",
            "definition",
            "collocations",
            "context",
            "example",
            "chinese_feel",
            "why",
            "learning_target",
            "why_it_matters",
            "how_to_use_it",
            "difficulty",
            "estimated_level",
            "difficulty_reason",
            "teacher_note",
            "cloze",
            "content_kind",
            "source_evidence",
            "retrieval_task",
            "atomic_answer",
            "memory_hook",
            "transfer_check",
            "boundary",
        ]:
            if ai_card.get(key):
                card[key] = str(ai_card[key])
        if card.get("retrieval_task"):
            card["english"] = clean_study_text(card.get("retrieval_task"))
        if card.get("atomic_answer"):
            card["chinese"] = clean_study_text(card.get("atomic_answer"))
        if card.get("memory_hook"):
            hook = clean_study_text(card.get("memory_hook"))
            existing_feel = clean_study_text(card.get("chinese_feel"))
            card["chinese_feel"] = "；".join(part for part in [existing_feel, hook] if part)
        if card.get("transfer_check"):
            transfer = clean_study_text(card.get("transfer_check"))
            card["how_to_use_it"] = transfer
            card["why"] = transfer
        if card.get("boundary"):
            boundary = clean_study_text(card.get("boundary"))
            existing_note = clean_study_text(card.get("teacher_note"))
            card["teacher_note"] = "；".join(part for part in [existing_note, boundary] if part)
            existing_collocations = clean_study_text(card.get("collocations"))
            if boundary and boundary not in existing_collocations:
                card["collocations"] = "；".join(part for part in [existing_collocations, boundary] if part)
        if card["cloze"].count("____") != 1:
            card["cloze"] = f"{card['phrase']} 的核心是 ____。"
        normalize_ai_document_card_defaults(card)
        card["type_label"] = "文档精读卡" if study_mode == "language_reading" else "知识卡"
        card["document_card_kind"] = "language_reading" if study_mode == "language_reading" else "knowledge"
        card["quality"] = document_card_quality(card, fallback=False)
        if study_mode == "language_reading":
            card["quality"]["status"] = "needs_review"
            card["quality"].setdefault("issues", []).append("文档精读卡默认待审，需确认语言点是否值得保留")
            card["teacher_note"] = (
                card.get("teacher_note", "")
                or "文档精读卡：请确认这个表达、词义或语法框架确实值得复习。"
            )
        card["enabled"] = card["quality"]["status"] == "recommended"
        return card

    def relation_card_from_document_cards(segment: dict[str, Any], cards: list[dict[str, Any]], index: int) -> dict[str, Any] | None:
        if study_mode == "language_reading" or len(cards) < 2:
            return None
        left, right = cards[0], cards[1]
        left_phrase = clean_study_text(left.get("phrase"))
        right_phrase = clean_study_text(right.get("phrase"))
        if not left_phrase or not right_phrase or left_phrase.lower() == right_phrase.lower():
            return None
        left_definition = clip_words(
            clean_study_text(left.get("definition") or left.get("chinese") or left.get("atomic_answer")),
            18,
        ).rstrip("。.!！?？；; ")
        right_definition = clip_words(
            clean_study_text(right.get("definition") or right.get("chinese") or right.get("atomic_answer")),
            18,
        ).rstrip("。.!！?？；; ")
        if not left_definition or not right_definition:
            return None
        evidence_parts = [
            clean_study_text(left.get("source_evidence")),
            clean_study_text(right.get("source_evidence")),
        ]
        source_evidence = " ".join(dict.fromkeys(part for part in evidence_parts if part)).strip()
        if not source_evidence:
            source_evidence = clean_study_text(segment.get("document_excerpt"))
        if not source_evidence:
            return None
        relation_phrase = f"{left_phrase} + {right_phrase}"
        relation_card = fallback_document_card(segment, level, study_mode=study_mode)
        relation_card.update(
            {
                "id": f"{segment['id']}_knowledge_{index:02d}",
                "type": "knowledge",
                "type_label": "知识卡",
                "enabled": True,
                "document_card_kind": "knowledge",
                "knowledge_type": "arguments",
                "content_kind": "knowledge",
                "source_evidence": source_evidence,
                "retrieval_task": f"{left_phrase} 和 {right_phrase} 在这段资料里是什么关系？",
                "atomic_answer": (
                    f"{left_phrase} 关注：{left_definition}；"
                    f"{right_phrase} 关注：{right_definition}。"
                    "二者合起来说明这段资料有两个需要同时理解的侧面。"
                ),
                "english": f"{left_phrase} 和 {right_phrase} 在这段资料里是什么关系？",
                "chinese": (
                    f"{left_phrase} 关注：{left_definition}；"
                    f"{right_phrase} 关注：{right_definition}。"
                    "二者合起来说明这段资料有两个需要同时理解的侧面。"
                ),
                "phrase": relation_phrase,
                "definition": "这是一张综合/对比卡：把同一段资料里的两个知识点连接起来，而不是重复任一张单点卡。",
                "collocations": f"{left_phrase}；{right_phrase}；综合关系；概念边界",
                "context": "来自同一段导入文档的综合关系，用来检查两个知识点是否能被连起来理解。",
                "example": clip_words(source_evidence, 42),
                "chinese_feel": "先分别回忆两个概念，再说明它们如何配合或区分。",
                "why": f"复习时先分别说出 {left_phrase} 和 {right_phrase}，再说明二者的配合或区别。",
                "learning_target": "把两个相关知识点从孤立记忆提升为关系理解。",
                "why_it_matters": "关系卡能防止只记住名词，却说不出它们如何一起支持原文观点。",
                "how_to_use_it": f"复习时先分别说出 {left_phrase} 和 {right_phrase}，再说明二者的配合或区别。",
                "difficulty": CEFR_LABELS.get(level, level),
                "estimated_level": level if level in CEFR_ORDER else "B1",
                "difficulty_reason": "根据当前水平和两个知识点的关系复杂度估计。",
                "teacher_note": "这张卡不是新造概念，而是关系卡；先答两个单点，再解释它们为什么放在同一段里。",
                "cloze": f"{left_phrase} 和 {right_phrase} 的关系是 ____。",
                "transfer_check": f"复习时先分别说出 {left_phrase} 和 {right_phrase}，再说明二者的配合或区别。",
                "boundary": "如果只能说出其中一个概念，而不能说明二者关系，这张综合卡就还没掌握。",
                "memory_hook": "两张单点卡是零件；关系卡检查你能不能把零件装成结构。",
            }
        )
        relation_card["quality"] = document_card_quality(relation_card, fallback=False)
        relation_card["enabled"] = relation_card["quality"]["status"] == "recommended"
        return relation_card

    emitted_cards = 0
    card_limit = max_cards if isinstance(max_cards, int) and max_cards > 0 else None
    for segment in segments:
        if card_limit is not None and emitted_cards >= card_limit:
            segment["cards"] = []
            continue
        cards: list[dict[str, Any]] = []
        ai_segment = ai_by_segment.get(segment["id"])
        if ai_segment:
            raw_ai_cards = [
                item
                for item in ai_segment.get("cards", [])
                if isinstance(item, dict) and str(item.get("type") or "knowledge") == "knowledge"
            ]
            seen_signatures: set[str] = set()
            for index, ai_card in enumerate(raw_ai_cards, 1):
                if card_limit is not None and emitted_cards >= card_limit:
                    break
                card = card_from_ai_card(segment, ai_card, index)
                signature = stable_cache_key(
                    {
                        "phrase": clean_study_text(card.get("phrase")).lower(),
                        "english": clean_study_text(card.get("english")).lower(),
                        "chinese": clean_study_text(card.get("chinese")).lower(),
                    }
                )
                if signature in seen_signatures:
                    continue
                seen_signatures.add(signature)
                cards.append(card)
                emitted_cards += 1
            if card_limit is not None and emitted_cards < card_limit and len(cards) >= 2:
                relation_card = relation_card_from_document_cards(segment, cards, len(cards) + 1)
                if relation_card is not None:
                    relation_signature = stable_cache_key(
                        {
                            "phrase": clean_study_text(relation_card.get("phrase")).lower(),
                            "english": clean_study_text(relation_card.get("english")).lower(),
                            "chinese": clean_study_text(relation_card.get("chinese")).lower(),
                        }
                    )
                    if relation_signature not in seen_signatures:
                        seen_signatures.add(relation_signature)
                        cards.append(relation_card)
                        emitted_cards += 1
            if not cards:
                card = fallback_document_card(segment, level, study_mode=study_mode)
                card["quality"] = document_card_quality(card, fallback=True)
                card["enabled"] = False
                cards = [card]
                emitted_cards += 1
        else:
            card = fallback_document_card(segment, level, study_mode=study_mode)
            card["quality"] = document_card_quality(card, fallback=True)
            card["enabled"] = False
            cards = [card]
            emitted_cards += 1
        if not cards:
            segment["cards"] = []
            continue
        card = cards[0]
        segment["phrase"] = card.get("phrase", segment.get("phrase", ""))
        segment["knowledge_type"] = card.get("knowledge_type", "")
        segment["document_card_kind"] = card.get("document_card_kind", "knowledge")
        segment["phrase_review_status"] = card["quality"]["status"]
        segment["phrase_card_focus"] = card.get("learning_target") or card.get("teacher_note", "")
        if card["quality"].get("issues"):
            segment["phrase_reject_reason"] = " / ".join(card["quality"]["issues"])
        else:
            segment["phrase_decision_reason"] = card.get("why_it_matters") or card.get("why", "")
        segment["cards"] = cards
    return segments, warning


def handle_generate_document(payload: dict[str, Any]) -> dict[str, Any]:
    timing_started = time.perf_counter()
    timing_ms: dict[str, int] = {}
    payload = {**payload, "language": normalize_learning_language(payload.get("language", "en"))}
    document_path = clean_input_path(payload.get("document_path"))
    if not document_path:
        fail("请先选择 TXT、Markdown、DOCX、EPUB 或 PDF 文档。")
    require_confirmed_local_path_access(payload, stage="document")

    source_started = time.perf_counter()
    emit_progress("generate", "document", 22, "正在读取文档。")
    text = read_document_source(document_path)
    level = payload.get("level", "B1")
    study_mode = normalized_document_study_mode(payload)
    collection_levels = collection_levels_from_payload(payload, level)
    max_segments = resolved_max_segments(payload, text=text)
    split_label = "文档精读点" if study_mode == "language_reading" else "文档知识点"
    emit_progress("generate", "document", 42, f"正在拆分{split_label}。")
    segments = split_document_chunks(text, min(max_segments, 36))
    if study_mode == "language_reading":
        for index, segment in enumerate(segments, 1):
            segment["source_time"] = f"文档精读点 {index}"
            title = segment.get("phrase") or f"精读点 {index}"
            segment["text"] = f"这段资料里值得精读的表达、词义或语法框架是什么：{title}"
    timing_ms["source_prepare"] = int((time.perf_counter() - source_started) * 1000)
    context_started = time.perf_counter()
    emit_progress("generate", "context", 54, "正在理解整份文档，建立制卡上下文。")
    material_context = call_material_context(payload, segments)
    payload = {**payload, "material_context": material_context, "study_depth": normalized_study_depth(payload)}
    timing_ms["context_model"] = int((time.perf_counter() - context_started) * 1000)
    context_warning = material_context.get("warning") if isinstance(material_context, dict) else None
    progress_label = "语言精读卡" if study_mode == "language_reading" else "文档知识卡"
    emit_progress("generate", "ai", 66, f"正在生成{progress_label}：{len(segments)} 个片段。")
    model_started = time.perf_counter()
    cache_disabled = bool(payload.get("disable_document_generation_cache") or (payload.get("api_config") or {}).get("disable_document_generation_cache"))
    ai_payload, document_cache_stats = cached_or_generated_document_payload(
        payload,
        segments,
        cache_disabled=cache_disabled,
    )
    timing_ms["card_model"] = int((time.perf_counter() - model_started) * 1000)
    emit_progress("generate", "cards", 86, "正在整理文档卡字段。")
    field_started = time.perf_counter()
    segments, warning = merge_document_cards(segments, ai_payload, level, study_mode=study_mode, max_cards=max_segments)
    document_candidate_count = len(segments)
    segments = apply_default_generated_card_selection(segments, payload)
    segments, output_filter_stats = filter_usable_segments_for_output(
        segments,
        [],
        block_export_drafts=False,
    )
    if context_warning:
        warning = f"{context_warning}；{warning}" if warning else str(context_warning)
    timing_ms["field_merge"] = int((time.perf_counter() - field_started) * 1000)

    title = payload.get("title") or Path(document_path).stem
    try:
        auto_segments = int(payload.get("max_segments", 0) or 0) <= 0
    except (TypeError, ValueError):
        auto_segments = True
    emit_progress("generate", "done", 100, f"文档制卡完成：{len(segments)} 个{split_label}。")
    quality_funnel = build_quality_funnel(
        segments,
        candidate_segments=document_candidate_count,
        reviewed_keep=len(segments),
        filter_stats=output_filter_stats,
        level_mode=normalized_level_mode(payload),
    )
    timing_ms["total"] = int((time.perf_counter() - timing_started) * 1000)
    generated_document_point_ids = [str(segment.get("id") or "") for segment in segments if segment.get("cards")]
    quality_funnel["generation_timing_ms"] = timing_ms
    quality_funnel["card_generation_cache_hits"] = int(document_cache_stats.get("cache_hits") or 0)
    quality_funnel["card_generation_cache_misses"] = int(document_cache_stats.get("cache_misses") or 0)
    return {
        "id": f"project_{int(time.time())}",
        "title": title,
        "video_path": "",
        "subtitle_path": "",
        "document_path": document_path,
        "language": payload.get("language", "en"),
        "level_mode": normalized_level_mode(payload),
        "level": level,
        "collection_levels": collection_levels,
        "template_id": payload.get("template_id", "immersive_v11"),
        "card_style": normalize_card_style(payload.get("card_style")),
        "content_toggles": payload.get("content_toggles", {}),
        "language_focus": normalized_document_reading_focus(payload) if study_mode == "language_reading" else normalized_language_focus(payload),
        "document_focus": normalized_document_focus(payload),
        "document_study_mode": study_mode,
        "document_answer_language": normalized_document_answer_language(payload),
        "document_depth": normalized_document_depth(payload),
        "document_answer_length": normalized_document_answer_length(payload),
        "study_depth": normalized_study_depth(payload),
        "material_context": material_context,
        "card_types": ["knowledge"],
        "max_segments": max_segments,
        "auto_max_segments": auto_segments,
        "quality_funnel": quality_funnel,
        "generated_document_point_ids": generated_document_point_ids,
        "source_fingerprint": stable_cache_key(
            {
                "source_mode": "document",
                "document_path": document_path,
                "title": title,
                "study_mode": study_mode,
            }
        ),
        "segments": segments,
        "warning": warning,
        "source_mode": "document",
        "source_url": "",
        "source_info": {
            "title": title,
            "document_path": document_path,
            "document_study_mode": study_mode,
        },
        "created_at": int(time.time()),
    }


def build_quality_funnel(
    segments: list[dict[str, Any]],
    subtitle_cues: int | None = None,
    candidate_segments: int | None = None,
    reviewed_keep: int | None = None,
    mimo_kept: int | None = None,
    max_learning_points: int | None = None,
    source_expansion_stats: dict[str, Any] | None = None,
    filter_stats: dict[str, int] | None = None,
    level_mode: str = "auto",
    learning_point_inventory: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    cards = [card for segment in segments for card in segment.get("cards", [])]
    source_groups: dict[str, list[dict[str, Any]]] = {}
    for segment in segments:
        source_groups.setdefault(learning_point_source_key(segment), []).append(segment)
    segment_learning_point_count = sum(
        len(segment.get("learning_points") or []) if isinstance(segment.get("learning_points"), list) else (1 if segment.get("cards") else 0)
        for segment in segments
    )
    inventory_counts = learning_point_inventory_stats(learning_point_inventory)
    inventory_learning_point_count = len(learning_point_inventory or [])
    learning_point_count = max(segment_learning_point_count, inventory_learning_point_count)
    selected_card_count = sum(1 for card in cards if card.get("enabled", True))
    recommended_cards = sum(1 for card in cards if (card.get("quality") or {}).get("status") == "recommended")
    review_cards = sum(1 for card in cards if (card.get("quality") or {}).get("status") == "needs_review")
    rejected_cards = sum(1 for card in cards if (card.get("quality") or {}).get("status") == "reject")
    usable_cards = recommended_cards + review_cards
    filter_stats = filter_stats or {}
    recommended_learning_points = {
        str(card.get("learning_point_id") or card.get("id") or "")
        for card in cards
        if (card.get("quality") or {}).get("status") == "recommended"
    }
    review_learning_points = {
        str(card.get("learning_point_id") or card.get("id") or "")
        for card in cards
        if (card.get("quality") or {}).get("status") == "needs_review"
    }
    rejected_learning_points = {
        str(card.get("learning_point_id") or card.get("id") or "")
        for card in cards
        if (card.get("quality") or {}).get("status") == "reject"
    }
    rejected_segments = sum(1 for segment in segments if segment.get("phrase_review_status") == "reject")
    duplicate_segments = sum(1 for segment in segments if segment.get("phrase_review_status") == "duplicate")
    learning_points_per_source_distribution: dict[str, int] = {}
    enabled_cards_per_source_distribution: dict[str, int] = {}
    for items in source_groups.values():
        lp_count = sum(
            len(item.get("learning_points") or []) if isinstance(item.get("learning_points"), list) else (1 if item.get("cards") else 0)
            for item in items
            if item.get("phrase_review_status") not in {"reject", "duplicate"}
        )
        enabled_count = sum(1 for item in items for card in item.get("cards", []) if card.get("enabled", True))
        learning_points_per_source_distribution[str(lp_count)] = learning_points_per_source_distribution.get(str(lp_count), 0) + 1
        enabled_cards_per_source_distribution[str(enabled_count)] = enabled_cards_per_source_distribution.get(str(enabled_count), 0) + 1
    scores = [
        phrase_review_score(segment.get("phrase_value_score"))
        for segment in segments
        if phrase_review_score(segment.get("phrase_value_score")) > 0
    ]
    average_score = round(sum(scores) / len(scores), 2) if scores else None
    if usable_cards < 5:
        if len(segments) < 6:
            short_reason = "字幕片段太少或有效候选不足。"
        elif usable_cards == 0:
            if filter_stats.get("filtered_learning_point_count", 0) > 0:
                short_reason = f"没有生成可导出卡，过滤了 {filter_stats.get('filtered_learning_point_count', 0)} 个低价值或重复学习点。"
            else:
                short_reason = "没有生成可导出卡，可能是词伙评分不足、模型返回空或素材可学习点较少。"
        else:
            short_reason = "可导出卡偏少，通常是重复合并、低价值表达或模型评审较严格。"
    else:
        short_reason = ""
    return {
        "subtitle_cues": subtitle_cues,
        "source_sentence_count": len(source_groups),
        "candidate_segments": candidate_segments if candidate_segments is not None else len(segments),
        "learning_point_count": learning_point_count,
        "recommended_learning_point_count": len([item for item in recommended_learning_points if item]),
        "review_learning_point_count": len([item for item in review_learning_points if item]),
        "rejected_learning_point_count": max(rejected_segments, len([item for item in rejected_learning_points if item])),
        "card_count": len(cards),
        "selected_card_count": selected_card_count,
        "usable_card_count": usable_cards,
        "filtered_learning_point_count": filter_stats.get("filtered_learning_point_count", 0),
        "low_value_filtered_count": filter_stats.get("low_value_filtered_count", 0),
        "blocked_quality_issue_count": filter_stats.get("blocked_quality_issue_count", 0),
        "candidate_only_learning_point_count": inventory_counts["candidate_only_learning_point_count"],
        "hidden_duplicate_learning_point_count": inventory_counts["hidden_duplicate_learning_point_count"],
        "hard_blocked_learning_point_count": inventory_counts["hard_blocked_learning_point_count"],
        "level_mode": level_mode,
        "recommended_card_count": recommended_cards,
        "review_card_count": review_cards,
        "duplicate_learning_point_count": max(duplicate_segments, filter_stats.get("duplicate_learning_point_count", 0)),
        "learning_points_per_source_distribution": learning_points_per_source_distribution,
        "enabled_cards_per_source_distribution": enabled_cards_per_source_distribution,
        "max_learning_points_per_source": max_learning_points,
        "source_expansion": source_expansion_stats or None,
        "reviewed_keep": reviewed_keep
        if reviewed_keep is not None
        else sum(1 for segment in segments if segment.get("phrase_review_status") not in {"reject", "duplicate"}),
        "mimo_kept": mimo_kept,
        "recommended_cards": recommended_cards,
        "review_cards": review_cards,
        "rejected_cards": rejected_cards,
        "rejected_segments": rejected_segments,
        "duplicate_segments": max(duplicate_segments, filter_stats.get("duplicate_learning_point_count", 0)),
        "average_phrase_score": average_score,
        "short_reason": short_reason,
    }


def handle_generate_batch(payload: dict[str, Any], source_mode: str) -> dict[str, Any]:
    raw_items = payload.get("batch_items") if isinstance(payload.get("batch_items"), list) else []
    items = [item for item in raw_items if isinstance(item, dict) and item.get("enabled") is not False]
    if not items:
        fail("批量模式下没有可生成的素材。请先添加文件夹、文档或多条链接。", error_code="BATCH_EMPTY", stage="source", retryable=False)

    parent_title = anki_deck_part(payload.get("title") or "批量学习包", "批量学习包")
    combined_segments: list[dict[str, Any]] = []
    combined_warnings: list[str] = []
    child_projects: list[dict[str, Any]] = []
    failed_items: list[dict[str, str]] = []
    total_items = len(items)
    emit_progress("generate", "batch", 8, f"开始批量生成：0/{total_items}。")

    for index, item in enumerate(items, start=1):
        item_source_mode = str(item.get("source_mode") or source_mode or payload.get("source_mode") or "local").strip().lower()
        item_id = str(item.get("id") or f"item-{index}").strip() or f"item-{index}"
        subdeck_title = anki_deck_part(item.get("subdeck_title") or item.get("title") or f"素材 {index}", f"素材 {index}")
        deck_name = anki_deck_name(item.get("deck_name") or f"{parent_title}::{subdeck_title}", parent_title)
        item_payload = {
            **payload,
            "batch_enabled": False,
            "batch_items": [],
            "title": subdeck_title,
            "source_mode": item_source_mode,
            "source_url": str(item.get("source_url") or "") if item_source_mode == "url" else "",
            "video_path": clean_input_path(item.get("video_path")) if item_source_mode == "local" else "",
            "subtitle_path": clean_input_path(item.get("subtitle_path")) if item_source_mode == "local" else "",
            "document_path": clean_input_path(item.get("document_path")) if item_source_mode == "document" else "",
            "allow_private_network_url": bool(
                item.get("allow_private_network_url")
                or payload.get("allow_private_network_url")
            ),
            "allow_ytdlp_remote_components": bool(
                item.get("allow_ytdlp_remote_components")
                or payload.get("allow_ytdlp_remote_components")
            ),
            "_batch_item_id": item_id,
            "_batch_subdeck_title": subdeck_title,
            "_batch_deck_name": deck_name,
        }
        if "local_path_access_confirmed" in item or "local_path_access_confirmed" in payload:
            item_payload["local_path_access_confirmed"] = bool(
                item.get("local_path_access_confirmed")
                or payload.get("local_path_access_confirmed")
            )
        if item_source_mode == "url" and not item_payload["source_url"]:
            failed_items.append({"id": item_id, "title": subdeck_title, "error": "缺少视频链接。"})
            continue
        if item_source_mode == "local" and not item_payload["video_path"]:
            failed_items.append({"id": item_id, "title": subdeck_title, "error": "缺少视频文件。"})
            continue
        if item_source_mode == "document" and not item_payload["document_path"]:
            failed_items.append({"id": item_id, "title": subdeck_title, "error": "缺少文档文件。"})
            continue
        emit_progress("generate", "batch", 8 + int((index - 1) / max(1, total_items) * 84), f"批量生成 {index}/{total_items}：{subdeck_title}")
        try:
            child_project = handle_generate_document(item_payload) if item_source_mode == "document" else handle_generate(item_payload)
        except SystemExit as err:
            failed_items.append({"id": item_id, "title": subdeck_title, "error": f"子任务失败：退出码 {err.code}"})
            continue
        child_projects.append(child_project)
        child_warning = str(child_project.get("warning") or "").strip()
        if child_warning:
            combined_warnings.append(f"{subdeck_title}：{child_warning}")
        for segment_index, segment in enumerate(child_project.get("segments") or [], start=1):
            if not isinstance(segment, dict):
                continue
            segment_id = f"{safe_filename(item_id)}_{segment.get('id') or segment_index}"
            next_segment = {
                **segment,
                "id": segment_id,
                "batch_item_id": item_id,
                "batch_subdeck_title": subdeck_title,
                "deck_name": deck_name,
                "video_path": child_project.get("video_path") or item_payload.get("video_path") or "",
                "subtitle_path": child_project.get("subtitle_path") or item_payload.get("subtitle_path") or "",
                "document_path": child_project.get("document_path") or item_payload.get("document_path") or "",
                "source_url": child_project.get("source_url") or item_payload.get("source_url") or "",
            }
            next_cards = []
            for card in segment.get("cards", []) or []:
                if not isinstance(card, dict):
                    continue
                next_cards.append(
                    {
                        **card,
                        "id": f"{safe_filename(item_id)}_{card.get('id') or len(next_cards) + 1}",
                        "batch_item_id": item_id,
                        "batch_subdeck_title": subdeck_title,
                        "deck_name": deck_name,
                    }
                )
            next_segment["cards"] = next_cards
            combined_segments.append(next_segment)

    if not combined_segments:
        detail = "；".join(f"{item.get('title')}: {item.get('error')}" for item in failed_items[:5])
        fail(f"批量生成没有产出可导出卡片。{detail}", error_code="BATCH_GENERATE_EMPTY", stage="batch", retryable=True)

    level = payload.get("level") or (child_projects[0].get("level") if child_projects else "B1")
    collection_levels = collection_levels_from_payload(payload, level)
    combined_segments = sorted(combined_segments, key=lambda item: (str(item.get("batch_item_id") or ""), float(item.get("start") or 0)))
    quality_funnel = build_quality_funnel(
        combined_segments,
        candidate_segments=sum(int((project.get("quality_funnel") or {}).get("candidate_segments") or len(project.get("segments") or [])) for project in child_projects),
        reviewed_keep=len(combined_segments),
        level_mode=normalized_level_mode(payload),
    )
    batch_items = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or f"item-{index}").strip() or f"item-{index}"
        subdeck_title = anki_deck_part(item.get("subdeck_title") or item.get("title") or f"素材 {index}", f"素材 {index}")
        batch_items.append(
            {
                **item,
                "id": item_id,
                "subdeck_title": subdeck_title,
                "title": item.get("title") or subdeck_title,
                "deck_name": anki_deck_name(item.get("deck_name") or f"{parent_title}::{subdeck_title}", parent_title),
                "status": "generated" if any(segment.get("batch_item_id") == item_id for segment in combined_segments) else "failed",
            }
        )
    warning = "；".join(combined_warnings)
    if failed_items:
        failed_summary = "；".join(f"{item['title']}：{item['error']}" for item in failed_items[:5])
        warning = f"{warning}；{failed_summary}" if warning else failed_summary
    emit_progress("generate", "done", 100, f"批量生成完成：{len(combined_segments)} 个片段，{quality_funnel.get('selected_card_count', 0)} 张可导出卡。")
    first_project = child_projects[0] if child_projects else {}
    return {
        "id": f"batch_project_{int(time.time())}",
        "title": parent_title,
        "batch_enabled": True,
        "batch_items": batch_items,
        "batch_summary": {
            "items": len(items),
            "generated_items": len({segment.get("batch_item_id") for segment in combined_segments}),
            "failed_items": len(failed_items),
        },
        "source_mode": source_mode or payload.get("source_mode") or "mixed",
        "source_url": "",
        "video_path": "" if len(child_projects) != 1 else child_projects[0].get("video_path", ""),
        "subtitle_path": "" if len(child_projects) != 1 else child_projects[0].get("subtitle_path", ""),
        "document_path": "" if len(child_projects) != 1 else child_projects[0].get("document_path", ""),
        "language": payload.get("language", "en"),
        "level_mode": normalized_level_mode(payload),
        "level": level,
        "collection_levels": collection_levels,
        "template_id": payload.get("template_id") or first_project.get("template_id") or "immersive_v11",
        "card_style": normalize_card_style(payload.get("card_style") or first_project.get("card_style")),
        "review_density": normalize_review_density(payload.get("review_density")),
        "content_toggles": payload.get("content_toggles", {}),
        "language_focus": normalized_document_reading_focus(payload) if source_mode == "document" and normalized_document_study_mode(payload) == "language_reading" else normalized_language_focus(payload),
        "document_focus": normalized_document_focus(payload),
        "document_study_mode": normalized_document_study_mode(payload),
        "document_answer_language": normalized_document_answer_language(payload),
        "document_depth": normalized_document_depth(payload),
        "document_answer_length": normalized_document_answer_length(payload),
        "study_depth": normalized_study_depth(payload),
        "selection_strategy": normalized_selection_strategy(payload),
        "card_types": payload.get("card_types") or first_project.get("card_types") or (["knowledge"] if source_mode == "document" else ["listening", "phrase", "cloze"]),
        "tts_semantic_verification": payload.get("tts_semantic_verification")
        or first_project.get("tts_semantic_verification")
        or {},
        "max_segments": payload.get("max_segments") or first_project.get("max_segments") or 0,
        "auto_max_segments": bool(payload.get("auto_max_segments") or first_project.get("auto_max_segments")),
        "skip_video_slicing": bool(payload.get("skip_video_slicing") or source_mode == "document"),
        "quality_funnel": quality_funnel,
        "learning_point_inventory": [],
        "segments": combined_segments,
        "warning": warning,
        "source_info": {
            "title": parent_title,
            "batch": True,
            "items": batch_items,
        },
        "created_at": int(time.time()),
    }


def handle_generate(payload: dict[str, Any]) -> dict[str, Any]:
    payload = {**payload, "language": normalize_learning_language(payload.get("language", "en"))}
    emit_progress("generate", "source", 5, "准备素材。")
    source_mode = str(payload.get("source_mode") or "").strip().lower()
    if not source_mode:
        source_mode = "url" if str(payload.get("source_url") or "").strip() else "local"
    if bool(payload.get("batch_enabled")) and isinstance(payload.get("batch_items"), list) and payload.get("batch_items"):
        return handle_generate_batch(payload, source_mode)
    if source_mode == "document":
        return handle_generate_document(payload)

    source_info = None
    if source_mode == "url":
        emit_progress("generate", "download", 12, "正在准备 URL 视频和字幕。")
        source_info = download_url_source(payload)
        source_message = "已复用 URL 缓存素材。" if source_info.get("cached") else "URL 素材下载完成。"
        if source_info.get("transcript_only"):
            source_message = (
                "已复用 URL 字幕缓存；当前任务未生成视频媒体。"
                if source_info.get("cached")
                else "URL 字幕已就绪；当前任务未生成视频媒体。"
            )
        emit_progress(
            "generate",
            "download",
            28,
            source_message,
        )
        skip_video_slicing = bool(source_info.get("skip_video_slicing")) or (
            bool(payload.get("skip_video_slicing")) and not url_video_mode_requested(payload)
        )
        payload = {
            **payload,
            "video_path": source_info.get("video_path", ""),
            "subtitle_path": source_info["subtitle_path"],
            "title": payload.get("title") or source_info.get("title") or "",
            "skip_video_slicing": skip_video_slicing,
        }

    video_path = clean_input_path(payload.get("video_path", ""))
    subtitle_path = clean_input_path(payload.get("subtitle_path", ""))
    if source_mode == "local":
        require_confirmed_local_path_access(payload, stage="source")
    subtitle_source = "manual" if subtitle_path and Path(subtitle_path).exists() else ""
    skip_video_slicing = bool(
        payload.get("skip_video_slicing")
        or (bool((source_info or {}).get("transcript_only")) and not bool(video_path))
    )
    if not skip_video_slicing and (not video_path or not Path(video_path).exists()):
        fail(f"视频文件不存在：{video_path}")
    if video_path and (not subtitle_path or not Path(subtitle_path).exists()):
        discovered_subtitle = discover_local_subtitle(video_path, payload.get("language", "English"))
        if discovered_subtitle:
            subtitle_path = str(discovered_subtitle)
            subtitle_source = "auto_matched"
    if video_path and (not subtitle_path or not Path(subtitle_path).exists()):
        emit_progress("generate", "subtitle", 30, "正在从视频内嵌字幕提取 SRT。")
        embedded_subtitle = extract_embedded_subtitle(video_path, payload.get("language", "English"))
        if embedded_subtitle:
            subtitle_path = str(embedded_subtitle)
            subtitle_source = "embedded"
    if not subtitle_path or not Path(subtitle_path).exists():
        fail(
            f"字幕文件不存在：{subtitle_path or '未选择'}。已尝试同目录 SRT/VTT 和视频内嵌文字字幕；请手动选择 SRT，或确认视频包含可提取的 SubRip/ASS/WebVTT 字幕。",
            error_code="LOCAL_SUBTITLE_MISSING",
            stage="subtitle",
            retryable=True,
        )
    emit_progress("generate", "subtitle", 34, "正在解析 SRT 字幕。")
    cues = parse_srt(subtitle_path)
    card_types = payload.get("card_types") or ["listening", "phrase", "cloze"]
    level = payload.get("level", "B1")
    collection_levels = collection_levels_from_payload(payload, level)
    max_segments = resolved_max_segments({**payload, "source_info": source_info or payload.get("source_info") or {}}, cues)
    auto_segments = True
    try:
        auto_segments = int(payload.get("max_segments", 0)) <= 0
    except (TypeError, ValueError):
        auto_segments = True
    payload = {**payload, "max_segments": max_segments, "auto_max_segments": auto_segments}

    review_enabled = phrase_review_available(payload)
    candidate_multiplier = selection_candidate_multiplier(payload)
    segment_payload = {
        **payload,
        "_candidate_limit": max(max_segments * candidate_multiplier, max_segments + 12 * candidate_multiplier),
    }
    emit_progress(
        "generate",
        "segments",
        48,
        f"正在按时间轴筛选候选片段：字幕 {len(cues)} 条，片段预算 {max_segments}，"
        f"{'准备 AI 学习候选评审。' if review_enabled else '使用本地评分。'}",
    )
    segments = build_segments(cues, segment_payload)
    candidate_segment_count = len(segments)
    if not segments:
        fail("没有筛选出合适片段。请检查 SRT，或放宽内容开关。")

    emit_progress("generate", "context", 54, "正在理解整段素材，建立制卡上下文。")
    material_context = call_material_context(payload, segments)
    payload = {**payload, "material_context": material_context, "study_depth": normalized_study_depth(payload)}
    context_warning = material_context.get("warning") if isinstance(material_context, dict) else None

    skipped_segments: list[dict[str, Any]] = []
    review_warning = None
    if review_enabled:
        emit_progress("generate", "learning_point_expansion", 56, f"AI 正在逐句补漏学习点：{len(segments)} 个候选。")
        segments, expansion_skipped, expansion_warning = expand_learning_points_by_source(payload, segments)
        candidate_segment_count = len(segments)
        if expansion_skipped:
            skipped_segments.extend(expansion_skipped)
        if expansion_warning:
            review_warning = expansion_warning
        emit_progress("generate", "phrase_review", 58, f"AI 正在评审学习候选：{len(segments)} 个片段。")
        reviewed_segments, skipped_segments, review_warning = review_phrase_candidates_with_mimo(payload, segments)
        if expansion_skipped:
            skipped_segments = [*skipped_segments, *expansion_skipped]
        if expansion_warning and expansion_warning not in (review_warning or ""):
            review_warning = f"{expansion_warning}；{review_warning}" if review_warning else expansion_warning
        review_applied = any(
            str(item.get("phrase_review_source") or "") in {"mimo", "ai"}
            for item in [*reviewed_segments, *skipped_segments]
        )
        if review_applied:
            segments = reviewed_segments
        else:
            segments = sorted(segments, key=lambda item: item["score"], reverse=True)[: max_segments * candidate_multiplier]
            segments = sorted(segments, key=lambda item: item["start"])
    else:
        segments = sorted(segments, key=lambda item: item["score"], reverse=True)[: max_segments * candidate_multiplier]
        segments = sorted(segments, key=lambda item: item["start"])

    segments = group_segments_by_learning_points(segments)

    emit_progress("generate", "ai", 66, f"正在分批生成词伙、解释和卡片字段：{len(segments)} 个片段组。")
    ai_payload = call_model_batches(payload, segments) if segments else None
    model_error_code = ai_payload.get("error_code") if isinstance(ai_payload, dict) else None
    model_stage = ai_payload.get("stage") if isinstance(ai_payload, dict) else None
    model_retryable = ai_payload.get("retryable") if isinstance(ai_payload, dict) else None
    emit_progress("generate", "cards", 84, "正在整理卡片草稿。")
    segments, warning = merge_ai_cards(segments, ai_payload, card_types, level, payload.get("language", "English")) if segments else ([], None)
    segments = enforce_reviewable_cards_per_source(segments, payload)
    segments = apply_default_generated_card_selection(segments, payload)
    reviewed_keep_count = len(segments)
    learning_point_inventory = build_learning_point_inventory(segments, skipped_segments)
    segments, output_filter_stats = filter_usable_segments_for_output(segments, skipped_segments)
    if context_warning:
        warning = f"{context_warning}；{warning}" if warning else str(context_warning)
    if review_warning:
        warning = f"{review_warning}；{warning}" if warning else review_warning
    segments = sorted(segments, key=lambda item: item["start"])

    project_id = f"project_{int(time.time())}"
    title = payload.get("title") or (Path(video_path).stem if video_path else (source_info or {}).get("title") or "字幕素材")
    source_warning = (source_info or {}).get("warning")
    source_notice = source_warning or ""
    if not source_info and subtitle_source in {"auto_matched", "embedded"}:
        subtitle_source_label = "自动匹配同目录字幕" if subtitle_source == "auto_matched" else "从视频内嵌字幕提取"
        source_notice = f"{subtitle_source_label}：{Path(subtitle_path).name}"
    quality_funnel = build_quality_funnel(
        segments,
        subtitle_cues=len(cues),
        candidate_segments=candidate_segment_count,
        reviewed_keep=reviewed_keep_count,
        mimo_kept=reviewed_keep_count if review_enabled else None,
        max_learning_points=max_learning_points_per_source(payload),
        source_expansion_stats=payload.get("_source_expansion_stats"),
        filter_stats=output_filter_stats,
        level_mode=normalized_level_mode(payload),
        learning_point_inventory=learning_point_inventory,
    )
    if ai_payload is None and (quality_funnel.get("recommended_cards", 0) > 0 or quality_funnel.get("review_cards", 0) > 0):
        recommended_count = int(quality_funnel.get("recommended_cards", 0) or 0)
        review_count = int(quality_funnel.get("review_cards", 0) or 0)
        usable_count = int(quality_funnel.get("usable_card_count", 0) or (recommended_count + review_count))
        if recommended_count:
            local_review_warning = (
                f"已解析 {len(cues)} 条字幕，生成 {usable_count} 张预览卡。"
                "正式抽取学习点和制卡请先配置并测试模型 API。"
            )
        else:
            local_review_warning = (
                f"已解析 {len(cues)} 条字幕，生成 {usable_count} 张预览卡。"
                "正式抽取学习点和制卡请先配置并测试模型 API。"
            )
        warning = (
            f"{warning}；{local_review_warning}"
            if warning and "模型没有返回可用精修结果" not in warning
            else local_review_warning
        )
    if source_notice and source_notice not in (warning or ""):
        warning = f"{source_notice}；{warning}" if warning else source_notice
    emit_progress("generate", "done", 100, f"生成完成：{quality_funnel.get('usable_card_count', 0)} 张可导出卡。")
    return {
        "id": project_id,
        "title": title,
        "video_path": video_path,
        "subtitle_path": subtitle_path,
        "language": payload.get("language", "en"),
        "level_mode": normalized_level_mode(payload),
        "level": level,
        "collection_levels": collection_levels,
        "template_id": payload.get("template_id", "immersive_v11"),
        "card_style": normalize_card_style(payload.get("card_style")),
        "content_toggles": payload.get("content_toggles", {}),
        "language_focus": normalized_language_focus(payload),
        "study_depth": normalized_study_depth(payload),
        "selection_strategy": normalized_selection_strategy(payload),
        "material_context": material_context,
        "card_types": card_types,
        "tts_semantic_verification": payload.get("tts_semantic_verification") or {},
        "max_segments": max_segments,
        "auto_max_segments": auto_segments,
        "skip_video_slicing": skip_video_slicing,
        "quality_funnel": quality_funnel,
        "learning_point_inventory": learning_point_inventory,
        "segments": segments,
        "warning": warning,
        "model_error_code": model_error_code,
        "model_stage": model_stage,
        "model_retryable": model_retryable,
        "source_mode": source_mode,
        "source_url": payload.get("source_url", "") if source_mode == "url" else "",
        "url_import_mode": payload.get("url_import_mode") or ("video" if source_mode == "url" else ""),
        "source_info": source_info
        or {
            "title": title,
            "video_path": video_path,
            "subtitle_path": subtitle_path,
            "subtitle_source": subtitle_source or "manual",
            "video_fingerprint": file_fingerprint(video_path),
            "subtitle_fingerprint": file_fingerprint(subtitle_path),
        },
        "created_at": int(time.time()),
    }


def run_ffmpeg(args: list[str]) -> None:
    try:
        completed = media_policy_run_ffmpeg(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **hidden_subprocess_flags(),
        )
    except MediaToolPolicyError as error:
        fail(
            f"FFmpeg 安全策略阻止了媒体处理：{error}",
            error_code=error.code,
            stage="media",
            retryable=error.code == "MANAGED_MEDIA_TOOL_MISSING",
            fallbacks=["skip_video_slicing"],
        )
    except subprocess.TimeoutExpired:
        fail(
            "FFmpeg 处理超过安全时限。",
            error_code="FFMPEG_TIMEOUT",
            stage="media",
            retryable=True,
            fallbacks=["skip_video_slicing"],
        )
    if completed.returncode != 0:
        fail(
            f"ffmpeg 处理失败：{completed.stderr[-1200:]}",
            error_code="FFMPEG_SLICE_FAILED",
            stage="media",
            retryable=True,
            fallbacks=["skip_video_slicing"],
        )


def try_run_ffmpeg(args: list[str]) -> str:
    try:
        completed = media_policy_run_ffmpeg(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **hidden_subprocess_flags(),
        )
    except MediaToolPolicyError as error:
        return f"FFmpeg 安全策略阻止了媒体处理（{error.code}）：{error}"
    except subprocess.TimeoutExpired:
        return "FFmpeg 处理超过安全时限。"
    if completed.returncode != 0:
        return completed.stderr[-900:] or f"ffmpeg 退出码 {completed.returncode}"
    return ""


CARD_CSS = """
.card {
  margin: 0;
  padding: 16px;
  color: #17211d;
  background: #f5f3ee;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans SC", sans-serif;
  line-height: 1.55;
}
.wrap {
  width: min(760px, 100%);
  margin: 0 auto;
}
.front-shell,
.back-shell {
  overflow: hidden;
  border: 1px solid #e3e1da;
  border-radius: 14px;
  background: #fffdfa;
  box-shadow: 0 10px 32px rgba(32, 38, 35, 0.10);
}
.media-frame {
  padding: 10px;
  background: #101613;
}
.media-frame video,
.mini-media video {
  display: block;
  width: 100%;
  aspect-ratio: 16 / 9;
  max-height: 320px;
  border-radius: 10px;
  background: #0b100e;
  object-fit: cover;
}
.mini-media video {
  max-height: 190px;
}
audio {
  display: block;
  width: 100%;
  height: 34px;
}
.front-panel,
.answer-panel {
  padding: 16px 18px 18px;
}
.meta-row,
.answer-meta,
.source {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  color: #66736d;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0;
  font-variant-numeric: tabular-nums;
}
.card-type {
  color: #0d3d30;
  font-size: 19px;
  font-weight: 800;
}
.task-box {
  margin-top: 12px;
  padding: 12px 14px;
  border: 1px solid #e3e7e1;
  border-radius: 10px;
  background: #fafbf8;
}
.task-box p {
  margin: 0;
  color: #50615a;
  font-size: 15px;
}
.label {
  display: block;
  margin-bottom: 5px;
  color: #617069;
  font-size: 11px;
  font-weight: 750;
  letter-spacing: 0;
}
.front-content {
  margin-top: 10px;
  color: #17211d;
  font-size: 20px;
  font-weight: 760;
  line-height: 1.45;
}
.audio-stack {
  display: grid;
  gap: 8px;
  margin-top: 12px;
}
.audio-row {
  display: grid;
  grid-template-columns: 72px 1fr;
  align-items: center;
  gap: 10px;
}
.audio-label {
  color: #66736d;
  font-size: 12px;
  font-weight: 750;
}
.back-hero {
  display: grid;
  grid-template-columns: 1fr 220px;
  gap: 16px;
  padding: 16px 18px;
  border-bottom: 1px solid #ece9e1;
}
.english {
  margin: 8px 0 0;
  color: #101915;
  font-size: 23px;
  font-weight: 820;
  line-height: 1.35;
}
.translation {
  margin-top: 8px;
  color: #2f3b36;
  font-size: 17px;
  font-weight: 650;
}
.answer-pill,
.phrase {
  display: inline-block;
  max-width: 100%;
  padding: 5px 10px;
  border-radius: 999px;
  background: #e5f2eb;
  color: #0b4c39;
  font-weight: 800;
}
.answer-pill {
  margin-top: 12px;
}
.teacher-note {
  margin-top: 12px;
  padding: 9px 11px;
  border: 1px solid #dce8e2;
  border-radius: 10px;
  background: #f5faf7;
  color: #31443c;
  font-size: 14px;
}
.focus-strip {
  display: grid;
  grid-template-columns: minmax(160px, 0.85fr) 1fr;
  gap: 12px;
  padding: 14px 18px;
  border-bottom: 1px solid #ece9e1;
}
.focus-main,
.focus-copy {
  min-width: 0;
}
.focus-copy {
  color: #3d4a45;
  font-size: 15px;
}
.focus-copy p {
  margin: 0 0 8px;
}
.detail-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px 14px;
  padding: 14px 18px 18px;
}
.detail {
  min-width: 0;
  padding-top: 10px;
  border-top: 1px solid #ecefe9;
}
.detail .value {
  color: #27342f;
  font-size: 14px;
}
.source {
  padding: 10px 18px 14px;
  border-top: 1px solid #ece9e1;
}
.compact-video-label {
  margin-bottom: 6px;
  color: #6b746f;
  font-size: 11px;
  font-weight: 750;
}
hr {
  display: none;
}
@media (max-width: 640px) {
  .card { padding: 10px; }
  .front-panel,
  .answer-panel,
  .back-hero,
  .focus-strip,
  .detail-grid,
  .source { padding-left: 14px; padding-right: 14px; }
  .back-hero,
  .focus-strip,
  .detail-grid { grid-template-columns: 1fr; }
  .audio-row { grid-template-columns: 1fr; gap: 4px; }
  .english { font-size: 20px; }
  .front-content { font-size: 18px; }
}
"""

FRONT_TEMPLATE = """
<div class="wrap">
  <section class="front-shell">
    <div class="media-frame">{{Video}}</div>
    <div class="front-panel">
      <div class="meta-row">
        <span class="card-type">{{CardType}}</span>
        <span>{{SourceTime}}</span>
      </div>
      <div class="task-box">
        <span class="label">正面任务</span>
        <p>{{FrontPrompt}}</p>
        {{#FrontContent}}<div class="front-content">{{FrontContent}}</div>{{/FrontContent}}
      </div>
      <div class="audio-stack">
        <div class="audio-row"><span class="audio-label">原声音频</span>{{Audio}}</div>
        {{#TtsAudio}}<div class="audio-row"><span class="audio-label">整句 AI 朗读</span>{{TtsAudio}}</div>{{/TtsAudio}}
      </div>
    </div>
  </section>
</div>
<script>
  setTimeout(function () {
    document.querySelectorAll("video,audio").forEach(function (node) {
      node.playbackRate = 0.75;
    });
  }, 60);
</script>
"""

BACK_TEMPLATE = """
<div class="wrap">
  <section class="back-shell">
    <div class="back-hero">
      <div class="answer-panel">
        <div class="answer-meta">
          <span class="card-type">{{CardType}}</span>
          <span>{{Difficulty}}</span>
        </div>
        <div class="english">{{English}}</div>
        <div class="translation">{{Chinese}}</div>
        <div class="answer-pill">{{Answer}}</div>
        <div class="teacher-note">{{TeacherNote}}</div>
      </div>
      <div class="mini-media">
        <div class="compact-video-label">复听视频</div>
        {{Video}}
      </div>
    </div>
    <div class="focus-strip">
      <div class="focus-main">
        <span class="label">重点词伙</span>
        <span class="phrase">{{Phrase}}</span>
      </div>
      <div class="focus-copy">
        <p><strong>释义：</strong>{{Definition}}</p>
        <p><strong>中文感：</strong>{{ChineseFeel}}</p>
      </div>
    </div>
    <div class="detail-grid">
      <div class="detail"><span class="label">搭配</span><div class="value">{{Collocations}}</div></div>
      <div class="detail"><span class="label">语境</span><div class="value">{{Context}}</div></div>
      <div class="detail"><span class="label">例句</span><div class="value">{{Example}}</div></div>
      <div class="detail"><span class="label">填空回忆</span><div class="value">{{Cloze}}</div></div>
      <div class="detail"><span class="label">为什么值得学</span><div class="value">{{Why}}</div></div>
      <div class="detail"><span class="label">来源时间轴</span><div class="value">{{SourceTime}}</div></div>
    </div>
  </section>
</div>
<script>
  setTimeout(function () {
    document.querySelectorAll("video,audio").forEach(function (node) {
      node.playbackRate = 0.75;
    });
  }, 60);
</script>
"""


DICTIONARY_FRONT_TEMPLATE = """
<div class="wrap dictionary-template">
  <section class="front-shell">
    <div class="media-frame compact-media">{{Video}}</div>
    <div class="compact-head">
      <strong>{{CardType}}</strong>
      <span>{{SourceTime}}</span>
    </div>
    <div class="task-box">
      <div class="label">正面任务</div>
      <p>{{FrontPrompt}}</p>
      {{#FrontContent}}<div class="front-content">{{FrontContent}}</div>{{/FrontContent}}
    </div>
    <div class="prompt compact-prompt">
      <div class="audio-stack">
        <div class="audio-row"><span class="audio-label">原声音频</span>{{Audio}}</div>
        {{#TtsAudio}}<div class="audio-row"><span class="audio-label">整句 AI 朗读</span>{{TtsAudio}}</div>{{/TtsAudio}}
      </div>
    </div>
  </section>
</div>
<script>
  setTimeout(function () {
    document.querySelectorAll("video,audio").forEach(function (node) {
      node.playbackRate = 0.75;
    });
  }, 60);
</script>
"""


DICTIONARY_BACK_TEMPLATE = """
<div class="wrap dictionary-template">
  <section class="back-shell dictionary-back">
    <div class="back-hero">
      <div class="answer-panel">
        <div class="answer-meta">
          <span class="card-type">{{CardType}}</span>
          <span>{{Difficulty}}</span>
        </div>
        <div class="english">{{English}}</div>
        <div class="translation">{{Chinese}}</div>
        <div class="teacher-note">{{TeacherNote}}</div>
      </div>
      <div class="mini-media">
        <div class="compact-video-label">复听视频</div>
        {{Video}}
      </div>
    </div>
    <div class="dictionary-grid">
      <div><span class="label">重点词伙</span><strong class="phrase">{{Phrase}}</strong></div>
      <div><span class="label">正面答案</span><p>{{Answer}}</p></div>
      <div><span class="label">释义</span><p>{{Definition}}</p></div>
      <div><span class="label">搭配</span><p>{{Collocations}}</p></div>
      <div><span class="label">语境</span><p>{{Context}}</p></div>
      <div><span class="label">例句</span><p>{{Example}}</p></div>
      <div><span class="label">中文感</span><p>{{ChineseFeel}}</p></div>
      <div><span class="label">填空回忆</span><p>{{Cloze}}</p></div>
      <div><span class="label">为什么值得学</span><p>{{Why}}</p></div>
      <div><span class="label">来源时间轴</span><p>{{SourceTime}}</p></div>
    </div>
  </section>
</div>
<script>
  setTimeout(function () {
    document.querySelectorAll("video,audio").forEach(function (node) {
      node.playbackRate = 0.75;
    });
  }, 60);
</script>
"""


MINIMAL_FRONT_TEMPLATE = """
<div class="wrap minimal-template">
  <section class="front-shell">
    <div class="media-frame minimal-media">{{Video}}</div>
    <div class="prompt minimal-prompt">
      <strong>{{CardType}}</strong>
      <span>{{FrontPrompt}}</span>
      {{#FrontContent}}<div class="front-content">{{FrontContent}}</div>{{/FrontContent}}
      {{Audio}}
    </div>
  </section>
</div>
<script>
  setTimeout(function () {
    document.querySelectorAll("video,audio").forEach(function (node) {
      node.playbackRate = 0.75;
    });
  }, 60);
</script>
"""


MINIMAL_BACK_TEMPLATE = """
<div class="wrap minimal-template">
  <section class="back-shell minimal-back">
    <div class="mini-media minimal-answer-media">{{Video}}</div>
    <div class="section">
      <div class="answer-meta"><span class="card-type">{{CardType}}</span><span>{{SourceTime}}</span></div>
      <div class="english">{{English}}</div>
      <div class="translation">{{Chinese}}</div>
      <div class="minimal-row"><strong>{{Phrase}}</strong><span>{{Difficulty}}</span></div>
      <div class="answer-pill">{{Answer}}</div>
      <p>{{ChineseFeel}}</p>
      <p>{{TeacherNote}}</p>
      <small>{{Cloze}}</small>
    </div>
  </section>
</div>
<script>
  setTimeout(function () {
    document.querySelectorAll("video,audio").forEach(function (node) {
      node.playbackRate = 0.75;
    });
  }, 60);
</script>
"""


CARD_CSS = """
.card {
  margin: 0;
  padding: 18px;
  display: block;
  background:
    radial-gradient(circle at 18% 0%, rgba(255,255,255,0.94), rgba(255,255,255,0) 32%),
    linear-gradient(145deg, #f6f1e8 0%, #eef2ee 52%, #f8f5ef 100%);
  color: #111817;
  font-family: Inter, "SF Pro Display", "Segoe UI", "Helvetica Neue", Arial, sans-serif;
  line-height: 1.55;
  letter-spacing: 0;
  text-align: left;
  overflow-x: hidden;
}
* {
  box-sizing: border-box;
}
html,
body,
#qa {
  width: 100% !important;
  max-width: none !important;
  margin: 0 !important;
}
.wrap {
  width: min(1080px, calc(100vw - 32px));
  margin: 0 auto;
  font-family: Inter, "SF Pro Display", "Segoe UI", "Helvetica Neue", Arial, sans-serif;
  --ink: #101817;
  --muted: #60706a;
  --soft: #eef5f1;
  --surface: #fffdf8;
  --line: rgba(25, 42, 37, 0.12);
  --accent: #0d6b52;
  --accent-deep: #074734;
  --accent-soft: #e8f5ef;
  --gold: #b7832d;
  --blue: #355f78;
}
.dictionary-template {
  --accent: #7b4f16;
  --accent-deep: #4e310d;
  --accent-soft: #f5ebda;
  --gold: #236478;
  --blue: #236478;
}
.minimal-template {
  --accent: #263b35;
  --accent-deep: #121d1a;
  --accent-soft: #edf1ef;
  --gold: #63716b;
  --blue: #4d6674;
}
.study-card {
  overflow: hidden;
  border: 1px solid rgba(16, 24, 23, 0.12);
  border-radius: 22px;
  background: var(--surface);
  box-shadow: 0 30px 90px rgba(24, 31, 28, 0.16);
}
.cinema {
  position: relative;
  padding: 12px;
  background:
    radial-gradient(circle at 20% 0%, rgba(255,255,255,0.16), rgba(255,255,255,0) 30%),
    linear-gradient(135deg, #0a1210 0%, #16241e 52%, #070908 100%);
}
.cinema video {
  display: block;
  width: 100%;
  max-height: 520px;
  aspect-ratio: 16 / 9;
  object-fit: cover;
  border-radius: 12px;
  background: #050706;
  box-shadow: inset 0 0 0 1px rgba(255,255,255,0.08);
}
.media-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 10px;
  color: rgba(255,255,255,0.84);
  font-size: 12px;
  font-weight: 760;
}
.type-pill,
.time-pill,
.micro-pill {
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  padding: 5px 10px;
  border-radius: 999px;
  border: 1px solid rgba(255,255,255,0.18);
  background: rgba(255,255,255,0.1);
  backdrop-filter: blur(10px);
}
.time-pill {
  color: rgba(255,255,255,0.72);
}
.front-body {
  display: grid;
  gap: 16px;
  padding: 20px 24px 22px;
}
.mission {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 18px;
  align-items: end;
}
.mission-kicker {
  margin: 0 0 6px;
  color: var(--accent);
  font-size: 13px;
  font-weight: 820;
}
.mission-title {
  margin: 0;
  color: var(--ink);
  font-size: 26px;
  line-height: 1.24;
  font-weight: 860;
}
.mission-note {
  max-width: 300px;
  color: var(--muted);
  font-size: 14px;
  text-align: right;
}
.front-content {
  margin: 0;
  padding: 12px 14px;
  border-left: 4px solid var(--gold);
  border-radius: 8px;
  background: #fbf6eb;
  color: #514739;
  font-size: 16px;
  font-weight: 660;
}
.sound-panel {
  display: grid;
  gap: 11px;
  padding: 15px 18px 17px;
  border-top: 1px solid var(--line);
  background: linear-gradient(180deg, #fbfdfb 0%, #f3f7f4 100%);
}
.sound-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  color: var(--muted);
  font-size: 12px;
  font-weight: 800;
}
.sound-title strong {
  color: var(--ink);
  font-size: 14px;
}
.audio-stack {
  display: grid;
  gap: 10px;
}
.audio-row {
  display: grid;
  grid-template-columns: 96px minmax(0, 1fr);
  gap: 12px;
  align-items: center;
}
.audio-row span {
  color: var(--muted);
  font-size: 12px;
  font-weight: 780;
}
audio {
  width: 100%;
  min-height: 38px;
  color-scheme: light;
}
audio[data-role="phrase-tts"],
.phrase-audio audio {
  width: 1px;
  min-height: 1px;
}
.back-card {
  background: #fffdf8;
}
@media (min-width: 860px) {
  .back-card {
    display: grid;
    grid-template-columns: minmax(290px, 0.72fr) minmax(0, 1fr);
    align-items: stretch;
  }
  .back-card .replay-panel {
    grid-column: 1;
    grid-row: 1 / span 3;
    align-self: stretch;
    border-top: 0;
    border-right: 1px solid var(--line);
  }
  .back-card .answer-hero,
  .back-card .sentence-panel,
  .back-card .detail-grid {
    grid-column: 2;
  }
}
.answer-hero {
  padding: 25px 27px 23px;
  background:
    radial-gradient(circle at 100% 0%, rgba(183, 131, 45, 0.16), rgba(183, 131, 45, 0) 34%),
    linear-gradient(135deg, #fffdf8 0%, var(--accent-soft) 100%);
  border-bottom: 1px solid var(--line);
}
.hero-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 12px;
  color: var(--muted);
  font-size: 12px;
  font-weight: 820;
}
.hero-phrase {
  margin: 0;
  color: var(--accent-deep);
  font-size: 34px;
  line-height: 1.15;
  font-weight: 900;
}
.hero-meaning {
  margin-top: 10px;
  color: #26322f;
  font-size: 21px;
  font-weight: 780;
}
.translation {
  margin-top: 8px;
  color: #5f4b25;
  font-size: 17px;
  font-weight: 680;
}
.teacher-note {
  margin-top: 16px;
  padding: 13px 15px;
  border: 1px solid rgba(13, 107, 82, 0.17);
  border-radius: 10px;
  background: rgba(255,255,255,0.74);
  color: #24332e;
  font-size: 15px;
}
.answer-key {
  display: grid;
  gap: 5px;
  margin-top: 15px;
  padding: 13px 15px;
  border-radius: 12px;
  background: rgba(7, 71, 52, 0.08);
  border: 1px solid rgba(7, 71, 52, 0.14);
}
.answer-key span {
  color: var(--muted);
  font-size: 12px;
  font-weight: 820;
}
.answer-key strong {
  color: var(--accent-deep);
  font-size: 19px;
  line-height: 1.35;
}
.sentence-panel {
  padding: 21px 27px 8px;
}
.section-label {
  display: block;
  margin-bottom: 7px;
  color: var(--muted);
  font-size: 12px;
  font-weight: 820;
}
.english {
  color: #101817;
  font-size: 25px;
  line-height: 1.35;
  font-weight: 850;
}
.detail-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  padding: 17px 27px 24px;
}
.detail {
  min-height: 98px;
  padding: 13px 14px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: #fffaf1;
}
.detail.wide {
  grid-column: 1 / -1;
  background: #f8fbf9;
}
.detail strong {
  display: block;
  margin-bottom: 6px;
  color: var(--accent-deep);
  font-size: 13px;
}
.detail p {
  margin: 0;
  color: #25322e;
  font-size: 15px;
}
.replay-panel {
  display: grid;
  grid-template-columns: minmax(210px, 300px) minmax(0, 1fr);
  gap: 16px;
  align-items: center;
  padding: 17px 18px 18px;
  border-top: 1px solid var(--line);
  background: #f4f6f2;
}
.replay-media {
  padding: 7px;
  border-radius: 12px;
  background: #101614;
}
.replay-media video {
  display: block;
  width: 100%;
  max-height: 220px;
  aspect-ratio: 16 / 9;
  object-fit: cover;
  border-radius: 8px;
  background: #050706;
}
@media (min-width: 860px) {
  .replay-panel {
    grid-template-columns: 1fr;
    align-content: start;
    gap: 18px;
    padding: 18px;
    background:
      linear-gradient(180deg, #0b1512 0%, #15211d 52%, #f4f6f2 52%, #f4f6f2 100%);
  }
  .replay-media {
    background: #050706;
    box-shadow: 0 18px 45px rgba(4, 8, 7, 0.24);
  }
  .replay-media video {
    max-height: none;
  }
}
.meta-line {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 13px;
}
.meta-chip {
  padding: 6px 9px;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: #fffdf8;
  color: var(--muted);
  font-size: 12px;
  font-weight: 760;
}
.minimal-template .study-card {
  box-shadow: 0 14px 42px rgba(29, 37, 34, 0.09);
}
.minimal-template .cinema video {
  max-height: 300px;
}
.minimal-template .answer-hero {
  padding: 22px 24px 19px;
  background: #fffdf8;
}
.minimal-template .detail-grid {
  grid-template-columns: 1fr;
}
.dictionary-template .detail {
  background: #fff7e8;
}
.dictionary-template .detail.wide {
  background: #f5fbfb;
}
@media (max-width: 650px) {
  .card {
    padding: 10px;
  }
  .study-card {
    border-radius: 14px;
  }
  .mission {
    grid-template-columns: 1fr;
  }
  .mission-note {
    max-width: none;
    text-align: left;
  }
  .mission-title {
    font-size: 22px;
  }
  .hero-phrase {
    font-size: 28px;
  }
  .english {
    font-size: 21px;
  }
  .detail-grid,
  .replay-panel {
    grid-template-columns: 1fr;
  }
  .audio-row {
    grid-template-columns: 1fr;
    gap: 5px;
  }
}
"""


FRONT_TEMPLATE = """
<div class="wrap immersive-template">
  <section class="study-card front-card">
    <div class="cinema">
      <div class="media-topbar">
        <span class="type-pill">{{CardType}}</span>
        <span class="time-pill">{{SourceTime}}</span>
      </div>
      {{Video}}
    </div>
    <div class="front-body">
      <div class="mission">
        <div>
          <p class="mission-kicker">先听，不看字幕</p>
          <h1 class="mission-title">{{FrontPrompt}}</h1>
        </div>
        <div class="mission-note">0.75 倍慢放、循环播放，翻面后再看原句和解释。</div>
      </div>
      {{#FrontContent}}<p class="front-content">{{FrontContent}}</p>{{/FrontContent}}
    </div>
    <div class="sound-panel">
      <div class="sound-title"><strong>声音轨道</strong><span>{{#TtsAudio}}原声 / 整句 AI 朗读{{/TtsAudio}}{{^TtsAudio}}循环慢放{{/TtsAudio}}</span></div>
      <div class="audio-stack">
        <div class="audio-row"><span>原声音频</span>{{Audio}}</div>
        {{#TtsAudio}}<div class="audio-row"><span>整句 AI 朗读</span>{{TtsAudio}}</div>{{/TtsAudio}}
      </div>
    </div>
  </section>
</div>
<script>
  setTimeout(function () {
    document.querySelectorAll("video,audio").forEach(function (node) {
      node.playbackRate = 0.75;
      node.loop = true;
    });
  }, 60);
</script>
"""


BACK_TEMPLATE = """
<div class="wrap immersive-template">
  <section class="study-card back-card">
    <div class="answer-hero">
      <div class="hero-meta">
        <span>{{CardType}}</span>
        <span>{{Difficulty}} · {{SourceTime}}</span>
      </div>
      <h1 class="hero-phrase">{{Phrase}}</h1>
      <div class="hero-meaning">{{ChineseFeel}}</div>
      <div class="translation">{{Chinese}}</div>
      {{#Answer}}<div class="answer-key"><span>这张卡真正要回忆的答案</span><strong>{{Answer}}</strong></div>{{/Answer}}
      <div class="teacher-note">{{TeacherNote}}</div>
    </div>

    <div class="sentence-panel">
      <span class="section-label">英文原句</span>
      <div class="english">{{English}}</div>
      {{#Cloze}}<div class="meta-line"><span class="meta-chip">填空：{{Cloze}}</span></div>{{/Cloze}}
    </div>

    <div class="detail-grid">
      <div class="detail"><strong>释义</strong><p>{{Definition}}</p></div>
      <div class="detail"><strong>搭配</strong><p>{{Collocations}}</p></div>
      <div class="detail"><strong>语境</strong><p>{{Context}}</p></div>
      <div class="detail"><strong>例句</strong><p>{{Example}}</p></div>
      <div class="detail wide"><strong>为什么值得学</strong><p>{{Why}}</p></div>
    </div>

    <div class="replay-panel">
      <div class="replay-media">{{Video}}</div>
      <div class="audio-stack">
        <div class="sound-title"><strong>回放</strong><span>{{Phrase}}</span></div>
        <div class="audio-row"><span>原声音频</span>{{Audio}}</div>
        {{#TtsAudio}}<div class="audio-row"><span>整句 AI 朗读</span>{{TtsAudio}}</div>{{/TtsAudio}}
      </div>
    </div>
  </section>
</div>
<script>
  setTimeout(function () {
    document.querySelectorAll("video,audio").forEach(function (node) {
      node.playbackRate = 0.75;
      node.loop = true;
    });
  }, 60);
</script>
"""


DICTIONARY_FRONT_TEMPLATE = FRONT_TEMPLATE.replace("immersive-template", "dictionary-template")
DICTIONARY_BACK_TEMPLATE = BACK_TEMPLATE.replace("immersive-template", "dictionary-template")
MINIMAL_FRONT_TEMPLATE = FRONT_TEMPLATE.replace("immersive-template", "minimal-template")
MINIMAL_BACK_TEMPLATE = BACK_TEMPLATE.replace("immersive-template", "minimal-template")


CARD_CSS = """
.card {
  margin: 0;
  padding: 18px;
  background:
    radial-gradient(circle at 20% 0%, rgba(255, 255, 255, 0.95), rgba(255, 255, 255, 0) 30%),
    linear-gradient(145deg, #f5f0e7 0%, #eef3ee 54%, #fbf8f1 100%);
  color: #101817;
  font-family: Inter, "SF Pro Display", "Segoe UI", "Noto Sans SC", Arial, sans-serif;
  line-height: 1.55;
  text-align: left;
  letter-spacing: 0;
}
* { box-sizing: border-box; }
html, body, #qa {
  width: 100% !important;
  max-width: none !important;
  margin: 0 !important;
}
.wrap {
  width: min(980px, calc(100vw - 32px));
  margin: 0 auto;
  --ink: #101817;
  --muted: #63706a;
  --line: rgba(25, 42, 37, 0.12);
  --surface: #fffdf8;
  --surface-2: #f7faf6;
  --accent: #0d6b52;
  --accent-deep: #063f2f;
  --accent-soft: #e8f5ef;
  --gold: #a97626;
}
.study-card {
  overflow: hidden;
  border: 1px solid rgba(16, 24, 23, 0.12);
  border-radius: 18px;
  background: var(--surface);
  box-shadow: 0 22px 70px rgba(25, 32, 29, 0.14);
}
.front-media {
  position: relative;
  padding: 12px;
  background: linear-gradient(135deg, #08100e 0%, #17241f 58%, #080b0a 100%);
}
.front-media video,
.replay-media video {
  display: block;
  width: 100%;
  aspect-ratio: 16 / 9;
  max-height: 500px;
  object-fit: cover;
  border-radius: 12px;
  background: #050706;
}
.no-media {
  display: grid;
  min-height: 220px;
  place-items: center;
  padding: 28px;
  border: 1px dashed rgba(255, 255, 255, 0.24);
  border-radius: 12px;
  color: rgba(255, 255, 255, 0.82);
  text-align: center;
}
.media-bar,
.hero-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  color: rgba(255, 255, 255, 0.78);
  font-size: 12px;
  font-weight: 780;
}
.media-bar {
  margin-bottom: 10px;
}
.pill {
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  padding: 5px 10px;
  border: 1px solid rgba(255, 255, 255, 0.16);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.10);
}
.front-task {
  display: grid;
  gap: 12px;
  padding: 20px 24px 22px;
}
.task-kicker,
.section-label {
  margin: 0;
  color: var(--accent);
  font-size: 12px;
  font-weight: 860;
}
.task-title {
  margin: 0;
  color: var(--ink);
  font-size: 26px;
  line-height: 1.25;
  font-weight: 880;
}
.front-content {
  margin: 0;
  padding: 12px 14px;
  border-left: 4px solid var(--gold);
  border-radius: 8px;
  background: #fbf5e9;
  color: #504737;
  font-size: 15px;
  font-weight: 680;
}
.audio-panel {
  display: grid;
  gap: 10px;
  padding: 14px 18px 18px;
  border-top: 1px solid var(--line);
  background: linear-gradient(180deg, #fbfdfb 0%, #f3f7f4 100%);
}
.audio-title {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  color: var(--muted);
  font-size: 12px;
  font-weight: 800;
}
.audio-row {
  display: grid;
  grid-template-columns: 92px minmax(0, 1fr);
  gap: 12px;
  align-items: center;
}
.audio-row span {
  color: var(--muted);
  font-size: 12px;
  font-weight: 780;
}
audio {
  width: 100%;
  min-height: 38px;
  color-scheme: light;
}
.back-card {
  background: #fffdf8;
}
.answer-hero {
  padding: 24px 28px 22px;
  border-bottom: 1px solid var(--line);
  background:
    radial-gradient(circle at 100% 0%, rgba(169, 118, 38, 0.16), rgba(169, 118, 38, 0) 34%),
    linear-gradient(135deg, #fffdf8 0%, var(--accent-soft) 100%);
}
.answer-hero .hero-meta {
  margin-bottom: 12px;
  color: var(--muted);
}
.hero-phrase {
  margin: 0;
  color: var(--accent-deep);
  font-size: 35px;
  line-height: 1.14;
  font-weight: 900;
}
.hero-meaning {
  margin-top: 9px;
  color: #26322f;
  font-size: 20px;
  font-weight: 780;
}
.translation {
  margin-top: 8px;
  color: #5d4b28;
  font-size: 17px;
  font-weight: 700;
}
.answer-key,
.teacher-note {
  margin-top: 14px;
  padding: 12px 14px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.72);
}
.answer-key {
  display: grid;
  gap: 4px;
  border: 1px solid rgba(13, 107, 82, 0.18);
}
.answer-key span,
.detail strong {
  color: var(--muted);
  font-size: 12px;
  font-weight: 840;
}
.answer-key strong {
  color: var(--accent-deep);
  font-size: 19px;
  line-height: 1.35;
}
.teacher-note {
  border: 1px solid rgba(13, 107, 82, 0.14);
  color: #24332e;
  font-size: 15px;
}
.sentence-panel {
  padding: 20px 28px 8px;
}
.english {
  margin-top: 6px;
  color: #101817;
  font-size: 24px;
  line-height: 1.36;
  font-weight: 850;
}
.detail-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  padding: 16px 28px 24px;
}
.detail {
  min-height: 96px;
  padding: 13px 14px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: #fffaf1;
}
.detail.wide {
  grid-column: 1 / -1;
  background: #f8fbf9;
}
.detail p {
  margin: 6px 0 0;
  color: #25322e;
  font-size: 15px;
}
.replay-panel {
  display: grid;
  grid-template-columns: minmax(220px, 330px) minmax(0, 1fr);
  gap: 16px;
  align-items: center;
  padding: 16px 18px 18px;
  border-top: 1px solid var(--line);
  background: #f3f6f2;
}
.replay-media {
  padding: 8px;
  border-radius: 12px;
  background: #101614;
}
.meta-line {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}
.meta-chip {
  padding: 6px 9px;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: #fffdf8;
  color: var(--muted);
  font-size: 12px;
  font-weight: 760;
}
@media (min-width: 860px) {
  .back-card.has-media {
    display: grid;
    grid-template-columns: minmax(285px, 0.72fr) minmax(0, 1fr);
  }
  .back-card.has-media .replay-panel {
    grid-column: 1;
    grid-row: 1 / span 3;
    grid-template-columns: 1fr;
    align-content: start;
    border-top: 0;
    border-right: 1px solid var(--line);
    background:
      linear-gradient(180deg, #0b1512 0%, #15211d 46%, #f3f6f2 46%, #f3f6f2 100%);
  }
  .back-card.has-media .answer-hero,
  .back-card.has-media .sentence-panel,
  .back-card.has-media .detail-grid {
    grid-column: 2;
  }
}
@media (max-width: 650px) {
  .card { padding: 10px; }
  .study-card { border-radius: 14px; }
  .task-title { font-size: 22px; }
  .hero-phrase { font-size: 28px; }
  .english { font-size: 20px; }
  .audio-row,
  .replay-panel,
  .detail-grid {
    grid-template-columns: 1fr;
  }
}
"""


FRONT_TEMPLATE = """
<div class="wrap immersive-template">
  <section class="study-card front-card">
    <div class="front-media">
      <div class="media-bar">
        <span class="pill">{{CardType}}</span>
        <span class="pill">{{SourceTime}}</span>
      </div>
      {{#Video}}{{Video}}{{/Video}}
      {{^Video}}<div class="no-media"><strong>知识卡</strong><span>先回答问题，翻面后核对答案。</span></div>{{/Video}}
    </div>
    <div class="front-task">
      <p class="task-kicker">{{#Video}}先听，不看字幕{{/Video}}{{^Video}}主动回忆{{/Video}}</p>
      <h1 class="task-title">{{FrontPrompt}}</h1>
      {{#FrontContent}}<p class="front-content">{{FrontContent}}</p>{{/FrontContent}}
    </div>
    {{#Audio}}<div class="audio-panel">
      <div class="audio-title"><strong>声音轨道</strong><span>0.75x 慢放 / 循环</span></div>
      <div class="audio-row"><span>原声音频</span>{{Audio}}</div>
      {{#TtsAudio}}<div class="audio-row"><span>整句 AI 朗读</span>{{TtsAudio}}</div>{{/TtsAudio}}
    </div>{{/Audio}}
  </section>
</div>
<script>
  setTimeout(function () {
    document.querySelectorAll("video,audio").forEach(function (node) {
      node.playbackRate = 0.75;
      node.loop = true;
    });
  }, 60);
</script>
"""


BACK_TEMPLATE = """
<div class="wrap immersive-template">
  <section class="study-card back-card {{#Video}}has-media{{/Video}}">
    {{#Video}}<div class="replay-panel">
      <div class="replay-media">{{Video}}</div>
      <div>
        <div class="audio-title"><strong>回放</strong><span>{{SourceTime}}</span></div>
        {{#Audio}}<div class="audio-row"><span>原声音频</span>{{Audio}}</div>{{/Audio}}
        {{#TtsAudio}}<div class="audio-row"><span>整句 AI 朗读</span>{{TtsAudio}}</div>{{/TtsAudio}}
      </div>
    </div>{{/Video}}

    <div class="answer-hero">
      <div class="hero-meta">
        <span>{{CardType}}</span>
        <span>{{Difficulty}} · {{SourceTime}}</span>
      </div>
      <h1 class="hero-phrase">{{Phrase}}</h1>
      <div class="hero-meaning">{{ChineseFeel}}</div>
      <div class="translation">{{Chinese}}</div>
      {{#Answer}}<div class="answer-key"><span>这张卡真正要回忆的答案</span><strong>{{Answer}}</strong></div>{{/Answer}}
      <div class="teacher-note">{{TeacherNote}}</div>
    </div>

    <div class="sentence-panel">
      <span class="section-label">{{#Video}}英文原句{{/Video}}{{^Video}}正面问题{{/Video}}</span>
      <div class="english">{{English}}</div>
      {{#Cloze}}<div class="meta-line"><span class="meta-chip">填空：{{Cloze}}</span></div>{{/Cloze}}
    </div>

    <div class="detail-grid">
      <div class="detail"><strong>释义 / 概念</strong><p>{{Definition}}</p></div>
      <div class="detail"><strong>搭配 / 相关概念</strong><p>{{Collocations}}</p></div>
      <div class="detail"><strong>语境</strong><p>{{Context}}</p></div>
      <div class="detail"><strong>例句</strong><p>{{Example}}</p></div>
      <div class="detail wide"><strong>为什么值得学</strong><p>{{Why}}</p></div>
    </div>
  </section>
</div>
<script>
  setTimeout(function () {
    document.querySelectorAll("video,audio").forEach(function (node) {
      node.playbackRate = 0.75;
      node.loop = true;
    });
  }, 60);
</script>
"""


DICTIONARY_FRONT_TEMPLATE = FRONT_TEMPLATE
DICTIONARY_BACK_TEMPLATE = BACK_TEMPLATE
MINIMAL_FRONT_TEMPLATE = FRONT_TEMPLATE
MINIMAL_BACK_TEMPLATE = BACK_TEMPLATE


# V10 keeps the existing fields, but moves the visual language to a lighter
# Apple-style study card with adaptive height, quieter borders, and blue emphasis.
CARD_CSS = """
.card {
  margin: 0;
  min-height: 0;
  padding: clamp(10px, 1.4vh, 18px);
  background: #f5f5f7;
  color: #1d1d1f;
  font-family: "SF Pro Display", "SF Pro Text", Inter, "Segoe UI", "Noto Sans SC", Arial, sans-serif;
  line-height: 1.42;
  text-align: left;
  letter-spacing: 0;
  overflow: hidden;
  display: flex;
  justify-content: center;
  align-items: flex-start;
}
* { box-sizing: border-box; }
[data-fit] {
  min-width: 0;
  max-width: 100%;
}
* {
  scrollbar-width: none;
  -ms-overflow-style: none;
}
*::-webkit-scrollbar {
  width: 0 !important;
  height: 0 !important;
  display: none !important;
}
html, body, #qa {
  width: 100% !important;
  min-height: 100% !important;
  height: 100% !important;
  max-width: none !important;
  margin: 0 !important;
  overflow: hidden !important;
}
.wrap {
  width: min(1360px, calc(100vw - clamp(24px, 4vw, 88px)));
  max-width: calc(100vw - 20px);
  height: min(1500px, 91vh);
  min-height: min(720px, 91vh);
  margin: 0 auto;
  display: grid;
  min-width: 0;
  --ink: #1d1d1f;
  --muted: #6e6e73;
  --line: rgba(60, 60, 67, 0.14);
  --paper: #ffffff;
  --soft: #f5f5f7;
  --blue: #007aff;
  --blue-deep: #0057d8;
  --blue-soft: rgba(0, 122, 255, 0.10);
  --green: var(--blue);
  --green-deep: var(--blue-deep);
  --green-soft: var(--blue-soft);
  --amber: #ff9f0a;
  --font-scale: 1;
}
.study-card {
  width: 100%;
  height: 100%;
  min-height: 0;
  max-width: 100%;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 18px;
  background: var(--paper);
  box-shadow: 0 20px 54px rgba(0, 0, 0, 0.10);
}
.front-card {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  grid-template-rows: minmax(0, 56%) minmax(145px, 22%) minmax(110px, 22%);
}
.cinema {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  min-height: 0;
  padding: clamp(10px, 1.2vh, 16px);
  background: #111114;
}
.media-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
  color: rgba(255, 255, 255, 0.76);
  font-size: 12px;
  font-weight: 800;
}
.pill {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 3px 9px;
  border: 1px solid rgba(255, 255, 255, 0.16);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.09);
}
.cinema video,
.replay video {
  display: block;
  width: 100%;
  height: 100%;
  min-height: 0;
  aspect-ratio: 16 / 9;
  max-height: 100%;
  object-fit: contain;
  border-radius: 8px;
  background: #000;
}
.replay video {
  max-height: 100%;
}
.no-media {
  display: grid;
  height: 100%;
  min-height: 0;
  place-items: center;
  padding: 28px;
  border: 1px dashed rgba(255, 255, 255, 0.25);
  border-radius: 12px;
  color: rgba(255, 255, 255, 0.84);
  text-align: center;
}
.no-media strong {
  display: block;
  margin-bottom: 8px;
  font-size: 25px;
}
.front-task {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: clamp(12px, 1.6vw, 24px);
  align-items: center;
  min-height: 0;
  overflow: hidden;
  padding: clamp(16px, 2.2vh, 28px) clamp(24px, 3.2vw, 42px);
}
.task-kicker,
.label {
  margin: 0;
  color: var(--green);
  font-size: 12px;
  font-weight: 860;
}
.task-title {
  margin: 4px 0 0;
  color: var(--ink);
  font-size: clamp(24px, min(3vw, 4.2vh), 34px);
  line-height: 1.18;
  font-weight: 980;
  overflow-wrap: anywhere;
}
.front-content {
  margin: clamp(8px, 1.2vh, 14px) 0 0;
  padding: clamp(10px, 1.4vh, 16px) clamp(12px, 1.8vw, 20px);
  border-left: 3px solid var(--blue);
  border-radius: 8px;
  background: var(--blue-soft);
  color: var(--ink);
  font-size: clamp(18px, min(2.1vw, 3vh), 24px);
  line-height: 1.38;
  font-weight: 780;
  overflow-wrap: anywhere;
}
.front-badge {
  display: grid;
  place-items: center;
  width: 84px;
  min-height: 56px;
  padding: 9px;
  border: 1px solid rgba(0, 122, 255, 0.18);
  border-radius: 12px;
  background: var(--green-soft);
  color: var(--green-deep);
  text-align: center;
  font-size: 12px;
  font-weight: 830;
}
.audio-strip {
  display: grid;
  min-height: 0;
  gap: clamp(8px, 1vh, 12px);
  overflow: hidden;
  padding: clamp(12px, 1.8vh, 22px) clamp(24px, 3.2vw, 42px);
  border-top: 1px solid var(--line);
  background: #fbfbfd;
}
.audio-title,
.hero-meta {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  color: var(--muted);
  font-size: 12px;
  font-weight: 800;
}
.audio-row {
  display: grid;
  grid-template-columns: clamp(82px, 10vw, 128px) minmax(0, 1fr);
  gap: 12px;
  align-items: center;
  min-height: 0;
}
.audio-row span {
  color: var(--muted);
  font-size: 12px;
  font-weight: 780;
}
audio {
  width: 100%;
  max-width: 100%;
  min-height: clamp(32px, 4vh, 44px);
  color-scheme: light;
}
.back-card {
  display: grid;
  grid-template-columns: 1fr;
  grid-template-rows: minmax(260px, 38%) auto auto minmax(0, 1fr);
  min-height: 0;
}
.back-card:not(.has-media) {
  grid-template-rows: auto auto minmax(0, 1fr);
}
.replay {
  display: grid;
  grid-template-rows: minmax(0, 1fr) auto;
  gap: clamp(10px, 1.4vh, 16px);
  height: 100%;
  min-height: 0;
  max-height: none;
  overflow: hidden;
  padding: clamp(12px, 1.6vh, 22px);
  background: #111114;
}
.replay-media {
  display: grid;
  place-items: center;
  justify-self: center;
  width: 100%;
  max-width: 1040px;
  height: 100%;
  min-height: 0;
  padding: 8px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.06);
}
.replay-media video {
  width: 100%;
  height: 100%;
  max-height: none;
  object-fit: contain;
  border-radius: 7px;
}
.replay-tools {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px 16px;
  min-width: 0;
}
.replay .audio-title {
  color: rgba(255, 255, 255, 0.72);
  flex: 1 1 220px;
  align-items: center;
}
.replay-buttons {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}
.replay-audio-control {
  position: relative;
}
.replay-audio-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  min-height: 38px;
  padding: 9px 14px;
  border: 1px solid rgba(255, 255, 255, 0.16);
  border-radius: 999px;
  background: #f7f7f8;
  color: #111114;
  font-size: 13px;
  font-weight: 880;
  line-height: 1;
  box-shadow: 0 10px 26px rgba(0, 0, 0, 0.18);
  cursor: pointer;
  transition: transform 140ms ease, background 140ms ease, color 140ms ease, border-color 140ms ease;
}
.replay-audio-button:focus-visible {
  outline: 3px solid rgba(255, 255, 255, 0.26);
  outline-offset: 3px;
}
.replay-audio-button:active {
  transform: translateY(1px);
}
.replay-audio-button.is-playing {
  border-color: rgba(10, 132, 255, 0.55);
  background: #0a84ff;
  color: #ffffff;
}
.play-dot {
  display: inline-block;
  width: 0;
  height: 0;
  border-top: 6px solid transparent;
  border-bottom: 6px solid transparent;
  border-left: 9px solid currentColor;
}
.replay-audio-source {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  opacity: 0;
  pointer-events: none;
}
.replay .audio-missing {
  min-height: 38px;
  margin: 0;
  padding: 9px 12px;
  border-radius: 999px;
  font-size: 12px;
}
.replay .audio-missing span {
  display: none;
}
.answer-hero {
  display: grid;
  grid-template-rows: auto auto auto auto auto auto;
  align-content: start;
  gap: clamp(6px, 0.9vh, 12px);
  min-height: 0;
  padding: clamp(20px, 2.6vh, 34px) clamp(32px, 4vw, 56px);
  border-bottom: 1px solid var(--line);
  background: linear-gradient(135deg, #ffffff 0%, #f5f8ff 100%);
  overflow: hidden;
}
.focus-word {
  margin: 0;
  color: var(--green-deep);
  font-size: clamp(44px, min(6.2vw, 8.2vh), 78px);
  line-height: 1;
  font-weight: 980;
  overflow-wrap: anywhere;
  max-width: 100%;
  min-width: 0;
}
.focus-line {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
}
.focus-line .focus-word {
  min-width: 0;
}
.phrase-speaker {
  display: inline-grid;
  place-items: center;
  width: 38px;
  height: 38px;
  margin-top: 4px;
  border: 1px solid rgba(0, 122, 255, 0.22);
  border-radius: 999px;
  background: #ffffff;
  color: var(--green-deep);
  font-size: 24px;
  line-height: 1;
  box-shadow: 0 8px 18px rgba(0, 122, 255, 0.12);
  cursor: pointer;
  transition: background 140ms ease, color 140ms ease, box-shadow 140ms ease, transform 140ms ease;
  position: relative;
}
.phrase-speaker:focus-visible {
  outline: 3px solid rgba(0, 122, 255, 0.24);
  outline-offset: 3px;
}
.speaker-icon {
  position: relative;
  display: block;
  width: 20px;
  height: 20px;
}
.speaker-icon::before {
  content: "";
  position: absolute;
  left: 1px;
  top: 4px;
  width: 15px;
  height: 15px;
  background: currentColor;
  clip-path: polygon(0 34%, 34% 34%, 78% 9%, 78% 91%, 34% 66%, 0 66%);
}
.speaker-icon::after {
  content: "";
  position: absolute;
  left: 14px;
  top: 5px;
  width: 8px;
  height: 12px;
  border: 2px solid currentColor;
  border-left: 0;
  border-top-color: transparent;
  border-bottom-color: transparent;
  border-radius: 0 999px 999px 0;
}
.phrase-speaker:active {
  transform: translateY(1px);
  background: var(--green-soft);
}
.phrase-speaker.is-playing {
  background: var(--green-deep);
  color: #ffffff;
  box-shadow: 0 10px 24px rgba(0, 122, 255, 0.24);
}
.phrase-speaker.is-playing::after {
  content: "";
  position: absolute;
  inset: -6px;
  border: 2px solid rgba(0, 122, 255, 0.25);
  border-radius: inherit;
  animation: speakerPulse 900ms ease-out infinite;
}
@keyframes speakerPulse {
  from { opacity: 0.9; transform: scale(0.92); }
  to { opacity: 0; transform: scale(1.2); }
}
.phrase-audio {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  opacity: 0;
  pointer-events: none;
}
.meaning {
  margin: 0;
  color: var(--ink);
  font-size: clamp(22px, min(2.8vw, 3.7vh), 34px);
  line-height: 1.22;
  font-weight: 900;
  overflow-wrap: anywhere;
}
.translation {
  margin: 0;
  color: #8a5a00;
  font-size: clamp(18px, min(2.1vw, 3vh), 26px);
  line-height: 1.26;
  font-weight: 820;
  overflow-wrap: anywhere;
}
.answer-box,
.teacher {
  margin-top: 0;
  border-radius: 9px;
  background: rgba(255, 255, 255, 0.78);
}
.answer-box {
  display: grid;
  gap: 6px;
  min-height: 0;
  padding: clamp(10px, 1.3vh, 16px) clamp(14px, 2vw, 22px);
  border: 1px solid rgba(0, 122, 255, 0.14);
  background: rgba(255, 255, 255, 0.52);
}
.answer-box span,
.detail strong {
  color: var(--muted);
  font-size: 12px;
  font-weight: 850;
}
.answer-box strong {
  color: var(--green-deep);
  font-size: clamp(28px, min(4vw, 5.3vh), 48px);
  line-height: 1.12;
  font-weight: 980;
  overflow-wrap: anywhere;
  max-width: 100%;
}
.teacher {
  display: block;
  overflow: hidden;
  padding: clamp(8px, 1vh, 14px) clamp(12px, 1.7vw, 18px);
  border: 1px solid rgba(154, 106, 34, 0.18);
  color: #343437;
  font-size: clamp(14px, min(1.45vw, 2.1vh), 18px);
  line-height: 1.42;
  font-weight: 640;
  overflow-wrap: anywhere;
}
.dense-card .answer-hero {
  gap: 5px;
  padding-top: 14px;
  padding-bottom: 12px;
}
.dense-card .answer-box,
.dense-card .teacher,
.dense-card .detail {
  padding-top: 8px;
  padding-bottom: 8px;
}
.dense-card .sentence {
  gap: 4px;
  padding-top: 10px;
  padding-bottom: 10px;
}
.dense-card .detail-grid {
  gap: 8px;
  padding-top: 10px;
  padding-bottom: 12px;
}
.dense-card .chip {
  padding: 4px 8px;
  font-size: 13px;
}
.ultra-dense-card .answer-hero {
  gap: 4px;
  padding-top: 10px;
  padding-bottom: 9px;
}
.ultra-dense-card .answer-box,
.ultra-dense-card .teacher,
.ultra-dense-card .detail {
  padding-top: 6px;
  padding-bottom: 6px;
}
.ultra-dense-card .sentence {
  padding-top: 8px;
  padding-bottom: 8px;
}
.ultra-dense-card .detail-grid {
  gap: 6px;
  padding-top: 8px;
  padding-bottom: 9px;
}
.ultra-dense-card .chip {
  padding: 3px 7px;
  font-size: 12px;
}
.sentence {
  display: grid;
  grid-template-rows: auto auto auto;
  gap: clamp(7px, 0.9vh, 12px);
  min-height: 0;
  overflow: visible;
  padding: clamp(18px, 2.1vh, 28px) clamp(34px, 4vw, 58px);
  border-bottom: 1px solid var(--line);
  background: #fbfbfd;
}
.english {
  display: block;
  min-height: 0;
  height: auto;
  margin: 0;
  color: var(--ink);
  font-size: clamp(24px, min(3.4vw, 4.7vh), 44px);
  line-height: 1.18;
  font-weight: 1000;
  overflow: visible;
  overflow-wrap: break-word;
  word-break: normal;
  text-wrap: balance;
  max-width: 100%;
}
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 0;
  min-width: 0;
}
.chip {
  max-width: 100%;
  padding: 6px 10px;
  border: 1px solid rgba(0, 122, 255, 0.22);
  border-radius: 999px;
  background: #ffffff;
  color: var(--green-deep);
  font-size: clamp(13px, min(1.4vw, 2vh), 17px);
  line-height: 1.2;
  font-weight: 920;
  white-space: normal;
  overflow-wrap: anywhere;
}
.audio-row.audio-missing {
  border-color: rgba(154, 106, 34, 0.2);
  background: rgba(255, 244, 224, 0.84);
  color: #8a5a00;
}
.audio-row.audio-missing em {
  font-style: normal;
  font-weight: 760;
  color: #8a5a00;
}
.detail-grid {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  grid-auto-rows: minmax(0, 1fr);
  min-height: 0;
  overflow: hidden;
  gap: clamp(8px, 1vw, 14px);
  padding: clamp(14px, 1.8vh, 22px) clamp(32px, 4vw, 56px) clamp(16px, 2vh, 26px);
}
.detail {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
  padding: clamp(10px, 1.3vh, 16px) clamp(12px, 1.6vw, 18px);
  border: 1px solid var(--line);
  border-radius: 9px;
  background: #ffffff;
}
.detail:nth-child(1),
.detail:nth-child(2),
.detail:nth-child(3) {
  grid-column: span 2;
}
.detail:nth-child(4),
.detail:nth-child(5) {
  grid-column: span 3;
}
.detail.wide {
  background: #f8fbff;
}
.detail p {
  display: block;
  flex: 1;
  min-height: 0;
  margin: 6px 0 0;
  color: #2c2c2e;
  font-size: clamp(14px, min(1.45vw, 2.15vh), 19px);
  line-height: 1.36;
  overflow: hidden;
  overflow-wrap: anywhere;
}
.detail p.english-detail {
  color: var(--ink);
  font-size: clamp(14px, min(1.6vw, 2.3vh), 21px);
  line-height: 1.24;
  font-weight: 760;
  overflow-wrap: anywhere;
}
.learning-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  grid-auto-rows: minmax(0, 1fr);
}
.learning-grid .detail {
  grid-column: auto;
}
.learning-block {
  gap: clamp(4px, 0.7vh, 9px);
}
.learning-block p {
  flex: 0 1 auto;
}
.support-note {
  padding-top: 6px;
  border-top: 1px solid var(--line);
  color: var(--muted) !important;
}
.example-line {
  color: var(--blue-deep) !important;
}
@media (max-width: 680px) {
  .card { padding: 6px; }
  .wrap {
    width: calc(100vw - 12px);
    height: min(1000px, 92vh);
    min-height: min(620px, 92vh);
  }
  .study-card { border-radius: 10px; }
  .front-card {
    grid-template-rows: minmax(0, 48%) minmax(130px, 26%) minmax(95px, 26%);
  }
  .back-card {
    grid-template-rows: minmax(230px, 36%) auto auto minmax(0, 1fr);
  }
  .front-task,
  .audio-row {
    grid-template-columns: 1fr;
  }
  .replay-tools {
    align-content: start;
  }
  .replay-buttons {
    justify-content: flex-start;
  }
  .detail-grid {
    grid-template-columns: 1fr;
    grid-auto-rows: minmax(0, 1fr);
  }
  .detail:nth-child(1),
  .detail:nth-child(2),
  .detail:nth-child(3),
  .detail:nth-child(4),
  .detail:nth-child(5) {
    grid-column: auto;
  }
  .front-badge { width: 100%; min-height: 52px; }
  .task-title { font-size: 24px; }
  .focus-word { font-size: 40px; }
  .phrase-speaker { width: 36px; height: 36px; }
  .speaker-icon { width: 21px; height: 21px; }
  .meaning { font-size: 20px; }
  .translation { font-size: 17px; }
  .english { font-size: 26px; }
  .answer-box strong { font-size: 26px; }
  .front-content { font-size: 17px; }
  .detail p,
  .detail p.english-detail { font-size: 14px; }
  .answer-hero,
  .sentence,
  .detail-grid {
    padding-left: 18px;
    padding-right: 18px;
  }
}
@media (max-height: 940px) {
  .back-card {
    grid-template-rows: minmax(240px, 36%) auto auto minmax(0, 1fr);
  }
  .answer-hero {
    gap: 5px;
    padding-top: 14px;
    padding-bottom: 12px;
  }
  .teacher {
    padding-top: 7px;
    padding-bottom: 7px;
  }
  .sentence {
    gap: 4px;
    padding-top: 10px;
    padding-bottom: 10px;
  }
  .detail-grid {
    padding-top: 10px;
    padding-bottom: 12px;
  }
  .detail p,
  .detail p.english-detail {
    font-size: clamp(13px, min(1.25vw, 1.85vh), 16px);
    line-height: 1.28;
  }
}
@media (max-height: 760px) {
  .card { padding: 6px; }
  .wrap {
    height: min(1120px, 92vh);
    min-height: min(610px, 92vh);
  }
  .front-card {
    grid-template-rows: minmax(0, 50%) minmax(120px, 25%) minmax(90px, 25%);
  }
  .back-card {
    grid-template-rows: minmax(190px, 34%) auto auto minmax(0, 1fr);
  }
  .replay {
    gap: 8px;
    padding: 8px;
  }
  .audio-strip .audio-row + .audio-row {
    margin-top: 4px;
  }
  .replay-audio-button,
  .replay .audio-missing {
    min-height: 34px;
    padding: 8px 11px;
    font-size: 12px;
  }
  .answer-hero {
    gap: 5px;
    padding: 12px 22px;
  }
  .focus-word { font-size: clamp(32px, min(5.2vw, 6.6vh), 54px); }
  .meaning { font-size: clamp(18px, min(2.3vw, 3.1vh), 25px); }
  .translation { font-size: clamp(15px, min(1.8vw, 2.6vh), 21px); }
  .answer-box { padding: 8px 12px; }
  .answer-box strong { font-size: clamp(23px, min(3.2vw, 4.2vh), 36px); }
  .teacher { padding: 7px 10px; }
  .sentence {
    gap: 4px;
    padding: 10px 22px;
  }
  .english { font-size: clamp(21px, min(3.1vw, 4vh), 35px); }
  .detail-grid {
    gap: 7px;
    padding: 9px 22px 11px;
  }
  .detail { padding: 8px 10px; }
  .detail p,
  .detail p.english-detail {
    font-size: clamp(12px, min(1.2vw, 1.8vh), 15px);
    line-height: 1.28;
  }
}
@media (max-height: 620px) {
  .wrap {
    height: 92vh;
    min-height: 92vh;
  }
  .back-card {
    grid-template-rows: minmax(160px, 31%) auto auto minmax(0, 1fr);
  }
  .front-content { display: none; }
  .teacher { padding: 5px 8px; }
  .audio-strip { padding-top: 6px; padding-bottom: 6px; }
  .answer-box strong { font-size: clamp(21px, 3.2vw, 28px); }
  .detail-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

/* Mobile-first review card overrides: keep every learning block in the natural
   document flow so Anki mobile never hides the answer, usage, or warning. */
html,
body,
#qa {
  height: auto !important;
  min-height: 100% !important;
  overflow-x: hidden !important;
  overflow-y: auto !important;
}
.card {
  min-height: 100%;
  overflow-x: hidden;
  overflow-y: visible;
}
.wrap {
  width: min(980px, calc(100vw - 16px));
  max-width: calc(100vw - 12px);
  height: auto;
  min-height: 0;
}
.study-card {
  height: auto;
  min-height: 0;
  overflow: visible;
  border-radius: 14px;
  box-shadow: 0 14px 38px rgba(0, 0, 0, 0.08);
}
.front-card,
.back-card,
.back-card:not(.has-media) {
  display: flex;
  flex-direction: column;
}
.front-task {
  order: 0;
  grid-template-columns: minmax(0, 1fr);
  align-items: start;
  overflow: visible;
  padding: clamp(18px, 4vw, 34px);
  border-bottom: 1px solid var(--line);
}
.front-badge {
  width: auto;
  min-height: 0;
  justify-self: start;
  padding: 6px 10px;
}
.cinema {
  order: 1;
  grid-template-rows: auto auto;
  padding: clamp(8px, 2vw, 14px);
}
.cinema video {
  height: auto;
  max-height: min(46vh, 520px);
}
.audio-strip {
  order: 2;
  overflow: visible;
  padding: clamp(12px, 3vw, 20px) clamp(18px, 4vw, 34px);
}
.audio-row {
  grid-template-columns: clamp(70px, 18vw, 108px) minmax(0, 1fr);
}
.replay {
  height: auto;
  max-height: none;
  grid-template-rows: auto auto;
  overflow: visible;
  padding: clamp(10px, 3vw, 18px);
}
.replay-media {
  height: auto;
  max-width: 920px;
  padding: 0;
}
.replay-media video {
  height: auto;
  max-height: min(34vh, 360px);
}
.answer-hero {
  gap: 10px;
  overflow: visible;
  padding: clamp(16px, 4vw, 30px);
  background: #ffffff;
}
.answer-line {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}
.answer-box strong {
  font-size: clamp(24px, 6vw, 44px);
}
.meaning {
  color: #3a3a3c;
  font-size: clamp(16px, 3.8vw, 23px);
  font-weight: 760;
}
.sentence {
  overflow: visible;
  padding: clamp(14px, 4vw, 26px);
}
.english {
  font-size: clamp(22px, 5vw, 38px);
}
.detail-grid,
.learning-grid {
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  grid-auto-rows: auto;
  overflow: visible;
  padding: clamp(14px, 4vw, 26px);
}
.detail,
.detail p,
.detail p.english-detail {
  overflow: visible;
}
.detail p {
  flex: 0 1 auto;
}
@media (max-width: 680px) {
  .card {
    padding: 5px;
  }
  .wrap {
    width: calc(100vw - 10px);
  }
  .audio-row {
    grid-template-columns: 1fr;
  }
  .detail-grid,
  .learning-grid {
    grid-template-columns: 1fr;
  }
  .replay-buttons {
    justify-content: flex-start;
  }
}
"""


FRONT_TEMPLATE = """
<div class="wrap">
  <section class="study-card front-card">
    <div class="cinema">
      <div class="media-top">
        <span class="pill">{{CardType}}</span>
        <span class="pill">{{SourceTime}}</span>
      </div>
      {{#Video}}{{Video}}{{/Video}}
      {{^Video}}<div class="no-media"><div><strong>知识卡</strong><span>先回答问题，翻面后核对答案。</span></div></div>{{/Video}}
    </div>
    <div class="front-task">
      <div>
        <p class="task-kicker">{{#Video}}先听，不看字幕{{/Video}}{{^Video}}主动回忆{{/Video}}</p>
        <h1 class="task-title" data-fit data-fit-min="18" data-fit-max="36">{{FrontPrompt}}</h1>
        {{#FrontContent}}<p class="front-content" data-fit data-fit-min="15" data-fit-max="25">{{FrontContent}}</p>{{/FrontContent}}
      </div>
      <div class="front-badge">{{#Video}}无字幕听辨{{/Video}}{{^Video}}主动检索{{/Video}}</div>
    </div>
    {{#Audio}}<div class="audio-strip">
      <div class="audio-title"><strong>原声线索</strong><span>0.75x 慢放 / 循环</span></div>
      <div class="audio-row"><span>原声音频</span>{{Audio}}</div>
    </div>{{/Audio}}
  </section>
</div>
<script>
  var responsiveFitQueued = false;
  function currentFontScale(root) {
    var wrap = (root || document).querySelector(".wrap");
    var raw = wrap ? window.getComputedStyle(wrap).getPropertyValue("--font-scale") : "1";
    var scale = parseFloat(raw);
    return isFinite(scale) && scale > 0 ? scale : 1;
  }
  function nodeHasOverflow(node) {
    var isDetailText = node.closest && node.closest(".detail");
    var heightSlack = isDetailText ? 2 : Math.max(6, Math.min(24, node.clientHeight * 0.18));
    var widthSlack = Math.max(2, Math.min(12, node.clientWidth * 0.01));
    if (node.hasAttribute("data-fit")) {
      var textLength = ((node.textContent || "").trim()).length;
      var desiredHeight = textLength > 90 ? 42 : (textLength > 45 ? 28 : 14);
      if (textLength && node.clientHeight < desiredHeight) return true;
    }
    return node.scrollWidth > node.clientWidth + widthSlack || node.scrollHeight > node.clientHeight + heightSlack;
  }
  function fitResponsiveText(root) {
    var scope = root || document;
    var scale = currentFontScale(scope);
    var nodes = scope.querySelectorAll("[data-fit]");
    nodes.forEach(function (node) {
      var style = window.getComputedStyle(node);
      var baseMin = parseFloat(node.getAttribute("data-fit-min")) || 12;
      var baseMax = parseFloat(node.getAttribute("data-fit-max")) || parseFloat(style.fontSize) || baseMin;
      var min = Math.max(10, baseMin * scale);
      var max = Math.max(min, baseMax * scale);
      if (node.clientWidth < 8 || node.clientHeight < 8) return;
      node.style.fontSize = max + "px";
      for (var i = 0; i < 24; i += 1) {
        if (!nodeHasOverflow(node)) break;
        max = Math.max(min, max - 1.5);
        node.style.fontSize = max + "px";
        if (max <= min) break;
      }
    });
  }
  function hasHiddenOverflow(root) {
    var nodes = (root || document).querySelectorAll("[data-fit], .answer-hero, .sentence, .detail-grid, .detail, .teacher, .english, .chips");
    for (var i = 0; i < nodes.length; i += 1) {
      var node = nodes[i];
      var style = window.getComputedStyle(node);
      if (style.display === "none" || style.visibility === "hidden") continue;
      if (node.clientWidth < 4) continue;
      if (nodeHasOverflow(node)) return true;
    }
    return false;
  }
  function fitAdaptiveCard(root) {
    var scope = root || document;
    var wrap = scope.querySelector(".wrap");
    var card = scope.querySelector(".study-card");
    if (wrap) {
      wrap.style.setProperty("--font-scale", "1");
      wrap.classList.remove("dense-card", "ultra-dense-card");
    }
    if (!card) return;
    fitResponsiveText(scope);
  }
  function scheduleResponsiveFit() {
    if (responsiveFitQueued) return;
    responsiveFitQueued = true;
    var run = function () {
      responsiveFitQueued = false;
      fitAdaptiveCard(document);
    };
    if (window.requestAnimationFrame) {
      window.requestAnimationFrame(run);
    } else {
      setTimeout(run, 16);
    }
  }
  function refreshResponsiveCard() {
    document.querySelectorAll("video,audio").forEach(function (node) {
      if (node.closest && node.closest(".phrase-audio")) return;
      node.playbackRate = 0.75;
      node.loop = true;
    });
    fitAdaptiveCard(document);
  }
  setTimeout(refreshResponsiveCard, 80);
  setTimeout(scheduleResponsiveFit, 320);
  window.addEventListener("resize", scheduleResponsiveFit);
  if (window.ResizeObserver) {
    var observedWrap = document.querySelector(".wrap");
    if (observedWrap) new ResizeObserver(scheduleResponsiveFit).observe(observedWrap);
  }
</script>
"""


BACK_TEMPLATE = """
<div class="wrap">
  <section class="study-card back-card {{#Video}}has-media{{/Video}}">
    {{#Video}}<div class="replay">
      <div class="replay-media">{{Video}}</div>
      <div class="replay-tools">
        <div class="audio-title"><strong>回放校对</strong><span>{{SourceTime}}</span></div>
        <div class="replay-buttons">
          {{#Audio}}<span class="replay-audio-control"><button class="replay-audio-button" type="button" title="播放原声音频" onclick="playReplayAudio(this)"><span class="play-dot" aria-hidden="true"></span><span>原声</span></button><span class="replay-audio-source">{{Audio}}</span></span>{{/Audio}}
          {{#TtsAudio}}<span class="replay-audio-control"><button class="replay-audio-button" type="button" title="播放整句 AI 朗读" onclick="playReplayAudio(this)"><span class="play-dot" aria-hidden="true"></span><span>AI 朗读</span></button><span class="replay-audio-source">{{TtsAudio}}</span></span>{{/TtsAudio}}
          {{^TtsAudio}}<span class="audio-missing"><span>整句 AI 朗读</span><em>AI 朗读未生成</em></span>{{/TtsAudio}}
        </div>
      </div>
    </div>{{/Video}}

    <div class="answer-hero">
      <div class="hero-meta">
        <span>{{CardType}}</span>
        <span>{{Difficulty}}</span>
      </div>
      {{#Answer}}<div class="answer-box main-answer">
        <span>核心答案</span>
        <div class="answer-line">
          <strong data-fit data-fit-min="20" data-fit-max="44">{{Answer}}</strong>
          {{#PhraseTtsAudio}}<button class="phrase-speaker" type="button" aria-label="播放表达发音" title="播放表达发音" onclick="playPhraseTts(this)"><span class="speaker-icon" aria-hidden="true"></span></button><span class="phrase-audio">{{PhraseTtsAudio}}</span>{{/PhraseTtsAudio}}
        </div>
      </div>{{/Answer}}
    </div>

    <div class="sentence">
      <span class="label">{{#Video}}英文原句{{/Video}}{{^Video}}正面问题{{/Video}}</span>
      <div class="english" data-fit data-fit-min="18" data-fit-max="44">{{English}}</div>
      <div class="chips">
        {{#Cloze}}<span class="chip cloze-chip">填空：{{Cloze}}</span>{{/Cloze}}
        <span class="chip">{{SourceTime}}</span>
      </div>
    </div>

    <div class="detail-grid learning-grid">
      <div class="detail learning-block understand-block">
        <strong>怎么理解</strong>
        <p data-fit data-fit-min="13" data-fit-max="20">{{Definition}}</p>
        {{#ChineseFeel}}<p class="support-note" data-fit data-fit-min="12" data-fit-max="18">{{ChineseFeel}}</p>{{/ChineseFeel}}
        {{#Why}}<p class="support-note" data-fit data-fit-min="12" data-fit-max="18">{{Why}}</p>{{/Why}}
      </div>
      <div class="detail learning-block use-block">
        <strong>怎么用</strong>
        <p class="english-detail" data-fit data-fit-min="13" data-fit-max="21">{{Collocations}}</p>
        {{#Context}}<p class="support-note" data-fit data-fit-min="12" data-fit-max="18">{{Context}}</p>{{/Context}}
      </div>
      {{#TeacherNote}}<div class="detail learning-block caution-block">
        <strong>别这样用</strong>
        <p data-fit data-fit-min="12" data-fit-max="18">{{TeacherNote}}</p>
      </div>{{/TeacherNote}}
      {{#Example}}<div class="detail learning-block transfer-block">
        <strong>再造一句</strong>
        <p class="english-detail example-line" data-fit data-fit-min="13" data-fit-max="20">{{Example}}</p>
      </div>{{/Example}}
    </div>
  </section>
</div>
<script>
  var responsiveFitQueued = false;
  function currentFontScale(root) {
    var wrap = (root || document).querySelector(".wrap");
    var raw = wrap ? window.getComputedStyle(wrap).getPropertyValue("--font-scale") : "1";
    var scale = parseFloat(raw);
    return isFinite(scale) && scale > 0 ? scale : 1;
  }
  function nodeHasOverflow(node) {
    var isDetailText = node.closest && node.closest(".detail");
    var heightSlack = isDetailText ? 2 : Math.max(6, Math.min(24, node.clientHeight * 0.18));
    var widthSlack = Math.max(2, Math.min(12, node.clientWidth * 0.01));
    if (node.hasAttribute("data-fit")) {
      var textLength = ((node.textContent || "").trim()).length;
      var desiredHeight = textLength > 90 ? 42 : (textLength > 45 ? 28 : 14);
      if (textLength && node.clientHeight < desiredHeight) return true;
    }
    return node.scrollWidth > node.clientWidth + widthSlack || node.scrollHeight > node.clientHeight + heightSlack;
  }
  function fitResponsiveText(root) {
    var scope = root || document;
    var scale = currentFontScale(scope);
    var nodes = scope.querySelectorAll("[data-fit]");
    nodes.forEach(function (node) {
      var style = window.getComputedStyle(node);
      var baseMin = parseFloat(node.getAttribute("data-fit-min")) || 12;
      var baseMax = parseFloat(node.getAttribute("data-fit-max")) || parseFloat(style.fontSize) || baseMin;
      var min = Math.max(10, baseMin * scale);
      var max = Math.max(min, baseMax * scale);
      if (node.clientWidth < 8 || node.clientHeight < 8) return;
      node.style.fontSize = max + "px";
      for (var i = 0; i < 24; i += 1) {
        if (!nodeHasOverflow(node)) break;
        max = Math.max(min, max - 1.5);
        node.style.fontSize = max + "px";
        if (max <= min) break;
      }
    });
  }
  function hasHiddenOverflow(root) {
    var nodes = (root || document).querySelectorAll("[data-fit], .answer-hero, .sentence, .detail-grid, .detail, .teacher, .english, .chips");
    for (var i = 0; i < nodes.length; i += 1) {
      var node = nodes[i];
      var style = window.getComputedStyle(node);
      if (style.display === "none" || style.visibility === "hidden") continue;
      if (node.clientWidth < 4) continue;
      if (nodeHasOverflow(node)) return true;
    }
    return false;
  }
  function fitAdaptiveCard(root) {
    var scope = root || document;
    var wrap = scope.querySelector(".wrap");
    var card = scope.querySelector(".study-card");
    if (wrap) {
      wrap.style.setProperty("--font-scale", "1");
      wrap.classList.remove("dense-card", "ultra-dense-card");
    }
    if (!card) return;
    fitResponsiveText(scope);
  }
  function scheduleResponsiveFit() {
    if (responsiveFitQueued) return;
    responsiveFitQueued = true;
    var run = function () {
      responsiveFitQueued = false;
      fitAdaptiveCard(document);
    };
    if (window.requestAnimationFrame) {
      window.requestAnimationFrame(run);
    } else {
      setTimeout(run, 16);
    }
  }
  function refreshResponsiveCard() {
    document.querySelectorAll("video,audio").forEach(function (node) {
      if (node.closest && node.closest(".phrase-audio")) return;
      node.playbackRate = 0.75;
      node.loop = true;
    });
    document.querySelectorAll(".phrase-audio audio").forEach(function (node) {
      node.loop = false;
      node.playbackRate = 1;
      node.setAttribute("data-role", "phrase-tts");
    });
    fitAdaptiveCard(document);
  }
  setTimeout(refreshResponsiveCard, 80);
  setTimeout(scheduleResponsiveFit, 320);
  window.addEventListener("resize", scheduleResponsiveFit);
  if (window.ResizeObserver) {
    var observedWrap = document.querySelector(".wrap");
    if (observedWrap) new ResizeObserver(scheduleResponsiveFit).observe(observedWrap);
  }
  function resetPhraseSpeaker(button) {
    if (!button) return;
    button.classList.remove("is-playing");
  }
  function playPhraseTts(button) {
    var root = button && button.closest ? button.closest(".focus-line") : null;
    var audio = root ? root.querySelector(".phrase-audio audio") : null;
    if (!audio) return;
    if (!audio.paused) {
      audio.pause();
      audio.currentTime = 0;
      resetPhraseSpeaker(button);
      return;
    }
    document.querySelectorAll(".phrase-audio audio").forEach(function (node) {
      if (node !== audio) {
        node.pause();
        node.currentTime = 0;
      }
    });
    document.querySelectorAll(".phrase-speaker.is-playing").forEach(resetPhraseSpeaker);
    button.classList.add("is-playing");
    audio.loop = false;
    audio.playbackRate = 1;
    audio.currentTime = 0;
    audio.onended = function () { resetPhraseSpeaker(button); };
    audio.onpause = function () {
      if (audio.currentTime === 0 || audio.ended) resetPhraseSpeaker(button);
    };
    var playResult = audio.play();
    if (playResult && playResult.catch) {
      playResult.catch(function () { resetPhraseSpeaker(button); });
    }
  }
  function resetReplayButton(button) {
    if (!button) return;
    button.classList.remove("is-playing");
  }
  function playReplayAudio(button) {
    var root = button && button.closest ? button.closest(".replay-audio-control") : null;
    var audio = root ? root.querySelector(".replay-audio-source audio") : null;
    if (!audio) return;
    if (!audio.paused) {
      audio.pause();
      audio.currentTime = 0;
      resetReplayButton(button);
      return;
    }
    document.querySelectorAll(".replay-audio-source audio").forEach(function (node) {
      if (node !== audio) {
        node.pause();
        node.currentTime = 0;
      }
    });
    document.querySelectorAll(".replay-audio-button.is-playing").forEach(resetReplayButton);
    button.classList.add("is-playing");
    audio.loop = true;
    audio.playbackRate = 0.75;
    audio.currentTime = 0;
    audio.onpause = function () {
      if (audio.currentTime === 0 || audio.ended) resetReplayButton(button);
    };
    var playResult = audio.play();
    if (playResult && playResult.catch) {
      playResult.catch(function () { resetReplayButton(button); });
    }
  }
</script>
"""


DICTIONARY_FRONT_TEMPLATE = FRONT_TEMPLATE
DICTIONARY_BACK_TEMPLATE = BACK_TEMPLATE
MINIMAL_FRONT_TEMPLATE = FRONT_TEMPLATE
MINIMAL_BACK_TEMPLATE = BACK_TEMPLATE


# Final V10 visual layer. It keeps the established APKG field names, but routes
# the same fields through source-aware layouts instead of one oversized shell.
CARD_CSS = """
.card {
  margin: 0;
  min-height: 100%;
  padding: clamp(10px, 3vw, 18px);
  background: #f5f5f7;
  color: #1d1d1f;
  font-family: "SF Pro Text", "Segoe UI", "Noto Sans SC", "Microsoft YaHei UI", sans-serif;
  line-height: 1.5;
  text-align: left;
  letter-spacing: 0;
  overflow-x: hidden;
  overflow-y: auto;
}
* { box-sizing: border-box; }
html,
body,
#qa {
  width: 100% !important;
  min-height: 100% !important;
  height: auto !important;
  margin: 0 !important;
  overflow-x: hidden !important;
  overflow-y: auto !important;
}
.review-card {
  width: min(900px, 100%);
  max-width: 100%;
  margin: 0 auto;
  border: 1px solid rgba(60, 60, 67, 0.13);
  border-radius: 16px;
  background: #ffffff;
  box-shadow: 0 16px 42px rgba(0, 0, 0, 0.08);
  overflow: hidden;
}
.learning-hierarchy-system {
  --recall-accent: #0057d8;
  --evidence-accent: #34c759;
  --boundary-accent: #b56a19;
  --transfer-accent: #5856d6;
}
.recall-task .prompt {
  font-weight: 950;
  letter-spacing: -0.025em;
}
.recall-task .cue {
  max-width: 72ch;
}
.answer-anchor {
  background:
    radial-gradient(circle at 0% 0%, rgba(0, 122, 255, 0.10), transparent 34%),
    #ffffff;
}
.answer-anchor .answer,
.answer-anchor h1 {
  font-weight: 950;
  letter-spacing: -0.025em;
}
.evidence-anchor {
  background: #f8fbff;
}
.evidence-anchor .source {
  font-weight: 860;
}
.understanding-block {
  border-color: rgba(0, 122, 255, 0.16);
  background: #fbfdff;
}
.transfer-block {
  border-color: rgba(88, 86, 214, 0.18);
  background: #fbfbff;
}
.boundary-block {
  border-color: rgba(181, 106, 25, 0.25);
  background: #fffaf0;
}
.card-section {
  padding: clamp(18px, 4vw, 34px);
  border-top: 1px solid rgba(60, 60, 67, 0.12);
}
.card-section:first-child { border-top: 0; }
.meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  justify-content: space-between;
  color: #6e6e73;
  font-size: clamp(12px, 2.8vw, 14px);
  font-weight: 800;
}
.meta > span {
  min-width: 0;
  overflow-wrap: anywhere;
}
.tag {
  display: inline-flex;
  align-items: center;
  min-height: 26px;
  padding: 4px 10px;
  border: 1px solid rgba(0, 122, 255, 0.18);
  border-radius: 999px;
  background: rgba(0, 122, 255, 0.08);
  color: #0057d8;
}
.layout-cloze .tag {
  border-color: rgba(255, 159, 10, 0.26);
  background: rgba(255, 159, 10, 0.10);
  color: #9a5b00;
}
.layout-listening .media-strip {
  max-height: none;
}
.prompt {
  margin: clamp(18px, 4vw, 32px) 0 0;
  color: #111114;
  font-size: clamp(28px, 7vw, 46px);
  line-height: 1.14;
  font-weight: 900;
  overflow-wrap: anywhere;
}
.cue {
  margin-top: 16px;
  padding: 14px 16px;
  border-left: 4px solid #007aff;
  border-radius: 10px;
  background: rgba(0, 122, 255, 0.08);
  color: #242426;
  font-size: clamp(17px, 4vw, 23px);
  font-weight: 720;
  overflow-wrap: anywhere;
}
.answer {
  margin: clamp(16px, 4vw, 26px) 0 0;
  color: #0057d8;
  font-size: clamp(31px, 8vw, 54px);
  line-height: 1.08;
  font-weight: 950;
  overflow-wrap: anywhere;
}
.source {
  margin-top: 12px;
  color: #1d1d1f;
  font-size: clamp(20px, 5vw, 34px);
  line-height: 1.22;
  font-weight: 850;
  overflow-wrap: anywhere;
}
.subtle {
  margin-top: 8px;
  color: #6e6e73;
  font-size: clamp(13px, 3vw, 16px);
  font-weight: 760;
}
.media-panel {
  padding: clamp(8px, 2.4vw, 14px);
  background: #111114;
}
.media-panel video {
  display: block;
  width: 100%;
  max-height: min(54vh, 520px);
  border-radius: 10px;
  background: #000;
  object-fit: contain;
}
.media-strip {
  margin-top: 16px;
  padding: 10px;
  border-radius: 12px;
  background: #111114;
}
.media-strip video {
  display: block;
  width: 100%;
  max-height: min(28vh, 240px);
  border-radius: 8px;
  background: #000;
  object-fit: contain;
}
.audio-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  margin-top: 16px;
}
.audio-item {
  display: grid;
  grid-template-columns: auto minmax(180px, 1fr);
  gap: 8px;
  align-items: center;
  max-width: 100%;
  padding: 8px 10px;
  border: 1px solid rgba(60, 60, 67, 0.12);
  border-radius: 999px;
  background: #f5f5f7;
}
.audio-item span {
  color: #6e6e73;
  font-size: 12px;
  font-weight: 850;
}
audio {
  width: min(360px, 64vw);
  min-height: 32px;
  color-scheme: light;
}
.answer-line {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
}
.phrase-audio {
  display: inline-flex;
  align-items: center;
}
.phrase-audio audio {
  width: 160px;
}
.block-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
}
.info-block {
  padding: 15px 16px;
  border: 1px solid rgba(60, 60, 67, 0.12);
  border-radius: 12px;
  background: #fbfbfd;
}
.info-block strong {
  display: block;
  margin-bottom: 7px;
  color: #6e6e73;
  font-size: 13px;
  font-weight: 880;
}
.info-block small {
  display: block;
  margin: -3px 0 8px;
  color: #8a8a8e;
  font-size: 12px;
  font-weight: 720;
}
.info-block p {
  margin: 0;
  color: #242426;
  font-size: clamp(15px, 3.6vw, 19px);
  line-height: 1.46;
  overflow-wrap: anywhere;
}
.info-block p + p { margin-top: 9px; }
.english-note {
  color: #0057d8 !important;
  font-weight: 780;
}
.warning-block {
  border-color: rgba(154, 106, 34, 0.22);
  background: #fffaf0;
}
.knowledge-card .answer {
  color: #1d1d1f;
}
.knowledge-answer-shell {
  background:
    radial-gradient(circle at 0% 0%, rgba(52, 199, 89, 0.13), transparent 34%),
    #ffffff;
}
.knowledge-answer-note {
  margin: 12px 0 0;
  color: #3f4a45;
  font-size: clamp(15px, 3.4vw, 18px);
  line-height: 1.55;
}
.knowledge-evidence-card {
  background: #f7fbf8;
}
.knowledge-source {
  color: #24312c;
  font-size: clamp(17px, 4.4vw, 25px);
  font-weight: 760;
  line-height: 1.35;
}
.knowledge-question-cue {
  display: grid;
  gap: 5px;
  border-left-color: #34c759;
  background: rgba(52, 199, 89, 0.08);
  font-size: clamp(14px, 3.5vw, 17px);
  font-weight: 650;
}
.knowledge-question-cue strong {
  color: #166534;
  font-size: 12px;
  letter-spacing: 0.04em;
}
.knowledge-question-cue p,
.knowledge-action-card p {
  margin: 0;
}
.knowledge-grid {
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
}
.knowledge-action-card,
.knowledge-transfer-check {
  display: grid;
  gap: 12px;
  background: #fbfbfd;
}
.knowledge-transfer-check {
  border-top-color: rgba(88, 86, 214, 0.18);
  background:
    linear-gradient(180deg, rgba(88, 86, 214, 0.055), rgba(255, 255, 255, 0.92));
}
.knowledge-action-card p,
.knowledge-transfer-check p {
  color: #242426;
  font-size: clamp(15px, 3.6vw, 19px);
  line-height: 1.5;
}
.knowledge-cloze-cue {
  margin-top: 0;
  border-left-color: #007aff;
}
.knowledge-card .tag {
  border-color: rgba(52, 199, 89, 0.22);
  background: rgba(52, 199, 89, 0.1);
  color: #166534;
}
.reading-card .tag {
  border-color: rgba(88, 86, 214, 0.22);
  background: rgba(88, 86, 214, 0.1);
  color: #4338ca;
}
@media (max-width: 560px) {
  .card { padding: 8px; }
  .review-card { width: 100%; max-width: 100%; border-radius: 14px; }
  .card-section { padding: 18px; }
  .prompt { font-size: clamp(24px, 7vw, 32px); line-height: 1.16; }
  .answer { font-size: clamp(26px, 8vw, 36px); line-height: 1.12; }
  .knowledge-card .answer { font-size: clamp(24px, 6.8vw, 32px); }
  .source { font-size: clamp(18px, 4.6vw, 24px); line-height: 1.3; }
  .subtle { font-size: clamp(13px, 3.4vw, 15px); }
  .media-panel video { max-height: min(34vh, 260px); }
  .media-strip video { max-height: min(20vh, 180px); }
  .audio-item {
    width: 100%;
    grid-template-columns: 1fr;
    border-radius: 12px;
  }
  audio { width: 100%; }
  .block-grid { grid-template-columns: 1fr; }
}
"""


LANGUAGE_FRONT_TEMPLATE = """
<div class="review-card language-card front layout-{{CardLayout}} learning-hierarchy-system">
  {{#IsListening}}
  {{#Video}}<div class="media-panel evidence-anchor">{{Video}}</div>{{/Video}}
  <section class="card-section recall-task">
    <div class="meta"><span class="tag">{{CardType}}</span><span>{{SourceTime}}</span></div>
    <div class="subtle">{{FrontKicker}}</div>
    <h1 class="prompt">{{FrontPrompt}}</h1>
    {{#Audio}}<div class="audio-actions"><div class="audio-item"><span>原声</span>{{Audio}}</div></div>{{/Audio}}
  </section>
  {{/IsListening}}
  {{^IsListening}}
  <section class="card-section recall-task">
    <div class="meta"><span class="tag">{{CardType}}</span><span>{{SourceTime}}</span></div>
    <div class="subtle">{{FrontKicker}}</div>
    <h1 class="prompt">{{FrontPrompt}}</h1>
    {{#FrontContent}}<div class="cue">{{FrontContent}}</div>{{/FrontContent}}
    {{#Audio}}<div class="audio-actions"><div class="audio-item"><span>原声</span>{{Audio}}</div></div>{{/Audio}}
    {{#Video}}<div class="media-strip evidence-anchor">{{Video}}</div>{{/Video}}
  </section>
  {{/IsListening}}
</div>
"""


LANGUAGE_BACK_TEMPLATE = """
<div class="review-card language-card back layout-{{CardLayout}} learning-hierarchy-system">
  <section class="card-section answer-anchor">
    <div class="meta"><span class="tag">{{CardType}}</span><span>{{Difficulty}}</span></div>
    <strong class="subtle">核心答案</strong>
    {{#Answer}}<div class="answer-line"><h1 class="answer">{{Answer}}</h1>{{#PhraseTtsAudio}}<span class="phrase-audio">{{PhraseTtsAudio}}</span>{{/PhraseTtsAudio}}</div>{{/Answer}}
  </section>
  <section class="card-section evidence-anchor">
    <strong class="subtle">{{SourceLabel}}</strong>
    <div class="source">{{English}}</div>
    <div class="subtle">{{SourceTime}}</div>
    {{#Cloze}}<div class="cue">{{Cloze}}</div>{{/Cloze}}
    <div class="audio-actions">
      {{#Audio}}<div class="audio-item"><span>原声</span>{{Audio}}</div>{{/Audio}}
      {{#TtsAudio}}<div class="audio-item"><span>AI 朗读</span>{{TtsAudio}}</div>{{/TtsAudio}}
    </div>
    {{#Video}}<div class="media-strip">{{Video}}</div>{{/Video}}
  </section>
  <section class="card-section">
    <div class="block-grid">
      <div class="info-block understanding-block"><strong>{{UnderstandLabel}}</strong><p>{{Definition}}</p>{{#ChineseFeel}}<p>{{ChineseFeel}}</p>{{/ChineseFeel}}</div>
      <div class="info-block transfer-block"><strong>{{UseLabel}}</strong><p class="english-note">{{Collocations}}</p>{{#Context}}<p>{{Context}}</p>{{/Context}}</div>
      {{#TeacherNote}}<div class="info-block warning-block boundary-block"><strong>老师提醒</strong><p>{{TeacherNote}}</p>{{#Why}}<p>{{Why}}</p>{{/Why}}</div>{{/TeacherNote}}
      {{#Example}}<div class="info-block transfer-block"><strong>再造一句</strong><p class="english-note">{{Example}}</p></div>{{/Example}}
    </div>
  </section>
</div>
"""


KNOWLEDGE_FRONT_TEMPLATE = """
<div class="review-card knowledge-card front layout-{{CardLayout}} learning-hierarchy-system">
  <section class="card-section recall-task">
    <div class="meta"><span class="tag">{{CardType}}</span><span>{{SourceTime}}</span></div>
    <div class="subtle">{{FrontKicker}}</div>
    <h1 class="prompt">{{FrontPrompt}}</h1>
    {{#FrontContent}}<div class="cue">{{FrontContent}}</div>{{/FrontContent}}
  </section>
</div>
"""


KNOWLEDGE_BACK_TEMPLATE = """
<div class="review-card knowledge-card back layout-{{CardLayout}} learning-hierarchy-system">
  <section class="card-section knowledge-answer-shell answer-anchor">
    <div class="meta"><span class="tag">{{CardType}}</span><span>{{Difficulty}}</span></div>
    <strong class="subtle">核心答案</strong>
    <h1 class="answer">{{Answer}}</h1>
    {{#ChineseFeel}}<p class="knowledge-answer-note">{{ChineseFeel}}</p>{{/ChineseFeel}}
  </section>
  <section class="card-section knowledge-evidence-card evidence-anchor">
    <strong class="subtle">原文依据</strong>
    {{#Context}}<div class="source knowledge-source">{{Context}}</div>{{/Context}}
    <div class="cue knowledge-question-cue"><strong>{{SourceLabel}}</strong><p>{{English}}</p></div>
    <div class="subtle">{{SourceTime}}</div>
  </section>
  <section class="card-section knowledge-structure-card">
    <div class="block-grid knowledge-grid">
      <div class="info-block understanding-block"><strong>理解结构</strong><small>{{UnderstandLabel}}</small><p>{{Definition}}</p></div>
      {{#Example}}<div class="info-block transfer-block"><strong>例子</strong><p>{{Example}}</p></div>{{/Example}}
      <div class="info-block warning-block boundary-block"><strong>边界 / 易混点</strong>{{#TeacherNote}}<p>{{TeacherNote}}</p>{{/TeacherNote}}</div>
    </div>
  </section>
  {{#Why}}<section class="card-section knowledge-transfer-check transfer-block">
    <strong class="subtle">迁移检查</strong>
    <p>{{Why}}</p>
  </section>{{/Why}}
  <section class="card-section knowledge-action-card transfer-block">
    <strong class="subtle">复习动作</strong>
    {{#Cloze}}<div class="cue knowledge-cloze-cue">{{Cloze}}</div>{{/Cloze}}
  </section>
</div>
"""


READING_FRONT_TEMPLATE = """
<div class="review-card reading-card front layout-{{CardLayout}} learning-hierarchy-system">
  <section class="card-section recall-task">
    <div class="meta"><span class="tag">{{CardType}}</span><span>{{SourceTime}}</span></div>
    <div class="subtle">{{FrontKicker}}</div>
    <h1 class="prompt">{{FrontPrompt}}</h1>
    {{#FrontContent}}<div class="cue">{{FrontContent}}</div>{{/FrontContent}}
  </section>
</div>
"""


READING_BACK_TEMPLATE = """
<div class="review-card reading-card back layout-{{CardLayout}} learning-hierarchy-system">
  <section class="card-section answer-anchor">
    <div class="meta"><span class="tag">{{CardType}}</span><span>{{Difficulty}}</span></div>
    <strong class="subtle">核心答案</strong>
    <h1 class="answer">{{Answer}}</h1>
  </section>
  <section class="card-section evidence-anchor">
    <strong class="subtle">{{SourceLabel}}</strong>
    <div class="source">{{English}}</div>
    <div class="subtle">{{SourceTime}}</div>
  </section>
  <section class="card-section">
    <div class="block-grid">
      <div class="info-block understanding-block"><strong>{{UnderstandLabel}}</strong><p>{{Definition}}</p>{{#ChineseFeel}}<p>{{ChineseFeel}}</p>{{/ChineseFeel}}</div>
      <div class="info-block transfer-block"><strong>{{UseLabel}}</strong><p class="english-note">{{Collocations}}</p>{{#Context}}<p>{{Context}}</p>{{/Context}}</div>
      {{#TeacherNote}}<div class="info-block warning-block boundary-block"><strong>边界 / 易错</strong><p>{{TeacherNote}}</p>{{#Why}}<p>{{Why}}</p>{{/Why}}</div>{{/TeacherNote}}
      {{#Example}}<div class="info-block transfer-block"><strong>再造一句</strong><p class="english-note">{{Example}}</p></div>{{/Example}}
    </div>
  </section>
</div>
"""


MINIMAL_FRONT_TEMPLATE = """
<div class="review-card minimal-card front layout-{{CardLayout}} learning-hierarchy-system">
  <section class="card-section recall-task">
    <div class="meta"><span class="tag">{{CardType}}</span><span>{{SourceTime}}</span></div>
    <div class="subtle">{{FrontKicker}}</div>
    <h1 class="prompt">{{FrontPrompt}}</h1>
    {{#FrontContent}}<div class="cue">{{FrontContent}}</div>{{/FrontContent}}
  </section>
</div>
"""


MINIMAL_BACK_TEMPLATE = """
<div class="review-card minimal-card back layout-{{CardLayout}} learning-hierarchy-system">
  <section class="card-section answer-anchor">
    <div class="meta"><span class="tag">{{CardType}}</span><span>{{Difficulty}}</span></div>
    <h1 class="answer">{{Answer}}</h1>
    <div class="source evidence-anchor">{{English}}</div>
  </section>
  <section class="card-section">
    <div class="block-grid">
      <div class="info-block understanding-block"><strong>怎么理解</strong><p>{{Definition}}</p>{{#ChineseFeel}}<p>{{ChineseFeel}}</p>{{/ChineseFeel}}</div>
      <div class="info-block transfer-block"><strong>怎么用 / 怎么记</strong><p>{{Collocations}}</p>{{#Example}}<p class="english-note">{{Example}}</p>{{/Example}}</div>
      {{#TeacherNote}}<div class="info-block warning-block boundary-block"><strong>边界提醒</strong><p>{{TeacherNote}}</p></div>{{/TeacherNote}}
    </div>
  </section>
</div>
"""


CARD_CSS_V11 = """
.card {
  margin: 0;
  min-height: 100%;
  padding: clamp(10px, 3vw, 24px);
  background: #f5f5f7;
  color: #1d1d1f;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans SC", "Microsoft YaHei UI", sans-serif;
  line-height: 1.5;
  text-align: left;
  letter-spacing: 0;
  overflow-x: hidden;
  overflow-y: auto;
}
* { box-sizing: border-box; }
html,
body,
#qa {
  width: 100% !important;
  min-height: 100% !important;
  height: auto !important;
  margin: 0 !important;
  overflow-x: hidden !important;
  overflow-y: auto !important;
}
.v11-card {
  width: min(1120px, calc(100vw - 18px));
  margin: 0 auto;
  padding: clamp(24px, 4vw, 42px);
  border: 1px solid rgba(60, 60, 67, 0.12);
  border-radius: clamp(22px, 3vw, 30px);
  background: #ffffff;
  box-shadow: 0 22px 70px rgba(0, 0, 0, 0.10);
  overflow: hidden;
}
.learning-hierarchy-system {
  --recall-accent: #245B85;
  --recall-accent-soft: rgba(36, 91, 133, 0.09);
  --evidence-accent: #34c759;
  --boundary-accent: #b56a19;
  --transfer-accent: #5856d6;
}
.recall-task h1,
.answer-anchor h1,
.answer-anchor .v11-answer-title {
  font-weight: 950;
  letter-spacing: -0.035em;
}
.evidence-anchor {
  border-color: rgba(52, 199, 89, 0.18);
  background: rgba(52, 199, 89, 0.045);
}
.understanding-block {
  border-color: rgba(0, 122, 255, 0.16) !important;
}
.transfer-block {
  border-color: rgba(88, 86, 214, 0.18) !important;
}
.boundary-block {
  border-color: rgba(181, 106, 25, 0.26) !important;
  background: #fffaf0 !important;
}
.v11-top {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
}
.v11-pill,
.v11-difficulty {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 34px;
  padding: 7px 14px;
  border-radius: 999px;
  font-size: clamp(14px, 2.8vw, 18px);
  font-weight: 850;
}
.v11-pill {
  background: rgba(0, 122, 255, 0.10);
  color: var(--recall-accent);
}
.v11-difficulty {
  background: rgba(88, 86, 214, 0.10);
  color: #5a38c7;
}
.v11-time {
  color: #6e6e73;
  font-size: clamp(14px, 2.6vw, 18px);
  font-weight: 650;
}
.v11-front-copy {
  margin-top: clamp(20px, 4vw, 30px);
}
.v11-front-copy h1 {
  margin: 0;
  color: #111114;
  font-size: clamp(38px, 6vw, 68px);
  line-height: 1.08;
  font-weight: 900;
  overflow-wrap: break-word;
  word-break: normal;
}
.v11-front-copy p {
  margin: 10px 0 0;
  color: #6e6e73;
  font-size: clamp(18px, 3vw, 25px);
  font-weight: 520;
}
.v11-video-stage {
  position: relative;
  margin-top: clamp(24px, 4vw, 34px);
  border-radius: clamp(18px, 2.5vw, 24px);
  background: #050506;
  overflow: hidden;
  cursor: pointer;
}
.v11-video-stage video {
  display: block;
  width: 100%;
  aspect-ratio: 16 / 9;
  max-height: min(58vh, 560px);
  background: #000;
  object-fit: cover;
}
.v11-back .v11-video-stage {
  margin-top: 0;
}
.v11-back .v11-video-stage video {
  max-height: 250px;
}
.v11-video-toggle {
  position: absolute;
  left: 50%;
  top: 50%;
  display: grid;
  width: clamp(58px, 10vw, 82px);
  height: clamp(58px, 10vw, 82px);
  place-items: center;
  border-radius: 999px;
  background: rgba(20, 20, 22, 0.44);
  color: #ffffff;
  font-size: clamp(28px, 5vw, 40px);
  font-weight: 900;
  transform: translate(-50%, -50%);
  opacity: 0;
  transition: opacity 160ms ease, background 160ms ease;
  pointer-events: none;
}
.v11-video-stage:hover .v11-video-toggle,
.v11-video-stage.is-sound-on .v11-video-toggle,
.v11-video-stage.is-paused .v11-video-toggle {
  opacity: 1;
}
.v11-video-stage.is-paused .v11-video-toggle {
  background: rgba(20, 20, 22, 0.62);
}
.v11-video-time {
  position: absolute;
  right: 14px;
  bottom: 12px;
  padding: 4px 9px;
  border-radius: 999px;
  background: rgba(0, 0, 0, 0.48);
  color: #ffffff;
  font-size: 13px;
  font-weight: 760;
}
.v11-video-cue {
  position: absolute;
  left: 14px;
  bottom: 12px;
  padding: 5px 10px;
  border-radius: 999px;
  background: rgba(0, 0, 0, 0.5);
  color: #ffffff;
  font-size: 13px;
  font-weight: 760;
}
.v11-video-stage.is-sound-on .v11-video-cue {
  background: rgba(36, 91, 133, 0.92);
}
.v11-video-stage.is-paused .v11-video-cue {
  background: rgba(36, 91, 133, 0.72);
}
.v11-video-stage.is-error {
  box-shadow: inset 0 0 0 3px rgba(178, 58, 53, 0.82);
}
.v11-video-stage.is-error .v11-video-cue {
  background: rgba(178, 58, 53, 0.92);
}
.v11-sound-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: clamp(12px, 3vw, 24px);
  margin-top: clamp(22px, 4vw, 32px);
}
.v11-sound-actions.is-left {
  justify-content: flex-start;
  margin-top: 18px;
}
.v11-sound-button,
.v11-speaker {
  border: 1px solid rgba(60, 60, 67, 0.15);
  background: #ffffff;
  color: #1d1d1f;
  box-shadow: 0 1px 1px rgba(0, 0, 0, 0.03);
  cursor: pointer;
}
.v11-sound-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  min-width: min(220px, 40vw);
  min-height: 58px;
  padding: 10px 24px;
  border-radius: 999px;
  font-size: clamp(18px, 3vw, 24px);
  font-weight: 820;
}
.v11-sound-actions.is-left .v11-sound-button {
  min-width: 150px;
  min-height: 48px;
  font-size: 18px;
}
.v11-play {
  color: var(--recall-accent);
  font-size: 1.1em;
  line-height: 1;
}
.v11-media-source,
.v11-media-source audio {
  display: none !important;
}
.v11-answer-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.18fr) minmax(280px, 0.82fr);
  gap: clamp(24px, 4vw, 42px);
  align-items: start;
  margin-top: clamp(28px, 5vw, 42px);
}
.v11-answer-main {
  grid-column: 1;
  min-width: 0;
}
.v11-answer-layout > .v11-video-stage {
  grid-column: 2;
  grid-row: 1;
}
.v11-back .v11-answer-layout {
  display: flex;
  flex-direction: column;
}
.v11-back .v11-answer-layout > .v11-video-stage {
  width: min(100%, 760px);
  margin-inline: auto;
}
.v11-back .v11-answer-main {
  width: 100%;
}
.v11-label {
  margin-top: 14px;
  color: #6e6e73;
  font-size: clamp(16px, 2.8vw, 22px);
  font-weight: 680;
}
.v11-phrase-line {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
  margin-top: 4px;
}
.v11-phrase-line .v11-answer-title,
.v11-phrase-line .fast-answer-title {
  flex: 0 1 auto;
  min-width: 0;
}
.v11-phrase-line .v11-speaker {
  flex: 0 0 44px;
}
.v11-answer-title {
  margin: 0;
  color: #050506;
  font-size: clamp(40px, 6.2vw, 72px);
  line-height: 1.06;
  font-weight: 910;
  overflow-wrap: break-word;
  word-break: normal;
}
.v11-answer-title.is-long {
  font-size: clamp(34px, 5.1vw, 58px);
  line-height: 1.1;
}
.v11-answer-title.is-very-long {
  font-size: clamp(30px, 4.4vw, 48px);
  line-height: 1.14;
}
.v11-speaker {
  display: inline-grid;
  width: 44px;
  height: 44px;
  place-items: center;
  border-radius: 14px;
  color: var(--recall-accent);
  font-size: 20px;
  font-weight: 900;
}
.v11-chinese-core {
  margin: 8px 0 0;
  color: var(--recall-accent);
  font-size: clamp(20px, 3.4vw, 27px);
  line-height: 1.3;
  font-weight: 820;
  overflow-wrap: break-word;
}
.v11-answer-note {
  margin: 8px 0 0;
  color: #6e6e73;
  font-size: clamp(15px, 2.7vw, 18px);
  line-height: 1.45;
  font-weight: 650;
  overflow-wrap: break-word;
}
.v11-pronunciation {
  display: grid;
  gap: 8px;
  margin-top: 14px;
}
.v11-ipa-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 12px;
  align-items: baseline;
  color: #424650;
  font-size: clamp(14px, 2.6vw, 17px);
  line-height: 1.4;
}
.v11-ipa-row span {
  min-width: 72px;
  color: #7a7f89;
  font-weight: 760;
}
.v11-ipa-row strong {
  color: #111114;
  font-weight: 760;
}
.v11-ipa-row.is-spoken strong {
  color: var(--recall-accent);
}
.v11-ipa-row.is-status strong {
  color: #6e6e73;
  font-size: clamp(13px, 2.4vw, 16px);
  font-weight: 680;
}
.v11-pronunciation-note {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 12px;
  align-items: baseline;
  margin: 2px 0 0;
  color: #5f626b;
  font-size: clamp(14px, 2.6vw, 17px);
  line-height: 1.48;
  font-weight: 620;
  overflow-wrap: break-word;
}
.v11-pronunciation-note span {
  min-width: 72px;
  color: #7a7f89;
  font-weight: 760;
}
.v11-pronunciation-note p {
  flex: 1 1 220px;
  margin: 0;
}
.v11-divider {
  margin: clamp(20px, 4vw, 28px) 0;
  border: 0;
  border-top: 1px solid rgba(60, 60, 67, 0.14);
}
.v11-source-block {
  margin-top: clamp(18px, 3.2vw, 26px);
  padding-left: clamp(14px, 2.4vw, 20px);
  border-left: 3px solid rgba(36, 91, 133, 0.18);
}
.v11-source-label {
  color: #6e6e73;
  font-size: clamp(16px, 2.8vw, 21px);
  line-height: 1.2;
  font-weight: 780;
}
.v11-source {
  margin: 8px 0 0;
  color: #111114;
  font-size: clamp(23px, 3.8vw, 33px);
  line-height: 1.24;
  font-weight: 850;
  overflow-wrap: break-word;
}
.target-expression {
  padding: 0 0.08em;
  border-radius: 4px;
  background: var(--recall-accent-soft);
  color: var(--recall-accent);
  font-size: 1.08em;
  font-weight: 800;
  line-height: inherit;
  -webkit-box-decoration-break: clone;
  box-decoration-break: clone;
}
.v11-source-ipa {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  gap: 6px 12px;
  align-items: start;
  margin: 12px 0 0;
  color: #5f626b;
  font-size: clamp(14px, 2.6vw, 17px);
  line-height: 1.48;
  font-weight: 650;
  overflow-wrap: break-word;
}
.v11-source-ipa span {
  color: #7a7f89;
  font-weight: 780;
  white-space: nowrap;
}
.v11-source-ipa strong {
  color: #2f3238;
  font-weight: 720;
  overflow-wrap: break-word;
}
.v11-source-ipa.is-status strong {
  color: #6e6e73;
  font-weight: 680;
}
.v11-source-translation {
  margin: 12px 0 0;
  padding-top: 10px;
  border-top: 1px solid rgba(60, 60, 67, 0.12);
  color: #5f626b;
  font-size: clamp(18px, 3.2vw, 24px);
  line-height: 1.38;
  font-weight: 650;
  overflow-wrap: break-word;
}
.v11-info-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: clamp(14px, 2.4vw, 24px);
  margin-top: clamp(32px, 5vw, 48px);
}
.v11-info-grid:empty {
  display: none;
}
.v11-info-block {
  min-height: 0;
  padding: clamp(18px, 3vw, 26px);
  border: 1px solid rgba(60, 60, 67, 0.13);
  border-radius: 20px;
  background: #ffffff;
  box-shadow: 0 1px 0 rgba(0, 0, 0, 0.03);
}
.v11-info-block:only-child {
  grid-column: 1 / -1;
}
.v11-example-block {
  margin-top: clamp(18px, 3vw, 26px);
  padding: clamp(18px, 3vw, 26px);
  border: 1px solid rgba(36, 91, 133, 0.16);
  border-radius: 20px;
  background: rgba(36, 91, 133, 0.035);
}
.v11-example-list {
  display: grid;
  gap: 12px;
  margin: 0;
  padding-left: 1.35em;
  color: #313943;
  font-size: clamp(17px, 3vw, 21px);
  line-height: 1.55;
}
.v11-example-list li {
  padding-left: 0.25em;
  overflow-wrap: break-word;
}
.v11-sound-button,
.v11-speaker,
.v11-video-stage {
  transition: border-color 140ms ease, background-color 140ms ease, color 140ms ease, box-shadow 140ms ease;
}
.v11-sound-button.is-playing,
.v11-speaker.is-playing {
  border-color: var(--recall-accent);
  background: var(--recall-accent-soft);
  color: var(--recall-accent);
  box-shadow: 0 0 0 3px rgba(36, 91, 133, 0.12);
}
.v11-sound-button.is-paused,
.v11-speaker.is-paused {
  border-color: rgba(36, 91, 133, 0.38);
  color: var(--recall-accent);
}
.v11-sound-button.is-error,
.v11-speaker.is-error {
  border-color: #b23a35;
  color: #b23a35;
  background: rgba(178, 58, 53, 0.07);
}
.v11-sound-button:focus-visible,
.v11-speaker:focus-visible,
.v11-video-stage:focus-visible {
  outline: 3px solid rgba(36, 91, 133, 0.35);
  outline-offset: 3px;
}
.v11-live-status {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
@media (prefers-reduced-motion: reduce) {
  .v11-sound-button,
  .v11-speaker,
  .v11-video-stage,
  .v11-video-toggle {
    transition: none !important;
  }
}
.v11-info-head {
  display: flex;
  gap: 12px;
  align-items: center;
  margin-bottom: 14px;
  color: #111114;
  font-size: clamp(18px, 3vw, 22px);
  font-weight: 880;
}
.v11-icon {
  display: inline-grid;
  width: 42px;
  height: 42px;
  place-items: center;
  border-radius: 999px;
  background: rgba(0, 122, 255, 0.10);
  color: var(--recall-accent);
}
.v11-info-block:nth-child(2) .v11-icon {
  background: rgba(255, 149, 0, 0.14);
  color: #9d5b00;
}
.v11-info-block:nth-child(3) .v11-icon {
  background: rgba(52, 199, 89, 0.13);
  color: #16833a;
}
.v11-info-block p {
  margin: 0;
  color: #5f626b;
  font-size: clamp(16px, 3vw, 20px);
  line-height: 1.55;
  overflow-wrap: break-word;
  white-space: pre-line;
}
.v11-info-block p + p {
  margin-top: 8px;
}
@media (max-width: 760px) {
  .card { padding: 8px; }
  .v11-card {
    width: calc(100vw - 16px);
    padding: clamp(18px, 5vw, 24px);
    border-radius: 22px;
  }
  .v11-front-copy h1 {
    font-size: clamp(32px, 9vw, 48px);
  }
  .v11-front-copy p {
    font-size: clamp(16px, 4.4vw, 20px);
  }
  .v11-video-stage video {
    max-height: min(34vh, 260px);
    aspect-ratio: 16 / 9;
  }
  .v11-sound-actions {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
  }
  .v11-sound-actions.is-left {
    display: flex;
    justify-content: flex-start;
  }
  .v11-sound-button {
    min-width: 0;
    width: 100%;
    min-height: 50px;
    padding: 8px 12px;
  }
  .v11-sound-actions.is-left .v11-sound-button {
    width: auto;
    min-width: 112px;
  }
  .v11-answer-layout {
    display: block;
  }
  .v11-source-ipa {
    grid-template-columns: 1fr;
  }
  .v11-back .v11-video-stage {
    margin-top: 26px;
  }
  .v11-back .v11-video-stage video {
    max-height: min(24vh, 190px);
    aspect-ratio: 16 / 9;
  }
  .v11-answer-title {
    font-size: clamp(30px, 8.5vw, 42px);
    line-height: 1.1;
  }
  .v11-answer-title.is-long {
    font-size: clamp(29px, 8.2vw, 38px);
    line-height: 1.12;
  }
  .v11-answer-title.is-very-long {
    font-size: clamp(24px, 7vw, 32px);
    line-height: 1.18;
  }
  .v11-chinese-core {
    font-size: clamp(17px, 4.7vw, 21px);
  }
  .v11-source {
    font-size: clamp(19px, 5vw, 25px);
  }
  .v11-info-grid {
    grid-template-columns: 1fr;
    gap: 14px;
    margin-top: 26px;
  }
  .v11-info-block {
    min-height: 0;
  }
}
"""


V11_CARD_SCRIPT = """
<script>
(function() {
  function rootFor(node) {
    return node && node.closest ? (node.closest(".v11-card") || document) : document;
  }
  var AUDIO_COPY = {
    original: { idle: "\u64ad\u653e\u539f\u58f0", playing: "\u6682\u505c\u539f\u58f0", paused: "\u7ee7\u7eed\u539f\u58f0", ended: "\u518d\u542c\u539f\u58f0", error: "\u539f\u58f0\u64ad\u653e\u5931\u8d25\uff0c\u70b9\u51fb\u91cd\u8bd5" },
    slow: { idle: "\u64ad\u653e\u6162\u8bfb", playing: "\u6682\u505c\u6162\u8bfb", paused: "\u7ee7\u7eed\u6162\u8bfb", ended: "\u518d\u542c\u6162\u8bfb", error: "\u6162\u8bfb\u64ad\u653e\u5931\u8d25\uff0c\u70b9\u51fb\u91cd\u8bd5" },
    phrase: { idle: "\u64ad\u653e\u8868\u8fbe\u53d1\u97f3", playing: "\u6682\u505c\u8868\u8fbe\u53d1\u97f3", paused: "\u7ee7\u7eed\u8868\u8fbe\u53d1\u97f3", ended: "\u518d\u542c\u8868\u8fbe\u53d1\u97f3", error: "\u8868\u8fbe\u53d1\u97f3\u64ad\u653e\u5931\u8d25\uff0c\u70b9\u51fb\u91cd\u8bd5" }
  };

  function announce(root, message) {
    var region = root.querySelector(".v11-live-status");
    if (region) region.textContent = message || "";
  }

  function copyFor(button, state) {
    var role = button.getAttribute("data-media-role") || "original";
    var copy = AUDIO_COPY[role] || AUDIO_COPY.original;
    return copy[state] || copy.idle;
  }

  function isV11ActivationKey(event) {
    return event && (event.key === "Enter" || event.key === " " || event.key === "Spacebar");
  }

  function consumeV11ActivationKey(event) {
    if (!isV11ActivationKey(event)) return false;
    event.preventDefault();
    event.stopPropagation();
    if (typeof event.stopImmediatePropagation === "function") {
      event.stopImmediatePropagation();
    }
    return true;
  }

  function focusV11MediaControl(control) {
    if (!control || typeof control.focus !== "function") return;
    try {
      control.focus({ preventScroll: true });
    } catch (error) {
      control.focus();
    }
  }

  function bindV11MediaKeyboard(control, activate) {
    if (!control || control.getAttribute("data-v11-keyboard-bound")) return;
    control.addEventListener("keydown", function(event) {
      if (!consumeV11ActivationKey(event) || event.repeat) return;
      activate();
    }, true);
    ["keypress", "keyup"].forEach(function(eventName) {
      control.addEventListener(eventName, function(event) {
        consumeV11ActivationKey(event);
      }, true);
    });
    control.setAttribute("data-v11-keyboard-bound", "1");
  }

  function setV11AudioState(button, state, shouldAnnounce) {
    if (!button) return;
    button.setAttribute("data-media-state", state);
    button.classList.toggle("is-playing", state === "playing");
    button.classList.toggle("is-paused", state === "paused");
    button.classList.toggle("is-error", state === "error");
    button.setAttribute("aria-pressed", state === "playing" ? "true" : "false");
    var message = copyFor(button, state);
    var label = button.querySelector(".v11-button-label");
    if (label) label.textContent = message;
    button.setAttribute("aria-label", message);
    button.setAttribute("title", message);
    if (shouldAnnounce) announce(rootFor(button), message);
  }

  function audioButtonFor(audio) {
    var root = rootFor(audio);
    var source = audio && audio.closest ? audio.closest(".v11-media-source") : null;
    if (!source) return null;
    var selector = source.classList.contains("audio-slow") ? ".audio-slow" : (source.classList.contains("audio-phrase") ? ".audio-phrase" : ".audio-original");
    return root.querySelector('[data-media-selector="' + selector + '"]');
  }

  function resetAudio(audio) {
    if (!audio) return;
    audio.pause();
    try { audio.currentTime = 0; } catch (error) {}
    setV11AudioState(audioButtonFor(audio), "idle", false);
  }

  window.playV11Audio = function(button, selector) {
    focusV11MediaControl(button);
    var root = rootFor(button);
    var audio = root.querySelector(selector + " audio");
    if (!audio) {
      setV11AudioState(button, "error", true);
      return;
    }
    var state = button.getAttribute("data-media-state") || "idle";
    if (state === "playing") {
      audio.pause();
      setV11AudioState(button, "paused", true);
      return;
    }
    pauseOtherMedia(audio);
    if (state !== "paused") {
      try { audio.currentTime = 0; } catch (error) {}
    }
    audio.playbackRate = 1;
    setV11AudioState(button, "playing", true);
    var playResult;
    try {
      playResult = audio.play();
    } catch (error) {
      if (button.getAttribute("data-media-state") === "playing") {
        setV11AudioState(button, "error", true);
      }
      return;
    }
    if (playResult && playResult.then) {
      playResult.catch(function() {
        if (button.getAttribute("data-media-state") === "playing") {
          setV11AudioState(button, "error", true);
        }
      });
    }
  };

  function setV11VideoState(stage, state, shouldAnnounce) {
    if (!stage) return;
    var cue = stage.querySelector(".v11-video-cue");
    var toggle = stage.querySelector(".v11-video-toggle");
    var messages = { idle: "\u70b9\u51fb\u64ad\u653e\u89c6\u9891", playing: "\u89c6\u9891\u64ad\u653e\u4e2d", paused: "\u89c6\u9891\u5df2\u6682\u505c", error: "\u89c6\u9891\u64ad\u653e\u5931\u8d25" };
    var message = messages[state] || messages.idle;
    stage.setAttribute("data-media-state", state);
    stage.classList.toggle("is-muted-preview", state === "idle");
    stage.classList.toggle("is-sound-on", state === "playing");
    stage.classList.toggle("is-paused", state === "paused");
    stage.classList.toggle("is-error", state === "error");
    stage.setAttribute("aria-pressed", state === "playing" ? "true" : "false");
    stage.setAttribute("aria-label", message);

    if (cue) cue.textContent = message;
    if (toggle) toggle.textContent = state === "playing" ? "II" : "\u25b6";
    if (shouldAnnounce) announce(rootFor(stage), message);
  }

  function pauseOtherMedia(activeMedia) {
    document.querySelectorAll("audio").forEach(function(node) {
      if (node !== activeMedia) resetAudio(node);
    });
    document.querySelectorAll(".v11-video-stage video").forEach(function(node) {
      if (node !== activeMedia) {
        node.pause();
        node.muted = false;
        try { node.currentTime = 0; } catch (error) {}
        setV11VideoState(node.closest(".v11-video-stage"), "idle", false);
      }
    });
  }

  window.toggleV11Video = function(stage) {
    if (!stage) return;
    focusV11MediaControl(stage);
    var video = stage.querySelector("video");
    if (!video) {
      setV11VideoState(stage, "error", true);
      return;
    }
    var state = stage.getAttribute("data-media-state") || "idle";
    if (state === "playing" || !video.paused) {
      video.pause();
      setV11VideoState(stage, "paused", true);
      return;
    }
    pauseOtherMedia(video);
    if (video.currentTime >= Math.max(0, video.duration - 0.1)) {
      try { video.currentTime = 0; } catch (error) {}
    }
    video.loop = true;
    video.muted = false;
    video.volume = 1;
    setV11VideoState(stage, "playing", true);
    var playResult;
    try {
      playResult = video.play();
    } catch (error) {
      if (stage.getAttribute("data-media-state") === "playing") {
        setV11VideoState(stage, "error", true);
      }
      return;
    }
    if (playResult && playResult.then) {
      playResult.catch(function() {
        if (stage.getAttribute("data-media-state") === "playing") {
          setV11VideoState(stage, "error", true);
        }
      });
    }
  };
  function setupV11AudioButtons() {
    document.querySelectorAll(".v11-card [data-media-selector]").forEach(function(button) {
      var root = rootFor(button);
      var selector = button.getAttribute("data-media-selector");
      var audio = selector ? root.querySelector(selector + " audio") : null;
      setV11AudioState(button, audio ? "idle" : "error", false);
      bindV11MediaKeyboard(button, function() {
        window.playV11Audio(button, selector);
      });
      if (!audio || audio.getAttribute("data-v11-state-bound")) return;
      audio.addEventListener("play", function() {
        setV11AudioState(button, "playing", false);
      });
      audio.addEventListener("ended", function() {
        setV11AudioState(button, "ended", true);
      });
      audio.addEventListener("error", function() {
        setV11AudioState(button, "error", true);
      });
      audio.setAttribute("data-v11-state-bound", "1");
    });
  }


  function setupV11Videos() {
    document.querySelectorAll(".v11-video-stage").forEach(function(stage) {
      var video = stage.querySelector("video");
      if (!video) return;
      if (!stage.getAttribute("role")) stage.setAttribute("role", "button");
      if (!stage.getAttribute("tabindex")) stage.setAttribute("tabindex", "0");
      if (!stage.getAttribute("aria-label")) stage.setAttribute("aria-label", "播放视频复读");
      bindV11MediaKeyboard(stage, function() {
        window.toggleV11Video(stage);
      });
      video.loop = true;
      video.muted = false;
      video.playsInline = true;
      if (!video.getAttribute("data-v11-state-bound")) {
        video.addEventListener("error", function() {
          setV11VideoState(stage, "error", true);
        });
        video.setAttribute("data-v11-state-bound", "1");
      }
      setV11VideoState(stage, "idle", false);
    });
  }

  function setupV11TextSizing() {
    document.querySelectorAll(".v11-answer-title").forEach(function(title) {
      var text = (title.textContent || "").trim();
      var words = text.split(/\\s+/).filter(Boolean).length;
      if (text.length >= 38 || words >= 6) {
        title.classList.add("is-very-long");
      } else if (text.length >= 24 || words >= 4) {
        title.classList.add("is-long");
      }
    });
  }

  function setupV11Card() {
    pauseOtherMedia(null);
    setupV11AudioButtons();
    setupV11Videos();
    setupV11TextSizing();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", setupV11Card);
  } else {
    setupV11Card();
  }
})();
</script>
"""


LANGUAGE_FRONT_TEMPLATE_V11 = """
<div class="v11-card v11-front layout-{{CardLayout}} learning-hierarchy-system">
  <div class="v11-top">
    <span class="v11-pill">▮ 复读卡</span>
    <span class="v11-time">{{SourceTime}}</span>
  </div>
  <section class="v11-front-copy recall-task">
    <h1>{{FrontPrompt}}</h1>
    {{#FrontContent}}<p>{{FrontContent}}</p>{{/FrontContent}}
  </section>
  {{#Video}}
  <section class="v11-video-stage evidence-anchor" onclick="toggleV11Video(this)" role="button" tabindex="0" aria-label="点击播放视频" aria-pressed="false">
    {{Video}}
    <span class="v11-video-toggle">▶</span>
    <span class="v11-video-cue">点击播放视频</span>
  </section>
  {{/Video}}
  <section class="v11-sound-actions">
    {{#Audio}}<span class="v11-media-source audio-original">{{Audio}}</span><button class="v11-sound-button" data-media-selector=".audio-original" data-media-role="original" data-media-state="idle" aria-pressed="false" onclick="playV11Audio(this, '.audio-original')"><span class="v11-play">▶</span><span class="v11-button-label">播放原声</span></button>{{/Audio}}
    {{#TtsAudio}}<span class="v11-media-source audio-slow">{{TtsAudio}}</span><button class="v11-sound-button" data-media-selector=".audio-slow" data-media-role="slow" data-media-state="idle" aria-pressed="false" onclick="playV11Audio(this, '.audio-slow')"><span class="v11-play">▶</span><span class="v11-button-label">播放慢读</span></button>{{/TtsAudio}}
  </section>
  <span class="v11-live-status" aria-live="polite"></span>
</div>
""" + V11_CARD_SCRIPT


LANGUAGE_BACK_TEMPLATE_V11 = """
<div class="v11-card v11-back layout-{{CardLayout}} learning-hierarchy-system">
  <div class="v11-top">
    <span class="v11-pill">▮ 复读卡</span>
    {{#Difficulty}}<span class="v11-difficulty">{{Difficulty}}</span>{{/Difficulty}}
  </div>
  <section class="v11-answer-layout answer-anchor">
    <div class="v11-answer-main">
      <div class="v11-time">{{SourceTime}}</div>
      <div class="v11-label">{{CardType}}</div>
      <div class="v11-phrase-line">
        <h1 class="v11-answer-title">{{Answer}}</h1>
        {{#PhraseTtsAudio}}<span class="v11-media-source audio-phrase">{{PhraseTtsAudio}}</span><button class="v11-speaker" data-media-selector=".audio-phrase" data-media-role="phrase" data-media-state="idle" aria-label="播放表达发音" aria-pressed="false" title="播放表达发音" onclick="playV11Audio(this, '.audio-phrase')">▶</button>{{/PhraseTtsAudio}}
      </div>
      {{#Chinese}}<p class="v11-chinese-core">{{#ChineseDisplay}}{{ChineseDisplay}}{{/ChineseDisplay}}{{^ChineseDisplay}}{{Chinese}}{{/ChineseDisplay}}</p>{{/Chinese}}
      {{#ChineseFeel}}<p class="v11-answer-note">{{#ChineseFeelDisplay}}{{ChineseFeelDisplay}}{{/ChineseFeelDisplay}}{{^ChineseFeelDisplay}}{{ChineseFeel}}{{/ChineseFeelDisplay}}</p>{{/ChineseFeel}}
      <div class="v11-pronunciation">
        {{#PhoneticIpa}}<div class="v11-ipa-row is-standard"><span>标准读法{{#StandardPronunciationHint}}（{{StandardPronunciationHint}}）{{/StandardPronunciationHint}}</span><strong>{{PhoneticIpa}}</strong></div>{{/PhoneticIpa}}
        {{#SpokenIpa}}<div class="v11-ipa-row is-spoken"><span>{{SpokenPronunciationLabel}}</span><strong>{{SpokenIpa}}</strong></div>{{/SpokenIpa}}
        {{^SpokenIpa}}{{#PronunciationStatus}}<div class="v11-ipa-row is-spoken is-status"><span>{{SpokenPronunciationLabel}}</span><strong>{{PronunciationStatus}}</strong></div>{{/PronunciationStatus}}{{/SpokenIpa}}
        {{#SpokenIpa}}{{#PronunciationStatus}}<div class="v11-ipa-row is-spoken is-status"><span>读法状态</span><strong>{{PronunciationStatus}}</strong></div>{{/PronunciationStatus}}{{/SpokenIpa}}
        {{#PronunciationNote}}<div class="v11-pronunciation-note"><span>发音说明</span><p>{{#PronunciationNoteDisplay}}{{PronunciationNoteDisplay}}{{/PronunciationNoteDisplay}}{{^PronunciationNoteDisplay}}{{PronunciationNote}}{{/PronunciationNoteDisplay}}</p></div>{{/PronunciationNote}}
      </div>
      <hr class="v11-divider">
      <section class="v11-source-block evidence-anchor">
        <div class="v11-source-label">原句</div>
        {{#EnglishDisplay}}<p class="v11-source">{{EnglishDisplay}}</p>{{/EnglishDisplay}}
        {{^EnglishDisplay}}<p class="v11-source">{{English}}</p>{{/EnglishDisplay}}
        {{#SourceSpokenIpa}}<p class="v11-source-ipa"><span>推测原句读法</span><strong>{{SourceSpokenIpa}}</strong></p>{{/SourceSpokenIpa}}
        {{^SourceSpokenIpa}}{{#SourcePronunciationStatus}}<p class="v11-source-ipa is-status"><span>推测原句读法</span><strong>{{SourcePronunciationStatus}}</strong></p>{{/SourcePronunciationStatus}}{{/SourceSpokenIpa}}
        {{#Context}}<p class="v11-source-translation">{{#ContextDisplay}}{{ContextDisplay}}{{/ContextDisplay}}{{^ContextDisplay}}{{Context}}{{/ContextDisplay}}</p>{{/Context}}
      </section>
      <div class="v11-sound-actions is-left">
        {{#Audio}}<span class="v11-media-source audio-original">{{Audio}}</span><button class="v11-sound-button" data-media-selector=".audio-original" data-media-role="original" data-media-state="idle" aria-pressed="false" onclick="playV11Audio(this, '.audio-original')"><span class="v11-play">▶</span><span class="v11-button-label">播放原声</span></button>{{/Audio}}
        {{#TtsAudio}}<span class="v11-media-source audio-slow">{{TtsAudio}}</span><button class="v11-sound-button" data-media-selector=".audio-slow" data-media-role="slow" data-media-state="idle" aria-pressed="false" onclick="playV11Audio(this, '.audio-slow')"><span class="v11-play">▶</span><span class="v11-button-label">播放慢读</span></button>{{/TtsAudio}}
      </div>
    </div>
    {{#Video}}
    <div class="v11-video-stage evidence-anchor" onclick="toggleV11Video(this)" role="button" tabindex="0" aria-label="点击播放视频" aria-pressed="false">
      {{Video}}
      <span class="v11-video-toggle">▶</span>
      <span class="v11-video-cue">点击播放视频</span>
    </div>
    {{/Video}}
  </section>
  <section class="v11-info-grid">
    {{#Definition}}<div class="v11-info-block understanding-block"><div class="v11-info-head"><span class="v11-icon">?</span><strong>怎么用</strong></div><p>{{#DefinitionDisplay}}{{DefinitionDisplay}}{{/DefinitionDisplay}}{{^DefinitionDisplay}}{{Definition}}{{/DefinitionDisplay}}</p></div>{{/Definition}}
    {{#TeacherNote}}<div class="v11-info-block boundary-block"><div class="v11-info-head"><span class="v11-icon">!</span><strong>别误用</strong></div><p>{{#TeacherNoteDisplay}}{{TeacherNoteDisplay}}{{/TeacherNoteDisplay}}{{^TeacherNoteDisplay}}{{TeacherNote}}{{/TeacherNoteDisplay}}</p></div>{{/TeacherNote}}
  </section>
  {{#TransferExamplesDisplay}}<section class="v11-example-block transfer-block"><div class="v11-info-head"><span class="v11-icon">↗</span><strong>例句与迁移</strong></div>{{TransferExamplesDisplay}}</section>{{/TransferExamplesDisplay}}
  <span class="v11-live-status" aria-live="polite"></span>
</div>
""" + V11_CARD_SCRIPT


CARD_CSS_V11_FAST = CARD_CSS_V11 + """
.fast-review-card .v11-top { margin-bottom: clamp(12px, 2.4vw, 18px); }
.fast-review-card .v11-pill { background: rgba(52, 199, 89, 0.13); color: #16783a; }
.fast-review-card .fast-answer-focus {
  margin-top: clamp(14px, 2.8vw, 22px);
  padding: clamp(20px, 4vw, 34px);
  border: 1px solid rgba(60, 60, 67, 0.12);
  border-radius: 26px;
  background: linear-gradient(180deg, #ffffff 0%, #f7fbff 100%);
}
.fast-review-card .fast-answer-title {
  margin: 0;
  color: #0b0c10;
  font-size: clamp(40px, 8vw, 78px);
  line-height: 1.02;
  font-weight: 950;
  letter-spacing: -0.055em;
  overflow-wrap: break-word;
}
.fast-review-card .fast-meaning {
  margin: 12px 0 0;
  color: #0057c2;
  font-size: clamp(21px, 4vw, 31px);
  line-height: 1.32;
  font-weight: 820;
}
.fast-review-card .fast-context {
  margin: 12px 0 0;
  color: #5f626b;
  font-size: clamp(17px, 3vw, 22px);
  line-height: 1.42;
  font-weight: 640;
}
.fast-review-card .fast-audio-row {
  margin-top: 14px;
}
.fast-review-card .v11-video-stage video {
  max-height: min(36vh, 320px);
}
"""


LANGUAGE_FRONT_TEMPLATE_V11_FAST = """
<div class="v11-card v11-front fast-review-card layout-{{CardLayout}} learning-hierarchy-system">
  <div class="v11-top">
    <span class="v11-pill">▮ 快速背卡</span>
    <span class="v11-time">{{SourceTime}}</span>
  </div>
  <section class="v11-front-copy recall-task">
    <h1>{{FrontPrompt}}</h1>
    {{#FrontContent}}<p>{{FrontContent}}</p>{{/FrontContent}}
  </section>
  {{#Video}}
  <section class="v11-video-stage evidence-anchor" onclick="toggleV11Video(this)" role="button" tabindex="0" aria-label="点击播放视频" aria-pressed="false">
    {{Video}}
    <span class="v11-video-toggle">▶</span>
    <span class="v11-video-cue">点击播放视频</span>
  </section>
  {{/Video}}
  <section class="v11-sound-actions">
    {{#Audio}}<span class="v11-media-source audio-original">{{Audio}}</span><button class="v11-sound-button" data-media-selector=".audio-original" data-media-role="original" data-media-state="idle" aria-pressed="false" onclick="playV11Audio(this, '.audio-original')"><span class="v11-play">▶</span><span class="v11-button-label">播放原声</span></button>{{/Audio}}
    {{#TtsAudio}}<span class="v11-media-source audio-slow">{{TtsAudio}}</span><button class="v11-sound-button" data-media-selector=".audio-slow" data-media-role="slow" data-media-state="idle" aria-pressed="false" onclick="playV11Audio(this, '.audio-slow')"><span class="v11-play">▶</span><span class="v11-button-label">播放慢读</span></button>{{/TtsAudio}}
  </section>
  <span class="v11-live-status" aria-live="polite"></span>
</div>
""" + V11_CARD_SCRIPT


LANGUAGE_BACK_TEMPLATE_V11_FAST = """
<div class="v11-card v11-back fast-review-card layout-{{CardLayout}} learning-hierarchy-system">
  <div class="v11-top">
    <span class="v11-pill">▮ 快速背卡</span>
    {{#Difficulty}}<span class="v11-difficulty">{{Difficulty}}</span>{{/Difficulty}}
  </div>
  <section class="fast-answer-focus answer-anchor">
    <div class="v11-label">{{CardType}}</div>
    <div class="v11-phrase-line">
      <h1 class="fast-answer-title">{{Answer}}</h1>
      {{#PhraseTtsAudio}}<span class="v11-media-source audio-phrase">{{PhraseTtsAudio}}</span><button class="v11-speaker" data-media-selector=".audio-phrase" data-media-role="phrase" data-media-state="idle" aria-label="播放表达发音" aria-pressed="false" title="播放表达发音" onclick="playV11Audio(this, '.audio-phrase')">▶</button>{{/PhraseTtsAudio}}
    </div>
    {{#Chinese}}<p class="fast-meaning"><strong>语境义</strong>：{{#ChineseDisplay}}{{ChineseDisplay}}{{/ChineseDisplay}}{{^ChineseDisplay}}{{Chinese}}{{/ChineseDisplay}}</p>{{/Chinese}}
    {{#ChineseFeel}}<p class="fast-context">{{#ChineseFeelDisplay}}{{ChineseFeelDisplay}}{{/ChineseFeelDisplay}}{{^ChineseFeelDisplay}}{{ChineseFeel}}{{/ChineseFeelDisplay}}</p>{{/ChineseFeel}}
    {{#EnglishDisplay}}<p class="fast-context evidence-anchor">{{EnglishDisplay}}</p>{{/EnglishDisplay}}
    {{^EnglishDisplay}}{{#English}}<p class="fast-context evidence-anchor">{{English}}</p>{{/English}}{{/EnglishDisplay}}
    <div class="v11-sound-actions is-left fast-audio-row">
      {{#Audio}}<span class="v11-media-source audio-original">{{Audio}}</span><button class="v11-sound-button" data-media-selector=".audio-original" data-media-role="original" data-media-state="idle" aria-pressed="false" onclick="playV11Audio(this, '.audio-original')"><span class="v11-play">▶</span><span class="v11-button-label">播放原声</span></button>{{/Audio}}
      {{#TtsAudio}}<span class="v11-media-source audio-slow">{{TtsAudio}}</span><button class="v11-sound-button" data-media-selector=".audio-slow" data-media-role="slow" data-media-state="idle" aria-pressed="false" onclick="playV11Audio(this, '.audio-slow')"><span class="v11-play">▶</span><span class="v11-button-label">播放慢读</span></button>{{/TtsAudio}}
    </div>
  </section>
  {{#Video}}
  <section class="v11-video-stage evidence-anchor" onclick="toggleV11Video(this)" role="button" tabindex="0" aria-label="点击播放视频" aria-pressed="false">
    {{Video}}
    <span class="v11-video-toggle">▶</span>
    <span class="v11-video-cue">点击播放视频</span>
  </section>
  {{/Video}}
  <span class="v11-live-status" aria-live="polite"></span>
</div>
""" + V11_CARD_SCRIPT


CARD_CSS_CIBA_V1 = CARD_CSS_V11 + """
.card {
  background: #f6f5f1 !important;
  color: #25211d !important;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Noto Sans SC", "Microsoft YaHei UI", sans-serif !important;
  padding: clamp(12px, 2.6vw, 24px) !important;
}
.ciba-card {
  --ciba-paper: #fbfaf7;
  --ciba-surface: #ffffff;
  --ciba-ink: #25211d;
  --ciba-muted: #706a63;
  --ciba-line: rgba(49, 48, 46, 0.12);
  --ciba-soft: #f4f1ec;
  --ciba-blue: #0b6fcb;
  --ciba-green: #2a8c62;
  --ciba-amber: #b56a19;
  width: min(880px, calc(100vw - 18px));
  margin: 0 auto;
  padding: clamp(18px, 3.4vw, 34px);
  border: 1px solid var(--ciba-line);
  border-radius: clamp(22px, 4vw, 34px);
  background: linear-gradient(180deg, #ffffff 0%, var(--ciba-paper) 100%);
  box-shadow:
    0 24px 70px rgba(49, 48, 46, 0.10),
    0 8px 24px rgba(49, 48, 46, 0.06),
    inset 0 1px 0 rgba(255, 255, 255, 0.82);
  overflow: hidden;
}
.ciba-top {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  justify-content: space-between;
  color: var(--ciba-muted);
}
.ciba-pill,
.ciba-difficulty,
.ciba-time {
  display: inline-flex;
  align-items: center;
  min-height: 30px;
  border-radius: 999px;
  font-size: clamp(12px, 2.2vw, 14px);
  line-height: 1;
  font-weight: 720;
  letter-spacing: 0.02em;
}
.ciba-pill {
  padding: 7px 12px;
  background: #f2f8ff;
  color: var(--ciba-blue);
  border: 1px solid rgba(11, 111, 203, 0.12);
}
.ciba-difficulty {
  padding: 7px 12px;
  background: #fff6e8;
  color: var(--ciba-amber);
  border: 1px solid rgba(181, 106, 25, 0.12);
}
.ciba-time {
  color: #8b837a;
  font-weight: 650;
}
.ciba-focus-card {
  position: relative;
  margin-top: clamp(12px, 2.4vw, 20px);
  padding: clamp(18px, 3.4vw, 30px);
  border: 1px solid rgba(49, 48, 46, 0.10);
  border-radius: clamp(20px, 3.6vw, 30px);
  background:
    radial-gradient(circle at 12% 0%, rgba(11, 111, 203, 0.10), transparent 30%),
    linear-gradient(135deg, #ffffff 0%, #fffdfa 58%, #f6f1ea 100%);
  box-shadow:
    0 14px 36px rgba(49, 48, 46, 0.07),
    inset 0 1px 0 rgba(255, 255, 255, 0.86);
}
.ciba-front .ciba-focus-card {
  min-height: clamp(170px, 34vw, 260px);
  display: flex;
  flex-direction: column;
  justify-content: center;
}
.ciba-kicker,
.ciba-label,
.ciba-section-label {
  margin: 0 0 9px;
  color: var(--ciba-muted);
  font-size: clamp(13px, 2.3vw, 15px);
  line-height: 1.3;
  font-weight: 760;
  letter-spacing: 0.04em;
}
.ciba-front-copy h1,
.ciba-answer-block h1 {
  margin: 0;
  color: var(--ciba-ink);
  font-size: clamp(29px, 5.0vw, 49px);
  line-height: 1.08;
  font-weight: 820;
  letter-spacing: -0.045em;
  overflow-wrap: break-word;
}
.ciba-front-copy p,
.ciba-answer-note,
.ciba-source-context {
  color: var(--ciba-muted);
}
.ciba-front-copy p,
.ciba-answer-note {
  margin: 13px 0 0;
  max-width: 48em;
  font-size: clamp(15px, 2.7vw, 18px);
  line-height: 1.58;
  font-weight: 520;
}
.ciba-answer-block h1 {
  color: #181511;
  font-size: clamp(31px, 5.2vw, 53px);
}
.ciba-answer-note {
  color: #5f5a53;
  font-weight: 620;
}
.ciba-video-stage {
  margin-top: clamp(10px, 2.2vw, 16px);
  border: 1px solid rgba(49, 48, 46, 0.14);
  border-radius: clamp(16px, 2.8vw, 22px);
  background: #090807;
  overflow: hidden;
  box-shadow: 0 10px 28px rgba(49, 48, 46, 0.11);
}
.ciba-video-stage video {
  display: block;
  width: 100%;
  aspect-ratio: 16 / 9;
  max-height: min(38vh, 340px);
  background: #000;
  object-fit: cover;
}
.ciba-media-row,
.ciba-audio-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin-top: 10px;
}
.ciba-audio-item {
  flex: 1 1 210px;
  min-width: 0;
  padding: 10px 12px;
  border: 1px solid rgba(49, 48, 46, 0.10);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.72);
}
.ciba-audio-item strong {
  display: block;
  margin-bottom: 7px;
  color: #5f5a53;
  font-size: 12px;
  font-weight: 760;
  letter-spacing: 0.04em;
}
.ciba-audio-item audio {
  width: 100%;
}
.ciba-inline-audio-row {
  margin-top: 10px;
  gap: 8px;
}
.ciba-compact-audio-item {
  flex: 0 1 auto;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  width: auto;
  max-width: 100%;
  padding: 7px 10px;
  border-radius: 999px;
}
.ciba-compact-audio-item strong {
  display: inline;
  margin: 0;
  font-size: 11px;
  white-space: nowrap;
}
.ciba-compact-audio-item audio {
  width: 132px;
  max-width: 46vw;
}
.ciba-back .ciba-video-stage video {
  max-height: min(32vh, 280px);
}
.ciba-learning-group {
  margin-top: clamp(14px, 2.8vw, 22px);
  padding: clamp(12px, 2.4vw, 16px);
  border: 1px solid rgba(49, 48, 46, 0.08);
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.42);
}
.ciba-core-group {
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.62) 0%, rgba(250, 247, 240, 0.50) 100%);
}
.ciba-transfer-group {
  margin-top: clamp(16px, 3vw, 24px);
  background: rgba(255, 253, 248, 0.34);
}
.ciba-group-label {
  display: inline-flex;
  align-items: center;
  margin: 0 0 11px;
  padding: 5px 10px;
  border-radius: 999px;
  background: rgba(37, 33, 29, 0.07);
  color: var(--ciba-muted);
  font-size: 12px;
  line-height: 1;
  font-weight: 820;
  letter-spacing: 0.08em;
}
.ciba-learning-group .ciba-priority-grid,
.ciba-learning-group .ciba-study-stack {
  margin-top: 0;
}
.ciba-priority-grid {
  display: grid;
  grid-template-columns: minmax(0, 0.92fr) minmax(0, 1.08fr);
  gap: clamp(12px, 2.4vw, 16px);
  margin-top: clamp(14px, 2.6vw, 20px);
}
.ciba-essential-block,
.ciba-note-row,
.ciba-listening-block,
.ciba-conceptual-block,
.ciba-source-block {
  border: 1px solid rgba(49, 48, 46, 0.10);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.74);
  box-shadow: 0 1px 0 rgba(49, 48, 46, 0.03);
}
.ciba-essential-block {
  min-height: 126px;
  padding: clamp(17px, 2.8vw, 22px);
}
.ciba-essential-block strong,
.ciba-note-row strong,
.ciba-listening-block strong,
.ciba-conceptual-block strong,
.ciba-source-block strong {
  display: block;
  color: #332f2a;
  font-size: clamp(14px, 2.5vw, 16px);
  line-height: 1.25;
  font-weight: 820;
  letter-spacing: 0.015em;
}
.ciba-essential-block p,
.ciba-note-row p,
.ciba-listening-block p,
.ciba-conceptual-block p,
.ciba-source-block p {
  margin: 8px 0 0;
  color: #4d4842;
  font-size: clamp(16px, 2.8vw, 18px);
  line-height: 1.62;
  white-space: pre-line;
  overflow-wrap: break-word;
}
.ciba-meaning-block {
  background: linear-gradient(180deg, #f4f9ff 0%, #ffffff 100%);
}
.ciba-action-block {
  background: linear-gradient(180deg, #f4fbf7 0%, #ffffff 100%);
}
.ciba-conceptual-stack {
  display: grid;
  gap: 10px;
  margin-top: 12px;
}
.ciba-conceptual-block {
  padding: clamp(13px, 2.3vw, 17px) clamp(15px, 2.7vw, 19px);
  background: #fffaf2;
}
.ciba-trap-block {
  background: #fff7ed;
}
.ciba-trap-block strong {
  color: #8a4f11;
}
.ciba-study-stack {
  display: grid;
  gap: 10px;
  margin-top: 12px;
}
.ciba-note-row {
  display: grid;
  grid-template-columns: minmax(92px, 0.24fr) minmax(0, 1fr);
  gap: 12px;
  align-items: start;
  padding: clamp(14px, 2.4vw, 18px) clamp(16px, 2.8vw, 20px);
}
.ciba-note-row strong {
  margin-top: 2px;
  color: #5d574f;
}
.ciba-note-row p {
  margin-top: 0;
}
.ciba-note-row p,
.ciba-listening-block p {
  font-size: clamp(15px, 2.5vw, 16px);
  line-height: 1.56;
}
.ciba-warning-block {
  background: #fff9ef;
}
.ciba-warning-block strong {
  color: #8a4f11;
}
.ciba-listening-block {
  margin-top: 10px;
  padding: clamp(14px, 2.4vw, 18px) clamp(16px, 2.8vw, 20px);
  background: #f7f6fb;
}
.ciba-source-block {
  margin-top: clamp(10px, 2.2vw, 16px);
  padding: clamp(14px, 2.4vw, 19px);
  background: #302d29;
  color: #fffdf8;
  border-color: rgba(255, 255, 255, 0.10);
  box-shadow: 0 18px 44px rgba(49, 48, 46, 0.16);
}
.ciba-source-block strong {
  color: rgba(255, 253, 248, 0.72);
}
.ciba-source {
  color: #fffdf8 !important;
  font-size: clamp(20px, 3.6vw, 30px) !important;
  line-height: 1.28 !important;
  font-weight: 720 !important;
  letter-spacing: -0.015em;
}
.ciba-source-context {
  margin-top: 12px !important;
  padding-top: 12px;
  border-top: 1px solid rgba(255, 255, 255, 0.13);
  color: rgba(255, 253, 248, 0.72) !important;
}
.ciba-source-meta {
  display: inline-flex;
  margin-top: 12px;
  color: rgba(255, 253, 248, 0.56);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.04em;
}
@media (max-width: 760px) {
  .card { padding: 8px !important; }
  .ciba-card {
    width: calc(100vw - 16px);
    padding: clamp(16px, 4.6vw, 22px);
    border-radius: 24px;
  }
  .ciba-front .ciba-focus-card {
    min-height: 160px;
  }
  .ciba-front-copy h1,
  .ciba-answer-block h1 {
    font-size: clamp(25px, 7.4vw, 35px);
    letter-spacing: -0.032em;
  }
  .ciba-priority-grid {
    grid-template-columns: 1fr;
  }
  .ciba-learning-group {
    padding: 12px;
    border-radius: 20px;
  }
  .ciba-group-label {
    margin-bottom: 10px;
  }
  .ciba-note-row {
    grid-template-columns: 1fr;
    gap: 4px;
  }
  .ciba-video-stage video {
    max-height: min(24vh, 190px);
    aspect-ratio: 16 / 9;
  }
}
.ciba-style-warm-paper {
  display: none;
}
"""


CARD_CSS_CIBA_MINIMAL_WHITE = CARD_CSS_CIBA_V1 + """
.ciba-style-minimal-white { display: none; }
.card {
  background: #f7f8fb !important;
  color: #1f2328 !important;
}
.ciba-card {
  --ciba-paper: #ffffff;
  --ciba-surface: #ffffff;
  --ciba-ink: #1f2328;
  --ciba-muted: #667085;
  --ciba-line: rgba(31, 35, 40, 0.12);
  --ciba-blue: #2563eb;
  --ciba-green: #168a5b;
  --ciba-amber: #a16207;
  background: #ffffff;
  border-radius: clamp(18px, 3vw, 26px);
  box-shadow: 0 18px 44px rgba(16, 24, 40, 0.08);
}
.ciba-focus-card {
  background: #ffffff;
  box-shadow: none;
}
.ciba-meaning-block,
.ciba-action-block,
.ciba-listening-block,
.ciba-conceptual-block,
.ciba-learning-group {
  background: #ffffff;
}
.ciba-note-row,
.ciba-essential-block,
.ciba-listening-block,
.ciba-conceptual-block,
.ciba-learning-group {
  border-color: rgba(31, 35, 40, 0.10);
  box-shadow: none;
}
.ciba-group-label {
  background: #f3f5f7;
}
.ciba-source-block {
  background: #f3f5f7;
  color: #1f2328;
  border-color: rgba(31, 35, 40, 0.10);
  box-shadow: none;
}
.ciba-source-block strong,
.ciba-source-meta {
  color: #667085;
}
.ciba-source {
  color: #1f2328 !important;
}
.ciba-source-context {
  border-top-color: rgba(31, 35, 40, 0.10);
  color: #667085 !important;
}
"""


CARD_CSS_CIBA_DARK_IMMERSIVE = CARD_CSS_CIBA_V1 + """
.ciba-style-dark-immersive { display: none; }
.card {
  background: #0d1117 !important;
  color: #f8f3ea !important;
}
.ciba-card {
  --ciba-paper: #111827;
  --ciba-surface: #161b22;
  --ciba-ink: #f8f3ea;
  --ciba-muted: #aeb7c4;
  --ciba-line: rgba(255, 255, 255, 0.12);
  --ciba-blue: #7db7ff;
  --ciba-green: #8ee0b7;
  --ciba-amber: #f3c57a;
  background: radial-gradient(circle at 18% 0%, rgba(125, 183, 255, 0.14), transparent 34%), linear-gradient(180deg, #151b24 0%, #0f141b 100%);
  border-color: rgba(255, 255, 255, 0.12);
  box-shadow: 0 28px 80px rgba(0, 0, 0, 0.38);
}
.ciba-pill {
  background: rgba(125, 183, 255, 0.13);
  color: #cfe5ff;
  border-color: rgba(125, 183, 255, 0.18);
}
.ciba-difficulty {
  background: rgba(243, 197, 122, 0.12);
  color: #f3c57a;
  border-color: rgba(243, 197, 122, 0.20);
}
.ciba-focus-card,
.ciba-essential-block,
.ciba-note-row,
.ciba-listening-block,
.ciba-conceptual-block,
.ciba-learning-group {
  background: rgba(22, 27, 34, 0.88);
  border-color: rgba(255, 255, 255, 0.10);
  box-shadow: 0 12px 34px rgba(0, 0, 0, 0.20);
}
.ciba-front-copy h1,
.ciba-answer-block h1,
.ciba-essential-block strong,
.ciba-note-row strong,
.ciba-listening-block strong,
.ciba-conceptual-block strong {
  color: #f8f3ea;
}
.ciba-front-copy p,
.ciba-answer-note,
.ciba-kicker,
.ciba-label,
.ciba-time,
.ciba-group-label,
.ciba-note-row p,
.ciba-listening-block p,
.ciba-essential-block p,
.ciba-conceptual-block p {
  color: #aeb7c4;
}
.ciba-meaning-block {
  background: rgba(31, 58, 91, 0.44);
}
.ciba-action-block {
  background: rgba(28, 73, 55, 0.38);
}
.ciba-core-group,
.ciba-transfer-group {
  background: rgba(255, 255, 255, 0.045);
  border-color: rgba(255, 255, 255, 0.07);
  box-shadow: none;
}
.ciba-transfer-group {
  margin-top: clamp(18px, 4vw, 28px);
}
.ciba-group-label {
  background: rgba(125, 183, 255, 0.10);
  color: #d7e6f6;
}
.ciba-conceptual-block {
  background: rgba(255, 255, 255, 0.055);
}
.ciba-trap-block {
  background: rgba(243, 197, 122, 0.11);
}
.ciba-trap-block strong {
  color: #d9aa64;
}
.ciba-warning-block {
  background: rgba(94, 63, 27, 0.34);
}
.ciba-warning-block strong {
  color: #f3c57a;
}
.ciba-source-block {
  background: #05070a;
  border-color: rgba(255, 255, 255, 0.12);
}
.ciba-source {
  color: #ffffff !important;
}
.ciba-source-context {
  color: #aeb7c4 !important;
}
.ciba-audio-item {
  background: rgba(255, 255, 255, 0.07);
  border-color: rgba(255, 255, 255, 0.11);
}
.ciba-audio-item strong {
  color: #c8d1dc;
}
"""


CARD_CSS_CIBA_BY_STYLE = {
    "warm_paper": CARD_CSS_CIBA_V1,
    "minimal_white": CARD_CSS_CIBA_MINIMAL_WHITE,
    "dark_immersive": CARD_CSS_CIBA_DARK_IMMERSIVE,
}


LANGUAGE_FRONT_TEMPLATE_CIBA_V1 = """
<div class="ciba-card ciba-front layout-{{CardLayout}} learning-hierarchy-system">
  <header class="ciba-top">
    <span class="ciba-pill">语言动作卡</span>
    <span class="ciba-time">{{SourceTime}}</span>
  </header>

  <section class="ciba-focus-card ciba-front-copy recall-task">
    <div class="ciba-kicker">{{FrontKicker}}</div>
    <h1>{{FrontPrompt}}</h1>
    {{#FrontContent}}<p>{{FrontContent}}</p>{{/FrontContent}}
  </section>

  {{#Video}}<section class="ciba-video-stage evidence-anchor">{{Video}}</section>{{/Video}}
  <section class="ciba-media-row">
    {{#Audio}}<div class="ciba-audio-item"><strong>原声线索</strong>{{Audio}}</div>{{/Audio}}
    {{#TtsAudio}}<div class="ciba-audio-item"><strong>整句慢读</strong>{{TtsAudio}}</div>{{/TtsAudio}}
  </section>
</div>
"""


LANGUAGE_BACK_TEMPLATE_CIBA_V1 = """
<div class="ciba-card ciba-back layout-{{CardLayout}} learning-hierarchy-system">
  <header class="ciba-top">
    <span class="ciba-pill">词霸天下 · V1.2</span>
    {{#Difficulty}}<span class="ciba-difficulty">{{Difficulty}}</span>{{/Difficulty}}
  </header>

  <section class="ciba-focus-card ciba-answer-block answer-anchor">
    <div class="ciba-label">核心答案</div>
    <h1>{{Answer}}</h1>
    {{#ChineseFeel}}<p class="ciba-answer-note">{{ChineseFeel}}</p>{{/ChineseFeel}}
    {{#PhraseTtsAudio}}<div class="ciba-audio-row ciba-inline-audio-row ciba-answer-audio-row"><div class="ciba-audio-item ciba-compact-audio-item"><strong>表达</strong>{{PhraseTtsAudio}}</div></div>{{/PhraseTtsAudio}}
  </section>

  <section class="ciba-source-block evidence-anchor">
    <strong>原句场景</strong>
    <p class="ciba-source">{{English}}</p>
    {{#Video}}<div class="ciba-video-stage">{{Video}}</div>{{/Video}}
    {{#Context}}<p class="ciba-source-context">{{Context}}</p>{{/Context}}
    <div class="ciba-audio-row ciba-inline-audio-row">
      {{#Audio}}<div class="ciba-audio-item ciba-compact-audio-item"><strong>原声</strong>{{Audio}}</div>{{/Audio}}
      {{#TtsAudio}}<div class="ciba-audio-item ciba-compact-audio-item"><strong>慢读</strong>{{TtsAudio}}</div>{{/TtsAudio}}
    </div>
    <span class="ciba-source-meta">{{SourceTime}}</span>
  </section>

  <section class="ciba-core-group ciba-learning-group understanding-block">
    <div class="ciba-group-label">理解核心</div>
    <section class="ciba-priority-grid">
      {{#Chinese}}<article class="ciba-essential-block ciba-meaning-block"><strong>语境义</strong><p>{{Chinese}}</p></article>{{/Chinese}}
      {{#Definition}}<article class="ciba-essential-block ciba-action-block"><strong>语言动作</strong><p>{{Definition}}</p></article>{{/Definition}}
    </section>

    <section class="ciba-conceptual-stack">
      {{#ConceptualAction}}<article class="ciba-conceptual-block"><strong>概念动作感</strong><p>{{ConceptualAction}}</p></article>{{/ConceptualAction}}
      {{#ChineseLearnerTrap}}<article class="ciba-conceptual-block ciba-trap-block"><strong>易混表达与区别</strong><p>{{ChineseLearnerTrap}}</p></article>{{/ChineseLearnerTrap}}
    </section>
  </section>

  <section class="ciba-transfer-group ciba-learning-group transfer-block">
    <div class="ciba-group-label">迁移使用</div>
    <section class="ciba-study-stack">
      {{#Why}}<article class="ciba-note-row"><strong>为什么选它</strong><p>{{Why}}</p></article>{{/Why}}
      {{#Collocations}}<article class="ciba-note-row"><strong>迁移句</strong><p>{{Collocations}}</p></article>{{/Collocations}}
      {{#TeacherNote}}<article class="ciba-note-row ciba-warning-block boundary-block"><strong>搭配边界 / 别这么用</strong><p>{{TeacherNote}}</p></article>{{/TeacherNote}}
    </section>
  </section>

  {{#PronunciationNote}}<section class="ciba-listening-block"><strong>发音提示</strong><p>{{PronunciationNote}}</p></section>{{/PronunciationNote}}
  {{#SpokenIpa}}<section class="ciba-listening-block"><strong>{{SpokenPronunciationLabel}}</strong><p>{{SpokenIpa}}</p></section>{{/SpokenIpa}}
  {{^SpokenIpa}}{{#PronunciationStatus}}<section class="ciba-listening-block"><strong>{{SpokenPronunciationLabel}}</strong><p>{{PronunciationStatus}}</p></section>{{/PronunciationStatus}}{{/SpokenIpa}}
  {{#SourceSpokenIpa}}<section class="ciba-listening-block"><strong>推测原句读法</strong><p>{{SourceSpokenIpa}}</p></section>{{/SourceSpokenIpa}}
  {{^SourceSpokenIpa}}{{#SourcePronunciationStatus}}<section class="ciba-listening-block"><strong>推测原句读法</strong><p>{{SourcePronunciationStatus}}</p></section>{{/SourcePronunciationStatus}}{{/SourceSpokenIpa}}
</div>
"""


DICTIONARY_FRONT_TEMPLATE = MINIMAL_FRONT_TEMPLATE
DICTIONARY_BACK_TEMPLATE = READING_BACK_TEMPLATE
FRONT_TEMPLATE = LANGUAGE_FRONT_TEMPLATE
BACK_TEMPLATE = LANGUAGE_BACK_TEMPLATE


def anki_template_family(template_id: str, deck_kind_code: str, card_style: str = "warm_paper", review_density: str = "full") -> str:
    template_id = normalize_template_id(template_id)
    deck_kind_code = str(deck_kind_code or "")
    review_density = normalize_review_density(review_density)
    if deck_kind_code == "document_knowledge":
        return "document-knowledge"
    if deck_kind_code == "document_reading":
        return "document-reading"
    if template_id == "ciba_tianxia_v1":
        return f"language-ciba-tianxia-v1-{normalize_card_style(card_style)}"
    if template_id == "immersive_v11":
        return "language-immersive-v11-fast" if review_density == "fast" else "language-immersive-v11"
    return f"language-{template_id}"


def anki_template_assets(template_id: str, deck_kind_code: str = "video_language", card_style: str = "warm_paper", review_density: str = "full") -> tuple[str, str, str, str]:
    template_id = normalize_template_id(template_id)
    review_density = normalize_review_density(review_density)
    if deck_kind_code == "document_knowledge":
        return "文档知识 V10", CARD_CSS, KNOWLEDGE_FRONT_TEMPLATE, KNOWLEDGE_BACK_TEMPLATE
    if deck_kind_code == "document_reading":
        return "文档精读 V10", CARD_CSS, READING_FRONT_TEMPLATE, READING_BACK_TEMPLATE
    if template_id == "ciba_tianxia_v1":
        normalized_style = normalize_card_style(card_style)
        style_label = CIBA_CARD_STYLE_LABELS[normalized_style]
        return (
            f"词霸天下实验 V1 · {style_label}",
            CARD_CSS_CIBA_BY_STYLE[normalized_style],
            LANGUAGE_FRONT_TEMPLATE_CIBA_V1,
            LANGUAGE_BACK_TEMPLATE_CIBA_V1,
        )
    if template_id == "immersive_v11":
        if review_density == "fast":
            return "沉浸复读 V11 · 快速复读", CARD_CSS_V11_FAST, LANGUAGE_FRONT_TEMPLATE_V11_FAST, LANGUAGE_BACK_TEMPLATE_V11_FAST
        return "沉浸复读 V11", CARD_CSS_V11, LANGUAGE_FRONT_TEMPLATE_V11, LANGUAGE_BACK_TEMPLATE_V11
    if template_id == "dictionary":
        return "词典解释 V10", CARD_CSS, DICTIONARY_FRONT_TEMPLATE, DICTIONARY_BACK_TEMPLATE
    if template_id == "minimal":
        return "极简复习 V10", CARD_CSS, MINIMAL_FRONT_TEMPLATE, MINIMAL_BACK_TEMPLATE
    return "视频语言 V10", CARD_CSS, LANGUAGE_FRONT_TEMPLATE, LANGUAGE_BACK_TEMPLATE


def anki_template_version(template_id: str, deck_kind_code: str = "video_language") -> str:
    template_id = normalize_template_id(template_id)
    if deck_kind_code not in {"video_language", "subtitle_language"}:
        return "V10"
    if template_id == "immersive_v11":
        return "V15"
    if template_id == "ciba_tianxia_v1":
        return "V12"
    return "V10"


_ANKI_NOTE_TAG_RE = re.compile(r"[a-z0-9]+(?:_[a-z0-9]+)*")


def anki_note_tag_component(value: Any, fallback: str) -> str:
    """Return one deterministic, lowercase ASCII component safe for Anki tags."""

    raw = str(value or "").strip()
    ascii_value = (
        unicodedata.normalize("NFKD", raw)
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
    )
    component = re.sub(r"[^a-z0-9]+", "_", ascii_value).strip("_")
    if not component:
        component = (
            f"u_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:12]}"
            if raw
            else fallback
        )
    component = component[:64].rstrip("_")
    return component or fallback


def build_anki_note_tags(
    *,
    anki_tag: str,
    language: Any,
    level: Any,
    template_id: Any,
    card_type: Any,
    layout: Any,
) -> list[str]:
    """Build the frozen six-tag identity shared by the note and export ledger."""

    tags = [
        str(anki_tag),
        f"lang_{anki_note_tag_component(language, 'unknown')}",
        f"level_{anki_note_tag_component(level, 'unknown')}",
        f"template_{anki_note_tag_component(template_id, 'unknown')}",
        f"type_{anki_note_tag_component(card_type, 'card')}",
        f"layout_{anki_note_tag_component(layout, 'default')}",
    ]
    if (
        len(set(tags)) != 6
        or any(_ANKI_NOTE_TAG_RE.fullmatch(tag) is None for tag in tags)
    ):
        raise ValueError("Anki note tags must be six unique ASCII tag-safe values")
    return tags


def uses_v11_repetition_front(template_id: str, deck_kind_code: str = "video_language") -> bool:
    template_id = normalize_template_id(template_id)
    if deck_kind_code not in {"video_language", "subtitle_language"}:
        return False
    return template_id == "immersive_v11"


def retrieve_anki_media_bytes(filename: str, anki_url: str) -> bytes | None:
    if not filename or not anki_url:
        return None
    try:
        result = anki_connect("retrieveMediaFile", {"filename": filename}, anki_url)
    except Exception:
        return None
    if not isinstance(result, str) or not result:
        return None
    try:
        return decode_anki_media_base64(result)
    except (ValueError, RuntimeError):
        return None


def media_manifest(media_files: list[str], media_ledger: list[dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    return media_manifest_core(
        media_files,
        media_ledger,
        duration_seconds_func=audio_duration_seconds,
        phrase_max_duration_func=phrase_tts_max_duration_seconds,
    )


def persistent_cache_root() -> Path:
    return cache_persistent_cache_root(Path.cwd())


def tts_provider_scope(tts: dict[str, Any]) -> dict[str, str]:
    provider = provider_name(tts)
    default_region = gemini_vertex_location(tts) if provider in GEMINI_VERTEX_TTS_PROVIDERS else ""
    return cache_tts_provider_scope(tts, provider=provider, default_region=default_region)


@functools.lru_cache(maxsize=1)
def ffmpeg_cache_signature() -> str:
    try:
        executable = media_managed_tool_path("ffmpeg")
        completed = media_tool_version("ffmpeg", timeout=10)
        version = (completed.stdout.splitlines() or [""])[0].strip()
    except Exception:
        return "missing"
    return f"{executable}|{version}"


def audio_duration_seconds(path: Path) -> float | None:
    try:
        completed = media_policy_run_ffprobe(
            [
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
            ],
            path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            **hidden_subprocess_flags(),
        )
    except (MediaToolPolicyError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    try:
        duration = float((completed.stdout or "").strip())
    except (TypeError, ValueError):
        return None
    if not math.isfinite(duration) or duration <= 0:
        return None
    return duration


def tts_semantic_config(project: dict[str, Any]) -> dict[str, Any]:
    return semantic_tts_semantic_config(project)


def tts_semantic_verification_enabled(project: dict[str, Any]) -> bool:
    return semantic_tts_semantic_verification_enabled(project)


def tts_semantic_requires_export_pass(project: dict[str, Any], deck_kind_code: str = "") -> bool:
    return semantic_tts_semantic_requires_export_pass(project, deck_kind_code)


def transcribe_tts_audio_with_whisper_cli(audio_path: Path, config: dict[str, Any]) -> dict[str, Any]:
    whisper_exe = shutil.which(str(config.get("whisper_command") or "whisper"))
    if not whisper_exe:
        return {"ok": False, "provider": "whisper-cli", "reason": "whisper_cli_not_found"}
    model = str(config.get("whisper_model") or "tiny.en").strip()
    language = str(config.get("whisper_language") or "en").strip()
    timeout = int(config.get("asr_timeout_seconds") or config.get("whisper_timeout_seconds") or 120)
    with tempfile.TemporaryDirectory(prefix="acg_tts_asr_") as temp_dir:
        command = [
            whisper_exe,
            str(audio_path),
            "--model",
            model,
            "--language",
            language,
            "--output_format",
            "txt",
            "--output_dir",
            temp_dir,
        ]
        if os.name == "nt":
            command.extend(["--fp16", "False"])
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            **hidden_subprocess_flags(),
        )
        if completed.returncode != 0:
            return {
                "ok": False,
                "provider": "whisper-cli",
                "reason": "whisper_cli_failed",
                "error": (completed.stderr or completed.stdout or "").strip()[-500:],
            }
        txt_files = sorted(Path(temp_dir).glob("*.txt"))
        transcript = ""
        if txt_files:
            transcript = txt_files[0].read_text(encoding="utf-8", errors="replace").strip()
        if not transcript:
            transcript = (completed.stdout or "").strip()
        if not transcript:
            return {"ok": False, "provider": "whisper-cli", "reason": "whisper_empty_transcript"}
    return {"ok": True, "provider": f"whisper-cli:{model}", "transcript": transcript}


def unsafe_asr_command_reason(command: str) -> str:
    return semantic_unsafe_asr_command_reason(command)


def build_asr_command_argv(command: str, args: Any, audio_path: Path) -> list[str]:
    argv, reason = semantic_build_asr_command_argv(command, args, audio_path)
    if reason:
        fail(
            "ASR 命令配置不安全，已阻止执行。请只填写 ASR 可执行文件路径，并把参数放入 asr_command_args。"
            "例如：asr_command='whisper'，asr_command_args=['{audio}', '--model', 'tiny.en']。",
            error_code="UNSAFE_ASR_COMMAND",
            stage="tts",
            details={"reason": reason},
        )
    return argv


def transcribe_tts_audio(
    audio_path: Path,
    *,
    project: dict[str, Any],
    expected_text: str,
    role: str,
) -> dict[str, Any]:
    config = tts_semantic_config(project)
    transcripts = config.get("transcripts") if isinstance(config.get("transcripts"), dict) else {}
    for key in (Path(audio_path).name, Path(audio_path).stem, media_text_hash(expected_text), expected_text):
        if key in transcripts:
            return {"ok": True, "provider": "configured-transcript", "transcript": str(transcripts[key] or "")}

    if str(config.get("asr_provider") or "").strip().lower() in {"whisper", "whisper-cli", "openai-whisper"} or bool(
        config.get("auto_whisper")
    ):
        return transcribe_tts_audio_with_whisper_cli(audio_path, config)

    command = str(config.get("asr_command") or os.environ.get("ACG_TTS_ASR_COMMAND") or "").strip()
    if command:
        completed = subprocess.run(
            build_asr_command_argv(command, config.get("asr_command_args"), audio_path),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=int(config.get("asr_timeout_seconds") or 60),
            **hidden_subprocess_flags(),
        )
        if completed.returncode == 0 and (completed.stdout or "").strip():
            return {"ok": True, "provider": "asr-command", "transcript": completed.stdout.strip()}
        return {
            "ok": False,
            "provider": "asr-command",
            "reason": "asr_command_failed",
            "error": (completed.stderr or completed.stdout or "").strip()[-500:],
        }

    return {
        "ok": False,
        "provider": "none",
        "reason": "asr_semantic_check_unavailable",
    }


def verify_tts_audio_semantics(
    audio_path: Path,
    expected_text: str,
    *,
    role: str,
    project: dict[str, Any],
) -> dict[str, Any]:
    tts_text = clean_tts_input_text(expected_text)
    base_reasons = tts_semantic_base_reasons(role, tts_text)
    transcript_result = transcribe_tts_audio(audio_path, project=project, expected_text=tts_text, role=role)
    if not transcript_result.get("ok"):
        return {
            "semantic_verification": "manual_review_required",
            "manual_review_required": True,
            "semantic_review_reasons": sorted(set(base_reasons + [str(transcript_result.get("reason") or "asr_unavailable")])),
            "asr_provider": str(transcript_result.get("provider") or "none"),
            "asr_transcript": "",
            "expected_text_normalized": normalize_tts_semantic_text(tts_text),
            "actual_text_normalized": "",
        }

    transcript = clean_study_text(transcript_result.get("transcript") or "")
    matched, expected_norm, actual_norm = tts_semantic_matches(tts_text, transcript, role=role)
    if matched:
        return {
            "semantic_verification": "passed",
            "manual_review_required": False,
            "semantic_review_reasons": [],
            "asr_provider": str(transcript_result.get("provider") or "asr"),
            "asr_transcript": transcript,
            "expected_text_normalized": expected_norm,
            "actual_text_normalized": actual_norm,
        }
    return {
        "semantic_verification": "mismatch",
        "manual_review_required": False,
        "semantic_review_reasons": sorted(set(base_reasons + ["asr_text_mismatch"])),
        "asr_provider": str(transcript_result.get("provider") or "asr"),
        "asr_transcript": transcript,
        "expected_text_normalized": expected_norm,
        "actual_text_normalized": actual_norm,
    }


def tts_cache_meta_path(cache_path: Path) -> Path:
    return cache_path.with_suffix(f"{cache_path.suffix}.json")


def load_tts_cache_semantic_meta(cache_path: Path, text: str) -> dict[str, Any] | None:
    meta_path = tts_cache_meta_path(cache_path)
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(meta, dict):
        return None
    if meta.get("adapter_version") != TTS_PROVIDER_ADAPTER_VERSION:
        return None
    if str(meta.get("text_hash") or "") != media_text_hash(text):
        return None
    semantic = meta.get("semantic") if isinstance(meta.get("semantic"), dict) else None
    if not semantic or semantic.get("semantic_verification") != "passed":
        return None
    return semantic


def store_tts_cache_semantic_meta(cache_path: Path, text: str, semantic: dict[str, Any]) -> None:
    if semantic.get("semantic_verification") != "passed":
        return
    meta = {
        "adapter_version": TTS_PROVIDER_ADAPTER_VERSION,
        "text_hash": media_text_hash(text),
        "semantic": semantic,
    }
    try:
        tts_cache_meta_path(cache_path).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def validate_tts_audio_duration(output_path: Path, text: str, tts_kind: str) -> None:
    if tts_kind != "phrase":
        return
    duration = audio_duration_seconds(output_path)
    if duration is None:
        return
    max_duration = phrase_tts_max_duration_seconds(text)
    if duration <= max_duration:
        return
    display_text = clean_tts_input_text(text)
    if len(display_text) > 80:
        display_text = f"{display_text[:77]}..."
    raise RuntimeError(
        f"表达 TTS 时长异常：{display_text!r} 生成 {duration:.2f}s，"
        f"超过上限 {max_duration:.2f}s，疑似 TTS 误读或扩写。"
    )


def tts_cache_path(tts: dict[str, Any], text: str, language: Any) -> tuple[Path, str]:
    return cache_tts_cache_path(
        persistent_cache_root(),
        tts,
        text,
        language,
        provider_name_func=provider_name,
        resolve_language_func=resolve_tts_language_code,
        normalize_volume_func=normalized_tts_output_volume,
        clean_text_func=clean_tts_input_text,
        text_hash_func=media_text_hash,
        provider_scope_func=tts_provider_scope,
    )


def project_cache_read_disabled(project: dict[str, Any], key: str) -> bool:
    if bool(project.get(key)):
        return True
    api_config = project.get("api_config")
    return isinstance(api_config, dict) and bool(api_config.get(key))


def tts_cache_read_enabled(project: dict[str, Any]) -> bool:
    return not project_cache_read_disabled(project, "disable_tts_cache_read")


def media_cache_read_enabled(project: dict[str, Any]) -> bool:
    return not project_cache_read_disabled(project, "disable_media_cache_read")


def media_clip_cache_path(
    video_fingerprint_value: str,
    start: str,
    duration: str,
    role: str,
    extension: str,
    profile: str,
) -> tuple[Path, str]:
    return cache_media_clip_cache_path(
        persistent_cache_root(),
        video_fingerprint_value,
        start,
        duration,
        role,
        extension,
        profile,
        ffmpeg_signature=ffmpeg_cache_signature(),
    )


def compare_media_manifest(
    expected: dict[str, dict[str, Any]],
    media_dir: Path,
    *,
    anki_url: str = "",
    max_attempts: int = 6,
    retry_delay_seconds: float = 0.2,
) -> dict[str, Any]:
    return compare_media_manifest_core(
        expected,
        media_dir,
        anki_url=anki_url,
        max_attempts=max_attempts,
        retry_delay_seconds=retry_delay_seconds,
        file_sha256_func=file_sha256,
        retrieve_media_bytes_func=retrieve_anki_media_bytes,
        bytes_sha256_func=bytes_sha256,
    )


def audio_duration_seconds_from_bytes(filename: str, data: bytes) -> float | None:
    return imported_audio_duration_seconds_from_bytes(
        filename,
        data,
        duration_seconds_func=audio_duration_seconds,
    )


def imported_tts_audio_duration_issues(
    expected_manifest: dict[str, dict[str, Any]],
    media_dir: Path,
    referenced_media: set[str],
    *,
    strict_video_import: bool,
    anki_url: str = "",
    max_attempts: int = 6,
    retry_delay_seconds: float = 0.2,
) -> list[dict[str, Any]]:
    return imported_tts_audio_duration_issues_core(
        expected_manifest,
        media_dir,
        referenced_media,
        strict_video_import=strict_video_import,
        anki_url=anki_url,
        max_attempts=max_attempts,
        retry_delay_seconds=retry_delay_seconds,
        retrieve_media_bytes_func=retrieve_anki_media_bytes,
        duration_seconds_func=audio_duration_seconds,
        duration_seconds_from_bytes_func=audio_duration_seconds_from_bytes,
        clean_tts_text_func=clean_tts_input_text,
        phrase_max_duration_func=phrase_tts_max_duration_seconds,
    )


def export_audit_card_title(segment: dict[str, Any], card: dict[str, Any]) -> str:
    for value in (
        card.get("answer_core"),
        card.get("phrase"),
        segment.get("phrase"),
        card.get("english"),
        segment.get("text"),
        card.get("id"),
    ):
        text = audit_text_excerpt(value, 56)
        if text:
            return text
    return "未命名卡片"


def export_audit_blocked_matches(
    card: dict[str, Any],
    required_values: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    matches: list[dict[str, str]] = []
    fields: list[tuple[str, Any]] = [
        ("LearningGoal", card.get("learning_goal")),
        ("DecisionReason", card.get("decision_reason")),
        ("PhraseDecisionReason", card.get("phrase_decision_reason")),
        ("PhraseRejectReason", card.get("phrase_reject_reason")),
        ("PhraseCardFocus", card.get("phrase_card_focus")),
        ("LearningAction", card.get("learning_action")),
        ("Chinese", card.get("chinese")),
        ("Definition", card.get("definition")),
        ("Collocations", card.get("collocations")),
        ("TeacherNote", card.get("teacher_note")),
        ("Context", card.get("context")),
        ("Example", card.get("example")),
        ("ChineseFeel", card.get("chinese_feel")),
        ("Why", card.get("why")),
        ("DifficultyReason", card.get("difficulty_reason")),
        ("Phrase", card.get("phrase")),
        ("Answer", card.get("answer_core")),
        ("LearningTarget", card.get("learning_target")),
        ("WhyItMatters", card.get("why_it_matters")),
        ("HowToUseIt", card.get("how_to_use_it")),
        ("NaturalChinese", card.get("natural_chinese")),
        ("UsageBoundary", card.get("usage_boundary")),
        ("ConfusableNote", card.get("confusable_note")),
        ("ReplacementExamples", card.get("replacement_examples")),
        ("AvoidReason", card.get("avoid_reason")),
    ]
    if required_values:
        fields.extend((f"Export{name}", value) for name, value in required_values.items())
    seen: set[tuple[str, str]] = set()
    for field, value in fields:
        patterns = internal_placeholder_patterns(value)
        if not patterns:
            continue
        excerpt = audit_text_excerpt(value)
        key = (field, excerpt)
        if key in seen:
            continue
        seen.add(key)
        matches.append(
            {
                "field": field,
                "matched_text": excerpt,
                "patterns": " / ".join(patterns[:4]),
            }
        )
    for index, issue in enumerate(card.get("quality", {}).get("issues") or [], start=1):
        patterns = internal_placeholder_patterns_for_quality_issue(issue)
        if not patterns:
            continue
        excerpt = audit_text_excerpt(issue)
        field = f"QualityIssue{index}"
        key = (field, excerpt)
        if key in seen:
            continue
        seen.add(key)
        matches.append(
            {
                "field": field,
                "matched_text": excerpt,
                "patterns": " / ".join(patterns[:4]),
            }
        )
    return matches


def ensure_card_pronunciation_meta(card: dict[str, Any], language: Any = "en") -> dict[str, Any]:
    sanitize_pronunciation_fields(card, card.get("language") or language)
    meta = card.get("pronunciation_meta")
    if isinstance(meta, dict):
        return meta
    return normalize_pronunciation_meta(
        meta,
        card.get("language") or language,
        has_spoken=bool(card.get("spoken_ipa")),
        has_source=bool(card.get("source_spoken_ipa")),
    )


def pronunciation_meta_json(card: dict[str, Any], language: Any = "en") -> str:
    meta = ensure_card_pronunciation_meta(card, language)
    return json.dumps(meta, ensure_ascii=False, separators=(",", ":"))


def compact_retrieval_cue(value: Any, max_chars: int = 26) -> str:
    text = clean_study_text(value)
    text = text.strip(" \t\r\n。.!！?？；;，,")
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars].rstrip()}..."


def is_contextual_vocabulary_card(card: dict[str, Any]) -> bool:
    return (
        str(card.get("content_kind") or "").strip() == "vocabulary"
        or str(card.get("phrase_type") or "").strip() == "vocabulary_usage"
    )


ANSWER_COMMENTARY_RE = re.compile(
    r"\s*[\(（]([^()（）]*(?:听力|连读|弱读|缩读|读作|读为|发音|音变|pronunciation|sounds like)[^()（）]*)[\)）]\s*",
    re.IGNORECASE,
)
ANSWER_EXPLANATION_PATTERNS = (
    "发音",
    "融合",
    "连读",
    "弱读",
    "缩读",
    "非标准",
    "变体",
    "过去式",
    "直接按",
    "映射",
    "听到",
    "听力",
    "读作",
    "读为",
    "解释为",
    "理解为",
    "pronunciation",
    "sounds like",
)
IPA_TEXT_RE = re.compile(r"/[^/\n]{2,}/|[ɑɒɔəɜɪʊʌæɛθðŋʃʒːˈˌɚɝ]")


def answer_display_text(value: Any) -> str:
    text = clean_study_text(value)
    if not text:
        return ""
    text = ANSWER_COMMENTARY_RE.sub(" ", text)
    equal_match = re.match(r"^\s*([^=＝:：]+?)\s*[=＝]\s*(.+)$", text)
    if equal_match and re.search(r"[A-Za-z]", equal_match.group(1)) and has_cjk(equal_match.group(2)):
        text = equal_match.group(1)
    text = re.sub(r"\s+", " ", text).strip(" \t\r\n。；;")
    return text


def answer_commentary_text(value: Any) -> str:
    text = clean_study_text(value)
    if not text:
        return ""
    notes = [match.group(1).strip(" \t\r\n。；;") for match in ANSWER_COMMENTARY_RE.finditer(text)]
    notes = [note for note in notes if note]
    if not notes:
        return ""
    note = "；".join(dict.fromkeys(notes))
    return note if note.startswith(("听感", "发音", "连读", "弱读", "缩读")) else f"听感：{note}"


def is_answer_expression_candidate(value: Any, card: dict[str, Any]) -> bool:
    text = clean_study_text(value)
    if not text:
        return False
    lowered = text.lower()
    language = normalize_learning_language(card.get("language_code") or card.get("language") or "en")
    if IPA_TEXT_RE.search(text):
        return False
    if any(pattern in text or pattern.lower() in lowered for pattern in ANSWER_EXPLANATION_PATTERNS):
        return False
    if any(mark in text for mark in ("；", "。", "，")):
        return False
    if language != "en":
        if not looks_like_target_language_text(text, language):
            return False
        source_text = clean_study_text(card.get("english") or card.get("source_text"))
        if source_text and text not in source_text and len(text) > 1 and not phrase_in_text(source_text, text):
            return False
        return True
    if has_cjk(text):
        return False
    words = overlap_words(text)
    if not words:
        return False
    if str(card.get("type") or "") != "listening" and len(words) > 8:
        return False
    if str(card.get("candidate_kind") or "") == "grammar_pattern":
        return True
    english = clean_study_text(card.get("english"))
    if english and not phrase_in_text(english, text) and len(words) >= 2:
        return False
    return True


PRONUNCIATION_FIELDS = (
    "phonetic_ipa",
    "spoken_ipa",
    "source_spoken_ipa",
    "pronunciation_note",
    "pronunciation_confidence",
    "pronunciation_status",
    "source_pronunciation_status",
)
PRONUNCIATION_TEXT_FIELDS = ("phonetic_ipa", "spoken_ipa", "source_spoken_ipa")
PRONUNCIATION_CONFIDENCE_VALUES = {"high", "medium", "low"}
GENERATION_BASIS_VALUES = {"audio_verified", "subtitle_inferred", "dictionary_only"}


def is_english_language(language: Any = "English") -> bool:
    return normalize_learning_language(language) == "en"


def normalize_pronunciation_confidence(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"high", "medium", "low"}:
        return text
    if text in {"高", "较高", "可信"}:
        return "high"
    if text in {"中", "中等", "一般"}:
        return "medium"
    if text in {"低", "不确定"}:
        return "low"
    return ""


def normalize_ipa_field(value: Any, *, max_chars: int = 180) -> str:
    text = clean_study_text(value)
    if not text or has_cjk(text):
        return ""
    text = text.replace("\\", "/")
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_chars:
        text = text[:max_chars].rstrip()
    return text


def normalize_pronunciation_text_field(
    value: Any,
    *,
    language: Any = "en",
    field: str = "phonetic_ipa",
    max_chars: int = 180,
) -> str:
    text = clean_study_text(value)
    if not text:
        return ""
    code = normalize_learning_language(language)
    text = unicodedata.normalize("NFC", text.replace("\\", "/"))
    text = re.sub(r"\s+", " ", text).strip()
    if field in PRONUNCIATION_TEXT_FIELDS and code != "ja" and has_cjk(text):
        return ""
    if len(text) > max_chars:
        text = text[:max_chars].rstrip()
    return text


def confidence_min(*values: Any) -> str:
    order = {"low": 0, "medium": 1, "high": 2}
    normalized = [normalize_pronunciation_confidence(value) or "low" for value in values if value not in (None, "")]
    if not normalized:
        return ""
    return min(normalized, key=lambda value: order[value])


def cap_confidence_for_basis(confidence: Any, basis: str, *, field: str = "") -> str:
    normalized = normalize_pronunciation_confidence(confidence) or "low"
    if basis != "audio_verified" and field in {"spoken_ipa", "source_spoken_ipa"} and normalized == "high":
        return "medium"
    return normalized


def pronunciation_issue(field: str, severity: str, code: str, message: str) -> dict[str, str]:
    return {"field": field, "severity": severity, "code": code, "message": message}


def normalize_pronunciation_issue(value: Any) -> dict[str, str] | None:
    if isinstance(value, dict):
        field = str(value.get("field") or "pronunciation_meta")
        severity = str(value.get("severity") or "warn")
        code = str(value.get("code") or "PRONUNCIATION_ISSUE")
        message = clean_study_text(value.get("message") or code)
        if field not in {*PRONUNCIATION_TEXT_FIELDS, "pronunciation_note", "pronunciation_meta"}:
            field = "pronunciation_meta"
        if severity not in {"block", "warn", "info"}:
            severity = "warn"
        return pronunciation_issue(field, severity, code, message)
    message = clean_study_text(value)
    if message:
        return pronunciation_issue("pronunciation_meta", "warn", "LEGACY_VALIDATION_ISSUE", message)
    return None


def normalize_pronunciation_field_change(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    field = str(value.get("field") or "").strip()
    action = str(value.get("action") or "").strip()
    code = str(value.get("code") or "PRONUNCIATION_FIELD_CHANGE").strip()
    message = clean_study_text(value.get("message") or code)
    if field not in {"phonetic_ipa", "spoken_ipa", "source_spoken_ipa", "pronunciation_note"}:
        return None
    if action not in {"kept", "hidden", "cleared", "downgraded", "not_generated"}:
        action = "downgraded"
    change = {"field": field, "action": action, "code": code, "message": message}
    original = clean_study_text(value.get("original_value") or "")
    if original:
        change["original_value"] = original
    return change


def normalize_pronunciation_meta(
    value: Any,
    language: Any = "en",
    *,
    has_spoken: bool = False,
    has_source: bool = False,
) -> dict[str, Any]:
    raw: dict[str, Any] = {}
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                raw = parsed
        except json.JSONDecodeError:
            raw = {}
    elif isinstance(value, dict):
        raw = dict(value)
    profile = pronunciation_profile(raw.get("language_code") or language)
    basis = str(raw.get("generation_basis") or "").strip()
    if basis not in GENERATION_BASIS_VALUES:
        basis = "subtitle_inferred" if has_spoken or has_source else "dictionary_only"
    field_confidence = raw.get("field_confidence")
    if not isinstance(field_confidence, dict):
        field_confidence = {}
    normalized_confidence: dict[str, str] = {}
    for field in ("phonetic_ipa", "spoken_ipa", "source_spoken_ipa", "pronunciation_note"):
        confidence = cap_confidence_for_basis(field_confidence.get(field), basis, field=field)
        if confidence:
            normalized_confidence[field] = confidence
    raw_issues = raw.get("validation_issues") or []
    if not isinstance(raw_issues, list):
        raw_issues = [raw_issues]
    issues = []
    for issue in raw_issues:
        normalized_issue = normalize_pronunciation_issue(issue)
        if normalized_issue:
            issues.append(normalized_issue)
    raw_changes = raw.get("field_changes") or []
    if not isinstance(raw_changes, list):
        raw_changes = [raw_changes]
    field_changes = []
    for change in raw_changes:
        normalized_change = normalize_pronunciation_field_change(change)
        if normalized_change:
            field_changes.append(normalized_change)
    meta = {
        "language_code": profile["code"],
        "accent_profile": str(raw.get("accent_profile") or profile["accent_profile"]),
        "notation_system": str(raw.get("notation_system") or profile["notation_system"]),
        "generation_basis": basis,
        "field_confidence": normalized_confidence,
        "same_as_standard_reason": raw.get("same_as_standard_reason") or None,
        "validation_issues": issues,
    }
    if field_changes:
        meta["field_changes"] = field_changes
    if profile["code"] == "ja":
        pitch_confidence = str(raw.get("pitch_confidence") or "").strip().lower()
        if pitch_confidence in {*PRONUNCIATION_CONFIDENCE_VALUES, "unknown"}:
            meta["pitch_confidence"] = pitch_confidence
    return meta


def add_pronunciation_issue(target: dict[str, Any], issue: dict[str, str]) -> None:
    existing_meta = target.get("pronunciation_meta")
    meta = existing_meta if isinstance(existing_meta, dict) else {"validation_issues": []}
    target["pronunciation_meta"] = meta
    issues = meta.setdefault("validation_issues", [])
    key = (issue["field"], issue["severity"], issue["code"], issue["message"])
    existing = {
        (str(item.get("field")), str(item.get("severity")), str(item.get("code")), str(item.get("message")))
        for item in issues
        if isinstance(item, dict)
    }
    if key not in existing:
        issues.append(issue)


def add_pronunciation_field_change(
    target: dict[str, Any],
    field: str,
    action: str,
    code: str,
    message: str,
    *,
    original_value: Any = "",
) -> None:
    existing_meta = target.get("pronunciation_meta")
    meta = existing_meta if isinstance(existing_meta, dict) else {"validation_issues": []}
    target["pronunciation_meta"] = meta
    changes = meta.setdefault("field_changes", [])
    normalized = normalize_pronunciation_field_change(
        {
            "field": field,
            "action": action,
            "code": code,
            "message": message,
            "original_value": original_value,
        }
    )
    if not normalized:
        return
    key = (normalized["field"], normalized["action"], normalized["code"], normalized["message"])
    existing = {
        (str(item.get("field")), str(item.get("action")), str(item.get("code")), str(item.get("message")))
        for item in changes
        if isinstance(item, dict)
    }
    if key not in existing:
        changes.append(normalized)


def append_pronunciation_note_once(target: dict[str, Any], message: str) -> None:
    note = clean_study_text(target.get("pronunciation_note") or "")
    if message in note:
        return
    target["pronunciation_note"] = f"{note} {message}".strip()[:260].rstrip()


def set_pronunciation_status_once(target: dict[str, Any], field: str, message: str) -> None:
    if field not in {"pronunciation_status", "source_pronunciation_status"}:
        return
    text = clean_study_text(message)
    if not text or pronunciation_status_is_unhelpful_placeholder(text):
        return
    current = clean_study_text(target.get(field) or "")
    if text in current:
        return
    target[field] = f"{current}；{text}".strip("；")[:180].rstrip()


UNHELPFUL_PRONUNCIATION_STATUS_PATTERNS = (
    r"未实听[，,]?\s*仅提供标准读法[。.]?",
    r"未实听[，,]?\s*按字幕和常见口语规律推测[。.]?",
    r"读法未可靠生成[，,]?\s*已隐藏[。.]?",
    r"原句听感未可靠生成[，,]?\s*已隐藏[。.]?",
)


def pronunciation_status_is_unhelpful_placeholder(value: Any) -> bool:
    text = clean_study_text(value)
    if not text:
        return True
    return any(re.fullmatch(pattern, text) for pattern in UNHELPFUL_PRONUNCIATION_STATUS_PATTERNS)


def clear_unhelpful_pronunciation_statuses(target: dict[str, Any]) -> None:
    for field in ("pronunciation_status", "source_pronunciation_status"):
        text = clean_study_text(target.get(field) or "")
        if not text:
            target.pop(field, None)
            continue
        parts = [part.strip() for part in re.split(r"[；;]", text) if part.strip()]
        useful_parts = [part for part in parts if not pronunciation_status_is_unhelpful_placeholder(part)]
        if useful_parts:
            target[field] = "；".join(useful_parts)[:180].rstrip()
        else:
            target.pop(field, None)


def set_source_pronunciation_hidden_status(target: dict[str, Any], *, code: str, message: str, original_value: Any = "") -> None:
    add_pronunciation_field_change(
        target,
        "source_spoken_ipa",
        "hidden",
        code,
        message,
        original_value=original_value,
    )


def remove_pronunciation_issue_code(target: dict[str, Any], code: str) -> None:
    meta = target.get("pronunciation_meta")
    if not isinstance(meta, dict):
        return
    issues = meta.get("validation_issues")
    if not isinstance(issues, list):
        return
    meta["validation_issues"] = [
        issue for issue in issues if not (isinstance(issue, dict) and issue.get("code") == code)
    ]


def set_pronunciation_field_confidence(target: dict[str, Any], field: str, confidence: str) -> None:
    meta = target.get("pronunciation_meta")
    if isinstance(meta, str) and meta.strip():
        try:
            parsed = json.loads(meta)
            meta = parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            meta = {}
    if not isinstance(meta, dict):
        meta = {}
    target["pronunciation_meta"] = meta
    field_confidence = meta.setdefault("field_confidence", {})
    if isinstance(field_confidence, dict):
        field_confidence[field] = confidence


def ipa_token_count(value: Any) -> int:
    text = clean_study_text(value).strip().strip("/")
    if not text:
        return 0
    return len([part for part in re.split(r"\s+", text) if part])


SPOKEN_IPA_DIFFERENCE_WORDS = {
    "a",
    "an",
    "the",
    "to",
    "of",
    "for",
    "and",
    "or",
    "as",
    "at",
    "in",
    "on",
    "with",
    "from",
    "into",
    "that",
    "this",
    "it",
    "you",
    "your",
    "me",
    "we",
    "will",
    "are",
    "is",
    "was",
    "were",
    "do",
    "does",
    "did",
    "have",
    "has",
    "had",
    "not",
    "can",
    "could",
    "would",
    "should",
    "just",
    "up",
    "off",
    "out",
    "about",
}


def ipa_comparison_key(value: Any) -> str:
    text = clean_study_text(value).strip().strip("/").lower()
    text = re.sub(r"\s+", " ", text)
    return text


def spoken_ipa_should_be_distinct(target: dict[str, Any]) -> bool:
    words = overlap_words(
        str(target.get("answer_core") or target.get("phrase") or target.get("normalized_answer") or "")
    )
    if len(words) < 3:
        return False
    weak_signal_words = SPOKEN_IPA_DIFFERENCE_WORDS - {"the", "off"}
    return any(word in weak_signal_words or "'" in word or word.endswith("ing") for word in words)


def spoken_ipa_is_unhelpful_duplicate(target: dict[str, Any], spoken_ipa: str) -> bool:
    phonetic = normalize_ipa_field(target.get("phonetic_ipa"))
    if not phonetic or not spoken_ipa or not spoken_ipa_should_be_distinct(target):
        return False
    return ipa_comparison_key(phonetic) == ipa_comparison_key(spoken_ipa)


def default_same_as_standard_reason(meta: dict[str, Any]) -> str:
    if meta.get("generation_basis") == "audio_verified":
        return "已按当前音频核验；未识别出明显弱读、连读或省读差异。"
    if meta.get("generation_basis") == "dictionary_only":
        return "只提供标准读法，未生成单独口语读法。"
    return "未实听；按字幕推测时未识别出可靠的弱读、连读或省读差异，暂按标准读法保留。"


def source_spoken_ipa_is_too_short(target: dict[str, Any], source_ipa: str) -> bool:
    english_words = overlap_words(str(target.get("english") or target.get("source_text") or ""))
    if len(english_words) < 5 or not source_ipa:
        return False

    token_count = ipa_token_count(source_ipa)
    if token_count <= 0:
        return False

    answer_words = overlap_words(
        str(target.get("answer_core") or target.get("phrase") or target.get("normalized_answer") or "")
    )
    phonetic = normalize_ipa_field(target.get("phonetic_ipa"))
    spoken = normalize_ipa_field(target.get("spoken_ipa"))
    if source_ipa.strip() in {phonetic.strip(), spoken.strip()} and len(english_words) > len(answer_words) + 1:
        return True

    missingish = len(english_words) - token_count
    return missingish >= 2 and token_count / max(1, len(english_words)) < 0.8


FRENCH_ASPIRE_H_WORDS = {
    "haricot",
    "hasard",
    "haut",
    "héros",
    "honte",
    "hors",
    "huit",
}

RUSSIAN_VOWELS = set("аеёиоуыэюяАЕЁИОУЫЭЮЯ")


def has_pitch_marker(value: Any) -> bool:
    return bool(re.search(r"[ꜜ°｜↗↘]", str(value or "")))


def looks_like_romaji_only(value: Any) -> bool:
    text = clean_study_text(value)
    return bool(text and re.fullmatch(r"[A-Za-z0-9\s'\-.,!?/]+", text) and re.search(r"[A-Za-z]", text))


def looks_like_ipa_only(value: Any) -> bool:
    text = clean_study_text(value)
    return bool(text and IPA_TEXT_RE.search(text) and not has_japanese_kana(text) and not has_cjk(text))


def russian_word_has_stress(word: str) -> bool:
    decomposed = unicodedata.normalize("NFD", word)
    return "\u0301" in decomposed or "ё" in word.lower()


def russian_word_needs_stress(word: str) -> bool:
    letters = re.sub(r"[^А-Яа-яЁё]", "", word)
    if not letters:
        return False
    vowel_count = sum(1 for char in letters if char in RUSSIAN_VOWELS)
    return vowel_count >= 2


def pronunciation_issue_messages(target: dict[str, Any]) -> list[str]:
    meta = target.get("pronunciation_meta")
    if not isinstance(meta, dict):
        return []
    messages = []
    for issue in meta.get("validation_issues") or []:
        if isinstance(issue, dict) and issue.get("message"):
            messages.append(str(issue["message"]))
    return list(dict.fromkeys(messages))


def spoken_label_for_meta(meta: dict[str, Any] | None) -> str:
    if not isinstance(meta, dict):
        return "剧中读法"
    basis = meta.get("generation_basis")
    if basis == "audio_verified":
        return "剧中读法"
    if basis == "dictionary_only":
        return "按标准读法"
    return "推测口语读法"


def standard_hint_for_meta(meta: dict[str, Any] | None, language: Any = "en") -> str:
    if isinstance(meta, dict):
        return LEARNING_LANGUAGE_PROFILES.get(str(meta.get("language_code") or ""), {}).get("standard_hint") or pronunciation_profile(language)["standard_hint"]
    return pronunciation_profile(language)["standard_hint"]


def maybe_prefix_inferred_note(target: dict[str, Any], meta: dict[str, Any]) -> None:
    # Public builds do not surface ASR/listening confidence placeholders on the card.
    # Real pronunciation fields are kept; missing or inferred status text is left empty.
    return


PRONUNCIATION_SYSTEM_NOTE_PATTERNS = (
    r"未实听[，,]?\s*仅提供标准读法[。.]?",
    r"未实听[，,]?\s*按字幕和常见口语规律推测[。.]?",
    r"未实听[；;]\s*按字幕推测时未识别出可靠的弱读、连读或省读差异，暂按标准读法保留[。.]?",
    r"原句听感未可靠生成[，,]?\s*已隐藏[。.]?",
    r"读法未可靠生成[，,]?\s*已隐藏[。.]?",
)


def separate_pronunciation_status_from_note(target: dict[str, Any]) -> None:
    note = clean_study_text(target.get("pronunciation_note"))
    if not note:
        target.pop("pronunciation_note", None)
        return
    original = note
    for pattern in PRONUNCIATION_SYSTEM_NOTE_PATTERNS:
        note = re.sub(pattern, "", note)
    note = re.sub(r"\s*[；;]\s*", "；", note)
    note = re.sub(r"^[。.;；,\s]+|[。.;；,\s]+$", "", note).strip()
    if note:
        target["pronunciation_note"] = note[:260].rstrip()
    else:
        target.pop("pronunciation_note", None)
    if note != original:
        add_pronunciation_field_change(
            target,
            "pronunciation_note",
            "downgraded" if note else "hidden",
            "PRONUNCIATION_STATUS_SEPARATED_FROM_NOTE",
            "系统状态已从发音说明中移除。",
            original_value=original,
        )


def sanitize_pronunciation_fields(target: dict[str, Any], language: Any = "English") -> list[str]:
    target_language = normalize_learning_language(language or target.get("language") or "en")
    target["language"] = target_language
    clear_unhelpful_pronunciation_statuses(target)
    issues: list[str] = []
    for key in PRONUNCIATION_TEXT_FIELDS:
        raw = target.get(key)
        normalized = normalize_pronunciation_text_field(
            raw,
            language=target_language,
            field=key,
            max_chars=340 if key == "source_spoken_ipa" else 220,
        )
        if raw and not normalized:
            issue = pronunciation_issue(key, "block", "PRONUNCIATION_FIELD_UNUSABLE", f"{key} 含不适合该语言读法字段的内容，已清空。")
            add_pronunciation_issue(target, issue)
            add_pronunciation_field_change(target, key, "cleared", issue["code"], issue["message"], original_value=raw)
            set_pronunciation_field_confidence(target, key, "low")
            issues.append(issue["message"])
        if target_language == "en" and key == "spoken_ipa" and normalized and spoken_ipa_is_unhelpful_duplicate(target, normalized):
            original_normalized = normalized
            normalized = ""
            issue = pronunciation_issue("spoken_ipa", "block", "SPOKEN_SAME_AS_STANDARD", "spoken_ipa 与标准读法完全相同，缺少口语听感，已清空。")
            add_pronunciation_issue(target, issue)
            add_pronunciation_field_change(target, "spoken_ipa", "hidden", issue["code"], issue["message"], original_value=original_normalized)
            set_pronunciation_field_confidence(target, "spoken_ipa", "low")
            issues.append(issue["message"])
        if target_language == "en" and key == "source_spoken_ipa" and normalized and source_spoken_ipa_is_too_short(target, normalized):
            original_normalized = normalized
            normalized = ""
            issue = pronunciation_issue("source_spoken_ipa", "block", "SOURCE_PRONUNCIATION_TOO_SHORT", "source_spoken_ipa 不是完整原句听感，已清空。")
            add_pronunciation_issue(target, issue)
            add_pronunciation_field_change(target, "source_spoken_ipa", "hidden", issue["code"], issue["message"], original_value=original_normalized)
            set_pronunciation_field_confidence(target, "source_spoken_ipa", "low")
            issues.append(issue["message"])
        if target_language == "es" and normalized and "θ" in normalized:
            original_normalized = normalized
            normalized = ""
            issue = pronunciation_issue(key, "block", "SPANISH_LATAM_THETA", "默认拉美西语 profile 不使用 /θ/，该读法字段已清空。")
            add_pronunciation_issue(target, issue)
            add_pronunciation_field_change(target, key, "cleared", issue["code"], issue["message"], original_value=original_normalized)
            set_pronunciation_field_confidence(target, key, "low")
            issues.append(issue["message"])
        if target_language == "ja" and key == "phonetic_ipa" and normalized:
            source_or_answer = str(target.get("answer_core") or target.get("phrase") or target.get("english") or "")
            if looks_like_romaji_only(normalized):
                original_normalized = normalized
                normalized = ""
                issue = pronunciation_issue("phonetic_ipa", "block", "JAPANESE_ROMAJI_ONLY", "日语标准读法不能只有 romaji，已清空。")
                add_pronunciation_issue(target, issue)
                add_pronunciation_field_change(target, "phonetic_ipa", "cleared", issue["code"], issue["message"], original_value=original_normalized)
                set_pronunciation_field_confidence(target, "phonetic_ipa", "low")
                issues.append(issue["message"])
            elif looks_like_ipa_only(normalized):
                original_normalized = normalized
                normalized = ""
                issue = pronunciation_issue("phonetic_ipa", "block", "JAPANESE_IPA_ONLY", "日语标准读法不能只有 IPA，已清空。")
                add_pronunciation_issue(target, issue)
                add_pronunciation_field_change(target, "phonetic_ipa", "cleared", issue["code"], issue["message"], original_value=original_normalized)
                set_pronunciation_field_confidence(target, "phonetic_ipa", "low")
                issues.append(issue["message"])
            elif has_cjk(source_or_answer) and not has_japanese_kana(normalized):
                original_normalized = normalized
                normalized = ""
                issue = pronunciation_issue("phonetic_ipa", "block", "JAPANESE_KANA_REQUIRED", "日语含汉字时必须给假名读音，已清空。")
                add_pronunciation_issue(target, issue)
                add_pronunciation_field_change(target, "phonetic_ipa", "cleared", issue["code"], issue["message"], original_value=original_normalized)
                set_pronunciation_field_confidence(target, "phonetic_ipa", "low")
                issues.append(issue["message"])
        if target_language == "ru" and key == "phonetic_ipa" and normalized:
            words = re.findall(r"[А-Яа-яЁё\u0301]+", unicodedata.normalize("NFD", normalized))
            unstressed = [word for word in words if russian_word_needs_stress(word) and not russian_word_has_stress(word)]
            if unstressed:
                original_normalized = normalized
                normalized = ""
                issue = pronunciation_issue("phonetic_ipa", "block", "RUSSIAN_STRESS_REQUIRED", "俄语多音节实词必须标重音，已清空。")
                add_pronunciation_issue(target, issue)
                add_pronunciation_field_change(target, "phonetic_ipa", "cleared", issue["code"], issue["message"], original_value=original_normalized)
                set_pronunciation_field_confidence(target, "phonetic_ipa", "low")
                issues.append(issue["message"])
        if normalized:
            target[key] = normalized
        else:
            target.pop(key, None)
    note = clean_study_text(target.get("pronunciation_note"))
    if note:
        target["pronunciation_note"] = note[:260].rstrip()
    else:
        target.pop("pronunciation_note", None)
    separate_pronunciation_status_from_note(target)
    meta = normalize_pronunciation_meta(
        target.get("pronunciation_meta"),
        target_language,
        has_spoken=bool(target.get("spoken_ipa")),
        has_source=bool(target.get("source_spoken_ipa")),
    )
    target["pronunciation_meta"] = meta

    if meta["generation_basis"] == "dictionary_only":
        for key in ("spoken_ipa", "source_spoken_ipa"):
            if target.get(key):
                original_value = target.get(key)
                target.pop(key, None)
                issue = pronunciation_issue(key, "block", "DICTIONARY_ONLY_NO_SPOKEN", "dictionary_only 只保留标准读法，口语/原句听感已清空。")
                add_pronunciation_issue(target, issue)
                add_pronunciation_field_change(target, key, "hidden", issue["code"], issue["message"], original_value=original_value)
                issues.append(issue["message"])
    maybe_prefix_inferred_note(target, meta)
    if not any(target.get(key) for key in PRONUNCIATION_TEXT_FIELDS) and not target.get("pronunciation_note"):
        message = "未生成可靠读法字段。"
        issue = pronunciation_issue(
            "pronunciation_note",
            "info",
            "PRONUNCIATION_NOT_GENERATED",
            message,
        )
        add_pronunciation_issue(target, issue)
        add_pronunciation_field_change(
            target,
            "pronunciation_note",
            "not_generated",
            issue["code"],
            "模型没有返回可靠的读法字段，卡面不显示发音占位。",
        )
        for key in ("phonetic_ipa", "spoken_ipa", "source_spoken_ipa", "pronunciation_note"):
            set_pronunciation_field_confidence(target, key, "low")
        issues.append(message)

    if target.get("spoken_ipa") and target.get("phonetic_ipa"):
        same = ipa_comparison_key(target.get("spoken_ipa")) == ipa_comparison_key(target.get("phonetic_ipa"))
        answer_words = overlap_words(str(target.get("answer_core") or target.get("phrase") or ""))
        if same and len(answer_words) >= 2 and not meta.get("same_as_standard_reason"):
            meta["same_as_standard_reason"] = default_same_as_standard_reason(meta)
            remove_pronunciation_issue_code(target, "SAME_AS_STANDARD_REASON_REQUIRED")
            note = clean_study_text(target.get("pronunciation_note"))
            same_note = "口语读法与标准读法暂按相同处理。"
            if note and same_note not in note:
                target["pronunciation_note"] = f"{note} {same_note}"[:260].rstrip()
            elif not note:
                target["pronunciation_note"] = same_note

    source_text = str(target.get("english") or target.get("source_text") or "")
    source_pronunciation = str(target.get("source_spoken_ipa") or target.get("spoken_ipa") or "")
    if target_language == "fr":
        if re.search(r"\bet\s*‿", source_pronunciation, flags=re.IGNORECASE):
            issue = pronunciation_issue("source_spoken_ipa", "warn", "FRENCH_ET_LIAISON", "法语 et 后通常禁连读，请检查 et‿...。")
            add_pronunciation_issue(target, issue)
            issues.append(issue["message"])
        if re.search(r"\b(?:les|des|mes|tes|ses|nos|vos|vous)\s+[aeiouhàâäéèêëîïôöùûü]", source_text, flags=re.IGNORECASE) and not re.search(r"[zZ]\s*‿|‿", source_pronunciation):
            issue = pronunciation_issue("source_spoken_ipa", "warn", "FRENCH_MANDATORY_LIAISON_POSSIBLY_MISSING", "法语高频必连读可能漏标，请检查 liaison。")
            add_pronunciation_issue(target, issue)
            issues.append(issue["message"])
        for word in FRENCH_ASPIRE_H_WORDS:
            if re.search(rf"[zZ]\s*‿\s*{word}", source_pronunciation, flags=re.IGNORECASE):
                issue = pronunciation_issue("source_spoken_ipa", "warn", "FRENCH_H_ASPIRE_LIAISON", f"h aspiré 词 {word} 前通常禁连读。")
                add_pronunciation_issue(target, issue)
                issues.append(issue["message"])
    if target_language == "es" and target.get("phonetic_ipa"):
        standard = str(target.get("phonetic_ipa") or "")
        if not re.search(r"[ˈáéíóúÁÉÍÓÚ]|[-·.]", standard) and len(overlap_words(standard)) >= 1:
            issue = pronunciation_issue("phonetic_ipa", "warn", "SPANISH_STRESS_HINT_MISSING", "西语标准读法建议包含重音或音节提示。")
            add_pronunciation_issue(target, issue)
            issues.append(issue["message"])
    if target_language == "ja" and has_pitch_marker(target.get("phonetic_ipa")) and not meta.get("pitch_confidence"):
        issue = pronunciation_issue("pronunciation_meta", "warn", "JAPANESE_PITCH_CONFIDENCE_MISSING", "日语音高符号存在，但缺少 pitch_confidence。")
        add_pronunciation_issue(target, issue)
        issues.append(issue["message"])
    if target_language == "ru" and "е" in source_text.lower():
        confidence = meta.get("field_confidence", {}).get("phonetic_ipa")
        if confidence == "high" and "ё" not in source_text.lower():
            issue = pronunciation_issue("phonetic_ipa", "warn", "RUSSIAN_E_YO_AMBIGUITY", "俄语 е/ё 可能有歧义；未确认时不应标 high confidence。")
            add_pronunciation_issue(target, issue)
            issues.append(issue["message"])

    field_confidence = meta.setdefault("field_confidence", {})
    if meta["generation_basis"] == "dictionary_only":
        field_confidence.setdefault("spoken_ipa", "low")
        field_confidence.setdefault("source_spoken_ipa", "low")
    for key in ("spoken_ipa", "source_spoken_ipa", "phonetic_ipa"):
        if target.get(key):
            continue
        if any(
            isinstance(issue, dict)
            and issue.get("field") == key
            and issue.get("severity") == "block"
            for issue in meta.get("validation_issues") or []
        ):
            field_confidence[key] = "low"
    if target.get("phonetic_ipa") and not field_confidence.get("phonetic_ipa"):
        field_confidence["phonetic_ipa"] = "high"
    for key in ("spoken_ipa", "source_spoken_ipa"):
        if target.get(key):
            before_confidence = field_confidence.get(key)
            field_confidence[key] = cap_confidence_for_basis(field_confidence.get(key), meta["generation_basis"], field=key)
            if meta["generation_basis"] != "audio_verified" and before_confidence == "high" and field_confidence[key] != "high":
                add_pronunciation_field_change(
                    target,
                    key,
                    "downgraded",
                    "SUBTITLE_INFERRED_CONFIDENCE_CAPPED",
                    f"{key} 未经音频实听，置信度已从 high 降级。",
                    original_value=target.get(key),
                )
    if target.get("pronunciation_note") and not field_confidence.get("pronunciation_note"):
        field_confidence["pronunciation_note"] = "medium"
    confidence = confidence_min(
        field_confidence.get("phonetic_ipa"),
        field_confidence.get("spoken_ipa"),
        field_confidence.get("source_spoken_ipa"),
    )
    if confidence:
        target["pronunciation_confidence"] = confidence
    else:
        target.pop("pronunciation_confidence", None)
    clear_unhelpful_pronunciation_statuses(target)
    return list(dict.fromkeys([*issues, *pronunciation_issue_messages(target)]))


def sanitize_learning_point_contract(
    item: dict[str, Any],
    text: str,
    *,
    language: Any = "English",
) -> tuple[bool, str, dict[str, Any]]:
    normalized = dict(item)
    issues: list[str] = []
    raw_kind = normalized.get("kind") or normalized.get("candidate_kind") or "expression"
    kind = normalize_candidate_kind(raw_kind)
    if str(raw_kind or "").strip() and str(raw_kind or "").strip() != kind:
        issues.append("candidate_kind 不在允许枚举内，已按 expression 修复。")
    raw_phrase_type = normalized.get("phrase_type") or phrase_type_for_candidate_kind(kind)
    phrase_type = normalize_phrase_type(raw_phrase_type, kind)
    if str(raw_phrase_type or "").strip() and str(raw_phrase_type or "").strip() != phrase_type:
        issues.append("phrase_type 不在允许枚举内，已按 candidate_kind 修复。")
    exact_span = normalize_candidate_span(
        normalized.get("exact_span")
        or normalized.get("normalized_answer")
        or normalized.get("answer_core")
        or normalized.get("phrase")
        or ""
    )
    if not exact_span:
        return False, "学习点缺少 exact_span。", {}
    if not phrase_in_text(text, exact_span):
        return False, "学习点 exact_span 不在原句中。", {}
    raw_answer = str(
        normalized.get("answer_core")
        or normalized.get("normalized_answer")
        or normalized.get("phrase")
        or exact_span
    ).strip()
    answer_core = answer_display_text(raw_answer)
    fake_card = {
        "type": "listening" if kind == "listening_feature" else "phrase",
        "english": text,
        "language": normalize_learning_language(language),
        "phrase": exact_span,
        "answer_core": answer_core,
        "candidate_kind": kind,
        "phrase_type": phrase_type,
        "content_kind": content_kind_for_phrase_type(phrase_type),
    }
    if raw_answer and clean_study_text(raw_answer) != answer_core:
        issues.append("answer_core 含解释/发音信息，已尝试修复。")
    if not is_answer_expression_candidate(answer_core, fake_card):
        for fallback in (normalized.get("normalized_answer"), normalized.get("phrase"), exact_span):
            candidate = answer_display_text(fallback)
            fake_card["answer_core"] = candidate
            fake_card["phrase"] = candidate or exact_span
            if is_answer_expression_candidate(candidate, fake_card):
                answer_core = candidate
                issues.append("answer_core 已回退为原句中的目标语言学习对象。")
                break
    fake_card["answer_core"] = answer_core
    if not is_answer_expression_candidate(answer_core, fake_card):
        return False, "学习点 answer_core 不是目标语言学习对象。", {}
    if not usable_learning_point_span(text, exact_span, kind, phrase_type):
        return False, "学习点 exact_span 不适合作为该类型学习点。", {}
    span_start, span_end = exact_span_offsets(text, exact_span)
    normalized["exact_span"] = exact_span
    if span_start is not None and span_end is not None:
        normalized["exact_span_start"] = span_start
        normalized["exact_span_end"] = span_end
    normalized["answer_core"] = answer_core
    normalized["normalized_answer"] = answer_display_text(normalized.get("normalized_answer")) or answer_core
    normalized["kind"] = kind
    normalized["candidate_kind"] = kind
    normalized["phrase_type"] = phrase_type
    normalized["content_kind"] = normalized.get("content_kind") or content_kind_for_phrase_type(phrase_type)
    normalized["language"] = normalize_learning_language(language)
    normalized["learning_action"] = clean_study_text(
        normalized.get("learning_action")
        or normalized.get("card_focus")
        or normalized.get("phrase_card_focus")
        or normalized.get("reason")
        or "确认这个学习点是否值得做成卡。"
    )
    normalized["learning_action_key"] = normalized.get("learning_action_key") or learning_action_key_for_contract(normalized)
    normalized["source"] = str(normalized.get("source") or normalized.get("candidate_source") or "model").strip() or "model"
    if normalized["source"] not in {"local", "model", "repaired"}:
        normalized["source"] = "model"
    normalized["confidence"] = str(normalized.get("confidence") or learning_point_confidence(normalized.get("value_score"))).strip()
    if normalized["confidence"] not in {"high", "medium", "low"}:
        normalized["confidence"] = learning_point_confidence(normalized.get("value_score"))
    issues.extend(sanitize_pronunciation_fields(normalized, language))
    if issues:
        raw_history = normalized.get("repair_history")
        prior_history: list[str] = []
        if isinstance(raw_history, list):
            for entry in raw_history:
                if isinstance(entry, str):
                    history_text = clean_study_text(entry)
                elif isinstance(entry, dict):
                    history_text = clean_study_text(
                        entry.get("reason")
                        or entry.get("message")
                        or entry.get("action")
                        or json.dumps(entry, ensure_ascii=False, sort_keys=True)
                    )
                else:
                    history_text = clean_study_text(entry)
                if history_text:
                    prior_history.append(history_text)
        normalized["source"] = "repaired"
        normalized["validation_status"] = "repaired"
        normalized["repair_history"] = list(dict.fromkeys([*prior_history, *issues]))
        normalized["validation_issues"] = list(dict.fromkeys(issues))
    else:
        normalized["validation_status"] = "valid"
        normalized.setdefault("repair_history", [])
    return True, "", normalized


def card_answer_core(card: dict[str, Any]) -> str:
    for value in (card.get("answer_core"), card.get("phrase")):
        candidate = answer_display_text(value)
        if is_answer_expression_candidate(candidate, card):
            return candidate
    phrase = answer_display_text(card.get("phrase"))
    if str(card.get("type") or "") != "listening":
        discovered = find_phrase(clean_study_text(card.get("english")), "B1")
        if is_answer_expression_candidate(discovered, card):
            return discovered
    chinese = clean_study_text(card.get("natural_chinese") or card.get("chinese") or "")
    return phrase or chinese or clean_study_text(card.get("english"))


def card_chinese_core(card: dict[str, Any]) -> str:
    return (
        clean_study_text(card.get("natural_chinese"))
        or clean_study_text(card.get("chinese"))
        or clean_study_text(card.get("chinese_feel"))
    )


def _normalized_study_compare(value: Any) -> str:
    text = clean_study_text(value).lower()
    return re.sub(r"[\s\W_]+", "", text, flags=re.UNICODE)


def _study_lines(*values: Any) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = clean_study_text(value)
        if not text:
            continue
        for raw_line in re.split(r"[\n\r]+", text):
            line = raw_line.strip(" \t；;。")
            if not line:
                continue
            marker = _normalized_study_compare(line)
            if not marker or marker in seen:
                continue
            seen.add(marker)
            lines.append(line)
    return lines


def _labeled_study_line(label: str, value: Any) -> str:
    text = clean_study_text(value)
    if not text:
        return ""
    if re.match(r"^\s*(理解|换法|替换|例句|边界|易错|价值|语气|提醒|注意)[:：]", text):
        return text
    return f"{label}：{text}"


def _new_example_for_card(card: dict[str, Any]) -> str:
    example = clean_study_text(card.get("example"))
    if not example:
        return ""
    if _normalized_study_compare(example) == _normalized_study_compare(card.get("english")):
        return ""
    return example


V11_EXPRESSION_FALLBACKS = {
    "run the register": {
        "meaning": "负责收银 / 操作收银机",
        "source_translations": {
            "i'm gonna run the register": "我来负责收银。",
        },
        "usage": "在店铺、餐厅等工作分工里说，表示某人负责看收银台、操作收银机。",
        "misuse": "不要理解成“运行登记表”。register 在这里是“收银机/收银台”，run 是“负责操作”。",
        "self_sentence": "I’ll run the register for a while. / Can you run the register today?",
    },
    "flat as a washboard": {
        "meaning": "平得像搓衣板；夸张地形容很平",
        "source_translations": {
            "i mean you're flat as a washboard": "我是说，你平得像个搓衣板。",
        },
        "usage": "用来夸张地形容表面或身材很平，通常带调侃或刻薄语气。",
        "misuse": "这是调侃外貌或身材的说法，可能冒犯；适合理解台词，不建议随便对人使用。",
        "self_sentence": "The floor was flat as a washboard. / Don’t use it to describe someone’s body unless you mean to sound rude.",
    },
}


GENERIC_V11_STUDY_PATTERNS = (
    "先抓住",
    "再回看上下文",
    "换一个相似场景",
    "用自己的话复述",
    "先确认语气",
    "不要只背中文翻译",
    "复习时先听语气",
    "注意语境",
    "很常见",
    "本句目标表达",
    "fallback",
    "natural object",
    "complete sentence",
)


def _v11_lookup_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9']+", " ", str(value or "").lower()).strip()


def _v11_fallback(card: dict[str, Any]) -> dict[str, Any]:
    phrase = clean_study_text(card.get("phrase")) or card_answer_core(card)
    return V11_EXPRESSION_FALLBACKS.get(phrase_guide_key(phrase), {})


def _v11_guide(card: dict[str, Any]) -> dict[str, Any]:
    phrase = clean_study_text(card.get("phrase")) or card_answer_core(card)
    return PHRASE_GUIDES.get(phrase_guide_key(phrase), {})


def _strip_study_label(value: Any) -> str:
    text = clean_study_text(value).strip()
    return re.sub(
        r"^\s*(理解|怎么用|用法|换法|替换|例句|边界|易错|价值|语气|提醒|注意|误用|释义|意思)[:：]\s*",
        "",
        text,
    ).strip()


def _specific_v11_text(value: Any) -> str:
    text = _strip_study_label(value)
    if not text:
        return ""
    lowered = text.lower()
    if any(pattern in text or pattern.lower() in lowered for pattern in GENERIC_V11_STUDY_PATTERNS):
        return ""
    return text


def _non_generic_export_text(value: Any) -> str:
    text = clean_study_text(value)
    if not text:
        return ""
    lowered = text.lower()
    if any(pattern in text or pattern.lower() in lowered for pattern in GENERIC_V11_STUDY_PATTERNS):
        return ""
    return text


def _v11_sentence_translation_fallback(card: dict[str, Any]) -> str:
    fallback = _v11_fallback(card)
    english_key = _v11_lookup_key(card.get("english"))
    translations = fallback.get("source_translations")
    if isinstance(translations, dict) and english_key:
        return clean_study_text(translations.get(english_key))
    return clean_study_text(fallback.get("source_translation"))


def v11_meaning_text(card: dict[str, Any]) -> str:
    guide = _v11_guide(card)
    fallback = _v11_fallback(card)
    for candidate in (
        card.get("chinese"),
        card.get("answer_chinese"),
        card.get("meaning"),
        guide.get("chinese"),
        fallback.get("meaning"),
        card.get("chinese_feel"),
        card.get("definition"),
        card.get("natural_chinese"),
    ):
        text = _specific_v11_text(candidate)
        if text and has_cjk(text):
            return text.strip("。；; ")
    return ""


def v11_answer_note_text(card: dict[str, Any]) -> str:
    return answer_commentary_text(card.get("answer_core")) or answer_commentary_text(card.get("phrase"))


def v11_source_translation_text(card: dict[str, Any]) -> str:
    meaning_marker = _normalized_study_compare(v11_meaning_text(card))
    for candidate in (
        card.get("source_chinese"),
        card.get("sentence_chinese"),
        card.get("original_chinese"),
        card.get("natural_chinese"),
        card.get("full_chinese"),
    ):
        text = _specific_v11_text(candidate)
        if text and has_cjk(text) and _normalized_study_compare(text) != meaning_marker:
            return text.strip("；; ")
    fallback = _v11_sentence_translation_fallback(card)
    if fallback:
        return fallback
    text = _specific_v11_text(card.get("chinese"))
    if text and has_cjk(text) and _normalized_study_compare(text) != meaning_marker:
        return text.strip("；; ")
    return ""


def v11_usage_text(card: dict[str, Any]) -> str:
    guide = _v11_guide(card)
    fallback = _v11_fallback(card)
    lines = _study_lines(
        _specific_v11_text(card.get("how_to_use_it")),
        _specific_v11_text(card.get("definition")),
        _specific_v11_text(guide.get("definition")),
        _specific_v11_text(fallback.get("usage")),
    )
    return "\n".join(lines[:2])


def v11_self_sentence_text(card: dict[str, Any]) -> str:
    guide = _v11_guide(card)
    fallback = _v11_fallback(card)
    lines = _study_lines(
        _specific_v11_text(card.get("replacement_examples")),
        _specific_v11_text(_new_example_for_card(card)),
        _specific_v11_text(card.get("collocations")),
        _specific_v11_text(guide.get("example")),
        _specific_v11_text(fallback.get("self_sentence")),
    )
    return "\n".join(lines[:3])


def v11_misuse_text(card: dict[str, Any]) -> str:
    fallback = _v11_fallback(card)
    phrase = card_answer_core(card).lower()
    special_boundary = ""
    if "flat as a washboard" in phrase:
        special_boundary = V11_EXPRESSION_FALLBACKS["flat as a washboard"]["misuse"]
    teacher_note = _specific_v11_text(card.get("teacher_note"))
    usage_boundary = _specific_v11_text(card.get("usage_boundary"))
    confusable_note = _specific_v11_text(card.get("confusable_note"))
    if normalized_contains_text(teacher_note, usage_boundary):
        usage_boundary = ""
    if normalized_contains_text(teacher_note, confusable_note):
        confusable_note = ""
    lines = _study_lines(
        usage_boundary,
        special_boundary,
        confusable_note,
        teacher_note,
        _specific_v11_text(fallback.get("misuse")),
    )
    return "\n".join(lines[:3])


def _export_answer_label(card: dict[str, Any]) -> str:
    return answer_display_text(card.get("answer_core") or card.get("phrase")) or card_answer_core(card) or "这个学习点"


def _export_definition_fallback(card: dict[str, Any]) -> str:
    answer = _export_answer_label(card)
    return f"结合原句理解“{answer}”在这里的意思、搭配和使用场景。"


def _export_teacher_note_fallback(card: dict[str, Any]) -> str:
    answer = _export_answer_label(card)
    return f"注意“{answer}”的语气和适用对象，复习时对照原句判断是否自然。"


def export_meaning_text(card: dict[str, Any], use_v11_template: bool) -> str:
    if use_v11_template:
        return v11_meaning_text(card) or card_chinese_core(card) or clean_study_text(card.get("chinese"))
    return card_chinese_core(card) or clean_study_text(card.get("chinese"))


def export_definition_text(card: dict[str, Any], use_v11_template: bool) -> str:
    if use_v11_template:
        return (
            v11_usage_text(card)
            or _specific_v11_text(card.get("definition"))
            or _specific_v11_text(card.get("how_to_use_it"))
            or _non_generic_export_text(card.get("definition"))
            or _non_generic_export_text(card.get("how_to_use_it"))
            or _non_generic_export_text(card.get("learning_goal"))
            or _non_generic_export_text(card.get("why_it_matters"))
            or _export_definition_fallback(card)
        )
    return (
        _non_generic_export_text(card.get("definition"))
        or _non_generic_export_text(card.get("how_to_use_it"))
        or _non_generic_export_text(card.get("learning_goal"))
        or _non_generic_export_text(card.get("why_it_matters"))
        or _export_definition_fallback(card)
    )


def export_teacher_note_text(card: dict[str, Any], use_v11_template: bool) -> str:
    if use_v11_template:
        return (
            v11_misuse_text(card)
            or _specific_v11_text(card.get("teacher_note"))
            or _specific_v11_text(card.get("usage_boundary"))
            or _specific_v11_text(card.get("confusable_note"))
            or _non_generic_export_text(card.get("teacher_note"))
            or _non_generic_export_text(card.get("usage_boundary"))
            or _non_generic_export_text(card.get("confusable_note"))
            or _non_generic_export_text(card.get("why_it_matters"))
            or _export_teacher_note_fallback(card)
        )
    return (
        _non_generic_export_text(card.get("teacher_note"))
        or _non_generic_export_text(card.get("usage_boundary"))
        or _non_generic_export_text(card.get("confusable_note"))
        or _non_generic_export_text(card.get("why_it_matters"))
        or _export_teacher_note_fallback(card)
    )


def export_context_text(card: dict[str, Any], use_v11_template: bool) -> str:
    if use_v11_template:
        return (
            v11_source_translation_text(card)
            or clean_study_text(card.get("context"))
            or clean_study_text(card.get("source_chinese"))
            or clean_study_text(card.get("sentence_chinese"))
            or card_chinese_core(card)
        )
    return (
        clean_study_text(card.get("source_evidence"))
        or clean_study_text(card.get("context"))
        or clean_study_text(card.get("source_chinese"))
        or clean_study_text(card.get("sentence_chinese"))
        or card_chinese_core(card)
    )


def document_reading_context_text(card: dict[str, Any]) -> str:
    """Short usage context for EPUB/document language-reading cards.

    Document reading cards often carry a full source_evidence excerpt for model
    judgement. That excerpt can be multiple paragraphs long and must not be
    exported into the back-side "怎么用" block.
    """
    direct_context = _study_lines(
        clean_study_text(card.get("context")),
        clean_study_text(card.get("source_chinese")),
        clean_study_text(card.get("sentence_chinese")),
    )
    if direct_context:
        return direct_context[0]
    evidence = clean_study_text(card.get("source_evidence"))
    if evidence and len(evidence) <= 160:
        return evidence
    return "结合上方原句和文档语境复习这个表达。"


def ciba_contextual_meaning_text(card: dict[str, Any]) -> str:
    return (
        _specific_v11_text(card.get("chinese"))
        or _specific_v11_text(card.get("answer_chinese"))
        or _specific_v11_text(card.get("meaning"))
        or _specific_v11_text(card.get("chinese_feel"))
        or v11_meaning_text(card)
        or _specific_v11_text(card.get("natural_chinese"))
        or card_chinese_core(card)
        or clean_study_text(card.get("chinese"))
    )


def ciba_language_action_text(card: dict[str, Any]) -> str:
    lines = _study_lines(
        _specific_v11_text(card.get("learning_target")),
        _specific_v11_text(card.get("how_to_use_it")),
        _specific_v11_text(card.get("definition")),
        _specific_v11_text(card.get("learning_goal")),
        _export_definition_fallback(card),
    )
    return "。".join(lines[:2])


def ciba_conceptual_action_text(card: dict[str, Any]) -> str:
    lines = _study_lines(
        _specific_v11_text(card.get("conceptual_action")),
        _specific_v11_text(card.get("learning_target")),
    )
    return "\n".join(lines[:1])


def ciba_chinese_learner_trap_text(card: dict[str, Any]) -> str:
    lines = _study_lines(
        _specific_v11_text(card.get("chinese_learner_trap")),
        _specific_v11_text(card.get("confusable_note")),
    )
    return "\n".join(lines[:1])


def ciba_reason_text(card: dict[str, Any]) -> str:
    lines = _study_lines(
        _specific_v11_text(card.get("why_it_matters")),
        _specific_v11_text(card.get("why")),
        _specific_v11_text(card.get("value_reason")),
        _specific_v11_text(card.get("reason")),
    )
    duplicate_markers = {
        _normalized_study_compare(value)
        for value in _study_lines(
            ciba_boundary_text(card),
            _specific_v11_text(card.get("definition")),
            _specific_v11_text(card.get("collocations")),
        )
    }
    unique_lines: list[str] = []
    for line in lines:
        marker = _normalized_study_compare(line)
        if not marker:
            continue
        if any(
            marker == duplicate
            or (len(marker) > 16 and len(duplicate) > 16 and (marker in duplicate or duplicate in marker))
            for duplicate in duplicate_markers
        ):
            continue
        unique_lines.append(line)
    return "\n".join(unique_lines[:1])


def export_cloze_text(card: dict[str, Any], deck_kind_code: str = "") -> str:
    cloze = clean_study_text(card.get("cloze"))
    if deck_kind_code == "document_knowledge":
        cloze = re.sub(r"[（(][^）)]*[\u4e00-\u9fff][^）)]*[）)]", "", cloze).strip()
    return cloze


def ciba_transfer_text(card: dict[str, Any]) -> str:
    lines = _study_lines(
        _specific_v11_text(card.get("replacement_examples")),
        _specific_v11_text(_new_example_for_card(card)),
        _specific_v11_text(card.get("collocations")),
    )
    return "\n".join(lines[:3])


def ciba_boundary_text(card: dict[str, Any]) -> str:
    lines = _study_lines(
        _specific_v11_text(card.get("chinese_learner_trap")),
        _specific_v11_text(card.get("usage_boundary")),
        _specific_v11_text(card.get("confusable_note")),
        _specific_v11_text(card.get("avoid_reason")),
        _specific_v11_text(card.get("boundary")),
        _specific_v11_text(card.get("teacher_note")),
        _export_teacher_note_fallback(card),
    )
    return "\n".join(lines[:1])


def ciba_source_context_text(card: dict[str, Any]) -> str:
    return (
        clean_study_text(card.get("source_evidence"))
        or v11_source_translation_text(card)
        or clean_study_text(card.get("context"))
        or clean_study_text(card.get("source_chinese"))
        or clean_study_text(card.get("sentence_chinese"))
    )


def v11_definition_text(card: dict[str, Any]) -> str:
    return export_definition_text(card, True)


def v11_migration_text(card: dict[str, Any]) -> str:
    return v11_self_sentence_text(card)


def v11_teacher_note_text(card: dict[str, Any]) -> str:
    return export_teacher_note_text(card, True)


def card_visual_role(card: dict[str, Any], deck_kind_code: str = "") -> str:
    if deck_kind_code == "document_knowledge":
        return "knowledge"
    if deck_kind_code == "document_reading":
        return "document_reading"
    card_type = str(card.get("type") or "").strip()
    if card_type == "listening":
        return "listening"
    if card_type == "cloze":
        return "cloze"
    if card_type == "knowledge":
        return "knowledge"
    if is_contextual_vocabulary_card(card):
        return "vocabulary"
    return "phrase"


def card_template_labels(card: dict[str, Any], deck_kind_code: str = "") -> dict[str, str]:
    role = card_visual_role(card, deck_kind_code)
    if role == "listening":
        return {
            "card_layout": "listening",
            "front_kicker": "只听一遍，先复述完整句。",
            "source_label": "听力原句",
            "understand_label": "听错点",
            "use_label": "关键表达",
        }
    if role == "cloze":
        return {
            "card_layout": "cloze",
            "front_kicker": "根据语气补出关键表达。",
            "source_label": "原句",
            "understand_label": "为什么这样填",
            "use_label": "可替换框架",
        }
    if role == "vocabulary":
        return {
            "card_layout": "vocabulary",
            "front_kicker": "按原句场景解释这个词。",
            "source_label": "原句",
            "understand_label": "此处词义",
            "use_label": "搭配 / 易混义",
        }
    if role == "knowledge":
        return {
            "card_layout": "knowledge",
            "front_kicker": "先用自己的话回答。",
            "source_label": "正面问题",
            "understand_label": "关键机制",
            "use_label": "相关概念",
        }
    if role == "document_reading":
        return {
            "card_layout": "document_reading",
            "front_kicker": "先解释原文里的语言点。",
            "source_label": "原文线索",
            "understand_label": "怎么理解",
            "use_label": "怎么用",
        }
    return {
        "card_layout": "phrase",
        "front_kicker": "根据中文语境回忆自然表达。",
        "source_label": "英文原句",
        "understand_label": "怎么理解",
        "use_label": "怎么迁移",
    }


def card_front_fields(card: dict[str, Any], *, repetition_mode: bool = False) -> dict[str, str]:
    card_type = card.get("type", "")
    english = clean_study_text(card.get("english"))
    phrase = clean_study_text(card.get("phrase"))
    chinese = card_chinese_core(card)
    retrieval_prompt = clean_study_text(card.get("retrieval_prompt"))
    if repetition_mode and card_type != "knowledge":
        return {
            "front_prompt": "听原声，跟读这一句。",
            "front_content": "先听一遍，再模仿语气和节奏。",
            "answer": card_answer_core(card),
        }
    if card_type == "listening":
        return {
            "front_prompt": "只看画面和听声音，先复述这一句。",
            "front_content": "",
            "answer": english,
        }
    if card_type == "phrase":
        if retrieval_prompt:
            front_prompt = retrieval_prompt
        elif is_contextual_vocabulary_card(card):
            front_prompt = f"“{phrase}”在这句里是什么意思？" if phrase else "这个词在原句里是什么意思？"
        else:
            cue = compact_retrieval_cue(card.get("natural_chinese") or chinese or card.get("chinese_feel"))
            front_prompt = f"这句里表示“{cue}”的自然表达是什么？" if cue else "回忆这句里最值得带走的自然表达。"
        return {
            "front_prompt": front_prompt,
            "front_content": (
                "按原句场景解释，不背词典第一个释义。"
                if is_contextual_vocabulary_card(card)
                else "先听原声，再在心里补出这个表达。"
            ),
            "answer": card_answer_core(card),
        }
    if card_type == "cloze":
        return {
            "front_prompt": "根据语气和画面，在心里补出关键表达。",
            "front_content": clean_study_text(card.get("cloze")) or "先听原声，再补出关键表达。",
            "answer": card_answer_core(card),
        }
    if card_type == "knowledge":
        short_answer = phrase if phrase and len(phrase) <= 32 else clean_study_text(card.get("answer_core"))
        if len(short_answer) > 48:
            short_answer = ""
        return {
            "front_prompt": english or "回忆这段资料的核心知识点。",
            "front_content": "先用自己的话回答，再翻面核对结构化解释。",
            "answer": short_answer or chinese or phrase,
        }
    return {
        "front_prompt": "回忆这张卡的核心表达。",
        "front_content": "",
        "answer": phrase or english,
    }


def card_phrase_tts_text(card: dict[str, Any], front_fields: dict[str, str]) -> str:
    candidates = [
        front_fields.get("answer"),
        card.get("answer_core"),
        card.get("phrase"),
    ]
    for value in candidates:
        text = answer_display_text(value)
        if is_answer_expression_candidate(text, card):
            return clean_tts_input_text(text)
    return ""


def language_code(language: str) -> str:
    return normalize_learning_language(language)


def tts_volume_filter_args(output_volume: Any) -> list[str]:
    volume = normalized_tts_output_volume(output_volume)
    if abs(volume - 1.0) < 0.001:
        return []
    return ["-af", f"volume={volume:.3f}"]


def apply_tts_output_volume(output_path: Path, output_volume: Any, label: str) -> None:
    volume_args = tts_volume_filter_args(output_volume)
    if not volume_args:
        return
    volume_path = output_path.with_name(f"{output_path.stem}.volume{output_path.suffix}")
    try:
        completed = media_policy_run_ffmpeg(
            [
                "-i",
                str(output_path),
                *volume_args,
                "-acodec",
                "libmp3lame",
                "-q:a",
                "5",
                str(volume_path),
            ],
            timeout=120,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **hidden_subprocess_flags(),
        )
    except (MediaToolPolicyError, subprocess.TimeoutExpired) as error:
        volume_path.unlink(missing_ok=True)
        raise RuntimeError(f"{label} 音量处理被安全策略阻止：{error}") from error
    if completed.returncode != 0:
        volume_path.unlink(missing_ok=True)
        raise RuntimeError(f"{label} 音量处理失败：{completed.stderr[-800:]}")
    volume_path.replace(output_path)


def transcode_wav_file_to_mp3(wav_path: Path, output_path: Path, label: str, output_volume: Any = 0.65) -> None:
    try:
        completed = media_policy_run_ffmpeg(
            [
                "-i",
                str(wav_path),
                *tts_volume_filter_args(output_volume),
                "-acodec",
                "libmp3lame",
                "-q:a",
                "5",
                str(output_path),
            ],
            timeout=120,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **hidden_subprocess_flags(),
        )
    except (MediaToolPolicyError, subprocess.TimeoutExpired) as error:
        wav_path.unlink(missing_ok=True)
        raise RuntimeError(f"{label} 音频转码被安全策略阻止：{error}") from error
    wav_path.unlink(missing_ok=True)
    if completed.returncode != 0:
        raise RuntimeError(f"{label} 音频转码失败：{completed.stderr[-800:]}")


def write_managed_tts_audio(
    audio: ManagedTtsAudio,
    output_path: Path,
    *,
    output_volume: Any = 0.65,
) -> None:
    mime_type = audio.mime_type.split(";", 1)[0].strip().casefold()
    if mime_type in {"audio/mpeg", "audio/mp3"}:
        output_path.write_bytes(audio.data)
        apply_tts_output_volume(output_path, output_volume, "Managed TTS")
        return
    if mime_type in {"audio/wav", "audio/x-wav", "audio/wave", "audio/vnd.wave"}:
        wav_path = output_path.with_suffix(".managed.wav")
        wav_path.write_bytes(audio.data)
        transcode_wav_file_to_mp3(wav_path, output_path, "Managed TTS", output_volume)
        return
    if mime_type in {"audio/pcm", "audio/l16", "audio/raw"}:
        sample_rate = int(audio.sample_rate or 0)
        if not 8000 <= sample_rate <= 48000:
            raise RuntimeError("Managed TTS PCM 音频缺少有效采样率。")
        pcm_path = output_path.with_suffix(".managed.pcm")
        pcm_path.write_bytes(audio.data)
        try:
            run_ffmpeg(
                [
                    "-f",
                    "s16le",
                    "-ar",
                    str(sample_rate),
                    "-ac",
                    "1",
                    "-i",
                    str(pcm_path),
                    *tts_volume_filter_args(output_volume),
                    "-acodec",
                    "libmp3lame",
                    "-q:a",
                    "5",
                    str(output_path),
                ]
            )
        finally:
            pcm_path.unlink(missing_ok=True)
        return
    raise RuntimeError(f"Managed TTS 返回了不支持的音频格式：{mime_type or 'unknown'}")


def synthesize_tts(
    project: dict[str, Any],
    segment: dict[str, Any],
    output_path: Path,
    text_override: str | None = None,
    tts_kind: str = "sentence",
) -> dict[str, Any] | bool:
    tts = normalized_tts_config(project)
    brokered = managed_tts_broker_is_configured()
    if not tts["enabled"] or tts["provider"] == "disabled":
        return False

    provider = tts["provider"]
    raw_text = (text_override or segment.get("text", "")).strip()
    if not provider or not raw_text:
        return False
    try:
        text = clean_tts_input_text(raw_text)
    except RuntimeError:
        return False

    cache_path, cache_key = tts_cache_path(tts, text, project.get("language", "en"))
    if tts_cache_read_enabled(project) and copy_cached_file(cache_path, output_path):
        try:
            validate_tts_audio_duration(output_path, text, tts_kind)
        except RuntimeError:
            discard_cached_file(output_path)
            discard_cached_file(cache_path)
        else:
            semantic_role = "phrase_tts" if tts_kind == "phrase" else "sentence_tts"
            if not tts_semantic_verification_enabled(project):
                return {
                    "ok": True,
                    "cache_hit": True,
                    "cache_key": cache_key,
                    "semantic": tts_semantic_not_applicable(text, semantic_role),
                }
            cached_semantic = load_tts_cache_semantic_meta(cache_path, text)
            if cached_semantic:
                return {"ok": True, "cache_hit": True, "cache_key": cache_key, "semantic": cached_semantic}
            semantic = verify_tts_audio_semantics(
                output_path,
                text,
                role=semantic_role,
                project=project,
            )
            if semantic.get("semantic_verification") == "passed":
                store_tts_cache_semantic_meta(cache_path, text, semantic)
                return {"ok": True, "cache_hit": True, "cache_key": cache_key, "semantic": semantic}
            discard_cached_file(output_path)
            if semantic.get("semantic_verification") == "mismatch":
                discard_cached_file(cache_path)
                discard_cached_file(tts_cache_meta_path(cache_path))

    if not brokered and not tts["api_key"] and not is_gemini_vertex_tts_config(tts):
        return False

    if not provider or not text:
        return False

    def done() -> dict[str, Any]:
        try:
            validate_tts_audio_duration(output_path, text, tts_kind)
        except RuntimeError:
            discard_cached_file(output_path)
            discard_cached_file(cache_path)
            raise
        semantic_role = "phrase_tts" if tts_kind == "phrase" else "sentence_tts"
        if not tts_semantic_verification_enabled(project):
            store_cached_file(output_path, cache_path)
            return {
                "ok": True,
                "cache_hit": False,
                "cache_key": cache_key,
                "semantic": tts_semantic_not_applicable(text, semantic_role),
            }
        semantic = verify_tts_audio_semantics(
            output_path,
            text,
            role=semantic_role,
            project=project,
        )
        if semantic.get("semantic_verification") == "mismatch":
            discard_cached_file(output_path)
            raise RuntimeError(
                "TTS 语义核验失败："
                f"期望 {text!r}，ASR 听到 {semantic.get('asr_transcript')!r}。"
            )
        if semantic.get("semantic_verification") == "passed":
            store_cached_file(output_path, cache_path)
            store_tts_cache_semantic_meta(cache_path, text, semantic)
        return {"ok": True, "cache_hit": False, "cache_key": cache_key, "semantic": semantic}

    if brokered:
        if not managed_tts_operation_available():
            raise ManagedTtsBrokerError("Managed TTS operation is not authorized for this task")
        segment_id = str(segment.get("id") or segment.get("segment_id") or "segment")
        resolved_language = resolve_tts_language_code(tts, project.get("language", "en"))
        audio = managed_tts_request(
            text,
            language=resolved_language,
            sample_rate=int(tts.get("sample_rate") or 24000),
            bit_rate=int(tts.get("bit_rate") or 128000),
            work_unit_base=f"{tts_kind}:{segment_id}",
        )
        write_managed_tts_audio(audio, output_path, output_volume=tts.get("output_volume"))
        return done()

    if provider in {"grok", "xai"}:
        audio = call_tts_audio(tts, text, project.get("language", "en"))
        output_path.write_bytes(audio)
        apply_tts_output_volume(output_path, tts.get("output_volume"), "Grok TTS")
        return done()

    if is_mimo_config(tts):
        if not compatible_base_url(tts) or not tts["model"]:
            return False
        wav_path = output_path.with_suffix(".mimo.wav")
        audio = call_tts_audio(tts, text, project.get("language", "en"))
        wav_path.write_bytes(audio)
        transcode_wav_file_to_mp3(wav_path, output_path, "MIMO TTS", tts.get("output_volume"))
        return done()

    if provider in QWEN_TTS_PROVIDERS:
        if not tts["base_url"] or not tts["model"]:
            return False
        wav_path = output_path.with_suffix(".qwen.wav")
        audio = call_tts_audio(tts, text, project.get("language", "en"))
        wav_path.write_bytes(audio)
        transcode_wav_file_to_mp3(wav_path, output_path, "Qwen TTS", tts.get("output_volume"))
        return done()

    if is_gemini_vertex_tts_config(tts):
        if not tts["model"]:
            return False
        wav_path = output_path.with_suffix(".gemini_vertex.wav")
        audio = call_tts_audio(tts, text, project.get("language", "en"))
        wav_path.write_bytes(audio)
        transcode_wav_file_to_mp3(wav_path, output_path, "Gemini Vertex TTS", tts.get("output_volume"))
        return done()

    if provider in OPENAI_COMPATIBLE_PROVIDERS:
        if not compatible_base_url(tts) or not tts["model"]:
            return False
        audio = call_tts_audio(tts, text, project.get("language", "en"))
        output_path.write_bytes(audio)
        apply_tts_output_volume(output_path, tts.get("output_volume"), "OpenAI-compatible TTS")
        return done()

    if provider == "gemini":
        model = tts["model"] or "gemini-2.5-flash-preview-tts"
        voice = tts["voice"] or "Kore"

        response = http_json(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            {"x-goog-api-key": tts["api_key"]},
            {
                "contents": [{"parts": [{"text": exact_tts_prompt(text)}]}],
                "generationConfig": {
                    "responseModalities": ["AUDIO"],
                    "speechConfig": {
                        "voiceConfig": {
                            "prebuiltVoiceConfig": {
                                "voiceName": voice,
                            }
                        }
                    },
                },
                "model": model,
            },
        )
        data = response["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
        pcm_path = output_path.with_suffix(".pcm")
        pcm_path.write_bytes(base64.b64decode(data))
        run_ffmpeg(
            [
                "-f",
                "s16le",
                "-ar",
                "24000",
                "-ac",
                "1",
                "-i",
                str(pcm_path),
                *tts_volume_filter_args(tts.get("output_volume")),
                "-acodec",
                "libmp3lame",
                "-q:a",
                "5",
                str(output_path),
            ]
        )
        pcm_path.unlink(missing_ok=True)
        return done()

    return False


def export_tts_concurrency(project: dict[str, Any]) -> int:
    tts = normalized_tts_config(project)
    raw_value = (
        tts.get("concurrency")
        or project.get("tts_concurrency")
        or project.get("export_tts_concurrency")
        or project.get("tts_export_concurrency")
    )
    if raw_value in (None, ""):
        raw_value = 2 if is_gemini_vertex_tts_config(tts) else 3
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        value = 2 if is_gemini_vertex_tts_config(tts) else 3
    return max(1, min(4, value))


def export_media_concurrency(project: dict[str, Any]) -> int:
    raw_value = project.get("media_concurrency") or project.get("export_media_concurrency")
    if raw_value in (None, ""):
        raw_value = 3
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        value = 3
    return max(1, min(3, value))


def publish_file_no_replace(source: Path, destination: Path) -> None:
    """Atomically publish a same-directory file without replacing an existing one."""

    if os.name == "nt":
        os.rename(source, destination)
        return
    os.link(source, destination)
    source.unlink()


def export_run_timestamp() -> float:
    """Return the wall-clock timestamp used only to label one export run."""

    return time.time()


def export_quality_audit(project: dict[str, Any], export_segments: list[dict[str, Any]]) -> dict[str, Any]:
    empty_required_fields = 0
    blocked_text_values = 0
    duplicate_visible_cards = 0
    pronunciation_meta_errors = 0
    answer_not_in_source = 0
    blocked_cards: list[dict[str, Any]] = []
    seen_cards: set[str] = set()
    deck_kind_code = str(project.get("deck_kind") or project.get("project_kind") or "")
    if not deck_kind_code:
        if project.get("source_mode") == "document":
            deck_kind_code = "document_reading" if project.get("document_study_mode") == "language_reading" else "document_knowledge"
        else:
            deck_kind_code = "video_language"
    project_template_id = str(project.get("template_id") or "immersive_v11")
    project_is_ciba_template = normalize_template_id(project_template_id) == "ciba_tianxia_v1"
    project_uses_v11_repetition_front = uses_v11_repetition_front(project_template_id, deck_kind_code)
    for segment in export_segments:
        source_text = clean_study_text(segment.get("text") or "")
        for card in [card for card in segment.get("cards", []) if card.get("enabled", True)]:
            use_v11_template = project_uses_v11_repetition_front or (
                str(card.get("card_layout") or "").lower() == "repetition" and not project_is_ciba_template
            )
            if project_is_ciba_template:
                meaning_field = ciba_contextual_meaning_text(card)
                definition_field = ciba_language_action_text(card)
                teacher_note_field = ciba_boundary_text(card)
                context_field = ciba_source_context_text(card)
            else:
                meaning_field = export_meaning_text(card, use_v11_template)
                definition_field = export_definition_text(card, use_v11_template)
                teacher_note_field = export_teacher_note_text(card, use_v11_template)
                context_field = document_reading_context_text(card) if deck_kind_code == "document_reading" else export_context_text(card, use_v11_template)
            required_values = {
                "English": card.get("english") or source_text,
                "Answer": card.get("answer_core") or card.get("phrase"),
                "Chinese": meaning_field,
                "Definition": definition_field,
                "TeacherNote": teacher_note_field,
                "Context": context_field,
            }
            empty_required_fields += sum(1 for value in required_values.values() if not clean_study_text(value))
            blocked_matches = export_audit_blocked_matches(card, required_values)
            blocked_text_values += len(blocked_matches)
            if blocked_matches:
                first_match = blocked_matches[0]
                blocked_cards.append(
                    {
                        "card_id": str(card.get("id") or ""),
                        "learning_point_id": str(card.get("learning_point_id") or ""),
                        "segment_id": str(segment.get("id") or ""),
                        "source_time": str(segment.get("source_time") or segment.get("media_source_time") or ""),
                        "title": export_audit_card_title(segment, card),
                        "answer_summary": audit_text_excerpt(card.get("answer_core") or card.get("phrase") or ""),
                        "matched_field": first_match.get("field", ""),
                        "matched_text": first_match.get("matched_text", ""),
                        "matched_patterns": first_match.get("patterns", ""),
                        "matched_fields": blocked_matches,
                        "suggested_action": "移除这张需修复卡，或重新生成/手动修正草稿字段后再导出。",
                    }
                )
            answer = answer_display_text(card.get("answer_core") or card.get("phrase") or "")
            evidence_text = " ".join(
                clean_study_text(value)
                for value in [source_text, segment.get("document_excerpt"), card.get("source_evidence"), card.get("english")]
                if clean_study_text(value)
            )
            answer_to_check = answer_display_text(card.get("phrase") or card.get("normalized_answer") or card.get("answer_core") or "")
            has_document_source_evidence = deck_kind_code == "document_knowledge" and bool(clean_study_text(card.get("source_evidence")))
            if (
                not has_document_source_evidence
                and answer_to_check
                and evidence_text
                and not phrase_in_text(evidence_text, answer_to_check)
                and str(card.get("type") or "") != "listening"
            ):
                answer_not_in_source += 1
            duplicate_key = f"{segment.get('id')}:{str(card.get('type') or '')}:{answer.lower()}"
            if duplicate_key in seen_cards:
                duplicate_visible_cards += 1
            seen_cards.add(duplicate_key)
            meta = card.get("pronunciation_meta")
            if isinstance(meta, str) and meta.strip():
                try:
                    parsed = json.loads(meta)
                    if not isinstance(parsed, dict):
                        pronunciation_meta_errors += 1
                except json.JSONDecodeError:
                    pronunciation_meta_errors += 1
            elif meta is not None and not isinstance(meta, dict):
                pronunciation_meta_errors += 1
    return {
        "card_count": sum(len([card for card in segment.get("cards", []) if card.get("enabled", True)]) for segment in export_segments),
        "segment_count": len(export_segments),
        "empty_required_fields": empty_required_fields,
        "blocked_text_values": blocked_text_values,
        "blocked_cards": blocked_cards,
        "duplicate_visible_cards": duplicate_visible_cards,
        "answer_not_in_source": answer_not_in_source,
        "pronunciation_meta_errors": pronunciation_meta_errors,
    }


def handle_export(payload: dict[str, Any]) -> dict[str, Any]:
    timing_started = time.perf_counter()
    prepare_started = timing_started
    timing_ms: dict[str, int] = {}
    emit_progress("export", "prepare", 4, "准备导出 Anki 卡包。")
    try:
        import genanki
    except ImportError:
        fail("缺少 genanki。请运行：pip install -r workers/requirements.txt")

    project = payload.get("project") or {}
    output_dir = Path(payload.get("output_dir") or os.getcwd())
    if not output_dir.exists():
        fail(f"导出目录不存在：{output_dir}")
    canonical_apkg_path_text = str(payload.get("canonical_apkg_path") or "").strip()
    canonical_apkg_path = Path(canonical_apkg_path_text) if canonical_apkg_path_text else None
    if canonical_apkg_path is not None:
        if canonical_apkg_path.suffix.lower() != ".apkg":
            fail(f"正式验收 APKG 路径必须以 .apkg 结尾：{canonical_apkg_path}")
        if not canonical_apkg_path.parent.exists():
            fail(f"正式验收 APKG 目录不存在：{canonical_apkg_path.parent}")
        try:
            selected_output_dir = output_dir.resolve()
            canonical_parent = canonical_apkg_path.parent.resolve()
        except OSError as exc:
            fail(f"正式验收 APKG 路径不可用：{exc}")
        if canonical_parent != selected_output_dir:
            fail(
                "正式验收 APKG 路径必须直接位于已选择的保存目录内，"
                f"selected={selected_output_dir} canonical_parent={canonical_parent}"
            )
        if canonical_apkg_path.exists():
            fail(f"正式验收 APKG 已存在，为避免覆盖证据已停止：{canonical_apkg_path}")

    is_document_project = project.get("source_mode") == "document"
    video_path_raw = clean_input_path(project.get("video_path"))
    video_required = video_media_required_for_export(project)
    skip_video_media = is_document_project or video_free_export_allowed(project)
    export_webm_media = project.get("export_webm_media")
    export_webm_media = True if export_webm_media is None else bool(export_webm_media)
    video_path = Path(video_path_raw) if video_path_raw else Path()
    if video_required and not video_path_raw:
        fail(
            "当前是视频卡导出，但项目里没有可切片的视频文件。请重新使用视频素材生成，或修复下载/本地路径后重试。",
            error_code=worker_errors.FFMPEG_SLICE_FAILED,
            stage="media",
            retryable=True,
            fallbacks=[],
        )
    if not skip_video_media and not video_path.exists():
        fail(
            f"视频文件不存在：{video_path}。请重新选择/下载视频，确认本地路径后再导出。",
            error_code=worker_errors.FFMPEG_SLICE_FAILED,
            stage="media",
            retryable=True,
            fallbacks=[],
        )
    video_source_fingerprint = file_fingerprint(video_path) if not skip_video_media else ""
    source_info = project.get("source_info") if isinstance(project.get("source_info"), dict) else {}

    def export_source_identity() -> dict[str, Any]:
        identity: dict[str, Any] = {
            "source_mode": str(project.get("source_mode") or ""),
            "source_title": str(project.get("title") or source_info.get("title") or ""),
            "url_import_mode": str(project.get("url_import_mode") or source_info.get("url_import_mode") or ""),
            "source_download_mode": str(source_info.get("download_mode") or ""),
            "source_transcript_only": bool(source_info.get("transcript_only")),
            "source_skip_video_slicing": bool(project.get("skip_video_slicing") or source_info.get("skip_video_slicing")),
            "source_video_path": str(video_path) if video_path_raw else str(source_info.get("video_path") or ""),
            "source_video_fingerprint": str(
                source_info.get("video_fingerprint") or source_info.get("video_sha256") or video_source_fingerprint or ""
            ),
            "source_video_sha256": str(source_info.get("video_sha256") or ""),
            "source_subtitle_path": str(export_subtitle_path or source_info.get("subtitle_path") or project.get("subtitle_path") or ""),
            "source_subtitle_fingerprint": str(
                source_info.get("subtitle_fingerprint")
                or source_info.get("subtitle_sha256")
                or file_fingerprint(export_subtitle_path or source_info.get("subtitle_path") or project.get("subtitle_path") or "")
            ),
            "source_subtitle_sha256": str(source_info.get("subtitle_sha256") or ""),
            "source_subtitle_status": str(export_subtitle_status or ""),
        }
        source_url = str(project.get("source_url") or source_info.get("webpage_url") or source_info.get("url") or "")
        if source_url:
            identity["source_url"] = source_url
        source_fingerprint_value = str(project.get("source_fingerprint") or source_info.get("source_fingerprint") or "")
        if source_fingerprint_value:
            identity["source_fingerprint"] = source_fingerprint_value
        filtered = {key: value for key, value in identity.items() if value not in (None, "", [])}
        scrubbed = scrub_runtime_secrets(filtered)
        return scrubbed if isinstance(scrubbed, dict) else {}

    source_identity: dict[str, Any] = {}

    emit_progress("export", "template", 10, "正在准备 Anki 模板和导出目录。")
    export_run_id = int(export_run_timestamp())
    export_root = Path(
        tempfile.mkdtemp(
            prefix=f"AnkiCard-{safe_filename(project.get('title', 'deck'))}-{export_run_id}-",
            dir=str(output_dir),
        )
    )
    media_dir = export_root / "media"
    media_dir.mkdir()

    if is_document_project:
        deck_kind_code = "document_reading" if project.get("document_study_mode") == "language_reading" else "document_knowledge"
        deck_kind = "文档精读卡" if deck_kind_code == "document_reading" else "文档知识卡"
    else:
        deck_kind_code = "subtitle_language" if skip_video_media else "video_language"
        deck_kind = "字幕语言卡" if skip_video_media else "视频语言卡"
    review_density = normalize_review_density(project.get("review_density"))
    parent_deck_name, batch_deck_specs = batch_export_deck_specs(project)
    is_batch_export = bool(project.get("batch_enabled")) and bool(batch_deck_specs)
    project_deck_title = anki_deck_part(project.get("title") or project.get("id") or "Untitled", "Untitled")
    export_timestamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(export_run_id))
    if is_batch_export:
        deck_name = parent_deck_name
    elif deck_kind_code in {"video_language", "subtitle_language"}:
        deck_name = anki_deck_name(f"{deck_kind} - {project_deck_title} - {export_timestamp}", deck_kind)
    else:
        deck_name = f"{deck_kind}::{project_deck_title}"
    template_id = normalize_template_id(project.get("template_id", "immersive_v11"))
    card_style = normalize_card_style(project.get("card_style"))
    template_family = anki_template_family(template_id, deck_kind_code, card_style, review_density)
    template_label, template_css, front_template, back_template = anki_template_assets(template_id, deck_kind_code, card_style, review_density)
    template_version = anki_template_version(template_id, deck_kind_code)
    anki_tag = f"anki_card_generator_{template_version.lower()}"
    is_ciba_template = normalize_template_id(template_id) == "ciba_tianxia_v1"
    use_v11_repetition_front = uses_v11_repetition_front(template_id, deck_kind_code)
    model_field_specs = note_model_field_specs(use_v11_repetition_front)
    model_field_names = [str(field["name"]) for field in model_field_specs]
    note_model_contract = resolve_export_note_model_contract(
        template_family,
        template_version,
        template_label,
    )
    validate_generated_note_model(
        note_model_contract,
        field_names=model_field_names,
        css=template_css,
        qfmt=front_template,
        afmt=back_template,
    )
    model = genanki.Model(
        str(note_model_contract.note_model_id),
        note_model_contract.model_name,
        fields=model_field_specs,
        templates=[
            {
                "name": template_label,
                "qfmt": front_template,
                "afmt": back_template,
            }
        ],
        css=template_css,
    )
    default_deck = genanki.Deck(stable_id(deck_name, 1500000000), deck_name)
    batch_decks_by_item_id: dict[str, Any] = {}
    decks_for_package: list[Any] = [default_deck]
    deck_names_for_result: list[str] = [deck_name]
    if is_batch_export:
        decks_for_package = []
        deck_names_for_result = []
        for spec in batch_deck_specs:
            item_deck_name = spec["deck_name"]
            item_deck = genanki.Deck(stable_id(item_deck_name, 1500000000), item_deck_name)
            batch_decks_by_item_id[spec["id"]] = item_deck
            decks_for_package.append(item_deck)
            deck_names_for_result.append(item_deck_name)
        if not decks_for_package:
            decks_for_package = [default_deck]
            deck_names_for_result = [deck_name]
    fallback_batch_deck = genanki.Deck(stable_id(f"{deck_name}::未分组", 1500000000), f"{deck_name}::未分组") if is_batch_export else default_deck
    fallback_batch_deck_used = False
    generated_model_deck_ids = [int(deck.deck_id) for deck in decks_for_package]
    validate_generated_note_model(
        note_model_contract,
        field_names=model_field_names,
        css=template_css,
        qfmt=front_template,
        afmt=back_template,
        model_json=model.to_json(0, generated_model_deck_ids[0]),
        deck_ids=generated_model_deck_ids,
    )

    exported_batch_item_ids: set[str] = set()
    media_files: list[str] = []
    media_ledger: list[dict[str, Any]] = []
    card_media_ledger: list[dict[str, Any]] = []
    media_by_clip_key: dict[tuple[str, str, str, bool], dict[str, str]] = {}
    tts_by_segment: dict[str, str] = {}
    sentence_tts_text_by_segment: dict[str, str] = {}
    tts_semantic_by_segment: dict[str, dict[str, Any]] = {}
    phrase_tts_by_phrase: dict[str, str] = {}
    phrase_tts_cache_hit_by_phrase: dict[str, bool] = {}
    phrase_tts_semantic_by_phrase: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    presentation_warnings: list[dict[str, Any]] = []
    tts_failure_items: list[dict[str, Any]] = []
    tts_config = normalized_tts_config(project)
    tts_requested = bool(tts_config["enabled"] and tts_config["provider"] != "disabled")
    expected_phrase_tts_keys: set[str] = set()
    exported_cards = 0
    cut_segments: set[str] = set()
    video_segment_count = 0
    video_file_count = 0
    original_audio_count = 0
    tts_cache_hit_count = 0
    media_cache_miss_count = 0
    media_cache_hit_count = 0
    media_reused_segment_count = 0
    project_card_prefix = safe_filename(project.get("title") or project.get("id") or "deck")
    media_prefix = project_media_prefix(project, time.time_ns())
    export_progress_percent = 10

    def emit_export_progress(stage: str, percent: int, message: str) -> None:
        nonlocal export_progress_percent
        export_progress_percent = max(export_progress_percent, min(100, int(percent)))
        emit_progress("export", stage, export_progress_percent, message)

    def ledger_add(
        file_name: str,
        *,
        role: str,
        segment: dict[str, Any],
        card: dict[str, Any] | None = None,
        field: str = "",
        tts_text: str = "",
        cache_hit: bool | None = None,
        semantic: dict[str, Any] | None = None,
    ) -> None:
        if not file_name:
            return
        entry = {
            "file": Path(file_name).name,
            "role": role,
            "segment_id": safe_filename(str(segment.get("id") or "segment")),
            "card_id": (
                f"{project_card_prefix}_{str(card.get('id') or '')}"
                if isinstance(card, dict) and str(card.get("id") or "")
                else ""
            ),
            "learning_point_id": str((card or segment).get("learning_point_id") or ""),
            "field": field,
            "source_time": str(segment.get("source_time") or segment_display_source_time(segment)),
            "media_source_time": str(segment.get("media_source_time") or segment_display_source_time(segment)),
            "source_cue_ids": segment.get("source_cue_ids") or [],
            "source_cue_count": segment.get("source_cue_count"),
            "source_cue_start": segment.get("source_cue_start"),
            "source_cue_end": segment.get("source_cue_end"),
            "source_cue_time": str(segment.get("source_cue_time") or ""),
            "source_cue_texts": segment.get("source_cue_texts") or [],
            "source_merge_reason": str(segment.get("source_merge_reason") or ""),
            "source_sentence_quality_flags": segment.get("source_sentence_quality_flags") or [],
            "source_sentence_quality_status": str(segment.get("source_sentence_quality_status") or ""),
            "media_alignment_status": str(segment.get("media_alignment_status") or ""),
            "media_alignment_text": clean_study_text(segment.get("media_alignment_text") or segment.get("text") or ""),
            "media_alignment_source_text": clean_study_text(
                segment.get("media_alignment_source_text")
                or segment.get("full_source_sentence")
                or segment.get("source_sentence")
                or segment.get("text")
                or ""
            ),
            "tts_text": clean_tts_input_text(tts_text) if tts_text else "",
            "text_hash": media_text_hash(tts_text) if tts_text else "",
        }
        entry.update(source_identity)
        segment_subtitle_diagnostic = subtitle_alignment_by_segment.get(str(segment.get("id") or ""), {})
        entry.update(segment_subtitle_diagnostic)
        if cache_hit is not None:
            entry["cache_hit"] = cache_hit
        if role in {"sentence_tts", "phrase_tts"}:
            entry.update(
                {
                    "provider": str(tts_config.get("provider") or ""),
                    "model": str(tts_config.get("model") or ""),
                    "voice": str(tts_config.get("voice") or ""),
                    "language": resolve_tts_language_code(tts_config, project.get("language", "en")),
                }
            )
            semantic = semantic if isinstance(semantic, dict) else {}
            default_semantic_status = "manual_review_required" if tts_semantic_verification_enabled(project) else "not_applicable"
            entry["semantic_verification"] = str(semantic.get("semantic_verification") or default_semantic_status)
            entry["manual_review_required"] = bool(
                semantic.get("manual_review_required")
                if "manual_review_required" in semantic
                else entry["semantic_verification"] == "manual_review_required"
            )
            entry["semantic_review_reasons"] = (
                semantic.get("semantic_review_reasons")
                if isinstance(semantic.get("semantic_review_reasons"), list)
                else tts_semantic_base_reasons(role, tts_text)
                if tts_semantic_verification_enabled(project)
                else []
            )
            if semantic.get("asr_provider"):
                entry["asr_provider"] = str(semantic.get("asr_provider") or "")
            if semantic.get("asr_transcript"):
                entry["asr_transcript"] = str(semantic.get("asr_transcript") or "")
            if semantic.get("expected_text_normalized"):
                entry["expected_text_normalized"] = str(semantic.get("expected_text_normalized") or "")
            if semantic.get("actual_text_normalized"):
                entry["actual_text_normalized"] = str(semantic.get("actual_text_normalized") or "")
            if role == "phrase_tts" and tts_text:
                entry["max_duration_seconds"] = round(phrase_tts_max_duration_seconds(tts_text), 3)
        media_ledger.append(entry)

    def tts_task_expected_text(task: dict[str, Any]) -> str:
        raw_text = task.get("text_override") or task.get("tts_text") or (task.get("segment") or {}).get("text") or ""
        try:
            return clean_tts_input_text(raw_text)
        except RuntimeError:
            return clean_study_text(raw_text)

    def tts_failure_item(
        task: dict[str, Any],
        error: Any,
        attempts: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        segment = task.get("segment") if isinstance(task.get("segment"), dict) else {}
        card = task.get("card") if isinstance(task.get("card"), dict) else {}
        error_text = str(error or "")
        return {
            "segment_id": str(segment.get("id") or task.get("key") or ""),
            "card_id": str(card.get("id") or ""),
            "learning_point_id": str(card.get("learning_point_id") or segment.get("learning_point_id") or ""),
            "source_time": str(segment.get("source_time") or segment_display_source_time(segment)),
            "media_source_time": str(segment.get("media_source_time") or segment_display_source_time(segment)),
            "role": "phrase_tts" if task.get("kind") == "phrase" else "sentence_tts",
            "key": str(task.get("key") or ""),
            "expected_text": tts_task_expected_text(task),
            "answer": clean_study_text(card.get("answer_core") or card.get("phrase") or segment.get("answer_core") or ""),
            "provider": str(tts_config.get("provider") or ""),
            "model": str(tts_config.get("model") or ""),
            "voice": str(tts_config.get("voice") or ""),
            "http_error": error_text if "HTTP" in error_text or "INVALID_ARGUMENT" in error_text else "",
            "error": error_text,
            "retryable": True,
            "attempts": attempts or [],
        }

    export_segments = [
        align_segment_media_to_display_sentence(segment)
        for segment in project.get("segments", [])
        if any(card.get("enabled", True) for card in segment.get("cards", []))
    ]
    subtitle_cues, export_subtitle_path, export_subtitle_status = load_export_subtitle_cues(project)
    source_identity = export_source_identity()
    subtitle_alignment_by_segment = export_subtitle_alignment_diagnostics(
        export_segments,
        subtitle_cues,
        export_subtitle_status,
        export_subtitle_path,
    )
    subtitle_mismatch_items = (
        video_media_subtitle_mismatch_items(export_segments, subtitle_alignment_by_segment)
        if video_required and export_subtitle_status == "loaded"
        else []
    )
    if subtitle_mismatch_items:
        mismatch_count = sum(
            1
            for segment in export_segments
            if media_subtitle_alignment_blocks_export(
                subtitle_alignment_by_segment.get(str(segment.get("id") or ""), {}),
                segment,
            )
        )
        fail(
            f"视频片段与字幕原句不匹配：发现 {mismatch_count} 个片段疑似错源、切片错位或字幕重合度过低，已阻止导出。",
            error_code=worker_errors.MEDIA_SUBTITLE_ALIGNMENT_MISMATCH,
            stage="media_alignment",
            retryable=False,
            details={
                "mismatch_count": mismatch_count,
                "items": subtitle_mismatch_items,
                "subtitle_path": export_subtitle_path,
                "suggested_action": "请重新抽取或重新选择匹配的视频/字幕素材；不要导出错源或低重合度视频卡。",
            },
        )
    quality_audit = export_quality_audit(project, export_segments)
    if quality_audit["blocked_text_values"] or quality_audit["duplicate_visible_cards"] or quality_audit["pronunciation_meta_errors"]:
        fail(
            "导出前质量审计未通过："
            f"草稿/内部文本 {quality_audit['blocked_text_values']}，"
            f"重复可见卡 {quality_audit['duplicate_visible_cards']}，"
            f"PronunciationMeta 错误 {quality_audit['pronunciation_meta_errors']}。",
            error_code="EXPORT_QUALITY_GATE_FAILED",
            stage="quality_audit",
            retryable=False,
            details={
                "quality_audit": quality_audit,
                "blocked_cards": quality_audit.get("blocked_cards", []),
            },
        )
    if quality_audit["empty_required_fields"]:
        warnings.append(f"导出前审计发现 {quality_audit['empty_required_fields']} 个学习字段为空；请在质量诊断中抽查。")
    if quality_audit["answer_not_in_source"]:
        warnings.append(f"导出前审计发现 {quality_audit['answer_not_in_source']} 张非听力卡答案未能直接匹配原句；请抽查。")
    timing_ms["source_prepare"] = int((time.perf_counter() - prepare_started) * 1000)
    tts_started = time.perf_counter()
    tts_generation_enabled = False
    sentence_tts_total = 0
    sentence_tts_done = 0
    phrase_tts_text_keys: set[str] = set()
    if not is_document_project:
        for segment in export_segments:
            for card in [card for card in segment.get("cards", []) if card.get("enabled", True)]:
                phrase_text = card_phrase_tts_text(card, card_front_fields(card, repetition_mode=use_v11_repetition_front)).lower()
                if phrase_text and phrase_text not in {"key expression", "n/a"}:
                    phrase_tts_text_keys.add(phrase_text)
    phrase_tts_total = 0
    phrase_tts_done = 0
    if not is_document_project:
        managed_tts_configured = managed_tts_broker_is_configured()
        if skip_video_media:
            warnings.append("本次导出没有视频媒体，APKG 不包含视频片段和原声音频。")
        if not tts_requested:
            warnings.append("TTS 当前未启用，本次导出不会生成整句 AI 朗读和表达小喇叭。")
        elif managed_tts_configured and not managed_tts_operation_available():
            warnings.append("TTS 已启用，但当前任务没有获得 TTS Service broker 授权。")
        elif not managed_tts_configured and not tts_config["api_key"] and not is_gemini_vertex_tts_config(tts_config):
            warnings.append("TTS 已启用但缺少 API Key，本次导出不会生成 MIMO / AI 朗读音频。")
        elif not managed_tts_configured and (
            tts_config["provider"] in OPENAI_COMPATIBLE_PROVIDERS
            or tts_config["provider"] in QWEN_TTS_PROVIDERS
            or is_gemini_vertex_tts_config(tts_config)
        ) and (not compatible_base_url(tts_config) or not tts_config["model"]):
            warnings.append("TTS 已启用但缺少 Base URL 或模型名，本次导出不会生成 AI 朗读音频。")
        else:
            tts_generation_enabled = tts_requested and (
                not managed_tts_configured or managed_tts_operation_available()
            )
    if tts_generation_enabled:
        sentence_tts_total = len(export_segments)
        phrase_tts_total = len(phrase_tts_text_keys)

    def synthesize_tts_tasks(
        tasks: list[dict[str, Any]],
        *,
        stage: str,
        label: str,
        progress_start: int,
        progress_end: int,
    ) -> list[dict[str, Any]]:
        if not tasks:
            return []
        max_workers = min(export_tts_concurrency(project), len(tasks))
        completed = 0
        results: list[dict[str, Any]] = []
        emit_export_progress(stage, progress_start, f"{label} 0/{len(tasks)}，并发 {max_workers}。")

        def run_task(task: dict[str, Any]) -> dict[str, Any]:
            result = synthesize_tts(
                project,
                task["segment"],
                task["output_path"],
                text_override=task.get("text_override"),
                tts_kind=str(task.get("kind") or "sentence"),
            )
            if not result:
                raise RuntimeError("TTS 没有生成音频。请检查 TTS 配置或文本内容后重试。")
            return {**task, "result": result}

        def retry_task_serial(task: dict[str, Any], first_error: Any) -> dict[str, Any]:
            attempts: list[dict[str, Any]] = [{"mode": "initial", "ok": False, "error": str(first_error)}]
            retry_texts: list[tuple[str, str | None]] = [("original_retry", task.get("text_override"))]
            try:
                safe_text = tts_speech_safe_variant(tts_task_expected_text(task))
                retry_texts.append(("speech_safe_text", safe_text))
            except RuntimeError as err:
                attempts.append({"mode": "speech_safe_text", "ok": False, "error": str(err)})

            last_error = str(first_error)
            for mode, text_override in retry_texts:
                try:
                    discard_cached_file(task["output_path"])
                    result = synthesize_tts(
                        project,
                        task["segment"],
                        task["output_path"],
                        text_override=text_override,
                        tts_kind=str(task.get("kind") or "sentence"),
                    )
                    if not result:
                        raise RuntimeError("TTS 没有生成音频。请检查 TTS 配置或文本内容后重试。")
                    attempts.append({"mode": mode, "ok": True})
                    cleaned_task = {key: value for key, value in task.items() if key != "error"}
                    return {**cleaned_task, "result": result, "tts_recovery_attempts": attempts, "tts_recovered": True}
                except Exception as err:
                    last_error = str(err)
                    attempts.append({"mode": mode, "ok": False, "error": last_error})
            return {**task, "error": last_error, "tts_recovery_attempts": attempts}

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = []
            for task in tasks:
                future = pool.submit(run_task, task)
                future._acg_tts_task = task  # type: ignore[attr-defined]
                futures.append(future)
            for future in as_completed(futures):
                completed += 1
                percent = progress_start + int((completed / max(1, len(tasks))) * (progress_end - progress_start))
                try:
                    task_result = future.result()
                    results.append(task_result)
                except Exception as err:
                    task_result = getattr(future, "_acg_tts_task", None)
                    if isinstance(task_result, dict):
                        results.append({**task_result, "error": str(err)})
                    else:
                        warnings.append(f"{label} 失败：{err}")
                emit_export_progress(stage, percent, f"{label} {completed}/{len(tasks)}，并发 {max_workers}。")
        failed_results = [item for item in results if item.get("error")]
        if failed_results:
            results = [item for item in results if not item.get("error")]
            emit_export_progress(stage, progress_end, f"{label} 有 {len(failed_results)} 条失败，正在逐条重试。")
            for index, item in enumerate(failed_results, start=1):
                retry_result = retry_task_serial(item, item.get("error"))
                results.append(retry_result)
                percent = progress_start + int((index / max(1, len(failed_results))) * (progress_end - progress_start))
                emit_export_progress(stage, percent, f"{label} 失败项重试 {index}/{len(failed_results)}。")
        return results

    sentence_tts_tasks: list[dict[str, Any]] = []
    phrase_tts_tasks: list[dict[str, Any]] = []
    if tts_generation_enabled:
        seen_phrase_keys: set[str] = set()
        for segment in export_segments:
            segment_id = safe_filename(segment.get("id", "segment"))
            media_segment_id = f"{media_prefix}_{segment_id}"
            enabled_cards = [card for card in segment.get("cards", []) if card.get("enabled", True)]
            segment_tts_text = card_sentence_tts_text(segment, enabled_cards)
            tts_name = f"{media_segment_id}_tts_{media_text_hash(segment_tts_text)}.mp3"
            try:
                clean_tts_input_text(segment_tts_text)
                sentence_tts_text_by_segment[segment_id] = segment_tts_text
                sentence_tts_tasks.append(
                    {
                        "kind": "sentence",
                        "key": segment_id,
                        "segment": segment,
                        "file_name": tts_name,
                        "output_path": media_dir / tts_name,
                        "tts_text": segment_tts_text,
                        "text_override": segment_tts_text,
                    }
                )
            except RuntimeError:
                warnings.append(f"{segment_id} 整句 TTS 文本为空，已跳过。")
            for card in enabled_cards:
                front_fields = card_front_fields(card, repetition_mode=use_v11_repetition_front)
                phrase_text = card_phrase_tts_text(card, front_fields)
                phrase_key = phrase_text.lower()
                if not phrase_text or phrase_key in {"key expression", "n/a"} or phrase_key in seen_phrase_keys:
                    continue
                seen_phrase_keys.add(phrase_key)
                phrase_tts_name = f"{media_prefix}_phrase_{media_text_hash(phrase_text)}.mp3"
                phrase_tts_tasks.append(
                    {
                        "kind": "phrase",
                        "key": phrase_key,
                        "segment": segment,
                        "card": card,
                        "file_name": phrase_tts_name,
                        "output_path": media_dir / phrase_tts_name,
                        "tts_text": phrase_text,
                        "text_override": phrase_text,
                    }
                )
        sentence_tts_total = len(sentence_tts_tasks)
        phrase_tts_total = len(phrase_tts_tasks)
        for item in synthesize_tts_tasks(
            [*sentence_tts_tasks, *phrase_tts_tasks],
            stage="tts",
            label="TTS",
            progress_start=12,
            progress_end=40,
        ):
            if item.get("error"):
                if "TTS 语义核验失败" in str(item.get("error") or ""):
                    fail(
                        str(item.get("error")),
                        error_code="TTS_SEMANTIC_MISMATCH",
                        stage="tts",
                        retryable=True,
                    )
                tts_failure_items.append(
                    tts_failure_item(
                        item,
                        item.get("error"),
                        item.get("tts_recovery_attempts") if isinstance(item.get("tts_recovery_attempts"), list) else [],
                    )
                )
                if item.get("kind") == "phrase":
                    warnings.append(f"{item.get('key')} 表达 TTS 失败：{item.get('error')}")
                else:
                    warnings.append(f"{item.get('key')} TTS 失败：{item.get('error')}")
                continue
            tts_result = item.get("result")
            if not tts_result:
                continue
            cache_hit = bool(tts_result.get("cache_hit")) if isinstance(tts_result, dict) else False
            semantic_result = (
                tts_result.get("semantic")
                if isinstance(tts_result, dict) and isinstance(tts_result.get("semantic"), dict)
                else {}
            )
            if cache_hit:
                tts_cache_hit_count += 1
            file_name = str(item.get("file_name") or "")
            media_files.append(str(item["output_path"]))
            if item.get("kind") == "phrase":
                phrase_key = str(item.get("key") or "")
                phrase_tts_by_phrase[phrase_key] = file_name
                phrase_tts_cache_hit_by_phrase[phrase_key] = cache_hit
                phrase_tts_semantic_by_phrase[phrase_key] = semantic_result
            else:
                segment_key = str(item.get("key") or "")
                tts_by_segment[segment_key] = file_name
                tts_semantic_by_segment[segment_key] = semantic_result
                ledger_add(
                    file_name,
                    role="sentence_tts",
                    segment=item["segment"],
                    field="TtsAudio",
                    tts_text=str(item.get("tts_text") or ""),
                    cache_hit=cache_hit,
                    semantic=semantic_result,
                )
        sentence_tts_done = len(tts_by_segment)
        phrase_tts_done = len(phrase_tts_by_phrase)

    timing_ms["tts"] = int((time.perf_counter() - tts_started) * 1000)
    media_started = time.perf_counter()
    for index, segment in enumerate(export_segments):
        enabled_cards = [card for card in segment.get("cards", []) if card.get("enabled", True)]
        if not enabled_cards:
            continue

        segment_id = safe_filename(segment.get("id", "segment"))
        media_segment_id = f"{media_prefix}_{segment_id}"
        video_webm_name = "" if skip_video_media or not export_webm_media else f"{media_segment_id}.webm"
        video_mp4_name = "" if skip_video_media else f"{media_segment_id}.mp4"
        poster_name = "" if skip_video_media else f"{media_segment_id}.jpg"
        audio_name = "" if skip_video_media else f"{media_segment_id}.mp3"
        video_webm_out = media_dir / video_webm_name
        video_mp4_out = media_dir / video_mp4_name
        poster_out = media_dir / poster_name
        audio_out = media_dir / audio_name
        segment_percent = 15 + int((index / max(1, len(export_segments))) * 68)

        if skip_video_media:
            emit_export_progress(
                "notes",
                segment_percent,
                f"正在整理无视频卡 {index + 1}/{len(export_segments)}：{segment.get('source_time', segment_id)}",
            )
            cut_segments.add(segment_id)
        elif segment_id not in cut_segments:
            clip_start = float(segment.get("media_start", segment.get("start", 0)) or 0)
            clip_end = float(segment.get("media_end", segment.get("end", 0)) or 0)
            if clip_end <= clip_start:
                clip_start = float(segment.get("start", 0) or 0)
                clip_end = float(segment.get("end", clip_start + 0.5) or clip_start + 0.5)
            start = str(max(0.0, clip_start))
            duration = str(max(0.5, clip_end - clip_start))
            media_clip_key = (video_source_fingerprint, start, duration, bool(export_webm_media))
            reused_media_names = media_by_clip_key.get(media_clip_key)
            if reused_media_names:
                emit_export_progress(
                    "media",
                    segment_percent,
                    f"媒体复用 {index + 1}/{len(export_segments)}：{segment.get('source_time', segment_id)}",
                )
                video_webm_name = reused_media_names.get("video_webm_name", "") if export_webm_media else ""
                video_mp4_name = reused_media_names.get("video_mp4_name", "")
                poster_name = reused_media_names.get("poster_name", "")
                audio_name = reused_media_names.get("audio_name", "")
                media_reused_segment_count += 1
                if video_webm_name:
                    ledger_add(video_webm_name, role="video", segment=segment, field="Video")
                if video_mp4_name:
                    ledger_add(video_mp4_name, role="video", segment=segment, field="Video")
                if audio_name:
                    ledger_add(audio_name, role="original_audio", segment=segment, field="Audio")
                if poster_name:
                    ledger_add(poster_name, role="poster", segment=segment, field="Video")
            else:
                media_commands = []
                if export_webm_media:
                    media_commands.append(
                        (
                            video_webm_out,
                            "video_webm",
                            "webm",
                            "vp9-540p-crf38-opus64",
                            [
                                "-ss",
                                start,
                                "-t",
                                duration,
                                "-i",
                                str(video_path),
                                "-map",
                                "0:v:0?",
                                "-map",
                                "0:a:0?",
                                "-vf",
                                "scale=-2:540",
                                "-c:v",
                                "libvpx-vp9",
                                "-b:v",
                                "0",
                                "-crf",
                                "38",
                                "-row-mt",
                                "1",
                                "-deadline",
                                "good",
                                "-cpu-used",
                                "4",
                                "-pix_fmt",
                                "yuv420p",
                                "-ac",
                                "2",
                                "-c:a",
                                "libopus",
                                "-b:a",
                                "64k",
                                str(video_webm_out),
                            ],
                        )
                    )
                media_commands.extend(
                    [
                        (
                            video_mp4_out,
                            "video_mp4",
                            "mp4",
                            "x264-540p-crf28-aac80",
                            [
                                "-ss",
                                start,
                                "-t",
                                duration,
                                "-i",
                                str(video_path),
                                "-map",
                                "0:v:0?",
                                "-map",
                                "0:a:0?",
                                "-vf",
                                "scale=-2:540",
                                "-c:v",
                                "libx264",
                                "-preset",
                                "veryfast",
                                "-profile:v",
                                "baseline",
                                "-level",
                                "3.1",
                                "-pix_fmt",
                                "yuv420p",
                                "-crf",
                                "28",
                                "-ac",
                                "2",
                                "-c:a",
                                "aac",
                                "-b:a",
                                "80k",
                                "-movflags",
                                "+faststart",
                                str(video_mp4_out),
                            ],
                        ),
                        (
                            audio_out,
                            "original_audio",
                            "mp3",
                            "mp3-q5-stereo",
                            [
                                "-ss",
                                start,
                                "-t",
                                duration,
                                "-i",
                                str(video_path),
                                "-vn",
                                "-ac",
                                "2",
                                "-acodec",
                                "libmp3lame",
                                "-q:a",
                                "5",
                                str(audio_out),
                            ],
                        ),
                    ]
                )
                media_command_cache_paths = [
                    media_clip_cache_path(video_source_fingerprint, start, duration, role, extension, profile)[0]
                    for _output_path, role, extension, profile, _command in media_commands
                ]
                media_cache_reads_enabled = media_cache_read_enabled(project)
                media_action = (
                    "媒体缓存"
                    if media_cache_reads_enabled
                    and media_command_cache_paths
                    and all(cached_media_file_valid(path) for path in media_command_cache_paths)
                    else "媒体切片"
                )
                emit_export_progress(
                    "media",
                    segment_percent,
                    f"{media_action} {index + 1}/{len(export_segments)}：{segment.get('source_time', segment_id)}",
                )
                media_errors = []
                media_results: list[dict[str, Any]] = []

                def run_media_command(command_spec: tuple[Path, str, str, str, list[str]]) -> dict[str, Any]:
                    output_path, role, extension, profile, command = command_spec
                    cache_path, _ = media_clip_cache_path(
                        video_source_fingerprint,
                        start,
                        duration,
                        role,
                        extension,
                        profile,
                    )
                    if media_cache_reads_enabled and copy_cached_file(cache_path, output_path):
                        return {"output_path": output_path, "role": role, "cache_hit": True, "error": ""}
                    error = try_run_ffmpeg(command)
                    if error:
                        return {"output_path": output_path, "role": role, "cache_hit": False, "error": error}
                    store_cached_file(output_path, cache_path)
                    return {"output_path": output_path, "role": role, "cache_hit": False, "error": ""}

                media_workers = min(export_media_concurrency(project), len(media_commands))
                if media_workers <= 1:
                    media_results = [run_media_command(command_spec) for command_spec in media_commands]
                else:
                    with ThreadPoolExecutor(max_workers=media_workers) as pool:
                        futures = [pool.submit(run_media_command, command_spec) for command_spec in media_commands]
                        media_results = [future.result() for future in futures]
                for result in media_results:
                    if result.get("cache_hit"):
                        media_cache_hit_count += 1
                    elif not result.get("error"):
                        media_cache_miss_count += 1
                    if result.get("error"):
                        media_errors.append(str(result.get("error")))
                if media_errors:
                    for output_path, *_ in media_commands:
                        output_path.unlink(missing_ok=True)
                    if video_required:
                        fail(
                            f"{segment_id} 视频/原声切片失败，已停止导出，避免生成缺视频的视频卡。请检查 FFmpeg、视频路径或重新生成素材后再导出：{media_errors[0]}",
                            error_code=worker_errors.FFMPEG_SLICE_FAILED,
                            stage="media",
                            retryable=True,
                            fallbacks=[],
                        )
                    video_webm_name = ""
                    video_mp4_name = ""
                    poster_name = ""
                    audio_name = ""
                    warnings.append(f"{segment_id} 视频/原声切片失败，已保留文字卡：{media_errors[0]}")
                else:
                    poster_at = str(float(start) + min(0.75, max(0.1, float(duration) / 2)))
                    poster_cache_path, _ = media_clip_cache_path(
                        video_source_fingerprint,
                        poster_at,
                        "poster",
                        "poster",
                        "jpg",
                        "jpg-q3-scale960",
                    )
                    poster_error = ""
                    if media_cache_reads_enabled and copy_cached_file(poster_cache_path, poster_out):
                        media_cache_hit_count += 1
                    else:
                        poster_error = try_run_ffmpeg(
                            [
                                "-ss",
                                poster_at,
                                "-i",
                                str(video_path),
                                "-frames:v",
                                "1",
                                "-q:v",
                                "3",
                                "-vf",
                                "scale='min(960,iw)':-2",
                                str(poster_out),
                            ]
                        )
                        if not poster_error:
                            store_cached_file(poster_out, poster_cache_path)
                            media_cache_miss_count += 1
                    if poster_error:
                        poster_name = ""
                        poster_out.unlink(missing_ok=True)
                        warnings.append(f"{segment_id} 视频封面生成失败：{poster_error}")
                    if video_webm_name and video_webm_out.exists():
                        media_files.append(str(video_webm_out))
                        ledger_add(video_webm_name, role="video", segment=segment, field="Video")
                        video_file_count += 1
                    if video_mp4_name and video_mp4_out.exists():
                        media_files.append(str(video_mp4_out))
                        ledger_add(video_mp4_name, role="video", segment=segment, field="Video")
                        video_file_count += 1
                    if audio_name and audio_out.exists():
                        media_files.append(str(audio_out))
                        ledger_add(audio_name, role="original_audio", segment=segment, field="Audio")
                        original_audio_count += 1
                    if poster_name and poster_out.exists():
                        media_files.append(str(poster_out))
                        ledger_add(poster_name, role="poster", segment=segment, field="Video")
                    if video_mp4_name or video_webm_name or audio_name or poster_name:
                        media_by_clip_key[media_clip_key] = {
                            "video_webm_name": video_webm_name,
                            "video_mp4_name": video_mp4_name,
                            "poster_name": poster_name,
                            "audio_name": audio_name,
                        }
                    video_segment_count += 1
            cut_segments.add(segment_id)

        for card in enabled_cards:
            front_fields = card_front_fields(card, repetition_mode=use_v11_repetition_front)
            front_fields = front_fields_for_export_media(
                front_fields,
                repetition_mode=use_v11_repetition_front,
                has_original_audio=bool(audio_name and audio_out.exists()),
                has_tts_audio=bool(tts_by_segment.get(segment_id, "")),
            )
            template_labels = card_template_labels(card, deck_kind_code)
            export_card_id = f"{project_card_prefix}_{card.get('id', '')}"
            phrase_text = card_phrase_tts_text(card, front_fields)
            phrase_tts_name = ""
            phrase_key = phrase_text.lower()
            if tts_generation_enabled and phrase_text and phrase_key not in {"key expression", "n/a"}:
                expected_phrase_tts_keys.add(phrase_key)
                if phrase_key in phrase_tts_by_phrase:
                    phrase_tts_name = phrase_tts_by_phrase[phrase_key]
            if phrase_tts_name:
                ledger_add(
                    phrase_tts_name,
                    role="phrase_tts",
                    segment=segment,
                    card=card,
                    field="PhraseTtsAudio",
                    tts_text=phrase_text,
                    cache_hit=phrase_tts_cache_hit_by_phrase.get(phrase_key, False),
                    semantic=phrase_tts_semantic_by_phrase.get(phrase_key, {}),
                )
            sentence_tts_name = tts_by_segment.get(segment_id, "")
            sentence_tts_text = sentence_tts_text_by_segment.get(segment_id) or card_sentence_tts_text(segment, enabled_cards)
            note_source_sentence = clean_study_text(sentence_tts_text) or clean_study_text(card.get("english", ""))
            sentence_semantic = tts_semantic_by_segment.get(segment_id, {})
            phrase_semantic = phrase_tts_semantic_by_phrase.get(phrase_key, {}) if phrase_tts_name else {}
            subtitle_diagnostic = subtitle_alignment_by_segment.get(str(segment.get("id") or ""), {})
            target_deck = default_deck
            if is_batch_export:
                batch_item_id = str(segment.get("batch_item_id") or card.get("batch_item_id") or "").strip()
                target_deck = batch_decks_by_item_id.get(batch_item_id) if batch_item_id else None
                if target_deck is None:
                    target_deck = fallback_batch_deck
                    if not fallback_batch_deck_used:
                        decks_for_package.append(fallback_batch_deck)
                        deck_names_for_result.append(fallback_batch_deck.name)
                        fallback_batch_deck_used = True
                elif batch_item_id:
                    exported_batch_item_ids.add(batch_item_id)
            note_tags = build_anki_note_tags(
                anki_tag=anki_tag,
                language=project.get("language") or "English",
                level=project.get("level") or "B1",
                template_id=template_id,
                card_type=card.get("type") or "card",
                layout=template_labels["card_layout"],
            )
            card_media_ledger.append(
                {
                    "card_id": export_card_id,
                    "source_card_id": str(card.get("id") or ""),
                    "learning_point_id": str(card.get("learning_point_id") or segment.get("learning_point_id") or ""),
                    "segment_id": segment_id,
                    "deck_name": str(target_deck.name),
                    "note_tags": note_tags,
                    "source_time": str(segment.get("source_time") or segment_display_source_time(segment)),
                    "media_start": segment.get("media_start"),
                    "media_end": segment.get("media_end"),
                    "media_source_time": str(segment.get("media_source_time") or segment_display_source_time(segment)),
                    "source_cue_ids": segment.get("source_cue_ids") or [],
                    "source_cue_count": segment.get("source_cue_count"),
                    "source_cue_start": segment.get("source_cue_start"),
                    "source_cue_end": segment.get("source_cue_end"),
                    "source_cue_time": str(segment.get("source_cue_time") or ""),
                    "source_cue_texts": segment.get("source_cue_texts") or [],
                    "source_merge_reason": str(segment.get("source_merge_reason") or ""),
                    "source_sentence_quality_flags": segment.get("source_sentence_quality_flags") or [],
                    "source_sentence_quality_status": str(segment.get("source_sentence_quality_status") or ""),
                    "media_alignment_status": str(segment.get("media_alignment_status") or ""),
                    "media_alignment_text": clean_study_text(segment.get("media_alignment_text") or segment.get("text") or ""),
                    "media_alignment_source_text": clean_study_text(
                        segment.get("media_alignment_source_text")
                        or segment.get("full_source_sentence")
                        or segment.get("source_sentence")
                        or segment.get("text")
                        or ""
                    ),
                    **subtitle_diagnostic,
                    "answer": clean_study_text(front_fields.get("answer") or ""),
                    "card_display_sentence": note_source_sentence,
                    "sentence_tts_text": clean_study_text(sentence_tts_text),
                    "phrase_tts_text": clean_study_text(phrase_text),
                    "video_webm": video_webm_name,
                    "video_mp4": video_mp4_name,
                    "poster": poster_name,
                    "original_audio": audio_name,
                    "sentence_tts_audio": sentence_tts_name,
                    "phrase_tts_audio": phrase_tts_name,
                    "sentence_tts_semantic_verification": str(sentence_semantic.get("semantic_verification") or ""),
                    "sentence_tts_asr_transcript": str(sentence_semantic.get("asr_transcript") or ""),
                    "phrase_tts_semantic_verification": str(phrase_semantic.get("semantic_verification") or ""),
                    "phrase_tts_asr_transcript": str(phrase_semantic.get("asr_transcript") or ""),
                    "template_label": template_labels["card_layout"],
                    "template_version": template_version,
                    **source_identity,
                }
            )
            why_field = card.get("why", "")
            if is_ciba_template:
                meaning_field = ciba_contextual_meaning_text(card)
                definition_field = ciba_language_action_text(card)
                collocations_field = ciba_transfer_text(card)
                context_field = ciba_source_context_text(card)
                teacher_note_field = ciba_boundary_text(card)
                chinese_feel_field = v11_answer_note_text(card)
                why_field = ciba_reason_text(card)
            else:
                meaning_field = export_meaning_text(card, use_v11_repetition_front)
                definition_field = export_definition_text(card, use_v11_repetition_front)
                collocations_field = v11_self_sentence_text(card) if use_v11_repetition_front else card.get("collocations", "")
                context_field = document_reading_context_text(card) if deck_kind_code == "document_reading" else export_context_text(card, use_v11_repetition_front)
                teacher_note_field = export_teacher_note_text(card, use_v11_repetition_front)
                chinese_feel_field = v11_answer_note_text(card) if use_v11_repetition_front else card.get("chinese_feel", "")
            presentation_values: list[str] = []
            if use_v11_repetition_front:
                presentation_card = {**segment, **card}
                presentation = build_card_presentation(
                    presentation_card,
                    source_text=note_source_sentence,
                    meaning_text=meaning_field,
                    answer_note_text=chinese_feel_field,
                    pronunciation_note_text=card.get("pronunciation_note", ""),
                    source_translation_text=context_field,
                    usage_text=definition_field,
                    misuse_text=teacher_note_field,
                    example_values=[collocations_field],
                )
                presentation_values = [
                    presentation.source_html,
                    presentation.meaning_html,
                    presentation.answer_note_html,
                    presentation.pronunciation_note_html,
                    presentation.source_translation_html,
                    presentation.usage_html,
                    presentation.misuse_html,
                    presentation.example_items_html,
                ]
                if presentation.warnings:
                    warning_item = {
                        "card_id": export_card_id,
                        "learning_point_id": str(card.get("learning_point_id") or segment.get("learning_point_id") or ""),
                        "warnings": list(presentation.warnings),
                    }
                    presentation_warnings.append(warning_item)
                    card_media_ledger[-1]["presentation_warnings"] = list(presentation.warnings)
                why_field = card.get("why", "")
            pronunciation_meta = ensure_card_pronunciation_meta(card, project.get("language", "en"))
            note_fields = [
                    anki_text(export_card_id),
                    anki_study_text(card.get("type_label", card.get("type", ""))),
                    anki_video_html(video_webm_name, video_mp4_name, poster_name, controls=not use_v11_repetition_front, muted=False),
                    anki_audio_html(audio_name, controls=not use_v11_repetition_front, role="original"),
                    anki_audio_html(sentence_tts_name, controls=not use_v11_repetition_front, role="slow"),
                    anki_audio_html(phrase_tts_name, controls=not use_v11_repetition_front, role="phrase"),
                    "1" if card.get("type") == "listening" else "",
                    anki_study_text(front_fields["front_prompt"]),
                    anki_study_text(front_fields["front_content"]),
                    anki_study_text(front_fields["answer"]),
                    anki_study_text(card.get("phonetic_ipa", "")),
                    anki_study_text(card.get("spoken_ipa", "")),
                    anki_study_text(card.get("source_spoken_ipa", "")),
                    anki_study_text(card.get("pronunciation_note", "")),
                    anki_text(card.get("pronunciation_confidence", "")),
                    anki_study_text(card.get("pronunciation_status", "")),
                    anki_study_text(card.get("source_pronunciation_status", "")),
                    anki_text(json.dumps(pronunciation_meta, ensure_ascii=False, separators=(",", ":"))),
                    anki_text(spoken_label_for_meta(pronunciation_meta)),
                    anki_text(standard_hint_for_meta(pronunciation_meta, project.get("language", "en"))),
                    anki_study_text(note_source_sentence),
                    *presentation_values,
                    anki_text(meaning_field),
                    anki_study_text(card.get("phrase", "")),
                    anki_study_text(definition_field),
                    anki_study_text(collocations_field),
                    anki_study_text(context_field),
                    anki_study_text(card.get("example", "")),
                    anki_study_text(chinese_feel_field),
                    anki_study_text(why_field),
                    anki_study_text(card.get("difficulty", "")),
                    anki_text(segment_display_source_time(segment)),
                    anki_study_text(teacher_note_field),
                    anki_text(learning_action_for_card(card)),
                    anki_study_text(ciba_conceptual_action_text(card) if is_ciba_template else card.get("conceptual_action", "")),
                    anki_study_text(ciba_chinese_learner_trap_text(card) if is_ciba_template else card.get("chinese_learner_trap", "")),
                    anki_study_text(export_cloze_text(card, deck_kind_code)),
                    anki_text(template_labels["card_layout"]),
                    anki_text("repetition" if use_v11_repetition_front else template_labels["card_layout"]),
                    anki_text(template_labels["front_kicker"]),
                    anki_text(template_labels["source_label"]),
                    anki_text(template_labels["understand_label"]),
                    anki_text(template_labels["use_label"]),
            ]
            card_media_ledger[-1]["note_content_sha256"] = note_content_sha256(model_field_names, note_fields)
            note = genanki.Note(
                model=model,
                fields=note_fields,
                tags=note_tags,
                guid=note_guid_for_model(note_model_contract.note_model_id, note_fields),
            )
            target_deck.add_note(note)
            exported_cards += 1

    timing_ms["media"] = int((time.perf_counter() - media_started) * 1000)
    if exported_cards == 0:
        fail("没有可导出的卡片。请在预览页至少启用一张卡。")
    if video_required and not tts_generation_enabled:
        if not tts_requested:
            tts_config_error = "TTS 当前未启用。"
        elif not tts_config["api_key"] and not is_gemini_vertex_tts_config(tts_config):
            tts_config_error = "TTS 已启用但缺少 API Key。"
        elif (
            tts_config["provider"] in OPENAI_COMPATIBLE_PROVIDERS
            or tts_config["provider"] in QWEN_TTS_PROVIDERS
            or is_gemini_vertex_tts_config(tts_config)
        ) and (not compatible_base_url(tts_config) or not tts_config["model"]):
            tts_config_error = "TTS 已启用但缺少 Base URL 或模型名。"
        else:
            tts_config_error = "TTS 配置未通过导出检查。"
        expected_sentence_tts = len(export_segments)
        expected_phrase_tts = len(phrase_tts_text_keys)
        fail(
            "TTS 生成失败：当前视频/字幕语言卡必须包含整句 TTS 和表达 TTS，"
            f"但 {tts_config_error} 因此没有生成 APKG。请先测试 TTS 配置后再导出。",
            error_code="MISSING_TTS_MEDIA",
            stage="tts",
            retryable=True,
            fallbacks=["test_tts_config", "return_to_selection"],
            details={
                "tts_failure_count": expected_sentence_tts + expected_phrase_tts,
                "tts_failure_items": [],
                "tts_failure_items_truncated": 0,
                "sentence_tts_requested": expected_sentence_tts,
                "sentence_tts_generated": 0,
                "phrase_tts_requested": expected_phrase_tts,
                "phrase_tts_generated": 0,
                "provider": str(tts_config.get("provider") or ""),
                "model": str(tts_config.get("model") or ""),
                "voice": str(tts_config.get("voice") or ""),
                "cache_root": str(persistent_cache_root()),
                "tts_media_errors": [tts_config_error],
            },
        )
    if tts_generation_enabled and not is_document_project:
        expected_sentence_tts = sentence_tts_total
        tts_media_errors: list[str] = []
        if expected_sentence_tts and not tts_by_segment:
            tts_media_errors.append("整句 AI 朗读生成 0 条")
        elif len(tts_by_segment) < expected_sentence_tts:
            tts_media_errors.append(f"整句 AI 朗读只生成 {len(tts_by_segment)}/{expected_sentence_tts} 条")
        expected_phrase_tts = phrase_tts_total
        if expected_phrase_tts and not phrase_tts_by_phrase:
            tts_media_errors.append("表达小喇叭生成 0 条")
        elif len(phrase_tts_by_phrase) < expected_phrase_tts:
            tts_media_errors.append(f"表达小喇叭只生成 {len(phrase_tts_by_phrase)}/{expected_phrase_tts} 条")
        if tts_media_errors:
            tts_failure_details = [
                warning
                for warning in warnings
                if "TTS 失败" in warning or "表达 TTS 失败" in warning
            ][:2]
            detail_suffix = f" 具体失败：{'；'.join(tts_failure_details)}。" if tts_failure_details else ""
            tts_failure_count = len(tts_failure_items)
            fail(
                f"TTS 生成失败：{tts_failure_count or '部分'} 条 TTS 未完成，因此没有生成 APKG。"
                "已生成的卡片仍保留，可重试失败音频。"
                " 详情："
                + "；".join(tts_media_errors)
                + "。"
                + detail_suffix
                + "为避免生成缺 TTS 的视频卡，请先测试 TTS 配置后再导出。",
                error_code="MISSING_TTS_MEDIA",
                stage="tts",
                retryable=True,
                fallbacks=["retry_failed_tts_and_export", "test_tts_config", "return_to_selection"],
                details={
                    "tts_failure_count": tts_failure_count,
                    "tts_failure_items": tts_failure_items[:50],
                    "tts_failure_items_truncated": max(0, len(tts_failure_items) - 50),
                    "sentence_tts_requested": expected_sentence_tts,
                    "sentence_tts_generated": len(tts_by_segment),
                    "phrase_tts_requested": expected_phrase_tts,
                    "phrase_tts_generated": len(phrase_tts_by_phrase),
                    "provider": str(tts_config.get("provider") or ""),
                    "model": str(tts_config.get("model") or ""),
                    "voice": str(tts_config.get("voice") or ""),
                    "cache_root": str(persistent_cache_root()),
                    "tts_media_errors": tts_media_errors,
                },
            )

    package_started = time.perf_counter()
    emit_export_progress("package", 92, "正在写入 APKG。")
    media_files = list(dict.fromkeys(media_files))
    exported_media_manifest = media_manifest(media_files, media_ledger)
    tts_manual_items = tts_manual_review_items(exported_media_manifest)
    tts_semantic_failures = tts_semantic_failure_items(exported_media_manifest)
    tts_semantic_summary = tts_semantic_verification_summary(tts_manual_items, exported_media_manifest)
    audio_audit_items = build_audio_audit_items(
        card_media_ledger,
        exported_media_manifest,
        deck_name=deck_name,
        model_name=note_model_contract.model_name,
        deck_kind=deck_kind_code,
    )
    audio_audit_info = audio_audit_summary(
        audio_audit_items,
        deck_kind=deck_kind_code,
        expected_items=exported_cards if deck_kind_code in {"video_language", "subtitle_language"} else 0,
    )
    audio_audit_path, audio_audit_markdown_path = write_audio_audit_files(export_root, audio_audit_items, audio_audit_info)
    if tts_semantic_failures and tts_semantic_requires_export_pass(project, deck_kind_code):
        first_failure = tts_semantic_failures[0]
        fail(
            "TTS 语义核验失败，已阻止导出，避免错音频进入 Anki："
            f"{first_failure.get('file')} 期望 {first_failure.get('tts_text')!r}，"
            f"ASR 听到 {first_failure.get('asr_transcript')!r}。",
            error_code="TTS_SEMANTIC_MISMATCH",
            stage="tts",
            retryable=True,
            details={
                **audio_audit_failure_details(audio_audit_items, tts_semantic_failures),
                "audio_audit_path": str(audio_audit_path),
                "audio_audit_markdown_path": str(audio_audit_markdown_path),
            },
        )
    if tts_manual_items and tts_semantic_requires_export_pass(project, deck_kind_code):
        first_manual = tts_manual_items[0]
        manual_reasons = [str(reason) for reason in first_manual.get("semantic_review_reasons") or []]
        fail(
            "TTS 语义未能自动证明，已阻止导出，避免未核验音频进入 Anki："
            f"{first_manual.get('file')} 期望 {first_manual.get('tts_text')!r}，"
            f"原因 {', '.join(manual_reasons) or 'asr_unavailable'}。",
            error_code="TTS_SEMANTIC_UNVERIFIED",
            stage="tts",
            retryable=True,
            details={
                **audio_audit_failure_details(audio_audit_items, tts_manual_items),
                "audio_audit_path": str(audio_audit_path),
                "audio_audit_markdown_path": str(audio_audit_markdown_path),
            },
        )
    media_bytes = 0
    for media_file in media_files:
        try:
            media_bytes += Path(media_file).stat().st_size
        except OSError:
            warnings.append(f"媒体文件统计失败：{Path(media_file).name}")
    package_decks: Any = decks_for_package[0] if len(decks_for_package) == 1 else decks_for_package
    package = genanki.Package(package_decks)
    package.media_files = media_files
    apkg_path = canonical_apkg_path or export_root / f"{safe_filename(project.get('title', 'anki-card'))}.apkg"
    partial_apkg_path = apkg_path.with_name(
        f".{apkg_path.name}.{os.getpid()}.{time.time_ns()}.partial"
    )
    try:
        package.write_to_file(str(partial_apkg_path))
    except Exception:
        partial_apkg_path.unlink(missing_ok=True)
        raise
    apkg_stat = partial_apkg_path.stat()
    apkg_sha256 = file_sha256(partial_apkg_path)
    timing_ms["apkg_packaging"] = int((time.perf_counter() - package_started) * 1000)

    tts_cache_total = sentence_tts_total + phrase_tts_total
    tts_cache_miss_count = max(0, tts_cache_total - tts_cache_hit_count)
    media_cache_total = media_cache_hit_count + media_cache_miss_count
    export_result = {
        "schema_version": 2,
        "apkg_path": str(partial_apkg_path),
        "apkg_sha256": apkg_sha256,
        "apkg_size_bytes": apkg_stat.st_size,
        "apkg_mtime_ms": int(apkg_stat.st_mtime * 1000),
        "media_dir": str(media_dir),
        "deck_name": deck_name,
        "deck_names": deck_names_for_result,
        "anki_manual_import_hint": f"导入后请在 Anki 牌组列表打开「{deck_name}」。",
        "anki_verify_after_manual_import_supported": True,
        "deck_kind": deck_kind_code,
        "template_family": template_family,
        "template_schema": template_version,
        "template_version": template_version,
        "template_name": template_label,
        "note_model_id": note_model_contract.note_model_id,
        "model_name": note_model_contract.model_name,
        "compatibility_contract_version": COMPATIBILITY_CONTRACT_VERSION,
        "note_model_contract_digest": note_model_contract.contract_digest,
        "anki_tag": anki_tag,
        "media_prefix": media_prefix,
        "source_identity": source_identity,
        "media_manifest": exported_media_manifest,
        "media_ledger": media_ledger,
        "card_media_ledger": card_media_ledger,
        "note_content_fingerprint": {
            "schema_version": NOTE_CONTENT_FINGERPRINT_SCHEMA_VERSION,
            "algorithm": NOTE_CONTENT_FINGERPRINT_ALGORITHM,
            "serialization": NOTE_CONTENT_FINGERPRINT_SERIALIZATION,
            "field_names": model_field_names,
            "card_count": len(card_media_ledger),
        },
        "presentation_warnings": presentation_warnings,
        "tts_manual_review_items": tts_manual_items,
        "tts_semantic_failures": tts_semantic_failures,
        "tts_semantic_verification": tts_semantic_summary,
        "audio_audit_path": str(audio_audit_path),
        "audio_audit_markdown_path": str(audio_audit_markdown_path),
        "audio_audit_summary": audio_audit_info,
        "audio_audit_items": audio_audit_items,
        "cards": exported_cards,
        "segments": len(cut_segments),
        "media_summary": {
            "video_segments": video_segment_count,
            "video_files": video_file_count,
            "original_audio_files": original_audio_count,
            "sentence_tts_files": len(tts_by_segment),
            "phrase_tts_files": len(phrase_tts_by_phrase),
            "sentence_tts_requested": sentence_tts_total,
            "phrase_tts_requested": phrase_tts_total,
            "tts_concurrency": export_tts_concurrency(project) if tts_generation_enabled else 0,
            "media_concurrency": export_media_concurrency(project) if not skip_video_media else 0,
            "tts_cache_hits": tts_cache_hit_count,
            "tts_cache_misses": tts_cache_miss_count,
            "tts_cache_total": tts_cache_total,
            "media_cache_hits": media_cache_hit_count,
            "media_cache_misses": media_cache_miss_count,
            "media_cache_total": media_cache_total,
            "media_reused_segments": media_reused_segment_count,
            "media_files": len(media_files),
            "media_bytes": media_bytes,
            "media_mb": round(media_bytes / (1024 * 1024), 1),
            "card_media_ledger_items": len(card_media_ledger),
            "presentation_warning_cards": len(presentation_warnings),
            "subtitle_diagnostic_status": export_subtitle_status,
            "subtitle_path": export_subtitle_path,
            "media_subtitle_alignment": audio_audit_info.get("media_subtitle_alignment", {}),
            "tts_manual_review_items": len(tts_manual_items),
            "tts_semantic_passed_items": tts_semantic_summary["passed"],
            "tts_semantic_failed_items": tts_semantic_summary["failed"],
            "tts_high_risk_manual_review_items": tts_semantic_summary["high_risk_items"],
        },
        "timing_ms": timing_ms,
        "batch_summary": {
            "enabled": is_batch_export,
            "items": len(batch_deck_specs) if is_batch_export else 0,
            "exported_items": len(exported_batch_item_ids) if is_batch_export else 0,
            "deck_names": deck_names_for_result if is_batch_export else [],
        },
        "quality_audit": quality_audit,
        "warnings": warnings,
    }
    validation_started = time.perf_counter()
    try:
        package_report = apkg_package_contract_module.validate_apkg_package_contract(
            partial_apkg_path,
            export_result,
        )
    except Exception:
        partial_apkg_path.unlink(missing_ok=True)
        fail(
            "最终 APKG 合同检查器无法完成核验，因此没有交付文件。",
            error_code="APKG_PACKAGE_CONTRACT_UNREADABLE",
            stage="package",
            retryable=True,
            fallbacks=["retry_export"],
        )
    timing_ms["apkg_contract_validation"] = int(
        (time.perf_counter() - validation_started) * 1000
    )
    if not isinstance(package_report, dict) or not package_report.get("ok"):
        partial_apkg_path.unlink(missing_ok=True)
        issue_codes = sorted(
            {
                str(item.get("code") or "APKG_PACKAGE_CONTRACT_INVALID")
                for item in (
                    package_report.get("issues", [])
                    if isinstance(package_report, dict)
                    else []
                )
                if isinstance(item, dict)
            }
        )
        fail(
            "最终 APKG 未通过完整合同核验，因此没有交付文件。",
            error_code="APKG_PACKAGE_CONTRACT_INVALID",
            stage="package",
            retryable=True,
            fallbacks=["retry_export", "review_cards"],
            details={"issue_codes": issue_codes or ["APKG_PACKAGE_CONTRACT_INVALID"]},
        )
    try:
        publish_file_no_replace(partial_apkg_path, apkg_path)
        final_stat = apkg_path.stat()
        final_sha256 = file_sha256(apkg_path)
    except OSError:
        partial_apkg_path.unlink(missing_ok=True)
        if apkg_path.exists():
            fail(
                "目标 APKG 在导出期间已被创建；为避免覆盖现有文件，本次没有交付。",
                error_code="APKG_FINAL_PATH_COLLISION",
                stage="package",
                retryable=True,
                fallbacks=["retry_export", "choose_another_output"],
            )
        raise
    if final_stat.st_size != apkg_stat.st_size or final_sha256 != apkg_sha256:
        apkg_path.unlink(missing_ok=True)
        fail(
            "APKG 在安全交付时发生变化，因此没有交付文件。",
            error_code="APKG_FINALIZATION_INTEGRITY_MISMATCH",
            stage="package",
            retryable=True,
            fallbacks=["retry_export"],
        )
    export_result["apkg_path"] = str(apkg_path)
    export_result["apkg_sha256"] = final_sha256
    export_result["apkg_size_bytes"] = final_stat.st_size
    export_result["apkg_mtime_ms"] = int(final_stat.st_mtime * 1000)
    timing_ms["total"] = int((time.perf_counter() - timing_started) * 1000)
    add_export_timing_aliases(timing_ms)
    emit_export_progress("done", 100, f"导出完成：{exported_cards} 张卡。")
    return export_result


_WINDOWS_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


def _file_identity(info: os.stat_result) -> tuple[int, int]:
    return (int(info.st_dev), int(info.st_ino))


def _is_reparse_stat(info: os.stat_result) -> bool:
    return bool(
        int(getattr(info, "st_file_attributes", 0))
        & _WINDOWS_FILE_ATTRIBUTE_REPARSE_POINT
    )


def _path_lstat(path: Path) -> os.stat_result:
    return os.stat(path, follow_symlinks=False)


def _path_is_reparse(path: Path, info: os.stat_result | None = None) -> bool:
    info = info or _path_lstat(path)
    return path.is_symlink() or _is_reparse_stat(info)


def _looks_like_standard_anki_media_directory(media_dir: Path) -> bool:
    if os.name != "nt":
        return False
    app_data = str(os.environ.get("APPDATA") or "").strip()
    if not app_data:
        return False
    try:
        trusted_root = Path(os.path.abspath(str(Path(app_data) / "Anki2")))
        lexical_media_dir = Path(os.path.abspath(str(media_dir)))
        relative = lexical_media_dir.relative_to(trusted_root)
        return len(relative.parts) == 2 and relative.parts[-1].lower() == "collection.media"
    except ValueError:
        return False


def _trusted_anki_media_directory_identity(media_dir: Path) -> tuple[int, int] | None:
    if os.name != "nt":
        return None
    app_data = str(os.environ.get("APPDATA") or "").strip()
    if not app_data:
        return None
    try:
        trusted_root = Path(os.path.abspath(str(Path(app_data) / "Anki2")))
        lexical_media_dir = Path(os.path.abspath(str(media_dir)))
        relative = lexical_media_dir.relative_to(trusted_root)
        if len(relative.parts) != 2 or relative.parts[-1].lower() != "collection.media":
            return None
        profile_dir = trusted_root / relative.parts[0]
        for component in (trusted_root, profile_dir, lexical_media_dir):
            info = _path_lstat(component)
            if not stat.S_ISDIR(info.st_mode) or _path_is_reparse(component, info):
                return None
        resolved_root = trusted_root.resolve(strict=True)
        resolved_media_dir = lexical_media_dir.resolve(strict=True)
        expected_media_dir = (resolved_root / relative.parts[0] / "collection.media").resolve(strict=True)
        if os.path.normcase(str(resolved_media_dir)) != os.path.normcase(str(expected_media_dir)):
            return None
        return _file_identity(_path_lstat(lexical_media_dir))
    except (OSError, ValueError):
        return None


def trusted_anki_media_directory(media_dir: Path) -> bool:
    return _trusted_anki_media_directory_identity(media_dir) is not None


def _stable_anki_media_directory_identity(media_dir: Path) -> tuple[int, int] | None:
    """Return a stable directory identity for import barriers.

    Standard Windows profiles must satisfy the stricter trusted-path contract.
    Portable and non-Windows profiles may use the bounded AnkiConnect fallback,
    but the media directory itself still cannot be a link or reparse point.
    """
    try:
        info = _path_lstat(media_dir)
        if not stat.S_ISDIR(info.st_mode) or _path_is_reparse(media_dir, info):
            return None
        if _looks_like_standard_anki_media_directory(media_dir):
            return _trusted_anki_media_directory_identity(media_dir)
        return _file_identity(info)
    except OSError:
        return None


def _verify_media_file_path(
    path: Path,
    expected_hash: str,
    expected_bytes: int,
) -> tuple[str, tuple[int, int] | None]:
    if not os.path.lexists(path):
        return "目标媒体文件不存在。", None
    try:
        path_info = _path_lstat(path)
        if _path_is_reparse(path, path_info) or not stat.S_ISREG(path_info.st_mode):
            return "目标同名项不是安全的普通文件，已拒绝使用。", None
        digest = hashlib.sha256()
        total = 0
        with path.open("rb") as handle:
            handle_info = os.fstat(handle.fileno())
            if not stat.S_ISREG(handle_info.st_mode) or _file_identity(handle_info) != _file_identity(path_info):
                return "目标媒体文件身份在校验前发生变化。", None
            while True:
                chunk = handle.read(ANKI_DIRECT_COPY_CHUNK_BYTES)
                if not chunk:
                    break
                total += len(chunk)
                if total > expected_bytes:
                    return "目标媒体文件大小与可信清单不一致。", None
                digest.update(chunk)
            final_handle_info = os.fstat(handle.fileno())
        final_path_info = _path_lstat(path)
        if (
            _path_is_reparse(path, final_path_info)
            or _file_identity(final_handle_info) != _file_identity(path_info)
            or _file_identity(final_path_info) != _file_identity(path_info)
        ):
            return "目标媒体文件身份在校验期间发生变化。", None
        if total != expected_bytes or digest.hexdigest() != expected_hash:
            return "目标媒体文件大小或哈希与可信清单不一致。", None
        return "", _file_identity(final_path_info)
    except OSError as err:
        return str(err), None


def _safe_unlink_owned_file(
    path: Path | None,
    identity: tuple[int, int] | None,
) -> tuple[bool, str]:
    if path is None or identity is None:
        return False, "缺少可证明的文件所有权，未执行清理。"
    if not os.path.lexists(path):
        return True, ""
    try:
        info = _path_lstat(path)
        if (
            not _path_is_reparse(path, info)
            and stat.S_ISREG(info.st_mode)
            and _file_identity(info) == identity
        ):
            path.unlink()
            if not os.path.lexists(path):
                return True, ""
            return False, "清理后文件仍然存在。"
        return False, "文件身份已变化，未删除无法证明属于本任务的路径。"
    except OSError as err:
        return False, str(err)


def _restore_anki_media_file_direct_result(
    source_path: Path,
    anki_media_dir: Path,
    filename: str,
    expected_hash: str,
    expected_bytes: int,
) -> dict[str, Any]:
    directory_identity = _trusted_anki_media_directory_identity(anki_media_dir)
    if directory_identity is None:
        return {
            "ok": False,
            "state": "failed",
            "code": "unsafe_source_or_name",
            "error": "Anki 媒体目录不在受信任的标准用户配置范围内，或包含链接/重解析点，已拒绝直接恢复。",
        }
    if (
        windows_safe_basename(filename) != filename
        or _SHA256_HEX_RE.fullmatch(expected_hash) is None
        or expected_bytes <= 0
        or expected_bytes > ANKI_MEDIA_MAX_FILE_BYTES
    ):
        return {
            "ok": False,
            "state": "failed",
            "code": "unsafe_source_or_name",
            "error": "媒体文件名、大小或哈希合同无效，已拒绝直接恢复。",
        }

    destination = anki_media_dir / filename
    temporary_path: Path | None = None
    temporary_identity: tuple[int, int] | None = None
    descriptor = -1
    outcome: dict[str, Any] = {}

    def finish(value: dict[str, Any]) -> dict[str, Any]:
        outcome.clear()
        outcome.update(value)
        return outcome

    try:
        source_parent_info = _path_lstat(source_path.parent)
        if (
            _path_is_reparse(source_path.parent, source_parent_info)
            or not stat.S_ISDIR(source_parent_info.st_mode)
        ):
            return finish({
                "ok": False,
                "state": "failed",
                "code": "unsafe_source_or_name",
                "error": "导出媒体源目录包含链接/重解析点或不是普通目录，已拒绝恢复。",
            })
        if os.path.lexists(destination):
            existing_error, _ = _verify_media_file_path(destination, expected_hash, expected_bytes)
            if not existing_error:
                return finish({"ok": True, "state": "already_present", "code": "", "error": ""})
            return finish({
                "ok": False,
                "state": "failed",
                "code": "destination_conflict",
                "error": "Anki 媒体目录中已有同名但内容不同或不安全的文件，已拒绝覆盖。",
            })

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".anki-card-generator-media-",
            suffix=".tmp",
            dir=str(anki_media_dir),
        )
        temporary_path = Path(temporary_name)
        temporary_handle_info = os.fstat(descriptor)
        temporary_path_info = _path_lstat(temporary_path)
        temporary_identity = _file_identity(temporary_handle_info)
        if (
            not stat.S_ISREG(temporary_handle_info.st_mode)
            or _path_is_reparse(temporary_path, temporary_path_info)
            or _file_identity(temporary_path_info) != temporary_identity
        ):
            raise OSError("目标目录临时文件身份异常。")

        digest = hashlib.sha256()
        total = 0
        with source_path.open("rb") as source_handle, os.fdopen(descriptor, "w+b") as temporary_handle:
            descriptor = -1
            source_path_info = _path_lstat(source_path)
            source_handle_info = os.fstat(source_handle.fileno())
            if (
                _path_is_reparse(source_path, source_path_info)
                or not stat.S_ISREG(source_path_info.st_mode)
                or not stat.S_ISREG(source_handle_info.st_mode)
                or _file_identity(source_path_info) != _file_identity(source_handle_info)
            ):
                return finish({
                    "ok": False,
                    "state": "failed",
                    "code": "unsafe_source_or_name",
                    "error": "导出媒体源不是稳定的普通文件，已拒绝恢复。",
                })
            remaining = expected_bytes
            while remaining:
                chunk = source_handle.read(min(ANKI_DIRECT_COPY_CHUNK_BYTES, remaining))
                if not chunk:
                    return finish({
                        "ok": False,
                        "state": "failed",
                        "code": "source_integrity_failed",
                        "error": "导出媒体源文件比可信清单更短，已拒绝恢复。",
                    })
                temporary_handle.write(chunk)
                digest.update(chunk)
                total += len(chunk)
                remaining -= len(chunk)
            if source_handle.read(1):
                return finish({
                    "ok": False,
                    "state": "failed",
                    "code": "source_integrity_failed",
                    "error": "导出媒体源文件比可信清单更长，已拒绝恢复。",
                })
            final_source_path_info = _path_lstat(source_path)
            if (
                _path_is_reparse(source_path, final_source_path_info)
                or _file_identity(final_source_path_info) != _file_identity(source_handle_info)
            ):
                return finish({
                    "ok": False,
                    "state": "failed",
                    "code": "source_integrity_failed",
                    "error": "导出媒体源文件身份在读取期间发生变化，已拒绝恢复。",
                })
            if total != expected_bytes or digest.hexdigest() != expected_hash:
                return finish({
                    "ok": False,
                    "state": "failed",
                    "code": "source_integrity_failed",
                    "error": "导出媒体源文件大小或哈希与清单不一致，已拒绝恢复。",
                })
            temporary_handle.flush()
            os.fsync(temporary_handle.fileno())
            temporary_handle.seek(0)
            verify_digest = hashlib.sha256()
            verify_total = 0
            while True:
                chunk = temporary_handle.read(ANKI_DIRECT_COPY_CHUNK_BYTES)
                if not chunk:
                    break
                verify_total += len(chunk)
                verify_digest.update(chunk)
            if verify_total != expected_bytes or verify_digest.hexdigest() != expected_hash:
                return finish({
                    "ok": False,
                    "state": "failed",
                    "code": "trusted_stream_copy_failed",
                    "error": "目标目录临时文件完整性校验失败，已拒绝发布。",
                })
            if _file_identity(os.fstat(temporary_handle.fileno())) != temporary_identity:
                raise OSError("目标目录临时文件身份在写入期间发生变化。")

        if _trusted_anki_media_directory_identity(anki_media_dir) != directory_identity:
            raise OSError("Anki 媒体目录身份在恢复期间发生变化。")
        temporary_path_info = _path_lstat(temporary_path)
        if (
            _path_is_reparse(temporary_path, temporary_path_info)
            or _file_identity(temporary_path_info) != temporary_identity
        ):
            raise OSError("目标目录临时文件身份在发布前发生变化。")
        if os.path.lexists(destination):
            existing_error, _ = _verify_media_file_path(destination, expected_hash, expected_bytes)
            if not existing_error:
                return finish({"ok": True, "state": "already_present", "code": "", "error": ""})
            return finish({
                "ok": False,
                "state": "failed",
                "code": "destination_conflict",
                "error": "恢复期间出现同名媒体冲突，已拒绝覆盖。",
            })
        try:
            publish_file_no_replace(temporary_path, destination)
        except FileExistsError:
            existing_error, _ = _verify_media_file_path(destination, expected_hash, expected_bytes)
            if not existing_error:
                return finish({"ok": True, "state": "already_present", "code": "", "error": ""})
            return finish({
                "ok": False,
                "state": "failed",
                "code": "destination_conflict",
                "error": "恢复期间出现同名媒体冲突，已拒绝覆盖。",
            })
        final_error, final_identity = _verify_media_file_path(destination, expected_hash, expected_bytes)
        if final_error or final_identity != temporary_identity:
            cleanup_ok, cleanup_error = _safe_unlink_owned_file(
                destination,
                temporary_identity,
            )
            return finish({
                "ok": False,
                "state": "failed",
                "code": "post_write_integrity_failed",
                "error": final_error or "写入后的 Anki 媒体身份与本次临时文件不一致。",
                "possible_partial_write": not cleanup_ok,
                "cleanup_error": cleanup_error or None,
            })
        if _trusted_anki_media_directory_identity(anki_media_dir) != directory_identity:
            cleanup_ok, cleanup_error = _safe_unlink_owned_file(
                destination,
                temporary_identity,
            )
            return finish({
                "ok": False,
                "state": "failed",
                "code": "post_write_integrity_failed",
                "error": "Anki 媒体目录身份在发布后发生变化。",
                "possible_partial_write": True,
                "cleanup_unproven": True,
                "cleanup_error": cleanup_error
                or (
                    "媒体目录身份已经变化；即使当前路径清理成功，也无法证明被替换前目录中的"
                    "已发布文件已经删除。"
                ),
            })
        temporary_path = None
        temporary_identity = None
        return finish({"ok": True, "state": "created", "code": "", "error": ""})
    except OSError as err:
        return finish({
            "ok": False,
            "state": "failed",
            "code": "trusted_stream_copy_failed",
            "error": str(err),
        })
    finally:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
        cleanup_ok, cleanup_error = _safe_unlink_owned_file(temporary_path, temporary_identity)
        if temporary_path is not None and not cleanup_ok:
            if outcome.get("ok"):
                outcome.update(
                    {
                        "ok": False,
                        "state": "failed",
                        "code": "temporary_cleanup_failed",
                        "error": "无法清理本次任务拥有的 Anki 媒体临时文件，已停止并保留诊断证据。",
                    }
                )
            outcome["possible_partial_write"] = True
            outcome["cleanup_error"] = cleanup_error or "Anki 媒体临时文件清理失败。"


def restore_anki_media_file_direct(
    source_path: Path,
    anki_media_dir: Path,
    filename: str,
    expected_hash: str,
    expected_bytes: int,
) -> str:
    return str(
        _restore_anki_media_file_direct_result(
            source_path,
            anki_media_dir,
            filename,
            expected_hash,
            expected_bytes,
        ).get("error")
        or ""
    )


def restore_missing_anki_media(
    missing_names: list[str],
    expected_manifest: dict[str, dict[str, Any]],
    media_dir: Path,
    anki_media_dir: Path,
    anki_url: str,
    progress_label: str = "APKG 未带入全部媒体，正在安全补齐",
    progress_start_percent: int = 30,
    progress_span_percent: int = 20,
) -> dict[str, Any]:
    unique_names = sorted(set(missing_names))
    restored: list[str] = []
    restored_by: dict[str, str] = {}
    failures: list[dict[str, Any]] = []
    ownership_ledger: list[dict[str, Any]] = []

    def add_success(name: str, method: str, state: str) -> None:
        restored.append(name)
        restored_by[name] = method
        ownership_ledger.append(
            {"file": name, "state": state, "method": method}
        )

    def add_failure(name: str, code: str, error: str, **details: Any) -> None:
        item = {"file": name, "code": code, "error": error, **details}
        failures.append(item)
        ownership_ledger.append(
            {
                "file": name,
                "state": "failed",
                "code": code,
                "error": error,
                **details,
            }
        )

    def result() -> dict[str, Any]:
        return {
            "attempted": bool(missing_names),
            "restored": restored,
            "restored_by": restored_by,
            "failures": failures,
            "ownership_ledger": ownership_ledger,
            "created": [
                item["file"] for item in ownership_ledger if item.get("state") == "created"
            ],
            "already_present": [
                item["file"] for item in ownership_ledger if item.get("state") == "already_present"
            ],
            "failed": [
                item["file"] for item in ownership_ledger if item.get("state") == "failed"
            ],
        }

    if len(unique_names) > ANKI_MEDIA_MAX_ITEMS:
        add_failure(
            "",
            "media_contract_limit_exceeded",
            f"待恢复媒体超过 {ANKI_MEDIA_MAX_ITEMS} 项的安全上限。",
        )
        return result()

    expected_total_bytes = 0
    for name in unique_names:
        normalized_name = windows_safe_basename(name)
        manifest_entry = expected_manifest.get(name) or {}
        expected_hash = str(manifest_entry.get("sha256") or "").strip().lower()
        expected_bytes = _strict_export_int(manifest_entry.get("bytes"))
        if normalized_name is None:
            add_failure(name, "unsafe_source_or_name", "媒体文件名不安全，已拒绝恢复。")
            continue
        if (
            _SHA256_HEX_RE.fullmatch(expected_hash) is None
            or expected_bytes is None
            or expected_bytes <= 0
            or expected_bytes > ANKI_MEDIA_MAX_FILE_BYTES
        ):
            add_failure(
                name,
                "source_integrity_failed",
                "媒体清单中的大小或 sha256 合同无效，已拒绝恢复。",
            )
            continue
        expected_total_bytes += expected_bytes
        if expected_total_bytes > ANKI_MEDIA_MAX_TOTAL_BYTES:
            add_failure(
                name,
                "media_contract_limit_exceeded",
                "待恢复媒体总量超过 2 GiB 的安全上限。",
            )
            break
    if failures:
        return result()

    total = len(unique_names)
    for index, name in enumerate(unique_names, start=1):
        normalized_name = windows_safe_basename(name)
        source_path = media_dir / normalized_name
        manifest_entry = expected_manifest.get(name) or {}
        expected_hash = str(manifest_entry.get("sha256") or "").strip().lower()
        expected_bytes = _strict_export_int(manifest_entry.get("bytes"))
        assert expected_bytes is not None

        emit_progress(
            "verify_anki_import",
            "restore_media",
            progress_start_percent
            + int((index / max(1, total)) * progress_span_percent),
            f"{progress_label} {index}/{total}。",
        )

        try:
            anki_media_dir_info = _path_lstat(anki_media_dir)
            anki_media_dir_reparse = (
                _path_is_reparse(anki_media_dir, anki_media_dir_info)
                or not stat.S_ISDIR(anki_media_dir_info.st_mode)
            )
        except OSError:
            anki_media_dir_reparse = True
        direct_trusted = trusted_anki_media_directory(anki_media_dir)
        if anki_media_dir_reparse or (
            _looks_like_standard_anki_media_directory(anki_media_dir)
            and not direct_trusted
        ):
            add_failure(
                name,
                "unsafe_source_or_name",
                "Anki 媒体目录包含链接/重解析点或身份不稳定，已拒绝恢复。",
            )
            continue

        if direct_trusted:
            direct_result = _restore_anki_media_file_direct_result(
                source_path,
                anki_media_dir,
                normalized_name,
                expected_hash,
                expected_bytes,
            )
            if direct_result.get("ok"):
                add_success(
                    name,
                    "trusted_atomic_copy",
                    str(direct_result.get("state") or "created"),
                )
            else:
                direct_details = {
                    key: value
                    for key, value in direct_result.items()
                    if key not in {"ok", "state", "code", "error"}
                    and value is not None
                }
                add_failure(
                    name,
                    str(direct_result.get("code") or "trusted_stream_copy_failed"),
                    str(direct_result.get("error") or "无法安全流式预置 Anki 媒体。"),
                    **direct_details,
                )
            continue

        if expected_bytes > ANKI_CONNECT_MEDIA_MAX_RAW_BYTES:
            add_failure(
                name,
                "anki_connect_media_limit_exceeded",
                (
                    "当前 Anki 使用非标准或不可直接验证的媒体目录；为避免整文件 Base64 "
                    f"导致内存峰值，AnkiConnect 兼容路径只允许不超过 "
                    f"{ANKI_CONNECT_MEDIA_MAX_RAW_BYTES // (1024 * 1024)} MiB 的单个媒体。"
                    "请改用标准 Anki profile，或手动导入 APKG。"
                ),
            )
            continue

        try:
            source_parent_info = _path_lstat(source_path.parent)
            if (
                _path_is_reparse(source_path.parent, source_parent_info)
                or not stat.S_ISDIR(source_parent_info.st_mode)
            ):
                add_failure(
                    name,
                    "unsafe_source_or_name",
                    "导出媒体源目录包含链接/重解析点或不是普通目录，已拒绝传输。",
                )
                continue
            source_path_info = _path_lstat(source_path)
            if _path_is_reparse(source_path, source_path_info) or not stat.S_ISREG(source_path_info.st_mode):
                add_failure(
                    name,
                    "unsafe_source_or_name",
                    "导出媒体源不是安全的普通文件，已拒绝通过 AnkiConnect 传输。",
                )
                continue
            with source_path.open("rb") as source_handle:
                source_handle_info = os.fstat(source_handle.fileno())
                if (
                    not stat.S_ISREG(source_handle_info.st_mode)
                    or _file_identity(source_handle_info) != _file_identity(source_path_info)
                ):
                    add_failure(
                        name,
                        "unsafe_source_or_name",
                        "导出媒体源文件身份不稳定，已拒绝通过 AnkiConnect 传输。",
                    )
                    continue
                source_bytes = source_handle.read(ANKI_CONNECT_MEDIA_MAX_RAW_BYTES + 1)
                final_source_path_info = _path_lstat(source_path)
            if (
                _path_is_reparse(source_path, final_source_path_info)
                or _file_identity(final_source_path_info) != _file_identity(source_handle_info)
                or len(source_bytes) != expected_bytes
                or hashlib.sha256(source_bytes).hexdigest() != expected_hash
            ):
                add_failure(
                    name,
                    "source_integrity_failed",
                    "导出媒体源文件大小、哈希或身份与可信清单不一致，已拒绝恢复。",
                )
                continue
        except OSError as err:
            add_failure(name, "unsafe_source_or_name", f"无法安全读取导出媒体源：{err}")
            continue

        store_attempted = False
        try:
            existing_data = anki_connect(
                "retrieveMediaFile",
                {"filename": normalized_name},
                anki_url,
            )
            if existing_data:
                try:
                    existing_bytes = decode_anki_media_base64(existing_data)
                except (ValueError, RuntimeError) as err:
                    add_failure(
                        name,
                        (
                            "anki_connect_response_too_large"
                            if ANKI_CONNECT_RESPONSE_TOO_LARGE_MARKER in str(err)
                            else "post_write_integrity_failed"
                        ),
                        f"无法校验 Anki 中的同名媒体：{err}",
                    )
                    continue
                if (
                    len(existing_bytes) == expected_bytes
                    and hashlib.sha256(existing_bytes).hexdigest() == expected_hash
                ):
                    add_success(name, "anki_connect_existing_race", "already_present")
                    continue
                add_failure(
                    name,
                    "destination_conflict",
                    "写入前 Anki 中出现同名但内容不同的媒体，已拒绝覆盖。",
                )
                continue

            store_attempted = True
            stored_name = anki_connect(
                "storeMediaFile",
                {
                    "filename": normalized_name,
                    "data": base64.b64encode(source_bytes).decode("ascii"),
                    "deleteExisting": False,
                },
                anki_url,
            )
        except Exception as err:
            error_text = str(err)
            if not store_attempted:
                add_failure(
                    name,
                    (
                        "anki_connect_response_too_large"
                        if ANKI_CONNECT_RESPONSE_TOO_LARGE_MARKER in error_text
                        else "anki_connect_store_failed"
                    ),
                    f"无法在写入前有界校验 Anki 媒体目录：{err}",
                    possible_partial_write=False,
                )
                continue
            cross_drive_error = any(
                marker in error_text.lower()
                for marker in (
                    "cross-device",
                    "different disk drive",
                    "os error 17",
                    "不同的磁盘驱动器",
                    "无法将文件移到不同",
                )
            )
            try:
                reconciled_data = anki_connect(
                    "retrieveMediaFile",
                    {"filename": normalized_name},
                    anki_url,
                )
                reconciled_bytes = (
                    decode_anki_media_base64(reconciled_data)
                    if reconciled_data
                    else None
                )
            except Exception as reconcile_err:
                add_failure(
                    name,
                    "anki_connect_store_failed",
                    f"AnkiConnect 写入结果未知，且无法完成有界核验：{err}",
                    reconcile_error=str(reconcile_err),
                    possible_partial_write=True,
                )
                continue
            if (
                reconciled_bytes is not None
                and len(reconciled_bytes) == expected_bytes
                and hashlib.sha256(reconciled_bytes).hexdigest() == expected_hash
            ):
                add_success(name, "anki_connect_reconciled", "already_present")
                continue
            add_failure(
                name,
                (
                    "destination_conflict"
                    if reconciled_bytes is not None
                    else "anki_connect_store_failed"
                ),
                (
                    "AnkiConnect 写入失败后发现同名但内容不同的媒体，已停止导入。"
                    if reconciled_bytes is not None
                    else (
                        "当前 Anki 媒体目录不是可验证的标准 profile，且 AnkiConnect "
                        "无法完成跨磁盘写入；请改用标准 Anki profile 或手动导入 APKG。"
                        if cross_drive_error
                        else f"AnkiConnect 未能写入媒体：{err}"
                    )
                ),
                possible_partial_write=True,
            )
            continue

        stored_basename = windows_safe_basename(str(stored_name or ""))
        stored_name_matches = (
            stored_basename is not None
            and windows_basename_key(stored_basename) == windows_basename_key(normalized_name)
        )
        if not stored_name_matches:
            add_failure(
                name,
                "anki_connect_store_failed",
                f"AnkiConnect 返回了意外的媒体文件名：{stored_name}",
                possible_orphan=str(stored_name or ""),
            )
            continue
        try:
            persisted_data = anki_connect(
                "retrieveMediaFile",
                {"filename": stored_basename},
                anki_url,
            )
            persisted_bytes = decode_anki_media_base64(persisted_data)
        except (ValueError, RuntimeError, OSError) as err:
            add_failure(
                name,
                (
                    "anki_connect_response_too_large"
                    if ANKI_CONNECT_RESPONSE_TOO_LARGE_MARKER in str(err)
                    else "post_write_integrity_failed"
                ),
                f"Anki 媒体写后校验失败：{err}",
                possible_partial_write=True,
            )
            continue
        if len(persisted_bytes) != expected_bytes or hashlib.sha256(persisted_bytes).hexdigest() != expected_hash:
            add_failure(
                name,
                "post_write_integrity_failed",
                "Anki 媒体写入后的大小或哈希与可信清单不一致。",
                possible_partial_write=True,
            )
            continue
        add_success(name, "anki_connect", "created")

    return result()


def inspect_anki_media_for_preload(
    expected_manifest: dict[str, dict[str, Any]],
    anki_media_dir: Path,
) -> dict[str, Any]:
    missing: list[str] = []
    already_present: list[str] = []
    conflicts: list[dict[str, str]] = []
    failures: list[dict[str, str]] = []

    if _stable_anki_media_directory_identity(anki_media_dir) is None:
        return {
            "missing": missing,
            "already_present": already_present,
            "conflicts": conflicts,
            "failures": [
                {
                    "file": "",
                    "error": "Anki 媒体目录包含链接/重解析点、不是普通目录或身份不稳定，已拒绝使用。",
                }
            ],
        }

    for name in sorted(expected_manifest):
        normalized_name = windows_safe_basename(name)
        if normalized_name is None:
            failures.append({"file": name, "error": "媒体文件名不安全，已拒绝预置。"})
            continue

        expected_hash = str((expected_manifest.get(name) or {}).get("sha256") or "").strip().lower()
        expected_bytes = _strict_export_int((expected_manifest.get(name) or {}).get("bytes"))
        if (
            _SHA256_HEX_RE.fullmatch(expected_hash) is None
            or expected_bytes is None
            or expected_bytes <= 0
            or expected_bytes > ANKI_MEDIA_MAX_FILE_BYTES
        ):
            failures.append({"file": name, "error": "媒体清单缺少有效大小或 sha256，已拒绝预置。"})
            continue

        destination = anki_media_dir / normalized_name
        if not os.path.lexists(destination):
            missing.append(name)
            continue
        verification_error, _ = _verify_media_file_path(
            destination,
            expected_hash,
            expected_bytes,
        )
        if not verification_error:
            already_present.append(name)
        else:
            conflicts.append(
                {
                    "file": name,
                    "error": (
                        "Anki 媒体目录中已有同名但内容不同或不安全的文件，"
                        f"已拒绝覆盖：{verification_error}"
                    ),
                    "expected_sha256": expected_hash,
                }
            )

    return {
        "missing": missing,
        "already_present": already_present,
        "conflicts": conflicts,
        "failures": failures,
    }


def merge_anki_media_recovery(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    restored = list(dict.fromkeys([*(first.get("restored") or []), *(second.get("restored") or [])]))
    restored_by = dict(first.get("restored_by") or {})
    restored_by.update(second.get("restored_by") or {})
    return {
        "attempted": bool(first.get("attempted") or second.get("attempted")),
        "restored": restored,
        "restored_by": restored_by,
        "failures": [*(first.get("failures") or []), *(second.get("failures") or [])],
        "ownership_ledger": [
            *(first.get("ownership_ledger") or []),
            *(second.get("ownership_ledger") or []),
        ],
        "created": list(
            dict.fromkeys([*(first.get("created") or []), *(second.get("created") or [])])
        ),
        "already_present": list(
            dict.fromkeys(
                [
                    *(first.get("already_present") or []),
                    *(second.get("already_present") or []),
                ]
            )
        ),
        "failed": list(
            dict.fromkeys([*(first.get("failed") or []), *(second.get("failed") or [])])
        ),
    }


def wait_for_anki_media_directory(anki_url: str, timeout_seconds: float = 0.0) -> Path:
    timeout_seconds = max(0.0, min(float(timeout_seconds or 0.0), 20.0))
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while True:
        try:
            media_dir_text = str(anki_connect("getMediaDirPath", {}, anki_url) or "").strip()
            if not media_dir_text:
                raise RuntimeError("AnkiConnect 没有返回可用的 collection.media 目录。")
            media_dir = Path(media_dir_text)
            if not media_dir.is_dir():
                raise RuntimeError("AnkiConnect 返回的 collection.media 目录不存在。")
            return media_dir
        except Exception as err:
            last_error = err
            if time.monotonic() >= deadline:
                raise last_error
            time.sleep(0.4)


def anki_import_preflight_query(deck_name: str, anki_tag: str) -> str:
    def quote(value: str) -> str:
        return str(value or "").replace("\\", "\\\\").replace('"', '\\"')

    return f'deck:"{quote(deck_name)}" tag:"{quote(anki_tag)}"'


NOTE_CONTENT_FINGERPRINT_SCHEMA_VERSION = 1
NOTE_CONTENT_FINGERPRINT_ALGORITHM = "sha256"
NOTE_CONTENT_FINGERPRINT_SERIALIZATION = "json-field-pairs-v1"


def note_content_sha256(field_names: list[str], field_values: list[Any]) -> str:
    """Fingerprint a note's complete fields in the model-defined order."""
    if len(field_names) != len(field_values):
        raise ValueError("note field names and values must have equal lengths")
    field_pairs = [
        [str(name), "" if value is None else str(value)]
        for name, value in zip(field_names, field_values)
    ]
    serialized = json.dumps(field_pairs, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def exported_card_ids_for_import_preflight(export_result: dict[str, Any]) -> set[str]:
    card_media_ledger = (
        export_result.get("card_media_ledger")
        if isinstance(export_result.get("card_media_ledger"), list)
        else []
    )
    audio_audit_items, _ = load_audio_audit_from_export_result(export_result)
    return {
        str(item.get("card_id") or "").strip()
        for item in [*card_media_ledger, *audio_audit_items]
        if isinstance(item, dict) and str(item.get("card_id") or "").strip()
    }


def exported_note_content_fingerprints_for_import_preflight(
    export_result: dict[str, Any],
) -> tuple[dict[str, Any] | None, str]:
    metadata = export_result.get("note_content_fingerprint")
    if not isinstance(metadata, dict):
        return None, "content_fingerprint_metadata_missing"
    if metadata.get("schema_version") != NOTE_CONTENT_FINGERPRINT_SCHEMA_VERSION:
        return None, "content_fingerprint_schema_unsupported"
    if str(metadata.get("algorithm") or "").lower() != NOTE_CONTENT_FINGERPRINT_ALGORITHM:
        return None, "content_fingerprint_algorithm_unsupported"
    if str(metadata.get("serialization") or "") != NOTE_CONTENT_FINGERPRINT_SERIALIZATION:
        return None, "content_fingerprint_serialization_unsupported"

    raw_field_names = metadata.get("field_names")
    if not isinstance(raw_field_names, list):
        return None, "content_fingerprint_fields_missing"
    field_names = [str(name or "").strip() for name in raw_field_names]
    if not field_names or any(not name for name in field_names) or len(set(field_names)) != len(field_names):
        return None, "content_fingerprint_fields_invalid"

    card_media_ledger = export_result.get("card_media_ledger")
    if not isinstance(card_media_ledger, list) or not card_media_ledger:
        return None, "content_fingerprint_ledger_missing"
    try:
        expected_count = int(metadata.get("card_count"))
    except (TypeError, ValueError):
        return None, "content_fingerprint_card_count_invalid"
    if expected_count != len(card_media_ledger):
        return None, "content_fingerprint_card_count_mismatch"

    hashes_by_card_id: dict[str, str] = {}
    for item in card_media_ledger:
        if not isinstance(item, dict):
            return None, "content_fingerprint_ledger_invalid"
        card_id = str(item.get("card_id") or "").strip()
        digest = str(item.get("note_content_sha256") or "").strip().lower()
        if not card_id or card_id in hashes_by_card_id:
            return None, "content_fingerprint_card_ids_invalid"
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            return None, "content_fingerprint_hash_invalid"
        hashes_by_card_id[card_id] = digest

    if len(hashes_by_card_id) != expected_count:
        return None, "content_fingerprint_coverage_mismatch"
    return {"field_names": field_names, "hashes_by_card_id": hashes_by_card_id}, ""


def imported_note_content_sha256(card_info: dict[str, Any], field_names: list[str]) -> str | None:
    fields = card_info.get("fields")
    if not isinstance(fields, dict) or any(name not in fields for name in field_names):
        return None
    values: list[Any] = []
    for name in field_names:
        field = fields.get(name)
        if not isinstance(field, dict) or "value" not in field:
            return None
        values.append(field.get("value"))
    return note_content_sha256(field_names, values)


def anki_deck_is_within_export(imported_deck_name: str, deck_name: str) -> bool:
    imported = str(imported_deck_name or "").strip()
    expected = str(deck_name or "").strip()
    return bool(imported and expected and (imported == expected or imported.startswith(f"{expected}::")))


def inspect_existing_anki_import(
    export_result: dict[str, Any],
    *,
    deck_name: str,
    anki_tag: str,
    expected_cards: int,
    anki_url: str,
) -> dict[str, Any]:
    # A failed or ambiguous preflight must never suppress importPackage.
    # Current exports are matched by their complete CardId evidence. The
    # count-only fallback is reserved for legacy cards that expose no CardId
    # and is still scoped by an exact deck + tag query.

    strict_query = anki_import_preflight_query(deck_name, anki_tag)
    result: dict[str, Any] = {
        "complete": False,
        "query": strict_query,
        "evidence": "none",
        "expected_cards": expected_cards,
        "matched_cards": 0,
        "error": None,
        "reason": "insufficient_evidence",
    }
    if not deck_name or not anki_tag or expected_cards <= 0:
        return result

    try:
        found_card_ids = list(anki_connect("findCards", {"query": strict_query}, anki_url) or [])
        card_infos = (
            list(anki_connect("cardsInfo", {"cards": found_card_ids}, anki_url) or [])
            if found_card_ids
            else []
        )
    except Exception as err:
        result["error"] = str(err)
        result["reason"] = "query_failed"
        return result

    # A strict Anki query is the primary deck/tag boundary. If cardsInfo also
    # reports a deck, reject any result that escaped that boundary. Parent deck
    # exports legitimately contain cards in child decks.
    if any(
        (imported_deck := anki_card_deck_name(info))
        and not anki_deck_is_within_export(imported_deck, deck_name)
        for info in card_infos
    ):
        result["reason"] = "deck_scope_mismatch"
        return result

    card_infos_by_export_id: dict[str, list[dict[str, Any]]] = {}
    for info in card_infos:
        export_card_id = anki_field_plain_text((info.get("fields") or {}), "CardId").strip()
        if export_card_id:
            card_infos_by_export_id.setdefault(export_card_id, []).append(info)

    expected_card_ids = exported_card_ids_for_import_preflight(export_result)
    imported_card_ids = set(card_infos_by_export_id)
    result["matched_cards"] = len(expected_card_ids & imported_card_ids)

    if expected_card_ids:
        result["evidence"] = "card_id_only"
        if len(expected_card_ids) != expected_cards:
            result["reason"] = "incomplete_export_card_id_evidence"
            return result
        missing_card_ids = sorted(expected_card_ids - imported_card_ids)
        if missing_card_ids:
            result["reason"] = "missing_export_card_ids"
            result["missing_card_ids"] = missing_card_ids
            return result

        fingerprint, fingerprint_error = exported_note_content_fingerprints_for_import_preflight(export_result)
        if fingerprint is None:
            result["reason"] = fingerprint_error
            return result
        hashes_by_card_id = fingerprint["hashes_by_card_id"]
        if set(hashes_by_card_id) != expected_card_ids:
            result["reason"] = "content_fingerprint_card_id_mismatch"
            return result
        field_names = fingerprint["field_names"]
        mismatched_card_ids = [
            card_id
            for card_id in sorted(expected_card_ids)
            if not any(
                imported_note_content_sha256(info, field_names) == hashes_by_card_id[card_id]
                for info in card_infos_by_export_id.get(card_id, [])
            )
        ]
        if mismatched_card_ids:
            result["reason"] = "note_content_fingerprint_mismatch"
            result["mismatched_card_ids"] = mismatched_card_ids
            return result
        result["evidence"] = "card_id+content_sha256"
        result["complete"] = True
        result["reason"] = "all_export_card_ids_and_content_match"
        return result

    # If Anki exposes CardId values but the export result cannot identify the
    # current package, an equal count may belong to an older package. Import in
    # that case instead of guessing. Count-only matching is only for legacy
    # packages whose notes genuinely have no CardId field/value.
    if imported_card_ids:
        result["reason"] = "current_export_card_ids_unavailable"
        return result

    result["evidence"] = "legacy_unbound"
    if len(found_card_ids) != expected_cards or len(card_infos) != expected_cards:
        result["reason"] = "strict_count_mismatch"
        return result
    result["matched_cards"] = len(card_infos)
    result["reason"] = "legacy_content_fingerprint_unavailable"
    return result


def anki_verify_query_progress_percent(import_attempted: bool) -> int:
    return 62 if import_attempted else 18


ANKI_IMPORT_DECK_KINDS = frozenset(
    {"video_language", "subtitle_language", "document_knowledge", "document_reading"}
)
LANGUAGE_IMPORT_TEMPLATE_FAMILIES = frozenset(
    {
        "language-immersive-v11",
        "language-immersive-v11-fast",
        "language-ciba-tianxia-v1-warm_paper",
        "language-ciba-tianxia-v1-minimal_white",
        "language-ciba-tianxia-v1-dark_immersive",
        "language-immersive",
        "language-dictionary",
        "language-minimal",
    }
)


def _canonical_import_path(value: Any) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        return ""
    try:
        path = Path(value)
        if not path.is_absolute():
            return ""
        return os.path.normcase(str(path.resolve(strict=False)))
    except (OSError, RuntimeError, ValueError):
        return ""


def _strict_export_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def validate_export_result_write_contract(export_result: dict[str, Any]) -> dict[str, Any]:
    cards = _strict_export_int(export_result.get("cards"))
    if cards is None or cards <= 0:
        return _import_preflight_failure(
            "apkg_export_card_count_invalid",
            "可信导出结果缺少有效卡片数量，已停止写入 Anki。",
        )

    manifest = export_result.get("media_manifest")
    media_summary = export_result.get("media_summary")
    if not isinstance(manifest, dict) or not isinstance(media_summary, dict):
        return _import_preflight_failure(
            "apkg_export_media_manifest_missing",
            "可信导出结果缺少固定媒体清单，不能从目录重新推断，已停止写入 Anki。",
        )
    expected_media_files = _strict_export_int(media_summary.get("media_files"))
    expected_media_bytes = _strict_export_int(media_summary.get("media_bytes"))
    if expected_media_files is None or expected_media_files < 0 or expected_media_bytes is None or expected_media_bytes < 0:
        return _import_preflight_failure(
            "apkg_export_media_summary_invalid",
            "可信导出结果中的媒体计数无效，已停止写入 Anki。",
        )
    if expected_media_files != len(manifest):
        return _import_preflight_failure(
            "apkg_export_media_manifest_mismatch",
            "可信导出结果中的媒体清单数量与摘要不一致，已停止写入 Anki。",
        )
    if (
        expected_media_files > ANKI_MEDIA_MAX_ITEMS
        or expected_media_bytes > ANKI_MEDIA_MAX_TOTAL_BYTES
    ):
        return _import_preflight_failure(
            "apkg_export_media_contract_limit_exceeded",
            (
                "可信导出结果中的媒体数量或总大小超过安全上限，已停止写入 Anki："
                f"最多 {ANKI_MEDIA_MAX_ITEMS} 项、"
                f"{ANKI_MEDIA_MAX_TOTAL_BYTES // (1024 * 1024 * 1024)} GiB。"
            ),
        )

    total_media_bytes = 0
    manifest_name_keys: set[str] = set()
    for name, item in manifest.items():
        name_key = windows_basename_key(name)
        if name_key is None or name_key in manifest_name_keys or not isinstance(item, dict):
            return _import_preflight_failure(
                "apkg_export_media_manifest_invalid",
                "可信导出结果包含不安全或在 Windows 上冲突的媒体清单项，已停止写入 Anki。",
            )
        manifest_name_keys.add(name_key)
        digest = item.get("sha256")
        byte_count = _strict_export_int(item.get("bytes"))
        if (
            not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or byte_count is None
            or byte_count <= 0
            or byte_count > ANKI_MEDIA_MAX_FILE_BYTES
        ):
            return _import_preflight_failure(
                "apkg_export_media_manifest_invalid",
                "可信导出结果包含无效媒体哈希或大小，已停止写入 Anki。",
                media_file=name,
            )
        total_media_bytes += byte_count
    if (
        total_media_bytes != expected_media_bytes
        or total_media_bytes > ANKI_MEDIA_MAX_TOTAL_BYTES
    ):
        return _import_preflight_failure(
            "apkg_export_media_manifest_mismatch",
            "可信导出结果中的媒体总大小与清单不一致或超过安全上限，已停止写入 Anki。",
        )

    ledger = export_result.get("card_media_ledger")
    if not isinstance(ledger, list) or len(ledger) != cards:
        return _import_preflight_failure(
            "apkg_export_card_ledger_invalid",
            "可信导出结果中的卡片账本与导出数量不一致，已停止写入 Anki。",
        )
    seen_card_ids: set[str] = set()
    for item in ledger:
        if not isinstance(item, dict):
            return _import_preflight_failure(
                "apkg_export_card_ledger_invalid",
                "可信导出结果包含无效卡片账本项，已停止写入 Anki。",
            )
        card_id = item.get("card_id")
        content_digest = item.get("note_content_sha256")
        segment_id = item.get("segment_id")
        deck_name = item.get("deck_name")
        if (
            not isinstance(card_id, str)
            or not card_id
            or card_id in seen_card_ids
            or not isinstance(segment_id, str)
            or not segment_id
            or segment_id != segment_id.strip()
            or not isinstance(deck_name, str)
            or not deck_name
            or deck_name != deck_name.strip()
            or not isinstance(content_digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", content_digest) is None
        ):
            return _import_preflight_failure(
                "apkg_export_card_ledger_invalid",
                "可信导出结果中的卡片身份或内容摘要无效，已停止写入 Anki。",
            )
        seen_card_ids.add(card_id)

    return {
        "ok": True,
        "failed_checks": [],
        "cards": cards,
        "media_manifest": manifest,
        "media_files": expected_media_files,
        "media_bytes": expected_media_bytes,
    }


def _import_preflight_failure(code: str, message: str, **details: Any) -> dict[str, Any]:
    return {
        "ok": False,
        "message": message,
        "failed_checks": [code],
        **details,
    }


def _payload_export_override_mismatch(
    payload: dict[str, Any],
    export_result: dict[str, Any],
) -> dict[str, Any] | None:
    path_fields = ("apkg_path", "media_dir")
    for field in path_fields:
        if field not in payload:
            continue
        trusted = _canonical_import_path(export_result.get(field))
        supplied = _canonical_import_path(payload.get(field))
        if not trusted or supplied != trusted:
            return _import_preflight_failure(
                "apkg_export_identity_mismatch",
                f"导入请求中的 {field} 与本次可信导出结果不一致，已停止写入 Anki。",
                identity_field=field,
            )

    exact_fields = (
        "deck_name",
        "deck_kind",
        "anki_tag",
        "template_family",
        "template_schema",
        "template_version",
        "note_model_id",
        "model_name",
        "compatibility_contract_version",
        "note_model_contract_digest",
        "apkg_sha256",
        "apkg_size_bytes",
        "source_fingerprint",
        "source_identity",
    )
    for field in exact_fields:
        if field not in payload:
            continue
        expected = export_result.get(field)
        if field == "source_fingerprint" and not expected:
            source_identity = export_result.get("source_identity")
            if isinstance(source_identity, dict):
                expected = source_identity.get("source_fingerprint")
        if payload.get(field) != expected:
            return _import_preflight_failure(
                "apkg_export_identity_mismatch",
                f"导入请求中的 {field} 与本次可信导出结果不一致，已停止写入 Anki。",
                identity_field=field,
            )
    if "expected_cards" in payload and payload.get("expected_cards") != export_result.get("cards"):
        return _import_preflight_failure(
            "apkg_export_identity_mismatch",
            "导入请求中的卡片数量与本次可信导出结果不一致，已停止写入 Anki。",
            identity_field="expected_cards",
        )
    return None


def _allowed_deck_kinds_for_contract_family(template_family: str) -> frozenset[str]:
    if template_family in LANGUAGE_IMPORT_TEMPLATE_FAMILIES:
        return frozenset({"video_language", "subtitle_language"})
    if template_family == "document-knowledge":
        return frozenset({"document_knowledge"})
    if template_family == "document-reading":
        return frozenset({"document_reading"})
    return frozenset()


def preflight_anki_import_apkg(
    payload: dict[str, Any],
    export_result: dict[str, Any],
) -> dict[str, Any]:
    """Fail closed before media preparation or any AnkiConnect write action."""
    if not isinstance(export_result, dict) or not export_result:
        return _import_preflight_failure(
            "apkg_export_result_missing",
            "缺少可信导出结果，无法证明这个 APKG 属于当前任务，已停止写入 Anki。",
        )

    override_failure = _payload_export_override_mismatch(payload, export_result)
    if override_failure:
        return override_failure

    if str(payload.get("anki_query") or "").strip():
        return _import_preflight_failure(
            "anki_import_query_override_forbidden",
            "导入与写入前核验不接受自定义 Anki 查询，已停止写入。",
        )

    trusted_path_text = export_result.get("apkg_path")
    trusted_canonical_path = _canonical_import_path(trusted_path_text)
    if not trusted_canonical_path:
        return _import_preflight_failure(
            "apkg_export_path_invalid",
            "可信导出结果缺少有效的 APKG 路径，已停止写入 Anki。",
        )
    apkg_path = Path(str(trusted_path_text))
    try:
        if not apkg_path.exists() or not apkg_path.is_file():
            return _import_preflight_failure(
                "apkg_missing_for_import",
                f"找不到可信导出结果中的 APKG：{apkg_path}",
            )
        if apkg_path.suffix.lower() != ".apkg":
            return _import_preflight_failure(
                "apkg_invalid_for_import",
                f"可信导出路径不是 APKG 文件：{apkg_path}",
            )
    except OSError as err:
        return _import_preflight_failure(
            "apkg_read_failed",
            f"无法读取可信导出的 APKG，已停止写入 Anki：{err}",
        )

    write_contract = validate_export_result_write_contract(export_result)
    if not write_contract.get("ok"):
        return write_contract

    deck_name = export_result.get("deck_name")
    deck_kind = export_result.get("deck_kind")
    if not isinstance(deck_name, str) or not deck_name or deck_name != deck_name.strip():
        return _import_preflight_failure(
            "apkg_export_identity_invalid",
            "可信导出结果缺少精确牌组名称，已停止写入 Anki。",
            identity_field="deck_name",
        )
    if deck_kind not in ANKI_IMPORT_DECK_KINDS:
        return _import_preflight_failure(
            "apkg_deck_kind_unsupported",
            "可信导出结果包含未知的卡片类型，已停止写入 Anki。",
            deck_kind=deck_kind,
        )

    trusted_media_text = export_result.get("media_dir")
    trusted_media_canonical = _canonical_import_path(trusted_media_text)
    if not trusted_media_canonical:
        return _import_preflight_failure(
            "apkg_export_media_path_invalid",
            "可信导出结果缺少有效的绝对媒体目录，已停止写入 Anki。",
        )
    trusted_media_path = Path(str(trusted_media_text))
    manifest = write_contract["media_manifest"]
    media_count = int(write_contract["media_files"])
    requires_media_dir = media_count > 0
    try:
        if trusted_media_path.exists() and not trusted_media_path.is_dir():
            return _import_preflight_failure(
                "apkg_export_media_path_invalid",
                "可信导出结果中的媒体路径不是目录，已停止写入 Anki。",
            )
        if requires_media_dir and not trusted_media_path.is_dir():
            return _import_preflight_failure(
                "apkg_export_media_path_missing",
                "可信导出的媒体目录不存在，已停止写入 Anki。",
            )
    except OSError as err:
        return _import_preflight_failure(
            "apkg_export_media_path_invalid",
            f"无法核验可信导出的媒体目录，已停止写入 Anki：{err}",
        )

    try:
        apkg_stat = apkg_path.stat()
        actual_sha256 = file_sha256(apkg_path)
    except OSError as err:
        return _import_preflight_failure(
            "apkg_read_failed",
            f"无法读取可信导出的 APKG，已停止写入 Anki：{err}",
        )

    expected_sha256 = export_result.get("apkg_sha256")
    expected_size_bytes = _strict_export_int(export_result.get("apkg_size_bytes"))
    if not isinstance(expected_sha256, str) or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None:
        return _import_preflight_failure(
            "apkg_export_digest_invalid",
            "可信导出结果缺少规范的 APKG SHA-256，已停止写入 Anki。",
        )
    if expected_size_bytes is None or expected_size_bytes < 0:
        return _import_preflight_failure(
            "apkg_export_size_invalid",
            "可信导出结果缺少规范的 APKG 文件大小，已停止写入 Anki。",
        )
    if actual_sha256 != expected_sha256 or apkg_stat.st_size != expected_size_bytes:
        return _import_preflight_failure(
            "apkg_integrity_mismatch",
            "APKG 在导出后发生变化，文件哈希或大小与可信导出结果不一致，已停止写入 Anki。",
            expected_apkg_sha256=expected_sha256,
            actual_apkg_sha256=actual_sha256,
            expected_apkg_size_bytes=expected_size_bytes,
            actual_apkg_size_bytes=apkg_stat.st_size,
        )

    required_text_fields = (
        "template_family",
        "template_schema",
        "template_version",
        "model_name",
        "note_model_contract_digest",
    )
    for field in required_text_fields:
        value = export_result.get(field)
        if not isinstance(value, str) or not value or value != value.strip():
            return _import_preflight_failure(
                "apkg_export_contract_identity_invalid",
                f"可信导出结果中的 {field} 无效，已停止写入 Anki。",
                identity_field=field,
            )
    note_model_id = _strict_export_int(export_result.get("note_model_id"))
    compatibility_version = _strict_export_int(export_result.get("compatibility_contract_version"))
    contract_digest = export_result.get("note_model_contract_digest")
    if note_model_id is None or note_model_id <= 0:
        return _import_preflight_failure(
            "apkg_export_contract_identity_invalid",
            "可信导出结果中的 Note Model ID 无效，已停止写入 Anki。",
            identity_field="note_model_id",
        )
    if compatibility_version is None or compatibility_version <= 0:
        return _import_preflight_failure(
            "apkg_export_contract_identity_invalid",
            "可信导出结果中的合同版本无效，已停止写入 Anki。",
            identity_field="compatibility_contract_version",
        )
    if re.fullmatch(r"[0-9a-f]{64}", str(contract_digest)) is None:
        return _import_preflight_failure(
            "apkg_export_contract_identity_invalid",
            "可信导出结果中的 Note Model 合同摘要无效，已停止写入 Anki。",
            identity_field="note_model_contract_digest",
        )

    package_validator = getattr(
        apkg_package_contract_module,
        "validate_apkg_package_contract",
        None,
    )
    if not callable(package_validator):
        return _import_preflight_failure(
            "apkg_package_contract_validator_unavailable",
            "本机缺少完整 APKG 合同检查器，已停止写入 Anki。",
        )
    try:
        package_report = package_validator(apkg_path, export_result)
    except Exception:
        return _import_preflight_failure(
            "apkg_package_contract_unreadable",
            "无法完成 APKG 整包合同核验，已停止写入 Anki。",
        )
    package_issues = (
        package_report.get("issues")
        if isinstance(package_report, dict)
        else None
    )
    if (
        not isinstance(package_report, dict)
        or not package_report.get("ok")
        or not isinstance(package_issues, list)
        or package_issues
    ):
        issue_codes = sorted(
            {
                str(item.get("code") or "APKG_PACKAGE_CONTRACT_INVALID")
                for item in (package_issues or [])
                if isinstance(item, dict)
            }
        )
        return _import_preflight_failure(
            "apkg_package_contract_mismatch",
            "APKG 的卡片、牌组、模型、字段或媒体整包合同不一致，已停止写入 Anki。",
            apkg_package_contract_issue_codes=(
                issue_codes or ["APKG_PACKAGE_CONTRACT_INVALID"]
            ),
        )

    inspector = getattr(anki_model_contracts_module, "inspect_apkg_note_model_contract", None)
    if not callable(inspector):
        return _import_preflight_failure(
            "apkg_contract_inspector_unavailable",
            "本机缺少 APKG Note Model 合同检查器，已停止写入 Anki。",
        )
    try:
        contract_report = inspector(apkg_path)
    except Exception as err:
        return _import_preflight_failure(
            "apkg_note_model_contract_unreadable",
            f"无法证明 APKG 的 Note Model 合同，已停止写入 Anki：{err}",
        )
    if not isinstance(contract_report, dict):
        return _import_preflight_failure(
            "apkg_note_model_contract_unreadable",
            "APKG Note Model 合同检查结果无效，已停止写入 Anki。",
        )
    contract_issues = contract_report.get("issues")
    contracts = contract_report.get("contracts")
    if not isinstance(contract_issues, list) or contract_issues:
        return _import_preflight_failure(
            "apkg_note_model_contract_mismatch",
            "APKG 的 Note Model 合同不受支持或已被修改，已停止写入 Anki。",
            note_model_contract_issues=contract_issues if isinstance(contract_issues, list) else [],
        )
    if not isinstance(contracts, list) or len(contracts) != 1 or not isinstance(contracts[0], dict):
        return _import_preflight_failure(
            "apkg_note_model_contract_ambiguous",
            "APKG 必须且只能引用一个已验证的 Note Model 合同，已停止写入 Anki。",
        )

    contract = contracts[0]
    expected_contract_identity = {
        "templateFamily": export_result["template_family"],
        "templateSchema": export_result["template_schema"],
        "noteModelId": note_model_id,
        "modelName": export_result["model_name"],
        "compatibilityContractVersion": compatibility_version,
        "contractDigest": contract_digest,
    }
    mismatched_contract_fields = [
        field
        for field, expected in expected_contract_identity.items()
        if contract.get(field) != expected
    ]
    if export_result["template_version"] != export_result["template_schema"]:
        mismatched_contract_fields.append("templateVersion")
    if mismatched_contract_fields:
        return _import_preflight_failure(
            "apkg_note_model_contract_identity_mismatch",
            "APKG 的 Note Model 身份与可信导出结果不一致，已停止写入 Anki。",
            mismatched_contract_fields=sorted(set(mismatched_contract_fields)),
        )

    allowed_deck_kinds = _allowed_deck_kinds_for_contract_family(str(contract.get("templateFamily") or ""))
    if deck_kind not in allowed_deck_kinds:
        return _import_preflight_failure(
            "apkg_deck_kind_contract_mismatch",
            "APKG 的 Note Model 合同与可信导出卡片类型不一致，已停止写入 Anki。",
            deck_kind=deck_kind,
            template_family=contract.get("templateFamily"),
        )

    return {
        "ok": True,
        "message": "APKG 写入前合同、身份和完整性检查通过。",
        "failed_checks": [],
        "apkg_path": str(apkg_path),
        "apkg_sha256": actual_sha256,
        "apkg_size_bytes": apkg_stat.st_size,
        "apkg_mtime_ms": int(apkg_stat.st_mtime * 1000),
        "deck_name": deck_name,
        "deck_kind": deck_kind,
        "media_dir": str(export_result.get("media_dir") or ""),
        "cards": int(write_contract["cards"]),
        "media_manifest": dict(manifest),
        "media_files": media_count,
        "media_bytes": int(write_contract["media_bytes"]),
        "note_model_contract": dict(contract),
        "apkg_package_contract_summary": dict(
            package_report.get("summary")
            if isinstance(package_report.get("summary"), dict)
            else {}
        ),
    }


def revalidate_apkg_integrity_before_anki_write(
    apkg_path: Path,
    expected_sha256: str,
    expected_size_bytes: int,
) -> dict[str, Any]:
    try:
        stat = apkg_path.stat()
        actual_sha256 = file_sha256(apkg_path)
    except OSError as err:
        return _import_preflight_failure(
            "apkg_integrity_changed_before_import",
            f"APKG 在准备导入时已不可读，已停止写入 Anki：{err}",
        )
    if stat.st_size != expected_size_bytes or actual_sha256 != expected_sha256:
        return _import_preflight_failure(
            "apkg_integrity_changed_before_import",
            "APKG 在安全检查后、写入 Anki 前发生变化，已停止导入。",
            expected_apkg_sha256=expected_sha256,
            actual_apkg_sha256=actual_sha256,
            expected_apkg_size_bytes=expected_size_bytes,
            actual_apkg_size_bytes=stat.st_size,
        )
    return {"ok": True, "failed_checks": []}


def handle_verify_anki_import(payload: dict[str, Any]) -> dict[str, Any]:
    timing_started = time.perf_counter()
    timing_ms: dict[str, int] = {}
    import_skipped_existing = False
    import_existing_check: dict[str, Any] = {}

    def with_verify_timing(result: dict[str, Any]) -> dict[str, Any]:
        timing_ms["anki_verify"] = int((time.perf_counter() - timing_started) * 1000)
        timing_ms["total"] = timing_ms["anki_verify"]
        add_verify_anki_import_timing_aliases(timing_ms)
        enriched = {
            **result,
            "import_skipped_existing": bool(import_skipped_existing),
            "timing_ms": dict(timing_ms),
        }
        if import_existing_check:
            enriched["import_existing_check"] = dict(import_existing_check)
        return enriched

    export_result = payload.get("export_result") or {}
    if not isinstance(export_result, dict):
        export_result = {}
    import_attempted = bool(payload.get("import_apkg"))
    prepare_media_only = bool(payload.get("prepare_media_only"))
    anki_url = str(payload.get("anki_connect_url") or "http://127.0.0.1:8765").strip()

    import_preflight: dict[str, Any] | None = None
    if import_attempted or prepare_media_only:
        import_preflight = preflight_anki_import_apkg(payload, export_result)
        if not import_preflight.get("ok"):
            return with_verify_timing(
                {
                    **import_preflight,
                    "query": "",
                    "import_attempted": import_attempted,
                    "import_result": False,
                }
            )
        deck_name = str(import_preflight["deck_name"])
        deck_kind = str(import_preflight["deck_kind"])
        media_dir = Path(str(import_preflight["media_dir"]))
        apkg_path_text = str(import_preflight["apkg_path"])
        apkg_path = Path(apkg_path_text)
        apkg_sha256 = str(import_preflight["apkg_sha256"])
        apkg_size_bytes = int(import_preflight["apkg_size_bytes"])
        apkg_mtime_ms = int(import_preflight["apkg_mtime_ms"])
    else:
        deck_name = str(payload.get("deck_name") or export_result.get("deck_name") or "").strip()
        deck_kind = str(payload.get("deck_kind") or export_result.get("deck_kind") or "").strip()
        media_dir = Path(str(payload.get("media_dir") or export_result.get("media_dir") or ""))
        apkg_path_text = str(payload.get("apkg_path") or export_result.get("apkg_path") or "").strip()
        apkg_path = Path(apkg_path_text) if apkg_path_text else Path()
        apkg_sha256 = str(export_result.get("apkg_sha256") or "").strip()
        apkg_size_bytes = export_result.get("apkg_size_bytes")
        apkg_mtime_ms = export_result.get("apkg_mtime_ms")

    strict_video_import = deck_kind in {"video_language", "subtitle_language"}
    strict_document_import = deck_kind in {"document_knowledge", "document_reading"}
    source_identity = export_result.get("source_identity") if isinstance(export_result.get("source_identity"), dict) else {}
    source_fingerprint = str(source_identity.get("source_fingerprint") or export_result.get("source_fingerprint") or "").strip()
    if import_preflight is not None:
        expected_media_files = int(import_preflight["media_files"])
        expected_manifest = dict(import_preflight["media_manifest"])
        manifest_provided = True
    else:
        media_summary = (
            export_result.get("media_summary")
            if isinstance(export_result.get("media_summary"), dict)
            else {}
        )
        expected_media_files = media_summary.get("media_files")
        try:
            expected_media_files = int(expected_media_files) if expected_media_files is not None else None
        except (TypeError, ValueError):
            expected_media_files = None
        manifest_provided = isinstance(export_result.get("media_manifest"), dict)
        expected_manifest = export_result.get("media_manifest") if manifest_provided else {}
        if not expected_manifest and media_dir.exists() and expected_media_files != 0:
            expected_manifest = media_manifest([str(path) for path in media_dir.iterdir() if path.is_file()])
        if not expected_manifest and expected_media_files != 0:
            fail("缺少导出媒体清单，无法核验 Anki 媒体。")

    anki_tag = str(payload.get("anki_tag") or export_result.get("anki_tag") or "").strip()
    if not anki_tag:
        template_version = str(export_result.get("template_version") or "").strip().lower()
        anki_tag = f"anki_card_generator_{template_version}" if template_version else "anki_card_generator_v10"
    explicit_anki_query = (
        ""
        if import_preflight is not None
        else str(payload.get("anki_query") or export_result.get("anki_query") or "").strip()
    )
    query = explicit_anki_query or anki_import_preflight_query(deck_name, anki_tag)
    import_result: Any = None
    import_error = ""
    prepared_anki_media_dir: Path | None = None
    prepared_anki_media_identity: tuple[int, int] | None = None
    media_preload = {"missing": [], "already_present": [], "conflicts": [], "failures": []}
    media_recovery: dict[str, Any] = {
        "attempted": False,
        "restored": [],
        "restored_by": {},
        "failures": [],
        "ownership_ledger": [],
        "created": [],
        "already_present": [],
        "failed": [],
    }
    if import_attempted or prepare_media_only:
        emit_progress(
            "verify_anki_import",
            "prepare_media",
            5,
            "正在连接 Anki，并检查本次 APKG 的媒体落盘条件。",
        )
        preparation_started = time.perf_counter()
        try:
            prepared_anki_media_dir = wait_for_anki_media_directory(
                anki_url,
                payload.get("wait_for_anki_seconds") or 0,
            )
            prepared_anki_media_identity = _stable_anki_media_directory_identity(
                prepared_anki_media_dir
            )
        except Exception as err:
            timing_ms["anki_media_prepare"] = int((time.perf_counter() - preparation_started) * 1000)
            return with_verify_timing(
                {
                    "ok": False,
                    "message": f"无法连接 AnkiConnect 或读取媒体目录：{err}",
                    "failed_checks": ["anki_connect"],
                    "query": query,
                    "import_attempted": import_attempted,
                    "import_result": False,
                }
            )

        if prepared_anki_media_identity is None:
            timing_ms["anki_media_prepare"] = int((time.perf_counter() - preparation_started) * 1000)
            return with_verify_timing(
                {
                    "ok": False,
                    "message": "Anki 媒体目录包含链接/重解析点、不是普通目录或身份不稳定，已停止导入。",
                    "failed_checks": ["anki_media_preload_conflict"],
                    "query": query,
                    "import_attempted": import_attempted,
                    "import_result": False,
                    "media_preload_conflicts": [],
                    "media_preload_failures": [
                        {
                            "file": "",
                            "error": "Anki 媒体目录未通过稳定身份检查。",
                        }
                    ],
                }
            )

        media_preload = inspect_anki_media_for_preload(expected_manifest, prepared_anki_media_dir)
        preload_issues = [*media_preload["failures"], *media_preload["conflicts"]]
        if preload_issues:
            timing_ms["anki_media_prepare"] = int((time.perf_counter() - preparation_started) * 1000)
            return with_verify_timing(
                {
                    "ok": False,
                    "message": "Anki 媒体预置被安全阻止：存在不安全文件名、缺失哈希或同名内容冲突。",
                    "failed_checks": ["anki_media_preload_conflict"],
                    "query": query,
                    "import_attempted": import_attempted,
                    "import_result": False,
                    "media_preload_conflicts": media_preload["conflicts"],
                    "media_preload_failures": media_preload["failures"],
                }
            )

        media_recovery = restore_missing_anki_media(
            media_preload["missing"],
            expected_manifest,
            media_dir,
            prepared_anki_media_dir,
            anki_url,
            progress_label="正在为安全导入预置 Anki 媒体",
        )
        timing_ms["anki_media_prepare"] = int((time.perf_counter() - preparation_started) * 1000)
        if media_recovery["failures"]:
            source_integrity_failed = any(
                str(item.get("code") or "") == "source_integrity_failed"
                for item in media_recovery["failures"]
            )
            return with_verify_timing(
                {
                    "ok": False,
                    "message": (
                        "导出后的媒体内容与导出清单不一致，已停止导入，避免把被修改的媒体写入 Anki。"
                        if source_integrity_failed
                        else "无法在导入前安全预置全部媒体，已停止导入。"
                    ),
                    "failed_checks": [
                        (
                            "anki_media_source_integrity_failed"
                            if source_integrity_failed
                            else "anki_media_preload_failed"
                        )
                    ],
                    "query": query,
                    "import_attempted": import_attempted,
                    "import_result": False,
                    "media_recovery_attempted": media_recovery["attempted"],
                    "media_recovered_count": len(media_recovery["restored"]),
                    "media_recovered": media_recovery["restored"],
                    "media_recovery_methods": media_recovery["restored_by"],
                    "media_recovery_failures": media_recovery["failures"],
                    "media_recovery_ownership_ledger": media_recovery["ownership_ledger"],
                }
            )

        final_media_barrier = inspect_anki_media_for_preload(
            expected_manifest,
            prepared_anki_media_dir,
        )
        directory_identity_changed = (
            prepared_anki_media_identity is not None
            and _stable_anki_media_directory_identity(prepared_anki_media_dir)
            != prepared_anki_media_identity
        )
        if (
            directory_identity_changed
            or final_media_barrier["missing"]
            or final_media_barrier["conflicts"]
            or final_media_barrier["failures"]
        ):
            return with_verify_timing(
                {
                    "ok": False,
                    "message": "Anki 媒体最终写入闸门未闭合，已停止导入。",
                    "failed_checks": ["anki_media_final_barrier_failed"],
                    "query": query,
                    "import_attempted": import_attempted,
                    "import_result": False,
                    "media_recovery_attempted": media_recovery["attempted"],
                    "media_recovered_count": len(media_recovery["restored"]),
                    "media_recovered": media_recovery["restored"],
                    "media_recovery_methods": media_recovery["restored_by"],
                    "media_recovery_failures": media_recovery["failures"],
                    "media_recovery_ownership_ledger": media_recovery["ownership_ledger"],
                    "media_final_barrier": {
                        **final_media_barrier,
                        "directory_identity_changed": directory_identity_changed,
                    },
                }
            )

        if prepare_media_only:
            prepared_count = len(media_recovery["restored"])
            already_present_count = len(media_preload["already_present"])
            return with_verify_timing(
                {
                    "ok": True,
                    "message": (
                        f"Anki 安全导入准备完成：已预置 {prepared_count} 个媒体文件，"
                        f"{already_present_count} 个文件已存在且哈希一致。"
                    ),
                    "failed_checks": [],
                    "query": query,
                    "import_attempted": False,
                    "import_result": None,
                    "apkg_path": apkg_path_text,
                    "apkg_sha256": apkg_sha256,
                    "apkg_size_bytes": apkg_size_bytes,
                    "apkg_mtime_ms": apkg_mtime_ms,
                    "media_prepared_count": prepared_count,
                    "media_already_present_count": already_present_count,
                    "media_recovery_attempted": media_recovery["attempted"],
                    "media_recovered_count": prepared_count,
                    "media_recovered": media_recovery["restored"],
                    "media_recovery_methods": media_recovery["restored_by"],
                    "media_recovery_failures": media_recovery["failures"],
                    "media_recovery_ownership_ledger": media_recovery["ownership_ledger"],
                }
            )

    if import_attempted:
        emit_progress(
            "verify_anki_import",
            "import_preflight",
            52,
            "正在确认当前 APKG 是否已完整导入，避免重复写入。",
        )
        import_preflight_started = time.perf_counter()
        expected_cards_for_preflight = int(export_result.get("cards") or payload.get("expected_cards") or 0)
        import_existing_check = inspect_existing_anki_import(
            export_result,
            deck_name=deck_name,
            anki_tag=anki_tag,
            expected_cards=expected_cards_for_preflight,
            anki_url=anki_url,
        )
        timing_ms["anki_import_preflight"] = int((time.perf_counter() - import_preflight_started) * 1000)
        import_skipped_existing = bool(import_existing_check.get("complete"))

        if import_skipped_existing:
            emit_progress(
                "verify_anki_import",
                "import_preflight",
                55,
                "当前 APKG 已完整存在，已跳过重复导入，继续执行完整核验。",
            )
        else:
            integrity_recheck = revalidate_apkg_integrity_before_anki_write(
                apkg_path,
                apkg_sha256,
                int(apkg_size_bytes),
            )
            if not integrity_recheck.get("ok"):
                return with_verify_timing(
                    {
                        **integrity_recheck,
                        "query": query,
                        "import_attempted": True,
                        "import_result": False,
                    }
                )
            immediate_media_barrier = inspect_anki_media_for_preload(
                expected_manifest,
                prepared_anki_media_dir,
            )
            immediate_directory_identity_changed = (
                prepared_anki_media_identity is not None
                and _stable_anki_media_directory_identity(prepared_anki_media_dir)
                != prepared_anki_media_identity
            )
            if (
                immediate_directory_identity_changed
                or immediate_media_barrier["missing"]
                or immediate_media_barrier["conflicts"]
                or immediate_media_barrier["failures"]
                or media_recovery["failures"]
            ):
                return with_verify_timing(
                    {
                        "ok": False,
                        "message": "导入前的最终媒体完整性复核未通过，已停止写入 Anki。",
                        "failed_checks": ["anki_media_final_barrier_failed"],
                        "query": query,
                        "import_attempted": True,
                        "import_result": False,
                        "media_recovered_count": len(media_recovery["restored"]),
                        "media_recovered": media_recovery["restored"],
                        "media_recovery_methods": media_recovery["restored_by"],
                        "media_recovery_failures": media_recovery["failures"],
                        "media_recovery_ownership_ledger": media_recovery["ownership_ledger"],
                        "media_final_barrier": {
                            **immediate_media_barrier,
                            "directory_identity_changed": immediate_directory_identity_changed,
                        },
                    }
                )
            emit_progress(
                "verify_anki_import",
                "import",
                55,
                "媒体已安全预置，正在通过 AnkiConnect 导入当前 APKG。",
            )
            import_started = time.perf_counter()
            try:
                import_result = anki_connect("importPackage", {"path": str(apkg_path)}, anki_url)
            except Exception as err:
                import_error = str(err)
                timing_ms["anki_import"] = int((time.perf_counter() - import_started) * 1000)
                return with_verify_timing(
                    {
                        "ok": False,
                        "message": f"AnkiConnect 导入 APKG 失败：{import_error}",
                        "failed_checks": ["anki_import_failed"],
                        "query": query,
                        "import_attempted": True,
                        "import_result": False,
                        "import_error": import_error,
                    }
                )
            timing_ms["anki_import"] = int((time.perf_counter() - import_started) * 1000)
            if import_result is False:
                return with_verify_timing(
                    {
                        "ok": False,
                        "message": "AnkiConnect 没有成功导入 APKG。",
                        "failed_checks": ["anki_import_failed"],
                        "query": query,
                        "import_attempted": True,
                        "import_result": False,
                    }
                )

    query_started = time.perf_counter()
    try:
        emit_progress(
            "verify_anki_import",
            "query",
            anki_verify_query_progress_percent(import_attempted),
            "正在读取 Anki 中的卡片、字段和媒体目录。",
        )
        card_ids = anki_connect("findCards", {"query": query}, anki_url)
        card_infos = anki_connect("cardsInfo", {"cards": card_ids or []}, anki_url) if card_ids else []
        anki_media_dir = prepared_anki_media_dir or Path(str(anki_connect("getMediaDirPath", {}, anki_url) or ""))
    except Exception as err:
        timing_ms["anki_query"] = int((time.perf_counter() - query_started) * 1000)
        return with_verify_timing(
            {
                "ok": False,
                "message": f"无法连接 AnkiConnect 或读取卡片：{err}",
                "failed_checks": ["anki_connect"],
                "query": query,
                "import_attempted": import_attempted,
                "import_result": import_result,
            }
        )
    timing_ms["anki_query"] = int((time.perf_counter() - query_started) * 1000)

    referenced_media: set[str] = set()
    card_ids_seen: set[int] = set()
    deck_names_seen: set[str] = set()
    model_names: set[str] = set()
    missing_video_field_media: list[dict[str, Any]] = []
    empty_required_fields: list[dict[str, Any]] = []
    corrupted_study_text_values: list[dict[str, str]] = []
    pronunciation_meta_errors: list[dict[str, str]] = []
    imported_tts_text_hash_mismatch: list[dict[str, str]] = []
    card_media_ledger = export_result.get("card_media_ledger") if isinstance(export_result.get("card_media_ledger"), list) else []
    card_media_ledger_provided = isinstance(export_result.get("card_media_ledger"), list)
    card_media_by_card_id = items_by_card_id(card_media_ledger)
    audio_audit_items, audio_audit_export_summary = load_audio_audit_from_export_result(export_result)
    if strict_video_import and not audio_audit_items and card_media_ledger:
        audio_audit_items = build_audio_audit_items(
            card_media_ledger,
            expected_manifest,
            deck_name=deck_name,
            model_name=str(export_result.get("model_name") or ""),
            deck_kind=deck_kind,
        )
        audio_audit_export_summary = audio_audit_summary(
            audio_audit_items,
            deck_kind=deck_kind,
            expected_items=int(export_result.get("cards") or payload.get("expected_cards") or 0),
        )
    audio_audit_by_card_id = items_by_card_id(audio_audit_items)
    audio_audit_verify_items: list[dict[str, Any]] = []
    audio_audit_mismatches: list[dict[str, Any]] = []
    card_media_ledger_mismatches: list[dict[str, Any]] = []
    matched_export_card_ids: set[str] = set()
    seen_export_card_ids: set[str] = set()
    duplicate_imported_cards: list[dict[str, str]] = []
    for info in card_infos or []:
        card_id = str(info.get("cardId") or "")
        try:
            card_ids_seen.add(int(info.get("cardId")))
        except Exception:
            pass
        model_name = anki_card_model_name(info)
        if model_name:
            model_names.add(model_name)
        imported_deck_name = anki_card_deck_name(info)
        if imported_deck_name:
            deck_names_seen.add(imported_deck_name)
        fields = info.get("fields") or {}
        for field_name in ["Video", "Audio", "TtsAudio", "PhraseTtsAudio"]:
            referenced_media.update(extract_media_references(anki_field_value(fields, field_name)))
        if strict_video_import:
            refs_by_field = {
                field_name: extract_media_references(anki_field_value(fields, field_name))
                for field_name in ["Video", "Audio", "TtsAudio", "PhraseTtsAudio"]
            }
            export_card_id = anki_field_plain_text(fields, "CardId")
            matches_current_export = bool(
                export_card_id and (export_card_id in card_media_by_card_id or export_card_id in audio_audit_by_card_id)
            )
            duplicate_current_export = False
            if matches_current_export:
                if export_card_id in seen_export_card_ids:
                    duplicate_current_export = True
                    duplicate_imported_cards.append({"card_id": export_card_id, "anki_card_id": card_id})
                else:
                    seen_export_card_ids.add(export_card_id)
                    matched_export_card_ids.add(export_card_id)
            card_media = card_media_by_card_id.get(export_card_id)
            if card_media_ledger_provided and export_card_id and card_media:
                card_media_ledger_mismatches.extend(
                    compare_expected_media_refs_by_field(
                        export_card_id,
                        refs_by_field,
                        card_media_expected_refs_by_field(card_media),
                    )
                )
            elif card_media_ledger_provided and export_card_id:
                card_media_ledger_mismatches.append(
                    missing_expected_entry_mismatch(export_card_id, "card_media_ledger entry")
                )
            audit_item = audio_audit_by_card_id.get(export_card_id)
            if export_card_id and audit_item:
                verified_audit = dict(audit_item)
                note_id = info.get("note") or info.get("noteId") or info.get("note_id")
                if note_id:
                    verified_audit["anki_note_id"] = note_id
                verified_audit["anki_card_id"] = card_id
                verified_audit["anki_fields"] = refs_by_field
                referenced_names = sorted(
                    {
                        Path(ref).name
                        for refs in refs_by_field.values()
                        for ref in refs
                        if str(ref).strip()
                    }
                )
                verified_audit["anki_media_exists"] = {
                    name: imported_media_exists_for_audit(anki_media_dir / name)
                    for name in referenced_names
                }
                audio_audit_mismatches.extend(
                    compare_expected_media_refs_by_field(
                        export_card_id,
                        refs_by_field,
                        audio_audit_expected_refs_by_field(audit_item),
                    )
                )
                sentence_actual, text_mismatches = audio_audit_imported_text_mismatches(
                    export_card_id,
                    audit_item,
                    fields,
                )
                verified_audit["anki_card_display_sentence"] = sentence_actual
                audio_audit_mismatches.extend(text_mismatches)
                if not duplicate_current_export:
                    audio_audit_verify_items.append(verified_audit)
            elif strict_video_import and export_card_id:
                audio_audit_mismatches.append(
                    missing_expected_entry_mismatch(export_card_id, "audio_audit entry")
                )
            missing_roles = missing_video_required_media_roles(refs_by_field)
            if missing_roles:
                missing_video_field_media.append(
                    {
                        "card_id": card_id,
                        "missing": missing_roles,
                    }
                )

            missing_text = missing_video_required_text_fields(fields)
            if missing_text:
                empty_required_fields.append({"card_id": card_id, "missing": missing_text})

            corrupted_study_text_values.extend(imported_corrupted_study_text_values(fields, card_id))

            pronunciation_error = anki_import_pronunciation_meta_error(fields)
            if pronunciation_error:
                pronunciation_meta_errors.append({"card_id": card_id, "error": pronunciation_error})

            imported_tts_text_hash_mismatch.extend(
                imported_tts_text_hash_mismatches(fields, card_id, refs_by_field, media_text_hash)
            )
        if strict_document_import:
            missing_text = missing_document_required_text_fields(fields)
            if missing_text:
                empty_required_fields.append({"card_id": card_id, "missing": missing_text})

    expected_names = set(expected_manifest)
    media_ledger = export_result.get("media_ledger") if isinstance(export_result.get("media_ledger"), list) else []
    ledger_manifest_check = media_ledger_manifest_consistency(media_ledger, expected_manifest)
    ledger_missing_manifest = ledger_manifest_check["ledger_missing_manifest"]
    manifest_tts_without_ledger = ledger_manifest_check["manifest_tts_without_ledger"]
    ledger_text_hash_mismatch = ledger_manifest_check["ledger_text_hash_mismatch"]
    media_ledger_card_text_mismatches = media_ledger_card_text_mismatches_core(card_media_ledger, media_ledger)
    expected_referenced_manifest = {
        name: expected_manifest[name]
        for name in sorted(expected_names & referenced_media)
    }
    tts_manual_items = tts_manual_review_items(expected_referenced_manifest)
    tts_semantic_failures = tts_semantic_failure_items(expected_referenced_manifest)
    tts_semantic_summary = tts_semantic_verification_summary(tts_manual_items, expected_referenced_manifest)
    manifest_check = compare_media_manifest(expected_referenced_manifest, anki_media_dir, anki_url=anki_url, max_attempts=1)
    if import_attempted and manifest_check["missing"]:
        recovery_started = time.perf_counter()
        post_import_recovery = restore_missing_anki_media(
            manifest_check["missing"],
            expected_referenced_manifest,
            media_dir,
            anki_media_dir,
            anki_url,
            progress_start_percent=70,
            progress_span_percent=10,
        )
        media_recovery = merge_anki_media_recovery(media_recovery, post_import_recovery)
        timing_ms["anki_media_recovery"] = int((time.perf_counter() - recovery_started) * 1000)
        manifest_check = compare_media_manifest(
            expected_referenced_manifest,
            anki_media_dir,
            anki_url=anki_url,
            max_attempts=3,
        )
        for audit_item in audio_audit_verify_items:
            imported_media = audit_item.get("anki_media_exists")
            if not isinstance(imported_media, dict):
                continue
            audit_item["anki_media_exists"] = {
                name: imported_media_exists_for_audit(anki_media_dir / name)
                for name in imported_media
            }
    tts_audio_duration_issues = imported_tts_audio_duration_issues(
        expected_referenced_manifest,
        anki_media_dir,
        referenced_media,
        strict_video_import=strict_video_import,
        anki_url=anki_url,
        max_attempts=1,
    )
    unreferenced_expected = sorted(expected_names - referenced_media)
    unexpected_references = sorted(referenced_media - expected_names)
    expected_cards = int(export_result.get("cards") or payload.get("expected_cards") or 0)
    audio_audit_verified_items = audio_audit_verify_items if audio_audit_verify_items else audio_audit_items
    audio_audit_verified_summary = audio_audit_summary(
        audio_audit_verified_items,
        deck_kind=deck_kind,
        expected_items=expected_cards if strict_video_import else 0,
    )
    audio_audit_verify_path = ""
    audio_audit_verify_markdown_path = ""
    audio_audit_write_errors: list[str] = []
    if strict_video_import or audio_audit_items:
        audit_output_root = None
        if str(export_result.get("audio_audit_path") or "").strip():
            audit_output_root = Path(str(export_result.get("audio_audit_path"))).parent
        elif media_dir:
            audit_output_root = media_dir.parent
        else:
            audit_output_root = Path.cwd()
        try:
            verify_json_path, verify_markdown_path = write_audio_audit_files(
                audit_output_root,
                audio_audit_verified_items,
                {
                    **audio_audit_verified_summary,
                    "export_summary": audio_audit_export_summary,
                    "mismatches": len(audio_audit_mismatches),
                },
                base_name="audio_audit.verify",
            )
            audio_audit_verify_path = str(verify_json_path)
            audio_audit_verify_markdown_path = str(verify_markdown_path)
            audio_audit_verified_summary["verify_path"] = audio_audit_verify_path
        except OSError as err:
            audio_audit_write_errors.append(str(err))
    sorted_model_names = sorted(model_names)
    sorted_deck_names = sorted(deck_names_seen)
    template_mismatches = imported_model_template_mismatches(
        sorted_model_names,
        strict_video_import=strict_video_import,
        strict_document_import=strict_document_import,
    )
    ciba_model_names = template_mismatches["ciba_model_names"]
    video_template_mismatches = template_mismatches["video_template_mismatches"]
    document_template_mismatches = template_mismatches["document_template_mismatches"]
    if strict_video_import and (card_media_by_card_id or audio_audit_by_card_id):
        verified_card_count = len(matched_export_card_ids)
    else:
        verified_card_count = len(card_ids_seen)

    # Public builds do not use ASR as a mandatory quality gate. Preserve the
    # diagnostic summary for old exports, but do not fail Anki verify unless a
    # future caller explicitly re-enables the ASR gate in this command payload.
    failed_checks = verify_anki_import_failed_checks(
        card_infos_present=bool(card_infos),
        strict_video_import=strict_video_import,
        strict_document_import=strict_document_import,
        sorted_model_names=sorted_model_names,
        video_template_mismatches=video_template_mismatches,
        ciba_model_names=ciba_model_names,
        document_template_mismatches=document_template_mismatches,
        expected_cards=expected_cards,
        verified_card_count=verified_card_count,
        card_media_ledger_provided=card_media_ledger_provided,
        card_media_ledger_count=len(card_media_ledger),
        audio_audit_count=len(audio_audit_items),
        audio_audit_mismatches=audio_audit_mismatches,
        audio_audit_write_errors=audio_audit_write_errors,
        card_media_ledger_mismatches=card_media_ledger_mismatches,
        missing_video_field_media=missing_video_field_media,
        empty_required_fields=empty_required_fields,
        corrupted_study_text_values=corrupted_study_text_values,
        pronunciation_meta_errors=pronunciation_meta_errors,
        imported_tts_text_hash_mismatch=imported_tts_text_hash_mismatch,
        unreferenced_expected=unreferenced_expected,
        unexpected_references=unexpected_references,
        manifest_missing=manifest_check["missing"],
        manifest_mismatched=manifest_check["mismatched"],
        manifest_inaccessible=manifest_check.get("inaccessible", []),
        tts_audio_duration_issues=tts_audio_duration_issues,
        tts_semantic_failures=tts_semantic_failures,
        tts_semantic_export_required=tts_semantic_requires_export_pass(payload, deck_kind),
        ledger_missing_manifest=ledger_missing_manifest,
        manifest_tts_without_ledger=manifest_tts_without_ledger,
        ledger_text_hash_mismatch=ledger_text_hash_mismatch,
        media_ledger_card_text_mismatches=media_ledger_card_text_mismatches,
    )
    if media_recovery["failures"] and "anki_media_recovery_failed" not in failed_checks:
        failed_checks.append("anki_media_recovery_failed")
    message = verify_anki_import_message(
        failed_checks,
        duplicate_imported_cards=duplicate_imported_cards,
        tts_manual_items=tts_manual_items,
    )
    if not failed_checks and media_recovery["restored"]:
        message = f"{message} 已在导入前安全预置或补齐 {len(media_recovery['restored'])} 个媒体文件。"
    if import_skipped_existing:
        message = f"{message} 当前 APKG 已完整存在，已跳过重复导入。"

    return with_verify_timing(
        {
            "ok": not failed_checks,
            "message": message,
            "failed_checks": failed_checks,
            "query": query,
            "import_attempted": import_attempted,
            "import_result": import_result,
            "import_error": import_error or None,
            "apkg_path": apkg_path_text or None,
            "apkg_sha256": apkg_sha256 or None,
            "apkg_size_bytes": apkg_size_bytes,
            "apkg_mtime_ms": apkg_mtime_ms,
            "source_identity": dict(source_identity) if source_identity else None,
            "source_fingerprint": source_fingerprint or None,
            "deck_name": deck_name,
            "deck_kind": deck_kind or None,
            "deck_names_seen": sorted_deck_names,
            "model_names": sorted_model_names,
            "ciba_model_names": ciba_model_names,
            "video_template_mismatches": video_template_mismatches,
            "document_template_mismatches": document_template_mismatches,
            "card_count": verified_card_count,
            "expected_cards": expected_cards or None,
            "imported_card_count": len(card_ids_seen),
            "duplicate_imported_card_count": len(duplicate_imported_cards),
            "duplicate_imported_cards": duplicate_imported_cards,
            "card_media_ledger_count": len(card_media_ledger) if card_media_ledger_provided else None,
            "card_media_ledger_mismatches": card_media_ledger_mismatches,
            "missing_video_field_media": missing_video_field_media,
            "empty_required_fields": empty_required_fields,
            "corrupted_study_text_values": corrupted_study_text_values,
            "pronunciation_meta_errors": pronunciation_meta_errors,
            "imported_tts_text_hash_mismatch": imported_tts_text_hash_mismatch,
            "media_count_expected": len(expected_manifest),
            "media_count_referenced": len(referenced_media),
            "media_count_checked": manifest_check["checked"],
            "media_recovery_attempted": media_recovery["attempted"],
            "media_recovered_count": len(media_recovery["restored"]),
            "media_recovered": media_recovery["restored"],
            "media_recovery_methods": media_recovery["restored_by"],
            "media_recovery_failures": media_recovery["failures"],
            "media_recovery_ownership_ledger": media_recovery["ownership_ledger"],
            "media_already_present_count": len(media_preload["already_present"]),
            "media_preload_conflicts": media_preload["conflicts"],
            "media_preload_failures": media_preload["failures"],
            "missing_media": manifest_check["missing"],
            "mismatched_media": manifest_check["mismatched"],
            "inaccessible_media": manifest_check.get("inaccessible", []),
            "imported_tts_audio_duration_issues": tts_audio_duration_issues,
            "tts_manual_review_items": tts_manual_items,
            "tts_semantic_failures": tts_semantic_failures,
            "tts_semantic_verification": tts_semantic_summary,
            "audio_audit_verify_path": audio_audit_verify_path or None,
            "audio_audit_verify_markdown_path": audio_audit_verify_markdown_path or None,
            "audio_audit_mismatches": audio_audit_mismatches,
            "audio_audit_write_errors": audio_audit_write_errors,
            "audio_audit_summary": audio_audit_verified_summary,
            "unexpected_media_references": unexpected_references,
            "unreferenced_expected_media": unreferenced_expected,
            "ledger_missing_manifest": ledger_missing_manifest,
            "manifest_tts_without_ledger": manifest_tts_without_ledger,
            "ledger_text_hash_mismatch": ledger_text_hash_mismatch,
            "media_ledger_card_text_mismatches": media_ledger_card_text_mismatches,
            "anki_media_dir": str(anki_media_dir),
        }
    )


def package_version(name: str) -> str:
    try:
        from importlib import metadata

        return metadata.version(name)
    except Exception:
        return ""


def check_anki_connect() -> tuple[bool, str]:
    try:
        response = http_json(
            "http://127.0.0.1:8765",
            {},
            {"action": "version", "version": 6, "params": {}},
            timeout=2,
            max_response_bytes=ANKI_CONNECT_SMALL_RESPONSE_MAX_BYTES,
        )
        version = response.get("result")
        return True, f"AnkiConnect {version}" if version else "AnkiConnect 可用"
    except Exception as err:
        return False, str(err)


def anki_executable_candidates() -> list[Path]:
    candidates: list[Path] = []
    env_path = str(os.environ.get("ANKI_EXE") or "").strip().strip('"').strip("'")
    if env_path:
        candidates.append(Path(env_path))

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        base = Path(local_app_data)
        candidates.extend(
            [
                base / "AnkiProgramFiles" / ".venv" / "Scripts" / "ankiw.exe",
                base / "AnkiProgramFiles" / ".venv" / "Scripts" / "anki.exe",
                base / "Programs" / "Anki" / "anki.exe",
            ]
        )

    program_files = [os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")]
    for root in program_files:
        if root:
            candidates.append(Path(root) / "Anki" / "anki.exe")

    which_anki = shutil.which("anki")
    if which_anki:
        candidates.append(Path(which_anki))

    seen: set[str] = set()
    unique: list[Path] = []
    for candidate in candidates:
        key = str(candidate).lower()
        if key and key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def is_anki_executable_name(path: Path) -> bool:
    return path.name.lower() in {"anki.exe", "ankiw.exe"}


def find_anki_executable() -> str:
    for candidate in anki_executable_candidates():
        try:
            if candidate.exists():
                return str(candidate)
        except PermissionError:
            if is_anki_executable_name(candidate):
                return str(candidate)
        except OSError:
            continue
    return ""


def is_process_running(image_name: str) -> bool:
    if os.name == "nt":
        try:
            completed = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {image_name}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                **hidden_subprocess_flags(),
            )
            if completed.returncode == 0 and image_name.lower() in completed.stdout.lower():
                return True
        except Exception:
            pass
        try:
            process_name = Path(image_name).stem.replace("'", "''")
            completed = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-Command",
                    f"Get-Process -Name '{process_name}' -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Id",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                **hidden_subprocess_flags(),
            )
            return completed.returncode == 0 and bool(completed.stdout.strip())
        except Exception:
            return False
    try:
        completed = subprocess.run(
            ["pgrep", "-f", image_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            **hidden_subprocess_flags(),
        )
        return completed.returncode == 0 and bool(completed.stdout.strip())
    except Exception:
        return False


def check_anki_desktop() -> dict[str, Any]:
    anki_path = find_anki_executable()
    anki_installed = bool(anki_path)
    anki_running = (
        is_process_running("anki.exe") or is_process_running("ankiw.exe")
        if os.name == "nt"
        else is_process_running("anki")
    )
    if anki_installed and anki_running:
        detail = f"已安装并正在运行：{anki_path}"
    elif anki_installed:
        detail = f"已安装但未打开：{anki_path}"
    else:
        detail = "未找到 Anki 桌面端；无法直连导入或安装 AnkiConnect。"
    return {
        "anki_installed": anki_installed,
        "anki_path": anki_path,
        "anki_running": anki_running,
        "detail": detail,
    }


def handle_check_env(_: dict[str, Any]) -> dict[str, Any]:
    try:
        import genanki  # noqa: F401

        genanki_ready = True
    except ImportError:
        genanki_ready = False
    yt_dlp_command = yt_dlp_base_command()
    yt_dlp_version = ""
    if yt_dlp_command:
        completed = subprocess.run(
            [*yt_dlp_command, "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **hidden_subprocess_flags(),
        )
        if completed.returncode == 0:
            yt_dlp_version = completed.stdout.strip()

    ffmpeg_path = ""
    ffmpeg_version = ""
    try:
        ffmpeg_path = str(media_managed_tool_path("ffmpeg"))
        completed = media_tool_version("ffmpeg", timeout=10)
        if completed.returncode == 0:
            ffmpeg_version = (completed.stdout.splitlines() or [""])[0]
    except (MediaToolPolicyError, subprocess.TimeoutExpired):
        ffmpeg_path = ""
    js_runtime = "deno" if shutil.which("deno") else ("node" if shutil.which("node") else "")
    anki_status = check_anki_desktop()
    anki_connect_ready, anki_connect_detail = check_anki_connect()
    venv_ready = ".venv" in str(Path(sys.executable).resolve()).lower()
    packages = {
        "genanki": package_version("genanki"),
        "yt-dlp": package_version("yt-dlp"),
        "pypdf": package_version("pypdf"),
        "cryptography": package_version("cryptography"),
        "curl-cffi": package_version("curl_cffi") or package_version("curl-cffi"),
    }
    status_items = [
        {
            "id": "python",
            "label": "Python worker",
            "status": "ok",
            "detail": f"{sys.version.split()[0]} · {sys.executable}",
            "fix": "",
        },
        {
            "id": "venv",
            "label": "项目私有 venv",
            "status": "ok" if venv_ready else "action",
            "detail": "正在使用项目 .venv" if venv_ready else "当前没有使用项目 .venv，发布包建议先运行 setup_runtime.ps1。",
            "fix": "运行 scripts/setup_runtime.ps1",
        },
        {
            "id": "ffmpeg",
            "label": "FFmpeg 视频切片",
            "status": "ok" if ffmpeg_path else "blocked",
            "detail": ffmpeg_version or "未在 PATH 找到 ffmpeg；本地视频导出会失败。",
            "fix": "安装 FFmpeg 并加入 PATH，或运行 scripts/setup_runtime.ps1 -InstallWithWinget",
        },
        {
            "id": "genanki",
            "label": "genanki APKG 导出",
            "status": "ok" if genanki_ready else "blocked",
            "detail": packages.get("genanki") or "缺少 genanki。",
            "fix": "运行 scripts/setup_runtime.ps1",
        },
        {
            "id": "yt_dlp",
            "label": "yt-dlp URL 导入",
            "status": "ok" if yt_dlp_command else "action",
            "detail": yt_dlp_version or "缺少 yt-dlp；URL 导入不可用，但本地 SRT/文档仍可用。",
            "fix": "运行 scripts/setup_runtime.ps1",
        },
        {
            "id": "js_runtime",
            "label": "Deno / Node challenge solver",
            "status": "ok" if js_runtime else "action",
            "detail": js_runtime or "YouTube n challenge 可能失败。",
            "fix": "安装 Deno 2.0+ 或 Node.js 20+。",
        },
        {
            "id": "anki",
            "label": "Anki 桌面端",
            "status": "ok" if anki_status["anki_installed"] else "blocked",
            "detail": anki_status["detail"],
            "fix": "安装 Anki，或设置 ANKI_EXE 指向 anki.exe。" if not anki_status["anki_installed"] else "打开 Anki 后重新检查。",
        },
        {
            "id": "anki_connect",
            "label": "AnkiConnect 导入核验",
            "status": "ok" if anki_connect_ready else ("blocked" if not anki_status["anki_installed"] else "action"),
            "detail": (
                anki_connect_detail
                if anki_connect_ready
                else (
                    "需要先安装 Anki 桌面端。"
                    if not anki_status["anki_installed"]
                    else (
                        "Anki 已安装但未打开；打开 Anki 后才能连接 AnkiConnect。"
                        if not anki_status["anki_running"]
                        else "Anki 已打开，但 AnkiConnect 插件未连接或未安装。"
                    )
                )
            ),
            "fix": (
                "先安装 Anki。"
                if not anki_status["anki_installed"]
                else (
                    "打开 Anki 后重新检查。"
                    if not anki_status["anki_running"]
                    else "安装/启用 AnkiConnect 插件，代码 2055492159。"
                )
            ),
        },
    ]

    return {
        "python": sys.version.split()[0],
        "python_executable": sys.executable,
        "venv": venv_ready,
        "ffmpeg": bool(ffmpeg_path),
        "ffmpeg_path": "managed:ffmpeg" if ffmpeg_path and os.environ.get("ACG_MANAGED_RUNTIME") == "1" else ffmpeg_path,
        "ffmpeg_version": ffmpeg_version,
        "genanki": genanki_ready,
        "yt_dlp": bool(yt_dlp_command),
        "yt_dlp_version": yt_dlp_version,
        "yt_dlp_js_runtime": js_runtime,
        "anki_installed": anki_status["anki_installed"],
        "anki_path": anki_status["anki_path"],
        "anki_running": anki_status["anki_running"],
        "anki_connect": anki_connect_ready,
        "anki_connect_detail": anki_connect_detail,
        "packages": packages,
        "status_items": status_items,
        "worker": str(Path(__file__).resolve()),
    }


def repair_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def summarize_repair_output(completed: subprocess.CompletedProcess[str]) -> str:
    output = "\n".join([completed.stdout or "", completed.stderr or ""]).strip()
    output = output.replace("\r\n", "\n").replace("\r", "\n")
    if not output:
        return f"退出码 {completed.returncode}"
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return "\n".join(lines[-8:])[:1200]


def run_repair_step(
    action_id: str,
    label: str,
    command: list[str],
    *,
    timeout: int = 600,
    next_step: str = "",
) -> dict[str, Any]:
    emit_progress("repair_env", action_id, 20, f"正在修复：{label}")
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            **hidden_subprocess_flags(),
        )
    except subprocess.TimeoutExpired:
        return {
            "id": action_id,
            "label": label,
            "status": "failed",
            "detail": f"修复超时，超过 {timeout} 秒没有完成。",
            "command": " ".join(command),
            "next_step": next_step,
        }
    except Exception as err:
        return {
            "id": action_id,
            "label": label,
            "status": "failed",
            "detail": f"无法执行修复命令：{err}",
            "command": " ".join(command),
            "next_step": next_step,
        }
    return {
        "id": action_id,
        "label": label,
        "status": "success" if completed.returncode == 0 else "failed",
        "detail": summarize_repair_output(completed),
        "command": " ".join(command),
        "next_step": "" if completed.returncode == 0 else next_step,
    }


def launch_anki_desktop(anki_path: str) -> tuple[bool, str]:
    if not anki_path:
        return False, "未找到 anki.exe。"
    try:
        if os.name == "nt" and hasattr(os, "startfile"):
            os.startfile(anki_path)  # type: ignore[attr-defined]
            return True, f"已尝试打开 Anki：{anki_path}"
        subprocess.Popen([anki_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **hidden_subprocess_flags())
        return True, f"已尝试打开 Anki：{anki_path}"
    except Exception as err:
        return False, f"无法打开 Anki：{err}"


def handle_repair_env(payload: dict[str, Any]) -> dict[str, Any]:
    target = str(payload.get("target") or "auto")
    if target not in {"all", "auto", "python_packages", "ffmpeg", "js_runtime", "anki", "anki_connect"}:
        target = "auto"
    root = repair_project_root()
    requirements = root / "workers" / "requirements.txt"
    venv_python = root / ".venv" / "Scripts" / "python.exe"
    actions: list[dict[str, Any]] = []

    emit_progress("repair_env", "start", 5, "正在准备环境修复。")

    needs_python_repair = (
        not venv_python.exists()
        or not package_version("genanki")
        or not yt_dlp_base_command()
    )
    if target in {"auto", "python_packages"} or (target == "all" and needs_python_repair):
        if not venv_python.exists():
            actions.append(
                run_repair_step(
                    "venv",
                    "创建项目 Python venv",
                    [sys.executable, "-m", "venv", str(root / ".venv")],
                    timeout=300,
                    next_step="如果创建失败，请确认已安装 Python 3.11+，并重新运行 scripts/setup_runtime.ps1。",
                )
            )
        else:
            actions.append(
                {
                    "id": "venv",
                    "label": "项目 Python venv",
                    "status": "skipped",
                    "detail": f"已存在：{venv_python}",
                    "next_step": "",
                }
            )

        installer_python = str(venv_python if venv_python.exists() else Path(sys.executable))
        actions.append(
            run_repair_step(
                "pip",
                "升级 pip",
                [installer_python, "-m", "pip", "install", "--upgrade", "pip"],
                timeout=300,
                next_step="如果 pip 升级失败，请检查网络代理，或手动运行 scripts/setup_runtime.ps1。",
            )
        )
        actions.append(
            run_repair_step(
                "python_packages",
                "安装/更新 worker Python 依赖",
                [installer_python, "-m", "pip", "install", "--upgrade", "-r", str(requirements)],
                timeout=900,
                next_step="如果依赖安装失败，请检查网络代理，或手动运行 scripts/setup_runtime.ps1。",
                )
            )

    elif target == "all":
        actions.append(
            {
                "id": "python_packages",
                "label": "Python worker 依赖",
                "status": "skipped",
                "detail": "项目 venv、genanki 和 yt-dlp 已经可用。",
                "next_step": "",
            }
        )

    if target in {"all", "ffmpeg"}:
        if shutil.which("ffmpeg"):
            actions.append(
                {
                    "id": "ffmpeg",
                    "label": "FFmpeg",
                    "status": "skipped",
                    "detail": "FFmpeg 已经在 PATH 中。",
                    "next_step": "",
                }
            )
        else:
            winget = shutil.which("winget")
            if not winget:
                actions.append(
                    {
                        "id": "ffmpeg",
                        "label": "安装 FFmpeg",
                        "status": "manual",
                        "detail": "本机没有 winget，无法自动安装 FFmpeg。",
                        "next_step": "请从 https://www.gyan.dev/ffmpeg/builds/ 下载 FFmpeg，并把 bin 目录加入 PATH。",
                    }
                )
            else:
                actions.append(
                    run_repair_step(
                        "ffmpeg",
                        "通过 winget 安装 FFmpeg",
                        [
                            winget,
                            "install",
                            "--id",
                            "Gyan.FFmpeg",
                            "-e",
                            "--accept-package-agreements",
                            "--accept-source-agreements",
                        ],
                        timeout=1200,
                        next_step="安装后请重启应用或重新打开终端，让 PATH 生效；如果失败，请手动安装 FFmpeg。",
                    )
                )

    if target in {"all", "js_runtime"}:
        if shutil.which("deno") or shutil.which("node"):
            actions.append(
                {
                    "id": "js_runtime",
                    "label": "Deno / Node",
                    "status": "skipped",
                    "detail": "已经检测到 Deno 或 Node。",
                    "next_step": "",
                }
            )
        else:
            winget = shutil.which("winget")
            if not winget:
                actions.append(
                    {
                        "id": "js_runtime",
                        "label": "安装 Deno",
                        "status": "manual",
                        "detail": "本机没有 winget，无法自动安装 Deno。",
                        "next_step": "请安装 Deno 2.0+ 或 Node.js 20+，并加入 PATH。",
                    }
                )
            else:
                actions.append(
                    run_repair_step(
                        "js_runtime",
                        "通过 winget 安装 Deno",
                        [winget, "install", "--id", "DenoLand.Deno", "-e", "--accept-package-agreements", "--accept-source-agreements"],
                        timeout=900,
                        next_step="安装后请重启应用或重新打开终端，让 PATH 生效。",
                    )
                )

    if target in {"all", "anki"}:
        anki_path = find_anki_executable()
        if anki_path:
            actions.append(
                {
                    "id": "anki",
                    "label": "Anki 桌面端",
                    "status": "skipped",
                    "detail": f"已找到：{anki_path}",
                    "next_step": "",
                }
            )
        else:
            winget = shutil.which("winget")
            if not winget:
                actions.append(
                    {
                        "id": "anki",
                        "label": "安装 Anki 桌面端",
                        "status": "manual",
                        "detail": "本机没有 winget，无法自动安装 Anki。",
                        "next_step": "请从 https://apps.ankiweb.net/ 下载并安装 Anki，或设置 ANKI_EXE 指向 anki.exe。",
                    }
                )
            else:
                actions.append(
                    run_repair_step(
                        "anki",
                        "通过 winget 安装 Anki",
                        [
                            winget,
                            "install",
                            "--id",
                            "Anki.Anki",
                            "-e",
                            "--accept-package-agreements",
                            "--accept-source-agreements",
                        ],
                        timeout=1200,
                        next_step="安装后请重新打开应用，或设置 ANKI_EXE 指向 anki.exe。",
                    )
                )

    if target in {"all", "anki_connect"}:
        anki_connect_ready, _ = check_anki_connect()
        anki_path = find_anki_executable()
        if anki_connect_ready:
            actions.append(
                {
                    "id": "anki_connect",
                    "label": "AnkiConnect",
                    "status": "skipped",
                    "detail": "AnkiConnect 已经可用。",
                    "next_step": "",
                }
            )
        elif not anki_path:
            actions.append(
                {
                    "id": "anki_connect",
                    "label": "AnkiConnect",
                    "status": "manual",
                    "detail": "还没有找到 Anki 桌面端，暂时不能配置 AnkiConnect。",
                    "next_step": "先安装 Anki，再打开 Anki → 工具 → 插件 → 获取插件 → 输入代码 2055492159。",
                }
            )
        else:
            if not (is_process_running("anki.exe") if os.name == "nt" else is_process_running("anki")):
                launched, detail = launch_anki_desktop(anki_path)
                actions.append(
                    {
                        "id": "anki_launch",
                        "label": "打开 Anki 桌面端",
                        "status": "success" if launched else "failed",
                        "detail": detail,
                        "next_step": "" if launched else "请手动打开 Anki 后继续安装插件。",
                    }
                )
            actions.append(
                {
                    "id": "anki_connect",
                    "label": "安装/启用 AnkiConnect",
                    "status": "manual",
                    "detail": "AnkiConnect 需要在 Anki 内确认安装，应用不能静默替你安装插件。",
                    "next_step": "Anki 打开后：工具 → 插件 → 获取插件 → 输入代码 2055492159 → 确认安装 → 重启 Anki → 回到这里重新检查。",
                }
            )

    ok = all(action["status"] in {"success", "skipped", "manual"} for action in actions)
    failed = sum(1 for action in actions if action["status"] == "failed")
    manual = sum(1 for action in actions if action["status"] == "manual")
    emit_progress("repair_env", "done", 100, "环境修复步骤已完成，正在等待复检。")
    return {
        "ok": ok and failed == 0,
        "target": target,
        "summary": f"已执行 {len(actions)} 个修复步骤；失败 {failed} 个，需手动处理 {manual} 个。",
        "actions": actions,
    }


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    payload = read_payload()

    if command == "check_env":
        emit(handle_check_env(payload))
    elif command == "test_api":
        emit(handle_test_api(payload))
    elif command == "test_tts":
        emit(handle_test_tts(payload))
    elif command == "generate":
        emit(handle_generate(payload))
    elif command == "export":
        emit(handle_export(payload))
    elif command == "verify_anki_import":
        emit(handle_verify_anki_import(payload))
    else:
        fail(f"未知 worker 命令：{command}")


if __name__ == "__main__":
    main()
