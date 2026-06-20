from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any, Callable

from acg.tts_text import clean_tts_input_text


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def bytes_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def media_text_hash(value: Any) -> str:
    text = clean_tts_input_text(str(value or "")).lower()
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12] if text else ""


def media_manifest(
    media_files: list[str],
    media_ledger: list[dict[str, Any]] | None = None,
    *,
    duration_seconds_func: Callable[[Path], float | None] | None = None,
    phrase_max_duration_func: Callable[[str], float] | None = None,
) -> dict[str, dict[str, Any]]:
    ledger_by_file: dict[str, dict[str, Any]] = {}
    for item in media_ledger or []:
        name = Path(str(item.get("file") or "")).name
        if name and name not in ledger_by_file:
            ledger_by_file[name] = {
                key: value
                for key, value in item.items()
                if key != "file" and value not in (None, "", [])
            }

    manifest: dict[str, dict[str, Any]] = {}
    for media_file in media_files:
        path = Path(media_file)
        if not path.exists():
            continue
        entry: dict[str, Any] = {
            "sha256": file_sha256(path),
            "bytes": path.stat().st_size,
        }
        ledger_entry = ledger_by_file.get(path.name, {})
        entry.update(ledger_entry)

        suffix = path.suffix.lower()
        if duration_seconds_func and suffix in {".mp3", ".mp4", ".webm"}:
            duration = duration_seconds_func(path)
            if duration is not None:
                entry["duration_seconds"] = round(duration, 3)
        if (
            phrase_max_duration_func
            and ledger_entry.get("role") == "phrase_tts"
            and ledger_entry.get("tts_text")
        ):
            entry["max_duration_seconds"] = round(
                phrase_max_duration_func(str(ledger_entry.get("tts_text") or "")),
                3,
            )
        manifest[path.name] = entry
    return manifest


def media_ledger_manifest_consistency(
    media_ledger: list[dict[str, Any]],
    expected_manifest: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    expected_names = set(expected_manifest)
    ledger_files = {
        Path(str(item.get("file") or "")).name
        for item in media_ledger
        if isinstance(item, dict) and str(item.get("file") or "").strip()
    }
    return {
        "ledger_missing_manifest": sorted(ledger_files - expected_names),
        "manifest_tts_without_ledger": sorted(
            name
            for name, info in expected_manifest.items()
            if isinstance(info, dict)
            and str(info.get("role") or "") in {"sentence_tts", "phrase_tts"}
            and name not in ledger_files
        ),
        "ledger_text_hash_mismatch": [
            {
                "file": Path(str(item.get("file") or "")).name,
                "expected_text_hash": media_text_hash(item.get("tts_text")),
                "ledger_text_hash": str(item.get("text_hash") or ""),
            }
            for item in media_ledger
            if isinstance(item, dict)
            and item.get("tts_text")
            and str(item.get("text_hash") or "") not in {"", media_text_hash(item.get("tts_text"))}
        ],
    }


def media_ledger_card_text_mismatches(
    card_media_ledger: list[dict[str, Any]],
    media_ledger: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ledger_by_file = {
        Path(str(item.get("file") or "")).name: item
        for item in media_ledger
        if isinstance(item, dict) and str(item.get("file") or "").strip()
    }
    checks = [
        {
            "audio_field": "sentence_tts_audio",
            "text_field": "sentence_tts_text",
            "imported_field": "TtsAudio",
            "role": "sentence_tts",
        },
        {
            "audio_field": "phrase_tts_audio",
            "text_field": "phrase_tts_text",
            "imported_field": "PhraseTtsAudio",
            "role": "phrase_tts",
        },
    ]
    mismatches: list[dict[str, Any]] = []
    for card_media in card_media_ledger:
        if not isinstance(card_media, dict):
            continue
        card_id = str(card_media.get("card_id") or "")
        for check in checks:
            file_name = Path(str(card_media.get(check["audio_field"]) or "")).name
            expected_hash = media_text_hash(card_media.get(check["text_field"]))
            if not file_name or not expected_hash:
                continue
            ledger_entry = ledger_by_file.get(file_name) or {}
            ledger_role = str(ledger_entry.get("role") or "")
            ledger_hash = media_text_hash(ledger_entry.get("tts_text"))
            if ledger_role == check["role"] and ledger_hash == expected_hash:
                continue
            mismatches.append(
                {
                    "card_id": card_id,
                    "field": check["imported_field"],
                    "file": file_name,
                    "expected_role": check["role"],
                    "ledger_role": ledger_role,
                    "expected_text_hash": expected_hash,
                    "ledger_text_hash": ledger_hash,
                    "ledger_declared_text_hash": str(ledger_entry.get("text_hash") or ""),
                }
            )
    return mismatches


def compare_media_manifest(
    expected: dict[str, dict[str, Any]],
    media_dir: Path,
    *,
    anki_url: str = "",
    max_attempts: int = 6,
    retry_delay_seconds: float = 0.2,
    file_sha256_func: Callable[[Path], str] = file_sha256,
    retrieve_media_bytes_func: Callable[[str, str], bytes | None] | None = None,
    bytes_sha256_func: Callable[[bytes], str] = bytes_sha256,
) -> dict[str, Any]:
    missing: list[str] = []
    mismatched: list[dict[str, str]] = []
    inaccessible: list[dict[str, str]] = []
    checked = 0
    for name, expected_info in sorted(expected.items()):
        imported = media_dir / name
        actual_hash = ""
        final_permission_error = ""
        for attempt in range(max(1, max_attempts)):
            try:
                if not imported.exists():
                    final_permission_error = ""
                    missing.append(name)
                    break
                actual_hash = file_sha256_func(imported)
                final_permission_error = ""
                checked += 1
                break
            except PermissionError as exc:
                final_permission_error = str(exc)
                if attempt + 1 < max(1, max_attempts):
                    time.sleep(retry_delay_seconds * (attempt + 1))
                    continue
        if final_permission_error and not actual_hash:
            media_bytes = retrieve_media_bytes_func(name, anki_url) if retrieve_media_bytes_func else None
            if media_bytes:
                actual_hash = bytes_sha256_func(media_bytes)
                checked += 1
            else:
                inaccessible.append({"file": name, "error": final_permission_error})
                continue
        if not actual_hash:
            continue
        expected_hash = str(expected_info.get("sha256") or "")
        if expected_hash and actual_hash != expected_hash:
            mismatched.append(
                {
                    "file": name,
                    "expected_sha256": expected_hash,
                    "actual_sha256": actual_hash,
                }
            )
    return {
        "checked": checked,
        "missing": missing,
        "mismatched": mismatched,
        "inaccessible": inaccessible,
    }
