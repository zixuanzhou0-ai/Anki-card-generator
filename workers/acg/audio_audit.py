from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from acg.anki_fields import anki_field_plain_text
from acg.media_alignment import media_subtitle_alignment_blocks_export, media_subtitle_alignment_failure_reason
from acg.text_cleaning import clean_study_text
from acg.tts_text import clean_tts_input_text


def optional_tts_text(value: Any) -> str:
    raw = str(value or "").strip()
    return clean_tts_input_text(raw) if raw else ""


def media_text_hash(value: Any) -> str:
    text = optional_tts_text(value).lower()
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12] if text else ""


def unique_clean_strings(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def audio_audit_manifest_entry(manifest: dict[str, dict[str, Any]], file_name: Any) -> dict[str, Any]:
    name = Path(str(file_name or "")).name
    entry = manifest.get(name) if name else None
    return entry if isinstance(entry, dict) else {}


def audio_audit_role_hashes(card_media: dict[str, Any], manifest: dict[str, dict[str, Any]]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for field in [
        "video_webm",
        "video_mp4",
        "poster",
        "original_audio",
        "sentence_tts_audio",
        "phrase_tts_audio",
    ]:
        name = Path(str(card_media.get(field) or "")).name
        if not name:
            continue
        sha = str(audio_audit_manifest_entry(manifest, name).get("sha256") or "")
        if sha:
            hashes[field] = sha
    return hashes


def audio_audit_tts_hashes(card_media: dict[str, Any], manifest: dict[str, dict[str, Any]]) -> dict[str, str]:
    sentence_entry = audio_audit_manifest_entry(manifest, card_media.get("sentence_tts_audio"))
    phrase_entry = audio_audit_manifest_entry(manifest, card_media.get("phrase_tts_audio"))
    hashes: dict[str, str] = {}
    sentence_hash = str(sentence_entry.get("text_hash") or media_text_hash(card_media.get("sentence_tts_text")))
    phrase_hash = str(phrase_entry.get("text_hash") or media_text_hash(card_media.get("phrase_tts_text")))
    if sentence_hash:
        hashes["sentence_tts"] = sentence_hash
    if phrase_hash:
        hashes["phrase_tts"] = phrase_hash
    return hashes


def audio_audit_reasons_for_file(manifest: dict[str, dict[str, Any]], file_name: Any) -> list[str]:
    entry = audio_audit_manifest_entry(manifest, file_name)
    reasons = entry.get("semantic_review_reasons")
    return [str(reason) for reason in reasons] if isinstance(reasons, list) else []


def items_by_card_id(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("card_id") or ""): item
        for item in items
        if isinstance(item, dict) and str(item.get("card_id") or "").strip()
    }


def card_media_expected_refs_by_field(card_media: dict[str, Any]) -> dict[str, list[str]]:
    return {
        "Video": [
            str(card_media.get("video_webm") or ""),
            str(card_media.get("video_mp4") or ""),
            str(card_media.get("poster") or ""),
        ],
        "Audio": [str(card_media.get("original_audio") or "")],
        "TtsAudio": [str(card_media.get("sentence_tts_audio") or "")],
        "PhraseTtsAudio": [str(card_media.get("phrase_tts_audio") or "")],
    }


def audio_audit_expected_refs_by_field(audit_item: dict[str, Any]) -> dict[str, list[str]]:
    return {
        "Video": [
            str(audit_item.get("video_webm") or ""),
            str(audit_item.get("video_mp4") or ""),
            str(audit_item.get("poster") or ""),
        ],
        "Audio": [str(audit_item.get("original_audio") or "")],
        "TtsAudio": [str(audit_item.get("sentence_tts_file") or "")],
        "PhraseTtsAudio": [str(audit_item.get("phrase_tts_file") or "")],
    }


def compare_expected_media_refs_by_field(
    card_id: str,
    refs_by_field: dict[str, list[str]],
    expected_refs_by_field: dict[str, list[str]],
) -> list[dict[str, Any]]:
    mismatches: list[dict[str, Any]] = []
    for field_name, expected_refs in expected_refs_by_field.items():
        expected_names = sorted(Path(ref).name for ref in expected_refs if str(ref).strip())
        if not expected_names:
            continue
        actual_names = sorted(Path(ref).name for ref in refs_by_field.get(field_name, []))
        missing_expected = [name for name in expected_names if name not in actual_names]
        unexpected_actual = [name for name in actual_names if name not in expected_names]
        if missing_expected or unexpected_actual:
            mismatches.append(
                {
                    "card_id": card_id,
                    "field": field_name,
                    "expected": expected_names,
                    "actual": actual_names,
                    "missing_expected": missing_expected,
                    "unexpected_actual": unexpected_actual,
                }
            )
    return mismatches


def missing_expected_entry_mismatch(card_id: str, entry_label: str) -> dict[str, Any]:
    return {
        "card_id": card_id,
        "field": "CardId",
        "expected": [entry_label],
        "actual": [],
        "missing_expected": [entry_label],
        "unexpected_actual": [],
    }


def audio_audit_imported_text_mismatches(
    card_id: str,
    audit_item: dict[str, Any],
    fields: dict[str, Any],
) -> tuple[str, list[dict[str, Any]]]:
    mismatches: list[dict[str, Any]] = []
    sentence_expected = optional_tts_text(audit_item.get("sentence_tts_expected_text"))
    sentence_actual = optional_tts_text(anki_field_plain_text(fields, "English"))
    card_display_expected = optional_tts_text(audit_item.get("card_display_sentence"))
    if (
        card_display_expected
        and sentence_actual
        and media_text_hash(card_display_expected) != media_text_hash(sentence_actual)
    ):
        mismatches.append(
            {
                "card_id": card_id,
                "field": "CardDisplaySentence",
                "expected_text_hash": media_text_hash(card_display_expected),
                "actual_text_hash": media_text_hash(sentence_actual),
            }
        )
    if media_subtitle_alignment_blocks_export(audit_item, audit_item):
        mismatches.append(
            {
                "card_id": card_id,
                "field": "MediaSubtitleAlignment",
                "status": str(audit_item.get("media_subtitle_alignment_status") or ""),
                "score": audit_item.get("media_subtitle_overlap_score"),
                "reason": media_subtitle_alignment_failure_reason(audit_item, audit_item),
                "media_subtitle_time": str(audit_item.get("media_subtitle_time") or ""),
                "media_window_subtitle_text": str(audit_item.get("media_window_subtitle_text") or ""),
            }
        )
    if sentence_expected and sentence_actual and media_text_hash(sentence_expected) != media_text_hash(sentence_actual):
        mismatches.append(
            {
                "card_id": card_id,
                "field": "English",
                "expected_text_hash": media_text_hash(sentence_expected),
                "actual_text_hash": media_text_hash(sentence_actual),
            }
        )
    phrase_expected = optional_tts_text(audit_item.get("phrase_tts_expected_text"))
    phrase_actual = optional_tts_text(
        anki_field_plain_text(fields, "Answer") or anki_field_plain_text(fields, "Phrase")
    )
    if phrase_expected and phrase_actual and media_text_hash(phrase_expected) != media_text_hash(phrase_actual):
        mismatches.append(
            {
                "card_id": card_id,
                "field": "AnswerOrPhrase",
                "expected_text_hash": media_text_hash(phrase_expected),
                "actual_text_hash": media_text_hash(phrase_actual),
            }
        )
    return sentence_actual, mismatches


def build_audio_audit_items(
    card_media_ledger: list[dict[str, Any]],
    manifest: dict[str, dict[str, Any]],
    *,
    deck_name: str,
    model_name: str,
    deck_kind: str,
) -> list[dict[str, Any]]:
    if deck_kind not in {"video_language", "subtitle_language"}:
        return []
    items: list[dict[str, Any]] = []
    for card_media in card_media_ledger:
        if not isinstance(card_media, dict):
            continue
        sentence_file = Path(str(card_media.get("sentence_tts_audio") or "")).name
        phrase_file = Path(str(card_media.get("phrase_tts_audio") or "")).name
        sentence_entry = audio_audit_manifest_entry(manifest, sentence_file)
        phrase_entry = audio_audit_manifest_entry(manifest, phrase_file)
        sentence_reasons = audio_audit_reasons_for_file(manifest, sentence_file)
        phrase_reasons = audio_audit_reasons_for_file(manifest, phrase_file)
        media_subtitle_text = clean_study_text(card_media.get("media_window_subtitle_text") or "")
        media_subtitle_score = card_media.get("media_subtitle_overlap_score")
        item = {
            "card_id": str(card_media.get("card_id") or ""),
            "learning_point_id": str(card_media.get("learning_point_id") or ""),
            "segment_id": str(card_media.get("segment_id") or ""),
            "source_mode": str(card_media.get("source_mode") or ""),
            "source_title": str(card_media.get("source_title") or ""),
            "source_url": str(card_media.get("source_url") or ""),
            "url_import_mode": str(card_media.get("url_import_mode") or ""),
            "source_download_mode": str(card_media.get("source_download_mode") or ""),
            "source_transcript_only": card_media.get("source_transcript_only"),
            "source_skip_video_slicing": card_media.get("source_skip_video_slicing"),
            "source_video_path": str(card_media.get("source_video_path") or ""),
            "source_video_fingerprint": str(card_media.get("source_video_fingerprint") or ""),
            "source_video_sha256": str(card_media.get("source_video_sha256") or ""),
            "source_subtitle_path": str(card_media.get("source_subtitle_path") or ""),
            "source_subtitle_fingerprint": str(card_media.get("source_subtitle_fingerprint") or ""),
            "source_subtitle_sha256": str(card_media.get("source_subtitle_sha256") or ""),
            "source_subtitle_status": str(card_media.get("source_subtitle_status") or ""),
            "source_fingerprint": str(card_media.get("source_fingerprint") or ""),
            "source_time": str(card_media.get("source_time") or ""),
            "media_start": card_media.get("media_start"),
            "media_end": card_media.get("media_end"),
            "media_source_time": str(card_media.get("media_source_time") or card_media.get("source_time") or ""),
            "source_cue_ids": card_media.get("source_cue_ids") or [],
            "source_cue_count": card_media.get("source_cue_count"),
            "source_cue_start": card_media.get("source_cue_start"),
            "source_cue_end": card_media.get("source_cue_end"),
            "source_cue_time": str(card_media.get("source_cue_time") or ""),
            "source_cue_texts": card_media.get("source_cue_texts") or [],
            "source_merge_reason": str(card_media.get("source_merge_reason") or ""),
            "source_sentence_quality_flags": card_media.get("source_sentence_quality_flags") or [],
            "source_sentence_quality_status": str(card_media.get("source_sentence_quality_status") or ""),
            "media_alignment_status": str(card_media.get("media_alignment_status") or ""),
            "media_alignment_text": clean_study_text(card_media.get("media_alignment_text") or ""),
            "media_alignment_source_text": clean_study_text(card_media.get("media_alignment_source_text") or ""),
            "media_subtitle_alignment_status": str(card_media.get("media_subtitle_alignment_status") or ""),
            "media_subtitle_alignment_reason": str(card_media.get("media_subtitle_alignment_reason") or ""),
            "media_subtitle_overlap_score": card_media.get("media_subtitle_overlap_score"),
            "media_alignment_score": media_subtitle_score,
            "media_subtitle_time": str(card_media.get("media_subtitle_time") or ""),
            "media_subtitle_cue_count": card_media.get("media_subtitle_cue_count"),
            "media_window_subtitle_text": media_subtitle_text,
            "media_subtitle_text": media_subtitle_text,
            "subtitle_path": str(card_media.get("subtitle_path") or ""),
            "card_display_sentence": clean_study_text(
                card_media.get("card_display_sentence") or card_media.get("sentence_tts_text") or ""
            ),
            "source_sentence": clean_study_text(card_media.get("sentence_tts_text") or ""),
            "visible_answer": clean_study_text(card_media.get("answer") or card_media.get("phrase_tts_text") or ""),
            "sentence_tts_expected_text": optional_tts_text(card_media.get("sentence_tts_text")),
            "phrase_tts_expected_text": optional_tts_text(card_media.get("phrase_tts_text")),
            "video_webm": Path(str(card_media.get("video_webm") or "")).name,
            "video_mp4": Path(str(card_media.get("video_mp4") or "")).name,
            "poster": Path(str(card_media.get("poster") or "")).name,
            "original_audio": Path(str(card_media.get("original_audio") or "")).name,
            "sentence_tts_file": sentence_file,
            "phrase_tts_file": phrase_file,
            "sentence_tts_asr_transcript": str(
                sentence_entry.get("asr_transcript")
                or card_media.get("sentence_tts_asr_transcript")
                or ""
            ),
            "phrase_tts_asr_transcript": str(
                phrase_entry.get("asr_transcript")
                or card_media.get("phrase_tts_asr_transcript")
                or ""
            ),
            "sentence_tts_semantic_verification": str(
                sentence_entry.get("semantic_verification")
                or card_media.get("sentence_tts_semantic_verification")
                or ""
            ),
            "phrase_tts_semantic_verification": str(
                phrase_entry.get("semantic_verification")
                or card_media.get("phrase_tts_semantic_verification")
                or ""
            ),
            "sentence_tts_semantic_review_reasons": sentence_reasons,
            "phrase_tts_semantic_review_reasons": phrase_reasons,
            "semantic_review_reasons": unique_clean_strings(sentence_reasons + phrase_reasons),
            "media_hashes": audio_audit_role_hashes(card_media, manifest),
            "tts_text_hashes": audio_audit_tts_hashes(card_media, manifest),
            "deck": deck_name,
            "model": model_name,
            "template": str(card_media.get("template_label") or ""),
        }
        items.append({key: value for key, value in item.items() if value not in (None, "", [], {})})
    return items


def audio_audit_summary(
    items: list[dict[str, Any]],
    *,
    deck_kind: str,
    expected_items: int = 0,
) -> dict[str, Any]:
    if deck_kind not in {"video_language", "subtitle_language"}:
        return {
            "status": "not_applicable",
            "items": 0,
            "expected_items": 0,
            "passed": 0,
            "failed": 0,
            "manual_review_required": 0,
            "mismatches": 0,
        }
    statuses: list[str] = []
    for item in items:
        for key in ("sentence_tts_semantic_verification", "phrase_tts_semantic_verification"):
            status = str(item.get(key) or "").strip()
            if status:
                statuses.append(status)
    failed = sum(1 for status in statuses if status == "mismatch")
    manual = sum(1 for status in statuses if status == "manual_review_required")
    passed = sum(1 for status in statuses if status == "passed")
    media_subtitle_statuses = [
        str(item.get("media_subtitle_alignment_status") or "").strip()
        for item in items
        if str(item.get("media_subtitle_alignment_status") or "").strip()
    ]
    media_subtitle_summary = {
        "matched": sum(1 for item_status in media_subtitle_statuses if item_status == "matched"),
        "partial": sum(1 for item_status in media_subtitle_statuses if item_status == "partial"),
        "mismatch": sum(1 for item_status in media_subtitle_statuses if item_status == "mismatch"),
        "unknown": sum(1 for item_status in media_subtitle_statuses if item_status == "unknown"),
    }
    source_sentence_quality_statuses = [
        str(item.get("source_sentence_quality_status") or "").strip()
        for item in items
        if str(item.get("source_sentence_quality_status") or "").strip()
    ]
    source_sentence_quality_summary = {
        "clean": sum(1 for item_status in source_sentence_quality_statuses if item_status == "clean"),
        "needs_review": sum(1 for item_status in source_sentence_quality_statuses if item_status == "needs_review"),
        "unknown": max(0, len(items) - len(source_sentence_quality_statuses)),
    }
    missing_items = max(0, int(expected_items or 0) - len(items))
    status = "passed"
    if failed or missing_items:
        status = "mismatch"
    elif manual:
        status = "manual_review_required"
    elif not statuses:
        status = "manual_review_required" if items else "not_applicable"
    return {
        "status": status,
        "items": len(items),
        "expected_items": int(expected_items or len(items)),
        "passed": passed,
        "failed": failed,
        "manual_review_required": manual,
        "mismatches": failed + missing_items,
        "media_subtitle_alignment": media_subtitle_summary,
        "source_sentence_quality": source_sentence_quality_summary,
    }


def audio_audit_markdown(items: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    lines = [
        "# Audio Audit",
        "",
        f"- Status: {summary.get('status')}",
        f"- Items: {summary.get('items', 0)}/{summary.get('expected_items', 0)}",
        f"- TTS passed: {summary.get('passed', 0)}",
        f"- TTS failed: {summary.get('failed', 0)}",
        f"- TTS manual review: {summary.get('manual_review_required', 0)}",
        f"- Media/subtitle alignment: {summary.get('media_subtitle_alignment', {})}",
        f"- Source sentence quality: {summary.get('source_sentence_quality', {})}",
        "",
    ]
    for index, item in enumerate(items, start=1):
        lines.extend(
            [
                f"## {index}. {item.get('visible_answer') or item.get('card_id')}",
                "",
                f"- CardId: `{item.get('card_id', '')}`",
                f"- LearningPointId: `{item.get('learning_point_id', '')}`",
                f"- SourceTime: {item.get('source_time', '')}",
                f"- MediaStart/End: {item.get('media_start', '')} - {item.get('media_end', '')}",
                f"- MediaSourceTime: {item.get('media_source_time', '')}",
                f"- Media alignment: {item.get('media_alignment_status', '')}",
                f"- Media subtitle status: {item.get('media_subtitle_alignment_status', '')} ({item.get('media_alignment_score', item.get('media_subtitle_overlap_score', ''))})",
                f"- Media subtitle time: {item.get('media_subtitle_time', '')}",
                f"- Media subtitle text: {item.get('media_subtitle_text') or item.get('media_window_subtitle_text', '')}",
                f"- Card display sentence: {item.get('card_display_sentence', '')}",
                f"- Sentence expected: {item.get('sentence_tts_expected_text', '')}",
                f"- Sentence ASR: {item.get('sentence_tts_asr_transcript', '')}",
                f"- Sentence status: {item.get('sentence_tts_semantic_verification', '')}",
                f"- Phrase expected: {item.get('phrase_tts_expected_text', '')}",
                f"- Phrase ASR: {item.get('phrase_tts_asr_transcript', '')}",
                f"- Phrase status: {item.get('phrase_tts_semantic_verification', '')}",
                f"- Sentence TTS file: `{item.get('sentence_tts_file', '')}`",
                f"- Phrase TTS file: `{item.get('phrase_tts_file', '')}`",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def write_audio_audit_files(
    export_root: Path,
    items: list[dict[str, Any]],
    summary: dict[str, Any],
    *,
    base_name: str = "audio_audit",
) -> tuple[Path, Path]:
    export_root.mkdir(parents=True, exist_ok=True)
    json_path = export_root / f"{base_name}.json"
    markdown_path = export_root / f"{base_name}.md"
    payload = {
        "summary": summary,
        "items": items,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(audio_audit_markdown(items, summary), encoding="utf-8")
    return json_path, markdown_path


def load_audio_audit_from_export_result(export_result: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    raw_items = export_result.get("audio_audit_items")
    items = [item for item in raw_items if isinstance(item, dict)] if isinstance(raw_items, list) else []
    summary = export_result.get("audio_audit_summary") if isinstance(export_result.get("audio_audit_summary"), dict) else {}
    if not items:
        audit_path = str(export_result.get("audio_audit_path") or "").strip()
        if audit_path:
            try:
                payload = json.loads(Path(audit_path).read_text(encoding="utf-8"))
                raw_file_items = payload.get("items") if isinstance(payload, dict) else []
                items = [item for item in raw_file_items if isinstance(item, dict)] if isinstance(raw_file_items, list) else []
                file_summary = payload.get("summary") if isinstance(payload, dict) and isinstance(payload.get("summary"), dict) else {}
                summary = summary or file_summary
            except Exception:
                pass
    return items, summary


def audio_audit_failure_details(
    items: list[dict[str, Any]],
    semantic_items: list[dict[str, Any]],
) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    for semantic in semantic_items:
        file_name = Path(str(semantic.get("file") or "")).name
        role = str(semantic.get("role") or "")
        matches = [
            item
            for item in items
            if file_name
            and file_name
            in {
                Path(str(item.get("sentence_tts_file") or "")).name,
                Path(str(item.get("phrase_tts_file") or "")).name,
            }
        ]
        if not matches:
            matches = [{}]
        for item in matches:
            failures.append(
                {
                    "card_id": item.get("card_id") or semantic.get("card_id") or "",
                    "learning_point_id": item.get("learning_point_id") or semantic.get("learning_point_id") or "",
                    "segment_id": item.get("segment_id") or semantic.get("segment_id") or "",
                    "source_time": item.get("source_time") or semantic.get("source_time") or "",
                    "role": role,
                    "file": file_name,
                    "expected_text": semantic.get("tts_text") or "",
                    "asr_transcript": semantic.get("asr_transcript") or "",
                    "semantic_verification": semantic.get("semantic_verification") or "",
                    "semantic_review_reasons": semantic.get("semantic_review_reasons") or [],
                }
            )
    return {"audio_failures": failures}
