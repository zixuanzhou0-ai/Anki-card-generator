from __future__ import annotations

import hashlib
import math
from pathlib import Path
import re
import unicodedata
from typing import Any

from acg.tts_text import clean_tts_input_text


SHELL_LIKE_COMMAND_NAMES = {
    "cmd",
    "cmd.exe",
    "powershell",
    "powershell.exe",
    "pwsh",
    "pwsh.exe",
    "bash",
    "bash.exe",
    "sh",
    "sh.exe",
}
SHELL_METACHAR_PATTERN = re.compile(r"[&|;<>()`]")


def tts_semantic_config(project: dict[str, Any]) -> dict[str, Any]:
    raw = project.get("tts_semantic_verification")
    return raw if isinstance(raw, dict) else {}


def tts_semantic_verification_enabled(project: dict[str, Any]) -> bool:
    config = tts_semantic_config(project)
    return bool(config.get("enabled") or config.get("enable_asr_quality_gate"))


def tts_semantic_requires_export_pass(project: dict[str, Any], deck_kind_code: str = "") -> bool:
    config = tts_semantic_config(project)
    if not tts_semantic_verification_enabled(project):
        return False
    return bool(
        config.get("require_pass_for_export")
        or config.get("strict")
        or config.get("block_unverified")
        or config.get("fail_on_manual_review")
    )


def unsafe_asr_command_reason(command: str) -> str:
    normalized = str(command or "").strip()
    if not normalized:
        return ""
    if "{audio}" in normalized:
        return "asr_command_audio_template_requires_args"
    if SHELL_METACHAR_PATTERN.search(normalized):
        return "asr_command_contains_shell_metacharacters"
    first_token = re.split(r"\s+", normalized, maxsplit=1)[0].strip('"').strip("'").lower()
    command_name = Path(normalized.strip('"').strip("'")).name.lower()
    if first_token in SHELL_LIKE_COMMAND_NAMES or command_name in SHELL_LIKE_COMMAND_NAMES:
        return "asr_command_shell_not_allowed"
    return ""


def build_asr_command_argv(command: str, args: Any, audio_path: Path) -> tuple[list[str], str]:
    reason = unsafe_asr_command_reason(command)
    if reason:
        return [], reason
    argv = [str(command).strip()]
    if isinstance(args, list):
        rendered_args = [str(item).replace("{audio}", str(audio_path)) for item in args]
        if not any("{audio}" in str(item) for item in args):
            rendered_args.append(str(audio_path))
        argv.extend(rendered_args)
    else:
        argv.append(str(audio_path))
    return argv, ""


def normalize_tts_semantic_text(text: Any) -> str:
    cleaned = unicodedata.normalize("NFKC", str(text or "")).lower()
    cleaned = cleaned.replace("’", "'").replace("`", "'")
    cleaned = re.sub(
        r"\[(?:laughter|laughs?|music|applause|cheering|clapping|silence|inaudible|noise|sound|sighs?|coughs?)\]",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\((?:laughter|laughs?|music|applause|cheering|clapping|silence|inaudible|noise|sound|sighs?|coughs?)\)",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"[^a-z0-9'\s]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def normalize_tts_semantic_without_articles(text: str) -> str:
    words = [word for word in normalize_tts_semantic_text(text).split() if word not in {"a", "an", "the"}]
    return " ".join(words)


TTS_SEMANTIC_HOMOPHONE_SIGNATURES = {
    "too": "to",
    "two": "to",
    "you're": "your",
    "youre": "your",
    "mourning": "morning",
}


def tts_semantic_word_signature(word: str) -> str:
    value = word.strip().lower()
    value = TTS_SEMANTIC_HOMOPHONE_SIGNATURES.get(value, value)
    if value == "says":
        return "say"
    if len(value) > 4 and value.endswith("ies"):
        return f"{value[:-3]}y"
    if len(value) > 4 and value.endswith("es"):
        return value[:-2]
    if len(value) > 4 and value.endswith("s") and not value.endswith("ss"):
        return value[:-1]
    return value


def tts_semantic_matches(expected: str, transcript: str, *, role: str) -> tuple[bool, str, str]:
    expected_norm = normalize_tts_semantic_text(expected)
    transcript_norm = normalize_tts_semantic_text(transcript)
    if not expected_norm or not transcript_norm:
        return False, expected_norm, transcript_norm
    if expected_norm == transcript_norm:
        return True, expected_norm, transcript_norm

    expected_no_articles = normalize_tts_semantic_without_articles(expected)
    transcript_no_articles = normalize_tts_semantic_without_articles(transcript)
    if expected_no_articles and expected_no_articles == transcript_no_articles:
        return True, expected_norm, transcript_norm

    expected_words = expected_norm.split()
    transcript_words = transcript_norm.split()
    if role in {"phrase_tts", "phrase"} and len(expected_words) <= 2:
        return False, expected_norm, transcript_norm
    if expected_words and transcript_words:
        expected_set = set(expected_words)
        transcript_set = set(transcript_words)
        coverage = len(expected_set & transcript_set) / max(1, len(expected_set))
        length_delta = abs(len(transcript_words) - len(expected_words))
        if coverage >= 0.9 and length_delta <= max(2, math.ceil(len(expected_words) * 0.2)):
            return True, expected_norm, transcript_norm
        expected_signature_set = {tts_semantic_word_signature(word) for word in expected_words}
        transcript_signature_set = {tts_semantic_word_signature(word) for word in transcript_words}
        signature_coverage = len(expected_signature_set & transcript_signature_set) / max(1, len(expected_signature_set))
        if signature_coverage >= 0.9 and length_delta <= max(2, math.ceil(len(expected_words) * 0.2)):
            return True, expected_norm, transcript_norm
    return False, expected_norm, transcript_norm


def _overlap_words(value: Any) -> list[str]:
    return re.findall(r"[A-Za-z0-9']+", str(value or "").lower())


def _media_text_hash(value: Any) -> str:
    return hashlib.sha256(clean_tts_input_text(value).lower().encode("utf-8")).hexdigest()[:12]


def phrase_tts_speech_units(text: str) -> int:
    words = _overlap_words(text)
    if words:
        return len(words)
    compact = re.sub(r"\s+", "", clean_tts_input_text(text))
    return max(1, math.ceil(len(compact) / 2))


def phrase_tts_max_duration_seconds(text: str) -> float:
    units = phrase_tts_speech_units(text)
    return min(12.0, max(3.5, 1.5 + units * 0.75))


HIGH_RISK_PHRASE_TTS_TERMS = {"prompt", "model", "design", "scratch"}


def phrase_tts_semantic_review_reasons(text: str) -> list[str]:
    cleaned = clean_tts_input_text(text).lower()
    reasons = ["asr_semantic_check_unavailable"]
    words = set(_overlap_words(cleaned))
    if cleaned in HIGH_RISK_PHRASE_TTS_TERMS or words.intersection(HIGH_RISK_PHRASE_TTS_TERMS):
        reasons.append("high_risk_short_expression")
    if phrase_tts_speech_units(cleaned) <= 2:
        reasons.append("short_expression")
    return sorted(set(reasons))


def tts_semantic_base_reasons(role: str, text: str) -> list[str]:
    if role == "phrase_tts" or role == "phrase":
        return phrase_tts_semantic_review_reasons(text)
    return ["asr_semantic_check_unavailable"]


def tts_semantic_not_applicable(expected_text: str, role: str) -> dict[str, Any]:
    tts_text = clean_tts_input_text(expected_text)
    return {
        "semantic_verification": "not_applicable",
        "manual_review_required": False,
        "semantic_review_reasons": [],
        "asr_provider": "none",
        "asr_transcript": "",
        "expected_text_normalized": normalize_tts_semantic_text(tts_text),
        "actual_text_normalized": "",
    }


def tts_semantic_failure_items(expected_manifest: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for name, info in sorted(expected_manifest.items()):
        if not isinstance(info, dict):
            continue
        role = str(info.get("role") or "")
        if role not in {"sentence_tts", "phrase_tts"}:
            continue
        if str(info.get("semantic_verification") or "") != "mismatch":
            continue
        failures.append(
            {
                "file": name,
                "role": role,
                "field": str(info.get("field") or ""),
                "card_id": str(info.get("card_id") or ""),
                "learning_point_id": str(info.get("learning_point_id") or ""),
                "tts_text": clean_tts_input_text(info.get("tts_text") or ""),
                "asr_transcript": str(info.get("asr_transcript") or ""),
                "expected_text_normalized": str(info.get("expected_text_normalized") or ""),
                "actual_text_normalized": str(info.get("actual_text_normalized") or ""),
                "semantic_review_reasons": info.get("semantic_review_reasons") or ["asr_text_mismatch"],
            }
        )
    return failures


def tts_manual_review_items(expected_manifest: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for name, info in sorted(expected_manifest.items()):
        if not isinstance(info, dict):
            continue
        role = str(info.get("role") or "")
        if role not in {"sentence_tts", "phrase_tts"}:
            continue
        tts_text = clean_tts_input_text(info.get("tts_text") or "")
        if not tts_text:
            continue
        semantic_status = str(info.get("semantic_verification") or "manual_review_required")
        if semantic_status == "passed":
            continue
        if semantic_status == "mismatch":
            continue
        if semantic_status == "not_applicable":
            continue
        reasons = info.get("semantic_review_reasons") if isinstance(info.get("semantic_review_reasons"), list) else None
        if not reasons:
            reasons = tts_semantic_base_reasons(role, tts_text)
        item = {
            "file": name,
            "role": role,
            "field": str(info.get("field") or ("PhraseTtsAudio" if role == "phrase_tts" else "TtsAudio")),
            "card_id": str(info.get("card_id") or ""),
            "learning_point_id": str(info.get("learning_point_id") or ""),
            "segment_id": str(info.get("segment_id") or ""),
            "source_time": str(info.get("source_time") or ""),
            "tts_text": tts_text,
            "text_hash": str(info.get("text_hash") or _media_text_hash(tts_text)),
            "semantic_verification": semantic_status or "manual_review_required",
            "semantic_review_reasons": sorted(set(reasons)),
            "asr_provider": str(info.get("asr_provider") or "none"),
            "asr_transcript": str(info.get("asr_transcript") or ""),
        }
        if info.get("duration_seconds") is not None:
            item["duration_seconds"] = info.get("duration_seconds")
        if role == "phrase_tts":
            item["max_duration_seconds"] = info.get("max_duration_seconds") or round(
                phrase_tts_max_duration_seconds(tts_text),
                3,
            )
        items.append({key: value for key, value in item.items() if value not in (None, "", [])})
    return items


def tts_semantic_verification_summary(
    items: list[dict[str, Any]],
    expected_manifest: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    tts_entries = [
        info
        for info in (expected_manifest or {}).values()
        if isinstance(info, dict) and str(info.get("role") or "") in {"sentence_tts", "phrase_tts"}
    ]
    passed = sum(1 for info in tts_entries if str(info.get("semantic_verification") or "") == "passed")
    failed = sum(1 for info in tts_entries if str(info.get("semantic_verification") or "") == "mismatch")
    high_risk_items = [
        item
        for item in items
        if "high_risk_short_expression" in (item.get("semantic_review_reasons") or [])
    ]
    automatic_available = any(info.get("asr_transcript") for info in tts_entries)
    if failed:
        status = "mismatch"
    elif tts_entries and passed == len(tts_entries):
        status = "passed"
    elif items:
        status = "manual_review_required"
    else:
        status = "not_applicable"
    return {
        "automatic_semantic_check": "available" if automatic_available else "unavailable",
        "status": status,
        "passed": passed,
        "failed": failed,
        "manual_review_required": len(items),
        "high_risk_items": len(high_risk_items),
    }
