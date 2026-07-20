"""Execute one confirmed Anki import from authenticated package artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

from workers.acg.anki_model_contracts import (
    CONTRACTS_BY_MODEL_ID,
    PRESENTATION_NOTE_FIELDS_SHA256,
    inspect_apkg_note_model_contract,
    note_model_field_names,
)
from workers.acg.apkg_package_contract import (
    NOTE_CONTENT_FINGERPRINT_ALGORITHM,
    NOTE_CONTENT_FINGERPRINT_SCHEMA_VERSION,
    NOTE_CONTENT_FINGERPRINT_SERIALIZATION,
    note_content_sha256,
    validate_apkg_package_contract,
)
from workers.acg.media_refs import extract_media_references

from .anki_import_approval import AnkiImportApprovalError, AnkiImportApprovalLedger
from .anki_import_preparation import (
    ANKI_DATA_VERIFICATION_CONTRACT_VERSION,
    ANKI_IMPORT_PLAN_POLICY_VERSION,
    AnkiImportPreparationError,
    AnkiImportPreparationRuntime,
)
from .anki_target_probe import ANKI_CONNECT_URL, normalize_anki_connect_url
from .artifact_registry import (
    ArtifactAudienceBinding,
    ArtifactRegistry,
    ArtifactRegistryError,
    canonical_json_bytes,
)
from .project_registry import ProjectRegistry, ProjectRegistryError
from .task_coordinator import StudyTaskCoordinator, StudyTaskError
from .task_manifests import (
    TaskManifestError,
    build_authorization_binding,
    build_capability_binding,
    build_task_input_manifest,
    build_work_reuse_manifest,
)


ANKI_IMPORT_EXECUTION_POLICY_VERSION = "anki-import-execution-v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_MEDIA_INDEX_RE = re.compile(r"^(?:0|[1-9][0-9]*)$")
_MAX_APKG_BYTES = 2 * 1024 * 1024 * 1024
_MAX_COLLECTION_BYTES = 128 * 1024 * 1024
_MAX_MEDIA_BYTES = 256 * 1024 * 1024
_MAX_MEDIA_ITEMS = 10_000
_PRODUCER = {
    "component": "card-service.anki-import-execution",
    "version": "1.0.0",
}
_COMPONENTS = {
    "cardService": "2.0.0",
    "worker": "managed-worker",
    "sourceAdapterSetDigest": hashlib.sha256(
        b"study.anki-import-execution.source-adapters.v1"
    ).hexdigest(),
    "gateRuleSetVersion": ANKI_IMPORT_EXECUTION_POLICY_VERSION,
}
_ROLE_TO_CARD_FIELD = {
    "video": ("video_webm", "video_mp4"),
    "poster": ("poster",),
    "original_audio": ("original_audio",),
    "sentence_tts": ("sentence_tts_audio",),
    "phrase_tts": ("phrase_tts_audio",),
}
_TEMPLATE_DECK_KIND = {
    "document-knowledge": "document_knowledge",
    "document-reading": "document_reading",
}


class AnkiImportExecutionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class AnkiImportExecutor(Protocol):
    def __call__(
        self,
        bundle: Mapping[str, Any],
        progress: Callable[[Mapping[str, Any]], None],
        cancel_event: threading.Event,
    ) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class _ActiveImport:
    cancel_event: threading.Event
    thread: threading.Thread


def _clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _identity(ref: Mapping[str, Any]) -> tuple[str, int, str]:
    return (
        str(ref.get("artifactId") or ""),
        int(ref.get("artifactRevision") or 0),
        str(ref.get("artifactDigest") or ""),
    )


def _strict_json_object(raw: bytes) -> dict[str, Any]:
    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
    if not isinstance(value, dict):
        raise ValueError("JSON value is not an object")
    return value


def _safe_media_name(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != Path(value).name
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
        or ":" in value
        or "\x00" in value
    ):
        raise AnkiImportExecutionError(
            "PACKAGE_VERIFY_FAILED", "APKG media name is unsafe"
        )
    return value


def _stream_archive_member(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    destination: Path,
    *,
    maximum_bytes: int,
    expected_sha256: str | None = None,
) -> tuple[int, str]:
    if info.flag_bits & 0x1 or info.file_size < 0 or info.file_size > maximum_bytes:
        raise AnkiImportExecutionError(
            "PACKAGE_VERIFY_FAILED", "APKG archive member is unsafe"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    total = 0
    try:
        with archive.open(info, "r") as source, destination.open("xb") as output:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > info.file_size or total > maximum_bytes:
                    raise AnkiImportExecutionError(
                        "PACKAGE_VERIFY_FAILED",
                        "APKG archive member exceeded its limit",
                    )
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
    except FileExistsError as error:
        raise AnkiImportExecutionError(
            "PACKAGE_VERIFY_FAILED", "APKG workspace destination already exists"
        ) from error
    actual = digest.hexdigest()
    if total != info.file_size or (
        expected_sha256 is not None and actual != expected_sha256
    ):
        destination.unlink(missing_ok=True)
        raise AnkiImportExecutionError(
            "PACKAGE_VERIFY_FAILED", "APKG archive member failed integrity verification"
        )
    return total, actual


def _deck_root(deck_names: Sequence[str]) -> str:
    split = [str(name).split("::") for name in deck_names]
    common: list[str] = []
    for values in zip(*split):
        if len(set(values)) != 1:
            break
        common.append(values[0])
    if not common:
        raise AnkiImportExecutionError(
            "PACKAGE_VERIFY_FAILED", "APKG deck hierarchy has no common root"
        )
    root = "::".join(common)
    if not all(name == root or name.startswith(root + "::") for name in deck_names):
        raise AnkiImportExecutionError(
            "PACKAGE_VERIFY_FAILED", "APKG deck hierarchy is invalid"
        )
    return root


def _only_reference(values: Sequence[str], label: str) -> str:
    unique = sorted(set(values))
    if len(unique) > 1:
        raise AnkiImportExecutionError(
            "PACKAGE_VERIFY_FAILED", f"APKG {label} field has ambiguous media"
        )
    return unique[0] if unique else ""


def materialize_anki_worker_request(
    bundle: Mapping[str, Any],
    workspace: Path,
    artifacts: ArtifactRegistry,
    *,
    anki_connect_url: str = ANKI_CONNECT_URL,
    import_apkg: bool = True,
) -> dict[str, Any]:
    """Build a legacy Worker request only from authenticated, immutable inputs."""

    required = {
        "schemaVersion",
        "apkgBlobRef",
        "apkgSha256",
        "sizeBytes",
        "deckNames",
        "cardCount",
        "mediaCount",
        "templateFamily",
        "templateSchemaVersion",
        "cardIdentities",
        "mediaEntries",
    }
    if not isinstance(bundle, Mapping) or set(bundle) != required:
        raise AnkiImportExecutionError(
            "PACKAGE_VERIFY_FAILED", "Authenticated import bundle fields are invalid"
        )
    if bundle.get("schemaVersion") != 1:
        raise AnkiImportExecutionError(
            "PACKAGE_VERIFY_FAILED", "Authenticated import bundle version is invalid"
        )
    expected_sha = bundle.get("apkgSha256")
    expected_size = bundle.get("sizeBytes")
    card_count = bundle.get("cardCount")
    media_count = bundle.get("mediaCount")
    if (
        not isinstance(expected_sha, str)
        or not _SHA256_RE.fullmatch(expected_sha)
        or isinstance(expected_size, bool)
        or not isinstance(expected_size, int)
        or not 0 < expected_size <= _MAX_APKG_BYTES
        or isinstance(card_count, bool)
        or not isinstance(card_count, int)
        or card_count <= 0
        or isinstance(media_count, bool)
        or not isinstance(media_count, int)
        or not 0 <= media_count <= _MAX_MEDIA_ITEMS
    ):
        raise AnkiImportExecutionError(
            "PACKAGE_VERIFY_FAILED", "Authenticated import bundle identity is invalid"
        )
    decks = bundle.get("deckNames")
    identities = bundle.get("cardIdentities")
    entries = bundle.get("mediaEntries")
    if (
        not isinstance(decks, list)
        or not decks
        or any(not isinstance(item, str) or not item for item in decks)
        or not isinstance(identities, list)
        or len(identities) != card_count
        or not isinstance(entries, list)
        or len(entries) != media_count
    ):
        raise AnkiImportExecutionError(
            "PACKAGE_VERIFY_FAILED", "Authenticated import bundle accounting is invalid"
        )

    root = Path(workspace).absolute()
    root.mkdir(parents=True, exist_ok=True)
    import_root = root / "anki-import"
    import_root.mkdir()
    media_root = import_root / "media"
    media_root.mkdir()
    apkg_path = import_root / "cards.apkg"
    materialized = artifacts.materialize_blob(bundle["apkgBlobRef"], apkg_path)
    if (
        materialized["sha256"] != expected_sha
        or materialized["sizeBytes"] != expected_size
    ):
        raise AnkiImportExecutionError(
            "PACKAGE_VERIFY_FAILED", "Materialized APKG identity is inconsistent"
        )

    manifest: dict[str, dict[str, Any]] = {}
    for raw in entries:
        if not isinstance(raw, Mapping):
            raise AnkiImportExecutionError(
                "PACKAGE_VERIFY_FAILED", "Authenticated media entry is invalid"
            )
        item = _clone(raw)
        name = _safe_media_name(item.pop("fileName", None))
        digest = item.get("sha256")
        size = item.get("bytes")
        if (
            name in manifest
            or not isinstance(digest, str)
            or not _SHA256_RE.fullmatch(digest)
            or isinstance(size, bool)
            or not isinstance(size, int)
            or not 0 < size <= _MAX_MEDIA_BYTES
        ):
            raise AnkiImportExecutionError(
                "PACKAGE_VERIFY_FAILED", "Authenticated media manifest is invalid"
            )
        manifest[name] = item

    database_path = import_root / "collection.anki2"
    try:
        with zipfile.ZipFile(apkg_path, "r") as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                raise AnkiImportExecutionError(
                    "PACKAGE_VERIFY_FAILED", "APKG contains duplicate archive members"
                )
            if "collection.anki2" not in names or "media" not in names:
                raise AnkiImportExecutionError(
                    "PACKAGE_VERIFY_FAILED", "APKG archive structure is incomplete"
                )
            media_map = _strict_json_object(archive.read("media"))
            if (
                any(not _MEDIA_INDEX_RE.fullmatch(key) for key in media_map)
                or set(media_map) != {str(index) for index in range(len(media_map))}
                or any(not isinstance(name, str) for name in media_map.values())
            ):
                raise AnkiImportExecutionError(
                    "PACKAGE_VERIFY_FAILED", "APKG media map is invalid"
                )
            parsed_media_map = {
                key: _safe_media_name(value) for key, value in media_map.items()
            }
            if set(parsed_media_map.values()) != set(manifest):
                raise AnkiImportExecutionError(
                    "PACKAGE_VERIFY_FAILED",
                    "APKG media map differs from authenticated manifest",
                )
            expected_names = {"collection.anki2", "media", *parsed_media_map.keys()}
            if set(names) != expected_names:
                raise AnkiImportExecutionError(
                    "PACKAGE_VERIFY_FAILED", "APKG contains unexpected archive members"
                )
            by_name = {info.filename: info for info in infos}
            _stream_archive_member(
                archive,
                by_name["collection.anki2"],
                database_path,
                maximum_bytes=_MAX_COLLECTION_BYTES,
            )
            for index, name in parsed_media_map.items():
                size, digest = _stream_archive_member(
                    archive,
                    by_name[index],
                    media_root / name,
                    maximum_bytes=_MAX_MEDIA_BYTES,
                    expected_sha256=str(manifest[name]["sha256"]),
                )
                if (
                    size != manifest[name]["bytes"]
                    or digest != manifest[name]["sha256"]
                ):
                    raise AnkiImportExecutionError(
                        "PACKAGE_VERIFY_FAILED",
                        "APKG media differs from authenticated manifest",
                    )
    except (KeyError, OSError, ValueError, zipfile.BadZipFile) as error:
        raise AnkiImportExecutionError(
            "PACKAGE_VERIFY_FAILED", "APKG could not be materialized safely"
        ) from error

    contract_report = inspect_apkg_note_model_contract(apkg_path)
    contracts = (
        contract_report.get("contracts")
        if isinstance(contract_report, Mapping)
        else None
    )
    issues = (
        contract_report.get("issues") if isinstance(contract_report, Mapping) else None
    )
    if not isinstance(contracts, list) or len(contracts) != 1 or issues:
        raise AnkiImportExecutionError(
            "PACKAGE_VERIFY_FAILED", "APKG Note Model contract is not uniquely trusted"
        )
    contract = contracts[0]
    if not isinstance(contract, Mapping):
        raise AnkiImportExecutionError(
            "PACKAGE_VERIFY_FAILED", "APKG Note Model contract is invalid"
        )
    model_id = contract.get("noteModelId")
    contract_object = CONTRACTS_BY_MODEL_ID.get(model_id)
    if contract_object is None:
        raise AnkiImportExecutionError(
            "PACKAGE_VERIFY_FAILED", "APKG Note Model is unsupported"
        )
    template_family = str(bundle["templateFamily"])
    template_schema = str(bundle["templateSchemaVersion"])
    if (
        contract.get("templateFamily") != template_family
        or contract.get("templateSchema") != template_schema
    ):
        raise AnkiImportExecutionError(
            "PACKAGE_VERIFY_FAILED", "APKG Note Model differs from ImportPlan"
        )
    deck_kind = (
        "video_language"
        if template_family.startswith("language-")
        else _TEMPLATE_DECK_KIND.get(template_family)
    )
    if deck_kind is None:
        raise AnkiImportExecutionError(
            "PACKAGE_VERIFY_FAILED", "APKG template family is not importable"
        )
    field_names = list(
        note_model_field_names(
            contract_object.ordered_fields_sha256 == PRESENTATION_NOTE_FIELDS_SHA256
        )
    )

    identity_by_card: dict[str, dict[str, Any]] = {}
    for raw in identities:
        if not isinstance(raw, Mapping):
            raise AnkiImportExecutionError(
                "PACKAGE_VERIFY_FAILED", "Authenticated card identity is invalid"
            )
        item = dict(raw)
        card_id = item.get("cardId")
        content_sha = item.get("noteContentSha256")
        if (
            not isinstance(card_id, str)
            or not card_id
            or card_id in identity_by_card
            or not isinstance(content_sha, str)
            or not _SHA256_RE.fullmatch(content_sha)
        ):
            raise AnkiImportExecutionError(
                "PACKAGE_VERIFY_FAILED", "Authenticated card identities are invalid"
            )
        identity_by_card[card_id] = item

    card_ledger: list[dict[str, Any]] = []
    connection = sqlite3.connect(f"file:{database_path.as_posix()}?mode=ro", uri=True)
    try:
        connection.execute("pragma query_only = on")
        col = connection.execute("select decks from col").fetchone()
        if col is None:
            raise AnkiImportExecutionError(
                "PACKAGE_VERIFY_FAILED", "APKG collection metadata is absent"
            )
        deck_registry = _strict_json_object(str(col[0]).encode("utf-8"))
        deck_by_id = {
            int(key): str(value.get("name") or "")
            for key, value in deck_registry.items()
            if isinstance(value, Mapping) and str(key).isdigit()
        }
        notes = connection.execute(
            "select id,tags,flds from notes order by id"
        ).fetchall()
        cards = connection.execute("select nid,did from cards order by nid").fetchall()
        deck_id_by_note = {int(note_id): int(deck_id) for note_id, deck_id in cards}
        if len(notes) != card_count or len(cards) != card_count:
            raise AnkiImportExecutionError(
                "PACKAGE_VERIFY_FAILED", "APKG note/card count differs from ImportPlan"
            )
        for note_id, raw_tags, raw_fields in notes:
            values = str(raw_fields).split("\x1f")
            if len(values) != len(field_names):
                raise AnkiImportExecutionError(
                    "PACKAGE_VERIFY_FAILED", "APKG note field count is invalid"
                )
            fields = dict(zip(field_names, values))
            card_id = fields.get("CardId", "")
            identity = identity_by_card.get(card_id)
            deck_name = deck_by_id.get(deck_id_by_note.get(int(note_id), -1), "")
            content_sha = note_content_sha256(field_names, values)
            if (
                identity is None
                or identity.get("noteContentSha256") != content_sha
                or identity.get("deckName") != deck_name
            ):
                raise AnkiImportExecutionError(
                    "PACKAGE_VERIFY_FAILED",
                    "APKG card identity differs from authenticated ledger",
                )
            refs_by_field = {
                name: extract_media_references(fields.get(name, ""))
                for name in ("Video", "Audio", "TtsAudio", "PhraseTtsAudio")
            }
            card_media = {
                "video_webm": "",
                "video_mp4": "",
                "poster": "",
                "original_audio": _only_reference(refs_by_field["Audio"], "Audio"),
                "sentence_tts_audio": _only_reference(
                    refs_by_field["TtsAudio"], "TtsAudio"
                ),
                "phrase_tts_audio": _only_reference(
                    refs_by_field["PhraseTtsAudio"], "PhraseTtsAudio"
                ),
            }
            for name in refs_by_field["Video"]:
                entry = manifest.get(name)
                if entry is None:
                    raise AnkiImportExecutionError(
                        "PACKAGE_VERIFY_FAILED", "APKG card references unknown media"
                    )
                role = entry.get("role")
                if role == "poster":
                    key = "poster"
                elif role == "video" and name.lower().endswith(".webm"):
                    key = "video_webm"
                elif role == "video" and name.lower().endswith(".mp4"):
                    key = "video_mp4"
                else:
                    raise AnkiImportExecutionError(
                        "PACKAGE_VERIFY_FAILED", "APKG video media role is invalid"
                    )
                if card_media[key]:
                    raise AnkiImportExecutionError(
                        "PACKAGE_VERIFY_FAILED", "APKG card has duplicate media role"
                    )
                card_media[key] = name
            all_refs = [name for values_ in refs_by_field.values() for name in values_]
            segment_ids = {
                str(manifest[name].get("segment_id") or "")
                for name in all_refs
                if name in manifest
            } - {""}
            if len(segment_ids) > 1:
                raise AnkiImportExecutionError(
                    "PACKAGE_VERIFY_FAILED", "APKG card media spans multiple segments"
                )
            segment_id = (
                next(iter(segment_ids))
                if segment_ids
                else str(identity.get("sourceCardId") or card_id)
            )
            note_tags = (
                str(raw_tags)[1:-1].split(" ")
                if str(raw_tags).startswith(" ") and str(raw_tags).endswith(" ")
                else []
            )
            card_ledger.append(
                {
                    "card_id": card_id,
                    "source_card_id": str(identity.get("sourceCardId") or card_id),
                    "segment_id": segment_id,
                    "deck_name": deck_name,
                    "note_tags": note_tags,
                    "note_content_sha256": content_sha,
                    **card_media,
                }
            )
    except sqlite3.Error as error:
        raise AnkiImportExecutionError(
            "PACKAGE_VERIFY_FAILED", "APKG collection could not be inspected"
        ) from error
    finally:
        connection.close()

    if set(identity_by_card) != {item["card_id"] for item in card_ledger}:
        raise AnkiImportExecutionError(
            "PACKAGE_VERIFY_FAILED", "APKG card set differs from authenticated ledger"
        )
    media_ledger = []
    for name, entry in sorted(manifest.items(), key=lambda item: item[0].encode()):
        role = str(entry.get("role") or "")
        field = {
            "video": "Video",
            "poster": "Video",
            "original_audio": "Audio",
            "sentence_tts": "TtsAudio",
            "phrase_tts": "PhraseTtsAudio",
        }.get(role)
        if field is None:
            raise AnkiImportExecutionError(
                "PACKAGE_VERIFY_FAILED", "Authenticated media role is invalid"
            )
        media_ledger.append(
            {
                "file": name,
                **_clone(entry),
                "field": field,
                "card_id": str(entry.get("card_id") or ""),
            }
        )
    media_bytes = sum(int(entry["bytes"]) for entry in manifest.values())
    export_result = {
        "schema_version": 2,
        "apkg_path": str(apkg_path),
        "apkg_sha256": expected_sha,
        "apkg_size_bytes": expected_size,
        "apkg_mtime_ms": int(apkg_path.stat().st_mtime * 1000),
        "media_dir": str(media_root),
        "deck_name": _deck_root(decks),
        "deck_names": list(decks),
        "deck_kind": deck_kind,
        "template_family": template_family,
        "template_schema": template_schema,
        "template_version": template_schema,
        "template_name": contract_object.template_name,
        "note_model_id": contract_object.note_model_id,
        "model_name": contract_object.model_name,
        "compatibility_contract_version": int(
            contract.get("compatibilityContractVersion")
        ),
        "note_model_contract_digest": contract_object.contract_digest,
        "anki_tag": f"anki_card_generator_{template_schema.lower()}",
        "media_manifest": manifest,
        "media_ledger": media_ledger,
        "card_media_ledger": sorted(
            card_ledger, key=lambda item: item["card_id"].encode()
        ),
        "note_content_fingerprint": {
            "schema_version": NOTE_CONTENT_FINGERPRINT_SCHEMA_VERSION,
            "algorithm": NOTE_CONTENT_FINGERPRINT_ALGORITHM,
            "serialization": NOTE_CONTENT_FINGERPRINT_SERIALIZATION,
            "field_names": field_names,
            "card_count": card_count,
        },
        "cards": card_count,
        "media_summary": {
            "media_files": media_count,
            "media_bytes": media_bytes,
            "card_media_ledger_items": card_count,
        },
    }
    report = validate_apkg_package_contract(apkg_path, export_result)
    if report.get("ok") is not True or report.get("issues"):
        raise AnkiImportExecutionError(
            "PACKAGE_VERIFY_FAILED", "Reconstructed APKG contract did not verify"
        )
    return {
        "export_result": export_result,
        "import_apkg": bool(import_apkg),
        "anki_connect_url": normalize_anki_connect_url(anki_connect_url),
        "wait_for_anki_seconds": 10 if import_apkg else 0,
    }


class AnkiImportExecutionRuntime:
    """Coordinate confirmation consumption, Worker execution, and evidence commit."""

    def __init__(
        self,
        *,
        service_instance_id: str,
        artifacts: ArtifactRegistry,
        projects: ProjectRegistry,
        tasks: StudyTaskCoordinator,
        preparation: AnkiImportPreparationRuntime,
        approvals: AnkiImportApprovalLedger,
        executor: AnkiImportExecutor,
    ) -> None:
        self._service_instance_id = service_instance_id
        self._artifacts = artifacts
        self._projects = projects
        self._tasks = tasks
        self._preparation = preparation
        self._approvals = approvals
        self._executor = executor
        self._active: dict[str, _ActiveImport] = {}
        self._active_lock = threading.RLock()

    def _artifact_payload(
        self,
        ref: Mapping[str, Any],
        audience: ArtifactAudienceBinding,
        schema: str,
    ) -> dict[str, Any]:
        envelope = self._artifacts.verify_ref(ref, audience)
        if envelope.get("payloadSchema") != schema or not isinstance(
            envelope.get("payload"), Mapping
        ):
            raise AnkiImportExecutionError(
                "ARTIFACT_CORRUPT", f"{schema} artifact is invalid"
            )
        return _clone(envelope["payload"])

    def _bundle(
        self,
        *,
        audience: ArtifactAudienceBinding,
        resolved: Mapping[str, Any],
    ) -> dict[str, Any]:
        plan = resolved["importPlanPayload"]
        package = self._artifact_payload(
            plan["packageArtifactRef"], audience, "study.package-artifact"
        )
        file_payload = self._artifact_payload(
            plan["apkgFileRef"], audience, "study.apkg-file"
        )
        identities = self._artifact_payload(
            plan["cardIdentitySetRef"], audience, "study.card-identity-set"
        )
        manifest = self._artifact_payload(
            plan["mediaManifestRef"], audience, "study.package-media-manifest"
        )
        inventory = self._artifact_payload(
            plan["cardMediaRoleInventoryRef"],
            audience,
            "study.card-media-role-inventory",
        )
        verification = self._artifact_payload(
            plan["verificationContractRef"],
            audience,
            "study.anki-verification-contract",
        )
        checks = (
            package.get("apkgSha256") == plan["apkgSha256"]
            and file_payload.get("sha256") == plan["apkgSha256"]
            and file_payload.get("sizeBytes") == plan["sizeBytes"]
            and identities.get("cardCount") == plan["cardCount"]
            and manifest.get("mediaCount") == plan["mediaCount"]
            and inventory.get("mediaCount") == plan["mediaCount"]
            and verification.get("contractDigest") == plan["verificationContractDigest"]
            and verification.get("contractVersion")
            == ANKI_DATA_VERIFICATION_CONTRACT_VERSION
        )
        blob_ref = file_payload.get("blobRef")
        if not checks or not isinstance(blob_ref, Mapping):
            raise AnkiImportExecutionError(
                "ARTIFACT_CORRUPT", "ImportPlan artifact graph is inconsistent"
            )
        return {
            "schemaVersion": 1,
            "apkgBlobRef": _clone(blob_ref),
            "apkgSha256": plan["apkgSha256"],
            "sizeBytes": plan["sizeBytes"],
            "deckNames": list(plan["deckNames"]),
            "cardCount": plan["cardCount"],
            "mediaCount": plan["mediaCount"],
            "templateFamily": plan["templateFamily"],
            "templateSchemaVersion": plan["templateSchemaVersion"],
            "cardIdentities": _clone(identities.get("cards")),
            "mediaEntries": _clone(manifest.get("entries")),
        }

    def authenticated_bundle(
        self,
        *,
        audience: ArtifactAudienceBinding,
        resolved: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Return the closed Worker bundle for another trusted Anki runtime."""

        return self._bundle(audience=audience, resolved=resolved)

    def _manifests(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project: Mapping[str, Any],
        plan_ref: Mapping[str, Any],
        operation_digest: str,
        import_intent_id: str,
        target_digest: str,
        apkg_sha256: str,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], str]:
        subject = {
            "kind": "project_task",
            "projectId": project["projectId"],
            "projectRevision": project["projectRevision"],
            "inputArtifacts": [
                {
                    "artifactId": plan_ref["artifactId"],
                    "artifactRevision": plan_ref["artifactRevision"],
                    "artifactDigest": plan_ref["artifactDigest"],
                }
            ],
            "sourceSnapshotDigests": [],
            "learningContractRevision": project["learningContract"]["contractRevision"],
        }
        work, work_digest = build_work_reuse_manifest(
            action_id="import_and_verify",
            subject=subject,
            component_versions=_COMPONENTS,
            service_configurations=[],
            work_partition_policy_digest=operation_digest,
        )
        capability, capability_digest = build_capability_binding(
            [
                {
                    "kind": "fixed",
                    "capabilityId": "runtime.card_service",
                    "implementationVersionOrDigest": "2.0.0",
                    "compatibilityContractVersion": ANKI_IMPORT_EXECUTION_POLICY_VERSION,
                },
                {
                    "kind": "fixed",
                    "capabilityId": "runtime.worker",
                    "implementationVersionOrDigest": "managed-worker",
                    "compatibilityContractVersion": ANKI_DATA_VERIFICATION_CONTRACT_VERSION,
                },
                {
                    "kind": "fixed",
                    "capabilityId": "service.anki",
                    "implementationVersionOrDigest": target_digest,
                    "compatibilityContractVersion": "ankiconnect-v6",
                },
            ]
        )
        scope = {
            "importIntentIdDigest": _digest(import_intent_id),
            "importPlanDigest": plan_ref["artifactDigest"],
            "targetDigest": target_digest,
            "apkgSha256": apkg_sha256,
        }
        authorization, authorization_digest = build_authorization_binding(
            audience=audience,
            service_instance_id=self._service_instance_id,
            bindings=[
                {
                    "action": "import_anki",
                    "authorizationRecordDigest": _digest(scope),
                    "constraintsDigest": _digest(
                        {"policy": "single-use-explicit-confirmation"}
                    ),
                    "exactScopeDigest": _digest(scope),
                    "expectedRevocationEpoch": 0,
                }
            ],
        )
        task_input, fingerprint = build_task_input_manifest(
            action_id="import_and_verify",
            work_reuse_manifest=work,
            work_reuse_digest=work_digest,
            subject=subject,
            authorization_binding_digest=authorization_digest,
            capability_binding_digest=capability_digest,
            component_versions=_COMPONENTS,
            service_bindings=[],
            operation_intent_digest=operation_digest,
            batch_policy_digest=_digest(
                {"policy": ANKI_IMPORT_EXECUTION_POLICY_VERSION}
            ),
        )
        return work, task_input, capability, authorization, fingerprint

    def _progress(
        self,
        task_id: str,
        audience: ArtifactAudienceBinding,
        payload: Mapping[str, Any],
    ) -> None:
        try:
            task = self._tasks.get_task(task_id, audience)
            if task.get("state") not in {"running", "cancelling"}:
                return
            raw = payload.get("percent")
            percent = (
                float(raw)
                if isinstance(raw, (int, float)) and not isinstance(raw, bool)
                else None
            )
            overall = None if percent is None else min(95.0, max(1.0, percent * 0.9))
            self._tasks.update_progress(
                task_id,
                audience,
                expected_revision=task["taskRevision"],
                operation_id="progress-" + _digest(dict(payload))[:40],
                phase=(
                    "anki_data_verification"
                    if str(payload.get("stage") or "") == "query"
                    else "anki_import"
                ),
                phase_percent=percent,
                overall_percent=overall,
            )
        except (StudyTaskError, TypeError, ValueError):
            return

    @staticmethod
    def _receipt_observation(result: Mapping[str, Any]) -> dict[str, Any]:
        attempted = result.get("import_attempted") is True
        skipped = result.get("import_skipped_existing") is True
        succeeded = skipped or (attempted and bool(result.get("import_result")))
        return {
            "importDisposition": "already_present" if skipped else "imported",
            "importAttempted": attempted,
            "importSucceeded": succeeded,
            "writeBoundaryComplete": succeeded,
        }

    @staticmethod
    def _result_payload(
        *,
        result: Mapping[str, Any],
        resolved: Mapping[str, Any],
        target_digest: str,
        operation_digest: str,
    ) -> dict[str, Any]:
        plan = resolved["importPlanPayload"]
        failed = result.get("failed_checks")
        if result.get("ok") is not True or not isinstance(failed, list) or failed:
            raise AnkiImportExecutionError(
                "ANKI_VERIFY_FAILED", "Anki import did not pass data verification"
            )
        expected = plan["cardCount"]
        verified = result.get("card_count")
        if (
            isinstance(verified, bool)
            or not isinstance(verified, int)
            or verified != expected
        ):
            raise AnkiImportExecutionError(
                "ANKI_VERIFY_FAILED", "Anki verified card count is inconsistent"
            )
        media_expected = result.get("media_count_expected")
        media_checked = result.get("media_count_checked")
        if (
            isinstance(media_expected, bool)
            or not isinstance(media_expected, int)
            or media_expected != plan["mediaCount"]
            or isinstance(media_checked, bool)
            or not isinstance(media_checked, int)
            or media_checked > media_expected
        ):
            raise AnkiImportExecutionError(
                "ANKI_VERIFY_FAILED", "Anki verified media count is inconsistent"
            )
        observation = AnkiImportExecutionRuntime._receipt_observation(result)
        if not observation["writeBoundaryComplete"]:
            raise AnkiImportExecutionError(
                "ANKI_VERIFY_FAILED", "Anki import did not complete its write boundary"
            )
        return {
            "schemaVersion": 1,
            "projectRevision": resolved["project"]["projectRevision"],
            "resultingProjectRevision": resolved["project"]["projectRevision"] + 1,
            "importPlanRef": _clone(resolved["importPlanRef"]),
            "importPlanDigest": resolved["importPlanRef"]["artifactDigest"],
            "apkgSha256": plan["apkgSha256"],
            "targetDigest": target_digest,
            "operationDigest": operation_digest,
            "importDisposition": observation["importDisposition"],
            "importAttempted": observation["importAttempted"],
            "importSucceeded": observation["importSucceeded"],
            "noteCount": plan["noteCount"],
            "cardCount": verified,
            "expectedCardCount": expected,
            "mediaCountExpected": media_expected,
            "mediaCountChecked": media_checked,
            "duplicateCardCount": int(result.get("duplicate_imported_card_count") or 0),
            "failedChecks": [],
            "dataVerification": "passed",
            "runtimeVerification": "not_assessed",
            "verificationContractVersion": ANKI_DATA_VERIFICATION_CONTRACT_VERSION,
            "policyVersion": ANKI_IMPORT_EXECUTION_POLICY_VERSION,
        }

    def _finish_failure(
        self,
        task_id: str,
        audience: ArtifactAudienceBinding,
        error: Exception,
    ) -> None:
        try:
            task = self._tasks.get_task(task_id, audience)
            if task.get("state") not in {"running", "cancelling"}:
                return
            code = getattr(error, "code", "ANKI_VERIFY_FAILED")
            if code in {
                "IMPORT_APPROVAL_REQUIRED",
                "IMPORT_INTENT_EXPIRED",
                "IMPORT_APPROVAL_CONSUMED",
                "ANKI_TARGET_CHANGED",
                "IMPORT_PLAN_STALE",
            }:
                code = "CONFIRMATION_REQUIRED"
                action = "confirm_anki_import"
            elif code in {"ANKI_OFFLINE"}:
                action = "open_anki"
            elif code in {"PACKAGE_VERIFY_FAILED", "ARTIFACT_CORRUPT"}:
                code = (
                    "PACKAGE_VERIFY_FAILED"
                    if code == "PACKAGE_VERIFY_FAILED"
                    else "ARTIFACT_CORRUPT"
                )
                action = "resolve_issue"
            else:
                code = "ANKI_VERIFY_FAILED"
                action = "resolve_issue"
            self._tasks.fail_task(
                task_id,
                audience,
                expected_revision=task["taskRevision"],
                operation_id="fail-" + _digest({"taskId": task_id, "code": code})[:40],
                code=code,
                stage="anki_import",
                retryable=False,
                remote_cost_state="none",
                retry_scope="none",
                authorization_state=(
                    "required" if code == "CONFIRMATION_REQUIRED" else "valid"
                ),
                required_action=action,
            )
        except StudyTaskError:
            return

    def _run(
        self,
        *,
        task_id: str,
        audience: ArtifactAudienceBinding,
        import_intent_id: str,
        operation_id: str,
        operation_digest: str,
        resolved: Mapping[str, Any],
        bundle: Mapping[str, Any],
        target_digest: str,
        cancel_event: threading.Event,
    ) -> None:
        try:
            current = self._preparation.resolve_current_import_plan_ref(
                audience=audience,
                import_plan_ref=resolved["importPlanRef"],
            )
            current_target = self._preparation.inspect_current_target()
            current_target_digest = _digest(current_target)
            if current_target_digest != target_digest:
                raise AnkiImportExecutionError(
                    "ANKI_TARGET_CHANGED", "Anki target changed before execution"
                )
            if cancel_event.is_set():
                raise AnkiImportExecutionError("TASK_CANCELLED", "Import cancelled")
            self._approvals.consume(
                audience=audience,
                import_intent_id=import_intent_id,
                execution_id=task_id,
                expected_import_plan_digest=current["importPlanRef"]["artifactDigest"],
                current_target_digest=current_target_digest,
            )
            result = self._executor(
                bundle,
                lambda payload: self._progress(task_id, audience, payload),
                cancel_event,
            )
            if cancel_event.is_set():
                raise AnkiImportExecutionError("TASK_CANCELLED", "Import cancelled")
            if not isinstance(result, Mapping):
                raise AnkiImportExecutionError(
                    "ANKI_VERIFY_FAILED", "Anki verification result is invalid"
                )
            observation = self._receipt_observation(result)
            receipt = None
            if observation["writeBoundaryComplete"]:
                receipt_digest = _digest(
                    {
                        "operationDigest": operation_digest,
                        "stage": "imported_unverified",
                    }
                )
                receipt_payload = {
                    "schemaVersion": 1,
                    "projectRevision": current["project"]["projectRevision"],
                    "resultingProjectRevision": current["project"]["projectRevision"] + 1,
                    "importPlanRef": _clone(current["importPlanRef"]),
                    "importPlanDigest": current["importPlanRef"]["artifactDigest"],
                    "apkgSha256": current["importPlanPayload"]["apkgSha256"],
                    "targetDigest": current_target_digest,
                    "importDisposition": observation["importDisposition"],
                    "importAttempted": observation["importAttempted"],
                    "importSucceeded": observation["importSucceeded"],
                    "writeBoundaryState": "observed_complete",
                    "policyVersion": ANKI_IMPORT_EXECUTION_POLICY_VERSION,
                }
                receipt = self._artifacts.publish_idempotent(
                    audience=audience,
                    project_id=current["project"]["projectId"],
                    project_revision=current["project"]["projectRevision"],
                    artifact_id="anki_import_receipt_" + operation_digest[:40],
                    artifact_revision=1,
                    payload_schema="study.anki-import-receipt",
                    payload_schema_version=1,
                    payload=receipt_payload,
                    producer=_PRODUCER,
                    parents=[current["importPlanRef"]],
                    input_fingerprint=operation_digest,
                    completeness={
                        "state": "complete",
                        "expectedUnits": current["importPlanPayload"]["cardCount"],
                        "processedUnits": current["importPlanPayload"]["cardCount"],
                        "omittedLocators": [],
                        "reasonCodes": [],
                    },
                    issue_refs=[],
                )
                self._projects.commit_artifact_stage(
                    audience=audience,
                    project_id=current["project"]["projectId"],
                    expected_project_revision=current["project"]["projectRevision"],
                    operation_id=operation_id + ":receipt",
                    operation_digest=receipt_digest,
                    task_id=task_id,
                    artifact_stage="imported_unverified",
                    artifact_refs=[receipt.artifact_ref],
                    artifact_handles=[receipt.handle],
                )
                current = self._preparation.resolve_current_import_plan_ref(
                    audience=audience,
                    import_plan_ref=current["importPlanRef"],
                )
            payload = self._result_payload(
                result=result,
                resolved=current,
                target_digest=current_target_digest,
                operation_digest=operation_digest,
            )
            publication = self._artifacts.publish_idempotent(
                audience=audience,
                project_id=current["project"]["projectId"],
                project_revision=current["project"]["projectRevision"],
                artifact_id="anki_verification_" + operation_digest[:40],
                artifact_revision=1,
                payload_schema="study.anki-verification",
                payload_schema_version=1,
                payload=payload,
                producer=_PRODUCER,
                parents=[current["importPlanRef"], receipt.artifact_ref] if receipt else [current["importPlanRef"]],
                input_fingerprint=operation_digest,
                completeness={
                    "state": "complete",
                    "expectedUnits": payload["expectedCardCount"],
                    "processedUnits": payload["cardCount"],
                    "omittedLocators": [],
                    "reasonCodes": [],
                },
                issue_refs=[],
            )
            task = self._tasks.get_task(task_id, audience)
            task = self._tasks.complete_work_unit(
                task_id,
                audience,
                expected_revision=task["taskRevision"],
                operation_id="complete-" + operation_digest[:37],
                work_unit_id="anki-import-and-verify",
                result_handles=[publication.handle],
            )
            task = self._tasks.succeed_task(
                task_id,
                audience,
                expected_revision=task["taskRevision"],
                operation_id="succeed-" + operation_digest[:38],
            )
            self._projects.commit_artifact_stage(
                audience=audience,
                project_id=current["project"]["projectId"],
                expected_project_revision=current["project"]["projectRevision"],
                operation_id=operation_id,
                operation_digest=operation_digest,
                task_id=task_id,
                artifact_stage="anki_data_verified",
                artifact_refs=[publication.artifact_ref],
                artifact_handles=[publication.handle],
            )
        except Exception as error:
            if getattr(error, "code", "") == "TASK_CANCELLED":
                try:
                    task = self._tasks.get_task(task_id, audience)
                    if task.get("state") == "running":
                        task = self._tasks.request_cancel(
                            task_id,
                            audience,
                            expected_revision=task["taskRevision"],
                            operation_id="request-internal-cancel",
                        )
                    if task.get("state") == "cancelling":
                        self._tasks.finish_cancellation(
                            task_id,
                            audience,
                            expected_revision=task["taskRevision"],
                            operation_id="finish-internal-cancel",
                            safe_checkpoint_proven=False,
                        )
                except StudyTaskError:
                    pass
            else:
                self._finish_failure(task_id, audience, error)
        finally:
            with self._active_lock:
                self._active.pop(task_id, None)

    def start(
        self,
        *,
        audience: ArtifactAudienceBinding,
        import_intent_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if not isinstance(idempotency_key, str) or not _IDEMPOTENCY_RE.fullmatch(
            idempotency_key
        ):
            raise AnkiImportExecutionError(
                "SCHEMA_INVALID", "idempotencyKey is invalid"
            )
        try:
            binding = self._approvals.get_binding(
                audience=audience, import_intent_id=import_intent_id
            )
            approval = self._approvals.get_intent(
                audience=audience, import_intent_id=import_intent_id
            )
            resolved = self._preparation.resolve_current_import_plan_ref(
                audience=audience, import_plan_ref=binding["importPlanRef"]
            )
            project = resolved["project"]
            plan_ref = resolved["importPlanRef"]
            plan = resolved["importPlanPayload"]
            current_target = self._preparation.inspect_current_target()
            target_digest = _digest(current_target)
            if (
                binding["importPlanDigest"] != plan_ref["artifactDigest"]
                or binding["apkgSha256"] != plan["apkgSha256"]
                or binding["targetDigest"] != target_digest
            ):
                raise AnkiImportExecutionError(
                    "IMPORT_PLAN_STALE",
                    "Import approval no longer matches current state",
                )
            operation_digest = _digest(
                {
                    "schema": "study.anki-import-execution.request",
                    "schemaVersion": 1,
                    "importIntentId": import_intent_id,
                    "importPlanDigest": plan_ref["artifactDigest"],
                    "targetDigest": target_digest,
                    "apkgSha256": plan["apkgSha256"],
                    "policyVersion": ANKI_IMPORT_EXECUTION_POLICY_VERSION,
                }
            )
            operation_id = "anki-import:" + idempotency_key
            prior = self._projects.get_operation_result(
                audience=audience,
                project_id=project["projectId"],
                operation_id=operation_id,
                operation_digest=operation_digest,
            )
            if prior is not None:
                return self.get_task(str(prior["taskId"]), audience)
            task_id = "task_anki_import_" + operation_digest[:40]
            try:
                existing = self._tasks.get_task(task_id, audience)
            except StudyTaskError as error:
                if error.code != "TASK_NOT_FOUND":
                    raise
            else:
                if existing.get("intent") != "import_and_verify":
                    raise AnkiImportExecutionError(
                        "TASK_ID_CONFLICT",
                        "Anki import task identity conflicts with another task",
                    )
                return self._public_task(existing, audience)
            if approval["approvalState"] != "approved":
                raise AnkiImportExecutionError(
                    "IMPORT_APPROVAL_REQUIRED",
                    "Trusted import approval is required",
                )
            bundle = self._bundle(audience=audience, resolved=resolved)
            work, task_input, capability, authorization, fingerprint = self._manifests(
                audience=audience,
                project=project,
                plan_ref=plan_ref,
                operation_digest=operation_digest,
                import_intent_id=import_intent_id,
                target_digest=target_digest,
                apkg_sha256=plan["apkgSha256"],
            )
            try:
                task = self._tasks.create_task(
                    audience=audience,
                    work_reuse_manifest=work,
                    task_input_manifest=task_input,
                    capability_binding=capability,
                    authorization_binding=authorization,
                    work_units=[
                        {
                            "workUnitId": "anki-import-and-verify",
                            "phase": "anki_import",
                        }
                    ],
                    cancellable=True,
                    resumability="none",
                    _task_id=task_id,
                )
            except StudyTaskError as error:
                if error.code != "TASK_ALREADY_EXISTS":
                    raise
                task = self._tasks.get_task(task_id, audience)
                if task.get("inputFingerprint") != fingerprint:
                    raise AnkiImportExecutionError(
                        "INPUT_REVISION_MISMATCH", "Anki import task input changed"
                    ) from error
            if task["state"] == "queued":
                task = self._tasks.start_task(
                    task_id,
                    audience,
                    expected_revision=task["taskRevision"],
                    operation_id="start-" + operation_digest[:40],
                )
                task = self._tasks.begin_work_unit(
                    task_id,
                    audience,
                    expected_revision=task["taskRevision"],
                    operation_id="begin-" + operation_digest[:40],
                    work_unit_id="anki-import-and-verify",
                )
                cancel_event = threading.Event()
                thread = threading.Thread(
                    target=self._run,
                    kwargs={
                        "task_id": task_id,
                        "audience": audience,
                        "import_intent_id": import_intent_id,
                        "operation_id": operation_id,
                        "operation_digest": operation_digest,
                        "resolved": resolved,
                        "bundle": bundle,
                        "target_digest": target_digest,
                        "cancel_event": cancel_event,
                    },
                    daemon=True,
                    name=f"study-anki-import-{task_id}",
                )
                with self._active_lock:
                    self._active[task_id] = _ActiveImport(cancel_event, thread)
                thread.start()
            return self._public_task(task, audience)
        except (
            AnkiImportApprovalError,
            AnkiImportPreparationError,
            ArtifactRegistryError,
            ProjectRegistryError,
            StudyTaskError,
            TaskManifestError,
        ) as error:
            raise AnkiImportExecutionError(
                getattr(error, "code", "ANKI_VERIFY_FAILED"),
                getattr(error, "message", str(error)),
            ) from error

    def _public_task(
        self, task: Mapping[str, Any], audience: ArtifactAudienceBinding
    ) -> dict[str, Any]:
        progress = (
            task.get("progress") if isinstance(task.get("progress"), Mapping) else {}
        )
        public: dict[str, Any] = {
            "schemaVersion": 1,
            "taskId": str(task.get("taskId") or ""),
            "intent": "import_and_verify",
            "state": str(task.get("state") or ""),
            "cancellable": bool(task.get("cancellable")),
            "resumability": str(task.get("resumability") or "none"),
            "progress": {
                "phase": str(progress.get("phase") or "anki_import"),
                "phasePercent": progress.get("phasePercent"),
                "overallPercent": progress.get("overallPercent"),
                "lastProgressAt": str(progress.get("lastProgressAt") or ""),
            },
        }
        if public["state"] == "succeeded":
            handles = task.get("resultHandles")
            if not isinstance(handles, list) or len(handles) != 1:
                raise AnkiImportExecutionError(
                    "ANKI_VERIFY_FAILED", "Anki verification task result is invalid"
                )
            ref, envelope = self._artifacts.resolve_with_ref(handles[0], audience)
            payload = envelope.get("payload")
            if envelope.get(
                "payloadSchema"
            ) != "study.anki-verification" or not isinstance(payload, Mapping):
                raise AnkiImportExecutionError(
                    "ANKI_VERIFY_FAILED", "Anki verification artifact is invalid"
                )
            project = self._projects.get_project(ref["projectId"], audience)
            committed = project.get("workflow", {}).get("artifactStage") in {
                "anki_data_verified",
                "anki_verified",
            } and _identity(ref) in {
                _identity(item)
                for item in project.get("latestArtifactRefs", [])
                if isinstance(item, Mapping)
                and item.get("payloadSchema") == "study.anki-verification"
            }
            if not committed:
                with self._active_lock:
                    finalizing = str(task.get("taskId") or "") in self._active
                public["state"] = "running" if finalizing else "interrupted"
                public["cancellable"] = False
                public["nextAction"] = "poll_task" if finalizing else "resolve_issue"
                return public
            public["result"] = {
                "artifactStage": "anki_data_verified",
                "projectRevision": payload["resultingProjectRevision"],
                "importDisposition": payload["importDisposition"],
                "cardCount": payload["cardCount"],
                "expectedCardCount": payload["expectedCardCount"],
                "mediaCountExpected": payload["mediaCountExpected"],
                "mediaCountChecked": payload["mediaCountChecked"],
                "duplicateCardCount": payload["duplicateCardCount"],
                "dataVerification": "passed",
                "runtimeVerification": "not_assessed",
                "nextAction": "open_anki",
            }
            public["nextAction"] = "open_anki"
        elif public["state"] in {"failed", "cancelled", "interrupted"}:
            failure = task.get("failure")
            if isinstance(failure, Mapping):
                public["error"] = {
                    "code": str(failure.get("code") or "ANKI_VERIFY_FAILED"),
                    "retryable": bool(failure.get("retryable")),
                    "stage": str(failure.get("stage") or "anki_import"),
                }
                if failure.get("requiredAction"):
                    public["error"]["requiredAction"] = str(failure["requiredAction"])
            public["nextAction"] = (
                "inspect_before_retry"
                if public["state"] == "interrupted"
                else "resolve_issue"
            )
        else:
            public["nextAction"] = "poll_task"
        return public

    def get_task(
        self, task_id: str, audience: ArtifactAudienceBinding
    ) -> dict[str, Any]:
        return self._public_task(self._tasks.get_task(task_id, audience), audience)

    def cancel_task(
        self, task_id: str, audience: ArtifactAudienceBinding
    ) -> dict[str, Any]:
        task = self._tasks.get_task(task_id, audience)
        if task.get("intent") != "import_and_verify":
            raise AnkiImportExecutionError(
                "TASK_NOT_CANCELLABLE", "Task is not an Anki import"
            )
        if task.get("state") in {"queued", "running"}:
            task = self._tasks.request_cancel(
                task_id,
                audience,
                expected_revision=task["taskRevision"],
                operation_id="request-public-cancel",
            )
            with self._active_lock:
                active = self._active.get(task_id)
            if active is not None:
                active.cancel_event.set()
        return self._public_task(task, audience)


__all__ = [
    "ANKI_IMPORT_EXECUTION_POLICY_VERSION",
    "AnkiImportExecutionError",
    "AnkiImportExecutionRuntime",
    "AnkiImportExecutor",
    "materialize_anki_worker_request",
]
