from __future__ import annotations

from typing import Any


SUBTITLE_ONLY_IMPORT_MODES = {"subtitles", "subtitle", "subtitle_only", "transcript"}


def normalized_url_import_mode(payload: dict[str, Any]) -> str:
    return str(payload.get("url_import_mode") or "").strip().lower()


def url_video_mode_requested(payload: dict[str, Any]) -> bool:
    return normalized_url_import_mode(payload) == "video"


def wants_subtitle_only(payload: dict[str, Any]) -> bool:
    mode = normalized_url_import_mode(payload)
    if mode in SUBTITLE_ONLY_IMPORT_MODES:
        return True
    if mode == "video":
        return False
    return bool(payload.get("skip_video_slicing"))


def video_free_export_allowed(project: dict[str, Any]) -> bool:
    source_mode = str(project.get("source_mode") or "").strip().lower()
    if source_mode == "document":
        return True
    source_info = project.get("source_info") if isinstance(project.get("source_info"), dict) else {}
    url_mode = normalized_url_import_mode(project)
    if source_mode == "url":
        if url_mode in SUBTITLE_ONLY_IMPORT_MODES:
            return True
        download_mode = str(source_info.get("download_mode") or "").strip().lower()
        has_video_path = bool(project.get("video_path") or source_info.get("video_path"))
        if url_mode == "video" or (download_mode == "video" and has_video_path) or has_video_path:
            return False
        if bool(source_info.get("transcript_only")):
            return True
    return (
        bool(project.get("skip_video_slicing"))
        or url_mode in SUBTITLE_ONLY_IMPORT_MODES
        or bool(source_info.get("transcript_only"))
    )


def video_media_required_for_export(project: dict[str, Any]) -> bool:
    source_mode = str(project.get("source_mode") or "").strip().lower()
    return source_mode != "document" and not video_free_export_allowed(project)
