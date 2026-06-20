from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Callable


MEDIA_CACHE_MIN_BYTES = {
    ".jpg": 1024,
    ".jpeg": 1024,
    ".mp3": 1024,
    ".mp4": 4096,
    ".webm": 4096,
}

TEXT_NORMALIZATION_CACHE_VERSION = 2
TTS_PROVIDER_ADAPTER_VERSION = 4
MEDIA_FFMPEG_PROFILE_VERSION = 2


def file_fingerprint(path_value: Any) -> str:
    path = Path(str(path_value or ""))
    if not path.exists() or not path.is_file():
        return ""
    try:
        stat = path.stat()
        digest = hashlib.sha256()
        digest.update(str(path.resolve()).encode("utf-8", errors="ignore"))
        digest.update(str(stat.st_size).encode("ascii"))
        digest.update(str(stat.st_mtime_ns).encode("ascii"))
        with path.open("rb") as handle:
            digest.update(handle.read(65536))
            if stat.st_size > 65536:
                handle.seek(max(0, stat.st_size - 65536))
                digest.update(handle.read(65536))
        return digest.hexdigest()[:24]
    except OSError:
        return ""


def stable_cache_key(payload: dict[str, Any], length: int = 32) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:length]


def persistent_cache_root(cwd: Path | None = None) -> Path:
    root = (cwd or Path.cwd()) / "projects" / "cache"
    root.mkdir(parents=True, exist_ok=True)
    return root


def tts_provider_scope(tts: dict[str, Any], *, provider: str, default_region: str = "") -> dict[str, str]:
    return {
        "project": str(tts.get("project") or tts.get("project_id") or "").strip(),
        "region": str(tts.get("location") or tts.get("region") or default_region).strip(),
        "style": str(tts.get("style") or tts.get("instructions") or "").strip(),
    }


def tts_cache_path(
    cache_root: Path,
    tts: dict[str, Any],
    text: str,
    language: Any,
    *,
    provider_name_func: Callable[[dict[str, Any]], str],
    resolve_language_func: Callable[[dict[str, Any], Any], str],
    normalize_volume_func: Callable[[Any], float],
    clean_text_func: Callable[[Any], str],
    text_hash_func: Callable[[Any], str],
    provider_scope_func: Callable[[dict[str, Any]], dict[str, str]],
) -> tuple[Path, str]:
    clean_text = clean_text_func(text)
    resolved_language = resolve_language_func(tts, language)
    cache_key = stable_cache_key(
        {
            "version": 2,
            "kind": "tts",
            "provider": provider_name_func(tts),
            "adapter_version": TTS_PROVIDER_ADAPTER_VERSION,
            "base_url": str(tts.get("base_url") or "").strip().rstrip("/"),
            "model": str(tts.get("model") or "").strip(),
            "voice": str(tts.get("voice") or "").strip(),
            "language": resolved_language,
            "provider_scope": provider_scope_func(tts),
            "sample_rate": int(tts.get("sample_rate") or 24000),
            "bit_rate": int(tts.get("bit_rate") or 128000),
            "output_volume": normalize_volume_func(tts.get("output_volume")),
            "text_normalization_version": TEXT_NORMALIZATION_CACHE_VERSION,
            "text_hash": text_hash_func(clean_text),
            "text": clean_text,
        }
    )
    return cache_root / "tts" / f"{cache_key}.mp3", cache_key


def media_clip_cache_path(
    cache_root: Path,
    video_fingerprint_value: str,
    start: str,
    duration: str,
    role: str,
    extension: str,
    profile: str,
    *,
    ffmpeg_signature: str,
) -> tuple[Path, str]:
    cache_key = stable_cache_key(
        {
            "version": 2,
            "kind": "media_clip",
            "video": video_fingerprint_value,
            "start": start,
            "duration": duration,
            "role": role,
            "extension": extension,
            "profile": profile,
            "ffmpeg_profile_version": MEDIA_FFMPEG_PROFILE_VERSION,
            "ffmpeg": ffmpeg_signature,
        }
    )
    return cache_root / "media" / f"{cache_key}.{extension.lstrip('.')}", cache_key


def cached_media_file_valid(path: Path) -> bool:
    try:
        size = path.stat().st_size
    except OSError:
        return False
    if size < MEDIA_CACHE_MIN_BYTES.get(path.suffix.lower(), 1):
        return False
    try:
        with path.open("rb") as handle:
            header = handle.read(64)
    except OSError:
        return False
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return header.startswith(b"\xff\xd8")
    if suffix == ".mp3":
        return header.startswith(b"ID3") or (
            len(header) >= 2 and header[0] == 0xFF and (header[1] & 0xE0) == 0xE0
        )
    if suffix == ".mp4":
        return b"ftyp" in header
    if suffix == ".webm":
        return header.startswith(b"\x1a\x45\xdf\xa3")
    return size > 0


def discard_cached_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def copy_cached_file(cache_path: Path, output_path: Path) -> bool:
    if not cached_media_file_valid(cache_path):
        discard_cached_file(cache_path)
        return False
    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(cache_path, output_path)
    if cached_media_file_valid(output_path):
        return True
    discard_cached_file(output_path)
    return False


def store_cached_file(output_path: Path, cache_path: Path) -> None:
    if not cached_media_file_valid(output_path):
        return
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = cache_path.with_suffix(f"{cache_path.suffix}.tmp")
    shutil.copy2(output_path, temp_path)
    temp_path.replace(cache_path)
