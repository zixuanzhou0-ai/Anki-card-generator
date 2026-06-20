from __future__ import annotations

import html
import re
from pathlib import Path


def extract_media_references(value: str) -> list[str]:
    refs: list[str] = []
    for attr in ("src", "poster"):
        for match in re.finditer(rf"\b{attr}\s*=\s*([\"'])(.*?)\1", str(value or ""), flags=re.IGNORECASE):
            name = html.unescape(match.group(2)).strip()
            if name and not re.match(r"^[a-z]+://", name, flags=re.IGNORECASE):
                refs.append(Path(name).name)
    return list(dict.fromkeys(refs))


def media_refs_with_suffix(refs: list[str], suffixes: set[str]) -> list[str]:
    normalized = {suffix.lower() for suffix in suffixes}
    return [ref for ref in refs if Path(ref).suffix.lower() in normalized]


def missing_video_required_media_roles(refs_by_field: dict[str, list[str]]) -> list[str]:
    missing_roles: list[str] = []
    if not media_refs_with_suffix(refs_by_field.get("Video", []), {".mp4"}):
        missing_roles.append("Video.mp4")
    if not media_refs_with_suffix(refs_by_field.get("Video", []), {".webm"}):
        missing_roles.append("Video.webm")
    if not media_refs_with_suffix(refs_by_field.get("Video", []), {".jpg", ".jpeg", ".png", ".webp"}):
        missing_roles.append("Video.poster")
    if not media_refs_with_suffix(refs_by_field.get("Audio", []), {".mp3"}):
        missing_roles.append("Audio.mp3")
    if not media_refs_with_suffix(refs_by_field.get("TtsAudio", []), {".mp3"}):
        missing_roles.append("TtsAudio.mp3")
    if not media_refs_with_suffix(refs_by_field.get("PhraseTtsAudio", []), {".mp3"}):
        missing_roles.append("PhraseTtsAudio.mp3")
    return missing_roles
