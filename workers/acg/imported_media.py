from __future__ import annotations

import math
import tempfile
import time
from pathlib import Path
from typing import Any, Callable


DurationSecondsFunc = Callable[[Path], float | None]
DurationSecondsFromBytesFunc = Callable[[str, bytes], float | None]
RetrieveMediaBytesFunc = Callable[[str, str], bytes | None]
CleanTtsTextFunc = Callable[[str], str]
PhraseMaxDurationFunc = Callable[[str], float]


def audio_duration_seconds_from_bytes(
    filename: str,
    data: bytes,
    *,
    duration_seconds_func: DurationSecondsFunc,
) -> float | None:
    suffix = Path(filename).suffix or ".mp3"
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
            handle.write(data)
            temp_path = Path(handle.name)
        return duration_seconds_func(temp_path)
    finally:
        if temp_path:
            try:
                temp_path.unlink()
            except OSError:
                pass


def imported_media_exists_for_audit(path: Path) -> bool:
    try:
        return path.exists()
    except PermissionError:
        return False
    except OSError:
        return False


def numeric_manifest_value(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def imported_tts_audio_duration_issues(
    expected_manifest: dict[str, dict[str, Any]],
    media_dir: Path,
    referenced_media: set[str],
    *,
    strict_video_import: bool,
    anki_url: str = "",
    max_attempts: int = 6,
    retry_delay_seconds: float = 0.2,
    retrieve_media_bytes_func: RetrieveMediaBytesFunc,
    duration_seconds_func: DurationSecondsFunc,
    duration_seconds_from_bytes_func: DurationSecondsFromBytesFunc,
    clean_tts_text_func: CleanTtsTextFunc,
    phrase_max_duration_func: PhraseMaxDurationFunc,
    sleep_func: Callable[[float], None] = time.sleep,
) -> list[dict[str, Any]]:
    if not strict_video_import:
        return []
    issues: list[dict[str, Any]] = []
    for name, info in sorted(expected_manifest.items()):
        if name not in referenced_media or not isinstance(info, dict):
            continue
        role = str(info.get("role") or "")
        if role not in {"sentence_tts", "phrase_tts"}:
            continue
        imported_path = media_dir / name
        imported_exists = False
        final_permission_error = ""
        for attempt in range(max(1, max_attempts)):
            try:
                imported_exists = imported_path.exists()
                final_permission_error = ""
                break
            except PermissionError as exc:
                final_permission_error = str(exc)
                if attempt + 1 < max(1, max_attempts):
                    sleep_func(retry_delay_seconds * (attempt + 1))
                    continue
        if final_permission_error and not imported_exists:
            media_bytes = retrieve_media_bytes_func(name, anki_url)
            if media_bytes:
                actual_duration = duration_seconds_from_bytes_func(name, media_bytes)
                _append_duration_issues(
                    issues,
                    name=name,
                    role=role,
                    info=info,
                    actual_duration=actual_duration,
                    clean_tts_text_func=clean_tts_text_func,
                    phrase_max_duration_func=phrase_max_duration_func,
                )
                continue
            issues.append(
                {
                    "file": name,
                    "role": role,
                    "reason": "duration_inaccessible",
                    "error": final_permission_error,
                }
            )
            continue
        if not imported_exists:
            continue
        actual_duration = duration_seconds_func(imported_path)
        _append_duration_issues(
            issues,
            name=name,
            role=role,
            info=info,
            actual_duration=actual_duration,
            clean_tts_text_func=clean_tts_text_func,
            phrase_max_duration_func=phrase_max_duration_func,
        )
    return issues


def _append_duration_issues(
    issues: list[dict[str, Any]],
    *,
    name: str,
    role: str,
    info: dict[str, Any],
    actual_duration: float | None,
    clean_tts_text_func: CleanTtsTextFunc,
    phrase_max_duration_func: PhraseMaxDurationFunc,
) -> None:
    expected_duration = numeric_manifest_value(info.get("duration_seconds"))
    duration_for_rules = actual_duration if actual_duration is not None else expected_duration
    if actual_duration is None and expected_duration is not None:
        issues.append(
            {
                "file": name,
                "role": role,
                "reason": "duration_unreadable",
                "expected_duration_seconds": round(expected_duration, 3),
            }
        )
        return
    if role != "phrase_tts":
        return
    tts_text = clean_tts_text_func(str(info.get("tts_text") or ""))
    if not tts_text:
        issues.append({"file": name, "role": role, "reason": "missing_tts_text"})
        return
    max_duration = phrase_max_duration_func(tts_text)
    if duration_for_rules is None:
        issues.append(
            {
                "file": name,
                "role": role,
                "reason": "duration_missing",
                "tts_text": tts_text,
                "max_duration_seconds": round(max_duration, 3),
            }
        )
        return
    if duration_for_rules > max_duration:
        issues.append(
            {
                "file": name,
                "role": role,
                "reason": "overlong_phrase_tts",
                "tts_text": tts_text,
                "duration_seconds": round(duration_for_rules, 3),
                "max_duration_seconds": round(max_duration, 3),
            }
        )
