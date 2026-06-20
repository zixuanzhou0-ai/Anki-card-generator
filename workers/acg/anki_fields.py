from __future__ import annotations

import html
import json
import re
from typing import Any, Callable


def anki_field_value(fields: dict[str, Any], name: str) -> str:
    field = fields.get(name)
    if isinstance(field, dict):
        return str(field.get("value") or "")
    return str(field or "")


def anki_field_plain_text(fields: dict[str, Any], name: str) -> str:
    value = html.unescape(anki_field_value(fields, name))
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def anki_field_has_any_text(fields: dict[str, Any], names: list[str]) -> bool:
    return any(bool(anki_field_plain_text(fields, name)) for name in names)


def missing_required_field_groups(
    fields: dict[str, Any],
    required_groups: dict[str, list[str]],
) -> list[str]:
    return [
        label
        for label, names in required_groups.items()
        if not anki_field_has_any_text(fields, names)
    ]


def missing_video_required_text_fields(fields: dict[str, Any]) -> list[str]:
    return missing_required_field_groups(
        fields,
        {
            "CardId": ["CardId"],
            "English": ["English"],
            "AnswerOrPhrase": ["Answer", "Phrase"],
        },
    )


def missing_document_required_text_fields(fields: dict[str, Any]) -> list[str]:
    return missing_required_field_groups(
        fields,
        {
            "CardId": ["CardId"],
            "QuestionOrSource": ["FrontContent", "English"],
            "AnswerOrDefinition": ["Answer", "Definition"],
        },
    )


def anki_card_model_name(info: dict[str, Any]) -> str:
    for key in ("modelName", "model"):
        value = info.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    note = info.get("note")
    if isinstance(note, dict):
        for key in ("modelName", "model"):
            value = note.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def anki_card_deck_name(info: dict[str, Any]) -> str:
    for key in ("deckName", "deck"):
        value = info.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def imported_model_template_mismatches(
    model_names: set[str] | list[str],
    *,
    strict_video_import: bool = False,
    strict_document_import: bool = False,
) -> dict[str, list[str]]:
    sorted_model_names = sorted(model_names)
    ciba_model_names = [
        name
        for name in sorted_model_names
        if "词霸天下" in name or "ciba" in name.lower()
    ]
    video_template_mismatches = (
        [
            name
            for name in sorted_model_names
            if "沉浸复读 v11" not in name.lower()
        ]
        if strict_video_import
        else []
    )
    document_template_mismatches = (
        [
            name
            for name in sorted_model_names
            if "文档" not in name or "沉浸复读 v11" in name.lower() or "词霸天下" in name or "ciba" in name.lower()
        ]
        if strict_document_import
        else []
    )
    return {
        "ciba_model_names": ciba_model_names,
        "video_template_mismatches": video_template_mismatches,
        "document_template_mismatches": document_template_mismatches,
    }


CORRUPTED_STUDY_TEXT_FIELDS = (
    "Chinese",
    "ChineseFeel",
    "TeacherNote",
    "Why",
    "Context",
    "ChineseLearnerTrap",
    "ConceptualAction",
)
ASCII_REPLACEMENT_RUN_RE = re.compile(r"\?{3,}")


def imported_corrupted_study_text_values(fields: dict[str, Any], card_id: str) -> list[dict[str, str]]:
    values: list[dict[str, str]] = []
    for field_name in CORRUPTED_STUDY_TEXT_FIELDS:
        text = anki_field_plain_text(fields, field_name)
        match = ASCII_REPLACEMENT_RUN_RE.search(text)
        if match:
            values.append(
                {
                    "card_id": card_id,
                    "field": field_name,
                    "pattern": match.group(0),
                    "excerpt": text[:160],
                }
            )
    return values


def anki_import_pronunciation_meta_error(fields: dict[str, Any]) -> str:
    raw = anki_field_plain_text(fields, "PronunciationMeta")
    if not raw:
        return "missing"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as err:
        return f"invalid_json:{err.msg}"
    if not isinstance(parsed, dict):
        return "not_object"
    return ""


def imported_tts_text_hash_mismatches(
    fields: dict[str, Any],
    card_id: str,
    refs_by_field: dict[str, list[str]],
    text_hash_func: Callable[[Any], str],
) -> list[dict[str, str]]:
    mismatches: list[dict[str, str]] = []
    sentence_hash = text_hash_func(anki_field_plain_text(fields, "English"))
    sentence_tts_refs = refs_by_field.get("TtsAudio", [])
    if sentence_hash and sentence_tts_refs and not any(sentence_hash in ref for ref in sentence_tts_refs):
        mismatches.append(
            {
                "card_id": card_id,
                "field": "TtsAudio",
                "expected_text_hash": sentence_hash,
                "refs": ", ".join(sentence_tts_refs),
            }
        )
    phrase_hash = text_hash_func(
        anki_field_plain_text(fields, "Answer") or anki_field_plain_text(fields, "Phrase")
    )
    phrase_tts_refs = refs_by_field.get("PhraseTtsAudio", [])
    if phrase_hash and phrase_tts_refs and not any(phrase_hash in ref for ref in phrase_tts_refs):
        mismatches.append(
            {
                "card_id": card_id,
                "field": "PhraseTtsAudio",
                "expected_text_hash": phrase_hash,
                "refs": ", ".join(phrase_tts_refs),
            }
        )
    return mismatches
