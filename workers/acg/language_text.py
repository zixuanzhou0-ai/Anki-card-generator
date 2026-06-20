from __future__ import annotations

import re
from typing import Any

from acg.text_cleaning import clean_study_text


LEARNING_LANGUAGE_PROFILES: dict[str, dict[str, str]] = {
    "en": {
        "label": "English",
        "accent_profile": "en-US-general",
        "notation_system": "ipa_en_connected",
        "standard_hint": "IPA",
    },
    "fr": {
        "label": "Français",
        "accent_profile": "fr-FR-standard-media",
        "notation_system": "api_ipa_liaison",
        "standard_hint": "API/IPA",
    },
    "es": {
        "label": "Español",
        "accent_profile": "es-LatAm-general-MX-like",
        "notation_system": "spanish_syllable_stress_optional_ipa",
        "standard_hint": "音节+重音",
    },
    "ja": {
        "label": "日本語",
        "accent_profile": "ja-JP-Tokyo-standard",
        "notation_system": "kana_pitch",
        "standard_hint": "假名+音高",
    },
    "ru": {
        "label": "Русский",
        "accent_profile": "ru-general-standard",
        "notation_system": "stressed_cyrillic_optional_ipa",
        "standard_hint": "重音西里尔",
    },
}

LEARNING_LANGUAGE_ALIASES = {
    "": "en",
    "english": "en",
    "en-us": "en",
    "en-gb": "en",
    "us english": "en",
    "american english": "en",
    "英语": "en",
    "français": "fr",
    "francais": "fr",
    "french": "fr",
    "fr-fr": "fr",
    "法语": "fr",
    "español": "es",
    "espanol": "es",
    "spanish": "es",
    "es-mx": "es",
    "es-419": "es",
    "es-es": "es",
    "西班牙语": "es",
    "日本語": "ja",
    "japanese": "ja",
    "ja-jp": "ja",
    "日语": "ja",
    "русский": "ru",
    "russian": "ru",
    "ru-ru": "ru",
    "俄语": "ru",
}

TTS_LANGUAGE_FALLBACKS: dict[str, list[str]] = {
    "en": ["en-US", "en-GB"],
    "fr": ["fr-FR", "fr-CA"],
    "es": ["es-MX", "es-419", "es-US", "es-ES"],
    "ja": ["ja-JP"],
    "ru": ["ru-RU"],
}

CONTRACTION_WORD_EXPANSIONS = {
    "i've": ["i", "have"],
    "you've": ["you", "have"],
    "we've": ["we", "have"],
    "they've": ["they", "have"],
    "i'm": ["i", "am"],
    "you're": ["you", "are"],
    "we're": ["we", "are"],
    "they're": ["they", "are"],
    "it's": ["it", "is"],
    "that's": ["that", "is"],
    "what's": ["what", "is"],
    "who's": ["who", "is"],
    "where's": ["where", "is"],
    "there's": ["there", "is"],
    "here's": ["here", "is"],
    "i'd": ["i", "would"],
    "you'd": ["you", "would"],
    "we'd": ["we", "would"],
    "they'd": ["they", "would"],
    "i'll": ["i", "will"],
    "you'll": ["you", "will"],
    "we'll": ["we", "will"],
    "they'll": ["they", "will"],
}


def normalize_learning_language(language: Any = "en") -> str:
    raw = str(language or "").strip()
    lower = raw.lower()
    if lower in LEARNING_LANGUAGE_PROFILES:
        return lower
    if lower in LEARNING_LANGUAGE_ALIASES:
        return LEARNING_LANGUAGE_ALIASES[lower]
    if lower.startswith("en"):
        return "en"
    if lower.startswith("fr"):
        return "fr"
    if lower.startswith("es"):
        return "es"
    if lower.startswith("ja") or "日本" in raw:
        return "ja"
    if lower.startswith("ru") or "рус" in lower or "俄语" in raw:
        return "ru"
    return "en"


def pronunciation_profile(language: Any = "en") -> dict[str, str]:
    code = normalize_learning_language(language)
    return {"code": code, **LEARNING_LANGUAGE_PROFILES[code]}


def overlap_words(value: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9']+", value.lower())


def expanded_overlap_words(value: str) -> list[str]:
    words: list[str] = []
    for word in overlap_words(value):
        words.extend(CONTRACTION_WORD_EXPANSIONS.get(word, [word]))
    return words


def has_cjk(value: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", str(value or "")))


def has_japanese_kana(value: Any) -> bool:
    return bool(re.search(r"[\u3040-\u30ff]", str(value or "")))


def has_cyrillic(value: Any) -> bool:
    return bool(re.search(r"[\u0400-\u04ff]", str(value or "")))


def has_latin_letter(value: Any) -> bool:
    return bool(re.search(r"[A-Za-zÀ-ÖØ-öø-ÿĀ-ž]", str(value or "")))


def looks_like_target_language_text(value: Any, language: Any = "en") -> bool:
    text = clean_study_text(value)
    if not text:
        return False
    code = normalize_learning_language(language)
    if code == "ja":
        return has_japanese_kana(text) or has_cjk(text)
    if code == "ru":
        return has_cyrillic(text)
    if code in {"fr", "es", "en"}:
        return has_latin_letter(text)
    return bool(text)


def word_overlap_ratio(left: str, right: str) -> float:
    left_words = set(overlap_words(left))
    right_words = set(overlap_words(right))
    if not left_words or not right_words:
        return 0.0
    return len(left_words & right_words) / max(1, min(len(left_words), len(right_words)))
