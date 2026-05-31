from __future__ import annotations

import html
import base64
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from pathlib import Path
from typing import Any

WORKER_DIR = Path(__file__).resolve().parents[1]
if str(WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(WORKER_DIR))

from acg.documents.chunking import clip_words, split_document_chunks
from acg.documents.readers import read_document_source
from acg.phrases.lexicon import (
    CARD_TYPE_LABELS,
    CEFR_LABELS,
    CEFR_ORDER,
    COMMON_FUNCTION_STARTS,
    CONTENT_PATTERNS,
    DISCOVERY_EXPRESSION_PATTERNS,
    DISCOVERY_PHRASE_PARTICLES,
    DISCOVERY_PHRASE_VERBS,
    DISCOVERY_PREPOSITION_STARTS,
    DISCOVERY_SIGNAL_WORDS,
    EXPRESSION_PATTERNS,
    FILLER_TEXTS,
    LOW_VALUE_STANDALONE_PHRASES,
    NON_TRANSFERABLE_PHRASES,
    PHRASE_GUIDE_ALIASES,
    PHRASE_GUIDES,
    PHRASES_BY_LEVEL,
    TEMPLATE_NOISE_PATTERNS,
    TOO_BASIC_FOR_INTERMEDIATE_PHRASES,
    TRANSFERABLE_FUNCTION_FRAME_PHRASES,
    VIDEO_INTRO_PATTERNS,
    WEAK_PHRASE_STARTS,
)
from acg.protocol import PROGRESS_PREFIX, emit, emit_progress, fail, read_payload
from acg.subtitles.core import Cue, fmt_time, parse_timestamp, strip_subtitle_text


for stream in (sys.stdin, sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")

MIMO_OPENAI_BASE_URL = "https://api.xiaomimimo.com/v1"
MIMO_TOKEN_PLAN_SGP_BASE_URL = "https://token-plan-sgp.xiaomimimo.com/v1"
DEEPSEEK_OPENAI_BASE_URL = "https://api.deepseek.com"
QWEN_DASHSCOPE_CN_TTS_BASE_URL = "https://dashscope.aliyuncs.com/api/v1"
QWEN_TTS_DEFAULT_MODEL = "qwen3-tts-flash"
QWEN_TTS_DEFAULT_VOICE = "Jennifer"
GEMINI_VERTEX_TTS_GLOBAL_BASE_URL = "https://aiplatform.googleapis.com"
GEMINI_VERTEX_TTS_DEFAULT_MODEL = "gemini-3.1-flash-tts-preview"
GEMINI_VERTEX_TTS_DEFAULT_VOICE = "Kore"
MIMO_PROVIDERS = {"mimo", "xiaomi-mimo"}
QWEN_TTS_PROVIDERS = {"qwen", "dashscope", "aliyun-dashscope"}
GEMINI_VERTEX_TTS_PROVIDERS = {"gemini-vertex", "vertex-gemini", "gemini-vertex-tts", "vertex-gemini-tts"}
OPENAI_COMPATIBLE_PROVIDERS = {"openai-compatible", *MIMO_PROVIDERS}
GEMINI_VERTEX_PROVIDERS = {"gemini-vertex", "vertex-gemini"}
GEMINI_VERTEX_GLOBAL_BASE_URL = "https://aiplatform.googleapis.com"
GEMINI_VERTEX_DEFAULT_MODEL = "gemini-3.1-pro-preview"
DEEPSEEK_THINKING_MODELS = {"deepseek-v4-pro", "deepseek-v4-flash", "deepseek-reasoner"}


def overlap_words(value: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9']+", value.lower())


def has_cjk(value: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", str(value or "")))


def clean_input_path(value: Any) -> str:
    return str(value or "").strip().strip('"').strip("'")


def word_overlap_ratio(left: str, right: str) -> float:
    left_words = set(overlap_words(left))
    right_words = set(overlap_words(right))
    if not left_words or not right_words:
        return 0.0
    return len(left_words & right_words) / max(1, min(len(left_words), len(right_words)))


def merge_subtitle_parts(parts: list[str]) -> str:
    merged = ""
    for raw_part in parts:
        part = strip_subtitle_text(raw_part)
        if not part:
            continue
        if not merged:
            merged = part
            continue

        merged_norm = " ".join(overlap_words(merged))
        part_norm = " ".join(overlap_words(part))
        if not part_norm:
            continue
        if part_norm in merged_norm:
            continue
        if merged_norm and merged_norm in part_norm:
            merged = part
            continue

        merged_words = overlap_words(merged)
        part_words = overlap_words(part)
        overlap = 0
        max_overlap = min(len(merged_words), len(part_words))
        for size in range(max_overlap, 0, -1):
            if merged_words[-size:] == part_words[:size]:
                overlap = size
                break
        if overlap >= 2:
            merged = f"{merged} {' '.join(part_words[overlap:])}".strip()
        else:
            merged = f"{merged} {part}".strip()
    return strip_subtitle_text(merged)


def parse_srt(path: str) -> list[Cue]:
    subtitle_path = Path(path)
    if not subtitle_path.exists():
        fail(f"SRT 文件不存在：{subtitle_path}")

    text = subtitle_path.read_text(encoding="utf-8-sig", errors="replace")
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    cues: list[Cue] = []
    i = 0

    while i < len(lines):
        line = lines[i].strip()
        if "-->" not in line:
            i += 1
            continue

        start_raw, end_raw = line.split("-->", 1)
        i += 1
        text_lines: list[str] = []
        while i < len(lines):
            current = lines[i].strip()
            if "-->" in current:
                break
            if current.isdigit():
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                if j < len(lines) and "-->" in lines[j]:
                    break
            if current:
                text_lines.append(current)
            i += 1

        clean_text = strip_subtitle_text(" ".join(text_lines))
        if not clean_text:
            continue
        cues.append(
            Cue(
                index=len(cues) + 1,
                start=parse_timestamp(start_raw),
                end=parse_timestamp(end_raw.split()[0]),
                text=clean_text,
            )
        )

    if not cues:
        fail("没有从 SRT 中解析出有效字幕。")
    return normalize_rolling_cues(cues)


def word_spans(text: str) -> list[re.Match[str]]:
    return list(re.finditer(r"[A-Za-z0-9']+", text))


def incremental_caption_text(previous_text: str, current_text: str) -> tuple[str, bool]:
    previous_words = overlap_words(previous_text)
    current_words = overlap_words(current_text)
    max_overlap = min(len(previous_words), len(current_words))
    overlap = 0
    for size in range(max_overlap, 1, -1):
        if previous_words[-size:] == current_words[:size]:
            overlap = size
            break
    if overlap < 2:
        return current_text, False

    spans = word_spans(current_text)
    if len(spans) < overlap:
        return current_text, False
    suffix = current_text[spans[overlap - 1].end() :].strip(" \t\r\n,")
    return suffix, True


def split_caption_fragment(text: str, start: float, end: float) -> list[tuple[str, float, float]]:
    text = strip_subtitle_text(text)
    if not text:
        return []
    parts: list[tuple[str, float, float]] = []
    cursor = 0
    duration = max(0.01, end - start)
    for match in re.finditer(r"[^.?!]+[.?!]+", text):
        fragment = strip_subtitle_text(match.group(0))
        if fragment:
            part_start = start + duration * (match.start() / max(1, len(text)))
            part_end = start + duration * (match.end() / max(1, len(text)))
            parts.append((fragment, part_start, part_end))
        cursor = match.end()
    tail = strip_subtitle_text(text[cursor:])
    if tail:
        part_start = start + duration * (cursor / max(1, len(text)))
        parts.append((tail, part_start, end))
    return parts


def append_caption_text(left: str, right: str) -> str:
    left = strip_subtitle_text(left)
    right = strip_subtitle_text(right)
    if not left:
        return right
    if not right:
        return left
    if re.search(r"[-/([{]$", left):
        return f"{left}{right}"
    return f"{left} {right}"


def stitch_sentence_cues(chunks: list[Cue]) -> list[Cue]:
    sentences: list[Cue] = []
    buffer = ""
    buffer_start = 0.0
    buffer_end = 0.0
    index = 1

    def flush_buffer() -> None:
        nonlocal buffer, buffer_start, buffer_end, index
        clean = strip_subtitle_text(buffer)
        if len(overlap_words(clean)) >= 3:
            sentences.append(Cue(index, buffer_start, buffer_end, clean))
            index += 1
        buffer = ""

    for cue in chunks:
        for fragment, frag_start, frag_end in split_caption_fragment(cue.text, cue.start, cue.end):
            if not buffer:
                buffer_start = frag_start
            buffer = append_caption_text(buffer, fragment)
            buffer_end = frag_end
            clean = strip_subtitle_text(buffer)
            words = overlap_words(clean)
            if re.search(r"[.?!][\"']?$", fragment):
                flush_buffer()
            elif len(words) >= 12 or (len(words) >= 7 and buffer_end - buffer_start >= 3.2):
                flush_buffer()

    tail = strip_subtitle_text(buffer)
    if len(overlap_words(tail)) >= 3:
        sentences.append(Cue(index, buffer_start, buffer_end, tail))

    return sentences or chunks


def normalize_rolling_cues(cues: list[Cue]) -> list[Cue]:
    chunks: list[Cue] = []
    previous_text = ""
    rolling_hits = 0

    for cue in cues:
        incremental, overlapped = incremental_caption_text(previous_text, cue.text)
        if overlapped:
            rolling_hits += 1
        clean = strip_subtitle_text(incremental)
        if clean:
            chunks.append(Cue(len(chunks) + 1, cue.start, cue.end, clean))
        previous_text = cue.text

    if cues and rolling_hits / max(1, len(cues)) >= 0.18:
        return stitch_sentence_cues(chunks)
    return cues


def contains_any(text: str, patterns: list[str]) -> bool:
    lower = text.lower()
    return any(pattern in lower for pattern in patterns)


def content_allowed(text: str, toggles: dict[str, bool]) -> bool:
    if not toggles.get("profanity", False) and contains_any(text, CONTENT_PATTERNS["profanity"]):
        return False
    if not toggles.get("romance", False) and contains_any(text, CONTENT_PATTERNS["romance"]):
        return False
    if not toggles.get("slang", True) and contains_any(text, CONTENT_PATTERNS["slang"]):
        return False
    if not toggles.get("sarcasm", True) and contains_any(text, CONTENT_PATTERNS["sarcasm"]):
        return False
    return True


def normalize_collection_levels(value: Any, current_level: str) -> list[str]:
    if not isinstance(value, list):
        value = []
    selected = [str(item).upper() for item in value if str(item).upper() in CEFR_ORDER]
    unique = list(dict.fromkeys(selected))
    if unique:
        return sorted(unique, key=CEFR_ORDER.index)
    cutoff = max(CEFR_ORDER.index(current_level), 0) if current_level in CEFR_ORDER else 2
    lower = max(0, cutoff - 1)
    return CEFR_ORDER[lower : cutoff + 1]


def collection_levels_from_payload(payload: dict[str, Any], current_level: str) -> list[str]:
    return normalize_collection_levels(payload.get("collection_levels"), current_level)


LANGUAGE_FOCUS_ORDER = ["phrases", "vocabulary", "grammar", "listening"]
LANGUAGE_FOCUS_LABELS = {
    "phrases": "词伙表达",
    "vocabulary": "单词用法",
    "grammar": "语法框架",
    "listening": "听力难点",
}
LANGUAGE_FOCUS_RULES = {
    "phrases": "优先选择可迁移的词伙、搭配、口语块和话语标记；phrase 必须来自原句且不能是整句。",
    "vocabulary": "可以选择原句里的一个核心单词或短搭配，但必须训练真实语境里的词义、搭配或用法，不做脱离原句的词典式生词卡。",
    "grammar": "可以选择原句里的可替换句型、结构或语法框架；重点解释它怎么换场景复用，而不是讲抽象语法术语。",
    "listening": "只在弱读、连读、缩读、停顿切分或听音辨义明显时强化听力点；不要把所有句子都硬做听力卡。",
}
STUDY_DEPTHS = {"standard", "deep"}
PHRASE_TYPE_CARD_LABELS = {
    "spoken_phrase": "表达卡",
    "sentence_frame": "表达卡",
    "collocation": "表达卡",
    "discourse_marker": "表达卡",
    "idiom": "表达卡",
    "listening_sentence": "听力卡",
    "vocabulary_usage": "语境生词卡",
    "grammar_pattern": "表达卡",
}
PHRASE_TYPE_CONTENT_KIND = {
    "spoken_phrase": "phrase",
    "sentence_frame": "grammar",
    "collocation": "phrase",
    "discourse_marker": "phrase",
    "idiom": "phrase",
    "listening_sentence": "listening",
    "vocabulary_usage": "vocabulary",
    "grammar_pattern": "grammar",
}
CANDIDATE_KIND_TO_PHRASE_TYPE = {
    "expression": "spoken_phrase",
    "contextual_vocab": "vocabulary_usage",
    "grammar_pattern": "grammar_pattern",
    "listening_feature": "listening_sentence",
    "pragmatic_risk": "idiom",
}
PHRASE_TYPE_TO_CANDIDATE_KIND = {
    "spoken_phrase": "expression",
    "sentence_frame": "grammar_pattern",
    "collocation": "expression",
    "discourse_marker": "expression",
    "idiom": "expression",
    "listening_sentence": "listening_feature",
    "vocabulary_usage": "contextual_vocab",
    "grammar_pattern": "grammar_pattern",
}
LEARNING_POINT_SCHEMA_VERSION = 3
TYPED_EXPRESSION_PATTERNS = [
    (r"\brun\s+the\s+register\b", "collocation", "expression", 1.6, "服务业场景搭配：负责收银/操作收银机。"),
    (r"\bhold\s+that\s+against\s+you\b", "idiom", "expression", 1.6, "把某事拿来责怪或记恨某人。"),
    (r"\bflat\s+as\s+a\s+washboard\b", "idiom", "pragmatic_risk", 1.7, "夸张比喻，带身体评价和冒犯风险。"),
    (r"\b(?:not\s+)?gonna\s+bite\s+you\b", "spoken_phrase", "expression", 1.2, "安抚别人别怕的口语句。"),
    (r"\b(?:add|adds|added|adding)\s+ten\s+pounds\b", "collocation", "expression", 1.4, "镜头让人显胖的非字面表达。"),
    (r"\bbounce\s+off\s+a\s+windshield\b", "collocation", "expression", 1.2, "撞到挡风玻璃后弹开的动作搭配。"),
    (r"\b(?:placed?|put)\s+(?:me|you|him|her|us|them|someone|somebody|people|[a-z']+)\s+into\s+custody\b", "collocation", "expression", 1.3, "法律/警务语境里的拘押搭配。"),
    (r"\bcould\s+use\s+a\s+hand\b", "spoken_phrase", "expression", 1.3, "表示需要帮忙的自然口语。"),
    (r"\btake\s+a\s+rain\s+check\b", "idiom", "expression", 1.4, "委婉改天再约的习语。"),
    (r"\bgetting\s+out\s+of\s+hand\b", "idiom", "expression", 1.4, "表示局面开始失控。"),
    (r"\bbetween\s+you\s+and\s+me\b", "discourse_marker", "expression", 1.1, "引出私下说法的话语标记。"),
    (r"\bno\s+offense,\s+but\b", "discourse_marker", "pragmatic_risk", 1.2, "带冒犯风险的缓冲开头。"),
]
CONTEXTUAL_VOCAB_PATTERNS = [
    (r"\bregister\b", "register", 1.1, "register 在服务业语境里可指收银机/收银台。"),
    (r"\bcustody\b", "custody", 1.0, "custody 在警务/法律语境里是羁押、拘留。"),
    (r"\bcritique\b", "critique", 1.0, "critique 是对作品或文本做专业点评。"),
    (r"\bfollowing\b", "following", 0.9, "following 在 I'm not following 里是跟上/听懂思路。"),
    (r"\b(?:add|adds|added|adding)\b", "add", 0.8, "add 在镜头/效果语境里可表示让人看起来增加。"),
]
GRAMMAR_PATTERN_RULES = [
    (r"\bi\s+seen\b", "I seen", 1.4, "非标准口语过去时，理解角色口音和方言色彩。"),
    (r"^\s*ever\s+want\s+me\s+to\b", "Ever want me to...", 1.5, "句首省略 If you 的口语条件框架。"),
    (r"\bit'?s\s+not\s+that\b.+\bit'?s\s+just\s+that\b", "It's not that..., it's just that...", 1.2, "解释原因时的可迁移框架。"),
    (r"\bnot\s+because\b.+\bbut\s+because\b", "not because..., but because...", 1.2, "纠正原因或对比原因的句型框架。"),
]
LISTENING_FEATURE_RE = re.compile(
    r"\b(?:i'm|you're|we're|they're|don't|can't|won't|let's|gonna|wanna|gotta|hafta|shoulda|coulda|woulda)\b(?:\s+[a-z']+){0,2}",
    re.IGNORECASE,
)


def normalized_language_focus(payload: dict[str, Any]) -> list[str]:
    raw = payload.get("language_focus")
    if not isinstance(raw, list):
        return ["phrases", "vocabulary", "listening"]
    selected = [str(item) for item in raw if str(item) in LANGUAGE_FOCUS_ORDER]
    unique = list(dict.fromkeys(selected))
    return unique or ["phrases", "vocabulary", "listening"]


def normalized_document_reading_focus(payload: dict[str, Any]) -> list[str]:
    focus = [item for item in normalized_language_focus(payload) if item in {"phrases", "vocabulary", "grammar"}]
    return focus or ["phrases"]


def language_focus_instruction(payload: dict[str, Any]) -> str:
    focus = normalized_language_focus(payload)
    labels = " / ".join(LANGUAGE_FOCUS_LABELS[item] for item in focus)
    rules = "".join(f"{LANGUAGE_FOCUS_LABELS[item]}：{LANGUAGE_FOCUS_RULES[item]}" for item in focus)
    return (
        f"本次用户选择的学习重点：{labels}。请只围绕这些重点判断和制卡。"
        "如果某个片段只有未选择的学习价值，优先降级为待审或跳过，不要为了数量硬凑。"
        f"{rules}"
    )


def normalized_study_depth(payload: dict[str, Any]) -> str:
    value = str(payload.get("study_depth") or "").strip()
    return value if value in STUDY_DEPTHS else "deep"


def card_label_for_phrase_type(phrase_type: str, fallback: str = "表达卡") -> str:
    return PHRASE_TYPE_CARD_LABELS.get(str(phrase_type or "").strip(), fallback)


def card_label_for_learning_card(phrase_type: str, content_kind: str, fallback: str = "表达卡") -> str:
    normalized_type = str(phrase_type or "").strip()
    if normalized_type in PHRASE_TYPE_CARD_LABELS:
        return PHRASE_TYPE_CARD_LABELS[normalized_type]
    normalized_kind = str(content_kind or "").strip()
    if normalized_kind == "vocabulary":
        return "语境生词卡"
    if normalized_kind == "listening":
        return "听力卡"
    return fallback


def content_kind_for_phrase_type(phrase_type: str, fallback: str = "phrase") -> str:
    return PHRASE_TYPE_CONTENT_KIND.get(str(phrase_type or "").strip(), fallback)


def candidate_kind_for_phrase_type(phrase_type: str, fallback: str = "expression") -> str:
    return PHRASE_TYPE_TO_CANDIDATE_KIND.get(str(phrase_type or "").strip(), fallback)


def phrase_type_for_candidate_kind(candidate_kind: str, fallback: str = "spoken_phrase") -> str:
    return CANDIDATE_KIND_TO_PHRASE_TYPE.get(str(candidate_kind or "").strip(), fallback)


def candidate_kind_for_segment(segment: dict[str, Any]) -> str:
    explicit = str(segment.get("candidate_kind") or "").strip()
    if explicit:
        return explicit
    content_kind = str(segment.get("content_kind") or "").strip()
    if content_kind == "vocabulary":
        return "contextual_vocab"
    if content_kind == "grammar":
        return "grammar_pattern"
    if content_kind == "listening":
        return "listening_feature"
    return candidate_kind_for_phrase_type(str(segment.get("phrase_type") or ""), "expression")


def candidate_kind_allowed_by_focus(candidate_kind: str, payload: dict[str, Any]) -> bool:
    focus = set(normalized_language_focus(payload))
    if candidate_kind in {"expression", "pragmatic_risk"}:
        return "phrases" in focus
    if candidate_kind == "contextual_vocab":
        return "vocabulary" in focus
    if candidate_kind == "listening_feature":
        return "listening" in focus
    if candidate_kind == "grammar_pattern":
        # Spoken ellipsis/non-standard grammar often behaves like an expression.
        return bool({"grammar", "phrases"} & focus)
    return True


DOCUMENT_FOCUS_ORDER = ["concepts", "arguments", "terms", "examples"]
DOCUMENT_FOCUS_LABELS = {
    "concepts": "核心概念",
    "arguments": "观点论证",
    "terms": "术语定义",
    "examples": "例子案例",
}
DOCUMENT_FOCUS_RULES = {
    "concepts": "抽取文档里必须理解的概念、机制或原则；问题要能训练主动回忆，不要把章节标题硬当概念。",
    "arguments": "抽取作者观点、理由、证据和推导链；要说明观点为什么成立，避免只写一句空泛结论。",
    "terms": "抽取术语、定义、边界和易混点；要能区分相关概念，不做词典式堆料。",
    "examples": "抽取真正能帮助记住概念的例子或案例；例子必须服务于一个明确知识点。",
}
DOCUMENT_STUDY_MODES = {"knowledge", "language_reading"}
DOCUMENT_ANSWER_LANGUAGES = {
    "zh": "反面解释优先用自然中文；关键术语可以保留英文。",
    "en": "反面答案和解释优先用英文；避免中文长解释。",
    "bilingual": "中文理解为主，同时保留关键英文术语和简短英文表达。",
}
DOCUMENT_DEPTH_RULES = {
    "quick": "快速记忆：问题要短，答案尽量 1 句，避免展开过多背景。",
    "standard": "标准理解：答案 1-3 句，保留必要条件、原因或例子。",
    "deep": "深入掌握：强调边界、推理链、对比项和容易误解的点。",
}
DOCUMENT_LENGTH_RULES = {
    "short": "短答案：反面核心答案尽量 1 句。",
    "medium": "中等答案：反面核心答案 1-3 句。",
    "long": "详细答案：允许更多解释，但仍禁止照抄原文长段。",
}


def normalized_document_focus(payload: dict[str, Any]) -> list[str]:
    raw = payload.get("document_focus")
    if not isinstance(raw, list):
        return ["concepts", "arguments", "terms"]
    selected = [str(item) for item in raw if str(item) in DOCUMENT_FOCUS_ORDER]
    unique = list(dict.fromkeys(selected))
    return unique or ["concepts", "arguments", "terms"]


def normalized_document_study_mode(payload: dict[str, Any]) -> str:
    raw = str(payload.get("document_study_mode") or "knowledge")
    return raw if raw in DOCUMENT_STUDY_MODES else "knowledge"


def normalized_document_answer_language(payload: dict[str, Any]) -> str:
    raw = str(payload.get("document_answer_language") or "zh")
    return raw if raw in DOCUMENT_ANSWER_LANGUAGES else "zh"


def normalized_document_depth(payload: dict[str, Any]) -> str:
    raw = str(payload.get("document_depth") or "standard")
    return raw if raw in DOCUMENT_DEPTH_RULES else "standard"


def normalized_document_answer_length(payload: dict[str, Any]) -> str:
    raw = str(payload.get("document_answer_length") or "medium")
    return raw if raw in DOCUMENT_LENGTH_RULES else "medium"


def document_style_instruction(payload: dict[str, Any]) -> str:
    answer_language = normalized_document_answer_language(payload)
    depth = normalized_document_depth(payload)
    answer_length = normalized_document_answer_length(payload)
    return (
        f"讲解语言：{DOCUMENT_ANSWER_LANGUAGES[answer_language]}"
        f"卡片深度：{DOCUMENT_DEPTH_RULES[depth]}"
        f"答案长度：{DOCUMENT_LENGTH_RULES[answer_length]}"
    )


def document_focus_instruction(payload: dict[str, Any]) -> str:
    focus = normalized_document_focus(payload)
    labels = " / ".join(DOCUMENT_FOCUS_LABELS[item] for item in focus)
    rules = "".join(f"{DOCUMENT_FOCUS_LABELS[item]}：{DOCUMENT_FOCUS_RULES[item]}" for item in focus)
    return (
        f"本次文档吸收目标：{labels}。请只围绕这些目标做知识卡。"
        "每张卡必须只有一个明确记忆动作：定义概念、解释观点、区分概念或记住例子。"
        f"{rules}"
    )


def phrase_pool(level: str, collection_levels: list[str] | None = None) -> list[str]:
    order = CEFR_ORDER
    if collection_levels:
        selected_levels = normalize_collection_levels(collection_levels, level)
    else:
        cutoff = max(order.index(level), 0) if level in order else 2
        lower = max(0, cutoff - 1)
        upper = min(len(order), cutoff + 2)
        selected_levels = order[lower:upper]
    pool: list[str] = []
    for item in selected_levels:
        pool.extend(PHRASES_BY_LEVEL[item])
    return pool


def normalize_phrase_candidate(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip(" \t\r\n.,!?;:\"“”‘’")).strip()


def has_adjacent_duplicate_words(words: list[str]) -> bool:
    return any(left == right for left, right in zip(words, words[1:]))


def trim_discovery_phrase_words(words: list[str]) -> list[str]:
    if len(words) >= 2 and words[0] in DISCOVERY_PHRASE_VERBS and words[1] in DISCOVERY_PHRASE_PARTICLES:
        return words[:2]
    if (
        len(words) >= 3
        and words[0] in DISCOVERY_PHRASE_VERBS
        and words[1] in {"it", "this", "that", "things", "something", "someone", "me", "you", "him", "her", "us", "them"}
        and words[2] in DISCOVERY_PHRASE_PARTICLES
    ):
        return words[:3]
    return words


def discovery_ngram_has_signal(words: list[str]) -> bool:
    phrase = " ".join(words)
    if phrase in TRANSFERABLE_FUNCTION_FRAME_PHRASES:
        return True
    if any(phrase == f"{item} that" for item in TRANSFERABLE_FUNCTION_FRAME_PHRASES):
        return True
    if len(words) == 2 and words[0] in {"feel", "feels", "felt", "look", "looks", "looked", "sound", "sounds", "sounded"} and words[1] == "like":
        return True
    if words[0] in DISCOVERY_PHRASE_VERBS and (
        words[1] in DISCOVERY_PHRASE_PARTICLES
        or (
            len(words) >= 3
            and words[1] in {"it", "this", "that", "things", "something", "someone", "me", "you", "him", "her", "us", "them"}
            and words[2] in DISCOVERY_PHRASE_PARTICLES
        )
    ):
        return True
    if (
        words[0] in DISCOVERY_PREPOSITION_STARTS
        and words[-1] in {"end", "middle", "mood", "place", "point", "run", "start", "time", "way"}
        and any(word in DISCOVERY_SIGNAL_WORDS for word in words[1:])
    ):
        return True
    if len(words) >= 3 and words[0] == "such" and words[1] in {"a", "an"}:
        return True
    if len(words) >= 3 and words[0] in {"more", "less"} and "than" in words:
        return True
    if len(words) >= 4 and words[0] == "as" and words[-1] == "possible":
        return True
    if len(words) >= 3 and "kind" in words and "of" in words:
        return True
    if len(words) >= 3 and "sort" in words and "of" in words:
        return True
    return False


def structurally_safe_discovery_phrase(phrase: str) -> bool:
    words = overlap_words(phrase)
    if len(words) < 2 or len(words) > 6:
        return False
    key = " ".join(words)
    if key in {"key expression", *LOW_VALUE_STANDALONE_PHRASES}:
        return False
    if has_adjacent_duplicate_words(words):
        return False
    if sum(1 for word in words if any(char.isdigit() for char in word)) > 1:
        return False
    if words[0] in COMMON_FUNCTION_STARTS and key not in TRANSFERABLE_FUNCTION_FRAME_PHRASES:
        return False
    if words[0] in WEAK_PHRASE_STARTS and words[0] not in DISCOVERY_PREPOSITION_STARTS and not discovery_ngram_has_signal(words):
        return False
    if words[-1] in {"the", "a", "an", "and", "or", "but", "as", "because", "if", "than", "to", "with"}:
        return False
    return discovery_ngram_has_signal(words)


def candidate_phrases_from_text(text: str) -> list[str]:
    lower = str(text or "").lower()
    candidates: list[str] = []
    seen: set[str] = set()

    def add(value: str, trusted: bool = False) -> None:
        candidate = normalize_phrase_candidate(value)
        if not trusted:
            words = trim_discovery_phrase_words(overlap_words(candidate))
            candidate = " ".join(words)
        key = " ".join(overlap_words(candidate))
        if not key or key in seen:
            return
        words = key.split()
        if trusted and 2 <= len(words) <= 6 and key not in LOW_VALUE_STANDALONE_PHRASES and not has_adjacent_duplicate_words(words):
            candidates.append(candidate)
            seen.add(key)
        elif structurally_safe_discovery_phrase(candidate):
            candidates.append(candidate)
            seen.add(key)

    for pattern in DISCOVERY_EXPRESSION_PATTERNS:
        for match in re.finditer(pattern, lower):
            add(match.group(0), trusted=True)

    words = overlap_words(lower)
    for length in (5, 4, 3, 2):
        if len(candidates) >= 8:
            break
        for index in range(0, max(0, len(words) - length + 1)):
            add(" ".join(words[index : index + length]))
            if len(candidates) >= 8:
                break

    return candidates


def find_phrase(text: str, level: str, collection_levels: list[str] | None = None) -> str:
    lower = text.lower()
    for pattern in EXPRESSION_PATTERNS:
        match = re.search(pattern, lower)
        if match:
            return re.sub(r"\s+", " ", match.group(0)).strip()

    pool = sorted(phrase_pool(level, collection_levels), key=len, reverse=True)
    for phrase in pool:
        if phrase in lower:
            return phrase

    for phrase in candidate_phrases_from_text(text):
        return phrase

    # Do not invent a phrase from arbitrary adjacent words. Bad fallback chunks like
    # "can we figure" or "ai model price" are worse than returning no phrase.
    return "key expression"


def is_filler_text(text: str) -> bool:
    words = overlap_words(text)
    return bool(words) and len(words) <= 2 and " ".join(words).strip(".?!") in FILLER_TEXTS


def looks_complete_sentence(text: str) -> bool:
    stripped = text.strip()
    words = overlap_words(stripped)
    return len(words) >= 4 and bool(re.search(r"[.?!]$|[.?!][\"']?$", stripped))


def has_unbalanced_quotes(text: str) -> bool:
    value = str(text or "")
    return value.count('"') % 2 == 1 or value.count("“") != value.count("”")


def clean_candidate_text(text: str) -> str:
    text = strip_subtitle_text(text)
    if not text:
        return ""
    if re.search(r"[.?!][\"']?$", text):
        return text
    complete_parts = re.findall(r"[^.?!]+[.?!]", text)
    if not complete_parts:
        return text
    cleaned = " ".join(part.strip() for part in complete_parts if part.strip())
    if len(overlap_words(cleaned)) >= 4:
        return cleaned
    return text


def starts_like_fragment(text: str) -> bool:
    words = overlap_words(text)
    if not words:
        return True
    if text.strip()[:1] in {".", "?", "!", ",", ";", ":"}:
        return True
    if words[0] in {"about", "of", "for", "to", "with", "from", "because", "and", "or", "but", "so"}:
        return True
    first_char = text.strip()[:1]
    return bool(first_char and first_char.islower() and words[0] not in {"i"} and not text.lower().startswith(("i ", "i'm", "i've")))


def looks_like_video_intro(text: str) -> bool:
    lower = re.sub(r"\s+", " ", str(text or "").strip().lower())
    return any(re.search(pattern, lower) for pattern in VIDEO_INTRO_PATTERNS)


def is_non_transferable_phrase(phrase: str) -> bool:
    lower = re.sub(r"\s+", " ", str(phrase or "").strip().lower())
    return bool(lower and (lower in NON_TRANSFERABLE_PHRASES or any(re.search(pattern, lower) for pattern in VIDEO_INTRO_PATTERNS)))


def is_low_value_standalone_phrase(phrase: str) -> bool:
    lower = re.sub(r"\s+", " ", str(phrase or "").strip().lower())
    return lower in LOW_VALUE_STANDALONE_PHRASES


GENERIC_DEFINITION_PATTERNS = [
    r"\bthis phrase is useful\b",
    r"\buseful in daily english\b",
    r"\bcommon(?:ly)? used\b",
    r"\bvery common\b",
    r"这个表达很常见",
    r"常用表达",
    r"高频表达",
    r"日常英语.*有用",
]

GENERIC_TEACHER_NOTE_PATTERNS = [
    r"^很常见[。.!]?$",
    r"^真实口语常用[。.!]?$",
    r"^高频口语表达[。.!]?$",
    r"^这个表达很常用[。.!]?$",
    r"^适合日常交流[。.!]?$",
    r"\buse it in daily english\b",
    r"\bthis is a common expression\b",
]


def has_generic_definition(value: str) -> bool:
    text = re.sub(r"\s+", " ", str(value or "").strip().lower())
    return bool(text and any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in GENERIC_DEFINITION_PATTERNS))


def has_generic_teacher_note(value: str) -> bool:
    text = re.sub(r"\s+", " ", str(value or "").strip().lower())
    return bool(text and any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in GENERIC_TEACHER_NOTE_PATTERNS))


def normalized_action_text(value: Any) -> str:
    if isinstance(value, list):
        return " / ".join(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, dict):
        return " / ".join(f"{key}: {item}" for key, item in value.items() if str(item).strip())
    return str(value or "").strip()


def cefr_rank(value: str) -> int:
    match = re.search(r"\b(A1|A2|B1|B2|C1|C2)\b", str(value or "").upper())
    if not match:
        return -1
    return CEFR_ORDER.index(match.group(1))


def is_too_basic_for_level(phrase: str, target_level: str) -> bool:
    level_rank = cefr_rank(target_level)
    if level_rank < cefr_rank("B1"):
        return False
    lower = re.sub(r"\s+", " ", str(phrase or "").strip().lower())
    return lower in TOO_BASIC_FOR_INTERMEDIATE_PHRASES


def allows_function_start_phrase(phrase: str) -> bool:
    lower = re.sub(r"\s+", " ", str(phrase or "").strip().lower())
    return lower in TRANSFERABLE_FUNCTION_FRAME_PHRASES or any(
        lower.startswith(f"{item} ") for item in TRANSFERABLE_FUNCTION_FRAME_PHRASES
    )


def phrase_guide_key(phrase: str) -> str:
    lower = re.sub(r"\s+", " ", str(phrase or "").strip().lower())
    return PHRASE_GUIDE_ALIASES.get(lower, lower)


def score_text(text: str, level: str, toggles: dict[str, bool], collection_levels: list[str] | None = None) -> float:
    lower = text.lower()
    words = re.findall(r"[A-Za-z']+", text)
    score = 2.0

    if 5 <= len(words) <= 12:
        score += 2.0
    elif 13 <= len(words) <= 14:
        score += 0.7
    if "?" in text or "!" in text:
        score += 0.4
    if contains_any(lower, phrase_pool(level, collection_levels)):
        score += 3.0
    if toggles.get("slang", True) and contains_any(lower, CONTENT_PATTERNS["slang"]):
        score += 0.6
    if toggles.get("sarcasm", True) and contains_any(lower, CONTENT_PATTERNS["sarcasm"]):
        score += 0.7
    if toggles.get("culture", True) and contains_any(lower, CONTENT_PATTERNS["culture"]):
        score += 0.5
    if toggles.get("business", True) and contains_any(lower, CONTENT_PATTERNS["business"]):
        score += 0.5
    if len(words) > 14:
        score -= 1.4
    if len(words) > 18:
        score -= 1.4
    if looks_like_video_intro(text):
        score -= 3.4
    if re.search(r"\[[^\]]+\]|\([^\)]*(music|applause|laugh)[^\)]*\)", lower):
        score -= 2.0
    return max(0.1, score)


def resolved_max_segments(payload: dict[str, Any], cues: list[Cue] | None = None, text: str = "") -> int:
    raw = payload.get("max_segments", 24)
    try:
        requested = int(raw)
    except (TypeError, ValueError):
        requested = 0
    if requested > 0:
        return max(3, min(120, requested))

    duration = 0.0
    source_info = payload.get("source_info") or {}
    try:
        duration = float(source_info.get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    if not duration and cues:
        duration = max(cue.end for cue in cues)
    if duration:
        minutes = max(1.0, duration / 60.0)
        target = round(18 + minutes * 3.1)
        if duration <= 300:
            target = max(20, target)
        elif duration <= 720:
            target = max(32, target)
        elif duration <= 1500:
            target = max(45, target)
        else:
            target = max(60, target)
        subtitle_cap = max(12, int((len(cues or []) or target) * 0.55))
        return max(12, min(80, target, subtitle_cap))

    word_count = len(overlap_words(text))
    if word_count:
        return max(8, min(60, round(word_count / 180)))
    return 35


def phrase_word_indices(text: str, phrase: str) -> tuple[int, int] | None:
    phrase_words = overlap_words(phrase)
    if not phrase_words or phrase == "key expression":
        return None
    text_words = overlap_words(text)
    if len(phrase_words) > len(text_words):
        return None
    for index in range(0, len(text_words) - len(phrase_words) + 1):
        if text_words[index : index + len(phrase_words)] == phrase_words:
            return index, index + len(phrase_words) - 1
    return None


def segment_media_bounds(start: float, end: float, text: str, phrase: str, review_mode: bool) -> tuple[float, float]:
    duration = max(0.1, end - start)
    words = overlap_words(text)
    if duration <= 3.8 or len(words) < 5:
        return max(0.0, start - 0.12), end + 0.18

    indices = phrase_word_indices(text, phrase)
    if not indices:
        return max(0.0, start - 0.12), end + 0.18

    first, last = indices
    before_words = 7 if review_mode else 5
    after_words = 7 if review_mode else 5
    window_first = max(0, first - before_words)
    window_after_last = min(len(words), last + 1 + after_words)
    media_start = start + duration * (window_first / max(1, len(words))) - 0.2
    media_end = start + duration * (window_after_last / max(1, len(words))) + 0.28
    media_start = max(0.0, media_start)
    media_end = min(end + 0.35, media_end)

    if media_end - media_start < 2.1:
        center = (media_start + media_end) / 2
        media_start = max(0.0, center - 1.05)
        media_end = center + 1.05
    if media_end - media_start > 6.2:
        center = (media_start + media_end) / 2
        media_start = max(0.0, center - 3.1)
        media_end = center + 3.1
    return round(media_start, 3), round(media_end, 3)


def refine_segment_media_for_phrase(
    segment: dict[str, Any],
    phrase: str,
    review_mode: bool = False,
) -> dict[str, Any]:
    """Keep exported media centered on the final learning phrase.

    Candidate building can keep a broad sentence for MIMO review. Once MIMO
    chooses the actual phrase, recompute the clip window so video/original audio
    and the final card focus do not drift apart.
    """
    if not phrase or not phrase_word_indices(str(segment.get("text") or ""), phrase):
        return segment
    try:
        start = float(segment.get("start") or 0)
        end = float(segment.get("end") or start)
    except (TypeError, ValueError):
        return segment
    media_start, media_end = segment_media_bounds(
        start,
        end,
        str(segment.get("text") or ""),
        phrase,
        review_mode,
    )
    return {
        **segment,
        "media_start": media_start,
        "media_end": media_end,
        "media_source_time": f"{fmt_time(media_start)} - {fmt_time(media_end)}",
    }


def normalize_candidate_span(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip(" \t\r\n\"'“”‘’.,?!"))


def expression_span_from_text(text: str, pattern: str) -> str:
    match = re.search(pattern, text, re.IGNORECASE)
    return normalize_candidate_span(match.group(0)) if match else ""


def usable_learning_point_span(
    text: str,
    span: str,
    candidate_kind: str = "expression",
    phrase_type: str = "",
) -> bool:
    normalized = normalize_candidate_span(span)
    if not normalized or normalized.lower() == "key expression":
        return False
    words = overlap_words(normalized)
    if not words:
        return False
    if not phrase_in_text(text, normalized) and len(words) >= 2:
        return False
    kind = candidate_kind or candidate_kind_for_phrase_type(phrase_type)
    if kind == "contextual_vocab":
        return 1 <= len(words) <= 3
    if kind in {"grammar_pattern", "listening_feature"}:
        return len(words) <= 12
    if kind in {"expression", "pragmatic_risk"} and phrase_type in {"collocation", "idiom", "spoken_phrase"}:
        if 2 <= len(words) <= 7 and phrase_in_text(text, normalized):
            if not is_non_transferable_phrase(normalized) and not is_low_value_standalone_phrase(normalized):
                if words[0] not in COMMON_FUNCTION_STARTS or allows_function_start_phrase(normalized):
                    return True
    return usable_phrase(text, normalized)


def typed_candidate_score(base_score: float, boost: float, kind: str) -> float:
    if kind == "contextual_vocab":
        return max(3.0, base_score + boost)
    if kind == "grammar_pattern":
        return max(3.2, base_score + boost)
    if kind == "listening_feature":
        return max(2.9, base_score + boost)
    if kind == "pragmatic_risk":
        return max(3.6, base_score + boost)
    return max(3.0, base_score + boost)


def typed_learning_point_candidates(
    text: str,
    phrase: str,
    base_score: float,
    level: str,
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add_candidate(
        span: str,
        *,
        candidate_kind: str,
        phrase_type: str = "",
        normalized_answer: str = "",
        boost: float = 0.0,
        focus: str = "",
        source: str = "rule",
    ) -> None:
        if not candidate_kind_allowed_by_focus(candidate_kind, payload):
            return
        final_phrase_type = phrase_type or phrase_type_for_candidate_kind(candidate_kind)
        answer = normalize_candidate_span(normalized_answer or span)
        exact_span = normalize_candidate_span(span)
        if not usable_learning_point_span(text, exact_span, candidate_kind, final_phrase_type):
            return
        key = (answer.lower(), candidate_kind)
        if key in seen:
            return
        seen.add(key)
        content_kind = content_kind_for_phrase_type(final_phrase_type, "phrase")
        score = typed_candidate_score(base_score, boost, candidate_kind)
        candidates.append(
            {
                "phrase": answer,
                "exact_span": exact_span,
                "normalized_answer": answer,
                "answer_core": answer,
                "candidate_kind": candidate_kind,
                "phrase_type": final_phrase_type,
                "content_kind": content_kind,
                "candidate_source": source,
                "learning_point_schema_version": LEARNING_POINT_SCHEMA_VERSION,
                "phrase_card_focus": focus,
                "source_evidence": text,
                "score": score,
                "recommendation": min(5, max(1, round(score))),
            }
        )

    if phrase and usable_learning_point_span(text, phrase, "expression", ""):
        add_candidate(phrase, candidate_kind="expression", boost=0.2, focus="训练原句里的可迁移自然表达。", source="local_phrase")

    for pattern, phrase_type, kind, boost, focus in TYPED_EXPRESSION_PATTERNS:
        span = expression_span_from_text(text, pattern)
        if span:
            add_candidate(span, candidate_kind=kind, phrase_type=phrase_type, boost=boost, focus=focus)

    lower = text.lower()
    for pattern, answer, boost, focus in CONTEXTUAL_VOCAB_PATTERNS:
        if not re.search(pattern, lower, re.IGNORECASE):
            continue
        if answer == "register" and "run the register" not in lower:
            continue
        if answer == "add" and not re.search(r"\b(?:add|adds|added|adding)\s+ten\s+pounds\b", lower):
            continue
        exact = expression_span_from_text(text, pattern)
        add_candidate(
            exact or answer,
            candidate_kind="contextual_vocab",
            phrase_type="vocabulary_usage",
            normalized_answer=answer,
            boost=boost,
            focus=focus,
        )

    for pattern, answer, boost, focus in GRAMMAR_PATTERN_RULES:
        span = expression_span_from_text(text, pattern)
        if span:
            add_candidate(
                span,
                candidate_kind="grammar_pattern",
                phrase_type="grammar_pattern",
                normalized_answer=answer,
                boost=boost,
                focus=focus,
            )

    listening_match = LISTENING_FEATURE_RE.search(text)
    if listening_match and has_listening_training_value(text):
        add_candidate(
            listening_match.group(0),
            candidate_kind="listening_feature",
            phrase_type="listening_sentence",
            normalized_answer=normalize_candidate_span(listening_match.group(0)),
            boost=0.4,
            focus="训练弱读、缩读、连读或真实语速下的听辨。",
        )

    return sorted(candidates, key=lambda item: float(item.get("score") or 0), reverse=True)


def review_candidate_mode(payload: dict[str, Any], max_segments: int, candidate_limit: int) -> bool:
    return bool(payload.get("_candidate_limit") and candidate_limit > max_segments)


def build_segments(cues: list[Cue], payload: dict[str, Any]) -> list[dict[str, Any]]:
    level = payload.get("level", "B1")
    collection_levels = collection_levels_from_payload(payload, level)
    toggles = payload.get("content_toggles", {})
    max_segments = resolved_max_segments(payload, cues)
    candidate_limit = int(payload.get("_candidate_limit", max_segments))
    review_mode = review_candidate_mode(payload, max_segments, candidate_limit)
    max_duration = 6.4 if review_mode else 5.4
    max_words = 22 if review_mode else 16
    min_discovery_score = 2.6 if review_mode else 4.0
    min_candidate_score = 2.8 if review_mode else 3.2
    min_context_score = 1.8 if review_mode else 2.4

    candidates: list[dict[str, Any]] = []
    i = 0
    while i < len(cues):
        start = cues[i].start
        end = cues[i].end
        parts = [cues[i].text]
        j = i

        while end - start < 3.0 and j + 1 < len(cues):
            gap = cues[j + 1].start - end
            if gap > 0.9:
                break
            current_text = merge_subtitle_parts(parts)
            if looks_complete_sentence(current_text) and end - start >= 1.4:
                break
            next_text = strip_subtitle_text(cues[j + 1].text)
            if is_filler_text(next_text) and looks_complete_sentence(current_text):
                break
            j += 1
            end = cues[j].end
            parts.append(cues[j].text)

        text = clean_candidate_text(merge_subtitle_parts(parts))
        duration = end - start
        words = re.findall(r"[A-Za-z']+", text)
        if has_unbalanced_quotes(text):
            i = max(j + 1, i + 1)
            continue

        terminal_count = len(re.findall(r"[.?!]+", text))
        min_duration = 1.4 if looks_complete_sentence(text) else 2.5
        normal_window = min_duration <= duration <= max_duration and 4 <= len(words) <= max_words
        typed_window = 0.6 <= duration <= (8.8 if review_mode else 7.2) and 1 <= len(words) <= max(max_words, 30)
        if typed_window and terminal_count <= 1 and content_allowed(text, toggles):
            if looks_like_video_intro(text):
                i = max(j + 1, i + 1)
                continue
            if re.search(r"\[[^\]]+\]|\([^\)]*(music|applause|laugh)[^\)]*\)", text, re.IGNORECASE):
                i = max(j + 1, i + 1)
                continue
            if not re.search(r"[.?!][\"']?$", text) and any(mark in text for mark in ".?!"):
                i = max(j + 1, i + 1)
                continue
            score = score_text(text, level, toggles, collection_levels)
            phrase = find_phrase(text, level, collection_levels)
            phrase_is_usable = usable_phrase(text, phrase)
            typed_candidates = typed_learning_point_candidates(text, phrase, score, level, payload)
            if phrase_is_usable and is_too_basic_for_level(phrase, level):
                score -= 0.4 if review_mode else 2.2
                typed_candidates = typed_learning_point_candidates(text, phrase, score, level, payload)
            if starts_like_fragment(text):
                if not review_mode and not phrase_is_usable and not typed_candidates:
                    i = max(j + 1, i + 1)
                    continue
                score -= 0.5
                typed_candidates = typed_learning_point_candidates(text, phrase, score, level, payload)
            if not normal_window and not typed_candidates:
                i = max(j + 1, i + 1)
                continue
            if score < min_context_score and not typed_candidates:
                i = max(j + 1, i + 1)
                continue
            if not phrase_is_usable:
                if phrase == "key expression" and score >= min_discovery_score:
                    # Vlogs and casual videos contain many useful spoken chunks that
                    # do not match our small local expression list. Keep strong short
                    # sentences and let the model decide whether a real phrase exists.
                    score = max(min_candidate_score, score - 0.6)
                else:
                    score -= 2.6
                if score < min_candidate_score and not typed_candidates:
                    i = max(j + 1, i + 1)
                    continue
            if not typed_candidates:
                typed_candidates = [
                    {
                        "phrase": phrase,
                        "exact_span": phrase,
                        "normalized_answer": phrase,
                        "answer_core": phrase if phrase != "key expression" else "",
                        "candidate_kind": "expression",
                        "phrase_type": "spoken_phrase",
                        "content_kind": "phrase",
                        "candidate_source": "legacy_phrase",
                        "learning_point_schema_version": LEARNING_POINT_SCHEMA_VERSION,
                        "phrase_card_focus": "围绕这个表达的真实语境和迁移用法制卡。",
                        "source_evidence": text,
                        "score": score,
                        "recommendation": min(5, max(1, round(score))),
                    }
                ]
            for typed in typed_candidates:
                segment_phrase = str(typed.get("exact_span") or typed.get("phrase") or phrase)
                media_start, media_end = segment_media_bounds(start, end, text, segment_phrase, review_mode)
                candidate_score = float(typed.get("score") or score)
                candidates.append(
                    {
                    "id": f"seg_{len(candidates) + 1:04d}",
                    "start": round(start, 3),
                    "end": round(end, 3),
                    "source_time": f"{fmt_time(start)} - {fmt_time(end)}",
                    "media_start": media_start,
                    "media_end": media_end,
                    "media_source_time": f"{fmt_time(media_start)} - {fmt_time(media_end)}",
                    "text": text,
                    "duration": round(duration, 2),
                    "recommendation": min(5, max(1, round(candidate_score))),
                    "phrase": typed.get("phrase") or segment_phrase,
                    "exact_span": typed.get("exact_span") or segment_phrase,
                    "normalized_answer": typed.get("normalized_answer") or typed.get("phrase") or segment_phrase,
                    "answer_core": typed.get("answer_core") or typed.get("normalized_answer") or typed.get("phrase") or segment_phrase,
                    "candidate_kind": typed.get("candidate_kind") or "expression",
                    "phrase_type": typed.get("phrase_type") or "spoken_phrase",
                    "content_kind": typed.get("content_kind") or "phrase",
                    "candidate_source": typed.get("candidate_source") or "rule",
                    "learning_point_schema_version": typed.get("learning_point_schema_version") or LEARNING_POINT_SCHEMA_VERSION,
                    "phrase_card_focus": typed.get("phrase_card_focus") or "",
                    "source_evidence": typed.get("source_evidence") or text,
                    "score": candidate_score,
                }
                )

        i = max(j + 1, i + 1)

    selected = sorted(candidates, key=lambda item: item["score"], reverse=True)[:candidate_limit]
    return sorted(selected, key=lambda item: item["start"])


def fallback_phrase_fields(text: str, phrase: str, level: str) -> dict[str, str]:
    if not phrase or phrase == "key expression":
        return {
            "phrase": "",
            "chinese": "本地待审：这句需要先确认真正值得学习的表达。",
            "definition": "系统没有在原句中找到稳定、完整、可迁移的表达；建议用作听力待审，不要直接导出为表达卡。",
            "collocations": "",
            "context": "适合人工复核是否有听力难点或隐藏表达。",
            "example": text,
            "chinese_feel": "待精修：需要结合上下文改成自然中文。",
            "why": "缺少明确词伙时默认不推荐导出，避免把占位内容做成废卡。",
            "difficulty": CEFR_LABELS.get(level, level),
        }
    guide = PHRASE_GUIDES.get(phrase_guide_key(phrase), {})
    if guide:
        return {
            "phrase": phrase,
            "difficulty": CEFR_LABELS.get(level, level),
            "teacher_note": guide.get(
                "teacher_note",
                f"把 {phrase} 当作一个整体记；复习时先听懂原句，再换一个场景自己说一遍。",
            ),
            "_quality_source": "curated_fallback",
            **guide,
        }
    return {
        "phrase": phrase,
        "chinese": f"待精修：先把 {phrase} 当作本句目标表达。",
        "definition": f"本地待审：先把 {phrase} 当作本句目标表达，正式导出前需要用 AI 精修释义。",
        "collocations": f"{phrase} + natural object / use {phrase} in a complete sentence",
        "context": "本地待审字段：适合快速预览流程，不建议直接作为正式学习内容。",
        "example": text,
        "chinese_feel": "待精修：需要结合上下文改成自然中文。",
        "why": "本地 fallback 只保证结构完整；正式导出前应使用模型精修内容。",
        "difficulty": CEFR_LABELS.get(level, level),
    }


def phrase_in_text(text: str, phrase: str) -> bool:
    normalized_text = " ".join(overlap_words(text))
    normalized_phrase = " ".join(overlap_words(phrase))
    if not normalized_phrase:
        return False
    if normalized_phrase in normalized_text:
        return True

    phrase_words = normalized_phrase.split()
    text_words = normalized_text.split()
    if len(phrase_words) < 2:
        return False

    def word_matches(pattern_word: str, text_word: str) -> bool:
        if pattern_word in {"someone", "somebody"}:
            return text_word in {"me", "you", "him", "her", "us", "them", "someone", "somebody"}
        if pattern_word == "something":
            return text_word in {"it", "this", "that", "things", "something", "everything"}
        return pattern_word == text_word

    max_extra_words = 2
    for first in [index for index, word in enumerate(text_words) if word_matches(phrase_words[0], word)]:
        position = first
        extra_words = 0
        matched = 1
        for phrase_word in phrase_words[1:]:
            found = -1
            scan_end = min(len(text_words), position + max_extra_words + 3)
            for index in range(position + 1, scan_end):
                if word_matches(phrase_word, text_words[index]):
                    found = index
                    break
            if found == -1:
                break
            extra_words += found - position - 1
            if extra_words > max_extra_words:
                break
            position = found
            matched += 1
        if matched == len(phrase_words):
            return True
    return False


def quality_issue_labels(
    card_type: str,
    text: str,
    phrase: str,
    cloze: str,
    source: str,
    content_kind: str = "",
    candidate_kind: str = "",
) -> tuple[int, list[str]]:
    is_listening = card_type == "listening"
    is_vocab = content_kind == "vocabulary" or candidate_kind == "contextual_vocab"
    is_grammar = content_kind == "grammar" or candidate_kind == "grammar_pattern"
    is_expression_like = not is_listening and not is_vocab and not is_grammar
    if source == "ai":
        score = 92
    elif source == "curated_fallback":
        score = 78
    else:
        score = 64 if is_listening else 52
    issues: list[str] = []
    words = overlap_words(phrase)
    text_words = overlap_words(text)
    trailing_prepositions = {"about", "of", "for", "to", "with", "from", "by", "at"}

    if source == "curated_fallback":
        issues.append("本地规则卡，需要人工确认")
        score -= 4
    elif source != "ai":
        issues.append("本地草稿，需要人工确认")
        score -= 18
    if not text_words:
        issues.append("缺少英文原句")
        score -= 34
    if not is_listening and (not phrase or phrase == "key expression"):
        issues.append("缺少明确目标表达")
        score -= 28
    if is_expression_like and len(words) < 2:
        issues.append("目标表达过短")
        score -= 14
    if is_expression_like and len(words) > 6:
        issues.append("目标表达偏长")
        score -= 24
    if is_expression_like and len(words) >= max(4, len(text_words) - 1) and len(text_words) >= 5:
        issues.append("目标表达像整句而不是词伙")
        score -= 28
    if len(text_words) > 15:
        issues.append("原句偏长")
        score -= 12
    if card_type in {"phrase", "cloze"} and len(text_words) > 12:
        issues.append("词伙任务原句太长")
        score -= 22
    if len(text_words) > 20:
        issues.append("原句太长，不适合做表达卡")
        score -= 18
    if starts_like_fragment(text):
        issues.append("原句像截断片段")
        score -= 18
    phrase_lower = phrase.lower()
    if is_expression_like and is_non_transferable_phrase(phrase_lower):
        issues.append("表达太像视频口播引入语")
        score -= 30
    if is_expression_like and is_low_value_standalone_phrase(phrase_lower):
        issues.append("目标表达太泛，学习价值低")
        score -= 26
    if looks_like_video_intro(text):
        issues.append("原句太像视频口播引入语")
        score -= 28
    allows_trailing_preposition = bool(
        re.search(r"\btell\s+\w+\s+about\b", phrase_lower)
        or phrase_lower
        in {
            "working with",
            "deal with",
            "talk about",
            "look for",
            "come up with",
            "get away with",
            "opening doors to",
            "connect with",
            "full of",
            "get used to",
            "feel free to",
            "in the mood for",
            "a bit of",
            "a couple of",
            "a lot of",
            "at the end of",
            "kind of",
            "sort of",
            "make the most of",
            "the kind of",
            "this kind of",
            "that kind of",
            "what do you think about",
            "how do you feel about",
        }
    )
    if is_expression_like and words and words[-1] in trailing_prepositions and not allows_trailing_preposition:
        issues.append("表达像半截词串")
        score -= 18
    if is_expression_like and words and words[0] in COMMON_FUNCTION_STARTS and not allows_function_start_phrase(phrase):
        issues.append("表达可能从功能词开头")
        score -= 16
    if is_expression_like and words and words[0] == "about" and re.search(r"\babout\s+[A-Z0-9][A-Za-z0-9-]*", phrase):
        issues.append("表达像主题名而不是可迁移词伙")
        score -= 24
    if not is_listening and phrase and len(words) >= 2 and not phrase_in_text(text, phrase):
        issues.append("表达和原句不完全匹配")
        score -= 12
    if card_type == "cloze":
        blank_count = cloze.count("____")
        if blank_count != 1:
            issues.append("填空卡必须只有一个空")
            score -= 24
        if cloze.strip() == text.strip():
            issues.append("填空卡没有真正挖空")
            score -= 24
        if len(words) > 5:
            issues.append("填空答案偏长")
            score -= 10
    if is_filler_text(text):
        issues.append("句子太像 filler")
        score -= 30
    if len(text_words) < 4:
        issues.append("上下文太短")
        score -= 12

    return max(0, min(100, score)), issues


def quality_from_score(score: int, issues: list[str]) -> dict[str, Any]:
    serious_issues = {
        "缺少英文原句",
        "缺少明确目标表达",
        "表达像半截词串",
        "表达可能从功能词开头",
        "表达像主题名而不是可迁移词伙",
        "目标表达偏长",
        "目标表达像整句而不是词伙",
        "表达和原句不完全匹配",
        "词伙任务原句太长",
        "填空卡必须只有一个空",
        "填空卡没有真正挖空",
        "字段疑似乱码",
        "缺少中文意思",
        "缺少释义",
        "句子太像 filler",
        "原句像截断片段",
        "表达太像视频口播引入语",
        "原句太像视频口播引入语",
        "目标表达太泛，学习价值低",
        "字段像模板废话",
        "中文意思不是中文",
        "搭配不自然",
        "例句只是照抄原句",
        "例句和原句过于相似",
        "老师提示和学习理由重复",
        "老师提示缺少具体用法",
        "释义太泛",
        "目标表达低于用户水平",
        "核心答案包含解释而不是英文答案",
        "词伙评审拒绝",
        "词伙重复合并",
    }
    has_serious_issue = any(issue in serious_issues for issue in issues)
    if score >= 78 and not issues:
        status = "recommended"
    elif score >= 72 and len(issues) <= 1 and not has_serious_issue:
        status = "recommended"
    elif score >= 42:
        status = "needs_review"
    else:
        status = "reject"
    return {"score": score, "status": status, "issues": issues}


def assess_card_quality(
    card: dict[str, Any],
    segment: dict[str, Any],
    source: str,
    target_level: str = "B1",
) -> dict[str, Any]:
    is_listening = card.get("type") == "listening"
    score, issues = quality_issue_labels(
        card.get("type", ""),
        card.get("english") or segment.get("text", ""),
        card.get("phrase", ""),
        card.get("cloze", ""),
        source,
        str(card.get("content_kind") or ""),
        str(card.get("candidate_kind") or ""),
    )
    text_fields = [
        card.get("english", ""),
        card.get("chinese", ""),
        card.get("phrase", ""),
        card.get("definition", ""),
        card.get("collocations", ""),
        card.get("context", ""),
        card.get("example", ""),
        card.get("chinese_feel", ""),
        card.get("why", ""),
        card.get("teacher_note", ""),
        card.get("learning_goal", ""),
        card.get("decision_reason", ""),
        card.get("learning_target", ""),
        card.get("why_it_matters", ""),
        card.get("how_to_use_it", ""),
    ]
    if any("???" in str(value) or "\ufffd" in str(value) for value in text_fields):
        issues.append("字段疑似乱码")
        score -= 36
    answer_core = str(card.get("answer_core") or "").strip()
    displayed_answer_core = answer_display_text(answer_core)
    if (
        not is_listening
        and answer_core
        and (
            displayed_answer_core != clean_study_text(answer_core)
            or not is_answer_expression_candidate(displayed_answer_core, card)
        )
    ):
        issues.append("核心答案包含解释而不是英文答案")
        score -= 32
    field_blob = "\n".join(str(value or "") for value in text_fields)
    if any(re.search(pattern, field_blob, flags=re.IGNORECASE) for pattern in TEMPLATE_NOISE_PATTERNS):
        issues.append("字段像模板废话")
        score -= 30
    chinese_value = str(card.get("chinese", "") or "").strip()
    if chinese_value and not has_cjk(chinese_value):
        issues.append("中文意思不是中文")
        score -= 22
    phrase_lower = re.sub(r"\s+", " ", str(card.get("phrase", "") or "").strip().lower())
    collocations_lower = str(card.get("collocations", "") or "").lower()
    if phrase_lower and f"not really {phrase_lower}" in collocations_lower and phrase_lower not in {"in the mood"}:
        issues.append("搭配不自然")
        score -= 24
    example_lower = re.sub(r"\s+", " ", str(card.get("example", "") or "").strip().lower())
    english_lower = re.sub(r"\s+", " ", str((card.get("english") or segment.get("text", "")) or "").strip().lower())
    if not is_listening and example_lower and english_lower and example_lower == english_lower:
        issues.append("例句只是照抄原句")
        score -= 14
    elif (
        not is_listening
        and example_lower
        and english_lower
        and len(overlap_words(example_lower)) >= 4
        and word_overlap_ratio(example_lower, english_lower) >= 0.82
    ):
        issues.append("例句和原句过于相似")
        score -= 14
    if not str(card.get("chinese", "")).strip():
        issues.append("缺少中文意思")
        score -= 22
    if card.get("type") in {"phrase", "cloze"} and not str(card.get("definition", "")).strip():
        issues.append("缺少释义")
        score -= 18
    if card.get("type") in {"phrase", "cloze"} and has_generic_definition(str(card.get("definition", ""))):
        issues.append("释义太泛")
        score -= 20
    teacher_note = str(card.get("teacher_note", "") or "").strip()
    if len(teacher_note) < 8:
        issues.append("老师提示太薄")
        score -= 8
    if teacher_note and has_generic_teacher_note(teacher_note):
        issues.append("老师提示缺少具体用法")
        score -= 18
    comparable_teacher_note = re.sub(r"\s+", " ", teacher_note)
    for key in ["why", "context", "chinese_feel"]:
        comparable_value = re.sub(r"\s+", " ", str(card.get(key, "") or "").strip())
        if not is_listening and comparable_teacher_note and comparable_value and comparable_teacher_note == comparable_value:
            issues.append("老师提示和学习理由重复")
            score -= 14
            break
        if (
            not is_listening
            and comparable_teacher_note
            and comparable_value
            and min(len(overlap_words(comparable_teacher_note)), len(overlap_words(comparable_value))) >= 6
            and word_overlap_ratio(comparable_teacher_note, comparable_value) >= 0.86
        ):
            issues.append("老师提示和学习理由重复")
            score -= 14
            break
    action_fields = [
        card.get("learning_goal", ""),
        card.get("decision_reason", ""),
        card.get("phrase_card_focus", ""),
        card.get("learning_target", ""),
        card.get("how_to_use_it", ""),
    ]
    if source == "ai" and not any(str(value or "").strip() for value in action_fields):
        issues.append("卡片训练点不明确")
        score -= 10
    if not is_listening and is_too_basic_for_level(phrase_lower, target_level):
        issues.append("目标表达低于用户水平")
        score -= 30
    difficulty_rank = cefr_rank(str(card.get("difficulty", "")))
    target_rank = cefr_rank(target_level)
    if target_rank >= cefr_rank("B1") and 0 <= difficulty_rank <= cefr_rank("A1"):
        issues.append("难度低于用户水平")
        score -= 18
    review_status = str(card.get("phrase_review_status") or segment.get("phrase_review_status") or "").strip()
    phrase_value_score = phrase_review_score(card.get("phrase_value_score", segment.get("phrase_value_score")))
    if review_status == "needs_review" or phrase_value_score == 3:
        issues.append("词伙评审待审")
        score = min(score, 70)
    elif review_status == "reject" or (0 < phrase_value_score < 3):
        issues.append("词伙评审拒绝")
        score = min(score, 34)
    elif review_status == "duplicate":
        issues.append("词伙重复合并")
        score = min(score, 34)
    elif phrase_value_score >= 4 and not issues:
        score = min(100, score + 4)
    return quality_from_score(score, issues)


def make_cloze(text: str, phrase: str) -> str:
    if not phrase:
        return text
    pattern = re.compile(re.escape(phrase), re.IGNORECASE)
    if pattern.search(text):
        return pattern.sub("____", text, count=1)
    words = re.findall(r"[A-Za-z']+", text)
    if words:
        return re.sub(re.escape(words[-1]), "____", text, count=1, flags=re.IGNORECASE)
    return "____"


def phrase_allows_trailing_preposition(phrase: str) -> bool:
    phrase_lower = phrase.lower()
    return bool(
        re.search(r"\btell\s+\w+\s+about\b", phrase_lower)
        or phrase_lower
        in {
            "working with",
            "deal with",
            "talk about",
            "look for",
            "come up with",
            "get away with",
            "opening doors to",
            "connect with",
            "full of",
            "get used to",
            "feel free to",
            "in the mood for",
            "what do you think about",
            "how do you feel about",
        }
    )


def usable_phrase(text: str, phrase: str) -> bool:
    words = overlap_words(phrase)
    text_words = overlap_words(text)
    if not phrase or phrase == "key expression":
        return False
    if len(words) < 2 or len(words) > 6:
        return False
    if len(words) >= max(4, len(text_words) - 1) and len(text_words) >= 5:
        return False
    if is_non_transferable_phrase(phrase):
        return False
    if is_low_value_standalone_phrase(phrase):
        return False
    if (words[0] in COMMON_FUNCTION_STARTS or words[0] in WEAK_PHRASE_STARTS) and not allows_function_start_phrase(phrase):
        return False
    trailing_prepositions = {"about", "of", "for", "to", "with", "from", "by", "at"}
    if words[-1] in trailing_prepositions and not phrase_allows_trailing_preposition(phrase):
        return False
    return phrase_in_text(text, phrase)


def choose_best_phrase(text: str, proposed: str, fallback: str, level: str, collection_levels: list[str] | None = None) -> str:
    candidates = [proposed, fallback, find_phrase(text, level, collection_levels)]
    seen: set[str] = set()
    for candidate in candidates:
        normalized = re.sub(r"\s+", " ", str(candidate or "")).strip()
        key = normalized.lower()
        if not normalized or key in seen:
            continue
        seen.add(key)
        if usable_phrase(text, normalized):
            return normalized
    return ""


def repair_card_fields(card: dict[str, Any], segment: dict[str, Any], level: str) -> None:
    text = card.get("english") or segment.get("text", "")
    reviewed_phrase = str(segment.get("phrase") or "").strip()
    candidate_kind = str(card.get("candidate_kind") or segment.get("candidate_kind") or "")
    phrase_type = str(card.get("phrase_type") or segment.get("phrase_type") or "")
    if not candidate_kind:
        candidate_kind = candidate_kind_for_phrase_type(phrase_type, candidate_kind_for_segment(segment))
    preferred_phrase = (
        str(card.get("normalized_answer") or "").strip()
        or str(card.get("answer_core") or "").strip()
        or str(card.get("phrase") or "").strip()
        or str(segment.get("normalized_answer") or "").strip()
        or reviewed_phrase
    )
    if usable_learning_point_span(text, preferred_phrase, candidate_kind, phrase_type):
        phrase = normalize_candidate_span(preferred_phrase)
    elif segment.get("phrase_review_source") in {"mimo", "ai"} and usable_learning_point_span(text, reviewed_phrase, candidate_kind, phrase_type):
        phrase = reviewed_phrase
    elif candidate_kind in {"contextual_vocab", "grammar_pattern", "listening_feature"}:
        phrase = normalize_candidate_span(reviewed_phrase or str(card.get("phrase") or ""))
    else:
        phrase = choose_best_phrase(text, card.get("phrase", ""), segment.get("phrase", ""), level)
    if phrase != card.get("phrase"):
        card["phrase"] = phrase
    if candidate_kind:
        card["candidate_kind"] = candidate_kind
    if not str(card.get("exact_span") or "").strip():
        card["exact_span"] = str(segment.get("exact_span") or phrase)
    if not str(card.get("normalized_answer") or "").strip():
        card["normalized_answer"] = str(segment.get("normalized_answer") or phrase)
    sanitized_answer = answer_display_text(card.get("answer_core"))
    if not is_answer_expression_candidate(sanitized_answer, card):
        sanitized_answer = phrase if is_answer_expression_candidate(phrase, card) else ""
    if sanitized_answer:
        card["answer_core"] = sanitized_answer
    card["cloze"] = make_cloze(text, phrase)


def normalize_learning_action_fields(card: dict[str, Any]) -> None:
    learning_target = normalized_action_text(card.get("learning_target"))
    why_it_matters = normalized_action_text(card.get("why_it_matters"))
    how_to_use_it = normalized_action_text(card.get("how_to_use_it"))
    natural_chinese = normalized_action_text(card.get("natural_chinese"))
    replacement_examples = normalized_action_text(card.get("replacement_examples"))
    avoid_reason = normalized_action_text(card.get("avoid_reason"))
    usage_boundary = normalized_action_text(card.get("usage_boundary"))
    confusable_note = normalized_action_text(card.get("confusable_note"))

    if natural_chinese and (not str(card.get("chinese") or "").strip() or not has_cjk(str(card.get("chinese") or ""))):
        card["chinese"] = natural_chinese
    learning_goal = str(card.get("learning_goal") or "").strip()
    if learning_target and (
        not learning_goal
        or "核心价值" in learning_goal
        or "额外能力点" in learning_goal
        or "这张卡训练什么" in learning_goal
    ):
        card["learning_goal"] = learning_target
    why = str(card.get("why") or "").strip()
    if why_it_matters and (
        not why
        or "本地 fallback" in why
        or "正式导出前" in why
        or "为什么值得学" in why
    ):
        card["why"] = why_it_matters
    context = str(card.get("context") or "").strip()
    if how_to_use_it and (
        not context
        or "本地待审字段" in context
        or "review page" in context.lower()
    ):
        card["context"] = how_to_use_it
    collocations = str(card.get("collocations") or "").strip()
    if replacement_examples and (
        not collocations
        or "natural object" in collocations.lower()
        or "complete sentence" in collocations.lower()
        or collocations.lower().startswith("use ")
    ):
        card["collocations"] = replacement_examples
    if avoid_reason and not str(card.get("phrase_reject_reason") or "").strip():
        card["phrase_reject_reason"] = avoid_reason

    teacher_note = str(card.get("teacher_note") or "").strip()
    if (not teacher_note or has_generic_teacher_note(teacher_note)) and how_to_use_it:
        card["teacher_note"] = how_to_use_it
        teacher_note = str(card.get("teacher_note") or "").strip()
    extra_notes = []
    if usage_boundary:
        extra_notes.append(f"使用边界：{usage_boundary}")
    if confusable_note:
        extra_notes.append(f"易错提醒：{confusable_note}")
    if extra_notes:
        merged_note = "；".join(extra_notes)
        if teacher_note and merged_note not in teacher_note:
            card["teacher_note"] = f"{teacher_note}；{merged_note}"
        elif not teacher_note:
            card["teacher_note"] = merged_note
    if has_generic_definition(str(card.get("definition", ""))) and learning_target:
        card["definition"] = learning_target

    comparable_teacher_note = re.sub(r"\s+", " ", str(card.get("teacher_note") or "").strip())
    for key, replacement in [
        ("why", learning_target or how_to_use_it),
        ("context", learning_target or why_it_matters),
        ("chinese_feel", how_to_use_it or why_it_matters),
    ]:
        comparable_value = re.sub(r"\s+", " ", str(card.get(key, "") or "").strip())
        if comparable_teacher_note and comparable_value and comparable_teacher_note == comparable_value and replacement:
            card["teacher_note"] = replacement
            break


def requested_card_types(card_types: list[str]) -> list[str]:
    requested = [str(card_type) for card_type in card_types if card_type in {"listening", "phrase", "cloze"}]
    return requested or ["phrase"]


def has_listening_training_value(text: str) -> bool:
    lower = str(text or "").lower()
    words = overlap_words(text)
    return bool(
        len(words) >= 8
        and (
            re.search(r"\b(?:i'm|you're|we're|they're|don't|can't|won't|i've|let's)\b", lower)
            or re.search(r"\b(?:gonna|wanna|gotta)\b", lower)
        )
    )


def has_output_training_value(phrase: str, level: str) -> bool:
    lower = re.sub(r"\s+", " ", str(phrase or "").strip().lower())
    if is_too_basic_for_level(lower, level):
        return False
    low_value_output_phrases = {
        "by the way",
        "make sure",
        "talk about",
        "talking about",
        "what about",
        "how about",
    }
    if lower in low_value_output_phrases:
        return False
    output_worthy_phrases = {"in the mood for", "end up", "turn out", "figure out", "make sense", "i see what you mean"}
    return bool(
        lower in output_worthy_phrases
        or phrase_guide_key(lower) in output_worthy_phrases
    )


def plan_card_types(segment: dict[str, Any], card_types: list[str], level: str) -> dict[str, Any]:
    requested = requested_card_types(card_types)
    phrase = re.sub(r"\s+", " ", str(segment.get("phrase") or "").strip())
    text = str(segment.get("text") or "")
    candidate_kind = candidate_kind_for_segment(segment)

    if candidate_kind == "listening_feature" and "listening" in requested:
        primary = "listening"
        reason = "这个片段的核心价值是听懂真实语速下的弱读、连读或缩读。"
    elif "phrase" in requested and usable_learning_point_span(text, phrase, candidate_kind, str(segment.get("phrase_type") or "")):
        primary = "phrase"
        if candidate_kind == "contextual_vocab":
            reason = "这个片段的核心价值是掌握一个词在原句里的真实语境义。"
        elif candidate_kind == "grammar_pattern":
            reason = "这个片段的核心价值是掌握一个可迁移的语法/句法框架。"
        elif candidate_kind == "pragmatic_risk":
            reason = "这个片段的核心价值是理解表达的语气、边界和冒犯风险。"
        else:
            reason = "这个片段的核心价值是把自然表达迁移到自己的口语里。"
    elif "listening" in requested:
        primary = "listening"
        reason = "这个片段更适合先做听音辨句，表达本身不够适合作为主词伙。"
    else:
        primary = requested[0]
        reason = "按用户选择的卡型保留一张主训练卡。"

    planned = [primary]
    optional: list[str] = []
    skipped: dict[str, str] = {}

    if "listening" in requested and primary != "listening":
        if has_listening_training_value(text):
            optional.append("listening")
        else:
            skipped["listening"] = "听力难点不明显，合并到主卡里即可。"
    if "cloze" in requested and primary != "cloze":
        if has_output_training_value(phrase, level):
            optional.append("cloze")
        else:
            skipped["cloze"] = "表达偏基础或输出价值不足，不单独做填空卡。"
    if "phrase" in requested and primary != "phrase":
        skipped["phrase"] = "没有稳定、完整、可迁移的表达，不单独做表达卡。"

    # Default to one card. Allow only one genuinely different specialist card.
    if optional:
        planned.append(optional[0])
        for card_type in optional[1:]:
            skipped[card_type] = "已有主卡和一个专项卡，避免同一句重复刷三遍。"

    for card_type in requested:
        if card_type not in planned and card_type not in skipped:
            skipped[card_type] = "训练目标已被主卡覆盖。"

    return {
        "primary": primary,
        "types": planned,
        "reason": reason,
        "skipped": skipped,
    }


def fallback_cards(segment: dict[str, Any], card_types: list[str], level: str) -> list[dict[str, Any]]:
    fields = fallback_phrase_fields(segment["text"], segment["phrase"], level)
    quality_source = fields.pop("_quality_source", "fallback")
    plan = plan_card_types(segment, card_types, level)
    cards: list[dict[str, Any]] = []
    for card_type in plan["types"]:
        card = {
            "id": f"{segment['id']}_{card_type}",
            "type": card_type,
            "type_label": CARD_TYPE_LABELS.get(card_type, card_type),
            "enabled": False,
            "english": segment["text"],
            "chinese": "本地草稿：请在预览页用模型精修或手动改成自然中文。",
            "cloze": make_cloze(segment["text"], fields["phrase"]),
            "teacher_note": fields.get("teacher_note") or fields["why"],
            "card_role": "primary" if card_type == plan["primary"] else "specialist",
            "learning_goal": plan["reason"] if card_type == plan["primary"] else "这张专项卡只训练一个额外能力点，避免和主卡重复。",
            "decision_reason": plan["reason"],
            "learning_target": plan["reason"],
            "why_it_matters": fields.get("why", ""),
            "how_to_use_it": fields.get("context", ""),
            "natural_chinese": fields.get("chinese", ""),
            "replacement_examples": fields.get("collocations", ""),
            "avoid_reason": "",
            "skipped_card_types": plan["skipped"],
            "phrase_value_score": segment.get("phrase_value_score"),
            "phrase_decision_reason": segment.get("phrase_decision_reason", ""),
            "phrase_reject_reason": segment.get("phrase_reject_reason", ""),
            "phrase_card_focus": segment.get("phrase_card_focus", ""),
            "phrase_review_status": segment.get("phrase_review_status", ""),
            "phrase_type": segment.get("phrase_type", ""),
            "content_kind": segment.get("content_kind") or content_kind_for_phrase_type(str(segment.get("phrase_type") or "")),
            "candidate_kind": segment.get("candidate_kind") or candidate_kind_for_segment(segment),
            "exact_span": segment.get("exact_span") or segment.get("phrase", ""),
            "normalized_answer": segment.get("normalized_answer") or segment.get("phrase", ""),
            "candidate_source": segment.get("candidate_source", ""),
            "learning_point_schema_version": segment.get("learning_point_schema_version") or LEARNING_POINT_SCHEMA_VERSION,
            "source_evidence": segment.get("source_evidence") or segment.get("text", ""),
            "retrieval_prompt": "",
            "answer_core": segment.get("answer_core") or segment.get("normalized_answer") or segment.get("phrase", ""),
            "usage_boundary": "",
            "confusable_note": "",
            **fields,
        }
        if card_type == "phrase":
            card["type_label"] = card_label_for_learning_card(
                str(card.get("phrase_type") or ""),
                str(card.get("content_kind") or ""),
                card["type_label"],
            )
        card_quality_source = quality_source if card_type == "phrase" else "fallback"
        card["quality"] = assess_card_quality(card, segment, card_quality_source, level)
        card["enabled"] = card_quality_source == "curated_fallback" and card["quality"]["status"] == "recommended"
        cards.append(card)
    return cards


def build_prompt(project: dict[str, Any], segments: list[dict[str, Any]]) -> str:
    requested_types = requested_card_types([str(card_type) for card_type in project.get("card_types", []) if card_type])
    current_level = str(project.get("level", "B1"))
    collection_levels = collection_levels_from_payload(project, current_level)
    focus_instruction = language_focus_instruction(project)
    material_context_instruction = material_context_for_prompt(project.get("material_context"))
    compact = [
        {
            "id": segment["id"],
            "source_time": segment["source_time"],
            "english": segment["text"],
            "phrase_hint": segment["phrase"],
            "exact_span": segment.get("exact_span", ""),
            "normalized_answer": segment.get("normalized_answer", ""),
            "candidate_kind": segment.get("candidate_kind", ""),
            "recommendation": segment["recommendation"],
            "phrase_value_score": segment.get("phrase_value_score"),
            "phrase_review_status": segment.get("phrase_review_status", ""),
            "phrase_decision_reason": segment.get("phrase_decision_reason", ""),
            "phrase_card_focus": segment.get("phrase_card_focus", ""),
            "phrase_type": segment.get("phrase_type", ""),
            "score_breakdown": segment.get("score_breakdown", {}),
        }
        for segment in segments
    ]
    return (
        "你是给中文母语者做英语 Anki 卡的资深老师。目标不是多写信息，而是让学习者翻面后立刻知道："
        "这句我该听懂什么、该记住哪个表达、以后怎么自己用。"
        "你不是字段填写器，而是英语学习卡片编辑老师：先判断学习价值，再决定是否制卡，最后自检这张卡是不是有明确训练动作。"
        f"{material_context_instruction}"
        "制卡前请在心里回答四个问题：这句最值得学的是什么？它是词伙、句型、口语短句、语气表达还是听力句？"
        "中文学习者为什么容易忽略它？这张卡训练听懂、会用、会替换还是理解语气？如果回答不清楚，返回 cards: []。"
        f"{focus_instruction}"
        "候选现在是 typed learning point：candidate_kind 可能是 expression/contextual_vocab/grammar_pattern/listening_feature/pragmatic_risk。"
        "制卡必须先尊重 candidate_kind 和 exact_span，再生成对应卡片；不要把所有候选都当词伙。"
        "contextual_vocab 允许 answer_core 是一个英文单词；grammar_pattern 允许 answer_core 是句型框架；"
        "listening_feature 的 answer_core 是要听辨的英文片段或原句，不是发音解释。"
        "请只为真正值得复习的片段生成卡；如果片段只是主题介绍、专有名词、技术名词堆叠或没有可迁移表达，返回该片段的 cards: []。"
        "内容标准："
        "1) phrase 必须来自原句：词伙通常 2-6 个词；单词用法可以是 1 个核心词；语法框架可以是原句里的可替换结构。"
        "它不能是整句、半截词串、产品名、主题名或 working with 这种孤立泛表达。"
        "如果候选里有 phrase_review_status 和 phrase_value_score，说明 AI 已经做过候选评审；正式制卡必须优先使用 phrase_hint，"
        "除非你能从同一句 english 里找到更完整、更可迁移的替代表达。替代表达仍必须逐词出现在原句里。"
        "如果 phrase_hint 是 key expression，说明本地规则没有识别出词伙；请你从 english 中自己选择最值得学的完整表达。"
        "如果句子里确实没有可迁移表达，返回该片段 cards: []，不要硬凑。"
        "如果用户水平是 B1 或更高，不要把 talk about 这类 A1/A2 基础短语当作重点；没有更具体表达就返回 cards: []。"
        "优先真实生活中可复用的短句、句型和口语框架，例如 it feels like、it turns out、what happens next、in the mood for、"
        "at some point、not because..., but because...、the thing is、I see what you mean、such a nice...。"
        "2) chinese 写 phrase 或单词在这句里的核心中文义，适合放在答案下方，例如“负责收银 / 操作收银机”；"
        "natural_chinese 写整句自然中文译文，例如“I’m gonna run the register.”=>“我来负责收银。”。"
        "3) definition 要写“怎么用”：这个表达通常用在什么动作/场景/对象上，面向学习者，不要词典腔，不要模板句。"
        "4) collocations 只能给自然搭配、句型框架或 1-2 个可直接模仿的新句子，用 ' / ' 分隔；不要编造不自然搭配，比如 not really + 任意 phrase。"
        "5) example 必须是新的短例句，不能照抄原句。"
        "6) context 说明什么场景会用；chinese_feel 说明中文语感；why 说明为什么值得学。每项 1 句即可。"
        "7) teacher_note 要按卡型聚焦：listening 说听力注意点；phrase 说怎么迁移使用；cloze 说挖空答案为什么是它。"
        "8) 每张卡还必须给学习动作字段：learning_target=这张卡训练什么；why_it_matters=为什么值得学；"
        "how_to_use_it=下次怎么换场景使用；natural_chinese=原句自然中文译文；replacement_examples=1-2 个可替换例子；"
        "avoid_reason=不值得制卡时的原因。how_to_use_it 和 replacement_examples 必须是可以直接放进卡片背面的自然内容，"
        "不要写 natural object、complete sentence、use X in a sentence 这种占位说明。"
        "9) 每张卡必须给复习字段：retrieval_prompt=正面明确回忆题，不能写“判断最值得学”；"
        "answer_core=翻面第一眼核对的核心答案，只能写英文表达/单词本体，例如 hold that against you；"
        "禁止在 answer_core 写中文释义、IPA、发音融合、连读说明、语法解释或“X 是 Y”的说明；这些放 teacher_note 或 confusable_note。"
        "usage_boundary=什么时候能用/不能用，尤其是调侃、冒犯、正式度；"
        "confusable_note=中文学习者最容易误解或误用的点。usage_boundary 和 confusable_note 要具体到这句的语气、对象、场景，"
        "不要写“注意语境”“很常见”这类空话。"
        "表达卡 retrieval_prompt 要问“这句里表示某个中文意思的自然表达是什么？”；"
        "语境生词卡要问“某个词在这句里是什么意思/怎么用？”，禁止做脱离原句的词典卡。"
        "好卡样例：english=Honestly, it's such a nice Monday morning. phrase=such a nice；"
        "learning_target=训练 such a nice + 名词来表达自然赞叹；how_to_use_it=such a nice day / such a nice place；"
        "teacher_note=下次想夸天气、地方或体验时，用 such a nice + 名词，比 very nice 更像真实口语。"
        "废卡样例：english=Today we are going to talk about AI models. phrase=talk about；B1 用户不推荐，因为太基础且不是真正值得学的内容。"
        "重复卡样例：同一句同时生成听力卡、表达卡、填空卡但训练点一样时，只保留一张表达卡。"
        "卡片规划规则：默认每个片段只生成 1 张主卡，不要机械生成三张。"
        "只有当训练目标明显不同，才额外生成 1 张专项卡；同一片段最多 2 张卡。"
        "phrase 作为默认主卡，整合听力、语义、中文感、例句和挖空答案；"
        "listening 只在弱读、连读、缩读或听音辨句难点明显时单独生成；"
        "cloze 只在该表达值得主动输出时单独生成，且必须输出一个且仅一个 ____。"
        "优先 5-12 个词的短句；超过 14 个词通常不要做精品卡。"
        f"可用卡型：{json.dumps(requested_types, ensure_ascii=False)}。"
        "如果只需要一张卡，就只返回一张；不要为了满足卡型列表而复制同一张卡。"
        "每张卡必须写 card_role: primary|specialist、learning_goal、decision_reason。"
        "返回严格 JSON，不要 Markdown。JSON 结构："
        '{"segments":[{"id":"seg_0001","cards":[{"type":"listening|phrase|cloze",'
        '"candidate_kind":"expression|contextual_vocab|grammar_pattern|listening_feature|pragmatic_risk",'
        '"exact_span":"逐词来自原句的片段","normalized_answer":"标准化英文答案",'
        '"phrase_type":"spoken_phrase|sentence_frame|collocation|discourse_marker|idiom|listening_sentence|vocabulary_usage|grammar_pattern",'
        '"content_kind":"phrase|vocabulary|grammar|listening",'
        '"source_evidence":"这张卡来自原句和上下文的证据",'
        '"chinese":"中文意思","phrase":"重点表达或生词","definition":"释义","collocations":"搭配",'
        '"context":"语境","example":"例句","chinese_feel":"中文感","why":"为什么值得学",'
        '"difficulty":"A1 入门|A2 基础|B1 日常交流|B2 独立表达|C1 高阶表达|C2 接近母语",'
        '"teacher_note":"一句老师评语","cloze":"挖空句","card_role":"primary|specialist",'
        '"learning_goal":"这张卡训练什么","decision_reason":"为什么生成这张卡",'
        '"learning_target":"这张卡训练什么","why_it_matters":"为什么值得学",'
        '"how_to_use_it":"下次怎么换场景使用","natural_chinese":"自然中文理解",'
        '"replacement_examples":"1-2 个可替换例子","avoid_reason":"不值得制卡时的原因",'
        '"retrieval_prompt":"正面明确回忆题","answer_core":"核心答案",'
        '"usage_boundary":"使用边界/语气风险","confusable_note":"易错提醒"}]}]}。'
        f"学习语言：{project.get('language', 'English')}。"
        f"用户当前水平：{current_level}，解释深度和中文提示按这个水平写。"
        f"允许收录难度范围：{', '.join(collection_levels)}；可以收录这些等级里的高频表达，但不要因为简单就写废话。"
        f"需要卡型：{', '.join(requested_types)}。"
        f"候选字幕：{json.dumps(compact, ensure_ascii=False)}"
    )


def material_context_for_prompt(context: Any) -> str:
    if not isinstance(context, dict) or not context:
        return ""
    useful = {
        key: value
        for key, value in context.items()
        if key in {"summary", "topic", "scene", "speakers_or_author", "tone", "key_points", "learning_opportunities"}
        and value not in (None, "", [])
    }
    if not useful:
        return ""
    return (
        "全局素材理解（用于判断上下文，不要照抄成卡片）："
        f"{json.dumps(useful, ensure_ascii=False)}。"
        "请用它理解人物关系、主题、语气和上下文，再判断哪个学习点真正值得复习。"
    )


def heuristic_material_context(project: dict[str, Any], segments: list[dict[str, Any]]) -> dict[str, Any]:
    title = str(project.get("title") or "").strip()
    sample = " ".join(str(item.get("text") or "").strip() for item in segments[:8]).strip()
    phrases = [
        str(item.get("phrase") or "").strip()
        for item in segments[:12]
        if str(item.get("phrase") or "").strip().lower() not in {"", "key expression", "n/a"}
    ]
    return {
        "summary": f"{title or '当前素材'}：系统根据字幕候选生成学习卡，需要以原句和时间轴为准。",
        "scene": sample[:280],
        "key_points": phrases[:6],
        "learning_opportunities": [LANGUAGE_FOCUS_LABELS[item] for item in normalized_language_focus(project)],
        "source": "heuristic",
    }


def build_material_context_prompt(project: dict[str, Any], segments: list[dict[str, Any]]) -> str:
    compact = [
        {
            "id": item.get("id"),
            "source_time": item.get("source_time"),
            "english": item.get("text"),
            "phrase_hint": item.get("phrase", ""),
        }
        for item in segments[:80]
    ]
    return (
        "你是中文母语者的英语学习材料分析老师。请先理解这段视频/字幕素材到底在讲什么，"
        "不要生成卡片内容。你的任务是给后续 Anki 制卡提供全局上下文：主题、场景、人物/说话者关系、"
        "语气、关键转折、反复出现的表达，以及最值得挖的学习机会。"
        f"{language_focus_instruction(project)}"
        "请特别关注：哪些表达必须依赖上下文才懂；哪些单词在这个场景里有特殊用法；哪些句型有迁移价值；"
        "哪些听力难点确实来自弱读/连读/缩读，而不是普通句子。"
        "只返回严格 JSON，不要 Markdown。结构："
        '{"material_context":{"summary":"这段素材的核心内容","topic":"主题",'
        '"scene":"场景或论点脉络","speakers_or_author":"人物关系或作者视角","tone":"语气",'
        '"key_points":["关键情节/论点"],"learning_opportunities":["值得制卡的语言机会"],"source":"ai"}}。'
        f"素材标题：{project.get('title') or 'Untitled'}。"
        f"候选字幕：{json.dumps(compact, ensure_ascii=False)}"
    )


def material_context_available(project: dict[str, Any]) -> bool:
    api = project.get("api_config") or {}
    return model_api_available(api)


def call_material_context(project: dict[str, Any], segments: list[dict[str, Any]]) -> dict[str, Any]:
    if normalized_study_depth(project) != "deep" or not segments:
        return heuristic_material_context(project, segments)
    if not material_context_available(project):
        return heuristic_material_context(project, segments)

    api = project.get("api_config") or {}
    provider = api.get("provider", "local")
    api_key = api.get("api_key", "").strip()
    model = api.get("model", "").strip()
    prompt = build_material_context_prompt(project, segments)
    try:
        if provider in OPENAI_COMPATIBLE_PROVIDERS:
            token_budget = 3000 if is_deepseek_thinking_config(api) else 2200
            response = compatible_chat_completion(
                api,
                [
                    {"role": "system", "content": "Return only valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                timeout=180 if is_thinking_model_config(api) else 60,
                max_tokens=token_budget,
                progress={
                    "command": "generate",
                    "stage": "context",
                    "percent": 54,
                    "message": "模型正在理解整段素材，thinking 已保留。",
                },
            )
            payload = extract_json_object(chat_completion_content(response))
        elif provider == "claude":
            response = http_json(
                anthropic_messages_url(api),
                anthropic_headers(api, api_key),
                {
                    "model": model,
                    "max_tokens": 2200,
                    "temperature": 0.2,
                    "system": "Return only valid JSON.",
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=90,
            )
            payload = extract_json_object("".join(part.get("text", "") for part in response.get("content", [])))
        elif provider == "gemini":
            response = http_json(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}",
                {},
                {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
                },
                timeout=90,
            )
            payload = extract_json_object(response["candidates"][0]["content"]["parts"][0]["text"])
        elif is_gemini_vertex_config(api):
            content = gemini_vertex_generate_content(
                api,
                prompt,
                temperature=0.2,
                timeout=180 if is_gemini_vertex_thinking_config(api) else 90,
                max_output_tokens=6000 if is_gemini_vertex_thinking_config(api) else 3000,
            )
            payload = extract_json_object(content)
        else:
            return heuristic_material_context(project, segments)
        context = payload.get("material_context") if isinstance(payload, dict) else None
        if not isinstance(context, dict) and isinstance(payload, dict):
            direct_context_keys = {"summary", "topic", "scene", "speakers_or_author", "tone", "key_points"}
            if any(key in payload for key in direct_context_keys):
                context = payload
        if isinstance(context, dict) and context:
            return {**context, "source": context.get("source") or "ai"}
    except Exception as err:
        fallback = heuristic_material_context(project, segments)
        fallback["warning"] = f"深度理解失败，已回退到本地上下文：{err}"
        return fallback
    return heuristic_material_context(project, segments)


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


def http_json(url: str, headers: dict[str, str], body: dict[str, Any], timeout: int = 60) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"API HTTP {err.code}: {detail}") from err


def http_sse_json_events(url: str, headers: dict[str, str], body: dict[str, Any], timeout: int = 120) -> list[dict[str, Any]]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "text/event-stream", **headers},
        method="POST",
    )
    events: list[dict[str, Any]] = []
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data_lines: list[str] = []
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    if data_lines:
                        data = "\n".join(data_lines).strip()
                        data_lines = []
                        if data == "[DONE]":
                            break
                        if data:
                            events.append(json.loads(data))
                    continue
                if line.startswith(":"):
                    continue
                if line.startswith("data:"):
                    data = line[len("data:") :].strip()
                    if data == "[DONE]":
                        break
                    data_lines.append(data)
            if data_lines:
                data = "\n".join(data_lines).strip()
                if data and data != "[DONE]":
                    events.append(json.loads(data))
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"API HTTP {err.code}: {detail}") from err
    return events


def stream_chat_completion(
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    timeout: int = 120,
    progress: dict[str, Any] | None = None,
) -> dict[str, Any]:
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    finish_reason: str | None = None
    last_emit = 0.0
    for event in http_sse_json_events(url, headers, body, timeout=timeout):
        for choice in event.get("choices") or []:
            delta = choice.get("delta") or {}
            if delta.get("reasoning_content"):
                reasoning_parts.append(str(delta["reasoning_content"]))
            if delta.get("content"):
                content_parts.append(str(delta["content"]))
            if choice.get("finish_reason"):
                finish_reason = str(choice["finish_reason"])
        if progress:
            now = time.time()
            if now - last_emit >= 3:
                content_chars = sum(len(part) for part in content_parts)
                reasoning_chars = sum(len(part) for part in reasoning_parts)
                phase = "正在输出最终 JSON" if content_chars else "正在思考"
                emit_progress(
                    str(progress.get("command") or "generate"),
                    str(progress.get("stage") or "ai"),
                    int(progress.get("percent") or 66),
                    f"{progress.get('message') or '模型正在生成'}：{phase}，已收到 {content_chars} 个答案字符 / {reasoning_chars} 个 thinking 字符。",
                )
                last_emit = now
    return {
        "choices": [
            {
                "finish_reason": finish_reason or "stop",
                "message": {
                    "role": "assistant",
                    "content": "".join(content_parts),
                    "reasoning_content": "".join(reasoning_parts),
                },
            }
        ]
    }


def http_binary(url: str, headers: dict[str, str], body: dict[str, Any], timeout: int = 90) -> bytes:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"TTS HTTP {err.code}: {detail}") from err


def http_get_binary(url: str, headers: dict[str, str] | None = None, timeout: int = 90) -> bytes:
    request = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"TTS download HTTP {err.code}: {detail}") from err


def anki_connect(action: str, params: dict[str, Any] | None = None, url: str = "http://127.0.0.1:8765") -> Any:
    response = http_json(
        url,
        {},
        {
            "action": action,
            "version": 6,
            "params": params or {},
        },
        timeout=30,
    )
    if response.get("error"):
        raise RuntimeError(str(response["error"]))
    return response.get("result")


def anki_field_value(fields: dict[str, Any], name: str) -> str:
    field = fields.get(name)
    if isinstance(field, dict):
        return str(field.get("value") or "")
    return str(field or "")


def compatible_base_url(config: dict[str, Any], default_url: str = "") -> str:
    provider = str(config.get("provider", "")).strip().lower()
    api_key = str(config.get("api_key") or "").strip().lower()
    base_url = str(config.get("base_url") or "").strip().rstrip("/")
    if is_mimo_config(config) and api_key.startswith("tp-") and "token-plan-" not in base_url.lower():
        return MIMO_TOKEN_PLAN_SGP_BASE_URL
    if base_url:
        return base_url
    if is_deepseek_config(config):
        return DEEPSEEK_OPENAI_BASE_URL
    if provider in MIMO_PROVIDERS:
        return MIMO_TOKEN_PLAN_SGP_BASE_URL if api_key.startswith("tp-") else MIMO_OPENAI_BASE_URL
    return default_url.rstrip("/")


def provider_name(config: dict[str, Any]) -> str:
    return str(config.get("provider", "")).strip().lower()


def is_mimo_config(config: dict[str, Any]) -> bool:
    base_url = str(config.get("base_url") or "").lower()
    return provider_name(config) in MIMO_PROVIDERS or "xiaomimimo.com" in base_url


def is_qwen_config(config: dict[str, Any]) -> bool:
    base_url = str(config.get("base_url") or "").lower()
    model = str(config.get("model") or "").strip().lower()
    return (
        provider_name(config) in QWEN_TTS_PROVIDERS
        or "dashscope" in base_url
        or "qwencloud" in base_url
        or model.startswith("qwen")
    )


def is_deepseek_config(config: dict[str, Any]) -> bool:
    base_url = str(config.get("base_url") or "").lower()
    model = str(config.get("model") or "").strip().lower()
    return "deepseek.com" in base_url or model.startswith("deepseek-")


def is_deepseek_thinking_config(config: dict[str, Any]) -> bool:
    model = str(config.get("model") or "").strip().lower()
    return is_deepseek_config(config) and model in DEEPSEEK_THINKING_MODELS


def is_gemini_vertex_config(config: dict[str, Any]) -> bool:
    return provider_name(config) in GEMINI_VERTEX_PROVIDERS


def is_gemini_vertex_tts_config(config: dict[str, Any]) -> bool:
    return provider_name(config) in GEMINI_VERTEX_TTS_PROVIDERS


def is_gemini_vertex_thinking_config(config: dict[str, Any]) -> bool:
    model = str(config.get("model") or "").strip().lower()
    return is_gemini_vertex_config(config) and model.startswith("gemini-3.")


def is_thinking_model_config(config: dict[str, Any]) -> bool:
    return (
        is_qwen_config(config)
        or is_mimo_config(config)
        or is_deepseek_thinking_config(config)
        or is_gemini_vertex_thinking_config(config)
    )


def thinking_budget(config: dict[str, Any], default_value: int = 800) -> int:
    for key in ("thinking_budget", "reasoning_budget"):
        value = config.get(key)
        try:
            budget = int(value)
        except (TypeError, ValueError):
            continue
        if budget > 0:
            return min(budget, 4000)
    return default_value


def should_stream_reasoning(config: dict[str, Any]) -> bool:
    return is_thinking_model_config(config)


def api_key_header(config: dict[str, Any]) -> dict[str, str]:
    api_key = str(config.get("api_key") or "").strip()
    if is_mimo_config(config):
        return {"api-key": api_key}
    return {"Authorization": f"Bearer {api_key}"}


def model_api_available(api: dict[str, Any]) -> bool:
    provider = provider_name(api) or "local"
    if provider == "local":
        return False
    if not str(api.get("model") or "").strip():
        return False
    if is_gemini_vertex_config(api):
        return True
    return bool(str(api.get("api_key") or "").strip())


def hidden_subprocess_flags() -> dict[str, Any]:
    if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def gcloud_executable() -> str:
    found = shutil.which("gcloud") or shutil.which("gcloud.cmd")
    if found:
        return found
    candidates = [
        Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"))
        / "Google"
        / "Cloud SDK"
        / "google-cloud-sdk"
        / "bin"
        / "gcloud.cmd",
        Path(os.environ.get("ProgramFiles", "C:/Program Files"))
        / "Google"
        / "Cloud SDK"
        / "google-cloud-sdk"
        / "bin"
        / "gcloud.cmd",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    raise FileNotFoundError("gcloud")


def gcloud_value(args: list[str], timeout: int = 30) -> str:
    try:
        result = subprocess.run(
            [gcloud_executable(), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=True,
            **hidden_subprocess_flags(),
        )
    except FileNotFoundError as err:
        raise RuntimeError("Gemini Vertex 需要先安装 Google Cloud SDK，并确保 gcloud 在 PATH 中。") from err
    except subprocess.CalledProcessError as err:
        detail = (err.stderr or err.stdout or "").strip()
        raise RuntimeError(f"gcloud 调用失败：{detail or err}") from err
    value = result.stdout.strip()
    if not value or value == "(unset)":
        raise RuntimeError(f"gcloud {' '.join(args)} 没有返回可用值。")
    return value


def gemini_vertex_project(config: dict[str, Any]) -> str:
    explicit = str(config.get("project") or config.get("project_id") or "").strip()
    return explicit or gcloud_value(["config", "get-value", "core/project"])


def gemini_vertex_location(config: dict[str, Any]) -> str:
    explicit = str(config.get("location") or config.get("region") or "").strip()
    if explicit:
        return explicit
    base_url = str(config.get("base_url") or "").strip().rstrip("/")
    if base_url:
        try:
            host = urllib.parse.urlparse(base_url).hostname or ""
        except ValueError:
            host = ""
        if host == "aiplatform.googleapis.com":
            return "global"
        suffix = "-aiplatform.googleapis.com"
        if host.endswith(suffix):
            return host[: -len(suffix)]
    return "global"


def gemini_vertex_base_url(location: str) -> str:
    return GEMINI_VERTEX_GLOBAL_BASE_URL if location == "global" else f"https://{location}-aiplatform.googleapis.com"


def gemini_content_text(response: dict[str, Any]) -> str:
    texts: list[str] = []
    for candidate in response.get("candidates", []) or []:
        content = candidate.get("content") or {}
        for part in content.get("parts", []) or []:
            text = part.get("text")
            if text:
                texts.append(str(text))
    return "\n".join(texts).strip()


def gemini_vertex_generate_content(
    config: dict[str, Any],
    prompt: str,
    *,
    temperature: float = 0.2,
    timeout: int = 180,
    max_output_tokens: int = 12000,
    response_mime_type: str = "application/json",
) -> str:
    model = str(config.get("model") or GEMINI_VERTEX_DEFAULT_MODEL).strip()
    project = gemini_vertex_project(config)
    location = gemini_vertex_location(config)
    token = gcloud_value(["auth", "print-access-token"])
    url = (
        f"{gemini_vertex_base_url(location)}/v1/projects/{urllib.parse.quote(project, safe='')}"
        f"/locations/{urllib.parse.quote(location, safe='')}/publishers/google/models/"
        f"{urllib.parse.quote(model, safe='')}:generateContent"
    )
    generation_config: dict[str, Any] = {
        "temperature": temperature,
        "maxOutputTokens": max_output_tokens,
    }
    if response_mime_type:
        generation_config["responseMimeType"] = response_mime_type
    response = http_json(
        url,
        {"Authorization": f"Bearer {token}"},
        {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": generation_config,
        },
        timeout=timeout,
    )
    text = gemini_content_text(response)
    if text:
        return text
    finish = ""
    for candidate in response.get("candidates", []) or []:
        finish = str(candidate.get("finishReason") or finish)
    if finish == "MAX_TOKENS":
        raise RuntimeError("Gemini Vertex 没有返回正文：输出预算被 thinking 消耗完，请提高 maxOutputTokens。")
    raise RuntimeError(f"Gemini Vertex 没有返回可用正文：{finish or 'empty response'}")


def anthropic_messages_url(config: dict[str, Any]) -> str:
    base_url = str(config.get("base_url") or "").strip().rstrip("/")
    if not base_url:
        return "https://api.anthropic.com/v1/messages"
    if base_url.endswith("/messages"):
        return base_url
    if base_url.endswith("/v1"):
        return f"{base_url}/messages"
    return f"{base_url}/v1/messages"


def anthropic_headers(config: dict[str, Any], api_key: str) -> dict[str, str]:
    if is_mimo_config(config):
        return {"api-key": api_key}
    return {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }


def compatible_chat_completion(
    api: dict[str, Any],
    messages: list[dict[str, str]],
    temperature: float,
    timeout: int = 60,
    max_tokens: int | None = None,
    progress: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base_url = compatible_base_url(api)
    if not base_url:
        raise RuntimeError("MIMO / OpenAI-compatible 需要 Base URL。")
    is_mimo = is_mimo_config(api)
    is_qwen = is_qwen_config(api)
    is_deepseek_thinking = is_deepseek_thinking_config(api)
    body: dict[str, Any] = {
        "model": str(api.get("model") or "").strip(),
        "messages": messages,
        "temperature": temperature,
    }
    stream_reasoning = should_stream_reasoning(api)
    if not is_mimo:
        body["response_format"] = {"type": "json_object"}
    else:
        body["reasoning_effort"] = "low"
        body["thinking"] = {"type": "enabled"}
    if is_deepseek_thinking:
        body["thinking"] = {"type": "enabled"}
        body["reasoning_effort"] = str(api.get("reasoning_effort") or "high")
    if is_qwen:
        body["enable_thinking"] = True
        body["thinking_budget"] = thinking_budget(api)
        body["preserve_thinking"] = False
    if stream_reasoning:
        body["stream"] = True
        body["stream_options"] = {"include_usage": True}
    if max_tokens is not None:
        body["max_completion_tokens" if is_mimo else "max_tokens"] = max_tokens
    supports_response_retry = "response_format" in body
    endpoint = f"{base_url}/chat/completions"

    def send(request_body: dict[str, Any]) -> dict[str, Any]:
        if request_body.get("stream"):
            return stream_chat_completion(
                endpoint,
                api_key_header(api),
                request_body,
                timeout=timeout,
                progress=progress,
            )
        return http_json(
            endpoint,
            api_key_header(api),
            request_body,
            timeout=timeout,
        )

    try:
        return send(body)
    except Exception as err:
        if is_mimo:
            retry_body = dict(body)
            if retry_body.get("stream"):
                retry_body["stream"] = False
                retry_body.pop("stream_options", None)
            try:
                return send(retry_body)
            except Exception as retry_err:
                if "max_completion_tokens" in retry_body:
                    fallback_body = dict(retry_body)
                    fallback_body["max_tokens"] = fallback_body.pop("max_completion_tokens")
                    try:
                        return send(fallback_body)
                    except Exception as token_retry_err:
                        raise RuntimeError(
                            f"{err}; 保留 MIMO thinking 重试失败：{retry_err}; 改用 max_tokens 重试仍失败：{token_retry_err}"
                        ) from token_retry_err
                raise RuntimeError(f"{err}; 保留 MIMO thinking 重试仍失败：{retry_err}") from retry_err
        if stream_reasoning:
            retry_body = dict(body)
            retry_body["stream"] = False
            retry_body.pop("stream_options", None)
            try:
                return send(retry_body)
            except Exception as stream_retry_err:
                if supports_response_retry:
                    retry_body.pop("response_format", None)
                    try:
                        return send(retry_body)
                    except Exception as response_retry_err:
                        raise RuntimeError(
                            f"{err}; 去掉流式 thinking 重试失败：{stream_retry_err}; "
                            f"去掉 response_format 重试仍失败：{response_retry_err}"
                        ) from response_retry_err
                raise RuntimeError(f"{err}; 去掉流式 thinking 重试失败：{stream_retry_err}") from stream_retry_err
        # Some OpenAI-compatible providers, including Token Plan gateways, may not support
        # response_format even when they can reliably return JSON from the prompt.
        if not supports_response_retry:
            raise
        body.pop("response_format", None)
        try:
            return send(body)
        except Exception as retry_err:
            raise RuntimeError(f"{err}; 去掉 response_format 重试仍失败：{retry_err}") from retry_err


def chat_completion_content(response: dict[str, Any]) -> str:
    message = response.get("choices", [{}])[0].get("message", {})
    content = message.get("content", "")
    if isinstance(content, list):
        return "".join(str(part.get("text", "")) if isinstance(part, dict) else str(part) for part in content)
    return str(content or "")


def call_model(project: dict[str, Any], segments: list[dict[str, Any]]) -> dict[str, Any] | None:
    api = project.get("api_config") or {}
    provider = api.get("provider", "local")
    api_key = api.get("api_key", "").strip()
    model = api.get("model", "").strip()
    if provider == "local" or not model or (not api_key and not is_gemini_vertex_config(api)):
        return None

    prompt = build_prompt(project, segments)

    try:
        if provider in OPENAI_COMPATIBLE_PROVIDERS:
            token_budget = 2200 if is_mimo_config(api) else 8000 if is_deepseek_thinking_config(api) else 4000 if is_qwen_config(api) else 6000
            response = compatible_chat_completion(
                api,
                [
                    {"role": "system", "content": "Return only valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                timeout=180 if is_thinking_model_config(api) else 60,
                max_tokens=token_budget,
                progress={
                    "command": "generate",
                    "stage": "ai",
                    "percent": 70,
                    "message": "模型保留 thinking 生成卡片字段",
                },
            )
            content = chat_completion_content(response)
            return extract_json_object(content)

        if provider == "claude":
            response = http_json(
                anthropic_messages_url(api),
                anthropic_headers(api, api_key),
                {
                    "model": model,
                    "max_tokens": 6000,
                    "temperature": 0.3,
                    "system": "Return only valid JSON.",
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            content = "".join(part.get("text", "") for part in response.get("content", []))
            return extract_json_object(content)

        if provider == "gemini":
            response = http_json(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}",
                {},
                {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0.3,
                        "responseMimeType": "application/json",
                    },
                },
            )
            content = response["candidates"][0]["content"]["parts"][0]["text"]
            return extract_json_object(content)

        if is_gemini_vertex_config(api):
            content = gemini_vertex_generate_content(
                api,
                prompt,
                temperature=0.3,
                timeout=180 if is_gemini_vertex_thinking_config(api) else 120,
                max_output_tokens=16000 if is_gemini_vertex_thinking_config(api) else 8000,
            )
            return extract_json_object(content)
    except Exception as err:
        return {"error": str(err)}

    return None


def call_model_batches(project: dict[str, Any], segments: list[dict[str, Any]], batch_size: int = 10) -> dict[str, Any] | None:
    if not segments:
        return None
    api = project.get("api_config") or {}
    if (
        api.get("provider", "local") == "local"
        or (not str(api.get("api_key", "")).strip() and not is_gemini_vertex_config(api))
        or not str(api.get("model", "")).strip()
    ):
        return None
    if is_mimo_config(api):
        batch_size = 1
    elif is_gemini_vertex_thinking_config(api):
        batch_size = min(batch_size, 3)
    elif is_deepseek_thinking_config(api):
        batch_size = min(batch_size, 4)
    elif is_qwen_config(api):
        batch_size = min(batch_size, 4)
    merged: list[dict[str, Any]] = []
    errors: list[str] = []
    any_called = False
    total_batches = max(1, (len(segments) + batch_size - 1) // batch_size)
    for start in range(0, len(segments), batch_size):
        batch = segments[start : start + batch_size]
        batch_index = start // batch_size + 1
        provider_hint = "，thinking 已保留" if is_thinking_model_config(api) else ""
        percent = min(82, 66 + int((batch_index - 1) / total_batches * 14))
        emit_progress(
            "generate",
            "ai",
            percent,
            f"正在请求模型生成卡片：第 {batch_index}/{total_batches} 批{provider_hint}。",
        )
        payload = call_model(project, batch)
        if payload is None:
            return None
        any_called = True
        if "error" in payload:
            errors.append(f"{batch[0]['id']}..{batch[-1]['id']}: {payload['error']}")
            continue
        merged.extend(payload.get("segments", []))
    if errors and not merged:
        return {"error": "；".join(errors)}
    result: dict[str, Any] = {"segments": merged}
    if errors:
        result["error"] = "部分批次失败：" + "；".join(errors)
    return result if any_called else None


def phrase_review_available(project: dict[str, Any]) -> bool:
    api = project.get("api_config") or {}
    return bool(
        model_api_available(api)
        and (api.get("provider", "local") in OPENAI_COMPATIBLE_PROVIDERS or is_gemini_vertex_config(api))
    )


def build_phrase_review_prompt(project: dict[str, Any], segments: list[dict[str, Any]]) -> str:
    level = str(project.get("level", "B1"))
    collection_levels = collection_levels_from_payload(project, level)
    focus_instruction = language_focus_instruction(project)
    material_context_instruction = material_context_for_prompt(project.get("material_context"))
    compact = [
        {
            "id": segment["id"],
            "source_time": segment["source_time"],
            "english": segment["text"],
            "local_phrase": segment.get("phrase", "key expression"),
            "exact_span": segment.get("exact_span", ""),
            "normalized_answer": segment.get("normalized_answer", ""),
            "candidate_kind": segment.get("candidate_kind", ""),
            "phrase_type": segment.get("phrase_type", ""),
            "content_kind": segment.get("content_kind", ""),
            "candidate_source": segment.get("candidate_source", ""),
            "phrase_card_focus": segment.get("phrase_card_focus", ""),
            "local_score": round(float(segment.get("score", 0)), 2),
        }
        for segment in segments
    ]
    return (
        "你是中文母语者的英语学习点评审老师。请判断这些 typed learning points 是否值得做 Anki 卡，"
        "不要生成卡片内容。学习点可能是表达、语境生词、语法句法、听力难点或语气风险。目标是同时提高数量和质量："
        "保留真实可用的学习点，拒绝主题词、专有名词、"
        "半截词串、视频口播引入语和过基础表达。"
        "请像英语老师一样先判断学习动作：这个片段训练听懂、会用、会替换、理解语气，还是根本不值得制卡。"
        f"{material_context_instruction}"
        f"{focus_instruction}"
        "判断标准："
        "1) exact_span 必须逐词来自 english 原句；normalized_answer/answer_core 必须是英文答案本体。"
        "词伙通常 2-6 个词，单词用法可以是 1 个核心词，语法框架可以是原句里的可替换结构。它必须完整、自然、可换场景复用。"
        "2) keep 只给真正值得复习的表达；如果只是句子主题、名词堆叠、产品名、working with 这类泛短语，decision=skip。"
        "3) B1 或更高水平不要把 talk about、go home 这类 A1/A2 基础表达评为 keep，除非原句里有更具体的表达框架。"
        "4) value_score 用 1-5：5=非常值得学，4=推荐制卡，3=可待审，1-2=跳过。"
        "5) candidate_kind 从 expression、contextual_vocab、grammar_pattern、listening_feature、pragmatic_risk 中选一个。"
        "phrase_type 从 spoken_phrase、sentence_frame、collocation、discourse_marker、idiom、listening_sentence、vocabulary_usage、grammar_pattern 中选一个。"
        "6) score_breakdown 必须给 transferability、spoken_naturalness、level_fit、context_dependence、answer_clarity、card_uniqueness、learning_action、risk_boundary 八项 1-5 分。"
        "7) card_focus 用一句短中文说明这张卡应该训练什么；skip 时写 reject_reason。"
        "8) answer_core 禁止包含中文、IPA、发音说明、语法解释或“X 是 Y”的说明；这些只能放到后续字段里。"
        "9) 同一句最多 keep 2 个学习点，且训练动作必须明显不同；expression 和 contextual_vocab 可以共存，重复训练目标不能共存。"
        "好例子：Honestly, it's such a nice Monday morning. -> keep, phrase=such a nice, phrase_type=sentence_frame, card_focus=训练 such a nice + 名词表达自然赞叹。"
        "废例子：Today we are going to talk about AI models. -> skip, phrase=talk about, reject_reason=B1 用户太基础，而且只是视频引入。"
        "只返回严格 JSON，不要 Markdown。结构："
        '{"candidates":[{"id":"seg_0001","decision":"keep|skip","phrase":"原句里的词伙",'
        '"candidate_kind":"expression|contextual_vocab|grammar_pattern|listening_feature|pragmatic_risk",'
        '"exact_span":"逐词来自原句","normalized_answer":"英文标准答案","answer_core":"英文答案本体",'
        '"phrase_type":"spoken_phrase|sentence_frame|collocation|discourse_marker|idiom|listening_sentence|vocabulary_usage|grammar_pattern",'
        '"value_score":1,"score_breakdown":{"transferability":1,"spoken_naturalness":1,"level_fit":1,"context_dependence":1,"answer_clarity":1,"card_uniqueness":1,"learning_action":1,"risk_boundary":1},'
        '"reason":"推荐理由","card_focus":"训练重点","reject_reason":"跳过原因"}]}。'
        f"用户当前水平：{level}。允许收录难度范围：{', '.join(collection_levels)}。"
        f"候选字幕：{json.dumps(compact, ensure_ascii=False)}"
    )


def phrase_review_score(value: Any) -> int:
    try:
        score = int(round(float(value)))
    except (TypeError, ValueError):
        score = 0
    return max(0, min(5, score))


def normalized_phrase_key(phrase: str) -> str:
    return re.sub(r"\s+", " ", str(phrase or "").strip().lower())


def review_phrase_choice(
    text: str,
    proposed: str,
    fallback: str,
    level: str,
    collection_levels: list[str] | None = None,
    candidate_kind: str = "expression",
    phrase_type: str = "",
) -> str:
    candidates = [proposed, fallback, find_phrase(text, level, collection_levels)]
    seen: set[str] = set()
    for candidate in candidates:
        normalized = re.sub(r"\s+", " ", str(candidate or "").strip())
        key = normalized.lower()
        if not normalized or key in seen or key == "key expression":
            continue
        seen.add(key)
        if usable_learning_point_span(text, normalized, candidate_kind, phrase_type):
            return normalized
    return ""


def repair_review_segment_phrase(
    segment: dict[str, Any],
    level: str,
    collection_levels: list[str] | None = None,
) -> dict[str, Any] | None:
    candidate_kind = candidate_kind_for_segment(segment)
    phrase_type = str(segment.get("phrase_type") or phrase_type_for_candidate_kind(candidate_kind))
    phrase = review_phrase_choice(
        str(segment.get("text") or ""),
        str(segment.get("phrase") or ""),
        "",
        level,
        collection_levels,
        candidate_kind,
        phrase_type,
    )
    if not phrase:
        return None
    return {
        **segment,
        "phrase": phrase,
        "recommendation": max(3, int(segment.get("recommendation") or 3)),
    }


def skipped_review_segment(segment: dict[str, Any], status: str, reason: str, value_score: int = 0) -> dict[str, Any]:
    return {
        **segment,
        "cards": [],
        "phrase_value_score": value_score,
        "phrase_review_status": status,
        "phrase_review_source": "ai",
        "phrase_decision_reason": "",
        "phrase_reject_reason": reason,
        "phrase_card_focus": "",
    }


def apply_phrase_review_decisions(
    segments: list[dict[str, Any]],
    reviews: dict[str, dict[str, Any]],
    project: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    level = str(project.get("level", "B1"))
    collection_levels = collection_levels_from_payload(project, level)
    kept: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for segment in segments:
        review = reviews.get(segment["id"])
        if not review:
            repaired = repair_review_segment_phrase(segment, level, collection_levels) or segment
            repaired = refine_segment_media_for_phrase(repaired, str(repaired.get("phrase") or ""))
            kept.append(
                {
                    **repaired,
                    "phrase_value_score": 3,
                    "phrase_review_status": "needs_review",
                    "phrase_review_source": "ai",
                    "phrase_decision_reason": "AI 评审没有返回这个片段，保留为待审候选。",
                    "phrase_reject_reason": "",
                    "phrase_card_focus": "人工确认是否值得制卡。",
                    "content_kind": content_kind_for_phrase_type(str(repaired.get("phrase_type") or "")),
                    "candidate_kind": candidate_kind_for_segment(repaired),
                    "exact_span": repaired.get("exact_span") or repaired.get("phrase", ""),
                    "normalized_answer": repaired.get("normalized_answer") or repaired.get("phrase", ""),
                    "answer_core": repaired.get("answer_core") or repaired.get("normalized_answer") or repaired.get("phrase", ""),
                    "candidate_source": repaired.get("candidate_source", ""),
                    "learning_point_schema_version": repaired.get("learning_point_schema_version") or LEARNING_POINT_SCHEMA_VERSION,
                    "source_evidence": repaired.get("text", ""),
                }
            )
            continue

        value_score = phrase_review_score(review.get("value_score"))
        decision = str(review.get("decision") or "").strip().lower()
        proposed = str(review.get("phrase") or "").strip()
        exact_span = str(review.get("exact_span") or "").strip()
        normalized_answer = str(review.get("normalized_answer") or "").strip()
        answer_core = str(review.get("answer_core") or "").strip()
        reason = str(review.get("reason") or "").strip()
        reject_reason = str(review.get("reject_reason") or "").strip()
        card_focus = str(review.get("card_focus") or "").strip()
        candidate_kind = str(review.get("candidate_kind") or segment.get("candidate_kind") or "").strip()
        phrase_type = str(review.get("phrase_type") or segment.get("phrase_type") or "").strip()
        if not candidate_kind:
            candidate_kind = candidate_kind_for_phrase_type(phrase_type, candidate_kind_for_segment(segment))
        if not phrase_type:
            phrase_type = phrase_type_for_candidate_kind(candidate_kind)
        score_breakdown = review.get("score_breakdown") if isinstance(review.get("score_breakdown"), dict) else {}
        phrase = review_phrase_choice(
            segment["text"],
            normalized_answer or answer_core or exact_span or proposed,
            segment.get("normalized_answer") or segment.get("answer_core") or segment.get("exact_span") or segment.get("phrase", ""),
            level,
            collection_levels,
            candidate_kind,
            phrase_type,
        )

        if decision != "keep" or value_score < 3:
            skipped.append(
                skipped_review_segment(
                    segment,
                    "reject",
                    reject_reason or reason or "AI 认为这个片段没有值得做卡的可迁移表达。",
                    value_score,
                )
            )
            continue
        if not phrase:
            skipped.append(
                skipped_review_segment(
                    segment,
                    "reject",
                    reject_reason or "AI 推荐的词伙不在原句中，且本地没有可修复的完整词伙。",
                    value_score,
                )
            )
            continue
        if is_too_basic_for_level(phrase, level):
            value_score = min(value_score, 3)

        status = "recommended" if value_score >= 4 else "needs_review"
        refined_segment = refine_segment_media_for_phrase(segment, phrase)
        kept.append(
            {
                **refined_segment,
                "phrase": phrase,
                "exact_span": exact_span or segment.get("exact_span") or phrase,
                "normalized_answer": normalized_answer or answer_core or phrase,
                "answer_core": answer_core or normalized_answer or phrase,
                "candidate_kind": candidate_kind,
                "recommendation": min(5, max(1, value_score)),
                "phrase_value_score": value_score,
                "phrase_review_status": status,
                "phrase_review_source": "ai",
                "phrase_decision_reason": reason or card_focus or "AI 认为这个表达值得制卡。",
                "phrase_reject_reason": "" if status == "recommended" else "词伙价值分为 3，默认进入待审。",
                "phrase_card_focus": card_focus or "围绕这个表达的真实语境和迁移用法制卡。",
                "phrase_type": phrase_type,
                "content_kind": content_kind_for_phrase_type(phrase_type),
                "candidate_source": segment.get("candidate_source", ""),
                "learning_point_schema_version": LEARNING_POINT_SCHEMA_VERSION,
                "source_evidence": segment.get("text", ""),
                "score_breakdown": score_breakdown,
            }
        )

    return kept, skipped


def ensure_min_review_candidates(
    original_segments: list[dict[str, Any]],
    kept: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
    project: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    max_segments = resolved_max_segments(project)
    min_count = min(len(original_segments), max_segments, max(8, min(18, round(max_segments * 0.45))))
    if len(kept) >= min_count:
        return kept, skipped

    kept_ids = {str(item.get("id")) for item in kept}
    promoted_ids: set[str] = set()
    ranked = sorted(
        original_segments,
        key=lambda item: (
            normalized_phrase_key(item.get("phrase", "")) != "key expression",
            float(item.get("score") or 0),
            -float(item.get("start") or 0),
        ),
        reverse=True,
    )
    for segment in ranked:
        segment_id = str(segment.get("id"))
        if segment_id in kept_ids:
            continue
        repaired = repair_review_segment_phrase(
            segment,
            str(project.get("level", "B1")),
            collection_levels_from_payload(project, str(project.get("level", "B1"))),
        )
        if not repaired:
            continue
        repaired = refine_segment_media_for_phrase(repaired, str(repaired.get("phrase") or ""))
        kept.append(
            {
                **repaired,
                "cards": [],
                "phrase_value_score": 3,
                "phrase_review_status": "needs_review",
                "phrase_review_source": "ai",
                "phrase_decision_reason": "AI 评审保留过少，系统保留这个本地高分候选供复核。",
                "phrase_reject_reason": "待审候选默认不导出；请确认词伙值得学后再启用。",
                "phrase_card_focus": "人工确认这句里是否有可迁移表达。",
                "content_kind": content_kind_for_phrase_type(str(repaired.get("phrase_type") or "")),
                "candidate_kind": candidate_kind_for_segment(repaired),
                "exact_span": repaired.get("exact_span") or repaired.get("phrase", ""),
                "normalized_answer": repaired.get("normalized_answer") or repaired.get("phrase", ""),
                "answer_core": repaired.get("answer_core") or repaired.get("normalized_answer") or repaired.get("phrase", ""),
                "candidate_source": repaired.get("candidate_source", ""),
                "learning_point_schema_version": repaired.get("learning_point_schema_version") or LEARNING_POINT_SCHEMA_VERSION,
                "source_evidence": repaired.get("text", ""),
            }
        )
        kept_ids.add(segment_id)
        promoted_ids.add(segment_id)
        if len(kept) >= min_count:
            break

    if promoted_ids:
        skipped = [item for item in skipped if str(item.get("id")) not in promoted_ids]
    return kept, skipped


def split_duplicate_phrase_segments(segments: list[dict[str, Any]], max_per_phrase: int = 2) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ranked = sorted(
        segments,
        key=lambda item: (
            int(item.get("phrase_value_score") or 0),
            float(item.get("score") or 0),
            -float(item.get("start") or 0),
        ),
        reverse=True,
    )
    counts: dict[str, int] = {}
    kept: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    for segment in ranked:
        key_parts = [
            normalized_phrase_key(segment.get("normalized_answer") or segment.get("phrase", "")),
            str(segment.get("candidate_kind") or candidate_kind_for_segment(segment)),
            re.sub(r"\s+", " ", str(segment.get("phrase_card_focus") or "").strip().lower())[:80],
        ]
        key = "::".join(part for part in key_parts if part)
        if key == "key expression":
            key = f"key expression::{segment.get('id', '')}"
        if not key:
            duplicates.append(skipped_review_segment(segment, "duplicate", "缺少稳定词伙，已从候选中移除。", 0))
            continue
        if counts.get(key, 0) >= max_per_phrase:
            duplicates.append(
                skipped_review_segment(
                    segment,
                    "duplicate",
                    f"词伙 {segment.get('phrase', '')} 已保留 {max_per_phrase} 个更好的语境，本片段合并为重复候选。",
                    phrase_review_score(segment.get("phrase_value_score")),
                )
            )
            continue
        counts[key] = counts.get(key, 0) + 1
        kept.append(segment)
    return sorted(kept, key=lambda item: item["start"]), sorted(duplicates, key=lambda item: item["start"])


def limit_reviewed_segments(
    segments: list[dict[str, Any]],
    max_segments: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ranked = sorted(
        segments,
        key=lambda item: (
            int(item.get("phrase_value_score") or 0),
            float(item.get("score") or 0),
            -float(item.get("start") or 0),
        ),
        reverse=True,
    )
    kept = ranked[:max_segments]
    overflow = [
        skipped_review_segment(
            item,
            "reject",
            "片段预算已满，已优先保留评分更高的候选。",
            phrase_review_score(item.get("phrase_value_score")),
        )
        for item in ranked[max_segments:]
    ]
    return sorted(kept, key=lambda item: item["start"]), sorted(overflow, key=lambda item: item["start"])


def review_phrase_candidates_with_mimo(
    project: dict[str, Any],
    segments: list[dict[str, Any]],
    batch_size: int = 16,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
    if not phrase_review_available(project) or not segments:
        return segments, [], None

    api = project.get("api_config") or {}
    reviews: dict[str, dict[str, Any]] = {}
    try:
        total_batches = max(1, (len(segments) + batch_size - 1) // batch_size)
        for start in range(0, len(segments), batch_size):
            batch = segments[start : start + batch_size]
            batch_index = start // batch_size + 1
            percent = min(64, 58 + int((batch_index - 1) / total_batches * 5))
            emit_progress(
                "generate",
                "phrase_review",
                percent,
                f"AI 正在评审学习候选：第 {batch_index}/{total_batches} 批，thinking 已保留。",
            )
            prompt = build_phrase_review_prompt(project, batch)
            if is_gemini_vertex_config(api):
                content = gemini_vertex_generate_content(
                    api,
                    prompt,
                    temperature=0.1,
                    timeout=180 if is_gemini_vertex_thinking_config(api) else 120,
                    max_output_tokens=9000 if is_gemini_vertex_thinking_config(api) else 4500,
                )
            else:
                response = compatible_chat_completion(
                    api,
                    [
                        {"role": "system", "content": "Return only valid JSON."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.1,
                    timeout=180 if is_thinking_model_config(api) else 120,
                    max_tokens=4500 if is_deepseek_thinking_config(api) else 3200,
                    progress={
                        "command": "generate",
                        "stage": "phrase_review",
                        "percent": percent,
                        "message": "AI 保留 thinking 评审学习候选",
                    },
                )
                content = chat_completion_content(response)
            payload = extract_json_object(content or "")
            for item in payload.get("candidates", []):
                if isinstance(item, dict) and item.get("id"):
                    reviews[str(item["id"])] = item
    except Exception as err:
        return segments, [], f"AI 学习候选评审失败，已回退到原有候选流程：{err}"

    if not reviews:
        return segments, [], "AI 学习候选评审没有返回可用 JSON，已回退到原有候选流程。"

    kept, skipped = apply_phrase_review_decisions(segments, reviews, project)
    kept, skipped = ensure_min_review_candidates(segments, kept, skipped, project)
    kept, duplicates = split_duplicate_phrase_segments(kept)
    max_segments = resolved_max_segments(project)
    kept, overflow = limit_reviewed_segments(kept, max_segments)
    skipped = [*skipped, *duplicates, *overflow]
    return kept, sorted(skipped, key=lambda item: item["start"]), None


def api_test_prompt() -> str:
    return (
        "Return only valid JSON for an Anki card generation capability test. "
        "Use exactly this structure and no Markdown: "
        '{"segments":[{"id":"seg_test","cards":[{"type":"phrase","phrase":"in the mood",'
        '"chinese":"有心情","definition":"willing or wanting to do something",'
        '"collocations":"in the mood for; not in the mood to","context":"spoken reply",'
        '"example":"I am not in the mood to go out.","chinese_feel":"没那个心情",'
        '"why":"高频口语表达","difficulty":"B1 日常交流","teacher_note":"真实口语常用",'
        '"cloze":"I am not really ____ right now."}]}]}'
    )


def validate_api_test_payload(text: str) -> tuple[bool, str]:
    payload = extract_json_object(text)
    segments = payload.get("segments")
    if not isinstance(segments, list) or not segments:
        return False, "JSON 缺少 segments。"
    cards = segments[0].get("cards") if isinstance(segments[0], dict) else None
    if not isinstance(cards, list) or not cards:
        return False, "JSON 缺少 cards。"
    card = cards[0]
    required = ["type", "phrase", "chinese", "definition", "cloze"]
    missing = [key for key in required if not card.get(key)]
    if missing:
        return False, f"JSON 缺少字段：{', '.join(missing)}。"
    if str(card.get("cloze", "")).count("____") != 1:
        return False, "cloze 必须有且只有一个 ____。"
    return True, f"结构化 JSON 测试通过：{card.get('phrase')}"


def handle_test_api(payload: dict[str, Any]) -> dict[str, Any]:
    api = payload.get("api_config") or {}
    provider = api.get("provider", "local")
    model = api.get("model", "").strip()
    api_key = api.get("api_key", "").strip()
    started = time.time()

    if provider == "local":
        return {
            "ok": True,
            "provider": provider,
            "model": model or "local-fallback",
            "message": "本地草稿模式可用，不需要 API Key。",
            "latency_ms": 0,
        }

    if not api_key and not is_gemini_vertex_config(api):
        return {
            "ok": False,
            "provider": provider,
            "model": model,
            "message": "缺少 API Key。",
        }
    if not model:
        return {
            "ok": False,
            "provider": provider,
            "model": model,
            "message": "缺少模型名。",
        }

    prompt = api_test_prompt()
    try:
        if provider in OPENAI_COMPATIBLE_PROVIDERS:
            response = compatible_chat_completion(
                api,
                [
                    {"role": "system", "content": "Return only valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0,
                timeout=90 if is_thinking_model_config(api) else 30,
                max_tokens=2000 if (is_mimo_config(api) or is_deepseek_thinking_config(api)) else 800,
            )
            content = chat_completion_content(response)
            if content is None:
                content = ""

        elif provider == "claude":
            response = http_json(
                anthropic_messages_url(api),
                anthropic_headers(api, api_key),
                {
                    "model": model,
                    "max_tokens": 800,
                    "temperature": 0,
                    "system": "Return only valid JSON.",
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=30,
            )
            content = "".join(part.get("text", "") for part in response.get("content", []))

        elif provider == "gemini":
            response = http_json(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}",
                {},
                {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0,
                        "maxOutputTokens": 800,
                        "responseMimeType": "application/json",
                    },
                },
                timeout=30,
            )
            content = response.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")

        elif is_gemini_vertex_config(api):
            content = gemini_vertex_generate_content(
                api,
                prompt,
                temperature=0,
                timeout=120 if is_gemini_vertex_thinking_config(api) else 45,
                max_output_tokens=2500 if is_gemini_vertex_thinking_config(api) else 1000,
            )

        else:
            return {
                "ok": False,
                "provider": provider,
                "model": model,
                "message": f"暂不支持测试这个 Provider：{provider}",
            }

        latency_ms = int((time.time() - started) * 1000)
        ok, message = validate_api_test_payload(str(content))
        return {
            "ok": ok,
            "provider": provider,
            "model": model,
            "message": message,
            "latency_ms": latency_ms,
        }
    except Exception as err:
        return {
            "ok": False,
            "provider": provider,
            "model": model,
            "message": str(err),
            "latency_ms": int((time.time() - started) * 1000),
        }


def normalized_tts_config(project_or_payload: dict[str, Any]) -> dict[str, Any]:
    api = project_or_payload.get("api_config") or project_or_payload
    tts = project_or_payload.get("tts_config") or api.get("tts_config") or {}
    legacy_provider = api.get("tts_provider", "")
    legacy_model = api.get("tts_model", "")
    provider = str(tts.get("provider") or legacy_provider or "disabled").strip().lower()
    base_url = str(tts.get("base_url") or "").strip()
    api_base_url = str(api.get("base_url") or "").strip()
    api_key = str(tts.get("api_key") or "").strip()
    main_api_key = str(api.get("api_key") or "").strip()
    main_is_mimo = provider_name(api) in MIMO_PROVIDERS or "xiaomimimo.com" in api_base_url.lower()
    main_is_qwen = provider_name(api) == "openai-compatible" and (
        "dashscope" in api_base_url.lower() or "qwencloud" in api_base_url.lower()
    )

    if provider in MIMO_PROVIDERS:
        stale_token_plan_key = (
            api_key.lower().startswith("tp-")
            and main_api_key.lower().startswith("tp-")
            and api_key != main_api_key
            and main_is_mimo
        )
        if (not api_key or stale_token_plan_key) and main_is_mimo:
            api_key = main_api_key
        if not base_url and main_is_mimo:
            base_url = api_base_url
        if not base_url:
            base_url = MIMO_TOKEN_PLAN_SGP_BASE_URL if api_key.lower().startswith("tp-") else MIMO_OPENAI_BASE_URL
        if api_key.lower().startswith("tp-") and "token-plan-" not in base_url.lower():
            base_url = MIMO_TOKEN_PLAN_SGP_BASE_URL

    if provider in QWEN_TTS_PROVIDERS:
        if not api_key and main_is_qwen:
            api_key = main_api_key
        if not base_url:
            base_url = QWEN_DASHSCOPE_CN_TTS_BASE_URL

    if provider in GEMINI_VERTEX_TTS_PROVIDERS and not base_url:
        base_url = GEMINI_VERTEX_TTS_GLOBAL_BASE_URL

    return {
        "enabled": bool(tts.get("enabled", False)),
        "provider": provider,
        "base_url": base_url,
        "api_key": api_key,
        "model": str(
            tts.get("model") or (GEMINI_VERTEX_TTS_DEFAULT_MODEL if provider in GEMINI_VERTEX_TTS_PROVIDERS else "")
        ).strip(),
        "voice": str(
            tts.get("voice") or legacy_model or (GEMINI_VERTEX_TTS_DEFAULT_VOICE if provider in GEMINI_VERTEX_TTS_PROVIDERS else "")
        ).strip(),
        "language": str(tts.get("language") or ("en-US" if provider in GEMINI_VERTEX_TTS_PROVIDERS else "auto")).strip()
        or "auto",
        "sample_rate": int(tts.get("sample_rate") or 24000),
        "bit_rate": int(tts.get("bit_rate") or 128000),
    }


def grok_tts_endpoint(base_url: str) -> str:
    return f"{(base_url or 'https://api.x.ai/v1').rstrip('/')}/tts"


def openai_speech_endpoint(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/audio/speech"


def qwen_tts_endpoint(base_url: str) -> str:
    base = (base_url or QWEN_DASHSCOPE_CN_TTS_BASE_URL).rstrip("/")
    if base.endswith("/services/aigc/multimodal-generation/generation"):
        return base
    return f"{base}/services/aigc/multimodal-generation/generation"


def gemini_vertex_tts_location(config: dict[str, Any]) -> str:
    explicit = str(config.get("location") or config.get("region") or "").strip()
    if explicit:
        return explicit
    base_url = str(config.get("base_url") or "").strip().rstrip("/")
    if base_url:
        try:
            host = urllib.parse.urlparse(base_url).hostname or ""
        except ValueError:
            host = ""
        if host == "aiplatform.googleapis.com":
            return "global"
        suffix = "-aiplatform.googleapis.com"
        if host.endswith(suffix):
            return host[: -len(suffix)]
    return "global"


def gemini_vertex_tts_base_url(config: dict[str, Any], location: str) -> str:
    base_url = str(config.get("base_url") or "").strip().rstrip("/")
    if base_url:
        return base_url
    return GEMINI_VERTEX_TTS_GLOBAL_BASE_URL if location == "global" else f"https://{location}-aiplatform.googleapis.com"


def gemini_vertex_tts_endpoint(config: dict[str, Any]) -> str:
    model = str(config.get("model") or GEMINI_VERTEX_TTS_DEFAULT_MODEL).strip()
    project = gemini_vertex_project(config)
    location = gemini_vertex_tts_location(config)
    base_url = gemini_vertex_tts_base_url(config, location)
    return (
        f"{base_url}/v1beta1/projects/{urllib.parse.quote(project, safe='')}"
        f"/locations/{urllib.parse.quote(location, safe='')}/publishers/google/models/"
        f"{urllib.parse.quote(model, safe='')}:generateContent"
    )


def wav_from_pcm_s16le(pcm: bytes, sample_rate: int = 24000, channels: int = 1) -> bytes:
    sample_width = 2
    data_size = len(pcm)
    byte_rate = sample_rate * channels * sample_width
    block_align = channels * sample_width
    return b"".join(
        [
            b"RIFF",
            (36 + data_size).to_bytes(4, "little"),
            b"WAVE",
            b"fmt ",
            (16).to_bytes(4, "little"),
            (1).to_bytes(2, "little"),
            channels.to_bytes(2, "little"),
            sample_rate.to_bytes(4, "little"),
            byte_rate.to_bytes(4, "little"),
            block_align.to_bytes(2, "little"),
            (sample_width * 8).to_bytes(2, "little"),
            b"data",
            data_size.to_bytes(4, "little"),
            pcm,
        ]
    )


def qwen_language_type(language: str) -> str:
    lower = str(language or "").strip().lower()
    if lower in {"auto", ""}:
        return "Auto"
    if lower.startswith("zh") or "中文" in lower or "chinese" in lower:
        return "Chinese"
    if lower.startswith("en") or "english" in lower:
        return "English"
    if lower.startswith("ja") or "japanese" in lower or "日本" in lower:
        return "Japanese"
    if lower.startswith("ko") or "korean" in lower:
        return "Korean"
    if lower.startswith("fr") or "french" in lower:
        return "French"
    if lower.startswith("de") or "german" in lower:
        return "German"
    if lower.startswith("es") or "spanish" in lower:
        return "Spanish"
    if lower.startswith("pt") or "portuguese" in lower:
        return "Portuguese"
    if lower.startswith("it") or "italian" in lower:
        return "Italian"
    if lower.startswith("ru") or "russian" in lower:
        return "Russian"
    return "Auto"


def gemini_vertex_tts_language_code(language: str) -> str:
    lower = str(language or "").strip().lower()
    if lower in {"", "auto"}:
        return "en-US"
    if lower in {"en", "english", "english (united states)", "us english", "american english"}:
        return "en-US"
    if lower in {"zh", "chinese", "mandarin", "中文", "普通话"}:
        return "cmn-CN"
    if re.fullmatch(r"[a-z]{2,3}-[a-z0-9]{2,4}", lower):
        left, right = lower.split("-", 1)
        return f"{left}-{right.upper()}"
    return language


def clean_tts_input_text(value: Any) -> str:
    text = clean_study_text(value)
    text = re.sub(r"\s+", " ", text).strip(" \t\r\n\"“”")
    if not text:
        raise RuntimeError("TTS 文本为空，无法生成音频。")
    return text


def mimo_tts_audio(tts: dict[str, Any], text: str, language: str) -> bytes:
    model = tts["model"] or "mimo-v2.5-tts"
    voice = (tts.get("voice") or "").strip()
    model_lower = model.lower()

    if "voicedesign" in model_lower:
        user_content = voice or "A clear, natural voice for language-learning flashcards."
        audio: dict[str, str] = {"format": "wav"}
    elif "voiceclone" in model_lower:
        user_content = ""
        audio = {"format": "wav"}
        if voice:
            audio["voice"] = voice
    else:
        user_content = f"Read naturally and clearly for a {language or 'en'} language-learning Anki card."
        audio = {
            "format": "wav",
            "voice": voice or "mimo_default",
        }

    response = http_json(
        f"{compatible_base_url(tts)}/chat/completions",
        api_key_header(tts),
        {
            "model": model,
            "messages": [
                {"role": "user", "content": user_content},
                {"role": "assistant", "content": text},
            ],
            "audio": audio,
            "stream": False,
        },
        timeout=120,
    )
    message = response.get("choices", [{}])[0].get("message", {})
    data = (message.get("audio") or {}).get("data")
    if not data:
        raise RuntimeError("MIMO TTS 没有返回 audio.data。请检查模型、voice 和套餐权限。")
    return base64.b64decode(data)


def qwen_tts_audio(tts: dict[str, Any], text: str, language: str) -> bytes:
    model = tts["model"] or QWEN_TTS_DEFAULT_MODEL
    body = {
        "model": model,
        "input": {
            "text": text,
            "voice": tts.get("voice") or QWEN_TTS_DEFAULT_VOICE,
            "language_type": qwen_language_type(tts.get("language") or language),
        },
    }
    model_lower = model.lower()
    if "instruct" in model_lower:
        body["input"]["instructions"] = (
            "Read naturally and clearly for a language-learning Anki card. "
            "Use steady pacing and accurate pronunciation."
        )
        body["input"]["optimize_instructions"] = True
    response = http_json(
        qwen_tts_endpoint(tts.get("base_url") or QWEN_DASHSCOPE_CN_TTS_BASE_URL),
        {"Authorization": f"Bearer {tts['api_key']}"},
        body,
        timeout=120,
    )
    audio = ((response.get("output") or {}).get("audio") or {})
    data = audio.get("data")
    if data:
        return base64.b64decode(data)
    url = audio.get("url")
    if url:
        return http_get_binary(str(url), timeout=120)
    raise RuntimeError("Qwen TTS 没有返回 output.audio.url 或 output.audio.data。请检查模型、voice、地域和 API Key。")


def gemini_vertex_tts_audio(tts: dict[str, Any], text: str, language: str) -> bytes:
    model = str(tts.get("model") or GEMINI_VERTEX_TTS_DEFAULT_MODEL).strip()
    if not model:
        raise RuntimeError("Gemini Vertex TTS 需要模型名。")
    project = gemini_vertex_project(tts)
    token = gcloud_value(["auth", "print-access-token"])
    speech_text = clean_tts_input_text(text)
    body = {
        "contents": {
            "role": "user",
            "parts": {"text": speech_text},
        },
        "generation_config": {
            "speech_config": {
                "language_code": gemini_vertex_tts_language_code(tts.get("language") or language),
                "voice_config": {
                    "prebuilt_voice_config": {
                        "voice_name": str(tts.get("voice") or GEMINI_VERTEX_TTS_DEFAULT_VOICE).strip(),
                    }
                },
            }
        },
    }
    response = http_json(
        gemini_vertex_tts_endpoint({**tts, "model": model, "project": project}),
        {"Authorization": f"Bearer {token}", "x-goog-user-project": project},
        body,
        timeout=120,
    )
    for candidate in response.get("candidates", []) or []:
        content = candidate.get("content") or {}
        for part in content.get("parts", []) or []:
            inline = part.get("inlineData") or part.get("inline_data") or {}
            data = inline.get("data")
            if data:
                return wav_from_pcm_s16le(base64.b64decode(data), sample_rate=int(tts.get("sample_rate") or 24000))
    raise RuntimeError("Gemini Vertex TTS 没有返回 inlineData 音频。请检查 Vertex AI 权限、模型、区域和 voice。")


def call_tts_audio(tts: dict[str, Any], text: str, language: str) -> bytes:
    provider = tts["provider"]
    api_key = tts["api_key"]
    text = clean_tts_input_text(text)
    if provider in {"grok", "xai"}:
        return http_binary(
            grok_tts_endpoint(tts["base_url"]),
            {"Authorization": f"Bearer {api_key}"},
            {
                "text": text,
                "voice_id": tts["voice"] or "eve",
                "language": tts["language"] or language or "auto",
                "output_format": {
                    "codec": "mp3",
                    "sample_rate": tts["sample_rate"],
                    "bit_rate": tts["bit_rate"],
                },
            },
        )

    if is_mimo_config(tts):
        return mimo_tts_audio(tts, text, language)

    if provider in QWEN_TTS_PROVIDERS:
        return qwen_tts_audio(tts, text, language)

    if is_gemini_vertex_tts_config(tts):
        return gemini_vertex_tts_audio(tts, text, language)

    if provider in OPENAI_COMPATIBLE_PROVIDERS:
        return http_binary(
            openai_speech_endpoint(compatible_base_url(tts)),
            api_key_header(tts),
            {
                "model": tts["model"],
                "input": text,
                "voice": tts["voice"] or "alloy",
                "response_format": "mp3",
            },
        )

    raise RuntimeError(f"不支持这个 TTS Provider：{provider}")


def handle_test_tts(payload: dict[str, Any]) -> dict[str, Any]:
    tts = normalized_tts_config(payload)
    language = str(payload.get("language") or "English")
    started = time.time()

    if not tts["enabled"] or tts["provider"] == "disabled":
        return {
            "ok": False,
            "provider": tts["provider"],
            "model": tts["model"],
            "voice": tts["voice"],
            "message": "TTS 当前是关闭状态。",
        }
    if not tts["api_key"] and not is_gemini_vertex_tts_config(tts):
        return {
            "ok": False,
            "provider": tts["provider"],
            "model": tts["model"],
            "voice": tts["voice"],
            "message": "缺少 TTS API Key。",
        }

    try:
        text = "This is a TTS test for your Anki cards."
        if tts["provider"] == "gemini":
            if not tts["model"]:
                return {
                    "ok": False,
                    "provider": tts["provider"],
                    "model": tts["model"],
                    "voice": tts["voice"],
                    "message": "Gemini TTS 需要模型名。",
                }
            response = http_json(
                f"https://generativelanguage.googleapis.com/v1beta/models/{tts['model']}:generateContent",
                {"x-goog-api-key": tts["api_key"]},
                {
                    "contents": [{"parts": [{"text": f"Read naturally and clearly: {text}"}]}],
                    "generationConfig": {
                        "responseModalities": ["AUDIO"],
                        "speechConfig": {
                            "voiceConfig": {
                                "prebuiltVoiceConfig": {
                                    "voiceName": tts["voice"] or "Kore",
                                }
                            }
                        },
                    },
                    "model": tts["model"],
                },
                timeout=45,
            )
            data = response["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
            audio_size = len(base64.b64decode(data))
        else:
            if is_gemini_vertex_tts_config(tts) and not tts["model"]:
                return {
                    "ok": False,
                    "provider": tts["provider"],
                    "model": tts["model"],
                    "voice": tts["voice"],
                    "message": "Gemini Vertex TTS 需要模型名。",
                }
            if tts["provider"] in OPENAI_COMPATIBLE_PROVIDERS and (not compatible_base_url(tts) or not tts["model"]):
                return {
                    "ok": False,
                    "provider": tts["provider"],
                    "model": tts["model"],
                    "voice": tts["voice"],
                    "message": "MIMO / OpenAI-compatible Speech 需要 Base URL 和模型名。",
                }
            audio_size = len(call_tts_audio(tts, text, language_code(language)))

        return {
            "ok": True,
            "provider": tts["provider"],
            "model": tts["model"],
            "voice": tts["voice"],
            "message": f"测试音频生成成功，大小 {audio_size} bytes。",
            "latency_ms": int((time.time() - started) * 1000),
            "bytes": audio_size,
        }
    except Exception as err:
        message = str(err)
        if (
            is_mimo_config(tts)
            and tts["api_key"].lower().startswith("tp-")
            and "api.xiaomimimo.com" in compatible_base_url(tts).lower()
        ):
            message = (
                "你的 TTS Key 是 tp- 开头的 Token Plan Key，不能配公共 "
                "https://api.xiaomimimo.com/v1。请把 TTS Base URL 改成 "
                "https://token-plan-sgp.xiaomimimo.com/v1，或直接点 MIMO SGP TTS 预设。"
            )
        return {
            "ok": False,
            "provider": tts["provider"],
            "model": tts["model"],
            "voice": tts["voice"],
            "message": message,
            "latency_ms": int((time.time() - started) * 1000),
        }


def merge_ai_cards(
    segments: list[dict[str, Any]],
    ai_payload: dict[str, Any] | None,
    card_types: list[str],
    level: str,
) -> tuple[list[dict[str, Any]], str | None]:
    ai_by_segment: dict[str, dict[str, Any]] = {}
    warning = None
    if ai_payload:
        if "error" in ai_payload:
            warning = f"部分模型精修失败，未精修片段会保留为停用的本地草稿：{ai_payload['error']}"
        for item in ai_payload.get("segments", []):
            ai_by_segment[item.get("id", "")] = item

    for segment in segments:
        ai_segment = ai_by_segment.get(segment["id"])
        fallback = fallback_cards(segment, card_types, level)
        cards = fallback
        if ai_payload is None:
            warning = warning or "模型没有返回可用精修结果，本地草稿已默认停用，请人工检查后再导出。"
        if ai_segment:
            ai_cards_by_type = {card.get("type"): card for card in ai_segment.get("cards", [])}
            usable_ai_cards = [
                card
                for card in ai_segment.get("cards", [])
                if card.get("phrase") or card.get("chinese") or card.get("definition")
            ]
            ai_template_card = usable_ai_cards[0] if usable_ai_cards else None
            cards = []
            for card in fallback:
                ai_card = ai_cards_by_type.get(card["type"]) or ai_template_card
                if card.get("card_role") == "specialist" and card["type"] not in ai_cards_by_type:
                    continue
                if not ai_card:
                    continue
                for key in [
                    "chinese",
                    "phrase",
                    "definition",
                    "collocations",
                    "context",
                    "example",
                    "chinese_feel",
                    "why",
                    "difficulty",
                    "teacher_note",
                    "cloze",
                    "card_role",
                    "learning_goal",
                    "decision_reason",
                    "learning_target",
                    "why_it_matters",
                    "how_to_use_it",
                    "natural_chinese",
                    "replacement_examples",
                    "avoid_reason",
                    "phrase_value_score",
                    "phrase_decision_reason",
                    "phrase_reject_reason",
                    "phrase_card_focus",
                    "phrase_review_status",
                    "phrase_type",
                    "content_kind",
                    "candidate_kind",
                    "exact_span",
                    "normalized_answer",
                    "candidate_source",
                    "learning_point_schema_version",
                    "source_evidence",
                    "retrieval_prompt",
                    "answer_core",
                    "usage_boundary",
                    "confusable_note",
                ]:
                    if ai_card.get(key):
                        card[key] = str(ai_card[key])
                if card["type"] == "phrase":
                    phrase_type = str(card.get("phrase_type") or segment.get("phrase_type") or "")
                    if phrase_type:
                        card["phrase_type"] = phrase_type
                        card["content_kind"] = card.get("content_kind") or content_kind_for_phrase_type(phrase_type)
                    card["type_label"] = card_label_for_learning_card(
                        str(card.get("phrase_type") or ""),
                        str(card.get("content_kind") or ""),
                        card.get("type_label", "表达卡"),
                    )
                if ai_card is ai_template_card and card["type"] not in ai_cards_by_type:
                    card["teacher_note"] = (
                        card.get("teacher_note")
                        or "同片段 AI 已识别出重点表达，这张卡由系统补齐为对应训练任务。"
                    )
                normalize_learning_action_fields(card)
                repair_card_fields(card, segment, level)
                for key in [
                    "phrase_value_score",
                    "phrase_decision_reason",
                    "phrase_reject_reason",
                    "phrase_card_focus",
                    "phrase_review_status",
                    "phrase_type",
                    "content_kind",
                    "candidate_kind",
                    "exact_span",
                    "normalized_answer",
                    "candidate_source",
                    "learning_point_schema_version",
                    "source_evidence",
                ]:
                    if segment.get(key) not in (None, ""):
                        card[key] = segment.get(key)
                if card["type"] == "phrase":
                    phrase_type = str(card.get("phrase_type") or "")
                    if phrase_type:
                        card["content_kind"] = card.get("content_kind") or content_kind_for_phrase_type(phrase_type)
                    card["type_label"] = card_label_for_learning_card(
                        str(card.get("phrase_type") or ""),
                        str(card.get("content_kind") or ""),
                        card.get("type_label", "表达卡"),
                    )
                card["quality"] = assess_card_quality(card, segment, "ai", level)
                card["enabled"] = card["quality"]["status"] == "recommended"
                cards.append(card)
            if not cards and fallback:
                cards = [fallback[0]]
        segment["cards"] = cards
    return segments, warning


def yt_dlp_base_command() -> list[str] | None:
    executable = shutil.which("yt-dlp")
    if executable:
        return [executable]

    completed = subprocess.run(
        [sys.executable, "-m", "yt_dlp", "--version"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        **hidden_subprocess_flags(),
    )
    if completed.returncode == 0:
        return [sys.executable, "-m", "yt_dlp"]
    return None


def yt_dlp_js_runtime_args() -> list[str]:
    if shutil.which("deno"):
        return ["--js-runtimes", "deno", "--remote-components", "ejs:github"]
    if shutil.which("node"):
        return ["--js-runtimes", "node", "--remote-components", "ejs:github"]
    if shutil.which("bun"):
        return ["--js-runtimes", "bun", "--remote-components", "ejs:github"]
    return []


def yt_dlp_network_args() -> list[str]:
    args = [
        "--force-ipv4",
        "--retries",
        "10",
        "--fragment-retries",
        "10",
        "--extractor-retries",
        "5",
        "--retry-sleep",
        "http:linear=3::20",
        "--sleep-requests",
        "0.75",
        "--sleep-subtitles",
        "1.5",
    ]
    if importlib.util.find_spec("curl_cffi"):
        args.extend(["--impersonate", "chrome"])
    return args


def yt_dlp_failure_detail(completed: subprocess.CompletedProcess[str]) -> str:
    return (completed.stderr or completed.stdout or "").strip()


def is_subtitle_rate_limited(detail: str) -> bool:
    lower = detail.lower()
    return "http error 429" in lower and "subtitles" in lower


def format_yt_dlp_failure(detail: str) -> str:
    tail = detail[-1800:]
    if "HTTP Error 429" in detail:
        return (
            "URL 下载失败：YouTube 返回 HTTP 429，说明当前网络/IP 被临时限流，尤其是字幕接口。"
            "我已经启用了 EJS、重试、降速和浏览器模拟；如果仍失败，请稍后重试、换网络/代理，"
            "或先下载/准备本地 SRT 后走“本地视频 + SRT”。\n\n"
            f"yt-dlp 原始信息：{tail}"
        )
    if "n challenge solving failed" in detail or "Remote component challenge solver" in detail:
        return (
            "URL 下载失败：YouTube JS challenge 没有解开。请运行 scripts/setup_runtime.ps1 更新依赖，"
            "并确保已安装 Deno 2.0+ 或 Node.js 20+。新版会自动给 yt-dlp 加 "
            "--remote-components ejs:github。\n\n"
            f"yt-dlp 原始信息：{tail}"
        )
    return f"URL 下载失败：{tail}"


def yt_dlp_failure_meta(detail: str) -> dict[str, Any]:
    if "HTTP Error 429" in detail:
        return {
            "error_code": "YOUTUBE_RATE_LIMIT",
            "stage": "download_subtitles" if "subtitles" in detail.lower() else "download_video",
            "retryable": True,
            "fallbacks": ["subtitle_only", "local_srt"],
        }
    if "n challenge solving failed" in detail or "Remote component challenge solver" in detail:
        return {
            "error_code": "YOUTUBE_N_CHALLENGE",
            "stage": "download_video",
            "retryable": True,
            "fallbacks": ["subtitle_only", "local_srt"],
        }
    return {
        "error_code": "YOUTUBE_SUBTITLE_UNAVAILABLE" if "subtitles" in detail.lower() else None,
        "stage": "download_subtitles" if "subtitles" in detail.lower() else "download_video",
        "retryable": True,
        "fallbacks": ["subtitle_only", "local_srt"],
    }


def run_yt_dlp(args: list[str], timeout: int = 900, check: bool = True) -> subprocess.CompletedProcess[str]:
    command = yt_dlp_base_command()
    if not command:
        fail("找不到 yt-dlp。请运行：pip install yt-dlp，或把 yt-dlp 加入 PATH。")

    completed = subprocess.run(
        [*command, *yt_dlp_js_runtime_args(), *yt_dlp_network_args(), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if check and completed.returncode != 0:
        detail = yt_dlp_failure_detail(completed)
        fail(format_yt_dlp_failure(detail), **yt_dlp_failure_meta(detail))
    return completed


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


def discover_local_subtitle(video_path: str, language: str = "English") -> Path | None:
    video = Path(clean_input_path(video_path))
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


TEXT_SUBTITLE_CODECS = {"subrip", "ass", "ssa", "webvtt", "mov_text"}


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
    if any(value in lower for value in ["ko", "korean", "한국"]):
        return {"ko", "kor", "korean"}
    return {"en", "eng", "english", "en-us", "en-gb"}


def run_ffprobe_json(video_path: Path) -> dict[str, Any] | None:
    if not shutil.which("ffprobe"):
        return None
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_streams",
            str(video_path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        **hidden_subprocess_flags(),
    )
    if completed.returncode != 0:
        return None
    try:
        return json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        return None


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


def extract_embedded_subtitle(video_path: str, language: str = "English") -> Path | None:
    video = Path(clean_input_path(video_path))
    if not video.exists() or not shutil.which("ffmpeg"):
        return None

    probe = run_ffprobe_json(video)
    stream = select_embedded_subtitle_stream(probe, language)
    if not stream:
        return None

    stream_index = stream.get("index")
    if stream_index is None:
        return None

    fingerprint_source = f"{video.resolve()}|{video.stat().st_mtime_ns}|{video.stat().st_size}|{stream_index}"
    fingerprint = hashlib.sha1(fingerprint_source.encode("utf-8", errors="ignore")).hexdigest()[:16]
    output_dir = Path.cwd() / "projects" / "local_subtitles"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{safe_filename(video.stem)}_stream_{stream_index}_{fingerprint}.srt"
    if output_path.exists() and output_path.stat().st_size > 0:
        return output_path

    completed = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video),
            "-map",
            f"0:{stream_index}",
            "-c:s",
            "srt",
            str(output_path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0 or not output_path.exists() or output_path.stat().st_size == 0:
        output_path.unlink(missing_ok=True)
        return None
    return output_path


def read_download_info(directory: Path) -> dict[str, Any]:
    info_files = sorted(directory.glob("*.info.json"))
    if not info_files:
        return {}
    info_file = info_files[0]
    try:
        data = json.loads(info_file.read_text(encoding="utf-8", errors="replace"))
        return {
            "title": data.get("title") or "",
            "webpage_url": data.get("webpage_url") or data.get("original_url") or "",
            "duration": data.get("duration"),
            "uploader": data.get("uploader") or "",
        }
    except Exception:
        return {}


def wants_subtitle_only(payload: dict[str, Any]) -> bool:
    mode = str(payload.get("url_import_mode") or "").strip().lower()
    return bool(payload.get("skip_video_slicing")) or mode in {"subtitles", "subtitle", "subtitle_only", "transcript"}


def find_cached_url_source(cache_root: Path, url_hash: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    candidates = [path for path in cache_root.glob(f"url_*{url_hash}") if path.is_dir()]
    stable_candidate = cache_root / f"url_{url_hash}"
    if stable_candidate.exists() and stable_candidate not in candidates:
        candidates.insert(0, stable_candidate)
    candidates = sorted(candidates, key=lambda path: path.stat().st_mtime if path.exists() else 0, reverse=True)

    for directory in candidates:
        video_path = first_file_by_suffix(directory, (".mp4", ".mkv", ".webm", ".mov"))
        subtitle_path = pick_subtitle_file(directory, payload.get("language", "English"))
        if not subtitle_path or (not video_path and not wants_subtitle_only(payload)):
            continue
        info = read_download_info(directory)
        return {
            "video_path": str(video_path) if video_path else "",
            "subtitle_path": str(subtitle_path),
            "download_dir": str(directory),
            "url": str(payload.get("source_url") or "").strip(),
            "cached": True,
            "transcript_only": not bool(video_path),
            "skip_video_slicing": not bool(video_path) or bool(payload.get("skip_video_slicing")),
            "download_mode": "subtitles" if not video_path else "video",
            **info,
        }
    return None


def download_url_subtitles_only(payload: dict[str, Any], download_dir: Path, output_template: str, sub_langs: str) -> dict[str, Any]:
    url = str(payload.get("source_url") or "").strip()
    args = [
        "--no-playlist",
        "--windows-filenames",
        "--write-info-json",
        "--skip-download",
        "--sub-langs",
        sub_langs,
        "--convert-subs",
        "srt",
        "--output",
        output_template,
        "--write-subs",
        "--write-auto-subs",
        url,
    ]
    completed = run_yt_dlp(args, check=False)
    if completed.returncode != 0:
        detail = yt_dlp_failure_detail(completed)
        fail(format_yt_dlp_failure(detail), **yt_dlp_failure_meta(detail))

    subtitle_path = pick_subtitle_file(download_dir, payload.get("language", "English"))
    if not subtitle_path:
        fail(
            "URL 字幕下载完成，但没有找到可用 SRT/VTT。请换一个带字幕的视频，或手动上传 SRT。",
            error_code="YOUTUBE_SUBTITLE_UNAVAILABLE",
            stage="download_subtitles",
            retryable=True,
            fallbacks=["local_srt"],
        )

    info = read_download_info(download_dir)
    return {
        "video_path": "",
        "subtitle_path": str(subtitle_path),
        "download_dir": str(download_dir),
        "url": url,
        "transcript_only": True,
        "skip_video_slicing": True,
        "download_mode": "subtitles",
        "warning": "本次只使用字幕生成卡片，导出的 APKG 不包含视频片段和原声音频。",
        **info,
    }


def download_url_source(payload: dict[str, Any]) -> dict[str, Any]:
    url = str(payload.get("source_url") or "").strip()
    if not url:
        fail("请输入 YouTube / 视频 URL。")
    if not re.match(r"^https?://", url, flags=re.IGNORECASE):
        fail("URL 需要以 http:// 或 https:// 开头。")

    cache_root = Path.cwd() / "projects" / "url_cache"
    cache_root.mkdir(parents=True, exist_ok=True)
    url_hash = f"{zlib.crc32(url.encode('utf-8')) & 0xFFFFFFFF:x}"
    cached_source = find_cached_url_source(cache_root, url_hash, payload)
    if cached_source:
        return cached_source

    download_dir = cache_root / f"url_{url_hash}"
    download_dir.mkdir(parents=True, exist_ok=True)

    output_template = str(download_dir / "source.%(ext)s")
    sub_langs = subtitle_language_args(payload.get("language", "English"))
    if wants_subtitle_only(payload):
        return download_url_subtitles_only(payload, download_dir, output_template, sub_langs)

    common_args = [
        "--no-playlist",
        "--windows-filenames",
        "--write-info-json",
        "--sub-langs",
        sub_langs,
        "--convert-subs",
        "srt",
        "--format",
        "bv*[height<=480]+ba/b[height<=480]/best[height<=480]/best",
        "--merge-output-format",
        "mp4",
        "--output",
        output_template,
    ]
    download_args = [
        *common_args,
        "--write-subs",
        "--write-auto-subs",
        url,
    ]
    completed = run_yt_dlp(download_args, check=False)
    if completed.returncode != 0:
        detail = yt_dlp_failure_detail(completed)
        if is_subtitle_rate_limited(detail):
            # If YouTube rate-limits official subtitles, try auto subtitles only once after a short pause.
            time.sleep(8)
            retry = run_yt_dlp(
                [
                    *common_args,
                    "--write-auto-subs",
                    url,
                ],
                check=False,
            )
            if retry.returncode != 0:
                retry_detail = yt_dlp_failure_detail(retry) or detail
                if payload.get("url_auto_subtitle_fallback", True):
                    try:
                        return download_url_subtitles_only(payload, download_dir, output_template, sub_langs)
                    except SystemExit as err:
                        fail(
                            f"{format_yt_dlp_failure(retry_detail)}\n\n字幕-only fallback 也失败，退出码：{err.code}",
                            **yt_dlp_failure_meta(retry_detail),
                        )
                fail(format_yt_dlp_failure(retry_detail), **yt_dlp_failure_meta(retry_detail))
        else:
            if payload.get("url_auto_subtitle_fallback", True):
                try:
                    return download_url_subtitles_only(payload, download_dir, output_template, sub_langs)
                except SystemExit as err:
                    fail(
                        f"{format_yt_dlp_failure(detail)}\n\n字幕-only fallback 也失败，退出码：{err.code}",
                        **yt_dlp_failure_meta(detail),
                    )
            fail(format_yt_dlp_failure(detail), **yt_dlp_failure_meta(detail))

    video_path = first_file_by_suffix(download_dir, (".mp4", ".mkv", ".webm", ".mov"))
    if not video_path:
        fail("URL 已处理，但没有找到下载后的视频文件。")

    subtitle_path = pick_subtitle_file(download_dir, payload.get("language", "English"))
    if not subtitle_path:
        if payload.get("url_auto_subtitle_fallback", True):
            return download_url_subtitles_only(payload, download_dir, output_template, sub_langs)
        fail(
            "视频已下载，但没有下载到可用字幕。请换一个带字幕/自动字幕的视频，或改用本地 SRT。",
            error_code="YOUTUBE_SUBTITLE_UNAVAILABLE",
            stage="download_subtitles",
            retryable=True,
            fallbacks=["local_srt"],
        )

    info = read_download_info(download_dir)
    return {
        "video_path": str(video_path),
        "subtitle_path": str(subtitle_path),
        "download_dir": str(download_dir),
        "url": url,
        "transcript_only": False,
        "skip_video_slicing": bool(payload.get("skip_video_slicing")),
        "download_mode": "video",
        **info,
    }


def build_document_prompt(project: dict[str, Any], segments: list[dict[str, Any]]) -> str:
    focus_instruction = document_focus_instruction(project)
    style_instruction = document_style_instruction(project)
    study_mode = normalized_document_study_mode(project)
    material_context_instruction = material_context_for_prompt(project.get("material_context"))
    compact = [
        {
            "id": segment["id"],
            "source": segment["source_time"],
            "question_hint": segment["text"],
            "excerpt": segment.get("document_excerpt", ""),
        }
        for segment in segments
    ]
    if study_mode == "language_reading":
        reading_focus = normalized_document_reading_focus(project)
        focus_labels = {
            "phrases": "词伙表达：抽取可迁移短语、搭配和句型块，禁止整句当词伙。",
            "vocabulary": "单词用法：抽取真实语境里的词义、搭配和易错用法，不做孤立词典卡。",
            "grammar": "语法框架：抽取可替换句型、结构和语气功能，不做抽象语法定义。",
        }
        focus_instruction = "".join(focus_labels[item] for item in reading_focus)
        return (
            "你是中文母语者的英文文档精读老师和 Anki 卡片编辑老师。请从文档片段里抽取语言学习点，"
            "不是总结知识内容。重点是让学习者下次能读懂、会用或能辨认表达结构。"
            f"{material_context_instruction}"
            "文档没有原声，禁止生成听力卡，禁止提到原声/TTS/视频切片。"
            f"本次语言精读目标：{focus_instruction}"
            f"{style_instruction}"
            "制卡标准："
            "1) 每张卡只训练一个语言动作：理解一个表达、掌握一个词的用法、看懂一个语法框架。"
            "2) phrase 必须来自原文片段，不能是 key expression，不能是整句。"
            "3) english 写主动回忆问题或原文提示；chinese 写自然中文理解。"
            "4) definition 写怎么理解；collocations 写可替换框架/搭配；context 写文档语境。"
            "5) why 和 teacher_note 必须说明为什么这个语言点值得学、下次怎么辨认或复用。"
            "6) 弱卡默认待审：不要为了数量硬凑语言点。"
            "返回严格 JSON，不要 Markdown。JSON 结构："
            '{"segments":[{"id":"doc_0001","cards":[{"type":"knowledge",'
            '"knowledge_type":"terms|concepts|examples","english":"正面问题或原文提示","chinese":"自然中文理解",'
            '"phrase":"原文中的表达/单词/语法框架","definition":"怎么理解",'
            '"collocations":"替换框架/搭配","context":"文档语境","example":"原文例子或改写例子","chinese_feel":"中文直觉",'
            '"why":"为什么值得学","difficulty":"A1 入门|A2 基础|B1 日常交流|B2 独立表达|C1 高阶表达|C2 接近母语",'
            '"teacher_note":"一句老师提醒","learning_target":"这张卡练什么",'
            '"why_it_matters":"为什么值得学","how_to_use_it":"下次如何辨认或复用",'
            '"cloze":"挖空复习句，且只有一个 ____"}]}]}。'
            f"用户水平：{project.get('level', 'B1')}。"
            f"文档片段：{json.dumps(compact, ensure_ascii=False)}"
        )
    return (
        "你是中文母语者的读书笔记老师和 Anki 知识卡编辑老师。请把文档片段变成少而精的知识卡，"
        "不要把它当摘要任务。先判断这段到底值得记什么，再写卡片。"
        f"{material_context_instruction}"
        f"{focus_instruction}"
        f"{style_instruction}"
        "制卡标准："
        "1) 每张卡只训练一个知识动作：定义一个概念、解释一个观点、区分一组概念、记住一个例子。"
        "2) 正面 english 必须是可主动回忆的问题；不要写“这段主要讲什么”这种泛问题。"
        "3) 反面 chinese 必须短而准，优先 1-3 句；不要照抄整段原文。"
        "4) phrase 是概念名、观点名或术语，必须短；禁止输出“核心知识点”“知识点”“章节标题”“N/A”。"
        "5) definition 写怎么理解；collocations 写相关概念/对比项；context 写出现语境或适用范围。"
        "6) example 必须来自文档例子或基于文档改写，不能空泛编造。"
        "7) why 和 teacher_note 要解释为什么值得记、复习时怎么抓关键，不要写套话。"
        "8) 如果片段只有铺垫、目录、广告、空泛背景，cards 返回空数组。"
        "返回严格 JSON，不要 Markdown。JSON 结构："
        '{"segments":[{"id":"doc_0001","cards":[{"type":"knowledge",'
        '"knowledge_type":"concepts|arguments|terms|examples","english":"正面问题","chinese":"反面核心答案",'
        '"phrase":"概念名/观点名/术语","definition":"概念解释",'
        '"collocations":"相关概念/搭配","context":"适用语境","example":"例子","chinese_feel":"中文理解",'
        '"why":"为什么值得记","difficulty":"A1 入门|A2 基础|B1 日常交流|B2 独立表达|C1 高阶表达|C2 接近母语",'
        '"teacher_note":"一句老师提醒","learning_target":"这张卡练什么",'
        '"why_it_matters":"为什么值得记","how_to_use_it":"复习时如何迁移或判断",'
        '"cloze":"挖空复习句，且只有一个 ____"}]}]}。'
        f"用户水平：{project.get('level', 'B1')}。"
        f"文档片段：{json.dumps(compact, ensure_ascii=False)}"
    )


def call_document_model(project: dict[str, Any], segments: list[dict[str, Any]]) -> dict[str, Any] | None:
    api = project.get("api_config") or {}
    provider = api.get("provider", "local")
    api_key = api.get("api_key", "").strip()
    model = api.get("model", "").strip()
    if provider == "local" or not model or (not api_key and not is_gemini_vertex_config(api)):
        return None

    prompt = build_document_prompt(project, segments)
    try:
        if provider in OPENAI_COMPATIBLE_PROVIDERS:
            token_budget = 2200 if is_mimo_config(api) else 7000 if is_deepseek_thinking_config(api) else 4000 if is_qwen_config(api) else 5000
            response = compatible_chat_completion(
                api,
                [
                    {"role": "system", "content": "Return only valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.25,
                timeout=180 if is_thinking_model_config(api) else 60,
                max_tokens=token_budget,
                progress={
                    "command": "generate",
                    "stage": "ai",
                    "percent": 70,
                    "message": "模型保留 thinking 生成文档卡字段",
                },
            )
            content = chat_completion_content(response)
            return extract_json_object(content)

        if provider == "claude":
            response = http_json(
                anthropic_messages_url(api),
                anthropic_headers(api, api_key),
                {
                    "model": model,
                    "max_tokens": 5000,
                    "temperature": 0.25,
                    "system": "Return only valid JSON.",
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            content = "".join(part.get("text", "") for part in response.get("content", []))
            return extract_json_object(content)

        if provider == "gemini":
            response = http_json(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}",
                {},
                {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0.25,
                        "responseMimeType": "application/json",
                    },
                },
            )
            content = response["candidates"][0]["content"]["parts"][0]["text"]
            return extract_json_object(content)

        if is_gemini_vertex_config(api):
            content = gemini_vertex_generate_content(
                api,
                prompt,
                temperature=0.25,
                timeout=180 if is_gemini_vertex_thinking_config(api) else 120,
                max_output_tokens=14000 if is_gemini_vertex_thinking_config(api) else 7000,
            )
            return extract_json_object(content)
    except Exception as err:
        return {"error": str(err)}
    return None


def fallback_document_card(segment: dict[str, Any], level: str, study_mode: str = "knowledge") -> dict[str, Any]:
    excerpt = segment.get("document_excerpt", "")
    phrase = segment.get("phrase") or "核心知识点"
    answer = clip_words(excerpt, 70)
    is_reading = study_mode == "language_reading"
    return {
        "id": f"{segment['id']}_knowledge",
        "type": "knowledge",
        "type_label": "文档精读卡" if is_reading else "知识卡",
        "enabled": False,
        "document_card_kind": "language_reading" if is_reading else "knowledge",
        "knowledge_type": "terms" if is_reading else "concepts",
        "content_kind": "phrase" if is_reading else "knowledge",
        "source_evidence": excerpt,
        "english": segment.get("text", ""),
        "chinese": answer or ("请根据原文补充语言点理解。" if is_reading else "请根据原文补充核心答案。"),
        "phrase": phrase,
        "definition": answer or "本地草稿：请用模型精修或手动补充定义。",
        "collocations": "替换框架；语境搭配；易混用法" if is_reading else "相关概念；关键原因；典型例子",
        "context": "来自导入文档的精读点，适合确认表达、词义或语法框架。" if is_reading else "来自导入文档的知识点，适合做概念理解和主动回忆。",
        "example": clip_words(excerpt, 42),
        "chinese_feel": "先用自己的话解释，再核对原文中的关键条件和例子。",
        "why": "这段内容被拆成可复习的问题，适合后续在 Anki 里主动回忆。",
        "learning_target": "确认这段文档里是否有明确语言点值得精读。" if is_reading else "确认这段文档里是否有明确概念或观点值得记。",
        "why_it_matters": "本地 fallback 只能保留原文线索，需要模型或人工把它改成具体精读动作。" if is_reading else "本地 fallback 只能保留原文线索，需要模型或人工把它改成具体知识动作。",
        "how_to_use_it": "先确认表达是否来自原文，再补充下次阅读时如何辨认或复用。" if is_reading else "先检查问题是否具体，再把答案压缩成自己的话。",
        "difficulty": CEFR_LABELS.get(level, level),
        "teacher_note": "本地待审精读卡：建议检查语言点是否来自原文且值得复习。" if is_reading else "本地待审卡：建议检查问题是否具体，答案是否过长。",
        "cloze": f"{phrase} 的核心是 ____。",
        "quality": {
            "score": 64,
            "status": "needs_review",
            "issues": ["本地文档精读草稿，需要人工确认"] if is_reading else ["本地文档草稿，需要人工确认"],
        },
    }


def document_card_quality(card: dict[str, Any], fallback: bool = False) -> dict[str, Any]:
    issues: list[str] = []
    phrase = str(card.get("phrase", "")).strip().lower()
    english = str(card.get("english", "")).strip()
    chinese = str(card.get("chinese", "")).strip()
    definition = str(card.get("definition", "")).strip()
    teacher_note = str(card.get("teacher_note", "")).strip()
    why = str(card.get("why_it_matters") or card.get("why") or "").strip()
    knowledge_type = str(card.get("knowledge_type", "")).strip()

    if fallback:
        issues.append("本地文档草稿，需要人工确认")
    if phrase in {"", "核心知识点", "知识点", "key point", "knowledge point", "n/a", "none"}:
        issues.append("概念名是占位词，需人工提炼")
    if knowledge_type not in DOCUMENT_FOCUS_ORDER:
        issues.append("缺少明确知识类型")
    if not english or len(english) < 8 or english in {"这段主要讲什么？", "这段内容的核心是什么？"}:
        issues.append("正面问题太泛")
    if len(chinese) > 260:
        issues.append("答案过长，建议压缩成 1-3 句")
    if not definition or definition == chinese:
        issues.append("缺少独立概念解释")
    if not why:
        issues.append("缺少为什么值得记")
    if not teacher_note or "很重要" == teacher_note:
        issues.append("老师提醒不够具体")

    severe_issues = {
        "概念名是占位词，需人工提炼",
        "正面问题太泛",
        "缺少独立概念解释",
        "缺少为什么值得记",
    }
    score = max(35, 86 - len(issues) * 10 - (10 if fallback else 0))
    if not fallback and len(severe_issues.intersection(issues)) >= 3:
        status = "reject"
    else:
        status = "recommended" if not issues and score >= 78 else "needs_review"
    return {"score": score, "status": status, "issues": issues}


def merge_document_cards(
    segments: list[dict[str, Any]],
    ai_payload: dict[str, Any] | None,
    level: str,
    study_mode: str = "knowledge",
) -> tuple[list[dict[str, Any]], str | None]:
    ai_by_segment: dict[str, dict[str, Any]] = {}
    warning = None
    if ai_payload:
        if "error" in ai_payload:
            warning = f"模型总结失败，已生成待审文档草稿：{ai_payload['error']}"
        for item in ai_payload.get("segments", []):
            ai_by_segment[item.get("id", "")] = item
    else:
        warning = "未配置可用模型，已生成本地待审文档草稿。"

    for segment in segments:
        card = fallback_document_card(segment, level, study_mode=study_mode)
        ai_segment = ai_by_segment.get(segment["id"])
        if ai_segment:
            ai_card = next((item for item in ai_segment.get("cards", []) if item.get("type") == "knowledge"), None)
            if ai_card:
                for key in [
                    "english",
                    "chinese",
                    "phrase",
                    "knowledge_type",
                    "definition",
                    "collocations",
                    "context",
                    "example",
                    "chinese_feel",
                    "why",
                    "learning_target",
                    "why_it_matters",
                    "how_to_use_it",
                    "difficulty",
                    "teacher_note",
                    "cloze",
                    "content_kind",
                    "source_evidence",
                ]:
                    if ai_card.get(key):
                        card[key] = str(ai_card[key])
                if card["cloze"].count("____") != 1:
                    card["cloze"] = f"{card['phrase']} 的核心是 ____。"
                card["type_label"] = "文档精读卡" if study_mode == "language_reading" else "知识卡"
                card["document_card_kind"] = "language_reading" if study_mode == "language_reading" else "knowledge"
                card["quality"] = document_card_quality(card, fallback=False)
                if study_mode == "language_reading":
                    card["quality"]["status"] = "needs_review"
                    card["quality"].setdefault("issues", []).append("文档精读卡默认待审，需确认语言点是否值得保留")
                    card["teacher_note"] = (
                        card.get("teacher_note", "")
                        or "文档精读卡：请确认这个表达、词义或语法框架确实值得复习。"
                    )
                card["enabled"] = card["quality"]["status"] == "recommended"
        else:
            card["quality"] = document_card_quality(card, fallback=True)
            card["enabled"] = False
        segment["phrase"] = card.get("phrase", segment.get("phrase", ""))
        segment["knowledge_type"] = card.get("knowledge_type", "")
        segment["document_card_kind"] = card.get("document_card_kind", "knowledge")
        segment["phrase_review_status"] = card["quality"]["status"]
        segment["phrase_card_focus"] = card.get("learning_target") or card.get("teacher_note", "")
        if card["quality"].get("issues"):
            segment["phrase_reject_reason"] = " / ".join(card["quality"]["issues"])
        else:
            segment["phrase_decision_reason"] = card.get("why_it_matters") or card.get("why", "")
        segment["cards"] = [card]
    return segments, warning


def handle_generate_document(payload: dict[str, Any]) -> dict[str, Any]:
    document_path = clean_input_path(payload.get("document_path"))
    if not document_path:
        fail("请先选择 TXT、Markdown、DOCX、EPUB 或 PDF 文档。")

    emit_progress("generate", "document", 22, "正在读取文档。")
    text = read_document_source(document_path)
    level = payload.get("level", "B1")
    study_mode = normalized_document_study_mode(payload)
    collection_levels = collection_levels_from_payload(payload, level)
    max_segments = resolved_max_segments(payload, text=text)
    split_label = "文档精读点" if study_mode == "language_reading" else "文档知识点"
    emit_progress("generate", "document", 42, f"正在拆分{split_label}。")
    segments = split_document_chunks(text, min(max_segments, 36))
    if study_mode == "language_reading":
        for index, segment in enumerate(segments, 1):
            segment["source_time"] = f"文档精读点 {index}"
            title = segment.get("phrase") or f"精读点 {index}"
            segment["text"] = f"这段资料里值得精读的表达、词义或语法框架是什么：{title}"
    emit_progress("generate", "context", 54, "正在理解整份文档，建立制卡上下文。")
    material_context = call_material_context(payload, segments)
    payload = {**payload, "material_context": material_context, "study_depth": normalized_study_depth(payload)}
    context_warning = material_context.get("warning") if isinstance(material_context, dict) else None
    progress_label = "语言精读卡" if study_mode == "language_reading" else "文档知识卡"
    emit_progress("generate", "ai", 66, f"正在生成{progress_label}：{len(segments)} 个片段。")
    ai_payload = call_document_model(payload, segments)
    emit_progress("generate", "cards", 86, "正在整理文档卡字段。")
    segments, warning = merge_document_cards(segments, ai_payload, level, study_mode=study_mode)
    if context_warning:
        warning = f"{context_warning}；{warning}" if warning else str(context_warning)

    title = payload.get("title") or Path(document_path).stem
    try:
        auto_segments = int(payload.get("max_segments", 0) or 0) <= 0
    except (TypeError, ValueError):
        auto_segments = True
    emit_progress("generate", "done", 100, f"文档制卡完成：{len(segments)} 个{split_label}。")
    quality_funnel = build_quality_funnel(
        segments,
        candidate_segments=len(segments),
        reviewed_keep=len(segments),
    )
    return {
        "id": f"project_{int(time.time())}",
        "title": title,
        "video_path": "",
        "subtitle_path": "",
        "document_path": document_path,
        "language": payload.get("language", "English"),
        "level": level,
        "collection_levels": collection_levels,
        "template_id": payload.get("template_id", "immersive_v11"),
        "content_toggles": payload.get("content_toggles", {}),
        "language_focus": normalized_document_reading_focus(payload) if study_mode == "language_reading" else normalized_language_focus(payload),
        "document_focus": normalized_document_focus(payload),
        "document_study_mode": study_mode,
        "document_answer_language": normalized_document_answer_language(payload),
        "document_depth": normalized_document_depth(payload),
        "document_answer_length": normalized_document_answer_length(payload),
        "study_depth": normalized_study_depth(payload),
        "material_context": material_context,
        "card_types": ["knowledge"],
        "max_segments": max_segments,
        "auto_max_segments": auto_segments,
        "quality_funnel": quality_funnel,
        "segments": segments,
        "warning": warning,
        "source_mode": "document",
        "source_url": "",
        "source_info": {
            "title": title,
            "document_path": document_path,
            "document_study_mode": study_mode,
        },
        "created_at": int(time.time()),
    }


def build_quality_funnel(
    segments: list[dict[str, Any]],
    subtitle_cues: int | None = None,
    candidate_segments: int | None = None,
    reviewed_keep: int | None = None,
    mimo_kept: int | None = None,
) -> dict[str, Any]:
    cards = [card for segment in segments for card in segment.get("cards", [])]
    recommended_cards = sum(1 for card in cards if (card.get("quality") or {}).get("status") == "recommended")
    review_cards = sum(1 for card in cards if (card.get("quality") or {}).get("status") == "needs_review")
    rejected_cards = sum(1 for card in cards if (card.get("quality") or {}).get("status") == "reject")
    rejected_segments = sum(1 for segment in segments if segment.get("phrase_review_status") == "reject")
    duplicate_segments = sum(1 for segment in segments if segment.get("phrase_review_status") == "duplicate")
    scores = [
        phrase_review_score(segment.get("phrase_value_score"))
        for segment in segments
        if phrase_review_score(segment.get("phrase_value_score")) > 0
    ]
    average_score = round(sum(scores) / len(scores), 2) if scores else None
    if recommended_cards < 5:
        if len(segments) < 6:
            short_reason = "字幕片段太少或有效候选不足。"
        elif recommended_cards == 0:
            if review_cards > 0:
                short_reason = f"没有推荐卡，但有 {review_cards} 张待审卡；请人工确认或配置模型精修。"
            else:
                short_reason = "没有推荐卡，可能是词伙评分不足、模型返回空或筛选太严格。"
        else:
            short_reason = "推荐卡偏少，通常是重复合并、低价值表达或模型评审较严格。"
    else:
        short_reason = ""
    return {
        "subtitle_cues": subtitle_cues,
        "candidate_segments": candidate_segments if candidate_segments is not None else len(segments),
        "reviewed_keep": reviewed_keep
        if reviewed_keep is not None
        else sum(1 for segment in segments if segment.get("phrase_review_status") not in {"reject", "duplicate"}),
        "mimo_kept": mimo_kept,
        "recommended_cards": recommended_cards,
        "review_cards": review_cards,
        "rejected_cards": rejected_cards,
        "rejected_segments": rejected_segments,
        "duplicate_segments": duplicate_segments,
        "average_phrase_score": average_score,
        "short_reason": short_reason,
    }


def handle_generate(payload: dict[str, Any]) -> dict[str, Any]:
    emit_progress("generate", "source", 5, "准备素材。")
    source_mode = str(payload.get("source_mode") or "").strip().lower()
    if not source_mode:
        source_mode = "url" if str(payload.get("source_url") or "").strip() else "local"
    if source_mode == "document":
        return handle_generate_document(payload)

    source_info = None
    if source_mode == "url":
        emit_progress("generate", "download", 12, "正在准备 URL 视频和字幕。")
        source_info = download_url_source(payload)
        source_message = "已复用 URL 缓存素材。" if source_info.get("cached") else "URL 素材下载完成。"
        if source_info.get("transcript_only"):
            source_message = (
                "已复用 URL 字幕缓存，跳过视频切片。"
                if source_info.get("cached")
                else "URL 字幕已就绪，跳过视频切片。"
            )
        emit_progress(
            "generate",
            "download",
            28,
            source_message,
        )
        payload = {
            **payload,
            "video_path": source_info.get("video_path", ""),
            "subtitle_path": source_info["subtitle_path"],
            "title": payload.get("title") or source_info.get("title") or "",
            "skip_video_slicing": bool(source_info.get("skip_video_slicing")) or bool(payload.get("skip_video_slicing")),
        }

    video_path = clean_input_path(payload.get("video_path", ""))
    subtitle_path = clean_input_path(payload.get("subtitle_path", ""))
    subtitle_source = "manual" if subtitle_path and Path(subtitle_path).exists() else ""
    skip_video_slicing = bool(payload.get("skip_video_slicing") or (source_info or {}).get("transcript_only"))
    if not skip_video_slicing and (not video_path or not Path(video_path).exists()):
        fail(f"视频文件不存在：{video_path}")
    if video_path and (not subtitle_path or not Path(subtitle_path).exists()):
        discovered_subtitle = discover_local_subtitle(video_path, payload.get("language", "English"))
        if discovered_subtitle:
            subtitle_path = str(discovered_subtitle)
            subtitle_source = "auto_matched"
    if video_path and (not subtitle_path or not Path(subtitle_path).exists()):
        emit_progress("generate", "subtitle", 30, "正在从视频内嵌字幕提取 SRT。")
        embedded_subtitle = extract_embedded_subtitle(video_path, payload.get("language", "English"))
        if embedded_subtitle:
            subtitle_path = str(embedded_subtitle)
            subtitle_source = "embedded"
    if not subtitle_path or not Path(subtitle_path).exists():
        fail(
            f"字幕文件不存在：{subtitle_path or '未选择'}。已尝试同目录 SRT/VTT 和视频内嵌文字字幕；请手动选择 SRT，或确认视频包含可提取的 SubRip/ASS/WebVTT 字幕。",
            error_code="LOCAL_SUBTITLE_MISSING",
            stage="subtitle",
            retryable=True,
        )
    emit_progress("generate", "subtitle", 34, "正在解析 SRT 字幕。")
    cues = parse_srt(subtitle_path)
    card_types = payload.get("card_types") or ["listening", "phrase", "cloze"]
    level = payload.get("level", "B1")
    collection_levels = collection_levels_from_payload(payload, level)
    max_segments = resolved_max_segments({**payload, "source_info": source_info or payload.get("source_info") or {}}, cues)
    auto_segments = True
    try:
        auto_segments = int(payload.get("max_segments", 0)) <= 0
    except (TypeError, ValueError):
        auto_segments = True
    payload = {**payload, "max_segments": max_segments, "auto_max_segments": auto_segments}

    review_enabled = phrase_review_available(payload)
    segment_payload = (
        {
            **payload,
            "_candidate_limit": max(max_segments * 2, max_segments + 12),
        }
        if review_enabled
        else payload
    )
    emit_progress(
        "generate",
        "segments",
        48,
        f"正在按时间轴筛选候选片段：字幕 {len(cues)} 条，片段预算 {max_segments}，"
        f"{'准备 AI 学习候选评审。' if review_enabled else '使用本地评分。'}",
    )
    segments = build_segments(cues, segment_payload)
    candidate_segment_count = len(segments)
    if not segments:
        fail("没有筛选出合适片段。请检查 SRT，或放宽内容开关。")

    emit_progress("generate", "context", 54, "正在理解整段素材，建立制卡上下文。")
    material_context = call_material_context(payload, segments)
    payload = {**payload, "material_context": material_context, "study_depth": normalized_study_depth(payload)}
    context_warning = material_context.get("warning") if isinstance(material_context, dict) else None

    skipped_segments: list[dict[str, Any]] = []
    review_warning = None
    if review_enabled:
        emit_progress("generate", "phrase_review", 58, f"AI 正在评审学习候选：{len(segments)} 个片段。")
        reviewed_segments, skipped_segments, review_warning = review_phrase_candidates_with_mimo(payload, segments)
        review_applied = any(
            str(item.get("phrase_review_source") or "") in {"mimo", "ai"}
            for item in [*reviewed_segments, *skipped_segments]
        )
        if review_applied:
            segments = reviewed_segments
        else:
            segments = sorted(segments, key=lambda item: item["score"], reverse=True)[:max_segments]
            segments = sorted(segments, key=lambda item: item["start"])
    else:
        segments = sorted(segments, key=lambda item: item["score"], reverse=True)[:max_segments]
        segments = sorted(segments, key=lambda item: item["start"])

    emit_progress("generate", "ai", 66, f"正在分批生成词伙、解释和卡片字段：{len(segments)} 个片段。")
    ai_payload = call_model_batches(payload, segments) if segments else None
    emit_progress("generate", "cards", 84, "正在整理卡片草稿。")
    segments, warning = merge_ai_cards(segments, ai_payload, card_types, level) if segments else ([], None)
    reviewed_keep_count = len(segments)
    if context_warning:
        warning = f"{context_warning}；{warning}" if warning else str(context_warning)
    if review_warning:
        warning = f"{review_warning}；{warning}" if warning else review_warning
    if skipped_segments:
        segments = sorted([*segments, *skipped_segments], key=lambda item: item["start"])

    project_id = f"project_{int(time.time())}"
    title = payload.get("title") or (Path(video_path).stem if video_path else (source_info or {}).get("title") or "字幕素材")
    source_warning = (source_info or {}).get("warning")
    source_notice = source_warning or ""
    if not source_info and subtitle_source in {"auto_matched", "embedded"}:
        subtitle_source_label = "自动匹配同目录字幕" if subtitle_source == "auto_matched" else "从视频内嵌字幕提取"
        source_notice = f"{subtitle_source_label}：{Path(subtitle_path).name}"
    quality_funnel = build_quality_funnel(
        segments,
        subtitle_cues=len(cues),
        candidate_segments=candidate_segment_count,
        reviewed_keep=reviewed_keep_count,
        mimo_kept=reviewed_keep_count if review_enabled else None,
    )
    if ai_payload is None and (quality_funnel.get("recommended_cards", 0) > 0 or quality_funnel.get("review_cards", 0) > 0):
        recommended_count = int(quality_funnel.get("recommended_cards", 0) or 0)
        review_count = int(quality_funnel.get("review_cards", 0) or 0)
        if recommended_count:
            local_review_warning = (
                f"已解析 {len(cues)} 条字幕，生成 {recommended_count} 张本地推荐卡"
                f"和 {review_count} 张待审卡。推荐卡已可直接审核导出；配置模型精修后可继续提升中文释义和例句质量。"
            )
        else:
            local_review_warning = (
                f"已解析 {len(cues)} 条字幕，生成 {review_count} 张待审本地草稿卡（默认停用）。"
                "配置模型精修后可得到推荐卡，或在审核页手动确认后导出。"
            )
        warning = (
            f"{warning}；{local_review_warning}"
            if warning and "模型没有返回可用精修结果" not in warning
            else local_review_warning
        )
    if source_notice and source_notice not in (warning or ""):
        warning = f"{source_notice}；{warning}" if warning else source_notice
    emit_progress("generate", "done", 100, f"生成完成：{len(segments)} 个片段组。")
    return {
        "id": project_id,
        "title": title,
        "video_path": video_path,
        "subtitle_path": subtitle_path,
        "language": payload.get("language", "English"),
        "level": level,
        "collection_levels": collection_levels,
        "template_id": payload.get("template_id", "immersive_v11"),
        "content_toggles": payload.get("content_toggles", {}),
        "language_focus": normalized_language_focus(payload),
        "study_depth": normalized_study_depth(payload),
        "material_context": material_context,
        "card_types": card_types,
        "max_segments": max_segments,
        "auto_max_segments": auto_segments,
        "skip_video_slicing": skip_video_slicing,
        "quality_funnel": quality_funnel,
        "segments": segments,
        "warning": warning,
        "source_mode": source_mode,
        "source_url": payload.get("source_url", "") if source_mode == "url" else "",
        "source_info": source_info
        or {
            "title": title,
            "video_path": video_path,
            "subtitle_path": subtitle_path,
            "subtitle_source": subtitle_source or "manual",
        },
        "created_at": int(time.time()),
    }


def stable_id(value: str, offset: int = 0) -> int:
    return int(zlib.crc32(value.encode("utf-8")) + offset)


def run_ffmpeg(args: list[str]) -> None:
    if not shutil.which("ffmpeg"):
        fail(
            "找不到 ffmpeg。请先安装 ffmpeg 并加入 PATH。",
            error_code="ENV_FFMPEG_MISSING",
            stage="media",
            retryable=True,
            fallbacks=["skip_video_slicing"],
        )
    completed = subprocess.run(
        ["ffmpeg", "-y", *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        fail(
            f"ffmpeg 处理失败：{completed.stderr[-1200:]}",
            error_code="FFMPEG_SLICE_FAILED",
            stage="media",
            retryable=True,
            fallbacks=["skip_video_slicing"],
        )


def try_run_ffmpeg(args: list[str]) -> str:
    if not shutil.which("ffmpeg"):
        return "找不到 ffmpeg。请先安装 ffmpeg 并加入 PATH。"
    completed = subprocess.run(
        ["ffmpeg", "-y", *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        return completed.stderr[-900:] or f"ffmpeg 退出码 {completed.returncode}"
    return ""


CARD_CSS = """
.card {
  margin: 0;
  padding: 16px;
  color: #17211d;
  background: #f5f3ee;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans SC", sans-serif;
  line-height: 1.55;
}
.wrap {
  width: min(760px, 100%);
  margin: 0 auto;
}
.front-shell,
.back-shell {
  overflow: hidden;
  border: 1px solid #e3e1da;
  border-radius: 14px;
  background: #fffdfa;
  box-shadow: 0 10px 32px rgba(32, 38, 35, 0.10);
}
.media-frame {
  padding: 10px;
  background: #101613;
}
.media-frame video,
.mini-media video {
  display: block;
  width: 100%;
  aspect-ratio: 16 / 9;
  max-height: 320px;
  border-radius: 10px;
  background: #0b100e;
  object-fit: cover;
}
.mini-media video {
  max-height: 190px;
}
audio {
  display: block;
  width: 100%;
  height: 34px;
}
.front-panel,
.answer-panel {
  padding: 16px 18px 18px;
}
.meta-row,
.answer-meta,
.source {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  color: #66736d;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0;
  font-variant-numeric: tabular-nums;
}
.card-type {
  color: #0d3d30;
  font-size: 19px;
  font-weight: 800;
}
.task-box {
  margin-top: 12px;
  padding: 12px 14px;
  border: 1px solid #e3e7e1;
  border-radius: 10px;
  background: #fafbf8;
}
.task-box p {
  margin: 0;
  color: #50615a;
  font-size: 15px;
}
.label {
  display: block;
  margin-bottom: 5px;
  color: #617069;
  font-size: 11px;
  font-weight: 750;
  letter-spacing: 0;
}
.front-content {
  margin-top: 10px;
  color: #17211d;
  font-size: 20px;
  font-weight: 760;
  line-height: 1.45;
}
.audio-stack {
  display: grid;
  gap: 8px;
  margin-top: 12px;
}
.audio-row {
  display: grid;
  grid-template-columns: 72px 1fr;
  align-items: center;
  gap: 10px;
}
.audio-label {
  color: #66736d;
  font-size: 12px;
  font-weight: 750;
}
.back-hero {
  display: grid;
  grid-template-columns: 1fr 220px;
  gap: 16px;
  padding: 16px 18px;
  border-bottom: 1px solid #ece9e1;
}
.english {
  margin: 8px 0 0;
  color: #101915;
  font-size: 23px;
  font-weight: 820;
  line-height: 1.35;
}
.translation {
  margin-top: 8px;
  color: #2f3b36;
  font-size: 17px;
  font-weight: 650;
}
.answer-pill,
.phrase {
  display: inline-block;
  max-width: 100%;
  padding: 5px 10px;
  border-radius: 999px;
  background: #e5f2eb;
  color: #0b4c39;
  font-weight: 800;
}
.answer-pill {
  margin-top: 12px;
}
.teacher-note {
  margin-top: 12px;
  padding: 10px 12px;
  border: 1px solid #dce8e2;
  border-radius: 10px;
  background: #f5faf7;
  color: #31443c;
  font-size: 14px;
}
.focus-strip {
  display: grid;
  grid-template-columns: minmax(160px, 0.85fr) 1fr;
  gap: 12px;
  padding: 14px 18px;
  border-bottom: 1px solid #ece9e1;
}
.focus-main,
.focus-copy {
  min-width: 0;
}
.focus-copy {
  color: #3d4a45;
  font-size: 15px;
}
.focus-copy p {
  margin: 0 0 8px;
}
.detail-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px 14px;
  padding: 14px 18px 18px;
}
.detail {
  min-width: 0;
  padding-top: 10px;
  border-top: 1px solid #ecefe9;
}
.detail .value {
  color: #27342f;
  font-size: 14px;
}
.source {
  padding: 10px 18px 14px;
  border-top: 1px solid #ece9e1;
}
.compact-video-label {
  margin-bottom: 7px;
  color: #6b746f;
  font-size: 11px;
  font-weight: 750;
}
hr {
  display: none;
}
@media (max-width: 640px) {
  .card { padding: 10px; }
  .front-panel,
  .answer-panel,
  .back-hero,
  .focus-strip,
  .detail-grid,
  .source { padding-left: 14px; padding-right: 14px; }
  .back-hero,
  .focus-strip,
  .detail-grid { grid-template-columns: 1fr; }
  .audio-row { grid-template-columns: 1fr; gap: 4px; }
  .english { font-size: 20px; }
  .front-content { font-size: 18px; }
}
"""

FRONT_TEMPLATE = """
<div class="wrap">
  <section class="front-shell">
    <div class="media-frame">{{Video}}</div>
    <div class="front-panel">
      <div class="meta-row">
        <span class="card-type">{{CardType}}</span>
        <span>{{SourceTime}}</span>
      </div>
      <div class="task-box">
        <span class="label">正面任务</span>
        <p>{{FrontPrompt}}</p>
        {{#FrontContent}}<div class="front-content">{{FrontContent}}</div>{{/FrontContent}}
      </div>
      <div class="audio-stack">
        <div class="audio-row"><span class="audio-label">原声音频</span>{{Audio}}</div>
        {{#TtsAudio}}<div class="audio-row"><span class="audio-label">整句 AI 朗读</span>{{TtsAudio}}</div>{{/TtsAudio}}
      </div>
    </div>
  </section>
</div>
<script>
  setTimeout(function () {
    document.querySelectorAll("video,audio").forEach(function (node) {
      node.playbackRate = 0.75;
    });
  }, 60);
</script>
"""

BACK_TEMPLATE = """
<div class="wrap">
  <section class="back-shell">
    <div class="back-hero">
      <div class="answer-panel">
        <div class="answer-meta">
          <span class="card-type">{{CardType}}</span>
          <span>{{Difficulty}}</span>
        </div>
        <div class="english">{{English}}</div>
        <div class="translation">{{Chinese}}</div>
        <div class="answer-pill">{{Answer}}</div>
        <div class="teacher-note">{{TeacherNote}}</div>
      </div>
      <div class="mini-media">
        <div class="compact-video-label">复听视频</div>
        {{Video}}
      </div>
    </div>
    <div class="focus-strip">
      <div class="focus-main">
        <span class="label">重点词伙</span>
        <span class="phrase">{{Phrase}}</span>
      </div>
      <div class="focus-copy">
        <p><strong>释义：</strong>{{Definition}}</p>
        <p><strong>中文感：</strong>{{ChineseFeel}}</p>
      </div>
    </div>
    <div class="detail-grid">
      <div class="detail"><span class="label">搭配</span><div class="value">{{Collocations}}</div></div>
      <div class="detail"><span class="label">语境</span><div class="value">{{Context}}</div></div>
      <div class="detail"><span class="label">例句</span><div class="value">{{Example}}</div></div>
      <div class="detail"><span class="label">填空回忆</span><div class="value">{{Cloze}}</div></div>
      <div class="detail"><span class="label">为什么值得学</span><div class="value">{{Why}}</div></div>
      <div class="detail"><span class="label">来源时间轴</span><div class="value">{{SourceTime}}</div></div>
    </div>
  </section>
</div>
<script>
  setTimeout(function () {
    document.querySelectorAll("video,audio").forEach(function (node) {
      node.playbackRate = 0.75;
    });
  }, 60);
</script>
"""


DICTIONARY_FRONT_TEMPLATE = """
<div class="wrap dictionary-template">
  <section class="front-shell">
    <div class="media-frame compact-media">{{Video}}</div>
    <div class="compact-head">
      <strong>{{CardType}}</strong>
      <span>{{SourceTime}}</span>
    </div>
    <div class="task-box">
      <div class="label">正面任务</div>
      <p>{{FrontPrompt}}</p>
      {{#FrontContent}}<div class="front-content">{{FrontContent}}</div>{{/FrontContent}}
    </div>
    <div class="prompt compact-prompt">
      <div class="audio-stack">
        <div class="audio-row"><span class="audio-label">原声音频</span>{{Audio}}</div>
        {{#TtsAudio}}<div class="audio-row"><span class="audio-label">整句 AI 朗读</span>{{TtsAudio}}</div>{{/TtsAudio}}
      </div>
    </div>
  </section>
</div>
<script>
  setTimeout(function () {
    document.querySelectorAll("video,audio").forEach(function (node) {
      node.playbackRate = 0.75;
    });
  }, 60);
</script>
"""


DICTIONARY_BACK_TEMPLATE = """
<div class="wrap dictionary-template">
  <section class="back-shell dictionary-back">
    <div class="back-hero">
      <div class="answer-panel">
        <div class="answer-meta">
          <span class="card-type">{{CardType}}</span>
          <span>{{Difficulty}}</span>
        </div>
        <div class="english">{{English}}</div>
        <div class="translation">{{Chinese}}</div>
        <div class="teacher-note">{{TeacherNote}}</div>
      </div>
      <div class="mini-media">
        <div class="compact-video-label">复听视频</div>
        {{Video}}
      </div>
    </div>
    <div class="dictionary-grid">
      <div><span class="label">重点词伙</span><strong class="phrase">{{Phrase}}</strong></div>
      <div><span class="label">正面答案</span><p>{{Answer}}</p></div>
      <div><span class="label">释义</span><p>{{Definition}}</p></div>
      <div><span class="label">搭配</span><p>{{Collocations}}</p></div>
      <div><span class="label">语境</span><p>{{Context}}</p></div>
      <div><span class="label">例句</span><p>{{Example}}</p></div>
      <div><span class="label">中文感</span><p>{{ChineseFeel}}</p></div>
      <div><span class="label">填空回忆</span><p>{{Cloze}}</p></div>
      <div><span class="label">为什么值得学</span><p>{{Why}}</p></div>
      <div><span class="label">来源时间轴</span><p>{{SourceTime}}</p></div>
    </div>
  </section>
</div>
<script>
  setTimeout(function () {
    document.querySelectorAll("video,audio").forEach(function (node) {
      node.playbackRate = 0.75;
    });
  }, 60);
</script>
"""


MINIMAL_FRONT_TEMPLATE = """
<div class="wrap minimal-template">
  <section class="front-shell">
    <div class="media-frame minimal-media">{{Video}}</div>
    <div class="prompt minimal-prompt">
      <strong>{{CardType}}</strong>
      <span>{{FrontPrompt}}</span>
      {{#FrontContent}}<div class="front-content">{{FrontContent}}</div>{{/FrontContent}}
      {{Audio}}
    </div>
  </section>
</div>
<script>
  setTimeout(function () {
    document.querySelectorAll("video,audio").forEach(function (node) {
      node.playbackRate = 0.75;
    });
  }, 60);
</script>
"""


MINIMAL_BACK_TEMPLATE = """
<div class="wrap minimal-template">
  <section class="back-shell minimal-back">
    <div class="mini-media minimal-answer-media">{{Video}}</div>
    <div class="section">
      <div class="answer-meta"><span class="card-type">{{CardType}}</span><span>{{SourceTime}}</span></div>
      <div class="english">{{English}}</div>
      <div class="translation">{{Chinese}}</div>
      <div class="minimal-row"><strong>{{Phrase}}</strong><span>{{Difficulty}}</span></div>
      <div class="answer-pill">{{Answer}}</div>
      <p>{{ChineseFeel}}</p>
      <p>{{TeacherNote}}</p>
      <small>{{Cloze}}</small>
    </div>
  </section>
</div>
<script>
  setTimeout(function () {
    document.querySelectorAll("video,audio").forEach(function (node) {
      node.playbackRate = 0.75;
    });
  }, 60);
</script>
"""


CARD_CSS = """
.card {
  margin: 0;
  padding: 18px;
  display: block;
  background:
    radial-gradient(circle at 18% 0%, rgba(255,255,255,0.94), rgba(255,255,255,0) 32%),
    linear-gradient(145deg, #f6f1e8 0%, #eef2ee 52%, #f8f5ef 100%);
  color: #111817;
  font-family: Inter, "SF Pro Display", "Segoe UI", "Helvetica Neue", Arial, sans-serif;
  line-height: 1.55;
  letter-spacing: 0;
  text-align: left;
  overflow-x: hidden;
}
* {
  box-sizing: border-box;
}
html,
body,
#qa {
  width: 100% !important;
  max-width: none !important;
  margin: 0 !important;
}
.wrap {
  width: min(1080px, calc(100vw - 32px));
  margin: 0 auto;
  font-family: Inter, "SF Pro Display", "Segoe UI", "Helvetica Neue", Arial, sans-serif;
  --ink: #101817;
  --muted: #60706a;
  --soft: #eef5f1;
  --surface: #fffdf8;
  --line: rgba(25, 42, 37, 0.12);
  --accent: #0d6b52;
  --accent-deep: #074734;
  --accent-soft: #e8f5ef;
  --gold: #b7832d;
  --blue: #355f78;
}
.dictionary-template {
  --accent: #7b4f16;
  --accent-deep: #4e310d;
  --accent-soft: #f5ebda;
  --gold: #236478;
  --blue: #236478;
}
.minimal-template {
  --accent: #263b35;
  --accent-deep: #121d1a;
  --accent-soft: #edf1ef;
  --gold: #63716b;
  --blue: #4d6674;
}
.study-card {
  overflow: hidden;
  border: 1px solid rgba(16, 24, 23, 0.12);
  border-radius: 22px;
  background: var(--surface);
  box-shadow: 0 30px 90px rgba(24, 31, 28, 0.16);
}
.cinema {
  position: relative;
  padding: 12px;
  background:
    radial-gradient(circle at 20% 0%, rgba(255,255,255,0.16), rgba(255,255,255,0) 30%),
    linear-gradient(135deg, #0a1210 0%, #16241e 52%, #070908 100%);
}
.cinema video {
  display: block;
  width: 100%;
  max-height: 520px;
  aspect-ratio: 16 / 9;
  object-fit: cover;
  border-radius: 12px;
  background: #050706;
  box-shadow: inset 0 0 0 1px rgba(255,255,255,0.08);
}
.media-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 10px;
  color: rgba(255,255,255,0.84);
  font-size: 12px;
  font-weight: 760;
}
.type-pill,
.time-pill,
.micro-pill {
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  padding: 5px 10px;
  border-radius: 999px;
  border: 1px solid rgba(255,255,255,0.18);
  background: rgba(255,255,255,0.1);
  backdrop-filter: blur(10px);
}
.time-pill {
  color: rgba(255,255,255,0.72);
}
.front-body {
  display: grid;
  gap: 16px;
  padding: 20px 24px 22px;
}
.mission {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 18px;
  align-items: end;
}
.mission-kicker {
  margin: 0 0 6px;
  color: var(--accent);
  font-size: 13px;
  font-weight: 820;
}
.mission-title {
  margin: 0;
  color: var(--ink);
  font-size: 26px;
  line-height: 1.24;
  font-weight: 860;
}
.mission-note {
  max-width: 300px;
  color: var(--muted);
  font-size: 14px;
  text-align: right;
}
.front-content {
  margin: 0;
  padding: 12px 14px;
  border-left: 4px solid var(--gold);
  border-radius: 8px;
  background: #fbf6eb;
  color: #514739;
  font-size: 16px;
  font-weight: 660;
}
.sound-panel {
  display: grid;
  gap: 11px;
  padding: 15px 18px 17px;
  border-top: 1px solid var(--line);
  background: linear-gradient(180deg, #fbfdfb 0%, #f3f7f4 100%);
}
.sound-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  color: var(--muted);
  font-size: 12px;
  font-weight: 800;
}
.sound-title strong {
  color: var(--ink);
  font-size: 14px;
}
.audio-stack {
  display: grid;
  gap: 10px;
}
.audio-row {
  display: grid;
  grid-template-columns: 96px minmax(0, 1fr);
  gap: 12px;
  align-items: center;
}
.audio-row span {
  color: var(--muted);
  font-size: 12px;
  font-weight: 780;
}
audio {
  width: 100%;
  min-height: 38px;
  color-scheme: light;
}
audio[data-role="phrase-tts"],
.phrase-audio audio {
  width: 1px;
  min-height: 1px;
}
.back-card {
  background: #fffdf8;
}
@media (min-width: 860px) {
  .back-card {
    display: grid;
    grid-template-columns: minmax(290px, 0.72fr) minmax(0, 1fr);
    align-items: stretch;
  }
  .back-card .replay-panel {
    grid-column: 1;
    grid-row: 1 / span 3;
    align-self: stretch;
    border-top: 0;
    border-right: 1px solid var(--line);
  }
  .back-card .answer-hero,
  .back-card .sentence-panel,
  .back-card .detail-grid {
    grid-column: 2;
  }
}
.answer-hero {
  padding: 25px 27px 23px;
  background:
    radial-gradient(circle at 100% 0%, rgba(183, 131, 45, 0.16), rgba(183, 131, 45, 0) 34%),
    linear-gradient(135deg, #fffdf8 0%, var(--accent-soft) 100%);
  border-bottom: 1px solid var(--line);
}
.hero-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 12px;
  color: var(--muted);
  font-size: 12px;
  font-weight: 820;
}
.hero-phrase {
  margin: 0;
  color: var(--accent-deep);
  font-size: 34px;
  line-height: 1.15;
  font-weight: 900;
}
.hero-meaning {
  margin-top: 10px;
  color: #26322f;
  font-size: 21px;
  font-weight: 780;
}
.translation {
  margin-top: 8px;
  color: #5f4b25;
  font-size: 17px;
  font-weight: 680;
}
.teacher-note {
  margin-top: 16px;
  padding: 13px 15px;
  border: 1px solid rgba(13, 107, 82, 0.17);
  border-radius: 10px;
  background: rgba(255,255,255,0.74);
  color: #24332e;
  font-size: 15px;
}
.answer-key {
  display: grid;
  gap: 5px;
  margin-top: 15px;
  padding: 13px 15px;
  border-radius: 12px;
  background: rgba(7, 71, 52, 0.08);
  border: 1px solid rgba(7, 71, 52, 0.14);
}
.answer-key span {
  color: var(--muted);
  font-size: 12px;
  font-weight: 820;
}
.answer-key strong {
  color: var(--accent-deep);
  font-size: 19px;
  line-height: 1.35;
}
.sentence-panel {
  padding: 21px 27px 8px;
}
.section-label {
  display: block;
  margin-bottom: 7px;
  color: var(--muted);
  font-size: 12px;
  font-weight: 820;
}
.english {
  color: #101817;
  font-size: 25px;
  line-height: 1.35;
  font-weight: 850;
}
.detail-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  padding: 17px 27px 24px;
}
.detail {
  min-height: 98px;
  padding: 13px 14px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: #fffaf1;
}
.detail.wide {
  grid-column: 1 / -1;
  background: #f8fbf9;
}
.detail strong {
  display: block;
  margin-bottom: 6px;
  color: var(--accent-deep);
  font-size: 13px;
}
.detail p {
  margin: 0;
  color: #25322e;
  font-size: 15px;
}
.replay-panel {
  display: grid;
  grid-template-columns: minmax(210px, 300px) minmax(0, 1fr);
  gap: 16px;
  align-items: center;
  padding: 17px 18px 18px;
  border-top: 1px solid var(--line);
  background: #f4f6f2;
}
.replay-media {
  padding: 7px;
  border-radius: 12px;
  background: #101614;
}
.replay-media video {
  display: block;
  width: 100%;
  max-height: 220px;
  aspect-ratio: 16 / 9;
  object-fit: cover;
  border-radius: 8px;
  background: #050706;
}
@media (min-width: 860px) {
  .replay-panel {
    grid-template-columns: 1fr;
    align-content: start;
    gap: 18px;
    padding: 18px;
    background:
      linear-gradient(180deg, #0b1512 0%, #15211d 52%, #f4f6f2 52%, #f4f6f2 100%);
  }
  .replay-media {
    background: #050706;
    box-shadow: 0 18px 45px rgba(4, 8, 7, 0.24);
  }
  .replay-media video {
    max-height: none;
  }
}
.meta-line {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 13px;
}
.meta-chip {
  padding: 6px 9px;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: #fffdf8;
  color: var(--muted);
  font-size: 12px;
  font-weight: 760;
}
.minimal-template .study-card {
  box-shadow: 0 14px 42px rgba(29, 37, 34, 0.09);
}
.minimal-template .cinema video {
  max-height: 300px;
}
.minimal-template .answer-hero {
  padding: 22px 24px 19px;
  background: #fffdf8;
}
.minimal-template .detail-grid {
  grid-template-columns: 1fr;
}
.dictionary-template .detail {
  background: #fff7e8;
}
.dictionary-template .detail.wide {
  background: #f5fbfb;
}
@media (max-width: 650px) {
  .card {
    padding: 10px;
  }
  .study-card {
    border-radius: 14px;
  }
  .mission {
    grid-template-columns: 1fr;
  }
  .mission-note {
    max-width: none;
    text-align: left;
  }
  .mission-title {
    font-size: 22px;
  }
  .hero-phrase {
    font-size: 28px;
  }
  .english {
    font-size: 21px;
  }
  .detail-grid,
  .replay-panel {
    grid-template-columns: 1fr;
  }
  .audio-row {
    grid-template-columns: 1fr;
    gap: 5px;
  }
}
"""


FRONT_TEMPLATE = """
<div class="wrap immersive-template">
  <section class="study-card front-card">
    <div class="cinema">
      <div class="media-topbar">
        <span class="type-pill">{{CardType}}</span>
        <span class="time-pill">{{SourceTime}}</span>
      </div>
      {{Video}}
    </div>
    <div class="front-body">
      <div class="mission">
        <div>
          <p class="mission-kicker">先听，不看字幕</p>
          <h1 class="mission-title">{{FrontPrompt}}</h1>
        </div>
        <div class="mission-note">0.75 倍慢放、循环播放，翻面后再看原句和解释。</div>
      </div>
      {{#FrontContent}}<p class="front-content">{{FrontContent}}</p>{{/FrontContent}}
    </div>
    <div class="sound-panel">
      <div class="sound-title"><strong>声音轨道</strong><span>{{#TtsAudio}}原声 / 整句 AI 朗读{{/TtsAudio}}{{^TtsAudio}}循环慢放{{/TtsAudio}}</span></div>
      <div class="audio-stack">
        <div class="audio-row"><span>原声音频</span>{{Audio}}</div>
        {{#TtsAudio}}<div class="audio-row"><span>整句 AI 朗读</span>{{TtsAudio}}</div>{{/TtsAudio}}
      </div>
    </div>
  </section>
</div>
<script>
  setTimeout(function () {
    document.querySelectorAll("video,audio").forEach(function (node) {
      node.playbackRate = 0.75;
      node.loop = true;
    });
  }, 60);
</script>
"""


BACK_TEMPLATE = """
<div class="wrap immersive-template">
  <section class="study-card back-card">
    <div class="answer-hero">
      <div class="hero-meta">
        <span>{{CardType}}</span>
        <span>{{Difficulty}} · {{SourceTime}}</span>
      </div>
      <h1 class="hero-phrase">{{Phrase}}</h1>
      <div class="hero-meaning">{{ChineseFeel}}</div>
      <div class="translation">{{Chinese}}</div>
      {{#Answer}}<div class="answer-key"><span>这张卡真正要回忆的答案</span><strong>{{Answer}}</strong></div>{{/Answer}}
      <div class="teacher-note">{{TeacherNote}}</div>
    </div>

    <div class="sentence-panel">
      <span class="section-label">英文原句</span>
      <div class="english">{{English}}</div>
      {{#Cloze}}<div class="meta-line"><span class="meta-chip">填空：{{Cloze}}</span></div>{{/Cloze}}
    </div>

    <div class="detail-grid">
      <div class="detail"><strong>释义</strong><p>{{Definition}}</p></div>
      <div class="detail"><strong>搭配</strong><p>{{Collocations}}</p></div>
      <div class="detail"><strong>语境</strong><p>{{Context}}</p></div>
      <div class="detail"><strong>例句</strong><p>{{Example}}</p></div>
      <div class="detail wide"><strong>为什么值得学</strong><p>{{Why}}</p></div>
    </div>

    <div class="replay-panel">
      <div class="replay-media">{{Video}}</div>
      <div class="audio-stack">
        <div class="sound-title"><strong>回放</strong><span>{{Phrase}}</span></div>
        <div class="audio-row"><span>原声音频</span>{{Audio}}</div>
        {{#TtsAudio}}<div class="audio-row"><span>整句 AI 朗读</span>{{TtsAudio}}</div>{{/TtsAudio}}
      </div>
    </div>
  </section>
</div>
<script>
  setTimeout(function () {
    document.querySelectorAll("video,audio").forEach(function (node) {
      node.playbackRate = 0.75;
      node.loop = true;
    });
  }, 60);
</script>
"""


DICTIONARY_FRONT_TEMPLATE = FRONT_TEMPLATE.replace("immersive-template", "dictionary-template")
DICTIONARY_BACK_TEMPLATE = BACK_TEMPLATE.replace("immersive-template", "dictionary-template")
MINIMAL_FRONT_TEMPLATE = FRONT_TEMPLATE.replace("immersive-template", "minimal-template")
MINIMAL_BACK_TEMPLATE = BACK_TEMPLATE.replace("immersive-template", "minimal-template")


CARD_CSS = """
.card {
  margin: 0;
  padding: 18px;
  background:
    radial-gradient(circle at 20% 0%, rgba(255, 255, 255, 0.95), rgba(255, 255, 255, 0) 30%),
    linear-gradient(145deg, #f5f0e7 0%, #eef3ee 54%, #fbf8f1 100%);
  color: #101817;
  font-family: Inter, "SF Pro Display", "Segoe UI", "Noto Sans SC", Arial, sans-serif;
  line-height: 1.55;
  text-align: left;
  letter-spacing: 0;
}
* { box-sizing: border-box; }
html, body, #qa {
  width: 100% !important;
  max-width: none !important;
  margin: 0 !important;
}
.wrap {
  width: min(980px, calc(100vw - 32px));
  margin: 0 auto;
  --ink: #101817;
  --muted: #63706a;
  --line: rgba(25, 42, 37, 0.12);
  --surface: #fffdf8;
  --surface-2: #f7faf6;
  --accent: #0d6b52;
  --accent-deep: #063f2f;
  --accent-soft: #e8f5ef;
  --gold: #a97626;
}
.study-card {
  overflow: hidden;
  border: 1px solid rgba(16, 24, 23, 0.12);
  border-radius: 18px;
  background: var(--surface);
  box-shadow: 0 22px 70px rgba(25, 32, 29, 0.14);
}
.front-media {
  position: relative;
  padding: 12px;
  background: linear-gradient(135deg, #08100e 0%, #17241f 58%, #080b0a 100%);
}
.front-media video,
.replay-media video {
  display: block;
  width: 100%;
  aspect-ratio: 16 / 9;
  max-height: 500px;
  object-fit: cover;
  border-radius: 12px;
  background: #050706;
}
.no-media {
  display: grid;
  min-height: 220px;
  place-items: center;
  padding: 28px;
  border: 1px dashed rgba(255, 255, 255, 0.24);
  border-radius: 12px;
  color: rgba(255, 255, 255, 0.82);
  text-align: center;
}
.media-bar,
.hero-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  color: rgba(255, 255, 255, 0.78);
  font-size: 12px;
  font-weight: 780;
}
.media-bar {
  margin-bottom: 10px;
}
.pill {
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  padding: 5px 10px;
  border: 1px solid rgba(255, 255, 255, 0.16);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.10);
}
.front-task {
  display: grid;
  gap: 12px;
  padding: 20px 24px 22px;
}
.task-kicker,
.section-label {
  margin: 0;
  color: var(--accent);
  font-size: 12px;
  font-weight: 860;
}
.task-title {
  margin: 0;
  color: var(--ink);
  font-size: 26px;
  line-height: 1.25;
  font-weight: 880;
}
.front-content {
  margin: 0;
  padding: 12px 14px;
  border-left: 4px solid var(--gold);
  border-radius: 8px;
  background: #fbf5e9;
  color: #504737;
  font-size: 15px;
  font-weight: 680;
}
.audio-panel {
  display: grid;
  gap: 10px;
  padding: 14px 18px 18px;
  border-top: 1px solid var(--line);
  background: linear-gradient(180deg, #fbfdfb 0%, #f3f7f4 100%);
}
.audio-title {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  color: var(--muted);
  font-size: 12px;
  font-weight: 800;
}
.audio-row {
  display: grid;
  grid-template-columns: 92px minmax(0, 1fr);
  gap: 12px;
  align-items: center;
}
.audio-row span {
  color: var(--muted);
  font-size: 12px;
  font-weight: 780;
}
audio {
  width: 100%;
  min-height: 38px;
  color-scheme: light;
}
.back-card {
  background: #fffdf8;
}
.answer-hero {
  padding: 24px 28px 22px;
  border-bottom: 1px solid var(--line);
  background:
    radial-gradient(circle at 100% 0%, rgba(169, 118, 38, 0.16), rgba(169, 118, 38, 0) 34%),
    linear-gradient(135deg, #fffdf8 0%, var(--accent-soft) 100%);
}
.answer-hero .hero-meta {
  margin-bottom: 12px;
  color: var(--muted);
}
.hero-phrase {
  margin: 0;
  color: var(--accent-deep);
  font-size: 35px;
  line-height: 1.14;
  font-weight: 900;
}
.hero-meaning {
  margin-top: 9px;
  color: #26322f;
  font-size: 20px;
  font-weight: 780;
}
.translation {
  margin-top: 8px;
  color: #5d4b28;
  font-size: 17px;
  font-weight: 700;
}
.answer-key,
.teacher-note {
  margin-top: 14px;
  padding: 12px 14px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.72);
}
.answer-key {
  display: grid;
  gap: 4px;
  border: 1px solid rgba(13, 107, 82, 0.18);
}
.answer-key span,
.detail strong {
  color: var(--muted);
  font-size: 12px;
  font-weight: 840;
}
.answer-key strong {
  color: var(--accent-deep);
  font-size: 19px;
  line-height: 1.35;
}
.teacher-note {
  border: 1px solid rgba(13, 107, 82, 0.14);
  color: #24332e;
  font-size: 15px;
}
.sentence-panel {
  padding: 20px 28px 8px;
}
.english {
  margin-top: 6px;
  color: #101817;
  font-size: 24px;
  line-height: 1.36;
  font-weight: 850;
}
.detail-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  padding: 16px 28px 24px;
}
.detail {
  min-height: 96px;
  padding: 13px 14px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: #fffaf1;
}
.detail.wide {
  grid-column: 1 / -1;
  background: #f8fbf9;
}
.detail p {
  margin: 6px 0 0;
  color: #25322e;
  font-size: 15px;
}
.replay-panel {
  display: grid;
  grid-template-columns: minmax(220px, 330px) minmax(0, 1fr);
  gap: 16px;
  align-items: center;
  padding: 16px 18px 18px;
  border-top: 1px solid var(--line);
  background: #f3f6f2;
}
.replay-media {
  padding: 8px;
  border-radius: 12px;
  background: #101614;
}
.meta-line {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}
.meta-chip {
  padding: 6px 9px;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: #fffdf8;
  color: var(--muted);
  font-size: 12px;
  font-weight: 760;
}
@media (min-width: 860px) {
  .back-card.has-media {
    display: grid;
    grid-template-columns: minmax(285px, 0.72fr) minmax(0, 1fr);
  }
  .back-card.has-media .replay-panel {
    grid-column: 1;
    grid-row: 1 / span 3;
    grid-template-columns: 1fr;
    align-content: start;
    border-top: 0;
    border-right: 1px solid var(--line);
    background:
      linear-gradient(180deg, #0b1512 0%, #15211d 46%, #f3f6f2 46%, #f3f6f2 100%);
  }
  .back-card.has-media .answer-hero,
  .back-card.has-media .sentence-panel,
  .back-card.has-media .detail-grid {
    grid-column: 2;
  }
}
@media (max-width: 650px) {
  .card { padding: 10px; }
  .study-card { border-radius: 14px; }
  .task-title { font-size: 22px; }
  .hero-phrase { font-size: 28px; }
  .english { font-size: 20px; }
  .audio-row,
  .replay-panel,
  .detail-grid {
    grid-template-columns: 1fr;
  }
}
"""


FRONT_TEMPLATE = """
<div class="wrap immersive-template">
  <section class="study-card front-card">
    <div class="front-media">
      <div class="media-bar">
        <span class="pill">{{CardType}}</span>
        <span class="pill">{{SourceTime}}</span>
      </div>
      {{#Video}}{{Video}}{{/Video}}
      {{^Video}}<div class="no-media"><strong>知识卡</strong><span>先回答问题，翻面后核对答案。</span></div>{{/Video}}
    </div>
    <div class="front-task">
      <p class="task-kicker">{{#Video}}先听，不看字幕{{/Video}}{{^Video}}主动回忆{{/Video}}</p>
      <h1 class="task-title">{{FrontPrompt}}</h1>
      {{#FrontContent}}<p class="front-content">{{FrontContent}}</p>{{/FrontContent}}
    </div>
    {{#Audio}}<div class="audio-panel">
      <div class="audio-title"><strong>声音轨道</strong><span>0.75x 慢放 / 循环</span></div>
      <div class="audio-row"><span>原声音频</span>{{Audio}}</div>
      {{#TtsAudio}}<div class="audio-row"><span>整句 AI 朗读</span>{{TtsAudio}}</div>{{/TtsAudio}}
    </div>{{/Audio}}
  </section>
</div>
<script>
  setTimeout(function () {
    document.querySelectorAll("video,audio").forEach(function (node) {
      node.playbackRate = 0.75;
      node.loop = true;
    });
  }, 60);
</script>
"""


BACK_TEMPLATE = """
<div class="wrap immersive-template">
  <section class="study-card back-card {{#Video}}has-media{{/Video}}">
    {{#Video}}<div class="replay-panel">
      <div class="replay-media">{{Video}}</div>
      <div>
        <div class="audio-title"><strong>回放</strong><span>{{SourceTime}}</span></div>
        {{#Audio}}<div class="audio-row"><span>原声音频</span>{{Audio}}</div>{{/Audio}}
        {{#TtsAudio}}<div class="audio-row"><span>整句 AI 朗读</span>{{TtsAudio}}</div>{{/TtsAudio}}
      </div>
    </div>{{/Video}}

    <div class="answer-hero">
      <div class="hero-meta">
        <span>{{CardType}}</span>
        <span>{{Difficulty}} · {{SourceTime}}</span>
      </div>
      <h1 class="hero-phrase">{{Phrase}}</h1>
      <div class="hero-meaning">{{ChineseFeel}}</div>
      <div class="translation">{{Chinese}}</div>
      {{#Answer}}<div class="answer-key"><span>这张卡真正要回忆的答案</span><strong>{{Answer}}</strong></div>{{/Answer}}
      <div class="teacher-note">{{TeacherNote}}</div>
    </div>

    <div class="sentence-panel">
      <span class="section-label">{{#Video}}英文原句{{/Video}}{{^Video}}正面问题{{/Video}}</span>
      <div class="english">{{English}}</div>
      {{#Cloze}}<div class="meta-line"><span class="meta-chip">填空：{{Cloze}}</span></div>{{/Cloze}}
    </div>

    <div class="detail-grid">
      <div class="detail"><strong>释义 / 概念</strong><p>{{Definition}}</p></div>
      <div class="detail"><strong>搭配 / 相关概念</strong><p>{{Collocations}}</p></div>
      <div class="detail"><strong>语境</strong><p>{{Context}}</p></div>
      <div class="detail"><strong>例句</strong><p>{{Example}}</p></div>
      <div class="detail wide"><strong>为什么值得学</strong><p>{{Why}}</p></div>
    </div>
  </section>
</div>
<script>
  setTimeout(function () {
    document.querySelectorAll("video,audio").forEach(function (node) {
      node.playbackRate = 0.75;
      node.loop = true;
    });
  }, 60);
</script>
"""


DICTIONARY_FRONT_TEMPLATE = FRONT_TEMPLATE
DICTIONARY_BACK_TEMPLATE = BACK_TEMPLATE
MINIMAL_FRONT_TEMPLATE = FRONT_TEMPLATE
MINIMAL_BACK_TEMPLATE = BACK_TEMPLATE


# V10 keeps the existing fields, but moves the visual language to a lighter
# Apple-style study card with adaptive height, quieter borders, and blue emphasis.
CARD_CSS = """
.card {
  margin: 0;
  min-height: 0;
  padding: clamp(10px, 1.4vh, 18px);
  background: #f5f5f7;
  color: #1d1d1f;
  font-family: "SF Pro Display", "SF Pro Text", Inter, "Segoe UI", "Noto Sans SC", Arial, sans-serif;
  line-height: 1.42;
  text-align: left;
  letter-spacing: 0;
  overflow: hidden;
  display: flex;
  justify-content: center;
  align-items: flex-start;
}
* { box-sizing: border-box; }
[data-fit] {
  min-width: 0;
  max-width: 100%;
}
* {
  scrollbar-width: none;
  -ms-overflow-style: none;
}
*::-webkit-scrollbar {
  width: 0 !important;
  height: 0 !important;
  display: none !important;
}
html, body, #qa {
  width: 100% !important;
  min-height: 100% !important;
  height: 100% !important;
  max-width: none !important;
  margin: 0 !important;
  overflow: hidden !important;
}
.wrap {
  width: min(1360px, calc(100vw - clamp(24px, 4vw, 88px)));
  max-width: calc(100vw - 20px);
  height: min(1500px, 91vh);
  min-height: min(720px, 91vh);
  margin: 0 auto;
  display: grid;
  min-width: 0;
  --ink: #1d1d1f;
  --muted: #6e6e73;
  --line: rgba(60, 60, 67, 0.14);
  --paper: #ffffff;
  --soft: #f5f5f7;
  --blue: #007aff;
  --blue-deep: #0057d8;
  --blue-soft: rgba(0, 122, 255, 0.10);
  --green: var(--blue);
  --green-deep: var(--blue-deep);
  --green-soft: var(--blue-soft);
  --amber: #ff9f0a;
  --font-scale: 1;
}
.study-card {
  width: 100%;
  height: 100%;
  min-height: 0;
  max-width: 100%;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 18px;
  background: var(--paper);
  box-shadow: 0 20px 54px rgba(0, 0, 0, 0.10);
}
.front-card {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  grid-template-rows: minmax(0, 56%) minmax(145px, 22%) minmax(110px, 22%);
}
.cinema {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  min-height: 0;
  padding: clamp(10px, 1.2vh, 16px);
  background: #111114;
}
.media-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
  color: rgba(255, 255, 255, 0.76);
  font-size: 12px;
  font-weight: 800;
}
.pill {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 3px 9px;
  border: 1px solid rgba(255, 255, 255, 0.16);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.09);
}
.cinema video,
.replay video {
  display: block;
  width: 100%;
  height: 100%;
  min-height: 0;
  aspect-ratio: 16 / 9;
  max-height: 100%;
  object-fit: contain;
  border-radius: 8px;
  background: #000;
}
.replay video {
  max-height: 100%;
}
.no-media {
  display: grid;
  height: 100%;
  min-height: 0;
  place-items: center;
  padding: 28px;
  border: 1px dashed rgba(255, 255, 255, 0.25);
  border-radius: 12px;
  color: rgba(255, 255, 255, 0.84);
  text-align: center;
}
.no-media strong {
  display: block;
  margin-bottom: 8px;
  font-size: 25px;
}
.front-task {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: clamp(12px, 1.6vw, 24px);
  align-items: center;
  min-height: 0;
  overflow: hidden;
  padding: clamp(16px, 2.2vh, 28px) clamp(24px, 3.2vw, 42px);
}
.task-kicker,
.label {
  margin: 0;
  color: var(--green);
  font-size: 12px;
  font-weight: 860;
}
.task-title {
  margin: 4px 0 0;
  color: var(--ink);
  font-size: clamp(24px, min(3vw, 4.2vh), 34px);
  line-height: 1.18;
  font-weight: 980;
  overflow-wrap: anywhere;
}
.front-content {
  margin: clamp(8px, 1.2vh, 14px) 0 0;
  padding: clamp(10px, 1.4vh, 16px) clamp(12px, 1.8vw, 20px);
  border-left: 3px solid var(--blue);
  border-radius: 8px;
  background: var(--blue-soft);
  color: var(--ink);
  font-size: clamp(18px, min(2.1vw, 3vh), 24px);
  line-height: 1.38;
  font-weight: 780;
  overflow-wrap: anywhere;
}
.front-badge {
  display: grid;
  place-items: center;
  width: 84px;
  min-height: 56px;
  padding: 9px;
  border: 1px solid rgba(0, 122, 255, 0.18);
  border-radius: 12px;
  background: var(--green-soft);
  color: var(--green-deep);
  text-align: center;
  font-size: 12px;
  font-weight: 830;
}
.audio-strip {
  display: grid;
  min-height: 0;
  gap: clamp(8px, 1vh, 12px);
  overflow: hidden;
  padding: clamp(12px, 1.8vh, 22px) clamp(24px, 3.2vw, 42px);
  border-top: 1px solid var(--line);
  background: #fbfbfd;
}
.audio-title,
.hero-meta {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  color: var(--muted);
  font-size: 12px;
  font-weight: 800;
}
.audio-row {
  display: grid;
  grid-template-columns: clamp(82px, 10vw, 128px) minmax(0, 1fr);
  gap: 12px;
  align-items: center;
  min-height: 0;
}
.audio-row span {
  color: var(--muted);
  font-size: 12px;
  font-weight: 780;
}
audio {
  width: 100%;
  max-width: 100%;
  min-height: clamp(32px, 4vh, 44px);
  color-scheme: light;
}
.back-card {
  display: grid;
  grid-template-columns: 1fr;
  grid-template-rows: minmax(260px, 38%) auto auto minmax(0, 1fr);
  min-height: 0;
}
.back-card:not(.has-media) {
  grid-template-rows: auto auto minmax(0, 1fr);
}
.replay {
  display: grid;
  grid-template-rows: minmax(0, 1fr) auto;
  gap: clamp(10px, 1.4vh, 16px);
  height: 100%;
  min-height: 0;
  max-height: none;
  overflow: hidden;
  padding: clamp(12px, 1.6vh, 22px);
  background: #111114;
}
.replay-media {
  display: grid;
  place-items: center;
  justify-self: center;
  width: 100%;
  max-width: 1040px;
  height: 100%;
  min-height: 0;
  padding: 8px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.06);
}
.replay-media video {
  width: 100%;
  height: 100%;
  max-height: none;
  object-fit: contain;
  border-radius: 7px;
}
.replay-tools {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px 16px;
  min-width: 0;
}
.replay .audio-title {
  color: rgba(255, 255, 255, 0.72);
  flex: 1 1 220px;
  align-items: center;
}
.replay-buttons {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}
.replay-audio-control {
  position: relative;
}
.replay-audio-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  min-height: 38px;
  padding: 9px 14px;
  border: 1px solid rgba(255, 255, 255, 0.16);
  border-radius: 999px;
  background: #f7f7f8;
  color: #111114;
  font-size: 13px;
  font-weight: 880;
  line-height: 1;
  box-shadow: 0 10px 26px rgba(0, 0, 0, 0.18);
  cursor: pointer;
  transition: transform 140ms ease, background 140ms ease, color 140ms ease, border-color 140ms ease;
}
.replay-audio-button:focus-visible {
  outline: 3px solid rgba(255, 255, 255, 0.26);
  outline-offset: 3px;
}
.replay-audio-button:active {
  transform: translateY(1px);
}
.replay-audio-button.is-playing {
  border-color: rgba(10, 132, 255, 0.55);
  background: #0a84ff;
  color: #ffffff;
}
.play-dot {
  display: inline-block;
  width: 0;
  height: 0;
  border-top: 6px solid transparent;
  border-bottom: 6px solid transparent;
  border-left: 9px solid currentColor;
}
.replay-audio-source {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  opacity: 0;
  pointer-events: none;
}
.replay .audio-missing {
  min-height: 38px;
  margin: 0;
  padding: 9px 12px;
  border-radius: 999px;
  font-size: 12px;
}
.replay .audio-missing span {
  display: none;
}
.answer-hero {
  display: grid;
  grid-template-rows: auto auto auto auto auto auto;
  align-content: start;
  gap: clamp(6px, 0.9vh, 12px);
  min-height: 0;
  padding: clamp(20px, 2.6vh, 34px) clamp(32px, 4vw, 56px);
  border-bottom: 1px solid var(--line);
  background: linear-gradient(135deg, #ffffff 0%, #f5f8ff 100%);
  overflow: hidden;
}
.focus-word {
  margin: 0;
  color: var(--green-deep);
  font-size: clamp(44px, min(6.2vw, 8.2vh), 78px);
  line-height: 1;
  font-weight: 980;
  overflow-wrap: anywhere;
  max-width: 100%;
  min-width: 0;
}
.focus-line {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
}
.focus-line .focus-word {
  min-width: 0;
}
.phrase-speaker {
  display: inline-grid;
  place-items: center;
  width: 38px;
  height: 38px;
  margin-top: 4px;
  border: 1px solid rgba(0, 122, 255, 0.22);
  border-radius: 999px;
  background: #ffffff;
  color: var(--green-deep);
  font-size: 24px;
  line-height: 1;
  box-shadow: 0 8px 18px rgba(0, 122, 255, 0.12);
  cursor: pointer;
  transition: background 140ms ease, color 140ms ease, box-shadow 140ms ease, transform 140ms ease;
  position: relative;
}
.phrase-speaker:focus-visible {
  outline: 3px solid rgba(0, 122, 255, 0.24);
  outline-offset: 3px;
}
.speaker-icon {
  position: relative;
  display: block;
  width: 20px;
  height: 20px;
}
.speaker-icon::before {
  content: "";
  position: absolute;
  left: 1px;
  top: 4px;
  width: 15px;
  height: 15px;
  background: currentColor;
  clip-path: polygon(0 34%, 34% 34%, 78% 9%, 78% 91%, 34% 66%, 0 66%);
}
.speaker-icon::after {
  content: "";
  position: absolute;
  left: 14px;
  top: 5px;
  width: 8px;
  height: 12px;
  border: 2px solid currentColor;
  border-left: 0;
  border-top-color: transparent;
  border-bottom-color: transparent;
  border-radius: 0 999px 999px 0;
}
.phrase-speaker:active {
  transform: translateY(1px);
  background: var(--green-soft);
}
.phrase-speaker.is-playing {
  background: var(--green-deep);
  color: #ffffff;
  box-shadow: 0 10px 24px rgba(0, 122, 255, 0.24);
}
.phrase-speaker.is-playing::after {
  content: "";
  position: absolute;
  inset: -6px;
  border: 2px solid rgba(0, 122, 255, 0.25);
  border-radius: inherit;
  animation: speakerPulse 900ms ease-out infinite;
}
@keyframes speakerPulse {
  from { opacity: 0.9; transform: scale(0.92); }
  to { opacity: 0; transform: scale(1.2); }
}
.phrase-audio {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  opacity: 0;
  pointer-events: none;
}
.meaning {
  margin: 0;
  color: var(--ink);
  font-size: clamp(22px, min(2.8vw, 3.7vh), 34px);
  line-height: 1.22;
  font-weight: 900;
  overflow-wrap: anywhere;
}
.translation {
  margin: 0;
  color: #8a5a00;
  font-size: clamp(18px, min(2.1vw, 3vh), 26px);
  line-height: 1.26;
  font-weight: 820;
  overflow-wrap: anywhere;
}
.answer-box,
.teacher {
  margin-top: 0;
  border-radius: 9px;
  background: rgba(255, 255, 255, 0.78);
}
.answer-box {
  display: grid;
  gap: 6px;
  min-height: 0;
  padding: clamp(10px, 1.3vh, 16px) clamp(14px, 2vw, 22px);
  border: 1px solid rgba(0, 122, 255, 0.14);
  background: rgba(255, 255, 255, 0.52);
}
.answer-box span,
.detail strong {
  color: var(--muted);
  font-size: 12px;
  font-weight: 850;
}
.answer-box strong {
  color: var(--green-deep);
  font-size: clamp(28px, min(4vw, 5.3vh), 48px);
  line-height: 1.12;
  font-weight: 980;
  overflow-wrap: anywhere;
  max-width: 100%;
}
.teacher {
  display: block;
  overflow: hidden;
  padding: clamp(8px, 1vh, 14px) clamp(12px, 1.7vw, 18px);
  border: 1px solid rgba(154, 106, 34, 0.18);
  color: #343437;
  font-size: clamp(14px, min(1.45vw, 2.1vh), 18px);
  line-height: 1.42;
  font-weight: 640;
  overflow-wrap: anywhere;
}
.dense-card .answer-hero {
  gap: 5px;
  padding-top: 14px;
  padding-bottom: 12px;
}
.dense-card .answer-box,
.dense-card .teacher,
.dense-card .detail {
  padding-top: 8px;
  padding-bottom: 8px;
}
.dense-card .sentence {
  gap: 4px;
  padding-top: 10px;
  padding-bottom: 10px;
}
.dense-card .detail-grid {
  gap: 8px;
  padding-top: 10px;
  padding-bottom: 12px;
}
.dense-card .chip {
  padding: 4px 8px;
  font-size: 13px;
}
.ultra-dense-card .answer-hero {
  gap: 4px;
  padding-top: 10px;
  padding-bottom: 9px;
}
.ultra-dense-card .answer-box,
.ultra-dense-card .teacher,
.ultra-dense-card .detail {
  padding-top: 6px;
  padding-bottom: 6px;
}
.ultra-dense-card .sentence {
  padding-top: 8px;
  padding-bottom: 8px;
}
.ultra-dense-card .detail-grid {
  gap: 6px;
  padding-top: 8px;
  padding-bottom: 9px;
}
.ultra-dense-card .chip {
  padding: 3px 7px;
  font-size: 12px;
}
.sentence {
  display: grid;
  grid-template-rows: auto auto auto;
  gap: clamp(7px, 0.9vh, 12px);
  min-height: 0;
  overflow: visible;
  padding: clamp(18px, 2.1vh, 28px) clamp(34px, 4vw, 58px);
  border-bottom: 1px solid var(--line);
  background: #fbfbfd;
}
.english {
  display: block;
  min-height: 0;
  height: auto;
  margin: 0;
  color: var(--ink);
  font-size: clamp(24px, min(3.4vw, 4.7vh), 44px);
  line-height: 1.18;
  font-weight: 1000;
  overflow: visible;
  overflow-wrap: break-word;
  word-break: normal;
  text-wrap: balance;
  max-width: 100%;
}
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 0;
  min-width: 0;
}
.chip {
  max-width: 100%;
  padding: 6px 10px;
  border: 1px solid rgba(0, 122, 255, 0.22);
  border-radius: 999px;
  background: #ffffff;
  color: var(--green-deep);
  font-size: clamp(13px, min(1.4vw, 2vh), 17px);
  line-height: 1.2;
  font-weight: 920;
  white-space: normal;
  overflow-wrap: anywhere;
}
.audio-row.audio-missing {
  border-color: rgba(154, 106, 34, 0.2);
  background: rgba(255, 244, 224, 0.84);
  color: #8a5a00;
}
.audio-row.audio-missing em {
  font-style: normal;
  font-weight: 760;
  color: #8a5a00;
}
.detail-grid {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  grid-auto-rows: minmax(0, 1fr);
  min-height: 0;
  overflow: hidden;
  gap: clamp(8px, 1vw, 14px);
  padding: clamp(14px, 1.8vh, 22px) clamp(32px, 4vw, 56px) clamp(16px, 2vh, 26px);
}
.detail {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
  padding: clamp(10px, 1.3vh, 16px) clamp(12px, 1.6vw, 18px);
  border: 1px solid var(--line);
  border-radius: 9px;
  background: #ffffff;
}
.detail:nth-child(1),
.detail:nth-child(2),
.detail:nth-child(3) {
  grid-column: span 2;
}
.detail:nth-child(4),
.detail:nth-child(5) {
  grid-column: span 3;
}
.detail.wide {
  background: #f8fbff;
}
.detail p {
  display: block;
  flex: 1;
  min-height: 0;
  margin: 6px 0 0;
  color: #2c2c2e;
  font-size: clamp(14px, min(1.45vw, 2.15vh), 19px);
  line-height: 1.36;
  overflow: hidden;
  overflow-wrap: anywhere;
}
.detail p.english-detail {
  color: var(--ink);
  font-size: clamp(14px, min(1.6vw, 2.3vh), 21px);
  line-height: 1.24;
  font-weight: 760;
  overflow-wrap: anywhere;
}
.learning-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  grid-auto-rows: minmax(0, 1fr);
}
.learning-grid .detail {
  grid-column: auto;
}
.learning-block {
  gap: clamp(4px, 0.7vh, 9px);
}
.learning-block p {
  flex: 0 1 auto;
}
.support-note {
  padding-top: 6px;
  border-top: 1px solid var(--line);
  color: var(--muted) !important;
}
.example-line {
  color: var(--blue-deep) !important;
}
@media (max-width: 680px) {
  .card { padding: 6px; }
  .wrap {
    width: calc(100vw - 12px);
    height: min(1000px, 92vh);
    min-height: min(620px, 92vh);
  }
  .study-card { border-radius: 10px; }
  .front-card {
    grid-template-rows: minmax(0, 48%) minmax(130px, 26%) minmax(95px, 26%);
  }
  .back-card {
    grid-template-rows: minmax(230px, 36%) auto auto minmax(0, 1fr);
  }
  .front-task,
  .audio-row {
    grid-template-columns: 1fr;
  }
  .replay-tools {
    align-content: start;
  }
  .replay-buttons {
    justify-content: flex-start;
  }
  .detail-grid {
    grid-template-columns: 1fr;
    grid-auto-rows: minmax(0, 1fr);
  }
  .detail:nth-child(1),
  .detail:nth-child(2),
  .detail:nth-child(3),
  .detail:nth-child(4),
  .detail:nth-child(5) {
    grid-column: auto;
  }
  .front-badge { width: 100%; min-height: 52px; }
  .task-title { font-size: 24px; }
  .focus-word { font-size: 40px; }
  .phrase-speaker { width: 36px; height: 36px; }
  .speaker-icon { width: 21px; height: 21px; }
  .meaning { font-size: 20px; }
  .translation { font-size: 17px; }
  .english { font-size: 26px; }
  .answer-box strong { font-size: 26px; }
  .front-content { font-size: 17px; }
  .detail p,
  .detail p.english-detail { font-size: 14px; }
  .answer-hero,
  .sentence,
  .detail-grid {
    padding-left: 18px;
    padding-right: 18px;
  }
}
@media (max-height: 940px) {
  .back-card {
    grid-template-rows: minmax(240px, 36%) auto auto minmax(0, 1fr);
  }
  .answer-hero {
    gap: 5px;
    padding-top: 14px;
    padding-bottom: 12px;
  }
  .teacher {
    padding-top: 7px;
    padding-bottom: 7px;
  }
  .sentence {
    gap: 4px;
    padding-top: 10px;
    padding-bottom: 10px;
  }
  .detail-grid {
    padding-top: 10px;
    padding-bottom: 12px;
  }
  .detail p,
  .detail p.english-detail {
    font-size: clamp(13px, min(1.25vw, 1.85vh), 16px);
    line-height: 1.28;
  }
}
@media (max-height: 760px) {
  .card { padding: 6px; }
  .wrap {
    height: min(1120px, 92vh);
    min-height: min(610px, 92vh);
  }
  .front-card {
    grid-template-rows: minmax(0, 50%) minmax(120px, 25%) minmax(90px, 25%);
  }
  .back-card {
    grid-template-rows: minmax(190px, 34%) auto auto minmax(0, 1fr);
  }
  .replay {
    gap: 8px;
    padding: 8px;
  }
  .audio-strip .audio-row + .audio-row {
    margin-top: 4px;
  }
  .replay-audio-button,
  .replay .audio-missing {
    min-height: 34px;
    padding: 8px 11px;
    font-size: 12px;
  }
  .answer-hero {
    gap: 5px;
    padding: 12px 22px;
  }
  .focus-word { font-size: clamp(32px, min(5.2vw, 6.6vh), 54px); }
  .meaning { font-size: clamp(18px, min(2.3vw, 3.1vh), 25px); }
  .translation { font-size: clamp(15px, min(1.8vw, 2.6vh), 21px); }
  .answer-box { padding: 8px 12px; }
  .answer-box strong { font-size: clamp(23px, min(3.2vw, 4.2vh), 36px); }
  .teacher { padding: 7px 10px; }
  .sentence {
    gap: 4px;
    padding: 10px 22px;
  }
  .english { font-size: clamp(21px, min(3.1vw, 4vh), 35px); }
  .detail-grid {
    gap: 7px;
    padding: 9px 22px 11px;
  }
  .detail { padding: 8px 10px; }
  .detail p,
  .detail p.english-detail {
    font-size: clamp(12px, min(1.2vw, 1.8vh), 15px);
    line-height: 1.28;
  }
}
@media (max-height: 620px) {
  .wrap {
    height: 92vh;
    min-height: 92vh;
  }
  .back-card {
    grid-template-rows: minmax(160px, 31%) auto auto minmax(0, 1fr);
  }
  .front-content { display: none; }
  .teacher { padding: 5px 8px; }
  .audio-strip { padding-top: 6px; padding-bottom: 6px; }
  .answer-box strong { font-size: clamp(21px, 3.2vw, 28px); }
  .detail-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

/* Mobile-first review card overrides: keep every learning block in the natural
   document flow so Anki mobile never hides the answer, usage, or warning. */
html,
body,
#qa {
  height: auto !important;
  min-height: 100% !important;
  overflow-x: hidden !important;
  overflow-y: auto !important;
}
.card {
  min-height: 100%;
  overflow-x: hidden;
  overflow-y: visible;
}
.wrap {
  width: min(980px, calc(100vw - 16px));
  max-width: calc(100vw - 12px);
  height: auto;
  min-height: 0;
}
.study-card {
  height: auto;
  min-height: 0;
  overflow: visible;
  border-radius: 14px;
  box-shadow: 0 14px 38px rgba(0, 0, 0, 0.08);
}
.front-card,
.back-card,
.back-card:not(.has-media) {
  display: flex;
  flex-direction: column;
}
.front-task {
  order: 0;
  grid-template-columns: minmax(0, 1fr);
  align-items: start;
  overflow: visible;
  padding: clamp(18px, 4vw, 34px);
  border-bottom: 1px solid var(--line);
}
.front-badge {
  width: auto;
  min-height: 0;
  justify-self: start;
  padding: 6px 10px;
}
.cinema {
  order: 1;
  grid-template-rows: auto auto;
  padding: clamp(8px, 2vw, 14px);
}
.cinema video {
  height: auto;
  max-height: min(46vh, 520px);
}
.audio-strip {
  order: 2;
  overflow: visible;
  padding: clamp(12px, 3vw, 20px) clamp(18px, 4vw, 34px);
}
.audio-row {
  grid-template-columns: clamp(70px, 18vw, 108px) minmax(0, 1fr);
}
.replay {
  height: auto;
  max-height: none;
  grid-template-rows: auto auto;
  overflow: visible;
  padding: clamp(10px, 3vw, 18px);
}
.replay-media {
  height: auto;
  max-width: 920px;
  padding: 0;
}
.replay-media video {
  height: auto;
  max-height: min(34vh, 360px);
}
.answer-hero {
  gap: 10px;
  overflow: visible;
  padding: clamp(16px, 4vw, 30px);
  background: #ffffff;
}
.answer-line {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}
.answer-box strong {
  font-size: clamp(24px, 6vw, 44px);
}
.meaning {
  color: #3a3a3c;
  font-size: clamp(16px, 3.8vw, 23px);
  font-weight: 760;
}
.sentence {
  overflow: visible;
  padding: clamp(14px, 4vw, 26px);
}
.english {
  font-size: clamp(22px, 5vw, 38px);
}
.detail-grid,
.learning-grid {
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  grid-auto-rows: auto;
  overflow: visible;
  padding: clamp(14px, 4vw, 26px);
}
.detail,
.detail p,
.detail p.english-detail {
  overflow: visible;
}
.detail p {
  flex: 0 1 auto;
}
@media (max-width: 680px) {
  .card {
    padding: 5px;
  }
  .wrap {
    width: calc(100vw - 10px);
  }
  .audio-row {
    grid-template-columns: 1fr;
  }
  .detail-grid,
  .learning-grid {
    grid-template-columns: 1fr;
  }
  .replay-buttons {
    justify-content: flex-start;
  }
}
"""


FRONT_TEMPLATE = """
<div class="wrap">
  <section class="study-card front-card">
    <div class="cinema">
      <div class="media-top">
        <span class="pill">{{CardType}}</span>
        <span class="pill">{{SourceTime}}</span>
      </div>
      {{#Video}}{{Video}}{{/Video}}
      {{^Video}}<div class="no-media"><div><strong>知识卡</strong><span>先回答问题，翻面后核对答案。</span></div></div>{{/Video}}
    </div>
    <div class="front-task">
      <div>
        <p class="task-kicker">{{#Video}}先听，不看字幕{{/Video}}{{^Video}}主动回忆{{/Video}}</p>
        <h1 class="task-title" data-fit data-fit-min="18" data-fit-max="36">{{FrontPrompt}}</h1>
        {{#FrontContent}}<p class="front-content" data-fit data-fit-min="15" data-fit-max="25">{{FrontContent}}</p>{{/FrontContent}}
      </div>
      <div class="front-badge">{{#Video}}无字幕听辨{{/Video}}{{^Video}}主动检索{{/Video}}</div>
    </div>
    {{#Audio}}<div class="audio-strip">
      <div class="audio-title"><strong>原声线索</strong><span>0.75x 慢放 / 循环</span></div>
      <div class="audio-row"><span>原声音频</span>{{Audio}}</div>
    </div>{{/Audio}}
  </section>
</div>
<script>
  var responsiveFitQueued = false;
  function currentFontScale(root) {
    var wrap = (root || document).querySelector(".wrap");
    var raw = wrap ? window.getComputedStyle(wrap).getPropertyValue("--font-scale") : "1";
    var scale = parseFloat(raw);
    return isFinite(scale) && scale > 0 ? scale : 1;
  }
  function nodeHasOverflow(node) {
    var isDetailText = node.closest && node.closest(".detail");
    var heightSlack = isDetailText ? 2 : Math.max(6, Math.min(24, node.clientHeight * 0.18));
    var widthSlack = Math.max(2, Math.min(12, node.clientWidth * 0.01));
    if (node.hasAttribute("data-fit")) {
      var textLength = ((node.textContent || "").trim()).length;
      var desiredHeight = textLength > 90 ? 42 : (textLength > 45 ? 28 : 14);
      if (textLength && node.clientHeight < desiredHeight) return true;
    }
    return node.scrollWidth > node.clientWidth + widthSlack || node.scrollHeight > node.clientHeight + heightSlack;
  }
  function fitResponsiveText(root) {
    var scope = root || document;
    var scale = currentFontScale(scope);
    var nodes = scope.querySelectorAll("[data-fit]");
    nodes.forEach(function (node) {
      var style = window.getComputedStyle(node);
      var baseMin = parseFloat(node.getAttribute("data-fit-min")) || 12;
      var baseMax = parseFloat(node.getAttribute("data-fit-max")) || parseFloat(style.fontSize) || baseMin;
      var min = Math.max(10, baseMin * scale);
      var max = Math.max(min, baseMax * scale);
      if (node.clientWidth < 8 || node.clientHeight < 8) return;
      node.style.fontSize = max + "px";
      for (var i = 0; i < 24; i += 1) {
        if (!nodeHasOverflow(node)) break;
        max = Math.max(min, max - 1.5);
        node.style.fontSize = max + "px";
        if (max <= min) break;
      }
    });
  }
  function hasHiddenOverflow(root) {
    var nodes = (root || document).querySelectorAll("[data-fit], .answer-hero, .sentence, .detail-grid, .detail, .teacher, .english, .chips");
    for (var i = 0; i < nodes.length; i += 1) {
      var node = nodes[i];
      var style = window.getComputedStyle(node);
      if (style.display === "none" || style.visibility === "hidden") continue;
      if (node.clientWidth < 4) continue;
      if (nodeHasOverflow(node)) return true;
    }
    return false;
  }
  function fitAdaptiveCard(root) {
    var scope = root || document;
    var wrap = scope.querySelector(".wrap");
    var card = scope.querySelector(".study-card");
    if (wrap) {
      wrap.style.setProperty("--font-scale", "1");
      wrap.classList.remove("dense-card", "ultra-dense-card");
    }
    if (!card) return;
    fitResponsiveText(scope);
  }
  function scheduleResponsiveFit() {
    if (responsiveFitQueued) return;
    responsiveFitQueued = true;
    var run = function () {
      responsiveFitQueued = false;
      fitAdaptiveCard(document);
    };
    if (window.requestAnimationFrame) {
      window.requestAnimationFrame(run);
    } else {
      setTimeout(run, 16);
    }
  }
  function refreshResponsiveCard() {
    document.querySelectorAll("video,audio").forEach(function (node) {
      if (node.closest && node.closest(".phrase-audio")) return;
      node.playbackRate = 0.75;
      node.loop = true;
    });
    fitAdaptiveCard(document);
  }
  setTimeout(refreshResponsiveCard, 80);
  setTimeout(scheduleResponsiveFit, 320);
  window.addEventListener("resize", scheduleResponsiveFit);
  if (window.ResizeObserver) {
    var observedWrap = document.querySelector(".wrap");
    if (observedWrap) new ResizeObserver(scheduleResponsiveFit).observe(observedWrap);
  }
</script>
"""


BACK_TEMPLATE = """
<div class="wrap">
  <section class="study-card back-card {{#Video}}has-media{{/Video}}">
    {{#Video}}<div class="replay">
      <div class="replay-media">{{Video}}</div>
      <div class="replay-tools">
        <div class="audio-title"><strong>回放校对</strong><span>{{SourceTime}}</span></div>
        <div class="replay-buttons">
          {{#Audio}}<span class="replay-audio-control"><button class="replay-audio-button" type="button" title="播放原声音频" onclick="playReplayAudio(this)"><span class="play-dot" aria-hidden="true"></span><span>原声</span></button><span class="replay-audio-source">{{Audio}}</span></span>{{/Audio}}
          {{#TtsAudio}}<span class="replay-audio-control"><button class="replay-audio-button" type="button" title="播放整句 AI 朗读" onclick="playReplayAudio(this)"><span class="play-dot" aria-hidden="true"></span><span>AI 朗读</span></button><span class="replay-audio-source">{{TtsAudio}}</span></span>{{/TtsAudio}}
          {{^TtsAudio}}<span class="audio-missing"><span>整句 AI 朗读</span><em>AI 朗读未生成</em></span>{{/TtsAudio}}
        </div>
      </div>
    </div>{{/Video}}

    <div class="answer-hero">
      <div class="hero-meta">
        <span>{{CardType}}</span>
        <span>{{Difficulty}}</span>
      </div>
      {{#Answer}}<div class="answer-box main-answer">
        <span>核心答案</span>
        <div class="answer-line">
          <strong data-fit data-fit-min="20" data-fit-max="44">{{Answer}}</strong>
          {{#PhraseTtsAudio}}<button class="phrase-speaker" type="button" aria-label="播放表达发音" title="播放表达发音" onclick="playPhraseTts(this)"><span class="speaker-icon" aria-hidden="true"></span></button><span class="phrase-audio">{{PhraseTtsAudio}}</span>{{/PhraseTtsAudio}}
        </div>
      </div>{{/Answer}}
    </div>

    <div class="sentence">
      <span class="label">{{#Video}}英文原句{{/Video}}{{^Video}}正面问题{{/Video}}</span>
      <div class="english" data-fit data-fit-min="18" data-fit-max="44">{{English}}</div>
      <div class="chips">
        {{#Cloze}}<span class="chip cloze-chip">填空：{{Cloze}}</span>{{/Cloze}}
        <span class="chip">{{SourceTime}}</span>
      </div>
    </div>

    <div class="detail-grid learning-grid">
      <div class="detail learning-block understand-block">
        <strong>怎么理解</strong>
        <p data-fit data-fit-min="13" data-fit-max="20">{{Definition}}</p>
        {{#ChineseFeel}}<p class="support-note" data-fit data-fit-min="12" data-fit-max="18">{{ChineseFeel}}</p>{{/ChineseFeel}}
        {{#Why}}<p class="support-note" data-fit data-fit-min="12" data-fit-max="18">{{Why}}</p>{{/Why}}
      </div>
      <div class="detail learning-block use-block">
        <strong>怎么用</strong>
        <p class="english-detail" data-fit data-fit-min="13" data-fit-max="21">{{Collocations}}</p>
        {{#Context}}<p class="support-note" data-fit data-fit-min="12" data-fit-max="18">{{Context}}</p>{{/Context}}
      </div>
      {{#TeacherNote}}<div class="detail learning-block caution-block">
        <strong>别这样用</strong>
        <p data-fit data-fit-min="12" data-fit-max="18">{{TeacherNote}}</p>
      </div>{{/TeacherNote}}
      {{#Example}}<div class="detail learning-block transfer-block">
        <strong>再造一句</strong>
        <p class="english-detail example-line" data-fit data-fit-min="13" data-fit-max="20">{{Example}}</p>
      </div>{{/Example}}
    </div>
  </section>
</div>
<script>
  var responsiveFitQueued = false;
  function currentFontScale(root) {
    var wrap = (root || document).querySelector(".wrap");
    var raw = wrap ? window.getComputedStyle(wrap).getPropertyValue("--font-scale") : "1";
    var scale = parseFloat(raw);
    return isFinite(scale) && scale > 0 ? scale : 1;
  }
  function nodeHasOverflow(node) {
    var isDetailText = node.closest && node.closest(".detail");
    var heightSlack = isDetailText ? 2 : Math.max(6, Math.min(24, node.clientHeight * 0.18));
    var widthSlack = Math.max(2, Math.min(12, node.clientWidth * 0.01));
    if (node.hasAttribute("data-fit")) {
      var textLength = ((node.textContent || "").trim()).length;
      var desiredHeight = textLength > 90 ? 42 : (textLength > 45 ? 28 : 14);
      if (textLength && node.clientHeight < desiredHeight) return true;
    }
    return node.scrollWidth > node.clientWidth + widthSlack || node.scrollHeight > node.clientHeight + heightSlack;
  }
  function fitResponsiveText(root) {
    var scope = root || document;
    var scale = currentFontScale(scope);
    var nodes = scope.querySelectorAll("[data-fit]");
    nodes.forEach(function (node) {
      var style = window.getComputedStyle(node);
      var baseMin = parseFloat(node.getAttribute("data-fit-min")) || 12;
      var baseMax = parseFloat(node.getAttribute("data-fit-max")) || parseFloat(style.fontSize) || baseMin;
      var min = Math.max(10, baseMin * scale);
      var max = Math.max(min, baseMax * scale);
      if (node.clientWidth < 8 || node.clientHeight < 8) return;
      node.style.fontSize = max + "px";
      for (var i = 0; i < 24; i += 1) {
        if (!nodeHasOverflow(node)) break;
        max = Math.max(min, max - 1.5);
        node.style.fontSize = max + "px";
        if (max <= min) break;
      }
    });
  }
  function hasHiddenOverflow(root) {
    var nodes = (root || document).querySelectorAll("[data-fit], .answer-hero, .sentence, .detail-grid, .detail, .teacher, .english, .chips");
    for (var i = 0; i < nodes.length; i += 1) {
      var node = nodes[i];
      var style = window.getComputedStyle(node);
      if (style.display === "none" || style.visibility === "hidden") continue;
      if (node.clientWidth < 4) continue;
      if (nodeHasOverflow(node)) return true;
    }
    return false;
  }
  function fitAdaptiveCard(root) {
    var scope = root || document;
    var wrap = scope.querySelector(".wrap");
    var card = scope.querySelector(".study-card");
    if (wrap) {
      wrap.style.setProperty("--font-scale", "1");
      wrap.classList.remove("dense-card", "ultra-dense-card");
    }
    if (!card) return;
    fitResponsiveText(scope);
  }
  function scheduleResponsiveFit() {
    if (responsiveFitQueued) return;
    responsiveFitQueued = true;
    var run = function () {
      responsiveFitQueued = false;
      fitAdaptiveCard(document);
    };
    if (window.requestAnimationFrame) {
      window.requestAnimationFrame(run);
    } else {
      setTimeout(run, 16);
    }
  }
  function refreshResponsiveCard() {
    document.querySelectorAll("video,audio").forEach(function (node) {
      if (node.closest && node.closest(".phrase-audio")) return;
      node.playbackRate = 0.75;
      node.loop = true;
    });
    document.querySelectorAll(".phrase-audio audio").forEach(function (node) {
      node.loop = false;
      node.playbackRate = 1;
      node.setAttribute("data-role", "phrase-tts");
    });
    fitAdaptiveCard(document);
  }
  setTimeout(refreshResponsiveCard, 80);
  setTimeout(scheduleResponsiveFit, 320);
  window.addEventListener("resize", scheduleResponsiveFit);
  if (window.ResizeObserver) {
    var observedWrap = document.querySelector(".wrap");
    if (observedWrap) new ResizeObserver(scheduleResponsiveFit).observe(observedWrap);
  }
  function resetPhraseSpeaker(button) {
    if (!button) return;
    button.classList.remove("is-playing");
  }
  function playPhraseTts(button) {
    var root = button && button.closest ? button.closest(".focus-line") : null;
    var audio = root ? root.querySelector(".phrase-audio audio") : null;
    if (!audio) return;
    if (!audio.paused) {
      audio.pause();
      audio.currentTime = 0;
      resetPhraseSpeaker(button);
      return;
    }
    document.querySelectorAll(".phrase-audio audio").forEach(function (node) {
      if (node !== audio) {
        node.pause();
        node.currentTime = 0;
      }
    });
    document.querySelectorAll(".phrase-speaker.is-playing").forEach(resetPhraseSpeaker);
    button.classList.add("is-playing");
    audio.loop = false;
    audio.playbackRate = 1;
    audio.currentTime = 0;
    audio.onended = function () { resetPhraseSpeaker(button); };
    audio.onpause = function () {
      if (audio.currentTime === 0 || audio.ended) resetPhraseSpeaker(button);
    };
    var playResult = audio.play();
    if (playResult && playResult.catch) {
      playResult.catch(function () { resetPhraseSpeaker(button); });
    }
  }
  function resetReplayButton(button) {
    if (!button) return;
    button.classList.remove("is-playing");
  }
  function playReplayAudio(button) {
    var root = button && button.closest ? button.closest(".replay-audio-control") : null;
    var audio = root ? root.querySelector(".replay-audio-source audio") : null;
    if (!audio) return;
    if (!audio.paused) {
      audio.pause();
      audio.currentTime = 0;
      resetReplayButton(button);
      return;
    }
    document.querySelectorAll(".replay-audio-source audio").forEach(function (node) {
      if (node !== audio) {
        node.pause();
        node.currentTime = 0;
      }
    });
    document.querySelectorAll(".replay-audio-button.is-playing").forEach(resetReplayButton);
    button.classList.add("is-playing");
    audio.loop = true;
    audio.playbackRate = 0.75;
    audio.currentTime = 0;
    audio.onpause = function () {
      if (audio.currentTime === 0 || audio.ended) resetReplayButton(button);
    };
    var playResult = audio.play();
    if (playResult && playResult.catch) {
      playResult.catch(function () { resetReplayButton(button); });
    }
  }
</script>
"""


DICTIONARY_FRONT_TEMPLATE = FRONT_TEMPLATE
DICTIONARY_BACK_TEMPLATE = BACK_TEMPLATE
MINIMAL_FRONT_TEMPLATE = FRONT_TEMPLATE
MINIMAL_BACK_TEMPLATE = BACK_TEMPLATE


# Final V10 visual layer. It keeps the established APKG field names, but routes
# the same fields through source-aware layouts instead of one oversized shell.
CARD_CSS = """
.card {
  margin: 0;
  min-height: 100%;
  padding: clamp(10px, 3vw, 18px);
  background: #f5f5f7;
  color: #1d1d1f;
  font-family: "SF Pro Text", "Segoe UI", "Noto Sans SC", "Microsoft YaHei UI", sans-serif;
  line-height: 1.5;
  text-align: left;
  letter-spacing: 0;
  overflow-x: hidden;
  overflow-y: auto;
}
* { box-sizing: border-box; }
html,
body,
#qa {
  width: 100% !important;
  min-height: 100% !important;
  height: auto !important;
  margin: 0 !important;
  overflow-x: hidden !important;
  overflow-y: auto !important;
}
.review-card {
  width: min(900px, calc(100vw - 18px));
  margin: 0 auto;
  border: 1px solid rgba(60, 60, 67, 0.13);
  border-radius: 16px;
  background: #ffffff;
  box-shadow: 0 16px 42px rgba(0, 0, 0, 0.08);
  overflow: hidden;
}
.card-section {
  padding: clamp(18px, 4vw, 34px);
  border-top: 1px solid rgba(60, 60, 67, 0.12);
}
.card-section:first-child { border-top: 0; }
.meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  justify-content: space-between;
  color: #6e6e73;
  font-size: clamp(12px, 2.8vw, 14px);
  font-weight: 800;
}
.tag {
  display: inline-flex;
  align-items: center;
  min-height: 26px;
  padding: 4px 10px;
  border: 1px solid rgba(0, 122, 255, 0.18);
  border-radius: 999px;
  background: rgba(0, 122, 255, 0.08);
  color: #0057d8;
}
.layout-cloze .tag {
  border-color: rgba(255, 159, 10, 0.26);
  background: rgba(255, 159, 10, 0.10);
  color: #9a5b00;
}
.layout-listening .media-strip {
  max-height: none;
}
.prompt {
  margin: clamp(18px, 4vw, 32px) 0 0;
  color: #111114;
  font-size: clamp(28px, 7vw, 46px);
  line-height: 1.14;
  font-weight: 900;
  overflow-wrap: anywhere;
}
.cue {
  margin-top: 16px;
  padding: 14px 16px;
  border-left: 4px solid #007aff;
  border-radius: 10px;
  background: rgba(0, 122, 255, 0.08);
  color: #242426;
  font-size: clamp(17px, 4vw, 23px);
  font-weight: 720;
  overflow-wrap: anywhere;
}
.answer {
  margin: clamp(16px, 4vw, 26px) 0 0;
  color: #0057d8;
  font-size: clamp(31px, 8vw, 54px);
  line-height: 1.08;
  font-weight: 950;
  overflow-wrap: anywhere;
}
.source {
  margin-top: 12px;
  color: #1d1d1f;
  font-size: clamp(20px, 5vw, 34px);
  line-height: 1.22;
  font-weight: 850;
  overflow-wrap: anywhere;
}
.subtle {
  margin-top: 8px;
  color: #6e6e73;
  font-size: clamp(13px, 3vw, 16px);
  font-weight: 760;
}
.media-panel {
  padding: clamp(8px, 2.4vw, 14px);
  background: #111114;
}
.media-panel video {
  display: block;
  width: 100%;
  max-height: min(54vh, 520px);
  border-radius: 10px;
  background: #000;
  object-fit: contain;
}
.media-strip {
  margin-top: 16px;
  padding: 10px;
  border-radius: 12px;
  background: #111114;
}
.media-strip video {
  display: block;
  width: 100%;
  max-height: min(28vh, 240px);
  border-radius: 8px;
  background: #000;
  object-fit: contain;
}
.audio-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  margin-top: 16px;
}
.audio-item {
  display: grid;
  grid-template-columns: auto minmax(180px, 1fr);
  gap: 8px;
  align-items: center;
  max-width: 100%;
  padding: 8px 10px;
  border: 1px solid rgba(60, 60, 67, 0.12);
  border-radius: 999px;
  background: #f5f5f7;
}
.audio-item span {
  color: #6e6e73;
  font-size: 12px;
  font-weight: 850;
}
audio {
  width: min(360px, 64vw);
  min-height: 32px;
  color-scheme: light;
}
.answer-line {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
}
.phrase-audio {
  display: inline-flex;
  align-items: center;
}
.phrase-audio audio {
  width: 160px;
}
.block-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
}
.info-block {
  padding: 15px 16px;
  border: 1px solid rgba(60, 60, 67, 0.12);
  border-radius: 12px;
  background: #fbfbfd;
}
.info-block strong {
  display: block;
  margin-bottom: 7px;
  color: #6e6e73;
  font-size: 13px;
  font-weight: 880;
}
.info-block p {
  margin: 0;
  color: #242426;
  font-size: clamp(15px, 3.6vw, 19px);
  line-height: 1.46;
  overflow-wrap: anywhere;
}
.info-block p + p { margin-top: 9px; }
.english-note {
  color: #0057d8 !important;
  font-weight: 780;
}
.warning-block {
  border-color: rgba(154, 106, 34, 0.22);
  background: #fffaf0;
}
.knowledge-card .answer {
  color: #1d1d1f;
}
.knowledge-card .tag {
  border-color: rgba(52, 199, 89, 0.22);
  background: rgba(52, 199, 89, 0.1);
  color: #166534;
}
.reading-card .tag {
  border-color: rgba(88, 86, 214, 0.22);
  background: rgba(88, 86, 214, 0.1);
  color: #4338ca;
}
@media (max-width: 560px) {
  .card { padding: 6px; }
  .review-card { width: calc(100vw - 10px); border-radius: 12px; }
  .card-section { padding: 17px; }
  .prompt { font-size: clamp(26px, 8vw, 36px); }
  .answer { font-size: clamp(29px, 9vw, 42px); }
  .audio-item {
    width: 100%;
    grid-template-columns: 1fr;
    border-radius: 12px;
  }
  audio { width: 100%; }
  .block-grid { grid-template-columns: 1fr; }
}
"""


LANGUAGE_FRONT_TEMPLATE = """
<div class="review-card language-card front layout-{{CardLayout}}">
  {{#IsListening}}
  {{#Video}}<div class="media-panel">{{Video}}</div>{{/Video}}
  <section class="card-section">
    <div class="meta"><span class="tag">{{CardType}}</span><span>{{SourceTime}}</span></div>
    <div class="subtle">{{FrontKicker}}</div>
    <h1 class="prompt">{{FrontPrompt}}</h1>
    {{#Audio}}<div class="audio-actions"><div class="audio-item"><span>原声</span>{{Audio}}</div></div>{{/Audio}}
  </section>
  {{/IsListening}}
  {{^IsListening}}
  <section class="card-section">
    <div class="meta"><span class="tag">{{CardType}}</span><span>{{SourceTime}}</span></div>
    <div class="subtle">{{FrontKicker}}</div>
    <h1 class="prompt">{{FrontPrompt}}</h1>
    {{#FrontContent}}<div class="cue">{{FrontContent}}</div>{{/FrontContent}}
    {{#Audio}}<div class="audio-actions"><div class="audio-item"><span>原声</span>{{Audio}}</div></div>{{/Audio}}
    {{#Video}}<div class="media-strip">{{Video}}</div>{{/Video}}
  </section>
  {{/IsListening}}
</div>
"""


LANGUAGE_BACK_TEMPLATE = """
<div class="review-card language-card back layout-{{CardLayout}}">
  <section class="card-section">
    <div class="meta"><span class="tag">{{CardType}}</span><span>{{Difficulty}}</span></div>
    <strong class="subtle">核心答案</strong>
    {{#Answer}}<div class="answer-line"><h1 class="answer">{{Answer}}</h1>{{#PhraseTtsAudio}}<span class="phrase-audio">{{PhraseTtsAudio}}</span>{{/PhraseTtsAudio}}</div>{{/Answer}}
  </section>
  <section class="card-section">
    <strong class="subtle">{{SourceLabel}}</strong>
    <div class="source">{{English}}</div>
    <div class="subtle">{{SourceTime}}</div>
    {{#Cloze}}<div class="cue">{{Cloze}}</div>{{/Cloze}}
    <div class="audio-actions">
      {{#Audio}}<div class="audio-item"><span>原声</span>{{Audio}}</div>{{/Audio}}
      {{#TtsAudio}}<div class="audio-item"><span>AI 朗读</span>{{TtsAudio}}</div>{{/TtsAudio}}
    </div>
    {{#Video}}<div class="media-strip">{{Video}}</div>{{/Video}}
  </section>
  <section class="card-section">
    <div class="block-grid">
      <div class="info-block"><strong>{{UnderstandLabel}}</strong><p>{{Definition}}</p>{{#ChineseFeel}}<p>{{ChineseFeel}}</p>{{/ChineseFeel}}</div>
      <div class="info-block"><strong>{{UseLabel}}</strong><p class="english-note">{{Collocations}}</p>{{#Context}}<p>{{Context}}</p>{{/Context}}</div>
      {{#TeacherNote}}<div class="info-block warning-block"><strong>老师提醒</strong><p>{{TeacherNote}}</p>{{#Why}}<p>{{Why}}</p>{{/Why}}</div>{{/TeacherNote}}
      {{#Example}}<div class="info-block"><strong>再造一句</strong><p class="english-note">{{Example}}</p></div>{{/Example}}
    </div>
  </section>
</div>
"""


KNOWLEDGE_FRONT_TEMPLATE = """
<div class="review-card knowledge-card front layout-{{CardLayout}}">
  <section class="card-section">
    <div class="meta"><span class="tag">{{CardType}}</span><span>{{SourceTime}}</span></div>
    <div class="subtle">{{FrontKicker}}</div>
    <h1 class="prompt">{{FrontPrompt}}</h1>
    {{#FrontContent}}<div class="cue">{{FrontContent}}</div>{{/FrontContent}}
  </section>
</div>
"""


KNOWLEDGE_BACK_TEMPLATE = """
<div class="review-card knowledge-card back layout-{{CardLayout}}">
  <section class="card-section">
    <div class="meta"><span class="tag">{{CardType}}</span><span>{{Difficulty}}</span></div>
    <strong class="subtle">核心答案</strong>
    <h1 class="answer">{{Answer}}</h1>
  </section>
  <section class="card-section">
    <strong class="subtle">{{SourceLabel}}</strong>
    <div class="source">{{English}}</div>
    <div class="subtle">{{SourceTime}}</div>
  </section>
  <section class="card-section">
    <div class="block-grid">
      <div class="info-block"><strong>{{UnderstandLabel}}</strong><p>{{Definition}}</p>{{#ChineseFeel}}<p>{{ChineseFeel}}</p>{{/ChineseFeel}}</div>
      {{#Example}}<div class="info-block"><strong>例子</strong><p>{{Example}}</p></div>{{/Example}}
      <div class="info-block warning-block"><strong>边界 / 易混点</strong>{{#TeacherNote}}<p>{{TeacherNote}}</p>{{/TeacherNote}}{{#Why}}<p>{{Why}}</p>{{/Why}}{{#Collocations}}<p>{{Collocations}}</p>{{/Collocations}}</div>
    </div>
  </section>
</div>
"""


READING_FRONT_TEMPLATE = """
<div class="review-card reading-card front layout-{{CardLayout}}">
  <section class="card-section">
    <div class="meta"><span class="tag">{{CardType}}</span><span>{{SourceTime}}</span></div>
    <div class="subtle">{{FrontKicker}}</div>
    <h1 class="prompt">{{FrontPrompt}}</h1>
    {{#FrontContent}}<div class="cue">{{FrontContent}}</div>{{/FrontContent}}
  </section>
</div>
"""


READING_BACK_TEMPLATE = """
<div class="review-card reading-card back layout-{{CardLayout}}">
  <section class="card-section">
    <div class="meta"><span class="tag">{{CardType}}</span><span>{{Difficulty}}</span></div>
    <strong class="subtle">核心答案</strong>
    <h1 class="answer">{{Answer}}</h1>
  </section>
  <section class="card-section">
    <strong class="subtle">{{SourceLabel}}</strong>
    <div class="source">{{English}}</div>
    <div class="subtle">{{SourceTime}}</div>
  </section>
  <section class="card-section">
    <div class="block-grid">
      <div class="info-block"><strong>{{UnderstandLabel}}</strong><p>{{Definition}}</p>{{#ChineseFeel}}<p>{{ChineseFeel}}</p>{{/ChineseFeel}}</div>
      <div class="info-block"><strong>{{UseLabel}}</strong><p class="english-note">{{Collocations}}</p>{{#Context}}<p>{{Context}}</p>{{/Context}}</div>
      {{#TeacherNote}}<div class="info-block warning-block"><strong>边界 / 易错</strong><p>{{TeacherNote}}</p>{{#Why}}<p>{{Why}}</p>{{/Why}}</div>{{/TeacherNote}}
      {{#Example}}<div class="info-block"><strong>再造一句</strong><p class="english-note">{{Example}}</p></div>{{/Example}}
    </div>
  </section>
</div>
"""


MINIMAL_FRONT_TEMPLATE = """
<div class="review-card minimal-card front layout-{{CardLayout}}">
  <section class="card-section">
    <div class="meta"><span class="tag">{{CardType}}</span><span>{{SourceTime}}</span></div>
    <div class="subtle">{{FrontKicker}}</div>
    <h1 class="prompt">{{FrontPrompt}}</h1>
    {{#FrontContent}}<div class="cue">{{FrontContent}}</div>{{/FrontContent}}
  </section>
</div>
"""


MINIMAL_BACK_TEMPLATE = """
<div class="review-card minimal-card back layout-{{CardLayout}}">
  <section class="card-section">
    <div class="meta"><span class="tag">{{CardType}}</span><span>{{Difficulty}}</span></div>
    <h1 class="answer">{{Answer}}</h1>
    <div class="source">{{English}}</div>
  </section>
  <section class="card-section">
    <div class="block-grid">
      <div class="info-block"><strong>怎么理解</strong><p>{{Definition}}</p></div>
      <div class="info-block"><strong>怎么用 / 怎么记</strong><p>{{Collocations}}</p>{{#Example}}<p class="english-note">{{Example}}</p>{{/Example}}</div>
    </div>
  </section>
</div>
"""


CARD_CSS_V11 = """
.card {
  margin: 0;
  min-height: 100%;
  padding: clamp(10px, 3vw, 24px);
  background: #f5f5f7;
  color: #1d1d1f;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans SC", "Microsoft YaHei UI", sans-serif;
  line-height: 1.5;
  text-align: left;
  letter-spacing: 0;
  overflow-x: hidden;
  overflow-y: auto;
}
* { box-sizing: border-box; }
html,
body,
#qa {
  width: 100% !important;
  min-height: 100% !important;
  height: auto !important;
  margin: 0 !important;
  overflow-x: hidden !important;
  overflow-y: auto !important;
}
.v11-card {
  width: min(1120px, calc(100vw - 18px));
  margin: 0 auto;
  padding: clamp(24px, 4vw, 42px);
  border: 1px solid rgba(60, 60, 67, 0.12);
  border-radius: clamp(22px, 3vw, 30px);
  background: #ffffff;
  box-shadow: 0 22px 70px rgba(0, 0, 0, 0.10);
  overflow: hidden;
}
.v11-top {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
}
.v11-pill,
.v11-difficulty {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 34px;
  padding: 7px 14px;
  border-radius: 999px;
  font-size: clamp(14px, 2.8vw, 18px);
  font-weight: 850;
}
.v11-pill {
  background: rgba(0, 122, 255, 0.10);
  color: #0066df;
}
.v11-difficulty {
  background: rgba(88, 86, 214, 0.10);
  color: #5a38c7;
}
.v11-time {
  color: #6e6e73;
  font-size: clamp(14px, 2.6vw, 18px);
  font-weight: 650;
}
.v11-front-copy {
  margin-top: clamp(20px, 4vw, 30px);
}
.v11-front-copy h1 {
  margin: 0;
  color: #111114;
  font-size: clamp(38px, 6vw, 68px);
  line-height: 1.08;
  font-weight: 900;
  overflow-wrap: break-word;
  word-break: normal;
}
.v11-front-copy p {
  margin: 10px 0 0;
  color: #6e6e73;
  font-size: clamp(18px, 3vw, 25px);
  font-weight: 520;
}
.v11-video-stage {
  position: relative;
  margin-top: clamp(24px, 4vw, 34px);
  border-radius: clamp(18px, 2.5vw, 24px);
  background: #050506;
  overflow: hidden;
  cursor: pointer;
}
.v11-video-stage video {
  display: block;
  width: 100%;
  aspect-ratio: 16 / 9;
  max-height: min(58vh, 560px);
  background: #000;
  object-fit: cover;
}
.v11-back .v11-video-stage {
  margin-top: 0;
}
.v11-back .v11-video-stage video {
  max-height: 250px;
}
.v11-video-toggle {
  position: absolute;
  left: 50%;
  top: 50%;
  display: grid;
  width: clamp(58px, 10vw, 82px);
  height: clamp(58px, 10vw, 82px);
  place-items: center;
  border-radius: 999px;
  background: rgba(20, 20, 22, 0.44);
  color: #ffffff;
  font-size: clamp(28px, 5vw, 40px);
  font-weight: 900;
  transform: translate(-50%, -50%);
  opacity: 0;
  transition: opacity 160ms ease, background 160ms ease;
  pointer-events: none;
}
.v11-video-stage:hover .v11-video-toggle,
.v11-video-stage.is-sound-on .v11-video-toggle,
.v11-video-stage.is-paused .v11-video-toggle {
  opacity: 1;
}
.v11-video-stage.is-paused .v11-video-toggle {
  background: rgba(20, 20, 22, 0.62);
}
.v11-video-time {
  position: absolute;
  right: 14px;
  bottom: 12px;
  padding: 4px 9px;
  border-radius: 999px;
  background: rgba(0, 0, 0, 0.48);
  color: #ffffff;
  font-size: 13px;
  font-weight: 760;
}
.v11-video-cue {
  position: absolute;
  left: 14px;
  bottom: 12px;
  padding: 5px 10px;
  border-radius: 999px;
  background: rgba(0, 0, 0, 0.5);
  color: #ffffff;
  font-size: 13px;
  font-weight: 760;
}
.v11-video-stage.is-sound-on .v11-video-cue {
  background: rgba(0, 102, 204, 0.86);
}
.v11-sound-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: clamp(12px, 3vw, 24px);
  margin-top: clamp(22px, 4vw, 32px);
}
.v11-sound-actions.is-left {
  justify-content: flex-start;
  margin-top: 18px;
}
.v11-sound-button,
.v11-speaker {
  border: 1px solid rgba(60, 60, 67, 0.15);
  background: #ffffff;
  color: #1d1d1f;
  box-shadow: 0 1px 1px rgba(0, 0, 0, 0.03);
  cursor: pointer;
}
.v11-sound-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  min-width: min(220px, 40vw);
  min-height: 58px;
  padding: 10px 24px;
  border-radius: 999px;
  font-size: clamp(18px, 3vw, 24px);
  font-weight: 820;
}
.v11-sound-actions.is-left .v11-sound-button {
  min-width: 150px;
  min-height: 48px;
  font-size: 18px;
}
.v11-play {
  color: #0066df;
  font-size: 1.1em;
  line-height: 1;
}
.v11-media-source,
.v11-media-source audio {
  display: none !important;
}
.v11-answer-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.18fr) minmax(280px, 0.82fr);
  gap: clamp(24px, 4vw, 42px);
  align-items: start;
  margin-top: clamp(28px, 5vw, 42px);
}
.v11-label {
  margin-top: 14px;
  color: #6e6e73;
  font-size: clamp(16px, 2.8vw, 22px);
  font-weight: 680;
}
.v11-phrase-line {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
  margin-top: 4px;
}
.v11-answer-title {
  margin: 0;
  color: #050506;
  font-size: clamp(40px, 6.2vw, 72px);
  line-height: 1.06;
  font-weight: 910;
  overflow-wrap: break-word;
  word-break: normal;
}
.v11-answer-title.is-long {
  font-size: clamp(34px, 5.1vw, 58px);
  line-height: 1.1;
}
.v11-answer-title.is-very-long {
  font-size: clamp(30px, 4.4vw, 48px);
  line-height: 1.14;
}
.v11-speaker {
  display: inline-grid;
  width: 42px;
  height: 42px;
  place-items: center;
  border-radius: 14px;
  color: #0066df;
  font-size: 20px;
  font-weight: 900;
}
.v11-chinese-core {
  margin: 8px 0 0;
  color: #0066df;
  font-size: clamp(20px, 3.4vw, 27px);
  line-height: 1.3;
  font-weight: 820;
  overflow-wrap: break-word;
}
.v11-answer-note {
  margin: 8px 0 0;
  color: #6e6e73;
  font-size: clamp(15px, 2.7vw, 18px);
  line-height: 1.45;
  font-weight: 650;
  overflow-wrap: break-word;
}
.v11-divider {
  margin: clamp(20px, 4vw, 28px) 0;
  border: 0;
  border-top: 1px solid rgba(60, 60, 67, 0.14);
}
.v11-source {
  margin: 8px 0 0;
  color: #111114;
  font-size: clamp(23px, 3.9vw, 34px);
  line-height: 1.22;
  font-weight: 850;
  overflow-wrap: break-word;
}
.v11-source-translation {
  margin: 10px 0 0;
  color: #5f626b;
  font-size: clamp(18px, 3.2vw, 24px);
  line-height: 1.38;
  font-weight: 650;
  overflow-wrap: break-word;
}
.v11-info-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: clamp(14px, 2.4vw, 24px);
  margin-top: clamp(32px, 5vw, 48px);
}
.v11-info-block {
  min-height: 150px;
  padding: clamp(18px, 3vw, 26px);
  border: 1px solid rgba(60, 60, 67, 0.13);
  border-radius: 20px;
  background: #ffffff;
  box-shadow: 0 1px 0 rgba(0, 0, 0, 0.03);
}
.v11-info-head {
  display: flex;
  gap: 12px;
  align-items: center;
  margin-bottom: 14px;
  color: #111114;
  font-size: clamp(18px, 3vw, 22px);
  font-weight: 880;
}
.v11-icon {
  display: inline-grid;
  width: 42px;
  height: 42px;
  place-items: center;
  border-radius: 999px;
  background: rgba(0, 122, 255, 0.10);
  color: #0066df;
}
.v11-info-block:nth-child(2) .v11-icon {
  background: rgba(255, 149, 0, 0.14);
  color: #9d5b00;
}
.v11-info-block:nth-child(3) .v11-icon {
  background: rgba(52, 199, 89, 0.13);
  color: #16833a;
}
.v11-info-block p {
  margin: 0;
  color: #5f626b;
  font-size: clamp(16px, 3vw, 20px);
  line-height: 1.55;
  overflow-wrap: break-word;
  white-space: pre-line;
}
.v11-info-block p + p {
  margin-top: 8px;
}
@media (max-width: 760px) {
  .card { padding: 8px; }
  .v11-card {
    width: calc(100vw - 16px);
    padding: clamp(18px, 5vw, 24px);
    border-radius: 22px;
  }
  .v11-front-copy h1 {
    font-size: clamp(38px, 11vw, 58px);
  }
  .v11-front-copy p {
    font-size: clamp(18px, 5vw, 23px);
  }
  .v11-video-stage video {
    max-height: none;
    aspect-ratio: 4 / 3;
  }
  .v11-sound-actions {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
  }
  .v11-sound-actions.is-left {
    display: flex;
    justify-content: flex-start;
  }
  .v11-sound-button {
    min-width: 0;
    width: 100%;
    min-height: 58px;
    padding: 9px 14px;
  }
  .v11-sound-actions.is-left .v11-sound-button {
    width: auto;
    min-width: 112px;
  }
  .v11-answer-layout {
    display: block;
  }
  .v11-back .v11-video-stage {
    margin-top: 26px;
  }
  .v11-back .v11-video-stage video {
    max-height: none;
    aspect-ratio: 16 / 9;
  }
  .v11-answer-title {
    font-size: clamp(34px, 10vw, 48px);
    line-height: 1.08;
  }
  .v11-answer-title.is-long {
    font-size: clamp(29px, 8.2vw, 38px);
    line-height: 1.12;
  }
  .v11-answer-title.is-very-long {
    font-size: clamp(24px, 7vw, 32px);
    line-height: 1.18;
  }
  .v11-chinese-core {
    font-size: clamp(18px, 5.2vw, 23px);
  }
  .v11-source {
    font-size: clamp(22px, 6vw, 30px);
  }
  .v11-info-grid {
    grid-template-columns: 1fr;
    gap: 14px;
    margin-top: 26px;
  }
  .v11-info-block {
    min-height: 0;
  }
}
"""


V11_CARD_SCRIPT = """
<script>
(function() {
  function rootFor(node) {
    return node && node.closest ? (node.closest(".v11-card") || document) : document;
  }

  window.playV11Audio = function(button, selector) {
    var root = rootFor(button);
    var audio = root.querySelector(selector + " audio");
    if (!audio) return;
    document.querySelectorAll("audio").forEach(function(node) {
      if (node !== audio) {
        node.pause();
        try { node.currentTime = 0; } catch (error) {}
      }
    });
    document.querySelectorAll(".v11-video-stage video").forEach(function(node) {
      node.pause();
      node.muted = false;
      var stage = node.closest(".v11-video-stage");
      if (stage) {
        setV11VideoState(stage, "ready");
      }
    });
    try { audio.currentTime = 0; } catch (error) {}
    audio.playbackRate = 1;
    var playResult = audio.play();
    if (playResult && playResult.catch) playResult.catch(function() {});
  };

  function setV11VideoState(stage, state) {
    var cue = stage.querySelector(".v11-video-cue");
    var toggle = stage.querySelector(".v11-video-toggle");
    stage.classList.toggle("is-muted-preview", state === "ready");
    stage.classList.toggle("is-sound-on", state === "sound");
    stage.classList.toggle("is-paused", state === "paused");
    if (cue) {
      cue.textContent = state === "sound" ? "复读循环中" : (state === "paused" ? "已暂停" : "点画面开始复读");
    }
    if (toggle) {
      toggle.textContent = state === "sound" ? "II" : "▶";
    }
  }

  function pauseOtherMedia(activeVideo) {
    document.querySelectorAll("audio").forEach(function(node) {
      node.pause();
      try { node.currentTime = 0; } catch (error) {}
    });
    document.querySelectorAll(".v11-video-stage video").forEach(function(node) {
      if (node !== activeVideo) {
        node.pause();
        node.muted = false;
        var stage = node.closest(".v11-video-stage");
        if (stage) {
          setV11VideoState(stage, "ready");
        }
      }
    });
  }

  window.toggleV11Video = function(stage) {
    if (!stage) return;
    var video = stage.querySelector("video");
    if (!video) return;
    if (video.paused) {
      pauseOtherMedia(video);
      if (video.currentTime >= Math.max(0, video.duration - 0.1)) {
        try { video.currentTime = 0; } catch (error) {}
      }
      video.loop = true;
      video.muted = false;
      video.volume = 1;
      var playResult = video.play();
      if (playResult && playResult.catch) playResult.catch(function() {});
      setV11VideoState(stage, "sound");
    } else {
      video.pause();
      setV11VideoState(stage, "paused");
    }
  };

  function setupV11Videos() {
    document.querySelectorAll(".v11-video-stage").forEach(function(stage) {
      var video = stage.querySelector("video");
      if (!video) return;
      video.loop = true;
      video.muted = false;
      video.playsInline = true;
      setV11VideoState(stage, "ready");
    });
  }

  function setupV11TextSizing() {
    document.querySelectorAll(".v11-answer-title").forEach(function(title) {
      var text = (title.textContent || "").trim();
      var words = text.split(/\\s+/).filter(Boolean).length;
      if (text.length >= 38 || words >= 6) {
        title.classList.add("is-very-long");
      } else if (text.length >= 24 || words >= 4) {
        title.classList.add("is-long");
      }
    });
  }

  function setupV11Card() {
    setupV11Videos();
    setupV11TextSizing();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", setupV11Card);
  } else {
    setupV11Card();
  }
})();
</script>
"""


LANGUAGE_FRONT_TEMPLATE_V11 = """
<div class="v11-card v11-front layout-{{CardLayout}}">
  <div class="v11-top">
    <span class="v11-pill">▮ 复读卡</span>
    <span class="v11-time">{{SourceTime}}</span>
  </div>
  <section class="v11-front-copy">
    <h1>{{FrontPrompt}}</h1>
    {{#FrontContent}}<p>{{FrontContent}}</p>{{/FrontContent}}
  </section>
  {{#Video}}
  <section class="v11-video-stage" onclick="toggleV11Video(this)">
    {{Video}}
    <span class="v11-video-toggle">▶</span>
    <span class="v11-video-cue">点画面开始复读</span>
  </section>
  {{/Video}}
  <section class="v11-sound-actions">
    {{#Audio}}<span class="v11-media-source audio-original">{{Audio}}</span><button class="v11-sound-button" onclick="playV11Audio(this, '.audio-original')"><span class="v11-play">▶</span><span>只听原声</span></button>{{/Audio}}
    {{#TtsAudio}}<span class="v11-media-source audio-slow">{{TtsAudio}}</span><button class="v11-sound-button" onclick="playV11Audio(this, '.audio-slow')"><span class="v11-play">▶</span><span>慢读跟读</span></button>{{/TtsAudio}}
  </section>
</div>
""" + V11_CARD_SCRIPT


LANGUAGE_BACK_TEMPLATE_V11 = """
<div class="v11-card v11-back layout-{{CardLayout}}">
  <div class="v11-top">
    <span class="v11-pill">▮ 复读卡</span>
    {{#Difficulty}}<span class="v11-difficulty">{{Difficulty}}</span>{{/Difficulty}}
  </div>
  <section class="v11-answer-layout">
    <div class="v11-answer-main">
      <div class="v11-time">{{SourceTime}}</div>
      <div class="v11-label">表达 / 词义</div>
      <div class="v11-phrase-line">
        <h1 class="v11-answer-title">{{Answer}}</h1>
        {{#PhraseTtsAudio}}<span class="v11-media-source audio-phrase">{{PhraseTtsAudio}}</span><button class="v11-speaker" onclick="playV11Audio(this, '.audio-phrase')" aria-label="播放表达发音">▶</button>{{/PhraseTtsAudio}}
      </div>
      {{#Chinese}}<p class="v11-chinese-core">{{Chinese}}</p>{{/Chinese}}
      {{#ChineseFeel}}<p class="v11-answer-note">{{ChineseFeel}}</p>{{/ChineseFeel}}
      <hr class="v11-divider">
      <div class="v11-label">原句</div>
      <p class="v11-source">{{English}}</p>
      {{#Context}}<p class="v11-source-translation">{{Context}}</p>{{/Context}}
      <div class="v11-sound-actions is-left">
        {{#Audio}}<span class="v11-media-source audio-original">{{Audio}}</span><button class="v11-sound-button" onclick="playV11Audio(this, '.audio-original')"><span class="v11-play">▶</span><span>只听原声</span></button>{{/Audio}}
        {{#TtsAudio}}<span class="v11-media-source audio-slow">{{TtsAudio}}</span><button class="v11-sound-button" onclick="playV11Audio(this, '.audio-slow')"><span class="v11-play">▶</span><span>慢读跟读</span></button>{{/TtsAudio}}
      </div>
    </div>
    {{#Video}}
    <div class="v11-video-stage" onclick="toggleV11Video(this)">
      {{Video}}
      <span class="v11-video-toggle">▶</span>
      <span class="v11-video-cue">点画面开始复读</span>
      <span class="v11-video-time">{{SourceTime}}</span>
    </div>
    {{/Video}}
  </section>
  <section class="v11-info-grid">
    {{#Definition}}<div class="v11-info-block"><div class="v11-info-head"><span class="v11-icon">?</span><strong>怎么用</strong></div><p>{{Definition}}</p></div>{{/Definition}}
    {{#TeacherNote}}<div class="v11-info-block"><div class="v11-info-head"><span class="v11-icon">!</span><strong>别误用</strong></div><p>{{TeacherNote}}</p></div>{{/TeacherNote}}
    {{#Collocations}}<div class="v11-info-block"><div class="v11-info-head"><span class="v11-icon">↔</span><strong>自己造句</strong></div><p>{{Collocations}}</p></div>{{/Collocations}}
  </section>
</div>
""" + V11_CARD_SCRIPT


DICTIONARY_FRONT_TEMPLATE = MINIMAL_FRONT_TEMPLATE
DICTIONARY_BACK_TEMPLATE = READING_BACK_TEMPLATE
FRONT_TEMPLATE = LANGUAGE_FRONT_TEMPLATE
BACK_TEMPLATE = LANGUAGE_BACK_TEMPLATE


def anki_template_family(template_id: str, deck_kind_code: str) -> str:
    template_id = template_id if template_id in {"immersive_v11", "immersive", "dictionary", "minimal"} else "immersive_v11"
    deck_kind_code = str(deck_kind_code or "")
    if deck_kind_code == "document_knowledge":
        return "document-knowledge"
    if deck_kind_code == "document_reading":
        return "document-reading"
    if template_id == "immersive_v11":
        return "language-immersive-v11"
    return f"language-{template_id}"


def anki_template_assets(template_id: str, deck_kind_code: str = "video_language") -> tuple[str, str, str, str]:
    template_id = template_id if template_id in {"immersive_v11", "immersive", "dictionary", "minimal"} else "immersive_v11"
    if deck_kind_code == "document_knowledge":
        return "文档知识 V10", CARD_CSS, KNOWLEDGE_FRONT_TEMPLATE, KNOWLEDGE_BACK_TEMPLATE
    if deck_kind_code == "document_reading":
        return "文档精读 V10", CARD_CSS, READING_FRONT_TEMPLATE, READING_BACK_TEMPLATE
    if template_id == "immersive_v11":
        return "沉浸复读 V11", CARD_CSS_V11, LANGUAGE_FRONT_TEMPLATE_V11, LANGUAGE_BACK_TEMPLATE_V11
    if template_id == "dictionary":
        return "词典解释 V10", CARD_CSS, DICTIONARY_FRONT_TEMPLATE, DICTIONARY_BACK_TEMPLATE
    if template_id == "minimal":
        return "极简复习 V10", CARD_CSS, MINIMAL_FRONT_TEMPLATE, MINIMAL_BACK_TEMPLATE
    return "视频语言 V10", CARD_CSS, LANGUAGE_FRONT_TEMPLATE, LANGUAGE_BACK_TEMPLATE


def anki_template_version(template_id: str, deck_kind_code: str = "video_language") -> str:
    template_id = template_id if template_id in {"immersive_v11", "immersive", "dictionary", "minimal"} else "immersive_v11"
    if deck_kind_code not in {"video_language", "subtitle_language"}:
        return "V10"
    return "V11" if template_id == "immersive_v11" else "V10"


def safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "media"


def project_media_prefix(project: dict[str, Any], export_run_id: int | None = None) -> str:
    base = safe_filename(str(project.get("title") or project.get("id") or "deck"))[:72]
    seed = "|".join(
        str(project.get(key) or "")
        for key in ("id", "title", "source_url", "created_at")
    )
    if export_run_id is not None:
        seed = f"{seed}|{export_run_id}"
    return f"{base}_{stable_id(seed, 0)}"


def anki_video_html(
    webm_filename: str,
    mp4_filename: str = "",
    poster_filename: str = "",
    *,
    controls: bool = True,
    muted: bool = False,
) -> str:
    if not webm_filename and not mp4_filename:
        return ""
    poster_attr = ""
    poster_preload = ""
    if poster_filename:
        safe_poster = html.escape(poster_filename, quote=True)
        poster_attr = f' poster="{safe_poster}"'
        poster_preload = f'<img src="{safe_poster}" alt="" style="display:none">'
    sources: list[str] = []
    if mp4_filename:
        safe_mp4 = html.escape(mp4_filename, quote=True)
        sources.append(f'<source src="{safe_mp4}" type="video/mp4">')
    if webm_filename:
        safe_webm = html.escape(webm_filename, quote=True)
        sources.append(f'<source src="{safe_webm}" type="video/webm">')
    fallback = '<span>视频无法播放：当前 Anki 客户端不支持这个视频格式。</span>'
    attrs = ["loop", "playsinline", 'preload="metadata"']
    if controls:
        attrs.append("controls")
    if muted:
        attrs.append("muted")
    return f'{poster_preload}<video {" ".join(attrs)}{poster_attr}>{"".join(sources)}{fallback}</video>'


def anki_audio_html(filename: str, *, controls: bool = True, role: str = "") -> str:
    if not filename:
        return ""
    safe_name = html.escape(filename, quote=True)
    controls_attr = " controls" if controls else ""
    role_attr = f' data-audio-role="{html.escape(role, quote=True)}"' if role else ""
    return f'<audio{controls_attr} preload="metadata"{role_attr}><source src="{safe_name}" type="audio/mpeg"></audio>'


def extract_media_references(value: str) -> list[str]:
    refs: list[str] = []
    for attr in ("src", "poster"):
        for match in re.finditer(rf"\b{attr}\s*=\s*([\"'])(.*?)\1", str(value or ""), flags=re.IGNORECASE):
            name = html.unescape(match.group(2)).strip()
            if name and not re.match(r"^[a-z]+://", name, flags=re.IGNORECASE):
                refs.append(Path(name).name)
    return list(dict.fromkeys(refs))


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def media_manifest(media_files: list[str]) -> dict[str, dict[str, Any]]:
    manifest: dict[str, dict[str, Any]] = {}
    for media_file in media_files:
        path = Path(media_file)
        if not path.exists():
            continue
        manifest[path.name] = {
            "sha256": file_sha256(path),
            "bytes": path.stat().st_size,
        }
    return manifest


def compare_media_manifest(expected: dict[str, dict[str, Any]], media_dir: Path) -> dict[str, Any]:
    missing: list[str] = []
    mismatched: list[dict[str, str]] = []
    checked = 0
    for name, expected_info in sorted(expected.items()):
        imported = media_dir / name
        if not imported.exists():
            missing.append(name)
            continue
        checked += 1
        actual_hash = file_sha256(imported)
        expected_hash = str(expected_info.get("sha256") or "")
        if expected_hash and actual_hash != expected_hash:
            mismatched.append(
                {
                    "file": name,
                    "expected_sha256": expected_hash,
                    "actual_sha256": actual_hash,
                }
            )
    return {
        "checked": checked,
        "missing": missing,
        "mismatched": mismatched,
    }


def anki_text(value: Any) -> str:
    return html.escape(str(value or ""), quote=False)


INTERNAL_PLACEHOLDER_PATTERNS = (
    "待精修",
    "本地 fallback",
    "本地草稿",
    "本地待审",
    "正式导出前",
    "需要 AI 精修",
    "只保证结构完整",
    "不建议直接作为正式学习内容",
    "当作本句目标表达",
    "natural object",
    "complete sentence",
)


def contains_internal_placeholder(value: Any) -> bool:
    text = str(value or "")
    text_lower = text.lower()
    return any(pattern in text or pattern.lower() in text_lower for pattern in INTERNAL_PLACEHOLDER_PATTERNS)


def clean_study_text(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if contains_internal_placeholder(text):
        return ""
    return text


def anki_study_text(value: Any) -> str:
    return anki_text(clean_study_text(value))


def compact_retrieval_cue(value: Any, max_chars: int = 26) -> str:
    text = clean_study_text(value)
    text = text.strip(" \t\r\n。.!！?？；;，,")
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars].rstrip()}..."


def is_contextual_vocabulary_card(card: dict[str, Any]) -> bool:
    return (
        str(card.get("content_kind") or "").strip() == "vocabulary"
        or str(card.get("phrase_type") or "").strip() == "vocabulary_usage"
    )


ANSWER_COMMENTARY_RE = re.compile(
    r"\s*[\(（]([^()（）]*(?:听力|连读|弱读|缩读|读作|读为|发音|音变|pronunciation|sounds like)[^()（）]*)[\)）]\s*",
    re.IGNORECASE,
)
ANSWER_EXPLANATION_PATTERNS = (
    "发音",
    "融合",
    "连读",
    "弱读",
    "缩读",
    "非标准",
    "变体",
    "过去式",
    "直接按",
    "映射",
    "听到",
    "听力",
    "读作",
    "读为",
    "解释为",
    "理解为",
    "pronunciation",
    "sounds like",
)
IPA_TEXT_RE = re.compile(r"/[^/\n]{2,}/|[ɑɒɔəɜɪʊʌæɛθðŋʃʒːˈˌɚɝ]")


def answer_display_text(value: Any) -> str:
    text = clean_study_text(value)
    if not text:
        return ""
    text = ANSWER_COMMENTARY_RE.sub(" ", text)
    equal_match = re.match(r"^\s*([^=＝:：]+?)\s*[=＝]\s*(.+)$", text)
    if equal_match and re.search(r"[A-Za-z]", equal_match.group(1)) and has_cjk(equal_match.group(2)):
        text = equal_match.group(1)
    text = re.sub(r"\s+", " ", text).strip(" \t\r\n。；;")
    return text


def answer_commentary_text(value: Any) -> str:
    text = clean_study_text(value)
    if not text:
        return ""
    notes = [match.group(1).strip(" \t\r\n。；;") for match in ANSWER_COMMENTARY_RE.finditer(text)]
    notes = [note for note in notes if note]
    if not notes:
        return ""
    note = "；".join(dict.fromkeys(notes))
    return note if note.startswith(("听感", "发音", "连读", "弱读", "缩读")) else f"听感：{note}"


def is_answer_expression_candidate(value: Any, card: dict[str, Any]) -> bool:
    text = clean_study_text(value)
    if not text:
        return False
    lowered = text.lower()
    if has_cjk(text) or IPA_TEXT_RE.search(text):
        return False
    if any(pattern in text or pattern.lower() in lowered for pattern in ANSWER_EXPLANATION_PATTERNS):
        return False
    if any(mark in text for mark in ("；", "。", "，")):
        return False
    words = overlap_words(text)
    if not words:
        return False
    if str(card.get("type") or "") != "listening" and len(words) > 8:
        return False
    english = clean_study_text(card.get("english"))
    if english and not phrase_in_text(english, text) and len(words) >= 2:
        return False
    return True


def card_answer_core(card: dict[str, Any]) -> str:
    for value in (card.get("answer_core"), card.get("phrase")):
        candidate = answer_display_text(value)
        if is_answer_expression_candidate(candidate, card):
            return candidate
    phrase = answer_display_text(card.get("phrase"))
    if str(card.get("type") or "") != "listening":
        discovered = find_phrase(clean_study_text(card.get("english")), "B1")
        if is_answer_expression_candidate(discovered, card):
            return discovered
    chinese = clean_study_text(card.get("natural_chinese") or card.get("chinese") or "")
    return phrase or chinese or clean_study_text(card.get("english"))


def card_chinese_core(card: dict[str, Any]) -> str:
    return (
        clean_study_text(card.get("natural_chinese"))
        or clean_study_text(card.get("chinese"))
        or clean_study_text(card.get("chinese_feel"))
    )


def _normalized_study_compare(value: Any) -> str:
    text = clean_study_text(value).lower()
    return re.sub(r"[\s\W_]+", "", text, flags=re.UNICODE)


def _study_lines(*values: Any) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = clean_study_text(value)
        if not text:
            continue
        for raw_line in re.split(r"[\n\r]+", text):
            line = raw_line.strip(" \t；;。")
            if not line:
                continue
            marker = _normalized_study_compare(line)
            if not marker or marker in seen:
                continue
            seen.add(marker)
            lines.append(line)
    return lines


def _labeled_study_line(label: str, value: Any) -> str:
    text = clean_study_text(value)
    if not text:
        return ""
    if re.match(r"^\s*(理解|换法|替换|例句|边界|易错|价值|语气|提醒|注意)[:：]", text):
        return text
    return f"{label}：{text}"


def _new_example_for_card(card: dict[str, Any]) -> str:
    example = clean_study_text(card.get("example"))
    if not example:
        return ""
    if _normalized_study_compare(example) == _normalized_study_compare(card.get("english")):
        return ""
    return example


V11_EXPRESSION_FALLBACKS = {
    "run the register": {
        "meaning": "负责收银 / 操作收银机",
        "source_translations": {
            "i'm gonna run the register": "我来负责收银。",
        },
        "usage": "在店铺、餐厅等工作分工里说，表示某人负责看收银台、操作收银机。",
        "misuse": "不要理解成“运行登记表”。register 在这里是“收银机/收银台”，run 是“负责操作”。",
        "self_sentence": "I’ll run the register for a while. / Can you run the register today?",
    },
    "flat as a washboard": {
        "meaning": "平得像搓衣板；夸张地形容很平",
        "source_translations": {
            "i mean you're flat as a washboard": "我是说，你平得像个搓衣板。",
        },
        "usage": "用来夸张地形容表面或身材很平，通常带调侃或刻薄语气。",
        "misuse": "这是调侃外貌或身材的说法，可能冒犯；适合理解台词，不建议随便对人使用。",
        "self_sentence": "The floor was flat as a washboard. / Don’t use it to describe someone’s body unless you mean to sound rude.",
    },
}


GENERIC_V11_STUDY_PATTERNS = (
    "先抓住",
    "再回看上下文",
    "换一个相似场景",
    "用自己的话复述",
    "先确认语气",
    "不要只背中文翻译",
    "复习时先听语气",
    "注意语境",
    "很常见",
    "本句目标表达",
    "fallback",
    "natural object",
    "complete sentence",
)


def _v11_lookup_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9']+", " ", str(value or "").lower()).strip()


def _v11_fallback(card: dict[str, Any]) -> dict[str, Any]:
    phrase = clean_study_text(card.get("phrase")) or card_answer_core(card)
    return V11_EXPRESSION_FALLBACKS.get(phrase_guide_key(phrase), {})


def _v11_guide(card: dict[str, Any]) -> dict[str, Any]:
    phrase = clean_study_text(card.get("phrase")) or card_answer_core(card)
    return PHRASE_GUIDES.get(phrase_guide_key(phrase), {})


def _strip_study_label(value: Any) -> str:
    text = clean_study_text(value).strip()
    return re.sub(
        r"^\s*(理解|怎么用|用法|换法|替换|例句|边界|易错|价值|语气|提醒|注意|误用|释义|意思)[:：]\s*",
        "",
        text,
    ).strip()


def _specific_v11_text(value: Any) -> str:
    text = _strip_study_label(value)
    if not text:
        return ""
    lowered = text.lower()
    if any(pattern in text or pattern.lower() in lowered for pattern in GENERIC_V11_STUDY_PATTERNS):
        return ""
    return text


def _v11_sentence_translation_fallback(card: dict[str, Any]) -> str:
    fallback = _v11_fallback(card)
    english_key = _v11_lookup_key(card.get("english"))
    translations = fallback.get("source_translations")
    if isinstance(translations, dict) and english_key:
        return clean_study_text(translations.get(english_key))
    return clean_study_text(fallback.get("source_translation"))


def v11_meaning_text(card: dict[str, Any]) -> str:
    guide = _v11_guide(card)
    fallback = _v11_fallback(card)
    for candidate in (
        card.get("chinese"),
        card.get("answer_chinese"),
        card.get("meaning"),
        guide.get("chinese"),
        fallback.get("meaning"),
        card.get("chinese_feel"),
        card.get("definition"),
        card.get("natural_chinese"),
    ):
        text = _specific_v11_text(candidate)
        if text and has_cjk(text):
            return text.strip("。；; ")
    return ""


def v11_answer_note_text(card: dict[str, Any]) -> str:
    return answer_commentary_text(card.get("answer_core")) or answer_commentary_text(card.get("phrase"))


def v11_source_translation_text(card: dict[str, Any]) -> str:
    meaning_marker = _normalized_study_compare(v11_meaning_text(card))
    for candidate in (
        card.get("source_chinese"),
        card.get("sentence_chinese"),
        card.get("original_chinese"),
        card.get("natural_chinese"),
        card.get("full_chinese"),
    ):
        text = _specific_v11_text(candidate)
        if text and has_cjk(text) and _normalized_study_compare(text) != meaning_marker:
            return text.strip("；; ")
    fallback = _v11_sentence_translation_fallback(card)
    if fallback:
        return fallback
    text = _specific_v11_text(card.get("chinese"))
    if text and has_cjk(text) and _normalized_study_compare(text) != meaning_marker:
        return text.strip("；; ")
    return ""


def v11_usage_text(card: dict[str, Any]) -> str:
    guide = _v11_guide(card)
    fallback = _v11_fallback(card)
    lines = _study_lines(
        _specific_v11_text(card.get("how_to_use_it")),
        _specific_v11_text(card.get("definition")),
        _specific_v11_text(guide.get("definition")),
        _specific_v11_text(fallback.get("usage")),
    )
    return "\n".join(lines[:2])


def v11_self_sentence_text(card: dict[str, Any]) -> str:
    guide = _v11_guide(card)
    fallback = _v11_fallback(card)
    lines = _study_lines(
        _specific_v11_text(card.get("replacement_examples")),
        _specific_v11_text(_new_example_for_card(card)),
        _specific_v11_text(card.get("collocations")),
        _specific_v11_text(guide.get("example")),
        _specific_v11_text(fallback.get("self_sentence")),
    )
    return "\n".join(lines[:3])


def v11_misuse_text(card: dict[str, Any]) -> str:
    fallback = _v11_fallback(card)
    phrase = card_answer_core(card).lower()
    special_boundary = ""
    if "flat as a washboard" in phrase:
        special_boundary = V11_EXPRESSION_FALLBACKS["flat as a washboard"]["misuse"]
    lines = _study_lines(
        _specific_v11_text(card.get("usage_boundary")),
        special_boundary,
        _specific_v11_text(card.get("confusable_note")),
        _specific_v11_text(card.get("teacher_note")),
        _specific_v11_text(fallback.get("misuse")),
    )
    return "\n".join(lines[:3])


def v11_definition_text(card: dict[str, Any]) -> str:
    return v11_usage_text(card)


def v11_migration_text(card: dict[str, Any]) -> str:
    return v11_self_sentence_text(card)


def v11_teacher_note_text(card: dict[str, Any]) -> str:
    return v11_misuse_text(card)


def card_visual_role(card: dict[str, Any], deck_kind_code: str = "") -> str:
    if deck_kind_code == "document_knowledge":
        return "knowledge"
    if deck_kind_code == "document_reading":
        return "document_reading"
    card_type = str(card.get("type") or "").strip()
    if card_type == "listening":
        return "listening"
    if card_type == "cloze":
        return "cloze"
    if card_type == "knowledge":
        return "knowledge"
    if is_contextual_vocabulary_card(card):
        return "vocabulary"
    return "phrase"


def card_template_labels(card: dict[str, Any], deck_kind_code: str = "") -> dict[str, str]:
    role = card_visual_role(card, deck_kind_code)
    if role == "listening":
        return {
            "card_layout": "listening",
            "front_kicker": "只听一遍，先复述完整句。",
            "source_label": "听力原句",
            "understand_label": "听错点",
            "use_label": "关键表达",
        }
    if role == "cloze":
        return {
            "card_layout": "cloze",
            "front_kicker": "根据语气补出关键表达。",
            "source_label": "原句",
            "understand_label": "为什么这样填",
            "use_label": "可替换框架",
        }
    if role == "vocabulary":
        return {
            "card_layout": "vocabulary",
            "front_kicker": "按原句场景解释这个词。",
            "source_label": "原句",
            "understand_label": "此处词义",
            "use_label": "搭配 / 易混义",
        }
    if role == "knowledge":
        return {
            "card_layout": "knowledge",
            "front_kicker": "先用自己的话回答。",
            "source_label": "正面问题",
            "understand_label": "关键机制",
            "use_label": "相关概念",
        }
    if role == "document_reading":
        return {
            "card_layout": "document_reading",
            "front_kicker": "先解释原文里的语言点。",
            "source_label": "原文线索",
            "understand_label": "怎么理解",
            "use_label": "怎么用",
        }
    return {
        "card_layout": "phrase",
        "front_kicker": "根据中文语境回忆自然表达。",
        "source_label": "英文原句",
        "understand_label": "怎么理解",
        "use_label": "怎么迁移",
    }


def card_front_fields(card: dict[str, Any], *, repetition_mode: bool = False) -> dict[str, str]:
    card_type = card.get("type", "")
    english = clean_study_text(card.get("english"))
    phrase = clean_study_text(card.get("phrase"))
    chinese = card_chinese_core(card)
    retrieval_prompt = clean_study_text(card.get("retrieval_prompt"))
    if repetition_mode and card_type != "knowledge":
        return {
            "front_prompt": "听原声，跟读这一句。",
            "front_content": "先听一遍，再模仿语气和节奏。",
            "answer": card_answer_core(card),
        }
    if card_type == "listening":
        return {
            "front_prompt": "只看画面和听声音，先复述这一句。",
            "front_content": "",
            "answer": english,
        }
    if card_type == "phrase":
        if retrieval_prompt:
            front_prompt = retrieval_prompt
        elif is_contextual_vocabulary_card(card):
            front_prompt = f"“{phrase}”在这句里是什么意思？" if phrase else "这个词在原句里是什么意思？"
        else:
            cue = compact_retrieval_cue(card.get("natural_chinese") or chinese or card.get("chinese_feel"))
            front_prompt = f"这句里表示“{cue}”的自然表达是什么？" if cue else "回忆这句里最值得带走的自然表达。"
        return {
            "front_prompt": front_prompt,
            "front_content": (
                "按原句场景解释，不背词典第一个释义。"
                if is_contextual_vocabulary_card(card)
                else "先听原声，再在心里补出这个表达。"
            ),
            "answer": card_answer_core(card),
        }
    if card_type == "cloze":
        return {
            "front_prompt": "根据语气和画面，在心里补出关键表达。",
            "front_content": clean_study_text(card.get("cloze")) or "先听原声，再补出关键表达。",
            "answer": card_answer_core(card),
        }
    if card_type == "knowledge":
        return {
            "front_prompt": english or "回忆这段资料的核心知识点。",
            "front_content": "先用自己的话回答，再翻面核对结构化解释。",
            "answer": chinese or phrase,
        }
    return {
        "front_prompt": "回忆这张卡的核心表达。",
        "front_content": "",
        "answer": phrase or english,
    }


def card_phrase_tts_text(card: dict[str, Any], front_fields: dict[str, str]) -> str:
    candidates = [
        front_fields.get("answer"),
        card.get("answer_core"),
        card.get("phrase"),
    ]
    for value in candidates:
        text = answer_display_text(value)
        if is_answer_expression_candidate(text, card):
            return clean_tts_input_text(text)
    return ""


def language_code(language: str) -> str:
    lower = language.lower()
    if "fr" in lower:
        return "fr"
    if "es" in lower:
        return "es"
    if "ja" in lower or "日本" in language:
        return "ja"
    return "en"


def transcode_wav_file_to_mp3(wav_path: Path, output_path: Path, label: str) -> None:
    if not shutil.which("ffmpeg"):
        wav_path.unlink(missing_ok=True)
        raise RuntimeError(f"找不到 ffmpeg，无法把 {label} 返回的音频转成 Anki 用的 mp3。")
    completed = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(wav_path),
            "-acodec",
            "libmp3lame",
            "-q:a",
            "5",
            str(output_path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        **hidden_subprocess_flags(),
    )
    wav_path.unlink(missing_ok=True)
    if completed.returncode != 0:
        raise RuntimeError(f"{label} 音频转码失败：{completed.stderr[-800:]}")


def synthesize_tts(
    project: dict[str, Any],
    segment: dict[str, Any],
    output_path: Path,
    text_override: str | None = None,
) -> bool:
    tts = normalized_tts_config(project)
    if not tts["enabled"] or tts["provider"] == "disabled":
        return False

    if not tts["api_key"] and not is_gemini_vertex_tts_config(tts):
        return False

    provider = tts["provider"]
    text = (text_override or segment.get("text", "")).strip()
    if not provider or not text:
        return False

    if provider in {"grok", "xai"}:
        audio = call_tts_audio(tts, text, language_code(project.get("language", "English")))
        output_path.write_bytes(audio)
        return True

    if is_mimo_config(tts):
        if not compatible_base_url(tts) or not tts["model"]:
            return False
        wav_path = output_path.with_suffix(".mimo.wav")
        audio = call_tts_audio(tts, text, language_code(project.get("language", "English")))
        wav_path.write_bytes(audio)
        transcode_wav_file_to_mp3(wav_path, output_path, "MIMO TTS")
        return True

    if provider in QWEN_TTS_PROVIDERS:
        if not tts["base_url"] or not tts["model"]:
            return False
        wav_path = output_path.with_suffix(".qwen.wav")
        audio = call_tts_audio(tts, text, project.get("language", "English"))
        wav_path.write_bytes(audio)
        transcode_wav_file_to_mp3(wav_path, output_path, "Qwen TTS")
        return True

    if is_gemini_vertex_tts_config(tts):
        if not tts["model"]:
            return False
        wav_path = output_path.with_suffix(".gemini_vertex.wav")
        audio = call_tts_audio(tts, text, project.get("language", "English"))
        wav_path.write_bytes(audio)
        transcode_wav_file_to_mp3(wav_path, output_path, "Gemini Vertex TTS")
        return True

    if provider in OPENAI_COMPATIBLE_PROVIDERS:
        if not compatible_base_url(tts) or not tts["model"]:
            return False
        audio = call_tts_audio(tts, text, language_code(project.get("language", "English")))
        output_path.write_bytes(audio)
        return True

    if provider == "gemini":
        model = tts["model"] or "gemini-2.5-flash-preview-tts"
        voice = tts["voice"] or "Kore"

        response = http_json(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            {"x-goog-api-key": tts["api_key"]},
            {
                "contents": [{"parts": [{"text": f"Read naturally and clearly: {text}"}]}],
                "generationConfig": {
                    "responseModalities": ["AUDIO"],
                    "speechConfig": {
                        "voiceConfig": {
                            "prebuiltVoiceConfig": {
                                "voiceName": voice,
                            }
                        }
                    },
                },
                "model": model,
            },
        )
        data = response["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
        pcm_path = output_path.with_suffix(".pcm")
        pcm_path.write_bytes(base64.b64decode(data))
        run_ffmpeg(
            [
                "-f",
                "s16le",
                "-ar",
                "24000",
                "-ac",
                "1",
                "-i",
                str(pcm_path),
                "-acodec",
                "libmp3lame",
                "-q:a",
                "5",
                str(output_path),
            ]
        )
        pcm_path.unlink(missing_ok=True)
        return True

    return False


def handle_export(payload: dict[str, Any]) -> dict[str, Any]:
    emit_progress("export", "prepare", 4, "准备导出 Anki 卡包。")
    try:
        import genanki
    except ImportError:
        fail("缺少 genanki。请运行：pip install -r workers/requirements.txt")

    project = payload.get("project") or {}
    output_dir = Path(payload.get("output_dir") or os.getcwd())
    if not output_dir.exists():
        fail(f"导出目录不存在：{output_dir}")

    is_document_project = project.get("source_mode") == "document"
    video_path_raw = clean_input_path(project.get("video_path"))
    skip_video_media = is_document_project or bool(project.get("skip_video_slicing")) or not video_path_raw
    video_path = Path(video_path_raw) if video_path_raw else Path()
    if not skip_video_media and not video_path.exists():
        fail(f"视频文件不存在：{video_path}")

    emit_progress("export", "template", 10, "正在准备 Anki 模板和导出目录。")
    export_run_id = int(time.time())
    export_root = output_dir / f"AnkiCard-{safe_filename(project.get('title', 'deck'))}-{export_run_id}"
    media_dir = export_root / "media"
    media_dir.mkdir(parents=True, exist_ok=True)

    if is_document_project:
        deck_kind_code = "document_reading" if project.get("document_study_mode") == "language_reading" else "document_knowledge"
        deck_kind = "文档精读卡" if deck_kind_code == "document_reading" else "文档知识卡"
    else:
        deck_kind_code = "subtitle_language" if skip_video_media else "video_language"
        deck_kind = "字幕语言卡" if skip_video_media else "视频语言卡"
    deck_name = f"{deck_kind}::{project.get('title', 'Untitled')}"
    template_id = project.get("template_id", "immersive_v11")
    template_family = anki_template_family(template_id, deck_kind_code)
    template_label, template_css, front_template, back_template = anki_template_assets(template_id, deck_kind_code)
    template_version = anki_template_version(template_id, deck_kind_code)
    use_v11_template = template_version == "V11"
    model = genanki.Model(
        stable_id(f"anki-card-model-{template_version.lower()}-{template_family}", 1000000000),
        f"Anki Card Generator {template_version} - {template_label}",
        fields=[
            {"name": "CardId"},
            {"name": "CardType"},
            {"name": "Video"},
            {"name": "Audio"},
            {"name": "TtsAudio"},
            {"name": "PhraseTtsAudio"},
            {"name": "IsListening"},
            {"name": "FrontPrompt"},
            {"name": "FrontContent"},
            {"name": "Answer"},
            {"name": "English"},
            {"name": "Chinese"},
            {"name": "Phrase"},
            {"name": "Definition"},
            {"name": "Collocations"},
            {"name": "Context"},
            {"name": "Example"},
            {"name": "ChineseFeel"},
            {"name": "Why"},
            {"name": "Difficulty"},
            {"name": "SourceTime"},
            {"name": "TeacherNote"},
            {"name": "Cloze"},
            {"name": "CardLayout"},
            {"name": "CardVisualRole"},
            {"name": "FrontKicker"},
            {"name": "SourceLabel"},
            {"name": "UnderstandLabel"},
            {"name": "UseLabel"},
        ],
        templates=[
            {
                "name": template_label,
                "qfmt": front_template,
                "afmt": back_template,
            }
        ],
        css=template_css,
    )
    deck = genanki.Deck(stable_id(deck_name, 1500000000), deck_name)
    media_files: list[str] = []
    tts_by_segment: dict[str, str] = {}
    phrase_tts_by_phrase: dict[str, str] = {}
    warnings: list[str] = []
    tts_config = normalized_tts_config(project)
    tts_requested = bool(tts_config["enabled"] and tts_config["provider"] != "disabled")
    expected_phrase_tts_keys: set[str] = set()
    exported_cards = 0
    cut_segments: set[str] = set()
    video_segment_count = 0
    video_file_count = 0
    original_audio_count = 0
    project_card_prefix = safe_filename(project.get("title") or project.get("id") or "deck")
    media_prefix = project_media_prefix(project, export_run_id)

    export_segments = [
        segment
        for segment in project.get("segments", [])
        if any(card.get("enabled", True) for card in segment.get("cards", []))
    ]
    if not is_document_project:
        if skip_video_media:
            warnings.append("本次导出为字幕-only / 跳过视频切片模式，APKG 不包含视频片段和原声音频。")
        if not tts_requested:
            warnings.append("TTS 当前未启用，本次导出不会生成整句 AI 朗读和表达小喇叭。")
        elif not tts_config["api_key"] and not is_gemini_vertex_tts_config(tts_config):
            warnings.append("TTS 已启用但缺少 API Key，本次导出不会生成 MIMO / AI 朗读音频。")
        elif (
            tts_config["provider"] in OPENAI_COMPATIBLE_PROVIDERS
            or tts_config["provider"] in QWEN_TTS_PROVIDERS
            or is_gemini_vertex_tts_config(tts_config)
        ) and (not compatible_base_url(tts_config) or not tts_config["model"]):
            warnings.append("TTS 已启用但缺少 Base URL 或模型名，本次导出不会生成 AI 朗读音频。")

    for index, segment in enumerate(export_segments):
        enabled_cards = [card for card in segment.get("cards", []) if card.get("enabled", True)]
        if not enabled_cards:
            continue

        segment_id = safe_filename(segment.get("id", "segment"))
        media_segment_id = f"{media_prefix}_{segment_id}"
        video_webm_name = "" if skip_video_media else f"{media_segment_id}.webm"
        video_mp4_name = "" if skip_video_media else f"{media_segment_id}.mp4"
        poster_name = "" if skip_video_media else f"{media_segment_id}.jpg"
        audio_name = "" if skip_video_media else f"{media_segment_id}.mp3"
        tts_name = f"{media_segment_id}_tts.mp3"
        video_webm_out = media_dir / video_webm_name
        video_mp4_out = media_dir / video_mp4_name
        poster_out = media_dir / poster_name
        audio_out = media_dir / audio_name
        tts_out = media_dir / tts_name
        segment_percent = 15 + int((index / max(1, len(export_segments))) * 68)

        if skip_video_media:
            emit_progress(
                "export",
                "notes",
                segment_percent,
                f"正在整理无视频卡 {index + 1}/{len(export_segments)}：{segment.get('source_time', segment_id)}",
            )
            if tts_requested and not is_document_project:
                try:
                    emit_progress("export", "tts", min(86, segment_percent + 4), f"正在生成整句朗读：{segment_id}")
                    if synthesize_tts(project, segment, tts_out):
                        media_files.append(str(tts_out))
                        tts_by_segment[segment_id] = tts_name
                except Exception as err:
                    warnings.append(f"{segment_id} TTS 失败：{err}")
            cut_segments.add(segment_id)
        elif segment_id not in cut_segments:
            emit_progress(
                "export",
                "media",
                segment_percent,
                f"正在切片 {index + 1}/{len(export_segments)}：{segment.get('source_time', segment_id)}",
            )
            clip_start = float(segment.get("media_start", segment.get("start", 0)) or 0)
            clip_end = float(segment.get("media_end", segment.get("end", 0)) or 0)
            if clip_end <= clip_start:
                clip_start = float(segment.get("start", 0) or 0)
                clip_end = float(segment.get("end", clip_start + 0.5) or clip_start + 0.5)
            start = str(max(0.0, clip_start))
            duration = str(max(0.5, clip_end - clip_start))
            media_commands = [
                (
                    video_webm_out,
                    [
                        "-ss",
                        start,
                        "-t",
                        duration,
                        "-i",
                        str(video_path),
                        "-map",
                        "0:v:0?",
                        "-map",
                        "0:a:0?",
                        "-c:v",
                        "libvpx-vp9",
                        "-b:v",
                        "0",
                        "-crf",
                        "36",
                        "-row-mt",
                        "1",
                        "-deadline",
                        "good",
                        "-cpu-used",
                        "4",
                        "-pix_fmt",
                        "yuv420p",
                        "-ac",
                        "2",
                        "-c:a",
                        "libopus",
                        "-b:a",
                        "64k",
                        str(video_webm_out),
                    ],
                ),
                (
                    video_mp4_out,
                    [
                        "-ss",
                        start,
                        "-t",
                        duration,
                        "-i",
                        str(video_path),
                        "-map",
                        "0:v:0?",
                        "-map",
                        "0:a:0?",
                        "-c:v",
                        "libx264",
                        "-preset",
                        "veryfast",
                        "-crf",
                        "26",
                        "-ac",
                        "2",
                        "-c:a",
                        "aac",
                        "-b:a",
                        "96k",
                        "-movflags",
                        "+faststart",
                        str(video_mp4_out),
                    ],
                ),
                (
                    audio_out,
                    [
                        "-ss",
                        start,
                        "-t",
                        duration,
                        "-i",
                        str(video_path),
                        "-vn",
                        "-ac",
                        "2",
                        "-acodec",
                        "libmp3lame",
                        "-q:a",
                        "5",
                        str(audio_out),
                    ],
                ),
            ]
            media_errors = [
                error
                for _, command in media_commands
                if (error := try_run_ffmpeg(command))
            ]
            if media_errors:
                for output_path, _ in media_commands:
                    output_path.unlink(missing_ok=True)
                video_webm_name = ""
                video_mp4_name = ""
                poster_name = ""
                audio_name = ""
                warnings.append(f"{segment_id} 视频/原声切片失败，已保留文字卡：{media_errors[0]}")
            else:
                poster_at = str(float(start) + min(0.75, max(0.1, float(duration) / 2)))
                poster_error = try_run_ffmpeg(
                    [
                        "-ss",
                        poster_at,
                        "-i",
                        str(video_path),
                        "-frames:v",
                        "1",
                        "-q:v",
                        "3",
                        "-vf",
                        "scale='min(960,iw)':-2",
                        str(poster_out),
                    ]
                )
                if poster_error:
                    poster_name = ""
                    poster_out.unlink(missing_ok=True)
                    warnings.append(f"{segment_id} 视频封面生成失败：{poster_error}")
                media_files.extend([str(video_webm_out), str(video_mp4_out), str(audio_out)])
                if poster_name and poster_out.exists():
                    media_files.append(str(poster_out))
                video_segment_count += 1
                video_file_count += 2
                original_audio_count += 1
            if tts_requested and not is_document_project:
                try:
                    emit_progress("export", "tts", min(86, segment_percent + 4), f"正在生成整句朗读：{segment_id}")
                    if synthesize_tts(project, segment, tts_out):
                        media_files.append(str(tts_out))
                        tts_by_segment[segment_id] = tts_name
                except Exception as err:
                    warnings.append(f"{segment_id} TTS 失败：{err}")
            cut_segments.add(segment_id)

        for card in enabled_cards:
            front_fields = card_front_fields(card, repetition_mode=use_v11_template)
            template_labels = card_template_labels(card, deck_kind_code)
            export_card_id = f"{project_card_prefix}_{card.get('id', '')}"
            phrase_text = card_phrase_tts_text(card, front_fields)
            phrase_tts_name = ""
            phrase_key = phrase_text.lower()
            if tts_requested and phrase_text and phrase_key not in {"key expression", "n/a"}:
                expected_phrase_tts_keys.add(phrase_key)
                if phrase_key in phrase_tts_by_phrase:
                    phrase_tts_name = phrase_tts_by_phrase[phrase_key]
                else:
                    phrase_tts_name = f"{media_prefix}_phrase_{stable_id(phrase_key, 0)}.mp3"
                    phrase_tts_out = media_dir / phrase_tts_name
                    try:
                        emit_progress("export", "tts", min(88, segment_percent + 5), f"正在生成表达发音：{phrase_text}")
                        if synthesize_tts(project, segment, phrase_tts_out, text_override=phrase_text):
                            media_files.append(str(phrase_tts_out))
                            phrase_tts_by_phrase[phrase_key] = phrase_tts_name
                        else:
                            phrase_tts_name = ""
                    except Exception as err:
                        phrase_tts_name = ""
                        warnings.append(f"{segment_id} 表达 TTS 失败：{err}")
            meaning_field = v11_meaning_text(card) if use_v11_template else card_chinese_core(card)
            definition_field = v11_usage_text(card) if use_v11_template else card.get("definition", "")
            collocations_field = v11_self_sentence_text(card) if use_v11_template else card.get("collocations", "")
            context_field = v11_source_translation_text(card) if use_v11_template else card.get("context", "")
            teacher_note_field = v11_misuse_text(card) if use_v11_template else card.get("teacher_note", "")
            chinese_feel_field = v11_answer_note_text(card) if use_v11_template else card.get("chinese_feel", "")
            note = genanki.Note(
                model=model,
                fields=[
                    anki_text(export_card_id),
                    anki_study_text(card.get("type_label", card.get("type", ""))),
                    anki_video_html(video_webm_name, video_mp4_name, poster_name, controls=not use_v11_template, muted=False),
                    anki_audio_html(audio_name, controls=not use_v11_template, role="original"),
                    anki_audio_html(tts_by_segment.get(segment_id, ""), controls=not use_v11_template, role="slow"),
                    anki_audio_html(phrase_tts_name, controls=not use_v11_template, role="phrase"),
                    "1" if card.get("type") == "listening" else "",
                    anki_study_text(front_fields["front_prompt"]),
                    anki_study_text(front_fields["front_content"]),
                    anki_study_text(front_fields["answer"]),
                    anki_study_text(card.get("english", "")),
                    anki_study_text(meaning_field),
                    anki_study_text(card.get("phrase", "")),
                    anki_study_text(definition_field),
                    anki_study_text(collocations_field),
                    anki_study_text(context_field),
                    anki_study_text(card.get("example", "")),
                    anki_study_text(chinese_feel_field),
                    anki_study_text(card.get("why", "")),
                    anki_study_text(card.get("difficulty", "")),
                    anki_text(segment.get("source_time", "")),
                    anki_study_text(teacher_note_field),
                    anki_study_text(card.get("cloze", "")),
                    anki_text(template_labels["card_layout"]),
                    anki_text("repetition" if use_v11_template else template_labels["card_layout"]),
                    anki_text(template_labels["front_kicker"]),
                    anki_text(template_labels["source_label"]),
                    anki_text(template_labels["understand_label"]),
                    anki_text(template_labels["use_label"]),
                ],
                tags=[
                    f"anki_card_generator_{template_version.lower()}",
                    project.get("language", "English"),
                    project.get("level", "B1"),
                    template_id,
                    card.get("type", "card"),
                    template_labels["card_layout"],
                ],
            )
            deck.add_note(note)
            exported_cards += 1

    if exported_cards == 0:
        fail("没有可导出的卡片。请在预览页至少启用一张卡。")
    if tts_requested and not is_document_project:
        expected_sentence_tts = len(cut_segments)
        if expected_sentence_tts and not tts_by_segment:
            warnings.append("TTS 已启用，但整句 AI 朗读生成 0 条；请先测试 TTS 配置后再导出。")
        elif len(tts_by_segment) < expected_sentence_tts:
            warnings.append(f"整句 AI 朗读只生成 {len(tts_by_segment)}/{expected_sentence_tts} 条，请检查导出日志。")
        expected_phrase_tts = len(expected_phrase_tts_keys)
        if expected_phrase_tts and not phrase_tts_by_phrase:
            warnings.append("TTS 已启用，但表达小喇叭生成 0 条；请先测试 TTS 配置后再导出。")
        elif len(phrase_tts_by_phrase) < expected_phrase_tts:
            warnings.append(f"表达小喇叭只生成 {len(phrase_tts_by_phrase)}/{expected_phrase_tts} 条，请检查导出日志。")

    emit_progress("export", "package", 92, "正在写入 .apkg。")
    media_files = list(dict.fromkeys(media_files))
    exported_media_manifest = media_manifest(media_files)
    media_bytes = 0
    for media_file in media_files:
        try:
            media_bytes += Path(media_file).stat().st_size
        except OSError:
            warnings.append(f"媒体文件统计失败：{Path(media_file).name}")
    package = genanki.Package(deck)
    package.media_files = media_files
    apkg_path = export_root / f"{safe_filename(project.get('title', 'anki-card'))}.apkg"
    package.write_to_file(str(apkg_path))

    emit_progress("export", "done", 100, f"导出完成：{exported_cards} 张卡。")
    return {
        "apkg_path": str(apkg_path),
        "media_dir": str(media_dir),
        "deck_name": deck_name,
        "deck_kind": deck_kind_code,
        "media_prefix": media_prefix,
        "media_manifest": exported_media_manifest,
        "cards": exported_cards,
        "segments": len(cut_segments),
        "media_summary": {
            "video_segments": video_segment_count,
            "video_files": video_file_count,
            "original_audio_files": original_audio_count,
            "sentence_tts_files": len(tts_by_segment),
            "phrase_tts_files": len(phrase_tts_by_phrase),
            "media_files": len(media_files),
            "media_bytes": media_bytes,
            "media_mb": round(media_bytes / (1024 * 1024), 1),
        },
        "warnings": warnings,
    }


def handle_verify_anki_import(payload: dict[str, Any]) -> dict[str, Any]:
    export_result = payload.get("export_result") or {}
    deck_name = str(payload.get("deck_name") or export_result.get("deck_name") or "").strip()
    media_dir = Path(str(payload.get("media_dir") or export_result.get("media_dir") or ""))
    anki_url = str(payload.get("anki_connect_url") or "http://127.0.0.1:8765").strip()
    media_summary = export_result.get("media_summary") if isinstance(export_result.get("media_summary"), dict) else {}
    expected_media_files = media_summary.get("media_files")
    try:
        expected_media_files = int(expected_media_files) if expected_media_files is not None else None
    except (TypeError, ValueError):
        expected_media_files = None
    manifest_provided = isinstance(export_result.get("media_manifest"), dict)
    expected_manifest = export_result.get("media_manifest") if manifest_provided else {}
    if not expected_manifest and media_dir.exists() and expected_media_files != 0:
        expected_manifest = media_manifest([str(path) for path in media_dir.iterdir() if path.is_file()])

    if not expected_manifest and expected_media_files != 0:
        fail("缺少导出媒体清单，无法核验 Anki 媒体。")

    query = "tag:anki_card_generator_v10"
    if deck_name:
        query = f'deck:"{deck_name}" {query}'

    try:
        card_ids = anki_connect("findCards", {"query": query}, anki_url)
        card_infos = anki_connect("cardsInfo", {"cards": card_ids or []}, anki_url) if card_ids else []
        anki_media_dir = Path(str(anki_connect("getMediaDirPath", {}, anki_url) or ""))
    except Exception as err:
        return {
            "ok": False,
            "message": f"无法连接 AnkiConnect 或读取卡片：{err}",
            "failed_checks": ["anki_connect"],
            "query": query,
        }

    referenced_media: set[str] = set()
    card_ids_seen: set[int] = set()
    for info in card_infos or []:
        try:
            card_ids_seen.add(int(info.get("cardId")))
        except Exception:
            pass
        fields = info.get("fields") or {}
        for field_name in ["Video", "Audio", "TtsAudio", "PhraseTtsAudio"]:
            referenced_media.update(extract_media_references(anki_field_value(fields, field_name)))

    expected_names = set(expected_manifest)
    expected_referenced_manifest = {
        name: expected_manifest[name]
        for name in sorted(expected_names & referenced_media)
    }
    manifest_check = compare_media_manifest(expected_referenced_manifest, anki_media_dir)
    unreferenced_expected = sorted(expected_names - referenced_media)
    unexpected_references = sorted(referenced_media - expected_names)
    expected_cards = int(export_result.get("cards") or payload.get("expected_cards") or 0)

    failed_checks: list[str] = []
    if not card_infos:
        failed_checks.append("no_imported_cards")
    if expected_cards and len(card_ids_seen) != expected_cards:
        failed_checks.append("card_count_mismatch")
    if unreferenced_expected:
        failed_checks.append("unreferenced_expected_media")
    if unexpected_references:
        failed_checks.append("unexpected_media_references")
    if manifest_check["missing"]:
        failed_checks.append("missing_imported_media")
    if manifest_check["mismatched"]:
        failed_checks.append("media_hash_mismatch")

    return {
        "ok": not failed_checks,
        "message": "Anki 导入媒体核验通过。" if not failed_checks else "Anki 导入媒体核验发现问题。",
        "failed_checks": failed_checks,
        "query": query,
        "deck_name": deck_name,
        "card_count": len(card_ids_seen),
        "expected_cards": expected_cards or None,
        "media_count_expected": len(expected_manifest),
        "media_count_referenced": len(referenced_media),
        "media_count_checked": manifest_check["checked"],
        "missing_media": manifest_check["missing"],
        "mismatched_media": manifest_check["mismatched"],
        "unexpected_media_references": unexpected_references,
        "unreferenced_expected_media": unreferenced_expected,
        "anki_media_dir": str(anki_media_dir),
    }


def package_version(name: str) -> str:
    try:
        from importlib import metadata

        return metadata.version(name)
    except Exception:
        return ""


def check_anki_connect() -> tuple[bool, str]:
    try:
        response = http_json(
            "http://127.0.0.1:8765",
            {},
            {"action": "version", "version": 6, "params": {}},
            timeout=2,
        )
        version = response.get("result")
        return True, f"AnkiConnect {version}" if version else "AnkiConnect 可用"
    except Exception as err:
        return False, str(err)


def handle_check_env(_: dict[str, Any]) -> dict[str, Any]:
    try:
        import genanki  # noqa: F401

        genanki_ready = True
    except ImportError:
        genanki_ready = False
    yt_dlp_command = yt_dlp_base_command()
    yt_dlp_version = ""
    if yt_dlp_command:
        completed = subprocess.run(
            [*yt_dlp_command, "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if completed.returncode == 0:
            yt_dlp_version = completed.stdout.strip()

    ffmpeg_path = shutil.which("ffmpeg") or ""
    ffmpeg_version = ""
    if ffmpeg_path:
        completed = subprocess.run(
            ["ffmpeg", "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if completed.returncode == 0:
            ffmpeg_version = (completed.stdout.splitlines() or [""])[0]
    js_runtime = "deno" if shutil.which("deno") else ("node" if shutil.which("node") else "")
    anki_connect_ready, anki_connect_detail = check_anki_connect()
    venv_ready = ".venv" in str(Path(sys.executable).resolve()).lower()
    packages = {
        "genanki": package_version("genanki"),
        "yt-dlp": package_version("yt-dlp"),
        "pypdf": package_version("pypdf"),
        "curl-cffi": package_version("curl_cffi") or package_version("curl-cffi"),
    }
    status_items = [
        {
            "id": "python",
            "label": "Python worker",
            "status": "ok",
            "detail": f"{sys.version.split()[0]} · {sys.executable}",
            "fix": "",
        },
        {
            "id": "venv",
            "label": "项目私有 venv",
            "status": "ok" if venv_ready else "action",
            "detail": "正在使用项目 .venv" if venv_ready else "当前没有使用项目 .venv，发布包建议先运行 setup_runtime.ps1。",
            "fix": "运行 scripts/setup_runtime.ps1",
        },
        {
            "id": "ffmpeg",
            "label": "FFmpeg 视频切片",
            "status": "ok" if ffmpeg_path else "blocked",
            "detail": ffmpeg_version or "未在 PATH 找到 ffmpeg；本地视频导出会失败。",
            "fix": "安装 FFmpeg 并加入 PATH，或运行 scripts/setup_runtime.ps1 -InstallWithWinget",
        },
        {
            "id": "genanki",
            "label": "genanki APKG 导出",
            "status": "ok" if genanki_ready else "blocked",
            "detail": packages.get("genanki") or "缺少 genanki。",
            "fix": "运行 scripts/setup_runtime.ps1",
        },
        {
            "id": "yt_dlp",
            "label": "yt-dlp URL 导入",
            "status": "ok" if yt_dlp_command else "action",
            "detail": yt_dlp_version or "缺少 yt-dlp；URL 导入不可用，但本地 SRT/文档仍可用。",
            "fix": "运行 scripts/setup_runtime.ps1",
        },
        {
            "id": "js_runtime",
            "label": "Deno / Node challenge solver",
            "status": "ok" if js_runtime else "action",
            "detail": js_runtime or "YouTube n challenge 可能失败。",
            "fix": "安装 Deno 2.0+ 或 Node.js 20+。",
        },
        {
            "id": "anki_connect",
            "label": "AnkiConnect 导入核验",
            "status": "ok" if anki_connect_ready else "action",
            "detail": anki_connect_detail if anki_connect_ready else "Anki 未打开或未安装 AnkiConnect；仍可导出 APKG 后手动导入。",
            "fix": "打开 Anki，并确认 AnkiConnect 插件启用。",
        },
    ]

    return {
        "python": sys.version.split()[0],
        "python_executable": sys.executable,
        "venv": venv_ready,
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "ffmpeg_path": ffmpeg_path,
        "ffmpeg_version": ffmpeg_version,
        "genanki": genanki_ready,
        "yt_dlp": bool(yt_dlp_command),
        "yt_dlp_version": yt_dlp_version,
        "yt_dlp_js_runtime": js_runtime,
        "anki_connect": anki_connect_ready,
        "anki_connect_detail": anki_connect_detail,
        "packages": packages,
        "status_items": status_items,
        "worker": str(Path(__file__).resolve()),
    }


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    payload = read_payload()

    if command == "check_env":
        emit(handle_check_env(payload))
    elif command == "test_api":
        emit(handle_test_api(payload))
    elif command == "test_tts":
        emit(handle_test_tts(payload))
    elif command == "generate":
        emit(handle_generate(payload))
    elif command == "export":
        emit(handle_export(payload))
    elif command == "verify_anki_import":
        emit(handle_verify_anki_import(payload))
    else:
        fail(f"未知 worker 命令：{command}")


if __name__ == "__main__":
    main()

