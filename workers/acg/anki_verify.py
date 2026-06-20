from __future__ import annotations

from typing import Any


def verify_anki_import_failed_checks(
    *,
    card_infos_present: bool,
    strict_video_import: bool,
    strict_document_import: bool,
    sorted_model_names: list[str],
    video_template_mismatches: list[str],
    ciba_model_names: list[str],
    document_template_mismatches: list[str],
    expected_cards: int,
    verified_card_count: int,
    card_media_ledger_provided: bool,
    card_media_ledger_count: int,
    audio_audit_count: int,
    audio_audit_mismatches: list[Any],
    audio_audit_write_errors: list[Any],
    card_media_ledger_mismatches: list[Any],
    missing_video_field_media: list[Any],
    empty_required_fields: list[Any],
    corrupted_study_text_values: list[Any],
    pronunciation_meta_errors: list[Any],
    imported_tts_text_hash_mismatch: list[Any],
    unreferenced_expected: list[Any],
    unexpected_references: list[Any],
    manifest_missing: list[Any],
    manifest_mismatched: list[Any],
    manifest_inaccessible: list[Any],
    tts_audio_duration_issues: list[Any],
    tts_semantic_failures: list[Any],
    tts_semantic_export_required: bool,
    ledger_missing_manifest: list[Any],
    manifest_tts_without_ledger: list[Any],
    ledger_text_hash_mismatch: list[Any],
    media_ledger_card_text_mismatches: list[Any],
) -> list[str]:
    failed_checks: list[str] = []
    if not card_infos_present:
        failed_checks.append("no_imported_cards")
    if (strict_video_import or strict_document_import) and card_infos_present and not sorted_model_names:
        failed_checks.append("imported_model_missing")
    if strict_video_import and video_template_mismatches:
        failed_checks.append("video_template_mismatch")
    if strict_video_import and ciba_model_names:
        failed_checks.append("ordinary_flow_ciba_template")
    if strict_document_import and document_template_mismatches:
        failed_checks.append("document_template_mismatch")
    if expected_cards and verified_card_count != expected_cards:
        failed_checks.append("card_count_mismatch")
    if card_media_ledger_provided and expected_cards and card_media_ledger_count != expected_cards:
        failed_checks.append("card_media_ledger_count_mismatch")
    if strict_video_import and expected_cards and audio_audit_count != expected_cards:
        failed_checks.append("audio_audit_count_mismatch")
    if audio_audit_mismatches:
        failed_checks.append("audio_audit_mismatch")
    if audio_audit_write_errors:
        failed_checks.append("audio_audit_write_failed")
    if card_media_ledger_mismatches:
        failed_checks.append("card_media_ledger_mismatch")
    if missing_video_field_media:
        failed_checks.append("missing_imported_video_field_media")
    if empty_required_fields:
        failed_checks.append("empty_imported_required_fields")
    if corrupted_study_text_values:
        failed_checks.append("corrupted_imported_study_text")
    if pronunciation_meta_errors:
        failed_checks.append("pronunciation_meta_parse_errors")
    if imported_tts_text_hash_mismatch:
        failed_checks.append("imported_tts_text_hash_mismatch")
    if unreferenced_expected:
        failed_checks.append("unreferenced_expected_media")
    if unexpected_references:
        failed_checks.append("unexpected_media_references")
    if manifest_missing:
        failed_checks.append("missing_imported_media")
    if manifest_mismatched:
        failed_checks.append("media_hash_mismatch")
    if manifest_inaccessible:
        failed_checks.append("inaccessible_imported_media")
    if tts_audio_duration_issues:
        failed_checks.append("imported_tts_audio_duration")
    if tts_semantic_failures and tts_semantic_export_required:
        failed_checks.append("tts_semantic_mismatch")
    if ledger_missing_manifest:
        failed_checks.append("ledger_missing_manifest")
    if manifest_tts_without_ledger:
        failed_checks.append("manifest_tts_without_ledger")
    if ledger_text_hash_mismatch:
        failed_checks.append("ledger_text_hash_mismatch")
    if media_ledger_card_text_mismatches:
        failed_checks.append("media_ledger_card_text_mismatch")
    return failed_checks


def verify_anki_import_message(
    failed_checks: list[str],
    *,
    duplicate_imported_cards: list[Any],
    tts_manual_items: list[Any],
) -> str:
    if failed_checks:
        return "Anki 导入媒体核验发现问题。"
    if duplicate_imported_cards:
        return (
            "Anki 导入媒体核验通过；检测到同名 deck 里已有旧导入，"
            "已按本次 audio_audit 匹配到的卡片核验。"
        )
    if tts_manual_items:
        return "Anki 导入媒体核验通过；TTS 语义仍需按清单人工抽查。"
    return "Anki 导入媒体核验通过。"
