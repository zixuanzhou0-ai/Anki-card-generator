from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Cue:
    index: int
    start: float
    end: float
    text: str


def parse_timestamp(value: str) -> float:
    match = re.match(r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})", value.strip())
    if not match:
        raise ValueError(f"无法解析 SRT 时间：{value}")
    hours, minutes, seconds, millis = [int(part) for part in match.groups()]
    return hours * 3600 + minutes * 60 + seconds + millis / 1000


def fmt_time(seconds: float) -> str:
    millis = int(round((seconds - int(seconds)) * 1000))
    whole = int(seconds)
    hh = whole // 3600
    mm = (whole % 3600) // 60
    ss = whole % 60
    return f"{hh:02d}:{mm:02d}:{ss:02d}.{millis:03d}"


def strip_subtitle_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", value)
    value = re.sub(r"\{\\.*?\}", "", value)
    value = re.sub(r"(?:^|\s)(?:>>|>)+\s*", " ", value)
    value = re.sub(r"^\s*[.?!]+\s*", "", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()
