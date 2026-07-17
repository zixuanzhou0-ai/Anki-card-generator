from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import tempfile
import zipfile
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Mapping, Sequence

from acg.anki_export import windows_basename_key, windows_safe_basename
from acg.anki_model_contracts import (
    COMPATIBILITY_CONTRACT_VERSION,
    CONTRACTS_BY_MODEL_ID,
    PRESENTATION_NOTE_FIELDS_SHA256,
    ApkgContractError,
    inspect_referenced_note_models,
    note_model_field_names,
    validate_apkg_archive_structure,
)
from acg.anki_note_identity import note_guid_for_model
from acg.media_refs import extract_media_references


NOTE_CONTENT_FINGERPRINT_SCHEMA_VERSION = 1
NOTE_CONTENT_FINGERPRINT_ALGORITHM = "sha256"
NOTE_CONTENT_FINGERPRINT_SERIALIZATION = "json-field-pairs-v1"

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_MODEL_ID_RE = re.compile(r"[1-9][0-9]*\Z")
_MEDIA_INDEX_RE = re.compile(r"(?:0|[1-9][0-9]*)\Z")
_ANKI_VERSION_TAG_RE = re.compile(r"anki_card_generator_v[0-9]+\Z")
_DANGEROUS_TAG_RE = re.compile(
    r"<\s*/?\s*(?:script|iframe|object|embed|svg|math|form|input|button|link|meta|style)\b",
    re.IGNORECASE,
)
_EVENT_HANDLER_RE = re.compile(r"\bon[a-z0-9_-]+\s*=", re.IGNORECASE)
_ACTIVE_URL_RE = re.compile(
    r"\b(?:href|src|action|formaction|poster)\s*=\s*['\"]?\s*(?:javascript|vbscript|data\s*:\s*text/html)\s*:",
    re.IGNORECASE,
)
_ACTIVE_CSS_RE = re.compile(r"(?:expression\s*\(|url\s*\(\s*['\"]?\s*javascript\s*:)", re.IGNORECASE)

_DISPLAY_FIELDS = frozenset(
    {
        "EnglishDisplay",
        "ChineseDisplay",
        "ChineseFeelDisplay",
        "PronunciationNoteDisplay",
        "ContextDisplay",
        "DefinitionDisplay",
        "TeacherNoteDisplay",
        "TransferExamplesDisplay",
    }
)
_CARD_MEDIA_FIELDS = (
    "video_webm",
    "video_mp4",
    "poster",
    "original_audio",
    "sentence_tts_audio",
    "phrase_tts_audio",
)
_CARD_MEDIA_ROLE_BY_FIELD = {
    "video_webm": "video",
    "video_mp4": "video",
    "poster": "poster",
    "original_audio": "original_audio",
    "sentence_tts_audio": "sentence_tts",
    "phrase_tts_audio": "phrase_tts",
}
_MEDIA_FIELD_BY_ROLE = {
    "video": "Video",
    "poster": "Video",
    "original_audio": "Audio",
    "sentence_tts": "TtsAudio",
    "phrase_tts": "PhraseTtsAudio",
}
_MAX_MEDIA_BYTES = 256 * 1024 * 1024
_MAX_COLLECTION_BYTES = 128 * 1024 * 1024
_MAX_PACKAGE_BYTES = 2 * 1024 * 1024 * 1024
_DECK_KEYS = frozenset(
    {
        "collapsed",
        "conf",
        "desc",
        "dyn",
        "extendNew",
        "extendRev",
        "id",
        "lrnToday",
        "mod",
        "name",
        "newToday",
        "revToday",
        "timeToday",
        "usn",
    }
)
_DEFAULT_DECK_METADATA = {
    "collapsed": False,
    "conf": 1,
    "desc": "",
    "dyn": 0,
    "extendNew": 10,
    "extendRev": 50,
    "id": 1,
    "lrnToday": [0, 0],
    "mod": 1425279151,
    "name": "Default",
    "newToday": [0, 0],
    "revToday": [0, 0],
    "timeToday": [0, 0],
    "usn": 0,
}
_GENANKI_DECK_FIXED_METADATA = {
    "collapsed": False,
    "conf": 1,
    "desc": "",
    "dyn": 0,
    "extendNew": 0,
    "extendRev": 50,
    "lrnToday": [163, 2],
    "mod": 1425278051,
    "newToday": [163, 2],
    "revToday": [163, 0],
    "timeToday": [163, 23598],
    "usn": -1,
}
_COL_SCALAR_CONTRACT = {
    "id": 1,
    "crt": 1411124400,
    "mod": 1425279151694,
    "scm": 1425279151690,
    "ver": 11,
    "dty": 0,
    "usn": 0,
    "ls": 0,
}
_COL_CONF_CONTRACT = {
    "activeDecks": [1],
    "addToCur": True,
    "collapseTime": 1200,
    "curDeck": 1,
    "curModel": "1425279151691",
    "dueCounts": True,
    "estTimes": True,
    "newBury": True,
    "newSpread": 0,
    "nextPos": 1,
    "sortBackwards": False,
    "sortType": "noteFld",
    "timeLim": 0,
}
_COL_DCONF_CONTRACT = {
    "1": {
        "autoplay": True,
        "id": 1,
        "lapse": {
            "delays": [10],
            "leechAction": 0,
            "leechFails": 8,
            "minInt": 1,
            "mult": 0,
        },
        "maxTaken": 60,
        "mod": 0,
        "name": "Default",
        "new": {
            "bury": True,
            "delays": [1, 10],
            "initialFactor": 2500,
            "ints": [1, 4, 7],
            "order": 1,
            "perDay": 20,
            "separate": True,
        },
        "replayq": True,
        "rev": {
            "bury": True,
            "ease4": 1.3,
            "fuzz": 0.05,
            "ivlFct": 1,
            "maxIvl": 36500,
            "minSpace": 1,
            "perDay": 100,
        },
        "timer": 0,
        "usn": 0,
    }
}


class _DuplicateJsonKey(ValueError):
    pass


def _native_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _safe_file_name(value: Any) -> str | None:
    return windows_safe_basename(value)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def note_content_sha256(field_names: Sequence[str], field_values: Sequence[Any]) -> str:
    """Hash complete Anki note fields using the generator's frozen v1 serialization."""

    if len(field_names) != len(field_values):
        raise ValueError("field names and values must have equal lengths")
    field_pairs = [
        [str(name), "" if value is None else str(value)]
        for name, value in zip(field_names, field_values)
    ]
    serialized = json.dumps(field_pairs, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _issue(code: str, message: str, **details: Any) -> dict[str, Any]:
    safe_details = {
        key: value
        for key, value in details.items()
        if value is not None and isinstance(value, (bool, int, float, str, list))
    }
    return {"code": code, "message": message, **safe_details}


def _add(issues: list[dict[str, Any]], code: str, message: str, **details: Any) -> None:
    issues.append(_issue(code, message, **details))


def _strict_object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey(key)
        result[key] = value
    return result


def _load_strict_json_object(
    raw: Any,
    *,
    issues: list[dict[str, Any]],
    invalid_code: str,
    duplicate_code: str,
) -> dict[str, Any] | None:
    if not isinstance(raw, (str, bytes, bytearray)):
        _add(issues, invalid_code, "JSON payload is not text or bytes.")
        return None
    try:
        value = json.loads(raw, object_pairs_hook=_strict_object_pairs)
    except _DuplicateJsonKey:
        _add(issues, duplicate_code, "JSON payload contains a duplicate object key.")
        return None
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
        _add(issues, invalid_code, "JSON payload is malformed.")
        return None
    if not isinstance(value, dict):
        _add(issues, invalid_code, "JSON payload must be an object.")
        return None
    return value


class _FieldHtmlParser(HTMLParser):
    _VOID_TAGS = frozenset({"img", "source"})

    def __init__(self, field_name: str, manifest_names: set[str]):
        super().__init__(convert_charrefs=True)
        self.field_name = field_name
        self.manifest_names = manifest_names
        self.errors: list[str] = []
        self.stack: list[str] = []

    def _allowed_tags(self) -> set[str]:
        if self.field_name == "Video":
            return {"img", "video", "source", "span"}
        if self.field_name in {"Audio", "TtsAudio", "PhraseTtsAudio"}:
            return {"audio", "source"}
        if self.field_name == "TransferExamplesDisplay":
            return {"ul", "li", "mark"}
        if self.field_name in _DISPLAY_FIELDS:
            return {"mark"}
        return set()

    def _check_media_name(self, value: str | None) -> None:
        if _safe_file_name(value) is None or value not in self.manifest_names:
            self.errors.append("media_reference_not_in_manifest")

    def _check_attributes(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        names = [name for name, _value in attrs]
        if len(names) != len(set(names)):
            self.errors.append("duplicate_attribute")
            return
        attributes = dict(attrs)
        if any(name.lower().startswith("on") for name in names):
            self.errors.append("event_handler_attribute")
            return

        allowed: dict[str, set[str]] = {
            "mark": {"class"},
            "ul": {"class"},
            "li": set(),
            "img": {"src", "alt", "style"},
            "video": {"loop", "playsinline", "preload", "controls", "muted", "poster"},
            "audio": {"controls", "preload", "data-audio-role"},
            "source": {"src", "type"},
            "span": {"class", "aria-hidden", "style"},
        }
        if set(names) - allowed.get(tag, set()):
            self.errors.append("attribute_not_allowed")
            return

        if tag == "mark" and attributes != {"class": "target-expression"}:
            self.errors.append("mark_attributes_invalid")
        elif tag == "ul" and attributes != {"class": "v11-example-list"}:
            self.errors.append("list_attributes_invalid")
        elif tag == "li" and attributes:
            self.errors.append("list_item_attributes_invalid")
        elif tag == "img":
            if set(attributes) != {"src", "alt", "style"}:
                self.errors.append("image_attributes_invalid")
            elif attributes.get("alt") != "" or attributes.get("style") != "display:none":
                self.errors.append("image_attributes_invalid")
            else:
                self._check_media_name(attributes.get("src"))
        elif tag == "video":
            required = {"loop", "playsinline", "preload"}
            if not required.issubset(attributes) or attributes.get("preload") != "metadata":
                self.errors.append("video_attributes_invalid")
            if attributes.get("loop") is not None or attributes.get("playsinline") is not None:
                self.errors.append("video_attributes_invalid")
            if "controls" in attributes and attributes.get("controls") is not None:
                self.errors.append("video_attributes_invalid")
            if "muted" in attributes and attributes.get("muted") is not None:
                self.errors.append("video_attributes_invalid")
            if "poster" in attributes:
                self._check_media_name(attributes.get("poster"))
        elif tag == "audio":
            if attributes.get("preload") != "metadata":
                self.errors.append("audio_attributes_invalid")
            if "controls" in attributes and attributes.get("controls") is not None:
                self.errors.append("audio_attributes_invalid")
            allowed_roles = {
                "Audio": "original",
                "TtsAudio": "slow",
                "PhraseTtsAudio": "phrase",
            }
            role = attributes.get("data-audio-role")
            if role is not None and role != allowed_roles.get(self.field_name):
                self.errors.append("audio_role_invalid")
        elif tag == "source":
            if set(attributes) != {"src", "type"}:
                self.errors.append("source_attributes_invalid")
            else:
                allowed_types = (
                    {"video/webm", "video/mp4"}
                    if self.field_name == "Video"
                    else {"audio/mpeg"}
                )
                if attributes.get("type") not in allowed_types:
                    self.errors.append("source_type_invalid")
                self._check_media_name(attributes.get("src"))
        elif tag == "span" and attributes != {
            "class": "anki-video-fallback",
            "aria-hidden": "true",
            "style": "display:none",
        }:
            self.errors.append("span_attributes_invalid")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag not in self._allowed_tags():
            self.errors.append("tag_not_allowed")
            return
        self._check_attributes(tag, attrs)
        if tag not in self._VOID_TAGS:
            self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag not in self._VOID_TAGS:
            self.errors.append("self_closing_tag_not_allowed")
            return
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._VOID_TAGS:
            self.errors.append("void_end_tag")
        elif not self.stack or self.stack[-1] != tag:
            self.errors.append("unbalanced_tag")
        else:
            self.stack.pop()

    def handle_comment(self, _data: str) -> None:
        self.errors.append("comment_not_allowed")

    def handle_decl(self, _decl: str) -> None:
        self.errors.append("declaration_not_allowed")

    def unknown_decl(self, _data: str) -> None:
        self.errors.append("declaration_not_allowed")

    def handle_pi(self, _data: str) -> None:
        self.errors.append("processing_instruction_not_allowed")

    def close(self) -> None:
        super().close()
        if self.stack:
            self.errors.append("unclosed_tag")


def _field_html_errors(field_name: str, value: str, manifest_names: set[str]) -> list[str]:
    if (
        _DANGEROUS_TAG_RE.search(value)
        or _EVENT_HANDLER_RE.search(value)
        or _ACTIVE_URL_RE.search(value)
        or _ACTIVE_CSS_RE.search(value)
    ):
        return ["active_content_detected"]
    parser = _FieldHtmlParser(field_name, manifest_names)
    try:
        parser.feed(value)
        parser.close()
    except (AssertionError, ValueError):
        return ["html_parse_failed"]
    return sorted(set(parser.errors))


def _validate_export_contract(
    export_result: Any,
    apkg_path: Path,
    issues: list[dict[str, Any]],
) -> dict[str, Any]:
    state: dict[str, Any] = {
        "manifest": {},
        "manifest_names": set(),
        "deck_names": [],
        "card_ledger": [],
        "media_ledger": [],
        "media_ledger_keys": set(),
        "media_roles": {},
        "field_names": [],
        "expected_cards": None,
    }
    if not isinstance(export_result, Mapping):
        _add(issues, "EXPORT_RESULT_INVALID", "ExportResult must be an object.")
        return state
    if export_result.get("schema_version") != 2:
        _add(
            issues,
            "EXPORT_SCHEMA_VERSION_INVALID",
            "ExportResult schema version is unsupported.",
        )

    trusted_path = export_result.get("apkg_path")
    if not isinstance(trusted_path, str) or not trusted_path or trusted_path != trusted_path.strip():
        _add(issues, "EXPORT_APKG_PATH_INVALID", "ExportResult APKG path is invalid.")
    else:
        try:
            if Path(trusted_path).resolve() != apkg_path.resolve():
                _add(issues, "EXPORT_APKG_PATH_MISMATCH", "APKG path does not match ExportResult.")
        except OSError:
            _add(issues, "EXPORT_APKG_PATH_INVALID", "ExportResult APKG path cannot be resolved.")

    expected_sha = export_result.get("apkg_sha256")
    if not isinstance(expected_sha, str) or _SHA256_RE.fullmatch(expected_sha) is None:
        _add(issues, "EXPORT_APKG_SHA256_INVALID", "ExportResult APKG SHA-256 is invalid.")
    expected_size = _native_int(export_result.get("apkg_size_bytes"))
    if expected_size is None or expected_size < 0:
        _add(issues, "EXPORT_APKG_SIZE_INVALID", "ExportResult APKG byte size is invalid.")
    try:
        actual_size = apkg_path.stat().st_size
        actual_sha = _file_sha256(apkg_path)
        if expected_size is not None and expected_size >= 0 and actual_size != expected_size:
            _add(issues, "EXPORT_APKG_SIZE_MISMATCH", "APKG byte size differs from ExportResult.")
        if isinstance(expected_sha, str) and _SHA256_RE.fullmatch(expected_sha) and actual_sha != expected_sha:
            _add(issues, "EXPORT_APKG_SHA256_MISMATCH", "APKG SHA-256 differs from ExportResult.")
    except OSError:
        _add(issues, "APKG_FILE_UNREADABLE", "APKG file cannot be read.")

    expected_cards = _native_int(export_result.get("cards"))
    if expected_cards is None or expected_cards <= 0:
        _add(issues, "EXPORT_CARD_COUNT_INVALID", "ExportResult card count must be a positive integer.")
    else:
        state["expected_cards"] = expected_cards

    deck_name = export_result.get("deck_name")
    raw_deck_names = export_result.get("deck_names")
    if not isinstance(deck_name, str) or not deck_name or deck_name != deck_name.strip():
        _add(issues, "EXPORT_DECK_NAME_INVALID", "ExportResult deck name is invalid.")
        deck_name = ""
    if (
        not isinstance(raw_deck_names, list)
        or not raw_deck_names
        or any(not isinstance(name, str) or not name or name != name.strip() for name in raw_deck_names)
        or len(set(raw_deck_names)) != len(raw_deck_names)
    ):
        _add(issues, "EXPORT_DECK_NAMES_INVALID", "ExportResult deck names must be a unique non-empty string list.")
    else:
        state["deck_names"] = list(raw_deck_names)
        if deck_name and not all(name == deck_name or name.startswith(f"{deck_name}::") for name in raw_deck_names):
            _add(issues, "EXPORT_DECK_HIERARCHY_MISMATCH", "Exported decks are outside the declared deck root.")

    manifest = export_result.get("media_manifest")
    if not isinstance(manifest, Mapping):
        _add(issues, "EXPORT_MEDIA_MANIFEST_INVALID", "Media manifest must be an object.")
    else:
        parsed_manifest: dict[str, dict[str, Any]] = {}
        manifest_keys: set[str] = set()
        for name, entry in manifest.items():
            safe_name = _safe_file_name(name)
            name_key = windows_basename_key(safe_name)
            if safe_name is None or name_key is None or name_key in manifest_keys:
                _add(
                    issues,
                    "EXPORT_MEDIA_NAME_INVALID",
                    "Media manifest contains an invalid or Windows-colliding file name.",
                )
                continue
            manifest_keys.add(name_key)
            if not isinstance(entry, Mapping):
                _add(issues, "EXPORT_MEDIA_ENTRY_INVALID", "Media manifest entry must be an object.")
                continue
            digest = entry.get("sha256")
            size = _native_int(entry.get("bytes"))
            if not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None:
                _add(issues, "EXPORT_MEDIA_SHA256_INVALID", "Media manifest SHA-256 is invalid.")
                continue
            if size is None or size < 0 or size > _MAX_MEDIA_BYTES:
                _add(issues, "EXPORT_MEDIA_SIZE_INVALID", "Media manifest byte size is invalid.")
                continue
            parsed_manifest[safe_name] = dict(entry)
        state["manifest"] = parsed_manifest
        state["manifest_names"] = set(parsed_manifest)

    media_summary = export_result.get("media_summary")
    if not isinstance(media_summary, Mapping):
        _add(issues, "EXPORT_MEDIA_SUMMARY_INVALID", "Media summary must be an object.")
    else:
        media_files = _native_int(media_summary.get("media_files"))
        media_bytes = _native_int(media_summary.get("media_bytes"))
        ledger_items = _native_int(media_summary.get("card_media_ledger_items"))
        if media_files is None or media_files < 0:
            _add(issues, "EXPORT_MEDIA_COUNT_INVALID", "Media file count must be a non-negative integer.")
        elif media_files != len(state["manifest"]):
            _add(issues, "EXPORT_MEDIA_COUNT_MISMATCH", "Media file count differs from the manifest.")
        manifest_bytes = sum(int(entry["bytes"]) for entry in state["manifest"].values())
        if media_bytes is None or media_bytes < 0:
            _add(issues, "EXPORT_MEDIA_BYTES_INVALID", "Media byte count must be a non-negative integer.")
        elif media_bytes != manifest_bytes or media_bytes > _MAX_PACKAGE_BYTES:
            _add(issues, "EXPORT_MEDIA_BYTES_MISMATCH", "Media byte count differs from the manifest.")
        if ledger_items is None or ledger_items < 0:
            _add(issues, "EXPORT_CARD_LEDGER_COUNT_INVALID", "Card ledger item count must be a non-negative integer.")
        elif state["expected_cards"] is not None and ledger_items != state["expected_cards"]:
            _add(issues, "EXPORT_CARD_LEDGER_COUNT_MISMATCH", "Card ledger count differs from card count.")

    fingerprint = export_result.get("note_content_fingerprint")
    if not isinstance(fingerprint, Mapping):
        _add(issues, "EXPORT_NOTE_FINGERPRINT_INVALID", "Note fingerprint metadata must be an object.")
    else:
        if fingerprint.get("schema_version") != NOTE_CONTENT_FINGERPRINT_SCHEMA_VERSION:
            _add(issues, "EXPORT_NOTE_FINGERPRINT_SCHEMA_INVALID", "Note fingerprint schema is unsupported.")
        if fingerprint.get("algorithm") != NOTE_CONTENT_FINGERPRINT_ALGORITHM:
            _add(issues, "EXPORT_NOTE_FINGERPRINT_ALGORITHM_INVALID", "Note fingerprint algorithm is unsupported.")
        if fingerprint.get("serialization") != NOTE_CONTENT_FINGERPRINT_SERIALIZATION:
            _add(issues, "EXPORT_NOTE_FINGERPRINT_SERIALIZATION_INVALID", "Note fingerprint serialization is unsupported.")
        raw_fields = fingerprint.get("field_names")
        if (
            not isinstance(raw_fields, list)
            or not raw_fields
            or any(not isinstance(name, str) or not name or name != name.strip() for name in raw_fields)
            or len(set(raw_fields)) != len(raw_fields)
        ):
            _add(issues, "EXPORT_NOTE_FINGERPRINT_FIELDS_INVALID", "Fingerprint field names are invalid.")
        else:
            state["field_names"] = list(raw_fields)
        fingerprint_count = _native_int(fingerprint.get("card_count"))
        if fingerprint_count is None or fingerprint_count <= 0:
            _add(issues, "EXPORT_NOTE_FINGERPRINT_COUNT_INVALID", "Fingerprint card count is invalid.")
        elif state["expected_cards"] is not None and fingerprint_count != state["expected_cards"]:
            _add(issues, "EXPORT_NOTE_FINGERPRINT_COUNT_MISMATCH", "Fingerprint card count differs from ExportResult.")

    card_ledger = export_result.get("card_media_ledger")
    if not isinstance(card_ledger, list) or not card_ledger:
        _add(issues, "EXPORT_CARD_LEDGER_INVALID", "Card media ledger must be a non-empty list.")
    else:
        parsed_ledger: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for item in card_ledger:
            if not isinstance(item, Mapping):
                _add(issues, "EXPORT_CARD_LEDGER_ENTRY_INVALID", "Card media ledger entry must be an object.")
                continue
            card_id = item.get("card_id")
            digest = item.get("note_content_sha256")
            segment_id = item.get("segment_id")
            deck_name = item.get("deck_name")
            note_tags = item.get("note_tags")
            if not isinstance(card_id, str) or not card_id or card_id != card_id.strip() or card_id in seen_ids:
                _add(issues, "EXPORT_CARD_ID_INVALID", "Card media ledger contains an invalid or duplicate CardId.")
                continue
            if (
                not isinstance(segment_id, str)
                or not segment_id
                or segment_id != segment_id.strip()
            ):
                _add(issues, "EXPORT_CARD_SEGMENT_ID_INVALID", "Card media ledger segment identity is invalid.")
                continue
            if (
                not isinstance(deck_name, str)
                or not deck_name
                or deck_name != deck_name.strip()
                or deck_name not in state["deck_names"]
            ):
                _add(issues, "EXPORT_CARD_DECK_NAME_INVALID", "Card media ledger deck identity is invalid.")
                continue
            if not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None:
                _add(issues, "EXPORT_NOTE_SHA256_INVALID", "Card media ledger note SHA-256 is invalid.")
                continue
            if (
                not isinstance(note_tags, list)
                or len(note_tags) != 6
                or any(
                    not isinstance(tag, str)
                    or not tag
                    or tag != tag.strip()
                    or any(character.isspace() for character in tag)
                    for tag in note_tags
                )
                or len(set(note_tags)) != 6
                or str(export_result.get("anki_tag") or "") not in note_tags
            ):
                _add(issues, "EXPORT_NOTE_TAGS_INVALID", "Card media ledger note tags are invalid.")
                continue
            media_types_valid = True
            for field in _CARD_MEDIA_FIELDS:
                value = item.get(field, "")
                if not isinstance(value, str):
                    _add(issues, "EXPORT_CARD_MEDIA_REFERENCE_INVALID", "Card media reference must be a string.")
                    media_types_valid = False
                    break
                if value and (_safe_file_name(value) is None or value not in state["manifest_names"]):
                    _add(issues, "EXPORT_CARD_MEDIA_REFERENCE_MISSING", "Card media reference is absent from the manifest.")
                    media_types_valid = False
                    break
            if media_types_valid:
                seen_ids.add(card_id)
                parsed_ledger.append(dict(item))
        state["card_ledger"] = parsed_ledger
        if state["expected_cards"] is not None and len(parsed_ledger) != state["expected_cards"]:
            _add(issues, "EXPORT_CARD_LEDGER_LENGTH_MISMATCH", "Card ledger length differs from card count.")

    media_ledger = export_result.get("media_ledger")
    if not isinstance(media_ledger, list):
        _add(issues, "EXPORT_MEDIA_LEDGER_INVALID", "Media ledger must be a list.")
    else:
        parsed_media_ledger: list[dict[str, Any]] = []
        ledger_names: set[str] = set()
        ledger_keys: set[tuple[str, str, str, str]] = set()
        roles_by_file: dict[str, str] = {}
        for item in media_ledger:
            if not isinstance(item, Mapping):
                _add(issues, "EXPORT_MEDIA_LEDGER_ENTRY_INVALID", "Media ledger entry must be an object.")
                continue
            name = item.get("file")
            if _safe_file_name(name) is None or name not in state["manifest_names"]:
                _add(issues, "EXPORT_MEDIA_LEDGER_FILE_INVALID", "Media ledger file is absent from the manifest.")
                continue
            role = item.get("role")
            segment_id = item.get("segment_id")
            card_id = item.get("card_id", "")
            field = item.get("field")
            if (
                role not in _MEDIA_FIELD_BY_ROLE
                or field != _MEDIA_FIELD_BY_ROLE.get(str(role))
                or not isinstance(segment_id, str)
                or not segment_id
                or segment_id != segment_id.strip()
                or not isinstance(card_id, str)
                or card_id != card_id.strip()
                or (role == "phrase_tts" and not card_id)
                or (role != "phrase_tts" and bool(card_id))
            ):
                _add(issues, "EXPORT_MEDIA_LEDGER_OWNER_INVALID", "Media ledger ownership metadata is invalid.")
                continue
            identity = (str(name), str(role), segment_id, card_id)
            if identity in ledger_keys:
                _add(issues, "EXPORT_MEDIA_LEDGER_DUPLICATE", "Media ledger contains a duplicate ownership entry.")
                continue
            existing_role = roles_by_file.get(str(name))
            if existing_role is not None and existing_role != role:
                _add(issues, "EXPORT_MEDIA_LEDGER_ROLE_CONFLICT", "One media file is assigned conflicting roles.")
                continue
            ledger_keys.add(identity)
            roles_by_file[str(name)] = str(role)
            ledger_names.add(name)
            parsed_media_ledger.append(dict(item))
        state["media_ledger"] = parsed_media_ledger
        state["media_ledger_keys"] = ledger_keys
        state["media_roles"] = roles_by_file
        if ledger_names != state["manifest_names"]:
            _add(issues, "EXPORT_MEDIA_LEDGER_COVERAGE_MISMATCH", "Media ledger does not cover the manifest exactly.")

        expected_ownership: set[tuple[str, str, str, str]] = set()
        for card_item in state["card_ledger"]:
            card_id = str(card_item.get("card_id") or "")
            segment_id = str(card_item.get("segment_id") or "")
            for card_field, role in _CARD_MEDIA_ROLE_BY_FIELD.items():
                file_name = str(card_item.get(card_field) or "")
                if file_name:
                    expected_ownership.add(
                        (
                            file_name,
                            role,
                            segment_id,
                            card_id if role == "phrase_tts" else "",
                        )
                    )
        if ledger_keys != expected_ownership:
            _add(
                issues,
                "EXPORT_CARD_MEDIA_OWNERSHIP_MISMATCH",
                "Card media references and media ledger ownership differ.",
            )

        for file_name, manifest_entry in state["manifest"].items():
            role = manifest_entry.get("role")
            if role != roles_by_file.get(file_name):
                _add(
                    issues,
                    "EXPORT_MEDIA_MANIFEST_ROLE_MISMATCH",
                    "Media manifest role differs from the media ledger.",
                )
                continue
            manifest_segment = manifest_entry.get("segment_id")
            manifest_card = manifest_entry.get("card_id", "")
            manifest_identity = (
                file_name,
                str(role),
                str(manifest_segment or ""),
                str(manifest_card or ""),
            )
            if manifest_identity not in ledger_keys:
                _add(
                    issues,
                    "EXPORT_MEDIA_MANIFEST_OWNER_MISMATCH",
                    "Media manifest owner is absent from the media ledger.",
                )

    return state


def _read_collection_database(payload: bytes) -> tuple[sqlite3.Connection | None, Path | None]:
    connection = sqlite3.connect(":memory:")
    try:
        deserialize = getattr(connection, "deserialize", None)
        if callable(deserialize):
            deserialize(payload)
            return connection, None
    except sqlite3.Error:
        connection.close()
    else:
        connection.close()

    handle = tempfile.NamedTemporaryFile(suffix=".anki2", delete=False)
    temp_path = Path(handle.name)
    try:
        handle.write(payload)
        handle.close()
        return sqlite3.connect(temp_path), temp_path
    except Exception:
        handle.close()
        temp_path.unlink(missing_ok=True)
        raise


def _validate_archive_and_media(
    apkg_path: Path,
    state: dict[str, Any],
    issues: list[dict[str, Any]],
) -> bytes | None:
    try:
        with zipfile.ZipFile(apkg_path) as archive:
            collection_name = validate_apkg_archive_structure(archive)
            infos = archive.infolist()
            names = [info.filename for info in infos]
            duplicate_names = sorted(name for name, count in Counter(names).items() if count != 1)
            if duplicate_names:
                _add(issues, "APKG_ARCHIVE_ENTRY_DUPLICATE", "APKG contains duplicate archive entries.", count=len(duplicate_names))

            media_map = _load_strict_json_object(
                archive.read("media"),
                issues=issues,
                invalid_code="APKG_MEDIA_MAP_INVALID",
                duplicate_code="APKG_MEDIA_MAP_DUPLICATE_KEY",
            )
            if media_map is None:
                return archive.read(collection_name)

            parsed_map: dict[str, str] = {}
            seen_file_name_keys: set[str] = set()
            for index, file_name in media_map.items():
                if not isinstance(index, str) or _MEDIA_INDEX_RE.fullmatch(index) is None:
                    _add(issues, "APKG_MEDIA_INDEX_INVALID", "APKG media index is not canonical.")
                    continue
                safe_name = _safe_file_name(file_name)
                name_key = windows_basename_key(safe_name)
                if safe_name is None or name_key is None or name_key in seen_file_name_keys:
                    _add(
                        issues,
                        "APKG_MEDIA_FILE_NAME_INVALID",
                        "APKG media map contains an invalid or Windows-colliding file name.",
                    )
                    continue
                parsed_map[index] = safe_name
                seen_file_name_keys.add(name_key)

            expected_indexes = {str(index) for index in range(len(parsed_map))}
            if set(parsed_map) != expected_indexes:
                _add(issues, "APKG_MEDIA_INDEX_SET_MISMATCH", "APKG media indexes are not contiguous from zero.")
            if set(parsed_map.values()) != state["manifest_names"]:
                _add(issues, "APKG_MEDIA_NAME_SET_MISMATCH", "APKG media names differ from ExportResult manifest.")

            expected_archive_names = {collection_name, "media", *parsed_map.keys()}
            if set(names) != expected_archive_names:
                _add(issues, "APKG_ARCHIVE_ENTRY_SET_MISMATCH", "APKG contains missing or unexpected archive entries.")

            name_counts = Counter(names)
            info_by_name = {info.filename: info for info in infos if name_counts[info.filename] == 1}
            for index, file_name in parsed_map.items():
                info = info_by_name.get(index)
                manifest_entry = state["manifest"].get(file_name)
                if info is None or manifest_entry is None:
                    continue
                if info.file_size != manifest_entry.get("bytes"):
                    _add(issues, "APKG_MEDIA_SIZE_MISMATCH", "Packaged media size differs from ExportResult manifest.")
                    continue
                digest = hashlib.sha256()
                streamed_bytes = 0
                with archive.open(info, "r") as media_stream:
                    while True:
                        chunk = media_stream.read(1024 * 1024)
                        if not chunk:
                            break
                        streamed_bytes += len(chunk)
                        if streamed_bytes > _MAX_MEDIA_BYTES:
                            raise ApkgContractError(
                                "UNSAFE_APKG_ARCHIVE",
                                "Packaged media exceeds the streaming safety limit.",
                            )
                        digest.update(chunk)
                if streamed_bytes != info.file_size:
                    _add(issues, "APKG_MEDIA_SIZE_MISMATCH", "Packaged media stream size is inconsistent.")
                    continue
                if digest.hexdigest() != manifest_entry.get("sha256"):
                    _add(issues, "APKG_MEDIA_SHA256_MISMATCH", "Packaged media SHA-256 differs from ExportResult manifest.")

            collection_info = info_by_name.get(collection_name)
            if collection_info is None or collection_info.file_size > _MAX_COLLECTION_BYTES:
                raise ApkgContractError(
                    "UNSAFE_APKG_ARCHIVE",
                    "Collection database exceeds the safety limit.",
                )
            return archive.read(collection_info)
    except ApkgContractError as exc:
        _add(issues, exc.code, "APKG archive structure violates the frozen contract.")
    except (OSError, zipfile.BadZipFile, KeyError, RuntimeError):
        _add(issues, "APKG_ARCHIVE_INVALID", "APKG archive cannot be inspected safely.")
    return None


def _validate_collection(
    collection_payload: bytes,
    state: dict[str, Any],
    export_result: Mapping[str, Any],
    issues: list[dict[str, Any]],
) -> dict[str, int]:
    counts = {"notes": 0, "cards": 0, "decks": 0, "media": len(state["manifest"])}
    connection: sqlite3.Connection | None = None
    temp_path: Path | None = None
    try:
        connection, temp_path = _read_collection_database(collection_payload)
        if connection is None:
            raise sqlite3.DatabaseError("collection unavailable")
        connection.execute("pragma query_only = on")

        col_rows = connection.execute(
            "select id,crt,mod,scm,ver,dty,usn,ls,conf,models,decks,dconf,tags from col"
        ).fetchall()
        if len(col_rows) != 1 or _native_int(col_rows[0][0]) != 1:
            _add(issues, "APKG_COL_ROW_INVALID", "Collection must contain exactly one col row with id=1.")
            if not col_rows:
                return counts
        col_row = col_rows[0]
        scalar_values = dict(
            zip(
                ("id", "crt", "mod", "scm", "ver", "dty", "usn", "ls"),
                col_row[:8],
            )
        )
        if scalar_values != _COL_SCALAR_CONTRACT:
            _add(issues, "APKG_COL_METADATA_INVALID", "Collection metadata differs from genanki 0.13.1.")
        conf = _load_strict_json_object(
            col_row[8],
            issues=issues,
            invalid_code="APKG_COL_CONF_INVALID",
            duplicate_code="APKG_COL_CONF_DUPLICATE_KEY",
        )
        if conf is not None and conf != _COL_CONF_CONTRACT:
            _add(issues, "APKG_COL_CONF_INVALID", "Collection preferences differ from genanki 0.13.1.")
        models_raw, decks_raw = col_row[9], col_row[10]
        dconf = _load_strict_json_object(
            col_row[11],
            issues=issues,
            invalid_code="APKG_COL_DCONF_INVALID",
            duplicate_code="APKG_COL_DCONF_DUPLICATE_KEY",
        )
        if dconf is not None and dconf != _COL_DCONF_CONTRACT:
            _add(issues, "APKG_COL_DCONF_INVALID", "Deck configuration differs from genanki 0.13.1.")
        collection_tags = _load_strict_json_object(
            col_row[12],
            issues=issues,
            invalid_code="APKG_COL_TAGS_INVALID",
            duplicate_code="APKG_COL_TAGS_DUPLICATE_KEY",
        )
        if collection_tags is not None and collection_tags:
            _add(issues, "APKG_COL_TAGS_INVALID", "Collection tag registry must be empty.")
        models = _load_strict_json_object(
            models_raw,
            issues=issues,
            invalid_code="APKG_MODELS_JSON_INVALID",
            duplicate_code="APKG_MODELS_JSON_DUPLICATE_KEY",
        )
        decks = _load_strict_json_object(
            decks_raw,
            issues=issues,
            invalid_code="APKG_DECKS_JSON_INVALID",
            duplicate_code="APKG_DECKS_JSON_DUPLICATE_KEY",
        )

        notes = connection.execute(
            "select id,guid,mid,mod,usn,tags,flds,sfld,csum,flags,data from notes order by id"
        ).fetchall()
        cards = connection.execute(
            "select id,nid,did,ord,mod,usn,type,queue,due,ivl,factor,reps,lapses,left,odue,odid,flags,data "
            "from cards order by id"
        ).fetchall()
        counts["notes"] = len(notes)
        counts["cards"] = len(cards)
        if connection.execute("select count(*) from revlog").fetchone()[0] != 0:
            _add(issues, "APKG_REVLOG_NOT_EMPTY", "Generated APKG must not contain review history.")
        if connection.execute("select count(*) from graves").fetchone()[0] != 0:
            _add(issues, "APKG_GRAVES_NOT_EMPTY", "Generated APKG must not contain deleted-object history.")

        expected_cards = state["expected_cards"]
        if expected_cards is not None and (len(notes) != expected_cards or len(cards) != expected_cards):
            _add(issues, "APKG_NOTE_CARD_COUNT_MISMATCH", "APKG note/card counts differ from ExportResult.")
        if len(notes) != len(cards):
            _add(issues, "APKG_NOTE_CARD_RELATION_INVALID", "APKG must contain exactly one card per note.")

        note_ids = [row[0] for row in notes]
        if any(_native_int(value) is None or value <= 0 for value in note_ids) or len(set(note_ids)) != len(note_ids):
            _add(issues, "APKG_NOTE_ID_INVALID", "APKG note IDs are invalid or duplicated.")
        card_ids = [row[0] for row in cards]
        if any(_native_int(value) is None or value <= 0 for value in card_ids) or len(set(card_ids)) != len(card_ids):
            _add(issues, "APKG_CARD_ID_INVALID", "APKG card IDs are invalid or duplicated.")
        guids = [row[1] for row in notes]
        if any(not isinstance(value, str) or not value for value in guids) or len(set(guids)) != len(guids):
            _add(issues, "APKG_NOTE_GUID_INVALID", "APKG note GUIDs are empty or duplicated.")

        cards_by_note = Counter(row[1] for row in cards)
        if set(cards_by_note) != set(note_ids) or any(count != 1 for count in cards_by_note.values()):
            _add(issues, "APKG_NOTE_CARD_LINK_INVALID", "Cards do not map one-to-one to notes.")
        if any(_native_int(row[3]) != 0 for row in cards):
            _add(issues, "APKG_CARD_TEMPLATE_ORD_INVALID", "Cards must use the single frozen template ordinal.")
        note_mod_by_id = {row[0]: row[3] for row in notes}
        for row in notes:
            note_tags = row[5]
            tag_items = note_tags[1:-1].split(" ") if isinstance(note_tags, str) and note_tags.startswith(" ") and note_tags.endswith(" ") else []
            if (
                _native_int(row[3]) is None
                or row[3] <= 0
                or row[4] != -1
                or len(tag_items) != 6
                or any(not tag for tag in tag_items)
                or len(set(tag_items)) != len(tag_items)
                or str(export_result.get("anki_tag") or "") not in tag_items
                or not isinstance(row[6], str)
                or row[7] != row[6].split("\x1f", 1)[0]
                or row[8] != 0
                or row[9] != 0
                or row[10] != ""
            ):
                _add(issues, "APKG_NOTE_METADATA_INVALID", "Note metadata differs from the frozen generator contract.")
                break
        for row in cards:
            fixed_schedule = row[5:] == (-1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, "")
            if (
                _native_int(row[4]) is None
                or row[4] <= 0
                or row[4] != note_mod_by_id.get(row[1])
                or not fixed_schedule
            ):
                _add(issues, "APKG_CARD_SCHEDULING_INVALID", "Card scheduling metadata differs from genanki 0.13.1.")
                break

        parsed_decks: dict[int, str] = {}
        expected_deck_ids: set[int] = set()
        if decks is not None:
            for key, deck in decks.items():
                parsed_id = int(key) if isinstance(key, str) and _MODEL_ID_RE.fullmatch(key) else None
                if parsed_id is None or not isinstance(deck, Mapping):
                    _add(issues, "APKG_DECK_REGISTRY_INVALID", "Deck registry entry is invalid.")
                    continue
                if set(deck) != _DECK_KEYS:
                    _add(
                        issues,
                        "APKG_DECK_METADATA_INVALID",
                        "Deck metadata keys differ from genanki 0.13.1.",
                    )
                    continue
                embedded_id = _native_int(deck.get("id"))
                name = deck.get("name")
                if embedded_id != parsed_id or not isinstance(name, str) or not name or name != name.strip():
                    _add(issues, "APKG_DECK_IDENTITY_INVALID", "Deck registry identity is invalid.")
                    continue
                if name in parsed_decks.values():
                    _add(issues, "APKG_DECK_NAME_DUPLICATE", "Deck registry contains duplicate names.")
                    continue
                expected_deck = (
                    _DEFAULT_DECK_METADATA
                    if parsed_id == 1
                    else {**_GENANKI_DECK_FIXED_METADATA, "id": parsed_id, "name": name}
                )
                if dict(deck) != expected_deck:
                    _add(
                        issues,
                        "APKG_DECK_METADATA_INVALID",
                        "Deck metadata values differ from genanki 0.13.1.",
                    )
                    continue
                parsed_decks[parsed_id] = name
            counts["decks"] = len(parsed_decks)
            expected_names = {"Default", *state["deck_names"]}
            if set(parsed_decks.values()) != expected_names:
                _add(issues, "APKG_DECK_NAME_SET_MISMATCH", "Deck registry names differ from ExportResult.")
            if parsed_decks.get(1) != "Default":
                _add(issues, "APKG_DEFAULT_DECK_INVALID", "Built-in Default deck identity is invalid.")
            expected_deck_ids = {
                deck_id for deck_id, name in parsed_decks.items() if name in set(state["deck_names"])
            }
            card_deck_ids = {row[2] for row in cards}
            if any(_native_int(value) is None for value in card_deck_ids) or not card_deck_ids.issubset(expected_deck_ids):
                _add(issues, "APKG_CARD_DECK_LINK_INVALID", "Cards reference a deck outside ExportResult.")

        referenced_mids = [row[2] for row in notes]
        contract = None
        if models is not None:
            model_report = inspect_referenced_note_models(
                models,
                referenced_mids,
                require_exact_registry=True,
                require_single_referenced_model=True,
                deck_ids=set(parsed_decks),
            )
            for model_issue in model_report.get("issues", []):
                _add(
                    issues,
                    str(model_issue.get("code") or "NOTE_MODEL_CONTRACT_INVALID"),
                    "APKG Note Model violates the frozen contract.",
                )
            contracts = model_report.get("contracts", [])
            if len(contracts) == 1:
                contract = contracts[0]

        if contract is not None:
            model_id = contract.get("noteModelId")
            contract_object = CONTRACTS_BY_MODEL_ID.get(model_id)
            if contract_object is None:
                _add(issues, "NOTE_MODEL_CONTRACT_UNAVAILABLE", "Resolved Note Model contract is unavailable.")
            else:
                expected_field_names = list(
                    note_model_field_names(
                        contract_object.ordered_fields_sha256 == PRESENTATION_NOTE_FIELDS_SHA256
                    )
                )
                if state["field_names"] != expected_field_names:
                    _add(issues, "EXPORT_NOTE_FIELDS_MISMATCH", "ExportResult fingerprint fields differ from Note Model.")
                identity_checks = {
                    "template_family": contract_object.template_family,
                    "template_schema": contract_object.template_schema,
                    "template_version": contract_object.template_schema,
                    "template_name": contract_object.template_name,
                    "note_model_id": contract_object.note_model_id,
                    "model_name": contract_object.model_name,
                    "compatibility_contract_version": COMPATIBILITY_CONTRACT_VERSION,
                    "note_model_contract_digest": contract_object.contract_digest,
                }
                if any(export_result.get(key) != expected for key, expected in identity_checks.items()):
                    _add(issues, "EXPORT_NOTE_MODEL_IDENTITY_MISMATCH", "ExportResult Note Model identity differs from APKG.")
                expected_anki_tag = (
                    f"anki_card_generator_{contract_object.template_schema.lower()}"
                )
                if export_result.get("anki_tag") != expected_anki_tag:
                    _add(
                        issues,
                        "EXPORT_ANKI_TAG_SCHEMA_MISMATCH",
                        "ExportResult Anki tag differs from the frozen template schema.",
                    )
                for ledger_item in state["card_ledger"]:
                    ledger_tags = ledger_item.get("note_tags")
                    version_tags = (
                        [
                            tag
                            for tag in ledger_tags
                            if isinstance(tag, str) and _ANKI_VERSION_TAG_RE.fullmatch(tag)
                        ]
                        if isinstance(ledger_tags, list)
                        else []
                    )
                    if version_tags != [expected_anki_tag]:
                        _add(
                            issues,
                            "EXPORT_NOTE_VERSION_TAG_MISMATCH",
                            "Card ledger must contain exactly the template schema Anki tag.",
                        )
                        break
                if models is not None:
                    model = models.get(str(contract_object.note_model_id))
                    model_did = _native_int(model.get("did")) if isinstance(model, Mapping) else None
                    if expected_deck_ids and model_did not in expected_deck_ids:
                        _add(issues, "APKG_MODEL_DECK_LINK_INVALID", "Note Model references a deck outside ExportResult.")

                ledger_by_card_id = {
                    item["card_id"]: item
                    for item in state["card_ledger"]
                    if isinstance(item.get("card_id"), str)
                }
                note_card_ids: set[str] = set()
                manifest_names = state["manifest_names"]
                card_by_note_id = {row[1]: row for row in cards}
                for note_row in notes:
                    note_id = note_row[0]
                    mid = note_row[2]
                    flds = note_row[6]
                    if mid != contract_object.note_model_id:
                        _add(issues, "APKG_NOTE_MODEL_LINK_INVALID", "A note references the wrong Note Model.")
                        continue
                    if not isinstance(flds, str):
                        _add(issues, "APKG_NOTE_FIELDS_INVALID", "Anki note fields are not text.")
                        continue
                    note_tag_text = note_row[5]
                    note_tag_items = (
                        note_tag_text[1:-1].split(" ")
                        if isinstance(note_tag_text, str)
                        and note_tag_text.startswith(" ")
                        and note_tag_text.endswith(" ")
                        else []
                    )
                    version_tags = [
                        tag
                        for tag in note_tag_items
                        if _ANKI_VERSION_TAG_RE.fullmatch(tag)
                    ]
                    if version_tags != [
                        f"anki_card_generator_{contract_object.template_schema.lower()}"
                    ]:
                        _add(
                            issues,
                            "APKG_NOTE_VERSION_TAG_MISMATCH",
                            "Anki note must contain exactly the template schema version tag.",
                        )
                    values = flds.split("\x1f")
                    if len(values) != len(expected_field_names):
                        _add(issues, "APKG_NOTE_FIELD_COUNT_MISMATCH", "Anki note field count differs from Note Model.")
                        continue
                    fields = dict(zip(expected_field_names, values))
                    card_id = fields.get("CardId", "")
                    if not card_id or card_id != card_id.strip() or card_id in note_card_ids:
                        _add(issues, "APKG_NOTE_CARD_ID_INVALID", "Anki note CardId is empty or duplicated.")
                        continue
                    note_card_ids.add(card_id)
                    ledger_item = ledger_by_card_id.get(card_id)
                    if ledger_item is None:
                        _add(issues, "APKG_NOTE_LEDGER_LINK_MISSING", "Anki note CardId is absent from the card ledger.")
                    else:
                        if note_content_sha256(expected_field_names, values) != ledger_item.get("note_content_sha256"):
                            _add(issues, "APKG_NOTE_CONTENT_SHA256_MISMATCH", "Anki note fields differ from the card ledger fingerprint.")
                        if note_tag_items != ledger_item.get("note_tags"):
                            _add(issues, "APKG_NOTE_TAGS_MISMATCH", "Anki note tags differ from the card ledger.")
                        if note_row[1] != note_guid_for_model(
                            contract_object.note_model_id,
                            values,
                        ):
                            _add(
                                issues,
                                "APKG_NOTE_GUID_MISMATCH",
                                "Anki note GUID differs from the frozen Note Model identity contract.",
                            )
                        note_card = card_by_note_id.get(note_id)
                        card_deck_name = parsed_decks.get(note_card[2]) if note_card is not None else None
                        if card_deck_name != ledger_item.get("deck_name"):
                            _add(
                                issues,
                                "APKG_NOTE_LEDGER_DECK_MISMATCH",
                                "CardId resolves to a deck different from the card ledger.",
                            )
                        expected_refs_by_field = {
                            "Video": {
                                str(ledger_item.get("video_webm") or ""),
                                str(ledger_item.get("video_mp4") or ""),
                                str(ledger_item.get("poster") or ""),
                            }
                            - {""},
                            "Audio": {str(ledger_item.get("original_audio") or "")} - {""},
                            "TtsAudio": {str(ledger_item.get("sentence_tts_audio") or "")} - {""},
                            "PhraseTtsAudio": {str(ledger_item.get("phrase_tts_audio") or "")} - {""},
                        }
                        actual_refs_by_field = {
                            field_name: set(extract_media_references(fields.get(field_name, "")))
                            for field_name in expected_refs_by_field
                        }
                        if actual_refs_by_field != expected_refs_by_field:
                            _add(
                                issues,
                                "APKG_NOTE_CARD_MEDIA_MISMATCH",
                                "Controlled Anki media fields differ from the card ledger.",
                            )

                    for field_name, value in fields.items():
                        html_errors = _field_html_errors(field_name, value, manifest_names)
                        if html_errors:
                            _add(
                                issues,
                                "APKG_NOTE_FIELD_HTML_UNSAFE",
                                "Anki note field contains HTML outside the field allowlist.",
                                field=field_name,
                                rules=html_errors,
                            )
                if note_card_ids != set(ledger_by_card_id):
                    _add(issues, "APKG_NOTE_CARD_ID_SET_MISMATCH", "APKG CardIds differ from the card ledger.")

    except (sqlite3.Error, OSError, ValueError, TypeError):
        _add(issues, "APKG_COLLECTION_DATABASE_INVALID", "APKG collection database cannot be inspected safely.")
    finally:
        if connection is not None:
            connection.close()
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
            Path(f"{temp_path}-shm").unlink(missing_ok=True)
            Path(f"{temp_path}-wal").unlink(missing_ok=True)
    return counts


def validate_apkg_package_contract(
    apkg_path: str | Path,
    export_result: Mapping[str, Any] | Any,
) -> dict[str, Any]:
    """Perform a complete, offline, fail-closed APKG/ExportResult write preflight.

    The report intentionally contains codes, counts, and field names only. It
    never includes note contents, credentials, full local paths, or exception
    strings, so callers can safely surface it in task diagnostics.
    """

    issues: list[dict[str, Any]] = []
    path = Path(apkg_path)
    try:
        if not path.is_file():
            _add(issues, "APKG_FILE_MISSING", "APKG file does not exist.")
    except OSError:
        _add(issues, "APKG_FILE_UNREADABLE", "APKG file cannot be inspected.")

    state = _validate_export_contract(export_result, path, issues)
    collection_payload = _validate_archive_and_media(path, state, issues) if path.is_file() else None
    counts = {
        "notes": 0,
        "cards": 0,
        "decks": 0,
        "media": len(state["manifest"]),
    }
    if collection_payload is not None and isinstance(export_result, Mapping):
        counts = _validate_collection(collection_payload, state, export_result, issues)

    unique_issues: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in issues:
        marker = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if marker not in seen:
            seen.add(marker)
            unique_issues.append(item)
    return {
        "ok": not unique_issues,
        "issues": unique_issues,
        "summary": {
            **counts,
            "issue_count": len(unique_issues),
            "contract_version": COMPATIBILITY_CONTRACT_VERSION,
        },
    }


__all__ = ["note_content_sha256", "validate_apkg_package_contract"]
