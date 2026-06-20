from __future__ import annotations

import re
import unicodedata
from typing import Any

from acg.text_cleaning import clean_study_text


TTS_SMALL_NUMBER_WORDS = {
    "0": "zero",
    "1": "one",
    "2": "two",
    "3": "three",
    "4": "four",
    "5": "five",
    "6": "six",
    "7": "seven",
    "8": "eight",
    "9": "nine",
    "10": "ten",
    "11": "eleven",
    "12": "twelve",
    "13": "thirteen",
    "14": "fourteen",
    "15": "fifteen",
    "16": "sixteen",
    "17": "seventeen",
    "18": "eighteen",
    "19": "nineteen",
    "20": "twenty",
}


def clean_tts_input_text(value: Any) -> str:
    text = clean_study_text(value)
    text = re.sub(r"\s+", " ", text).strip(" \t\r\n\"“”")
    if not text:
        raise RuntimeError("TTS 文本为空，无法生成音频。")
    return text


def tts_ascii_punctuation_variant(text: str) -> str:
    return (
        text.replace("’", "'")
        .replace("‘", "'")
        .replace("“", '"')
        .replace("”", '"')
        .replace("—", "-")
        .replace("–", "-")
        .replace("…", "...")
    )


def tts_sentence_punctuation_variant(text: str) -> str:
    stripped = text.strip()
    if not stripped or re.search(r"[.!?。！？]$", stripped):
        return stripped
    return f"{stripped}."


def tts_small_number_words_variant(text: str) -> str:
    def replace_match(match: re.Match[str]) -> str:
        return TTS_SMALL_NUMBER_WORDS.get(match.group(0), match.group(0))

    return re.sub(r"(?<![\w.])(?:[0-9]|1[0-9]|20)(?![\w]|\.\d)", replace_match, text)


def tts_speech_safe_variant(text: str) -> str:
    value = unicodedata.normalize("NFKC", str(text or ""))
    value = re.sub(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff]", "", value)
    value = tts_ascii_punctuation_variant(value)
    value = value.replace("\\", " ")
    value = re.sub(r"\s*/\s*", " ", value)
    value = re.sub(r"[<>\[\]{}]", " ", value)
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"\s+([,.!?;:])", r"\1", value)
    return clean_tts_input_text(value)


def gemini_vertex_tts_text_variants(text: str) -> list[str]:
    candidates = [
        text,
        tts_ascii_punctuation_variant(text),
        tts_sentence_punctuation_variant(text),
        tts_sentence_punctuation_variant(tts_ascii_punctuation_variant(text)),
        tts_small_number_words_variant(text),
        tts_sentence_punctuation_variant(tts_small_number_words_variant(text)),
        tts_speech_safe_variant(text),
        tts_sentence_punctuation_variant(tts_speech_safe_variant(text)),
    ]
    variants: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        cleaned = clean_tts_input_text(candidate)
        if cleaned not in seen:
            variants.append(cleaned)
            seen.add(cleaned)
    return variants


def exact_tts_prompt(text: str) -> str:
    speech_text = clean_tts_input_text(text)
    return (
        "Read aloud exactly the target text below. "
        "Do not explain, translate, expand, add words, add a preface, or read this instruction.\n"
        f"Target text: {speech_text}"
    )
