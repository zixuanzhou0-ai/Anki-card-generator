from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from acg.cache_identity import stable_cache_key

CARD_GENERATION_PROMPT_VERSION = 2


def card_generation_cache_path(
    payload: dict[str, Any],
    segments: list[dict[str, Any]],
    requested_card_types: list[str],
    *,
    cache_root: Path,
    provider_name: str,
    normalized_language: str,
    normalized_level_mode: str,
    normalized_review_density: str,
) -> tuple[Path, str]:
    api = payload.get("api_config") or {}
    cache_namespace = str(payload.get("card_generation_cache_namespace") or api.get("card_generation_cache_namespace") or "").strip()
    cache_key_payload: dict[str, Any] = {
        "version": CARD_GENERATION_PROMPT_VERSION,
        "kind": "selected_learning_point_card_generation",
        "provider": provider_name,
        "base_url": str(api.get("base_url") or "").strip().rstrip("/"),
        "model": str(api.get("model") or "").strip(),
        "language": normalized_language,
        "level_mode": normalized_level_mode,
        "level": str(payload.get("level") or "B1"),
        "template_id": str(payload.get("template_id") or "immersive_v11"),
        "review_density": normalized_review_density,
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
    if cache_namespace:
        cache_key_payload["cache_namespace"] = cache_namespace
    cache_key = stable_cache_key(cache_key_payload)
    return cache_root / "card_generation" / f"{cache_key}.json", cache_key


def ai_payload_has_usable_cards(ai_payload: dict[str, Any] | None) -> bool:
    if not isinstance(ai_payload, dict):
        return False
    for segment in ai_payload.get("segments") or []:
        if not isinstance(segment, dict):
            continue
        for card in segment.get("cards", []) or []:
            if not isinstance(card, dict):
                continue
            if card.get("phrase") or card.get("chinese") or card.get("definition"):
                return True
    return False


def load_card_generation_cache(cache_path: Path) -> dict[str, Any] | None:
    if not cache_path.exists() or cache_path.stat().st_size <= 0:
        return None
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    payload = cached.get("payload") if isinstance(cached, dict) else None
    if ai_payload_has_usable_cards(payload):
        return payload
    return None


def store_card_generation_cache(cache_path: Path, cache_key: str, ai_payload: dict[str, Any]) -> None:
    if ai_payload.get("error") or not ai_payload_has_usable_cards(ai_payload):
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


def single_card_generation_cache_paths(
    payload: dict[str, Any],
    segments: list[dict[str, Any]],
    requested_card_types: list[str],
    *,
    cache_root: Path,
    provider_name: str,
    normalized_language: str,
    normalized_level_mode: str,
    normalized_review_density: str,
) -> dict[str, tuple[Path, str]]:
    paths: dict[str, tuple[Path, str]] = {}
    for segment in segments:
        segment_id = str(segment.get("id") or "")
        if not segment_id:
            continue
        paths[segment_id] = card_generation_cache_path(
            payload,
            [segment],
            requested_card_types,
            cache_root=cache_root,
            provider_name=provider_name,
            normalized_language=normalized_language,
            normalized_level_mode=normalized_level_mode,
            normalized_review_density=normalized_review_density,
        )
    return paths


def card_generation_cache_disabled(payload: dict[str, Any], api: dict[str, Any], field: str) -> bool:
    legacy_disabled = bool(payload.get("disable_card_generation_cache") or api.get("disable_card_generation_cache"))
    return legacy_disabled or bool(payload.get(field) or api.get(field))


def card_generation_cache_policy(payload: dict[str, Any]) -> tuple[bool, bool]:
    api = payload.get("api_config") or {}
    read_enabled = not card_generation_cache_disabled(payload, api, "disable_card_generation_cache_read")
    write_enabled = not card_generation_cache_disabled(payload, api, "disable_card_generation_cache_write")
    return read_enabled, write_enabled


def source_fingerprint(payload: dict[str, Any], source_info: dict[str, Any] | None = None) -> str:
    source_info = source_info or {}
    return stable_cache_key(
        {
            "source_mode": str(payload.get("source_mode") or ""),
            "source_url": str(payload.get("source_url") or ""),
            "url_import_mode": str(payload.get("url_import_mode") or ""),
            "video_path": str(payload.get("video_path") or source_info.get("video_path") or ""),
            "subtitle_path": str(payload.get("subtitle_path") or source_info.get("subtitle_path") or ""),
            "document_path": str(payload.get("document_path") or ""),
            "title": str(payload.get("title") or source_info.get("title") or ""),
        }
    )
