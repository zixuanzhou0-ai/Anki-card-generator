from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from acg.language_text import normalize_learning_language
from acg.protocol import fail
from acg.subtitles.core import strip_subtitle_text


TEXT_SUBTITLE_CODECS = {"subrip", "ass", "ssa", "webvtt", "mov_text"}


def language_code(language: str) -> str:
    return normalize_learning_language(language)


def subtitle_language_args(language: str) -> str:
    code = language_code(language)
    if code == "en":
        return "en,en-orig,en-GB,en-US"
    return f"{code},{code}-orig,{code}.*,{code},en,en-orig,en.*"


def first_file_by_suffix(directory: Path, suffixes: tuple[str, ...]) -> Path | None:
    candidates = [
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in suffixes and not path.name.endswith(".info.json")
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda path: path.stat().st_size if path.exists() else 0, reverse=True)[0]


def convert_vtt_to_srt(path: Path) -> Path:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n\s*\n", text)
    cues: list[str] = []

    for block in blocks:
        lines = [line.strip("\ufeff") for line in block.split("\n") if line.strip()]
        if not lines:
            continue
        if lines[0].startswith(("WEBVTT", "NOTE", "STYLE", "REGION")):
            continue
        time_index = next((index for index, line in enumerate(lines) if "-->" in line), -1)
        if time_index == -1:
            continue
        time_line = re.sub(r"(\d{2}:\d{2}:\d{2})\.(\d{3})", r"\1,\2", lines[time_index])
        cue_text = strip_subtitle_text(" ".join(lines[time_index + 1 :]))
        if cue_text:
            cues.append(f"{len(cues) + 1}\n{time_line}\n{cue_text}")

    if not cues:
        fail(f"字幕不是可转换的 VTT：{path}")
    output = path.with_suffix(".srt")
    output.write_text("\n\n".join(cues) + "\n", encoding="utf-8")
    return output


def pick_subtitle_file(directory: Path, language: str) -> Path | None:
    code = language_code(language)
    subtitles = [
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in {".srt", ".vtt"}
    ]
    if not subtitles:
        return None

    def score(path: Path) -> tuple[int, str]:
        name = path.name.lower()
        if f".{code}" in name:
            return (0, name)
        if ".en" in name:
            return (1, name)
        return (2, name)

    selected = sorted(subtitles, key=score)[0]
    if selected.suffix.lower() == ".vtt":
        return convert_vtt_to_srt(selected)
    return selected


def compact_match_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def subtitle_language_markers(language: str) -> set[str]:
    code = language_code(language)
    markers = {f".{code}", f"-{code}", f"_{code}", f" {code}", f".{code}-", f".{code}_"}
    if code == "en":
        markers.update({"english", ".eng", "-eng", "_eng", " eng"})
    return markers


def _clean_input_path(value: Any) -> str:
    return str(value or "").strip().strip('"').strip("'")


def discover_local_subtitle(video_path: str, language: str = "English") -> Path | None:
    video = Path(_clean_input_path(video_path))
    directory = video.parent
    if not video.name or not directory.exists():
        return None

    subtitles = [
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in {".srt", ".vtt"}
    ]
    if not subtitles:
        return None

    video_stem = video.stem.lower()
    compact_video = compact_match_text(video_stem)
    markers = subtitle_language_markers(language)

    def score(path: Path) -> tuple[int, int, str]:
        stem = path.stem.lower()
        compact_stem = compact_match_text(stem)
        has_language_marker = any(marker in stem for marker in markers)
        size = path.stat().st_size if path.exists() else 0
        if compact_stem == compact_video:
            return (0, -size, path.name.lower())
        if compact_video and compact_stem.startswith(compact_video) and has_language_marker:
            return (1, -size, path.name.lower())
        if compact_video and compact_video in compact_stem and has_language_marker:
            return (2, -size, path.name.lower())
        if compact_video and compact_stem.startswith(compact_video):
            return (3, -size, path.name.lower())
        if len(subtitles) == 1:
            return (4, -size, path.name.lower())
        return (9, -size, path.name.lower())

    selected = sorted(subtitles, key=score)[0]
    if score(selected)[0] >= 9:
        return None
    if selected.suffix.lower() == ".vtt":
        return convert_vtt_to_srt(selected)
    return selected


def subtitle_language_aliases(language: str) -> set[str]:
    lower = str(language or "").lower()
    if any(value in lower for value in ["zh", "chinese", "中文", "汉语", "chi", "zho", "cmn"]):
        return {"zh", "zho", "chi", "cmn", "chn", "chinese", "中文"}
    if any(value in lower for value in ["fr", "french", "français"]):
        return {"fr", "fra", "fre", "french"}
    if any(value in lower for value in ["es", "spanish", "español"]):
        return {"es", "spa", "spanish"}
    if any(value in lower for value in ["ja", "japanese", "日本"]):
        return {"ja", "jpn", "japanese"}
    if any(value in lower for value in ["ru", "russian", "рус", "俄语"]):
        return {"ru", "rus", "russian"}
    if any(value in lower for value in ["ko", "korean", "한국"]):
        return {"ko", "kor", "korean"}
    return {"en", "eng", "english", "en-us", "en-gb"}


def select_embedded_subtitle_stream(probe: dict[str, Any] | None, language: str) -> dict[str, Any] | None:
    aliases = subtitle_language_aliases(language)
    streams = [stream for stream in (probe or {}).get("streams", []) if stream.get("codec_type") == "subtitle"]
    text_streams = [stream for stream in streams if str(stream.get("codec_name") or "").lower() in TEXT_SUBTITLE_CODECS]
    if not text_streams:
        return None

    def score(stream: dict[str, Any]) -> tuple[int, int, int, int]:
        tags = stream.get("tags") if isinstance(stream.get("tags"), dict) else {}
        language_tag = str(tags.get("language") or "").strip().lower()
        codec = str(stream.get("codec_name") or "").lower()
        disposition = stream.get("disposition") if isinstance(stream.get("disposition"), dict) else {}
        language_score = 0 if language_tag in aliases else 3 if language_tag in {"", "und", "unknown"} else 8
        codec_score = 0 if codec == "subrip" else 1
        forced_score = 2 if int(disposition.get("forced") or 0) else 0
        default_score = 0 if int(disposition.get("default") or 0) else 1
        return (language_score, forced_score, codec_score, default_score)

    selected = sorted(text_streams, key=score)[0]
    return selected if score(selected)[0] < 8 else None
