from __future__ import annotations

import json
import re
from typing import Any


def strip_reasoning_text(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.IGNORECASE | re.DOTALL)
    return text.strip()


def extract_json_object(text: str) -> dict[str, Any]:
    text = strip_reasoning_text(text)
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    decoder = json.JSONDecoder()
    candidates: list[dict[str, Any]] = []
    for match in re.finditer(r"\{", text):
        try:
            value, _end = decoder.raw_decode(text[match.start() :])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            candidates.append(value)
    if not candidates:
        raise ValueError("模型没有返回 JSON 对象。")
    for key in ("segments", "candidates"):
        for candidate in reversed(candidates):
            if key in candidate:
                return candidate
    return candidates[-1]
