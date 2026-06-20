from __future__ import annotations

from typing import Any

GENERATION_TIMING_ALIASES = {
    "source_prepare_ms": "source_prepare",
    "card_body_ms": "card_model",
    "field_merge_ms": "field_merge",
    "total_ms": "total",
}

LEARNING_POINT_EXTRACTION_TIMING_ALIASES = {
    "source_prepare_ms": "source_prepare",
    "learning_point_extract_ms": "learning_point_extract",
    "ai_review_ms": "ai_review",
    "total_ms": "total",
}

EXPORT_TIMING_ALIASES = {
    "source_prepare_ms": "source_prepare",
    "tts_ms": "tts",
    "media_slice_ms": "media",
    "apkg_pack_ms": "apkg_packaging",
    "total_ms": "total",
}

VERIFY_ANKI_IMPORT_TIMING_ALIASES = {
    "anki_verify_ms": "anki_verify",
    "total_ms": "total",
}


def _coerce_timing_ms(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _add_timing_aliases(timing_ms: dict[str, Any], aliases: dict[str, str]) -> dict[str, Any]:
    for alias, source_key in aliases.items():
        if source_key in timing_ms and alias not in timing_ms:
            timing_ms[alias] = _coerce_timing_ms(timing_ms.get(source_key))
    return timing_ms


def add_generation_timing_aliases(timing_ms: dict[str, Any]) -> dict[str, Any]:
    return _add_timing_aliases(timing_ms, GENERATION_TIMING_ALIASES)


def add_learning_point_extraction_timing_aliases(timing_ms: dict[str, Any]) -> dict[str, Any]:
    return _add_timing_aliases(timing_ms, LEARNING_POINT_EXTRACTION_TIMING_ALIASES)


def add_export_timing_aliases(timing_ms: dict[str, Any]) -> dict[str, Any]:
    return _add_timing_aliases(timing_ms, EXPORT_TIMING_ALIASES)


def add_verify_anki_import_timing_aliases(timing_ms: dict[str, Any]) -> dict[str, Any]:
    return _add_timing_aliases(timing_ms, VERIFY_ANKI_IMPORT_TIMING_ALIASES)
