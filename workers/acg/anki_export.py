from __future__ import annotations

import re
import zlib
from typing import Any


def stable_id(value: str, offset: int = 0) -> int:
    return int(zlib.crc32(value.encode("utf-8")) + offset)


def safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "media"


def anki_deck_part(value: Any, fallback: str = "未命名") -> str:
    cleaned = str(value or "").strip()
    cleaned = re.sub(r"::+", " - ", cleaned)
    cleaned = re.sub(r"[\\/:*?\"<>|]+", " - ", cleaned)
    cleaned = re.sub(r"\s*-\s*", " - ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"(?: - ){2,}", " - ", cleaned).strip(" -")
    return cleaned or fallback


def anki_deck_name(value: Any, fallback: str = "未命名") -> str:
    raw = str(value or "").strip()
    if "::" not in raw:
        return anki_deck_part(raw, fallback)
    parts = [anki_deck_part(part, fallback) for part in raw.split("::")]
    return "::".join(part for part in parts if part) or fallback


def batch_export_deck_specs(project: dict[str, Any]) -> tuple[str, list[dict[str, str]]]:
    parent = anki_deck_part(project.get("title") or project.get("id") or "批量学习包", "批量学习包")
    raw_items = project.get("batch_items") if isinstance(project.get("batch_items"), list) else []
    specs: list[dict[str, str]] = []
    seen_names: dict[str, int] = {}
    for index, item in enumerate(raw_items):
        if not isinstance(item, dict) or item.get("enabled") is False:
            continue
        item_id = str(item.get("id") or f"item-{index + 1}").strip()
        if not item_id:
            continue
        explicit_deck = str(item.get("deck_name") or "").strip()
        if explicit_deck:
            deck_name = anki_deck_name(explicit_deck, parent)
            if "::" not in deck_name:
                deck_name = f"{parent}::{deck_name}"
        else:
            child = anki_deck_part(item.get("subdeck_title") or item.get("title") or item_id, f"素材 {index + 1}")
            deck_name = f"{parent}::{child}"
        count = seen_names.get(deck_name, 0)
        seen_names[deck_name] = count + 1
        if count:
            deck_name = f"{deck_name} ({count + 1})"
        specs.append({"id": item_id, "deck_name": deck_name})
    return parent, specs


def project_media_prefix(project: dict[str, Any], export_run_id: int | None = None) -> str:
    base = safe_filename(str(project.get("title") or project.get("id") or "deck"))[:72]
    seed = "|".join(str(project.get(key) or "") for key in ("id", "title", "source_url", "created_at"))
    if export_run_id is not None:
        seed = f"{seed}|{export_run_id}"
    return f"{base}_{stable_id(seed, 0)}"
