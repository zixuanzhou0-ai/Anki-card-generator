"""Canonical language profiles for the first bilingual candidate slice.

Language strings enter the service from user-authored learning contracts and
model output.  They are therefore aliases, not trustworthy policy decisions.
This module keeps normalization and the deliberately small first-release
support matrix in one deterministic place.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Mapping


ZH_CN = "zh-CN"
EN = "en"
AUTO = "auto"
ZH_CN_TO_EN_ROUTES = frozenset({"production", "chunk_collocation"})
LEGACY_EN_ROUTES = frozenset(
    {
        "reading_recognition",
        "listening_recognition",
        "production",
        "grammar_cloze",
        "pronunciation",
        "pragmatics_register",
        "chunk_collocation",
        "contrast",
    }
)

_ZH_ALIASES = frozenset(
    {
        "zh",
        "zh-cn",
        "zh-hans",
        "chinese",
        "chinese-simplified",
        "中文",
        "简体中文",
        "汉语",
        "普通话",
    }
)
_EN_ALIASES = frozenset(
    {"en", "en-us", "en-gb", "english", "英语", "英文"}
)
_HAN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def normalize_language(value: Any) -> str:
    """Return the stable language identifier used by candidate policy.

    Known English regional tags intentionally collapse to ``en`` because the
    first candidate contract does not make dialect-specific scoring claims.
    Traditional-Chinese tags stay outside the supported alias set rather than
    being silently rewritten to Simplified Chinese.
    """

    if not isinstance(value, str):
        return ""
    text = unicodedata.normalize("NFKC", value).strip()
    if not text:
        return ""
    folded = re.sub(r"[\s_]+", "-", text).casefold()
    if folded == AUTO:
        return AUTO
    if folded in _ZH_ALIASES:
        return ZH_CN
    if folded in _EN_ALIASES:
        return EN
    return folded


def normalize_learning_contract_languages(
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Clone a public contract and canonicalize only recognized language fields."""

    normalized = dict(contract)
    for field in ("promptLanguage", "answerLanguage"):
        language = normalize_language(contract.get(field))
        if language:
            normalized[field] = language
    return normalized


@dataclass(frozen=True)
class CandidateLanguageProfile:
    prompt_language: str
    answer_language: str
    mode: str

    @property
    def is_zh_cn_to_en(self) -> bool:
        return self.mode == "zh-CN-to-en"

    def supports_route(self, route: str) -> bool:
        if self.is_zh_cn_to_en:
            return route in ZH_CN_TO_EN_ROUTES
        if self.mode == "legacy-en":
            return route in LEGACY_EN_ROUTES
        return False


def candidate_language_profile(
    contract: Mapping[str, Any],
) -> CandidateLanguageProfile:
    """Resolve the bilingual policy without changing legacy English behavior."""

    prompt = normalize_language(contract.get("promptLanguage"))
    answer = normalize_language(contract.get("answerLanguage"))
    if prompt == ZH_CN and answer == EN:
        mode = "zh-CN-to-en"
    elif prompt in {"", AUTO, EN} and answer in {"", AUTO, EN}:
        mode = "legacy-en"
    else:
        mode = "unsupported"
    return CandidateLanguageProfile(prompt, answer, mode)


def contains_han(value: str) -> bool:
    return _HAN_RE.search(value) is not None


def contains_latin(value: str) -> bool:
    return any(
        character.isalpha()
        and "LATIN" in unicodedata.name(character, "")
        for character in value
    )


def is_latin_script_text(value: Any) -> bool:
    """Require Latin letters only while allowing numbers and punctuation."""

    if not isinstance(value, str):
        return False
    saw_latin = False
    for character in unicodedata.normalize("NFKC", value):
        if not character.isalpha():
            continue
        if "LATIN" not in unicodedata.name(character, ""):
            return False
        saw_latin = True
    return saw_latin


def normalize_answer_leakage_text(value: Any) -> str:
    """Collapse display-only separators before deterministic answer-leak checks.

    Models can insert punctuation, hyphens or Unicode format characters between
    answer characters.  Keeping only Unicode letters and numbers after NFKC and
    case folding gives both candidate gates and card planning the same closed,
    locale-independent comparison surface.
    """

    if not isinstance(value, str):
        return ""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in normalized if character.isalnum())


__all__ = [
    "AUTO",
    "EN",
    "LEGACY_EN_ROUTES",
    "ZH_CN",
    "ZH_CN_TO_EN_ROUTES",
    "CandidateLanguageProfile",
    "candidate_language_profile",
    "contains_han",
    "contains_latin",
    "is_latin_script_text",
    "normalize_answer_leakage_text",
    "normalize_language",
    "normalize_learning_contract_languages",
]
