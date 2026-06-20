from __future__ import annotations

import re
from typing import Any


INTERNAL_PLACEHOLDER_PATTERNS = (
    "待精修",
    "本地 fallback",
    "本地草稿",
    "本地文档草稿",
    "本地文档精读草稿",
    "自动草稿卡",
    "预览草稿",
    "本地待审",
    "正式导出前",
    "内部提示",
    "需要人工确认",
    "需人工确认",
    "需要 AI 精修",
    "只保证结构完整",
    "不建议直接作为正式学习内容",
    "当作本句目标表达",
    "natural object",
    "complete sentence",
)

MANUAL_CONFIRMATION_ONLY_PLACEHOLDER_PATTERNS = {"需要人工确认", "需人工确认"}


def contains_internal_placeholder(value: Any) -> bool:
    text = str(value or "")
    text_lower = text.lower()
    return any(pattern in text or pattern.lower() in text_lower for pattern in INTERNAL_PLACEHOLDER_PATTERNS)


def internal_placeholder_patterns(value: Any) -> list[str]:
    text = str(value or "")
    if not text.strip():
        return []
    text_lower = text.lower()
    return [pattern for pattern in INTERNAL_PLACEHOLDER_PATTERNS if pattern in text or pattern.lower() in text_lower]


def internal_placeholder_patterns_for_quality_issue(value: Any) -> list[str]:
    patterns = internal_placeholder_patterns(value)
    return [pattern for pattern in patterns if pattern not in MANUAL_CONFIRMATION_ONLY_PLACEHOLDER_PATTERNS]


def clean_study_text(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if contains_internal_placeholder(text):
        return ""
    return text
