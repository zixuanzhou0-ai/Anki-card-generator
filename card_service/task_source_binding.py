"""Authenticated binding of opaque local input grants to one StudyTask.

The public MCP surface may carry an opaque ``InputRef``.  This module is the
only bridge from that public value to a task-owned byte snapshot.  It verifies
the current StudyTask input identity, consumes the audience-bound grant,
stages a stable copy, and persists an authenticated private binding.  Public
callers never receive the staging receipt or a path; Workers receive only the
already-verified workspace-relative locator.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterator, Mapping

from .artifact_registry import ArtifactAudienceBinding, canonical_json_bytes
from .resource_runtime import ServiceResourceRuntime, ServiceResourceRuntimeError
from .resource_staging import ResourceStagingError, StagedResource
from .task_coordinator import StudyTaskCoordinator, StudyTaskError


_BINDING_REF_RE = re.compile(r"^srcb1_[A-Za-z0-9_-]{43}$")
_RESOURCE_REF_RE = re.compile(r"^resource_[A-Za-z0-9_-]{43}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_FILE_FIELDS = {
    "schemaVersion",
    "kind",
    "fileResourceRef",
    "displayName",
    "resourceRevisionDigest",
    "constraints",
    "expiresAt",
}
_DIRECTORY_FIELDS = {
    "schemaVersion",
    "kind",
    "directoryResourceRef",
    "displayName",
    "resourceRevisionDigest",
    "constraints",
    "expiresAt",
}


class TaskSourceBindingError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _require_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise TaskSourceBindingError(
            "TASK_SOURCE_REQUEST_INVALID", f"{label} is invalid"
        )
    return value


def _require_digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise TaskSourceBindingError(
            "TASK_SOURCE_REQUEST_INVALID", f"{label} is invalid"
        )
    return value


def _require_binding_ref(value: Any) -> str:
    if not isinstance(value, str) or not _BINDING_REF_RE.fullmatch(value):
        raise TaskSourceBindingError(
            "TASK_SOURCE_BINDING_REF_INVALID", "source binding reference is invalid"
        )
    return value


def _clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


class TaskSourceBindingRuntime:
    """Bind trusted local sources to task input fingerprints and workspaces."""

    def __init__(
        self,
        root: Path,
        *,
        authentication_key: bytes,
        service_instance_id: str,
        resource_runtime: ServiceResourceRuntime,
        task_coordinator: StudyTaskCoordinator,
        key_id: str = "study-task-source-binding-v1",
    ) -> None:
        if not isinstance(authentication_key, bytes) or len(authentication_key) < 32:
            raise TaskSourceBindingError(
                "TASK_SOURCE_KEY_INVALID",
                "source binding authentication key must contain at least 256 bits",
            )
        if not isinstance(resource_runtime, ServiceResourceRuntime):
            raise TaskSourceBindingError(
                "TASK_SOURCE_RUNTIME_INVALID", "resource runtime is invalid"
            )
        if not isinstance(task_coordinator, StudyTaskCoordinator):
            raise TaskSourceBindingError(
                "TASK_SOURCE_RUNTIME_INVALID", "task coordinator is invalid"
            )
        _require_id(service_instance_id, "serviceInstanceId")
        _require_id(key_id, "keyId")
        if resource_runtime.service_instance_id != service_instance_id:
            raise TaskSourceBindingError(
                "TASK_SOURCE_SERVICE_MISMATCH",
                "resource and task source services do not share one instance identity",
            )
        self._root = Path(root).absolute()
        self._root.mkdir(parents=True, exist_ok=True)
        self._records = self._root / "records"
        self._records.mkdir(exist_ok=True)
        self._lock_path = self._root / "task-source-binding.lock"
        try:
            descriptor = os.open(
                self._lock_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOINHERIT", 0),
                0o600,
            )
        except FileExistsError:
            descriptor = None
        if descriptor is not None:
            try:
                if os.write(descriptor, b"\x00") != 1:
                    raise OSError("lock initialization stalled")
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        self._key = bytes(authentication_key)
        self._service_instance_id = service_instance_id
        self._key_id = key_id
        self._resources = resource_runtime
        self._tasks = task_coordinator
        self._thread_lock = threading.RLock()

    def _mac(self, domain: str, value: Mapping[str, Any] | bytes) -> str:
        raw = value if isinstance(value, bytes) else canonical_json_bytes(dict(value))
        return hmac.new(
            self._key,
            domain.encode("ascii") + b"\x00" + raw,
            hashlib.sha256,
        ).hexdigest()

    def _audience_digest(self, audience: ArtifactAudienceBinding) -> str:
        if not isinstance(audience, ArtifactAudienceBinding):
            raise TaskSourceBindingError(
                "TASK_SOURCE_AUDIENCE_INVALID", "source binding audience is invalid"
            )
        return _sha(canonical_json_bytes(audience.audience(self._service_instance_id)))

    def _binding_ref(
        self, *, audience_digest: str, task_id: str, registration_id: str
    ) -> str:
        raw = hmac.new(
            self._key,
            b"study.task-source-binding.ref.v1\x00"
            + audience_digest.encode("ascii")
            + b"\x00"
            + task_id.encode("utf-8")
            + b"\x00"
            + registration_id.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return "srcb1_" + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    def _record_path(self, binding_ref: str) -> Path:
        digest = _sha(binding_ref.encode("ascii"))
        parent = self._records / digest[:2]
        parent.mkdir(exist_ok=True)
        return parent / f"{digest}.json"

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        with self._thread_lock:
            with self._lock_path.open("r+b") as lock_file:
                lock_file.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
                    try:
                        yield
                    finally:
                        lock_file.seek(0)
                        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                    try:
                        yield
                    finally:
                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _authenticate(self, value: Mapping[str, Any]) -> dict[str, Any]:
        unsigned = {**dict(value), "authKeyId": self._key_id}
        return {
            **unsigned,
            "authTag": self._mac("study.task-source-binding.record.v1", unsigned),
        }

    def _validate_record(self, record: Mapping[str, Any]) -> None:
        if (
            record.get("schema") != "study.task-source-binding.record"
            or record.get("schemaVersion") != 1
            or record.get("serviceInstanceId") != self._service_instance_id
            or record.get("authKeyId") != self._key_id
        ):
            raise TaskSourceBindingError(
                "TASK_SOURCE_BINDING_INVALID", "source binding record is invalid"
            )
        _require_binding_ref(record.get("bindingRef"))
        auth_tag = record.get("authTag")
        if not isinstance(auth_tag, str) or not _SHA256_RE.fullmatch(auth_tag):
            raise TaskSourceBindingError(
                "TASK_SOURCE_BINDING_AUTH_FAILED",
                "source binding authentication failed",
            )
        unsigned = dict(record)
        unsigned.pop("authTag", None)
        if not hmac.compare_digest(
            auth_tag, self._mac("study.task-source-binding.record.v1", unsigned)
        ):
            raise TaskSourceBindingError(
                "TASK_SOURCE_BINDING_AUTH_FAILED",
                "source binding authentication failed",
            )
        if not isinstance(record.get("staged"), Mapping):
            raise TaskSourceBindingError(
                "TASK_SOURCE_BINDING_INVALID", "staged source receipt is invalid"
            )

    def _load(self, binding_ref: str) -> dict[str, Any]:
        path = self._record_path(_require_binding_ref(binding_ref))
        try:
            raw = path.read_bytes()
        except FileNotFoundError as error:
            raise TaskSourceBindingError(
                "TASK_SOURCE_BINDING_NOT_FOUND", "source binding was not found"
            ) from error
        if len(raw) > 256 * 1024:
            raise TaskSourceBindingError(
                "TASK_SOURCE_BINDING_INVALID", "source binding record is too large"
            )
        try:
            record = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise TaskSourceBindingError(
                "TASK_SOURCE_BINDING_INVALID", "source binding record is invalid"
            ) from error
        if not isinstance(record, dict) or canonical_json_bytes(record) != raw:
            raise TaskSourceBindingError(
                "TASK_SOURCE_BINDING_INVALID", "source binding record is not canonical"
            )
        self._validate_record(record)
        return record

    def _publish(self, record: Mapping[str, Any]) -> None:
        path = self._record_path(str(record["bindingRef"]))
        raw = canonical_json_bytes(dict(record))
        descriptor: int | None = None
        try:
            descriptor = os.open(
                path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOINHERIT", 0),
                0o600,
            )
            offset = 0
            while offset < len(raw):
                written = os.write(descriptor, raw[offset:])
                if written <= 0:
                    raise OSError("source binding write stalled")
                offset += written
            os.fsync(descriptor)
        except FileExistsError as error:
            raise TaskSourceBindingError(
                "TASK_SOURCE_BINDING_CONFLICT",
                "source binding was published concurrently",
            ) from error
        finally:
            if descriptor is not None:
                os.close(descriptor)

    @staticmethod
    def _parse_input_ref(
        input_ref: Mapping[str, Any]
    ) -> tuple[str, str, str, str, dict[str, Any], str]:
        if not isinstance(input_ref, Mapping):
            raise TaskSourceBindingError(
                "TASK_SOURCE_INPUT_REF_INVALID", "input reference must be an object"
            )
        kind = input_ref.get("kind")
        fields = (
            _FILE_FIELDS
            if kind == "file"
            else _DIRECTORY_FIELDS if kind == "directory" else None
        )
        if (
            fields is None
            or set(input_ref) != fields
            or input_ref.get("schemaVersion") != 1
        ):
            raise TaskSourceBindingError(
                "TASK_SOURCE_INPUT_REF_INVALID", "input reference fields are invalid"
            )
        ref_field = "fileResourceRef" if kind == "file" else "directoryResourceRef"
        resource_ref = input_ref.get(ref_field)
        display_name = input_ref.get("displayName")
        revision = input_ref.get("resourceRevisionDigest")
        constraints = input_ref.get("constraints")
        expires_at = input_ref.get("expiresAt")
        if (
            not isinstance(resource_ref, str)
            or not _RESOURCE_REF_RE.fullmatch(resource_ref)
            or not isinstance(display_name, str)
            or not 1 <= len(display_name) <= 160
            or any(ord(character) < 0x20 for character in display_name)
            or not isinstance(revision, str)
            or not _SHA256_RE.fullmatch(revision)
            or not isinstance(constraints, dict)
            or not isinstance(expires_at, str)
            or not expires_at
        ):
            raise TaskSourceBindingError(
                "TASK_SOURCE_INPUT_REF_INVALID", "input reference values are invalid"
            )
        return (
            kind,
            resource_ref,
            display_name,
            revision,
            _clone(constraints),
            expires_at,
        )

    @staticmethod
    def _staged_value(staged: StagedResource) -> dict[str, Any]:
        return {
            "stagingRef": staged.staging_ref,
            "taskId": staged.task_id,
            "kind": staged.kind,
            "workspaceRelativePath": staged.workspace_relative_path,
            "sourceRevisionDigest": staged.source_revision_digest,
            "manifestDigest": staged.manifest_digest,
            "totalBytes": staged.total_bytes,
            "entryCount": staged.entry_count,
            "hardeningApplied": staged.hardening_applied,
            "resolutionProof": staged.resolution_proof,
        }

    @staticmethod
    def _staged_resource(value: Mapping[str, Any]) -> StagedResource:
        expected = {
            "stagingRef",
            "taskId",
            "kind",
            "workspaceRelativePath",
            "sourceRevisionDigest",
            "manifestDigest",
            "totalBytes",
            "entryCount",
            "hardeningApplied",
            "resolutionProof",
        }
        if set(value) != expected:
            raise TaskSourceBindingError(
                "TASK_SOURCE_BINDING_INVALID", "staged source receipt is invalid"
            )
        try:
            return StagedResource(
                staging_ref=str(value["stagingRef"]),
                task_id=str(value["taskId"]),
                kind=str(value["kind"]),
                workspace_relative_path=str(value["workspaceRelativePath"]),
                source_revision_digest=str(value["sourceRevisionDigest"]),
                manifest_digest=str(value["manifestDigest"]),
                total_bytes=int(value["totalBytes"]),
                entry_count=int(value["entryCount"]),
                hardening_applied=value["hardeningApplied"] is True,
                resolution_proof=str(value["resolutionProof"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise TaskSourceBindingError(
                "TASK_SOURCE_BINDING_INVALID", "staged source receipt is invalid"
            ) from error

    @staticmethod
    def _public(record: Mapping[str, Any]) -> dict[str, Any]:
        staged = record["staged"]
        return {
            "schema": "study.task-source-binding.summary",
            "schemaVersion": 1,
            "sourceBindingRef": record["bindingRef"],
            "taskId": record["taskId"],
            "state": "staged",
            "inputKind": record["kind"],
            "displayName": record["displayName"],
            "sourceRevisionDigest": record["sourceRevisionDigest"],
            "contentSnapshot": {
                "manifestDigest": staged["manifestDigest"],
                "totalBytes": staged["totalBytes"],
                "entryCount": staged["entryCount"],
            },
            "createdAt": record["createdAt"],
        }

    def bind_local_input(
        self,
        *,
        audience: ArtifactAudienceBinding,
        task_id: str,
        task_input_fingerprint: str,
        task_workspace: Path,
        task_sandbox_id: str | None,
        input_ref: Mapping[str, Any],
        registration_id: str,
    ) -> dict[str, Any]:
        task_id = _require_id(task_id, "taskId")
        registration_id = _require_id(registration_id, "registrationId")
        input_fingerprint = _require_digest(
            task_input_fingerprint, "taskInputFingerprint"
        )
        kind, resource_ref, display_name, revision, constraints, expires_at = (
            self._parse_input_ref(input_ref)
        )
        audience_digest = self._audience_digest(audience)
        binding_ref = self._binding_ref(
            audience_digest=audience_digest,
            task_id=task_id,
            registration_id=registration_id,
        )
        request_digest = _sha(
            canonical_json_bytes(
                {
                    "schema": "study.task-source-binding.request",
                    "schemaVersion": 1,
                    "taskId": task_id,
                    "inputFingerprint": input_fingerprint,
                    "audienceDigest": audience_digest,
                    "registrationId": registration_id,
                    "inputRef": dict(input_ref),
                }
            )
        )
        with self._transaction():
            try:
                existing = self._load(binding_ref)
            except TaskSourceBindingError as error:
                if error.code != "TASK_SOURCE_BINDING_NOT_FOUND":
                    raise
            else:
                if existing.get("requestDigest") != request_digest:
                    raise TaskSourceBindingError(
                        "TASK_SOURCE_IDEMPOTENCY_CONFLICT",
                        "registrationId was reused for a different source binding",
                    )
                try:
                    self._tasks.authorize_local_source_binding(
                        task_id,
                        audience,
                        expected_input_fingerprint=input_fingerprint,
                        source_revision_digest=revision,
                        require_prestart=False,
                    )
                except StudyTaskError as error:
                    raise TaskSourceBindingError(error.code, error.message) from error
                return self._public(existing)
        try:
            self._tasks.authorize_local_source_binding(
                task_id,
                audience,
                expected_input_fingerprint=input_fingerprint,
                source_revision_digest=revision,
                require_prestart=True,
            )
        except StudyTaskError as error:
            raise TaskSourceBindingError(error.code, error.message) from error
        try:
            summary = self._resources.local_registry.inspect(resource_ref, audience)
        except Exception as error:
            code = getattr(error, "code", "TASK_SOURCE_GRANT_INVALID")
            message = getattr(error, "message", "source grant is unavailable")
            raise TaskSourceBindingError(code, message) from error
        expected = {
            "kind": kind,
            "displayName": display_name,
            "resourceRevisionDigest": revision,
            "constraints": constraints,
            "expiresAt": expires_at,
        }
        if any(summary.get(field) != value for field, value in expected.items()):
            raise TaskSourceBindingError(
                "TASK_SOURCE_INPUT_REF_MISMATCH",
                "input reference does not match the service-owned grant",
            )
        if summary.get("state") != "active" or summary.get("remainingUses", 0) < 1:
            raise TaskSourceBindingError(
                "TASK_SOURCE_GRANT_UNAVAILABLE",
                "source grant is no longer available for a new task binding",
            )
        use_id = "source-bind-" + _sha(binding_ref.encode("ascii"))[:40]
        stage_id = "source-stage-" + _sha(binding_ref.encode("ascii"))[:40]
        try:
            resolved = self._resources.consume_local_grant(
                resource_ref=resource_ref,
                audience=audience,
                use_id=use_id,
                action="read",
                expected_resource_revision_digest=revision,
                expected_revocation_epoch=int(summary["revocationEpoch"]),
                requested_constraints=constraints,
            )
            staged = self._resources.stage_local_resource(
                resolved,
                audience=audience,
                task_id=task_id,
                task_workspace=Path(task_workspace),
                staging_request_id=stage_id,
                task_sandbox_id=task_sandbox_id,
            )
        except (ServiceResourceRuntimeError, ResourceStagingError) as error:
            raise TaskSourceBindingError(error.code, error.message) from error
        record = self._authenticate(
            {
                "schema": "study.task-source-binding.record",
                "schemaVersion": 1,
                "bindingRef": binding_ref,
                "serviceInstanceId": self._service_instance_id,
                "taskId": task_id,
                "inputFingerprint": input_fingerprint,
                "audienceDigest": audience_digest,
                "requestDigest": request_digest,
                "registrationDigest": self._mac(
                    "study.task-source-binding.registration.v1",
                    registration_id.encode("utf-8"),
                ),
                "resourceRef": resource_ref,
                "sourceRevisionDigest": revision,
                "revocationEpoch": int(summary["revocationEpoch"]),
                "constraints": constraints,
                "kind": kind,
                "displayName": display_name,
                "expiresAt": expires_at,
                "useId": use_id,
                "staged": self._staged_value(staged),
                "createdAt": _now(),
            }
        )
        self._validate_record(record)
        with self._transaction():
            try:
                existing = self._load(binding_ref)
            except TaskSourceBindingError as error:
                if error.code != "TASK_SOURCE_BINDING_NOT_FOUND":
                    raise
                self._publish(record)
                existing = record
            if existing.get("requestDigest") != request_digest:
                raise TaskSourceBindingError(
                    "TASK_SOURCE_IDEMPOTENCY_CONFLICT",
                    "registrationId was reused for a different source binding",
                )
            return self._public(existing)

    def worker_input(
        self,
        binding_ref: str,
        *,
        audience: ArtifactAudienceBinding,
        task_id: str,
        task_input_fingerprint: str,
        task_workspace: Path,
    ) -> dict[str, Any]:
        binding_ref = _require_binding_ref(binding_ref)
        task_id = _require_id(task_id, "taskId")
        input_fingerprint = _require_digest(
            task_input_fingerprint, "taskInputFingerprint"
        )
        with self._transaction():
            record = self._load(binding_ref)
        if (
            record.get("taskId") != task_id
            or record.get("inputFingerprint") != input_fingerprint
            or record.get("audienceDigest") != self._audience_digest(audience)
        ):
            raise TaskSourceBindingError(
                "TASK_SOURCE_BINDING_SCOPE_MISMATCH",
                "source binding does not belong to this task and audience",
            )
        try:
            self._tasks.authorize_local_source_binding(
                task_id,
                audience,
                expected_input_fingerprint=input_fingerprint,
                source_revision_digest=str(record["sourceRevisionDigest"]),
                require_prestart=False,
            )
            resolved = self._resources.consume_local_grant(
                resource_ref=str(record["resourceRef"]),
                audience=audience,
                use_id=str(record["useId"]),
                action="read",
                expected_resource_revision_digest=str(record["sourceRevisionDigest"]),
                expected_revocation_epoch=int(record["revocationEpoch"]),
                requested_constraints=record["constraints"],
            )
            staged = self._staged_resource(record["staged"])
            self._resources.stager.resolve_worker_path(
                staged,
                resource=resolved,
                registry=self._resources.local_registry,
                audience=audience,
                task_workspace=Path(task_workspace),
            )
        except (
            StudyTaskError,
            ServiceResourceRuntimeError,
            ResourceStagingError,
        ) as error:
            raise TaskSourceBindingError(error.code, error.message) from error
        locator = staged.worker_locator()
        relative = PurePosixPath(str(locator["workspaceRelativePath"]))
        if relative.is_absolute() or ".." in relative.parts:
            raise TaskSourceBindingError(
                "TASK_SOURCE_WORKER_LOCATOR_INVALID",
                "worker source locator escaped the task workspace",
            )
        return {
            "schema": "study.source-adapter.worker-input",
            "schemaVersion": 1,
            "adapterId": (
                "source.local-file" if record["kind"] == "file" else "source.directory"
            ),
            "inputKind": record["kind"],
            "sourceRevisionDigest": record["sourceRevisionDigest"],
            "locator": locator,
        }
