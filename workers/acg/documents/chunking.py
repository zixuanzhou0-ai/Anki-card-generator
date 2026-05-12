from __future__ import annotations

import re
from typing import Any

from acg.protocol import fail


def normalize_document_text(text: str) -> str:
    text = re.sub(r"```[\s\S]*?```", " ", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"!\[[^\]]*\]\([^\)]*\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^\)]*\)", r"\1", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def clip_words(text: str, max_words: int) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text.strip()
    return " ".join(words[:max_words]).strip() + "..."


def document_title_from_text(text: str) -> str:
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if first_line:
        return clip_words(first_line, 12)
    words = re.findall(r"[\w\u4e00-\u9fff]+", text)
    return " ".join(words[:8]) if words else "知识点"


def split_document_chunks(text: str, max_chunks: int) -> list[dict[str, Any]]:
    raw_lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    heading_sections: list[str] = []
    current_section: list[str] = []
    for line in raw_lines:
        if re.match(r"^\s{0,3}#{1,6}\s+\S", line):
            if current_section:
                section = normalize_document_text("\n".join(current_section))
                if len(section) >= 40:
                    heading_sections.append(section)
            current_section = [line]
        else:
            current_section.append(line)
    if current_section:
        section = normalize_document_text("\n".join(current_section))
        if len(section) >= 40:
            heading_sections.append(section)

    if len(heading_sections) >= 2:
        chunks = heading_sections
    else:
        clean = normalize_document_text(text)
        paragraphs = [re.sub(r"\s+", " ", item).strip() for item in re.split(r"\n\s*\n", clean) if item.strip()]
        chunks = []
        buffer = ""
        for paragraph in paragraphs:
            if len(paragraph) < 40 and buffer:
                buffer = f"{buffer}\n{paragraph}".strip()
                continue
            if buffer and len(buffer) + len(paragraph) > 900:
                chunks.append(buffer)
                buffer = paragraph
            else:
                buffer = f"{buffer}\n{paragraph}".strip() if buffer else paragraph
        if buffer:
            chunks.append(buffer)

    if not chunks:
        fail("文档里没有足够的可制卡文本。")

    selected = chunks[: max(1, max_chunks)]
    segments: list[dict[str, Any]] = []
    for index, chunk in enumerate(selected, 1):
        title = document_title_from_text(chunk)
        question = f"这段资料的核心知识点是什么：{title}"
        segments.append(
            {
                "id": f"doc_{index:04d}",
                "start": 0,
                "end": 0,
                "source_time": f"文档知识点 {index}",
                "text": question,
                "document_excerpt": clip_words(chunk, 180),
                "duration": 0,
                "recommendation": 4,
                "phrase": title,
                "score": 4.0,
            }
        )
    return segments

