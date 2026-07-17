from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


COMPATIBILITY_CONTRACT_VERSION = 1

MAX_ARCHIVE_MEDIA_ENTRIES = 2000
MAX_ARCHIVE_MEDIA_BYTES = 256 * 1024 * 1024
MAX_ARCHIVE_COLLECTION_BYTES = 128 * 1024 * 1024
MAX_ARCHIVE_MEDIA_MAP_BYTES = 2 * 1024 * 1024
MAX_ARCHIVE_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
COLLECTION_ENTRY_NAMES = frozenset({"collection.anki2", "collection.anki21"})
MODEL_STATIC_KEYS = frozenset(
    {
        "css",
        "did",
        "flds",
        "id",
        "latexPost",
        "latexPre",
        "latexsvg",
        "mod",
        "name",
        "req",
        "sortf",
        "tags",
        "tmpls",
        "type",
        "usn",
        "vers",
    }
)
FIELD_SPEC_KEYS = frozenset({"font", "media", "name", "ord", "rtl", "size", "sticky"})
TEMPLATE_KEYS = frozenset({"afmt", "bafmt", "bfont", "bqfmt", "bsize", "did", "name", "ord", "qfmt"})
MODEL_EXTRA_KEYS = ("latexPost", "latexPre", "latexsvg", "req", "tags", "vers")
TEMPLATE_EXTRA_KEYS = ("did", "bfont", "bsize")

V14_FIELD_SPECS_SHA256 = "1484fc9c5bc61ed2b63485e3607795e184e2a8af10f8b155054a477a5e82e11c"
BASE_FIELD_SPECS_SHA256 = "ade94901df52485b2436a8f1cb535083ca7e59dc89dd64f5058c6b073b44adae"
TEMPLATE_EXTRAS_SHA256 = "9756390bef591eb7cbf867d563aa2462fae3cabe2e50e742b869f97750866380"
V14_MODEL_EXTRAS_SHA256 = "e0e0978d2726760ac09e9a1b3e92347935eedd740be7d69b1a9d590dc16b6fb6"
V12_CIBA_MODEL_EXTRAS_SHA256 = "206dacf225da250502de2f246ec88f8ed2cbee0a29ba91bc7a36dab71e7c3c84"
V10_IMMERSIVE_MODEL_EXTRAS_SHA256 = "3928b6247f55efcfac28258ed340a382f67ba96890fc44b51bd9413367b85f43"
V10_BASE_MODEL_EXTRAS_SHA256 = "2d96bc505e320bc056f39613193322599d4b6506f5ad23ce12ffcdd29eaf8dfc"

PRESENTATION_FIELD_NAMES = (
    "EnglishDisplay",
    "ChineseDisplay",
    "ChineseFeelDisplay",
    "PronunciationNoteDisplay",
    "ContextDisplay",
    "DefinitionDisplay",
    "TeacherNoteDisplay",
    "TransferExamplesDisplay",
)

BASE_NOTE_FIELD_NAMES = (
    "CardId",
    "CardType",
    "Video",
    "Audio",
    "TtsAudio",
    "PhraseTtsAudio",
    "IsListening",
    "FrontPrompt",
    "FrontContent",
    "Answer",
    "PhoneticIpa",
    "SpokenIpa",
    "SourceSpokenIpa",
    "PronunciationNote",
    "PronunciationConfidence",
    "PronunciationStatus",
    "SourcePronunciationStatus",
    "PronunciationMeta",
    "SpokenPronunciationLabel",
    "StandardPronunciationHint",
    "English",
    "Chinese",
    "Phrase",
    "Definition",
    "Collocations",
    "Context",
    "Example",
    "ChineseFeel",
    "Why",
    "Difficulty",
    "SourceTime",
    "TeacherNote",
    "LearningAction",
    "ConceptualAction",
    "ChineseLearnerTrap",
    "Cloze",
    "CardLayout",
    "CardVisualRole",
    "FrontKicker",
    "SourceLabel",
    "UnderstandLabel",
    "UseLabel",
)

BASE_NOTE_FIELDS_SHA256 = "aab8dad5dfd6bb010ffddfcb56dc9b04bad0a803adf6fac6df8a35f233e8f6de"
PRESENTATION_NOTE_FIELDS_SHA256 = "5f55885a8307c2d7320ea1184d79425cffea66ccd53d29694bca88c8fdc1e44b"
V14_NOTE_FIELDS_SHA256 = PRESENTATION_NOTE_FIELDS_SHA256


def text_sha256(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def canonical_json_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def ordered_field_names_sha256(field_names: Iterable[str]) -> str:
    payload = json.dumps(
        [str(name) for name in field_names],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def note_model_field_names(include_presentation: bool) -> tuple[str, ...]:
    if not include_presentation:
        return BASE_NOTE_FIELD_NAMES
    english_index = BASE_NOTE_FIELD_NAMES.index("English") + 1
    return (
        *BASE_NOTE_FIELD_NAMES[:english_index],
        *PRESENTATION_FIELD_NAMES,
        *BASE_NOTE_FIELD_NAMES[english_index:],
    )


def note_model_field_specs(include_presentation: bool) -> list[dict[str, str]]:
    return [{"name": name} for name in note_model_field_names(include_presentation)]


@dataclass(frozen=True)
class NoteModelContract:
    template_family: str
    template_schema: str
    note_model_id: int
    model_name: str
    template_name: str
    ordered_fields_sha256: str
    css_sha256: str
    qfmt_sha256: str
    afmt_sha256: str
    support_status: str = "current"
    model_type: int = 0
    sort_field: int = 0
    template_ordinal: int = 0
    bqfmt: str = ""
    bafmt: str = ""
    field_specs_sha256: str = ""
    model_extras_sha256: str = ""
    template_extras_sha256: str = TEMPLATE_EXTRAS_SHA256

    def __post_init__(self) -> None:
        if not self.field_specs_sha256:
            field_digest = (
                V14_FIELD_SPECS_SHA256
                if self.ordered_fields_sha256 == PRESENTATION_NOTE_FIELDS_SHA256
                else BASE_FIELD_SPECS_SHA256
            )
            object.__setattr__(self, "field_specs_sha256", field_digest)
        if not self.model_extras_sha256:
            if self.ordered_fields_sha256 == PRESENTATION_NOTE_FIELDS_SHA256:
                model_digest = V14_MODEL_EXTRAS_SHA256
            elif self.template_schema == "V12":
                model_digest = V12_CIBA_MODEL_EXTRAS_SHA256
            elif self.template_family == "language-immersive":
                model_digest = V10_IMMERSIVE_MODEL_EXTRAS_SHA256
            else:
                model_digest = V10_BASE_MODEL_EXTRAS_SHA256
            object.__setattr__(self, "model_extras_sha256", model_digest)

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "compatibilityContractVersion": COMPATIBILITY_CONTRACT_VERSION,
            "templateFamily": self.template_family,
            "templateSchema": self.template_schema,
            "noteModelId": self.note_model_id,
            "modelName": self.model_name,
            "modelType": self.model_type,
            "sortField": self.sort_field,
            "orderedFieldsSha256": self.ordered_fields_sha256,
            "fieldSpecsSha256": self.field_specs_sha256,
            "modelExtrasSha256": self.model_extras_sha256,
            "templateExtrasSha256": self.template_extras_sha256,
            "templateName": self.template_name,
            "templateOrdinal": self.template_ordinal,
            "qfmtSha256": self.qfmt_sha256,
            "afmtSha256": self.afmt_sha256,
            "bqfmt": self.bqfmt,
            "bafmt": self.bafmt,
            "cssSha256": self.css_sha256,
            "supportStatus": self.support_status,
        }

    @property
    def contract_digest(self) -> str:
        payload = json.dumps(
            self.canonical_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def public_dict(self) -> dict[str, Any]:
        return {
            **self.canonical_dict(),
            "contractDigest": self.contract_digest,
            "compatibility_contract_version": COMPATIBILITY_CONTRACT_VERSION,
            "template_family": self.template_family,
            "template_schema": self.template_schema,
            "note_model_id": self.note_model_id,
            "model_name": self.model_name,
            "template_name": self.template_name,
            "note_model_contract_digest": self.contract_digest,
        }


NOTE_MODEL_CONTRACTS = (
    NoteModelContract(
        template_family="language-immersive-v11",
        template_schema="V15",
        note_model_id=1028904201,
        model_name="Anki Card Generator V15 - 沉浸复读 V11",
        template_name="沉浸复读 V11",
        ordered_fields_sha256=PRESENTATION_NOTE_FIELDS_SHA256,
        css_sha256="ce67ba0760df2996366989d25196ccaf0d6f05d3da87e44a7b692676e795f8a4",
        qfmt_sha256="03fa14f4b922ef350a358d77c10548eb1b5b8206b22d61b62ce6db8c83f29b35",
        afmt_sha256="7037ae6a3a8b0f2a5237b65010ffdafabf0fb6c6cb2c45dcc7514c50f81fb0a5",
    ),
    NoteModelContract(
        template_family="language-immersive-v11-fast",
        template_schema="V15",
        note_model_id=5074019806,
        model_name="Anki Card Generator V15 - 沉浸复读 V11 · 快速复读",
        template_name="沉浸复读 V11 · 快速复读",
        ordered_fields_sha256=PRESENTATION_NOTE_FIELDS_SHA256,
        css_sha256="3023d916bf3ad30182ffdacccec6d5d76c987478fbe667a9cca9451d63b177df",
        qfmt_sha256="0c977481c6fa3aa5aa97c0c9d81d925e32f00dea135244ddae844206abbeedd9",
        afmt_sha256="9395ce09a444716a78ce363c8ebe88cd03409014f42f3ae62a56039eb5bf6bb7",
    ),
    NoteModelContract(
        template_family="language-immersive-v11",
        template_schema="V14",
        note_model_id=3157735470,
        model_name="Anki Card Generator V14 - 沉浸复读 V11",
        template_name="沉浸复读 V11",
        ordered_fields_sha256=V14_NOTE_FIELDS_SHA256,
        css_sha256="ce67ba0760df2996366989d25196ccaf0d6f05d3da87e44a7b692676e795f8a4",
        qfmt_sha256="532ce91006678d1241e2bc198c6ed9cfded60a81ef6a41d466fc8d7dcdffb800",
        afmt_sha256="2c6104616c72026d5f83f7a11ba4c4af6f802c110ab5c360454ebd8ad47ff421",
    ),
    NoteModelContract(
        template_family="language-immersive-v11-fast",
        template_schema="V14",
        note_model_id=3446541562,
        model_name="Anki Card Generator V14 - 沉浸复读 V11 · 快速复读",
        template_name="沉浸复读 V11 · 快速复读",
        ordered_fields_sha256=V14_NOTE_FIELDS_SHA256,
        css_sha256="3023d916bf3ad30182ffdacccec6d5d76c987478fbe667a9cca9451d63b177df",
        qfmt_sha256="5b629c8f163f93e0a8785e41a27fcccbb6fe3df5db329f747185168e8af3f3e3",
        afmt_sha256="5df6319768cfd1465fed37f22100bb951c2b09b8c17b395f5ab6a10a733fafd9",
    ),
    NoteModelContract(
        template_family="language-ciba-tianxia-v1-warm_paper",
        template_schema="V12",
        note_model_id=4472596631,
        model_name="Anki Card Generator V12 - 词霸天下实验 V1 · 暖色纸感",
        template_name="词霸天下实验 V1 · 暖色纸感",
        ordered_fields_sha256=BASE_NOTE_FIELDS_SHA256,
        css_sha256="dcc638cc0376318a3b2dbe5b8bf703d6604b6d882a0276fc65bbd196c004c05d",
        qfmt_sha256="bfb89ef27f1514b15a5db835e6f3a9752bce81b6174b41bd67aab39cee8dec99",
        afmt_sha256="b06f960b2038c608cdab12bf9f7e438363feb71fc1ff603a55b4aa497bcc8865",
    ),
    NoteModelContract(
        template_family="language-ciba-tianxia-v1-minimal_white",
        template_schema="V12",
        note_model_id=4557891724,
        model_name="Anki Card Generator V12 - 词霸天下实验 V1 · 极简白卡",
        template_name="词霸天下实验 V1 · 极简白卡",
        ordered_fields_sha256=BASE_NOTE_FIELDS_SHA256,
        css_sha256="a882c1a900f83c2925ddd97e15b8967cf506ddd611e9873afddc8a47d77e832f",
        qfmt_sha256="bfb89ef27f1514b15a5db835e6f3a9752bce81b6174b41bd67aab39cee8dec99",
        afmt_sha256="b06f960b2038c608cdab12bf9f7e438363feb71fc1ff603a55b4aa497bcc8865",
    ),
    NoteModelContract(
        template_family="language-ciba-tianxia-v1-dark_immersive",
        template_schema="V12",
        note_model_id=3757246943,
        model_name="Anki Card Generator V12 - 词霸天下实验 V1 · 深色沉浸",
        template_name="词霸天下实验 V1 · 深色沉浸",
        ordered_fields_sha256=BASE_NOTE_FIELDS_SHA256,
        css_sha256="ca512a6c4c2a2e37637de269555a84b33eab8209a3bb1fcfdfb4c23a6490f445",
        qfmt_sha256="bfb89ef27f1514b15a5db835e6f3a9752bce81b6174b41bd67aab39cee8dec99",
        afmt_sha256="b06f960b2038c608cdab12bf9f7e438363feb71fc1ff603a55b4aa497bcc8865",
    ),
    NoteModelContract(
        template_family="language-immersive",
        template_schema="V10",
        note_model_id=3784810093,
        model_name="Anki Card Generator V10 - 视频语言 V10",
        template_name="视频语言 V10",
        ordered_fields_sha256=BASE_NOTE_FIELDS_SHA256,
        css_sha256="938bdd1a971103059cbe246403b99c842721f16bf308b215dd877113a6121850",
        qfmt_sha256="4c0595ecb919a334e9206687e655116c2a0ffea4086a0230bd1f9bb735e6966c",
        afmt_sha256="c60a45ddcd20477e14cdc0099cf288f29dc1c78112383091cd2b8752e9a6b52e",
    ),
    NoteModelContract(
        template_family="language-dictionary",
        template_schema="V10",
        note_model_id=5184873425,
        model_name="Anki Card Generator V10 - 词典解释 V10",
        template_name="词典解释 V10",
        ordered_fields_sha256=BASE_NOTE_FIELDS_SHA256,
        css_sha256="938bdd1a971103059cbe246403b99c842721f16bf308b215dd877113a6121850",
        qfmt_sha256="2d795c47d543c23c6a55c2848f4bca6ef30753fef064a2c4e608c6fa9c30e4cc",
        afmt_sha256="801afceb0d801dcd1e447d8535578ee2660e8264e21e49966e2149d7f79c268d",
    ),
    NoteModelContract(
        template_family="language-minimal",
        template_schema="V10",
        note_model_id=4230644400,
        model_name="Anki Card Generator V10 - 极简复习 V10",
        template_name="极简复习 V10",
        ordered_fields_sha256=BASE_NOTE_FIELDS_SHA256,
        css_sha256="938bdd1a971103059cbe246403b99c842721f16bf308b215dd877113a6121850",
        qfmt_sha256="2d795c47d543c23c6a55c2848f4bca6ef30753fef064a2c4e608c6fa9c30e4cc",
        afmt_sha256="4956ae2e5677efbe14afb0caa0ecf11db1d8d4411be665de093d837790ea5285",
    ),
    NoteModelContract(
        template_family="document-knowledge",
        template_schema="V10",
        note_model_id=5194274073,
        model_name="Anki Card Generator V10 - 文档知识 V10",
        template_name="文档知识 V10",
        ordered_fields_sha256=BASE_NOTE_FIELDS_SHA256,
        css_sha256="938bdd1a971103059cbe246403b99c842721f16bf308b215dd877113a6121850",
        qfmt_sha256="5dcbaf2455b5c2ea78b6c733f14e3fbb98b6e708ab241beb91f1aaac85d96e63",
        afmt_sha256="3de36319db074ca293024b58be7a1caa75c8f5cd54228c88125bc372447cadc0",
    ),
    NoteModelContract(
        template_family="document-reading",
        template_schema="V10",
        note_model_id=2090570227,
        model_name="Anki Card Generator V10 - 文档精读 V10",
        template_name="文档精读 V10",
        ordered_fields_sha256=BASE_NOTE_FIELDS_SHA256,
        css_sha256="938bdd1a971103059cbe246403b99c842721f16bf308b215dd877113a6121850",
        qfmt_sha256="35e0fa7b73d9e1bcf40e9ba419e1021a2d2063cc9222775ca44dd3bcb371cd03",
        afmt_sha256="801afceb0d801dcd1e447d8535578ee2660e8264e21e49966e2149d7f79c268d",
    ),
)

CONTRACTS_BY_MODEL_ID = {contract.note_model_id: contract for contract in NOTE_MODEL_CONTRACTS}
CONTRACTS_BY_EXPORT_KEY = {
    (contract.template_family, contract.template_schema, contract.template_name): contract
    for contract in NOTE_MODEL_CONTRACTS
}
if len(CONTRACTS_BY_MODEL_ID) != len(NOTE_MODEL_CONTRACTS):
    raise RuntimeError("Duplicate Note Model IDs in the frozen contract registry.")
if len(CONTRACTS_BY_EXPORT_KEY) != len(NOTE_MODEL_CONTRACTS):
    raise RuntimeError("Duplicate family/schema/template keys in the frozen contract registry.")

CURRENT_VIDEO_MODEL_NAMES = frozenset(
    contract.model_name
    for contract in NOTE_MODEL_CONTRACTS
    if contract.template_family in {"language-immersive-v11", "language-immersive-v11-fast"}
)
LEGACY_SUPPORTED_VIDEO_MODEL_NAMES = frozenset(
    {
        "Anki Card Generator V12 - 沉浸复读 V11",
        "Anki Card Generator V12 - 沉浸复读 V11 · 快速复读",
    }
)
VIDEO_IMPORT_MODEL_NAMES = CURRENT_VIDEO_MODEL_NAMES | LEGACY_SUPPORTED_VIDEO_MODEL_NAMES
DOCUMENT_IMPORT_MODEL_NAMES = frozenset(
    contract.model_name
    for contract in NOTE_MODEL_CONTRACTS
    if contract.template_family in {"document-knowledge", "document-reading"}
)
CIBA_IMPORT_MODEL_NAMES = frozenset(
    {
        *(
            contract.model_name
            for contract in NOTE_MODEL_CONTRACTS
            if contract.template_family.startswith("language-ciba-tianxia-v1-")
        ),
        "Anki Card Generator V12 - 词霸天下实验 V1",
    }
)


def resolve_export_note_model_contract(
    template_family: str,
    template_schema: str,
    template_name: str,
) -> NoteModelContract:
    key = (str(template_family), str(template_schema), str(template_name))
    contract = CONTRACTS_BY_EXPORT_KEY.get(key)
    if contract is None:
        raise ValueError(f"UNREGISTERED_NOTE_MODEL_CONTRACT: {key!r}")
    return contract


def validate_generated_note_model(
    contract: NoteModelContract,
    *,
    field_names: Iterable[str],
    css: str,
    qfmt: str,
    afmt: str,
    model_json: Mapping[str, Any] | None = None,
    deck_ids: Iterable[int] | None = None,
) -> None:
    """Validate both authored assets and, when provided, genanki's complete model JSON."""
    actual = {
        "ordered_fields_sha256": ordered_field_names_sha256(field_names),
        "css_sha256": text_sha256(css),
        "qfmt_sha256": text_sha256(qfmt),
        "afmt_sha256": text_sha256(afmt),
    }
    expected = {
        "ordered_fields_sha256": contract.ordered_fields_sha256,
        "css_sha256": contract.css_sha256,
        "qfmt_sha256": contract.qfmt_sha256,
        "afmt_sha256": contract.afmt_sha256,
    }
    mismatches = [key for key in expected if actual[key] != expected[key]]
    if mismatches:
        raise ValueError(
            "NOTE_MODEL_TEMPLATE_DRIFT: "
            + ", ".join(f"{key}={actual[key]} expected={expected[key]}" for key in mismatches)
        )
    if model_json is not None:
        issues = _inspect_model_payload(
            contract,
            contract.note_model_id,
            model_json,
            strict_embedded_id=False,
            deck_ids=set(deck_ids) if deck_ids is not None else None,
        )
        if issues:
            raise ValueError(
                "NOTE_MODEL_TEMPLATE_DRIFT: "
                + ", ".join(str(issue.get("code") or "UNKNOWN") for issue in issues)
            )


def _native_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _canonical_decimal(value: Any) -> int | None:
    if not isinstance(value, str) or re.fullmatch(r"[1-9][0-9]*", value) is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _issue(code: str, model_id: Any, **details: Any) -> dict[str, Any]:
    return {
        "code": code,
        "note_model_id": str(model_id),
        **{key: value for key, value in details.items() if value not in (None, "")},
    }


def _inspect_model_payload(
    contract: NoteModelContract,
    reference_id: int,
    model: Mapping[str, Any],
    *,
    strict_embedded_id: bool,
    deck_ids: set[int] | None,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    reference = str(reference_id)

    if contract.support_status not in {"allowed", "current"}:
        issues.append(_issue("NOTE_MODEL_SUPPORT_STATUS_BLOCKED", reference))

    if set(model.keys()) != MODEL_STATIC_KEYS:
        issues.append(
            _issue(
                "NOTE_MODEL_STRUCTURE_MISMATCH",
                reference,
                missing_keys=sorted(MODEL_STATIC_KEYS - set(model.keys())),
                unexpected_keys=sorted(set(model.keys()) - MODEL_STATIC_KEYS),
            )
        )

    embedded = model.get("id")
    embedded_id = _canonical_decimal(embedded)
    if not strict_embedded_id and _native_int(embedded) is not None:
        embedded_id = _native_int(embedded)
    if embedded_id != reference_id:
        issues.append(
            _issue(
                "NOTE_MODEL_ID_MISMATCH",
                reference,
                embedded_note_model_id=embedded,
            )
        )

    if not isinstance(model.get("name"), str) or model.get("name") != contract.model_name:
        issues.append(
            _issue(
                "NOTE_MODEL_NAME_MISMATCH",
                reference,
                model_name=model.get("name"),
                expected_model_name=contract.model_name,
            )
        )
    if _native_int(model.get("type")) != contract.model_type:
        issues.append(_issue("NOTE_MODEL_TYPE_MISMATCH", reference))
    if _native_int(model.get("sortf")) != contract.sort_field:
        issues.append(_issue("NOTE_MODEL_SORT_FIELD_MISMATCH", reference))
    if _native_int(model.get("mod")) is None or _native_int(model.get("usn")) is None:
        issues.append(_issue("NOTE_MODEL_METADATA_TYPE_MISMATCH", reference))

    model_deck_id = _native_int(model.get("did"))
    if model_deck_id is None:
        issues.append(_issue("NOTE_MODEL_DECK_ID_TYPE_MISMATCH", reference))
    elif deck_ids is not None and model_deck_id not in deck_ids:
        issues.append(
            _issue(
                "NOTE_MODEL_DECK_ID_MISMATCH",
                reference,
                deck_id=model_deck_id,
            )
        )

    expected_field_names = note_model_field_names(
        contract.ordered_fields_sha256 == PRESENTATION_NOTE_FIELDS_SHA256
    )
    raw_fields = model.get("flds")
    if (
        not isinstance(raw_fields, list)
        or len(raw_fields) != len(expected_field_names)
        or any(not isinstance(field, dict) for field in raw_fields)
    ):
        issues.append(_issue("NOTE_MODEL_FIELD_STRUCTURE_MISMATCH", reference))
        raw_fields = []
    else:
        if any(set(field.keys()) != FIELD_SPEC_KEYS for field in raw_fields):
            issues.append(_issue("NOTE_MODEL_FIELD_STRUCTURE_MISMATCH", reference))
        field_names = tuple(field.get("name") for field in raw_fields)
        if field_names != expected_field_names:
            issues.append(_issue("NOTE_MODEL_FIELDS_MISMATCH", reference))
        if any(_native_int(field.get("ord")) != index for index, field in enumerate(raw_fields)):
            issues.append(_issue("NOTE_MODEL_FIELD_ORDER_MISMATCH", reference))
        if canonical_json_sha256(raw_fields) != contract.field_specs_sha256:
            issues.append(_issue("NOTE_MODEL_FIELD_SPECS_MISMATCH", reference))

    raw_templates = model.get("tmpls")
    if (
        not isinstance(raw_templates, list)
        or len(raw_templates) != 1
        or not isinstance(raw_templates[0], dict)
    ):
        issues.append(_issue("NOTE_MODEL_TEMPLATE_COUNT_MISMATCH", reference))
        raw_templates = []
    else:
        template = raw_templates[0]
        if set(template.keys()) != TEMPLATE_KEYS:
            issues.append(_issue("NOTE_MODEL_TEMPLATE_STRUCTURE_MISMATCH", reference))
        if not isinstance(template.get("name"), str) or template.get("name") != contract.template_name:
            issues.append(_issue("NOTE_MODEL_TEMPLATE_NAME_MISMATCH", reference))
        if _native_int(template.get("ord")) != contract.template_ordinal:
            issues.append(_issue("NOTE_MODEL_TEMPLATE_ORDER_MISMATCH", reference))
        if text_sha256(template.get("qfmt") if isinstance(template.get("qfmt"), str) else "") != contract.qfmt_sha256:
            issues.append(_issue("NOTE_MODEL_QFMT_MISMATCH", reference))
        if text_sha256(template.get("afmt") if isinstance(template.get("afmt"), str) else "") != contract.afmt_sha256:
            issues.append(_issue("NOTE_MODEL_AFMT_MISMATCH", reference))
        if template.get("bqfmt") != contract.bqfmt:
            issues.append(_issue("NOTE_MODEL_BQFMT_MISMATCH", reference))
        if template.get("bafmt") != contract.bafmt:
            issues.append(_issue("NOTE_MODEL_BAFMT_MISMATCH", reference))
        template_extras = [{key: template.get(key) for key in TEMPLATE_EXTRA_KEYS}]
        if canonical_json_sha256(template_extras) != contract.template_extras_sha256:
            issues.append(_issue("NOTE_MODEL_TEMPLATE_EXTRAS_MISMATCH", reference))

    if text_sha256(model.get("css") if isinstance(model.get("css"), str) else "") != contract.css_sha256:
        issues.append(_issue("NOTE_MODEL_CSS_MISMATCH", reference))
    model_extras = {key: model.get(key) for key in MODEL_EXTRA_KEYS}
    if canonical_json_sha256(model_extras) != contract.model_extras_sha256:
        issues.append(_issue("NOTE_MODEL_EXTRAS_MISMATCH", reference))

    return issues


def inspect_referenced_note_models(
    models: Mapping[Any, Any],
    referenced_model_ids: Iterable[Any],
    *,
    require_exact_registry: bool = False,
    require_single_referenced_model: bool = False,
    deck_ids: Iterable[int] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    matched: list[dict[str, Any]] = []
    valid_deck_ids = set(deck_ids) if deck_ids is not None else None

    references: list[int] = []
    for value in referenced_model_ids:
        native = _native_int(value)
        if native is None or native <= 0:
            issues.append(_issue("NOTE_MODEL_REFERENCE_ID_INVALID", value))
        else:
            references.append(native)
    referenced_ids = sorted(set(references))

    if not referenced_ids:
        issues.append(_issue("NO_REFERENCED_NOTE_MODEL", ""))
    if require_single_referenced_model and len(referenced_ids) != 1:
        issues.append(
            _issue(
                "REFERENCED_NOTE_MODEL_COUNT_MISMATCH",
                "",
                referenced_count=len(referenced_ids),
            )
        )

    if not isinstance(models, Mapping):
        issues.append(_issue("NOTE_MODEL_REGISTRY_INVALID", ""))
        return {"contracts": matched, "issues": issues}

    normalized_models: dict[str, Mapping[str, Any]] = {}
    registry_ids: set[int] = set()
    for key, value in models.items():
        if isinstance(key, str):
            parsed_key = _canonical_decimal(key)
        elif not require_exact_registry:
            parsed_key = _native_int(key)
        else:
            parsed_key = None
        if parsed_key is None:
            issues.append(_issue("NOTE_MODEL_REGISTRY_ID_INVALID", key))
            continue
        registry_ids.add(parsed_key)
        if not isinstance(value, Mapping):
            issues.append(_issue("NOTE_MODEL_REGISTRY_ENTRY_INVALID", key))
            continue
        normalized_models[str(parsed_key)] = value

    if require_exact_registry and registry_ids != set(referenced_ids):
        issues.append(
            _issue(
                "NOTE_MODEL_REGISTRY_SET_MISMATCH",
                "",
                referenced_ids=referenced_ids,
                registry_ids=sorted(registry_ids),
            )
        )

    for reference_id in referenced_ids:
        reference = str(reference_id)
        model = normalized_models.get(reference)
        if model is None:
            issues.append(_issue("REFERENCED_NOTE_MODEL_MISSING", reference))
            continue
        contract = CONTRACTS_BY_MODEL_ID.get(reference_id)
        if contract is None:
            issues.append(
                _issue(
                    "UNSUPPORTED_NOTE_MODEL_ID",
                    reference,
                    model_name=model.get("name"),
                )
            )
            continue
        model_issues = _inspect_model_payload(
            contract,
            reference_id,
            model,
            strict_embedded_id=require_exact_registry,
            deck_ids=valid_deck_ids,
        )
        if model_issues:
            issues.extend(model_issues)
        else:
            matched.append(contract.public_dict())

    return {"contracts": matched, "issues": issues}


class ApkgContractError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


def archive_limit_error(message: str) -> ApkgContractError:
    return ApkgContractError("UNSAFE_APKG_ARCHIVE", message)


def validate_apkg_archive_limits(archive: zipfile.ZipFile) -> None:
    media_entries = 0
    total_size = 0
    for info in archive.infolist():
        if info.filename in COLLECTION_ENTRY_NAMES:
            per_entry_limit = MAX_ARCHIVE_COLLECTION_BYTES
        elif info.filename == "media":
            per_entry_limit = MAX_ARCHIVE_MEDIA_MAP_BYTES
        else:
            per_entry_limit = MAX_ARCHIVE_MEDIA_BYTES
        if info.file_size < 0 or info.file_size > per_entry_limit:
            raise archive_limit_error(f"{info.filename} 超过单文件上限。")
        total_size += int(info.file_size)
        if total_size > MAX_ARCHIVE_TOTAL_BYTES:
            raise archive_limit_error("解压后总大小超过上限。")
        if info.filename not in COLLECTION_ENTRY_NAMES | {"media"}:
            media_entries += 1
    if media_entries > MAX_ARCHIVE_MEDIA_ENTRIES:
        raise archive_limit_error("媒体文件数量超过上限。")


def validate_apkg_archive_structure(archive: zipfile.ZipFile) -> str:
    validate_apkg_archive_limits(archive)
    names = [info.filename for info in archive.infolist()]
    collection_entries = [name for name in names if name in COLLECTION_ENTRY_NAMES]
    if len(collection_entries) != 1:
        raise ApkgContractError(
            "APKG_COLLECTION_ENTRY_INVALID",
            "APKG 必须且只能包含一个 collection.anki2 或 collection.anki21。",
        )
    if names.count("media") != 1:
        raise ApkgContractError(
            "APKG_MEDIA_MAP_ENTRY_INVALID",
            "APKG 必须且只能包含一个 media 映射文件。",
        )
    return collection_entries[0]


def inspect_apkg_note_model_contract(apkg: Path) -> dict[str, list[dict[str, Any]]]:
    """Fail-closed inspection shared by offline verification and production import."""
    db_path: Path | None = None
    try:
        with zipfile.ZipFile(apkg) as archive:
            collection_name = validate_apkg_archive_structure(archive)
            collection_payload = archive.read(collection_name)
        with tempfile.NamedTemporaryFile(suffix=f"_{collection_name}", delete=False) as tmp_db:
            db_path = Path(tmp_db.name)
            tmp_db.write(collection_payload)
        con = sqlite3.connect(db_path)
        try:
            row = con.execute("select models, decks from col").fetchone()
            if row is None:
                raise ApkgContractError("APKG_COLLECTION_INVALID", "col 表没有模型注册表。")
            models = json.loads(row[0])
            decks = json.loads(row[1])
            if not isinstance(decks, Mapping):
                raise ApkgContractError("APKG_DECK_REGISTRY_INVALID", "牌组注册表不是对象。")
            deck_ids: set[int] = set()
            for key in decks:
                parsed = _canonical_decimal(key)
                if parsed is None:
                    raise ApkgContractError("APKG_DECK_REGISTRY_INVALID", "牌组 ID 不是规范十进制字符串。")
                deck_ids.add(parsed)
            referenced_mids = [row[0] for row in con.execute("select distinct mid from notes").fetchall()]
            return inspect_referenced_note_models(
                models,
                referenced_mids,
                require_exact_registry=True,
                require_single_referenced_model=True,
                deck_ids=deck_ids,
            )
        finally:
            con.close()
    except ApkgContractError as exc:
        return {"contracts": [], "issues": [_issue(exc.code, "", detail=str(exc))]}
    except (OSError, ValueError, json.JSONDecodeError, sqlite3.Error, zipfile.BadZipFile, KeyError) as exc:
        return {
            "contracts": [],
            "issues": [_issue("APKG_CONTRACT_INSPECTION_FAILED", "", detail=str(exc))],
        }
    finally:
        if db_path is not None:
            db_path.unlink(missing_ok=True)
            Path(f"{db_path}-shm").unlink(missing_ok=True)
            Path(f"{db_path}-wal").unlink(missing_ok=True)
