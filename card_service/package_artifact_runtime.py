"""Authenticated, recoverable APKG export from a current ProjectArtifact."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
import threading
import unicodedata
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

from workers.acg.apkg_package_contract import validate_apkg_package_contract

from .artifact_registry import (
    ArtifactAudienceBinding,
    ArtifactRegistry,
    ArtifactRegistryError,
    canonical_json_bytes,
)
from .card_artifact_runtime import CardArtifactRuntime, CardArtifactRuntimeError
from .local_resource_registry import ResolvedLocalResource
from .project_registry import ProjectRegistry, ProjectRegistryError
from .resource_runtime import ServiceResourceRuntime, ServiceResourceRuntimeError
from .task_coordinator import StudyTaskCoordinator, StudyTaskError
from .task_manifests import (
    TaskManifestError,
    build_authorization_binding,
    build_capability_binding,
    build_task_input_manifest,
    build_work_reuse_manifest,
)


PACKAGE_EXPORT_POLICY_VERSION = "authenticated-apkg-export-v1"
PACKAGE_CONTRACT_VERSION = "apkg-package-contract-v3"
_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_RESOURCE_RE = re.compile(r"^resource_[A-Za-z0-9_-]{43}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PRODUCER = {
    "component": "card-service.package-artifact-runtime",
    "version": "1.0.0",
}
_COMPONENTS = {
    "cardService": "2.0.0",
    "worker": "legacy-compatible",
    "sourceAdapterSetDigest": hashlib.sha256(
        b"study.source-adapter-set.v1"
    ).hexdigest(),
    "gateRuleSetVersion": "card-reliability-gates-v1",
    "templateFamily": "document_knowledge",
    "templateSchemaVersion": "v15",
    "compatibilityContractVersion": PACKAGE_CONTRACT_VERSION,
}


class PackageArtifactRuntimeError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class PackageExportCancelled(RuntimeError):
    pass


class PackageExportExecutor(Protocol):
    def __call__(
        self,
        legacy_project: Mapping[str, Any],
        progress: Callable[[Mapping[str, Any]], None],
        cancel_event: threading.Event,
    ) -> Mapping[str, Any]: ...


@dataclass
class _ActiveExport:
    cancel_event: threading.Event
    thread: threading.Thread


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _identity(ref: Mapping[str, Any]) -> tuple[str, int, str]:
    return (
        str(ref.get("artifactId") or ""),
        int(ref.get("artifactRevision") or 0),
        str(ref.get("artifactDigest") or ""),
    )


def _clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def _safe_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = "".join(
        " " if character.isspace() else character
        for character in normalized
        if ord(character) >= 32 and character not in '<>:"/\\|?*'
    )
    normalized = re.sub(r"\s+", " ", normalized).strip(" .")[:80]
    if not normalized:
        normalized = "Anki Study Cards"
    reserved = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{index}" for index in range(1, 10)),
        *(f"LPT{index}" for index in range(1, 10)),
    }
    if normalized.upper() in reserved:
        normalized = "Study " + normalized
    return normalized


def _regular_file(path: Path) -> os.stat_result:
    try:
        info = path.lstat()
    except OSError as error:
        raise PackageArtifactRuntimeError(
            "PACKAGE_VERIFY_FAILED", "APKG output is unavailable"
        ) from error
    attributes = int(getattr(info, "st_file_attributes", 0))
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or attributes & 0x400
        or info.st_nlink != 1
    ):
        raise PackageArtifactRuntimeError(
            "PACKAGE_VERIFY_FAILED", "APKG output is not a private regular file"
        )
    return info


def _file_digest(path: Path, *, maximum_bytes: int) -> tuple[int, str]:
    before = _regular_file(path)
    if before.st_size < 0 or before.st_size > maximum_bytes:
        raise PackageArtifactRuntimeError(
            "PACKAGE_VERIFY_FAILED", "APKG output exceeds its size limit"
        )
    total = 0
    digest = hashlib.sha256()
    try:
        with path.open("rb", buffering=0) as source:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > maximum_bytes:
                    raise PackageArtifactRuntimeError(
                        "PACKAGE_VERIFY_FAILED", "APKG output exceeds its size limit"
                    )
                digest.update(chunk)
    except PackageArtifactRuntimeError:
        raise
    except OSError as error:
        raise PackageArtifactRuntimeError(
            "PACKAGE_VERIFY_FAILED", "APKG output could not be read"
        ) from error
    after = _regular_file(path)
    if total != before.st_size or (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise PackageArtifactRuntimeError(
            "PACKAGE_VERIFY_FAILED", "APKG output changed while being verified"
        )
    return total, digest.hexdigest()


class PackageArtifactRuntime:
    """Run export asynchronously and promote only independently verified packages."""

    def __init__(
        self,
        *,
        root: Path,
        service_instance_id: str,
        artifacts: ArtifactRegistry,
        projects: ProjectRegistry,
        tasks: StudyTaskCoordinator,
        resources: ServiceResourceRuntime,
        card_artifacts: CardArtifactRuntime,
        export_executor: PackageExportExecutor,
    ) -> None:
        self._root = Path(root).absolute()
        self._root.mkdir(parents=True, exist_ok=True)
        self._service_instance_id = service_instance_id
        self._artifacts = artifacts
        self._projects = projects
        self._tasks = tasks
        self._resources = resources
        self._cards = card_artifacts
        self._export_executor = export_executor
        self._active: dict[str, _ActiveExport] = {}
        self._active_lock = threading.RLock()

    @staticmethod
    def _validate_output_ref(value: Mapping[str, Any]) -> dict[str, Any]:
        required = {
            "schemaVersion",
            "displayName",
            "resourceRevisionDigest",
            "constraints",
            "expiresAt",
            "kind",
            "outputResourceRef",
        }
        if not isinstance(value, Mapping) or set(value) != required:
            raise PackageArtifactRuntimeError(
                "OUTPUT_NOT_WRITABLE", "outputRef fields are invalid"
            )
        resource_ref = value.get("outputResourceRef")
        revision = value.get("resourceRevisionDigest")
        constraints = value.get("constraints")
        if (
            value.get("schemaVersion") != 1
            or value.get("kind") != "output_directory"
            or not isinstance(resource_ref, str)
            or not _RESOURCE_RE.fullmatch(resource_ref)
            or not isinstance(revision, str)
            or not _SHA256_RE.fullmatch(revision)
            or not isinstance(constraints, Mapping)
            or set(constraints) != {"actions", "maxFiles", "maxTotalBytes"}
            or constraints.get("actions") != ["create", "versioned"]
        ):
            raise PackageArtifactRuntimeError(
                "OUTPUT_NOT_WRITABLE", "outputRef is invalid"
            )
        return _clone(value)

    def _output_resolution(
        self,
        *,
        audience: ArtifactAudienceBinding,
        output_ref: Mapping[str, Any],
        use_id: str,
    ) -> tuple[ResolvedLocalResource, Mapping[str, Any]]:
        normalized = self._validate_output_ref(output_ref)
        try:
            summary = self._resources.local_registry.inspect(
                normalized["outputResourceRef"], audience
            )
        except Exception as error:
            raise PackageArtifactRuntimeError(
                getattr(error, "code", "OUTPUT_NOT_WRITABLE"),
                "output authorization is unavailable",
            ) from error
        expected = {
            "kind": "output_directory",
            "displayName": normalized["displayName"],
            "resourceRevisionDigest": normalized["resourceRevisionDigest"],
            "constraints": normalized["constraints"],
            "expiresAt": normalized["expiresAt"],
        }
        if any(summary.get(name) != value for name, value in expected.items()):
            raise PackageArtifactRuntimeError(
                "OUTPUT_NOT_WRITABLE", "outputRef no longer matches its authorization"
            )
        if summary.get("state") not in {"active", "exhausted"}:
            raise PackageArtifactRuntimeError(
                "OUTPUT_NOT_WRITABLE", "output authorization is no longer active"
            )
        try:
            resolved = self._resources.consume_local_grant(
                resource_ref=normalized["outputResourceRef"],
                audience=audience,
                use_id=use_id,
                action="versioned",
                expected_resource_revision_digest=normalized["resourceRevisionDigest"],
                expected_revocation_epoch=int(summary["revocationEpoch"]),
                requested_constraints=normalized["constraints"],
            )
        except ServiceResourceRuntimeError as error:
            raise PackageArtifactRuntimeError(error.code, error.message) from error
        return resolved, summary

    def _bundle(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project: Mapping[str, Any],
        project_ref: Mapping[str, Any],
        output_ref: Mapping[str, Any],
        output_summary: Mapping[str, Any],
        operation_digest: str,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], str]:
        subject = {
            "kind": "project_task",
            "projectId": project["projectId"],
            "projectRevision": project["projectRevision"],
            "inputArtifacts": [
                {
                    "artifactId": project_ref["artifactId"],
                    "artifactRevision": project_ref["artifactRevision"],
                    "artifactDigest": project_ref["artifactDigest"],
                }
            ],
            "sourceSnapshotDigests": [],
            "learningContractRevision": project["learningContract"]["contractRevision"],
        }
        work, work_digest = build_work_reuse_manifest(
            action_id="export_apkg",
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
                    "compatibilityContractVersion": PACKAGE_EXPORT_POLICY_VERSION,
                },
                {
                    "kind": "fixed",
                    "capabilityId": "runtime.worker",
                    "implementationVersionOrDigest": "managed-worker",
                    "compatibilityContractVersion": PACKAGE_CONTRACT_VERSION,
                },
            ]
        )
        constraints = output_ref["constraints"]
        scope = {
            "kind": "output_directory",
            "resourceRef": output_ref["outputResourceRef"],
            "resourceRevisionDigest": output_ref["resourceRevisionDigest"],
            "constraints": constraints,
        }
        authorization, authorization_digest = build_authorization_binding(
            audience=audience,
            service_instance_id=self._service_instance_id,
            bindings=[
                {
                    "action": "write_output",
                    "authorizationRecordDigest": _digest(
                        {
                            "resourceRef": output_ref["outputResourceRef"],
                            "resourceRevisionDigest": output_ref[
                                "resourceRevisionDigest"
                            ],
                        }
                    ),
                    "constraintsDigest": _digest(constraints),
                    "exactScopeDigest": _digest(scope),
                    "expectedRevocationEpoch": int(output_summary["revocationEpoch"]),
                }
            ],
        )
        task_input, fingerprint = build_task_input_manifest(
            action_id="export_apkg",
            work_reuse_manifest=work,
            work_reuse_digest=work_digest,
            subject=subject,
            authorization_binding_digest=authorization_digest,
            capability_binding_digest=capability_digest,
            component_versions=_COMPONENTS,
            service_bindings=[],
            operation_intent_digest=operation_digest,
            batch_policy_digest=_digest(
                {
                    "policy": PACKAGE_EXPORT_POLICY_VERSION,
                    "delivery": "versioned-no-replace",
                }
            ),
        )
        return work, task_input, capability, authorization, fingerprint

    def _package_metadata(
        self, apkg_path: Path, export_result: Mapping[str, Any]
    ) -> dict[str, Any]:
        inspection_root = self._root / "package-inspection"
        inspection_root.mkdir(parents=True, exist_ok=True)
        database_path = inspection_root / f"{uuid.uuid4().hex}.sqlite"
        try:
            with zipfile.ZipFile(apkg_path, "r") as archive:
                names = [
                    name for name in archive.namelist() if name == "collection.anki2"
                ]
                if len(names) != 1:
                    raise PackageArtifactRuntimeError(
                        "PACKAGE_VERIFY_FAILED",
                        "Current package route requires one inspectable Anki collection",
                    )
                info = archive.getinfo(names[0])
                if info.file_size > 256 * 1024 * 1024:
                    raise PackageArtifactRuntimeError(
                        "PACKAGE_VERIFY_FAILED",
                        "Anki collection exceeds its inspection limit",
                    )
                with archive.open(info, "r") as source, database_path.open(
                    "xb"
                ) as output:
                    total = 0
                    while True:
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > info.file_size or total > 256 * 1024 * 1024:
                            raise PackageArtifactRuntimeError(
                                "PACKAGE_VERIFY_FAILED",
                                "Anki collection exceeded its declared size",
                            )
                        output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                if total != info.file_size:
                    raise PackageArtifactRuntimeError(
                        "PACKAGE_VERIFY_FAILED", "Anki collection was truncated"
                    )
            connection = sqlite3.connect(
                f"file:{database_path.as_posix()}?mode=ro", uri=True
            )
            try:
                note_count = int(
                    connection.execute("select count(*) from notes").fetchone()[0]
                )
                card_count = int(
                    connection.execute("select count(*) from cards").fetchone()[0]
                )
                models_raw = connection.execute("select models from col").fetchone()[0]
            finally:
                connection.close()
            models = json.loads(models_raw)
            model_id = str(export_result.get("note_model_id") or "")
            model = models.get(model_id)
            if not isinstance(model, Mapping):
                raise PackageArtifactRuntimeError(
                    "PACKAGE_VERIFY_FAILED",
                    "Note Model identity is absent from the package",
                )
            templates = model.get("tmpls")
            if not isinstance(templates, list) or len(templates) != 1:
                raise PackageArtifactRuntimeError(
                    "PACKAGE_VERIFY_FAILED", "Note Model template shape is unsupported"
                )
            template = templates[0]
            if not isinstance(template, Mapping):
                raise PackageArtifactRuntimeError(
                    "PACKAGE_VERIFY_FAILED", "Note Model template is invalid"
                )
            encoded = lambda value: hashlib.sha256(
                str(value or "").encode("utf-8")
            ).hexdigest()
            return {
                "noteCount": note_count,
                "cardCount": card_count,
                "frontTemplateSha256": encoded(template.get("qfmt")),
                "backTemplateSha256": encoded(template.get("afmt")),
                "cssSha256": encoded(model.get("css")),
            }
        except PackageArtifactRuntimeError:
            raise
        except (
            OSError,
            zipfile.BadZipFile,
            sqlite3.Error,
            ValueError,
            TypeError,
        ) as error:
            raise PackageArtifactRuntimeError(
                "PACKAGE_VERIFY_FAILED", "Package metadata could not be inspected"
            ) from error
        finally:
            try:
                database_path.unlink()
            except FileNotFoundError:
                pass

    def _deliver(
        self,
        *,
        audience: ArtifactAudienceBinding,
        resource: ResolvedLocalResource,
        source: Path,
        title: str,
        expected_size: int,
        expected_sha256: str,
    ) -> str:
        try:
            self._resources.local_registry.assert_resolution_active(
                resource, audience, required_action="versioned"
            )
        except Exception as error:
            raise PackageArtifactRuntimeError(
                getattr(error, "code", "OUTPUT_NOT_WRITABLE"),
                "output authorization changed before delivery",
            ) from error
        root = resource.path
        try:
            root_info = root.lstat()
        except OSError as error:
            raise PackageArtifactRuntimeError(
                "OUTPUT_NOT_WRITABLE", "output directory is unavailable"
            ) from error
        if (
            not stat.S_ISDIR(root_info.st_mode)
            or stat.S_ISLNK(root_info.st_mode)
            or int(getattr(root_info, "st_file_attributes", 0)) & 0x400
        ):
            raise PackageArtifactRuntimeError(
                "OUTPUT_NOT_WRITABLE", "output directory is unsafe"
            )
        file_name = f"{_safe_name(title)}-{expected_sha256[:12]}.apkg"
        destination = root / file_name
        partial = root / f".{file_name}.{uuid.uuid4().hex}.partial"
        source_before = _regular_file(source)
        descriptor = None
        output = None
        digest = hashlib.sha256()
        total = 0
        try:
            flags = (
                os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOINHERIT", 0)
            )
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(source, flags)
            opened = os.fstat(descriptor)
            if (opened.st_dev, opened.st_ino, opened.st_size) != (
                source_before.st_dev,
                source_before.st_ino,
                source_before.st_size,
            ):
                raise PackageArtifactRuntimeError(
                    "PACKAGE_VERIFY_FAILED", "APKG changed before delivery"
                )
            output = os.open(
                partial,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_BINARY", 0)
                | getattr(os, "O_NOINHERIT", 0),
                0o600,
            )
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > expected_size:
                    raise PackageArtifactRuntimeError(
                        "PACKAGE_VERIFY_FAILED", "APKG changed during delivery"
                    )
                digest.update(chunk)
                offset = 0
                while offset < len(chunk):
                    written = os.write(output, chunk[offset:])
                    if written <= 0:
                        raise PackageArtifactRuntimeError(
                            "OUTPUT_NOT_WRITABLE", "output write stalled"
                        )
                    offset += written
            os.fsync(output)
            if total != expected_size or digest.hexdigest() != expected_sha256:
                raise PackageArtifactRuntimeError(
                    "PACKAGE_VERIFY_FAILED", "APKG integrity changed during delivery"
                )
            try:
                os.link(partial, destination)
            except FileExistsError:
                existing_size, existing_digest = _file_digest(
                    destination, maximum_bytes=expected_size
                )
                if existing_size != expected_size or existing_digest != expected_sha256:
                    raise PackageArtifactRuntimeError(
                        "OUTPUT_NOT_WRITABLE",
                        "versioned APKG destination contains conflicting content",
                    )
        except PackageArtifactRuntimeError:
            raise
        except OSError as error:
            raise PackageArtifactRuntimeError(
                "OUTPUT_NOT_WRITABLE", "APKG could not be delivered safely"
            ) from error
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if output is not None:
                os.close(output)
            try:
                partial.unlink()
            except FileNotFoundError:
                pass
        delivered_size, delivered_digest = _file_digest(
            destination, maximum_bytes=expected_size
        )
        if delivered_size != expected_size or delivered_digest != expected_sha256:
            raise PackageArtifactRuntimeError(
                "PACKAGE_VERIFY_FAILED", "delivered APKG failed final verification"
            )
        try:
            self._resources.local_registry.assert_resolution_active(
                resource, audience, required_action="versioned"
            )
        except Exception as error:
            raise PackageArtifactRuntimeError(
                getattr(error, "code", "OUTPUT_NOT_WRITABLE"),
                "output authorization changed during delivery",
            ) from error
        return file_name

    def _publish_package(
        self,
        *,
        audience: ArtifactAudienceBinding,
        resolved: Mapping[str, Any],
        export_result: Mapping[str, Any],
        output_resource: ResolvedLocalResource,
        input_fingerprint: str,
        operation_digest: str,
    ) -> str:
        project = resolved["project"]
        project_ref = resolved["projectRef"]
        project_artifact = resolved["projectArtifact"]
        project_payload = project_artifact["payload"]
        apkg_path = Path(str(export_result.get("apkg_path") or ""))
        expected_sha = str(export_result.get("apkg_sha256") or "")
        expected_size = export_result.get("apkg_size_bytes")
        if (
            not apkg_path.is_absolute()
            or not _SHA256_RE.fullmatch(expected_sha)
            or isinstance(expected_size, bool)
            or not isinstance(expected_size, int)
            or expected_size <= 0
        ):
            raise PackageArtifactRuntimeError(
                "PACKAGE_VERIFY_FAILED", "ExportResult package identity is invalid"
            )
        report = validate_apkg_package_contract(apkg_path, export_result)
        if not isinstance(report, Mapping) or report.get("ok") is not True:
            raise PackageArtifactRuntimeError(
                "PACKAGE_VERIFY_FAILED", "APKG failed the complete package contract"
            )
        actual_size, actual_sha = _file_digest(
            apkg_path, maximum_bytes=2 * 1024 * 1024 * 1024
        )
        if actual_size != expected_size or actual_sha != expected_sha:
            raise PackageArtifactRuntimeError(
                "PACKAGE_VERIFY_FAILED", "APKG identity differs from ExportResult"
            )
        metadata = self._package_metadata(apkg_path, export_result)
        expected_cards = len(project_payload["cardIds"])
        if (
            metadata["noteCount"] != expected_cards
            or metadata["cardCount"] != expected_cards
            or export_result.get("cards") != expected_cards
        ):
            raise PackageArtifactRuntimeError(
                "PACKAGE_VERIFY_FAILED",
                "APKG card accounting differs from ProjectArtifact",
            )
        blob = self._artifacts.put_blob_path(
            apkg_path,
            media_type="application/vnd.anki.apkg",
            maximum_bytes=2 * 1024 * 1024 * 1024,
        )
        if blob["sha256"] != actual_sha or blob["sizeBytes"] != actual_size:
            raise PackageArtifactRuntimeError(
                "PACKAGE_VERIFY_FAILED", "content-addressed APKG identity mismatch"
            )
        file_name = self._deliver(
            audience=audience,
            resource=output_resource,
            source=apkg_path,
            title=str(project.get("title") or "Anki Study Cards"),
            expected_size=actual_size,
            expected_sha256=actual_sha,
        )
        revision = project["projectRevision"]
        project_id = project["projectId"]
        file_payload = {
            "schemaVersion": 1,
            "blobRef": blob,
            "fileName": file_name,
            "sha256": actual_sha,
            "sizeBytes": actual_size,
            "outputResourceRefDigest": hashlib.sha256(
                output_resource.resource_ref.encode("ascii")
            ).hexdigest(),
            "deliveryPolicy": "versioned-no-replace-v1",
        }
        file_publication = self._artifacts.publish_idempotent(
            audience=audience,
            project_id=project_id,
            project_revision=revision,
            artifact_id="apkg_file_" + operation_digest[:40],
            artifact_revision=1,
            payload_schema="study.apkg-file",
            payload_schema_version=1,
            payload=file_payload,
            producer=_PRODUCER,
            parents=[project_ref],
            input_fingerprint=input_fingerprint,
            completeness={
                "state": "complete",
                "omittedLocators": [],
                "reasonCodes": [],
            },
            issue_refs=[],
        )
        ledger = export_result.get("card_media_ledger")
        manifest = export_result.get("media_manifest")
        if not isinstance(ledger, list) or not isinstance(manifest, Mapping):
            raise PackageArtifactRuntimeError(
                "PACKAGE_VERIFY_FAILED", "APKG identity or media ledger is missing"
            )
        identities = []
        for row in ledger:
            if not isinstance(row, Mapping):
                raise PackageArtifactRuntimeError(
                    "PACKAGE_VERIFY_FAILED", "APKG card identity ledger is invalid"
                )
            packaged_card_id = str(row.get("card_id") or "")
            source_card_id = str(row.get("source_card_id") or packaged_card_id)
            content_sha = str(row.get("note_content_sha256") or "")
            if (
                not packaged_card_id
                or source_card_id not in project_payload["cardIds"]
                or not _SHA256_RE.fullmatch(content_sha)
            ):
                raise PackageArtifactRuntimeError(
                    "PACKAGE_VERIFY_FAILED",
                    "APKG card identity is not bound to the project",
                )
            identities.append(
                {
                    "cardId": packaged_card_id,
                    "sourceCardId": source_card_id,
                    "noteContentSha256": content_sha,
                    "deckName": str(row.get("deck_name") or ""),
                }
            )
        identities.sort(key=lambda item: item["sourceCardId"].encode("utf-8"))
        if (
            len(identities) != expected_cards
            or len({row["cardId"] for row in identities}) != expected_cards
            or len({row["sourceCardId"] for row in identities}) != expected_cards
        ):
            raise PackageArtifactRuntimeError(
                "PACKAGE_VERIFY_FAILED", "APKG card identity set is incomplete"
            )
        identity_payload = {
            "schemaVersion": 1,
            "cards": identities,
            "cardCount": len(identities),
            "identityPolicy": "card-id-note-content-sha256-v1",
        }
        identity_publication = self._artifacts.publish_idempotent(
            audience=audience,
            project_id=project_id,
            project_revision=revision,
            artifact_id="card_identity_set_" + operation_digest[:40],
            artifact_revision=1,
            payload_schema="study.card-identity-set",
            payload_schema_version=1,
            payload=identity_payload,
            producer=_PRODUCER,
            parents=[project_ref],
            input_fingerprint=input_fingerprint,
            completeness={
                "state": "complete",
                "omittedLocators": [],
                "reasonCodes": [],
            },
            issue_refs=[],
        )
        manifest_payload = {
            "schemaVersion": 1,
            "entries": [
                {**_clone(value), "fileName": str(name)}
                for name, value in sorted(
                    manifest.items(), key=lambda item: str(item[0]).encode("utf-8")
                )
                if isinstance(value, Mapping)
            ],
            "mediaCount": len(manifest),
        }
        if len(manifest_payload["entries"]) != len(manifest):
            raise PackageArtifactRuntimeError(
                "PACKAGE_VERIFY_FAILED", "APKG media manifest is invalid"
            )
        manifest_publication = self._artifacts.publish_idempotent(
            audience=audience,
            project_id=project_id,
            project_revision=revision,
            artifact_id="package_media_manifest_" + operation_digest[:40],
            artifact_revision=1,
            payload_schema="study.package-media-manifest",
            payload_schema_version=1,
            payload=manifest_payload,
            producer=_PRODUCER,
            parents=[project_ref],
            input_fingerprint=input_fingerprint,
            completeness={
                "state": "complete",
                "omittedLocators": [],
                "reasonCodes": [],
            },
            issue_refs=[],
        )
        roles_by_card: dict[str, set[str]] = {
            row["cardId"]: set() for row in identities
        }
        for value in manifest.values():
            if not isinstance(value, Mapping):
                continue
            card_id = str(value.get("card_id") or "")
            role = str(value.get("role") or "")
            if card_id in roles_by_card and role:
                roles_by_card[card_id].add(role)
        inventory_payload = {
            "schemaVersion": 1,
            "cards": [
                {"cardId": card_id, "mediaRoles": sorted(roles_by_card[card_id])}
                for card_id in sorted(roles_by_card)
            ],
            "mediaCount": len(manifest),
        }
        inventory_publication = self._artifacts.publish_idempotent(
            audience=audience,
            project_id=project_id,
            project_revision=revision,
            artifact_id="card_media_inventory_" + operation_digest[:40],
            artifact_revision=1,
            payload_schema="study.card-media-role-inventory",
            payload_schema_version=1,
            payload=inventory_payload,
            producer=_PRODUCER,
            parents=[
                identity_publication.artifact_ref,
                manifest_publication.artifact_ref,
            ],
            input_fingerprint=input_fingerprint,
            completeness={
                "state": "complete",
                "omittedLocators": [],
                "reasonCodes": [],
            },
            issue_refs=[],
        )
        reliability_ref = project_payload["reliabilityManifestRef"]
        package_payload = {
            "projectRef": dict(project_ref),
            "projectRevision": revision,
            "resultingProjectRevision": revision + 1,
            "apkgFileRef": file_publication.artifact_ref["artifactId"],
            "apkgSha256": actual_sha,
            "sizeBytes": actual_size,
            "fileName": file_name,
            "deckNames": [str(value) for value in export_result.get("deck_names", [])],
            "noteCount": metadata["noteCount"],
            "cardCount": metadata["cardCount"],
            "cardIdentitySetRef": dict(identity_publication.artifact_ref),
            "cardIdentitySetDigest": identity_publication.artifact_ref[
                "artifactDigest"
            ],
            "mediaCount": len(manifest),
            "mediaManifestRef": dict(manifest_publication.artifact_ref),
            "mediaManifestDigest": manifest_publication.artifact_ref["artifactDigest"],
            "cardMediaRoleInventoryRef": dict(inventory_publication.artifact_ref),
            "cardMediaRoleInventoryDigest": inventory_publication.artifact_ref[
                "artifactDigest"
            ],
            "templateFamily": str(export_result.get("template_family") or ""),
            "templateSchemaVersion": str(export_result.get("template_schema") or ""),
            "noteModelId": str(export_result.get("note_model_id") or ""),
            "compatibilityContractVersion": str(
                export_result.get("compatibility_contract_version") or ""
            ),
            "frontTemplateSha256": metadata["frontTemplateSha256"],
            "backTemplateSha256": metadata["backTemplateSha256"],
            "cssSha256": metadata["cssSha256"],
            "reliabilityManifestRef": dict(reliability_ref),
            "exportProducer": dict(_PRODUCER),
        }
        package_publication = self._artifacts.publish_idempotent(
            audience=audience,
            project_id=project_id,
            project_revision=revision,
            artifact_id="package_" + operation_digest[:40],
            artifact_revision=1,
            payload_schema="study.package-artifact",
            payload_schema_version=1,
            payload=package_payload,
            producer=_PRODUCER,
            parents=[
                project_ref,
                file_publication.artifact_ref,
                identity_publication.artifact_ref,
                manifest_publication.artifact_ref,
                inventory_publication.artifact_ref,
                reliability_ref,
            ],
            input_fingerprint=input_fingerprint,
            completeness={
                "state": "complete",
                "expectedUnits": expected_cards,
                "processedUnits": expected_cards,
                "omittedLocators": [],
                "reasonCodes": [],
            },
            issue_refs=[],
        )
        return package_publication.handle

    def resolve_current_package_artifact(
        self,
        *,
        audience: ArtifactAudienceBinding,
        package_artifact_handle: str,
    ) -> dict[str, Any]:
        """Resolve and reverify the current package without disclosing its Blob path."""

        try:
            package_ref, envelope = self._artifacts.resolve_with_ref(
                package_artifact_handle, audience
            )
            if envelope.get("payloadSchema") != "study.package-artifact":
                raise PackageArtifactRuntimeError(
                    "PACKAGE_ARTIFACT_INVALID", "package handle has the wrong schema"
                )
            payload = envelope.get("payload")
            required = {
                "projectRef",
                "projectRevision",
                "resultingProjectRevision",
                "apkgFileRef",
                "apkgSha256",
                "sizeBytes",
                "fileName",
                "deckNames",
                "noteCount",
                "cardCount",
                "cardIdentitySetRef",
                "cardIdentitySetDigest",
                "mediaCount",
                "mediaManifestRef",
                "mediaManifestDigest",
                "cardMediaRoleInventoryRef",
                "cardMediaRoleInventoryDigest",
                "templateFamily",
                "templateSchemaVersion",
                "noteModelId",
                "compatibilityContractVersion",
                "frontTemplateSha256",
                "backTemplateSha256",
                "cssSha256",
                "reliabilityManifestRef",
                "exportProducer",
            }
            if not isinstance(payload, Mapping) or set(payload) != required:
                raise PackageArtifactRuntimeError(
                    "PACKAGE_ARTIFACT_INVALID", "PackageArtifact fields are invalid"
                )
            project = self._projects.get_project(package_ref["projectId"], audience)
            current_packages = {
                _identity(value)
                for value in project.get("latestArtifactRefs", [])
                if isinstance(value, Mapping)
                and value.get("payloadSchema") == "study.package-artifact"
            }
            if (
                project.get("workflow", {}).get("artifactStage")
                not in {
                    "apkg_ready",
                    "imported_unverified",
                    "anki_data_verified",
                    "anki_verified",
                }
                or _identity(package_ref) not in current_packages
                or project.get("projectRevision", 0)
                < payload.get("resultingProjectRevision", 0)
            ):
                raise PackageArtifactRuntimeError(
                    "PACKAGE_ARTIFACT_STALE", "PackageArtifact is not current"
                )
            file_parents = [
                value
                for value in envelope.get("parents", [])
                if isinstance(value, Mapping)
                and value.get("payloadSchema") == "study.apkg-file"
                and value.get("artifactId") == payload.get("apkgFileRef")
            ]
            if len(file_parents) != 1:
                raise PackageArtifactRuntimeError(
                    "PACKAGE_ARTIFACT_INVALID", "APKG file parent is invalid"
                )
            file_handle = self._artifacts.issue_handle(file_parents[0], audience)
            file_ref, file_envelope = self._artifacts.resolve_with_ref(
                file_handle, audience
            )
            file_payload = file_envelope.get("payload")
            if (
                file_envelope.get("payloadSchema") != "study.apkg-file"
                or not isinstance(file_payload, Mapping)
                or file_payload.get("sha256") != payload.get("apkgSha256")
                or file_payload.get("sizeBytes") != payload.get("sizeBytes")
                or file_payload.get("fileName") != payload.get("fileName")
                or not isinstance(file_payload.get("blobRef"), Mapping)
                or file_payload["blobRef"].get("sha256")
                != payload.get("apkgSha256")
                or file_payload["blobRef"].get("sizeBytes")
                != payload.get("sizeBytes")
            ):
                raise PackageArtifactRuntimeError(
                    "PACKAGE_ARTIFACT_INVALID", "APKG file identity is invalid"
                )
            self._artifacts.read_blob_prefix(
                file_payload["blobRef"], maximum_prefix_bytes=0
            )
            return {
                "packageRef": _clone(package_ref),
                "packageEnvelope": _clone(envelope),
                "packagePayload": _clone(payload),
                "fileRef": _clone(file_ref),
                "fileEnvelope": _clone(file_envelope),
                "filePayload": _clone(file_payload),
                "project": _clone(project),
            }
        except (ArtifactRegistryError, ProjectRegistryError) as error:
            raise PackageArtifactRuntimeError(error.code, error.message) from error

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
            raw = payload.get("overallPercent", payload.get("percent"))
            percent = (
                int(raw)
                if isinstance(raw, (int, float)) and not isinstance(raw, bool)
                else None
            )
            percent = min(94, max(0, percent)) if percent is not None else None
            previous = task.get("progress", {}).get("overallPercent")
            if percent is None or (
                isinstance(previous, (int, float)) and percent <= previous
            ):
                return
            self._tasks.update_progress(
                task_id,
                audience,
                expected_revision=task["taskRevision"],
                operation_id=f"export-progress-{percent:02d}",
                phase="export",
                phase_percent=percent,
                overall_percent=percent,
            )
        except StudyTaskError:
            return

    def _finish_failure(
        self,
        task_id: str,
        audience: ArtifactAudienceBinding,
        error: Exception,
    ) -> None:
        try:
            task = self._tasks.get_task(task_id, audience)
            if task.get("state") == "cancelling" or isinstance(
                error, PackageExportCancelled
            ):
                if task.get("state") == "running":
                    task = self._tasks.request_cancel(
                        task_id,
                        audience,
                        expected_revision=task["taskRevision"],
                        operation_id="cancel-from-exporter",
                    )
                self._tasks.finish_cancellation(
                    task_id,
                    audience,
                    expected_revision=task["taskRevision"],
                    operation_id="finish-export-cancellation",
                    safe_checkpoint_proven=True,
                )
                return
            if task.get("state") != "running":
                return
            code = getattr(error, "code", "WORKER_EXITED")
            if code not in {
                "PACKAGE_VERIFY_FAILED",
                "OUTPUT_NOT_WRITABLE",
                "WORKER_EXITED",
            }:
                code = "WORKER_EXITED"
            self._tasks.fail_task(
                task_id,
                audience,
                expected_revision=task["taskRevision"],
                operation_id="fail-export-task",
                code=code,
                stage="export",
                retryable=True,
                remote_cost_state="none",
                retry_scope="phase",
                authorization_state=(
                    "required" if code == "OUTPUT_NOT_WRITABLE" else "valid"
                ),
                required_action=(
                    "request_output_grant"
                    if code == "OUTPUT_NOT_WRITABLE"
                    else "resume_task"
                ),
            )
        except StudyTaskError:
            return

    def _run_export(
        self,
        *,
        task_id: str,
        audience: ArtifactAudienceBinding,
        resolved: Mapping[str, Any],
        output_resource: ResolvedLocalResource,
        legacy_project: Mapping[str, Any],
        input_fingerprint: str,
        operation_digest: str,
        operation_id: str,
        cancel_event: threading.Event,
    ) -> None:
        try:
            result = self._export_executor(
                legacy_project,
                lambda payload: self._progress(task_id, audience, payload),
                cancel_event,
            )
            if cancel_event.is_set():
                raise PackageExportCancelled("export cancelled")
            package_handle = self._publish_package(
                audience=audience,
                resolved=resolved,
                export_result=result,
                output_resource=output_resource,
                input_fingerprint=input_fingerprint,
                operation_digest=operation_digest,
            )
            task = self._tasks.get_task(task_id, audience)
            if task.get("state") != "running":
                raise PackageExportCancelled("export was cancelled before publication")
            task = self._tasks.complete_work_unit(
                task_id,
                audience,
                expected_revision=task["taskRevision"],
                operation_id="complete-" + operation_digest[:37],
                work_unit_id="apkg-export",
                result_handles=[package_handle],
            )
            task = self._tasks.succeed_task(
                task_id,
                audience,
                expected_revision=task["taskRevision"],
                operation_id="succeed-" + operation_digest[:38],
            )
            package_ref, _ = self._artifacts.resolve_with_ref(package_handle, audience)
            self._projects.commit_artifact_stage(
                audience=audience,
                project_id=resolved["project"]["projectId"],
                expected_project_revision=resolved["project"]["projectRevision"],
                operation_id=operation_id,
                operation_digest=operation_digest,
                task_id=task_id,
                artifact_stage="apkg_ready",
                artifact_refs=[package_ref],
                artifact_handles=[package_handle],
            )
        except Exception as error:
            self._finish_failure(task_id, audience, error)
        finally:
            with self._active_lock:
                self._active.pop(task_id, None)

    def start_export(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_id: str,
        expected_project_revision: int,
        idempotency_key: str,
        project_artifact_handle: str,
        output_ref: Mapping[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(idempotency_key, str) or not _IDEMPOTENCY_RE.fullmatch(
            idempotency_key
        ):
            raise PackageArtifactRuntimeError(
                "PACKAGE_EXPORT_REQUEST_INVALID", "idempotencyKey is invalid"
            )
        try:
            resolved = self._cards.resolve_current_project_artifact(
                audience=audience,
                project_artifact_handle=project_artifact_handle,
            )
        except CardArtifactRuntimeError as error:
            raise PackageArtifactRuntimeError(error.code, error.message) from error
        project = resolved["project"]
        if project.get("projectId") != project_id:
            raise PackageArtifactRuntimeError(
                "PACKAGE_EXPORT_PROJECT_MISMATCH",
                "ProjectArtifact belongs to another project",
            )
        normalized_output = self._validate_output_ref(output_ref)
        operation_digest = _digest(
            {
                "schema": "study.package-export.request",
                "schemaVersion": 1,
                "projectId": project_id,
                "projectRevision": expected_project_revision,
                "projectArtifactDigest": resolved["projectRef"]["artifactDigest"],
                "outputResourceRef": normalized_output["outputResourceRef"],
                "outputRevisionDigest": normalized_output["resourceRevisionDigest"],
                "outputConstraints": normalized_output["constraints"],
                "policyVersion": PACKAGE_EXPORT_POLICY_VERSION,
            }
        )
        operation_id = "package-export:" + idempotency_key
        try:
            prior = self._projects.get_operation_result(
                audience=audience,
                project_id=project_id,
                operation_id=operation_id,
                operation_digest=operation_digest,
            )
            if prior is not None:
                return self.get_task(str(prior["taskId"]), audience)
        except ProjectRegistryError as error:
            raise PackageArtifactRuntimeError(error.code, error.message) from error
        if project.get("projectRevision") != expected_project_revision:
            raise PackageArtifactRuntimeError(
                "PROJECT_REVISION_CONFLICT", "project changed before APKG export"
            )
        if project.get("workflow", {}).get("artifactStage") != "cards_ready":
            raise PackageArtifactRuntimeError(
                "PACKAGE_EXPORT_STAGE_CONFLICT", "APKG export is not current"
            )
        output_resource, output_summary = self._output_resolution(
            audience=audience,
            output_ref=normalized_output,
            use_id="package-export-" + operation_digest[:40],
        )
        try:
            work, task_input, capability, authorization, input_fingerprint = (
                self._bundle(
                    audience=audience,
                    project=project,
                    project_ref=resolved["projectRef"],
                    output_ref=normalized_output,
                    output_summary=output_summary,
                    operation_digest=operation_digest,
                )
            )
            task_id = "task_package_export_" + operation_digest[:40]
            try:
                task = self._tasks.create_task(
                    audience=audience,
                    work_reuse_manifest=work,
                    task_input_manifest=task_input,
                    capability_binding=capability,
                    authorization_binding=authorization,
                    work_units=[{"workUnitId": "apkg-export", "phase": "export"}],
                    cancellable=True,
                    resumability="restart_phase",
                    _task_id=task_id,
                )
            except StudyTaskError as error:
                if error.code != "TASK_ALREADY_EXISTS":
                    raise
                task = self._tasks.get_task(task_id, audience)
                if task.get("inputFingerprint") != input_fingerprint:
                    raise PackageArtifactRuntimeError(
                        "TASK_INPUT_MISMATCH", "APKG export task input changed"
                    ) from error
            if task["state"] == "succeeded":
                handles = task.get("resultHandles")
                if (
                    not isinstance(handles, Sequence)
                    or isinstance(handles, (str, bytes))
                    or len(handles) != 1
                ):
                    raise PackageArtifactRuntimeError(
                        "PACKAGE_EXPORT_RESULT_INVALID",
                        "completed export task has no PackageArtifact",
                    )
                package_ref, package = self._artifacts.resolve_with_ref(
                    handles[0], audience
                )
                if package.get("payloadSchema") != "study.package-artifact":
                    raise PackageArtifactRuntimeError(
                        "PACKAGE_EXPORT_RESULT_INVALID",
                        "completed export task result is invalid",
                    )
                self._projects.commit_artifact_stage(
                    audience=audience,
                    project_id=project_id,
                    expected_project_revision=expected_project_revision,
                    operation_id=operation_id,
                    operation_digest=operation_digest,
                    task_id=task_id,
                    artifact_stage="apkg_ready",
                    artifact_refs=[package_ref],
                    artifact_handles=[handles[0]],
                )
                return self._public_task(task, audience)
            if task["state"] in {"failed", "cancelled", "interrupted"}:
                return self._public_task(task, audience)
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
                    work_unit_id="apkg-export",
                )
                cancel_event = threading.Event()
                thread = threading.Thread(
                    target=self._run_export,
                    kwargs={
                        "task_id": task_id,
                        "audience": audience,
                        "resolved": resolved,
                        "output_resource": output_resource,
                        "legacy_project": resolved["legacyProjection"]["projection"][
                            "project"
                        ],
                        "input_fingerprint": input_fingerprint,
                        "operation_digest": operation_digest,
                        "operation_id": operation_id,
                        "cancel_event": cancel_event,
                    },
                    daemon=True,
                    name=f"study-apkg-export-{task_id}",
                )
                with self._active_lock:
                    self._active[task_id] = _ActiveExport(cancel_event, thread)
                thread.start()
            return self._public_task(task, audience)
        except (
            ArtifactRegistryError,
            ProjectRegistryError,
            StudyTaskError,
            TaskManifestError,
        ) as error:
            raise PackageArtifactRuntimeError(
                getattr(error, "code", "PACKAGE_EXPORT_FAILED"),
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
            "intent": str(task.get("intent") or ""),
            "state": str(task.get("state") or ""),
            "cancellable": bool(task.get("cancellable")),
            "resumability": str(task.get("resumability") or "none"),
            "progress": {
                "phase": str(progress.get("phase") or "request"),
                "phasePercent": progress.get("phasePercent"),
                "overallPercent": progress.get("overallPercent"),
                "lastProgressAt": str(progress.get("lastProgressAt") or ""),
            },
        }
        state = public["state"]
        if state == "succeeded":
            handles = task.get("resultHandles")
            if (
                not isinstance(handles, Sequence)
                or isinstance(handles, (str, bytes))
                or len(handles) != 1
            ):
                raise PackageArtifactRuntimeError(
                    "PACKAGE_EXPORT_RESULT_INVALID", "export task result is invalid"
                )
            ref, envelope = self._artifacts.resolve_with_ref(handles[0], audience)
            if envelope.get("payloadSchema") != "study.package-artifact":
                raise PackageArtifactRuntimeError(
                    "PACKAGE_EXPORT_RESULT_INVALID",
                    "export result is not a PackageArtifact",
                )
            payload = envelope.get("payload")
            if not isinstance(payload, Mapping):
                raise PackageArtifactRuntimeError(
                    "PACKAGE_EXPORT_RESULT_INVALID",
                    "PackageArtifact payload is invalid",
                )
            try:
                project = self._projects.get_project(ref["projectId"], audience)
            except ProjectRegistryError as error:
                raise PackageArtifactRuntimeError(error.code, error.message) from error
            current_packages = {
                _identity(value)
                for value in project.get("latestArtifactRefs", [])
                if isinstance(value, Mapping)
                and value.get("payloadSchema") == "study.package-artifact"
            }
            committed = (
                project.get("workflow", {}).get("artifactStage")
                in {
                    "apkg_ready",
                    "imported_unverified",
                    "anki_data_verified",
                    "anki_verified",
                }
                and _identity(ref) in current_packages
                and project.get("projectRevision", 0)
                >= payload.get("resultingProjectRevision", 0)
            )
            if not committed:
                with self._active_lock:
                    finalizing = str(task.get("taskId") or "") in self._active
                public["state"] = "running" if finalizing else "interrupted"
                public["cancellable"] = False
                public["progress"] = {
                    **public["progress"],
                    "phase": "export",
                    "phasePercent": 99,
                    "overallPercent": 99,
                }
                if finalizing:
                    public["nextAction"] = "poll_task"
                else:
                    public["error"] = {
                        "code": "PROJECT_COMMIT_PENDING",
                        "retryable": True,
                        "stage": "export",
                        "requiredAction": "export_apkg",
                    }
                    public["nextAction"] = "export_apkg"
                return public
            public["result"] = {
                "packageArtifactHandle": self._artifacts.issue_handle(ref, audience),
                "artifactStage": "apkg_ready",
                "projectRevision": payload["resultingProjectRevision"],
                "apkgSha256": payload["apkgSha256"],
                "sizeBytes": payload["sizeBytes"],
                "fileName": payload["fileName"],
                "deckNames": list(payload["deckNames"]),
                "noteCount": payload["noteCount"],
                "cardCount": payload["cardCount"],
                "mediaCount": payload["mediaCount"],
                "deliveryState": "written",
                "nextAction": "prepare_anki_import",
            }
            public["nextAction"] = "prepare_anki_import"
        elif state in {"failed", "cancelled", "interrupted"}:
            failure = task.get("failure")
            if isinstance(failure, Mapping):
                public["error"] = {
                    "code": str(failure.get("code") or "PACKAGE_EXPORT_FAILED"),
                    "retryable": bool(failure.get("retryable")),
                    "stage": str(failure.get("stage") or "export"),
                }
                if failure.get("requiredAction"):
                    public["error"]["requiredAction"] = str(failure["requiredAction"])
            public["nextAction"] = (
                "resume_task" if state != "cancelled" else "export_apkg"
            )
        else:
            public["nextAction"] = "poll_task"
        return public

    def get_task(
        self, task_id: str, audience: ArtifactAudienceBinding
    ) -> dict[str, Any]:
        try:
            task = self._tasks.get_task(task_id, audience)
        except StudyTaskError as error:
            raise PackageArtifactRuntimeError(error.code, error.message) from error
        return self._public_task(task, audience)

    def cancel_task(
        self, task_id: str, audience: ArtifactAudienceBinding
    ) -> dict[str, Any]:
        try:
            task = self._tasks.get_task(task_id, audience)
            if task.get("intent") != "export_apkg":
                raise PackageArtifactRuntimeError(
                    "TASK_NOT_CANCELLABLE",
                    "only APKG export tasks are cancellable here",
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
        except StudyTaskError as error:
            raise PackageArtifactRuntimeError(error.code, error.message) from error


__all__ = [
    "PACKAGE_CONTRACT_VERSION",
    "PACKAGE_EXPORT_POLICY_VERSION",
    "PackageArtifactRuntime",
    "PackageArtifactRuntimeError",
    "PackageExportCancelled",
    "PackageExportExecutor",
]
