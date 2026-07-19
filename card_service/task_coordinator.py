from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import os
import secrets
import stat
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from .artifact_registry import (
    ArtifactAudienceBinding,
    ArtifactRegistry,
    ArtifactRegistryError,
    canonical_json_bytes,
    validate_persistable_json,
)
from .task_manifests import (
    TaskManifestError,
    WORKFLOW_ACTIONS,
    build_authorization_binding,
    build_capability_binding,
    build_successor_rebase,
    build_task_input_manifest,
    build_work_reuse_manifest,
    manifest_digest,
)


MAX_RECORD_BYTES = 16 * 1024 * 1024
MAX_OPERATIONS = 512
MAX_RECOVERY_SCAN_RECORDS = 2048
ID_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-")
TASK_STATES = frozenset({"queued", "running", "cancelling", "succeeded", "failed", "cancelled", "interrupted"})
ACTIVE_TASK_STATES = frozenset({"queued", "running", "cancelling"})
TERMINAL_TASK_STATES = TASK_STATES - ACTIVE_TASK_STATES
TASK_STAGES = frozenset(
    {
        "request", "authorization", "capability", "source_registration", "source_inspection",
        "discovery", "selection", "planning", "card_validation", "generation", "export",
        "anki_prepare", "anki_import", "anki_data_verification", "anki_runtime_verification",
        "recovery", "cancellation", "internal",
    }
)
TOOL_ERROR_CODES = frozenset(
    {
        "SCHEMA_INVALID", "UNSUPPORTED_COMBINATION", "UNSUPPORTED_CARD_PLAN", "GRANT_REQUIRED",
        "GRANT_EXPIRED", "AUTHORIZATION_REQUIRED", "CONFIRMATION_REQUIRED", "SOURCE_CHANGED",
        "SOURCE_PARTIAL", "SOURCE_UNREADABLE", "PRIVATE_NETWORK_BLOCKED", "PATH_ESCAPE",
        "PROMPT_INJECTION_SUSPECTED", "MODEL_STALE", "TTS_UNAVAILABLE", "FFMPEG_MISSING",
        "MEDIA_SANDBOX_BLOCKED", "ANKI_OFFLINE", "NO_SCOREABLE_OBJECTIVE", "UNRESOLVED_CONFLICT",
        "REVIEW_BUDGET_EXCEEDED", "TASK_NOT_FOUND", "TASK_NOT_CANCELLABLE", "INPUT_REVISION_MISMATCH",
        "MODEL_OUTPUT_INVALID", "MEDIA_SEMANTIC_MISMATCH", "RELIABILITY_BLOCKED", "OUTPUT_NOT_WRITABLE",
        "PACKAGE_VERIFY_FAILED", "IMPORT_CONFLICT", "MEDIA_HASH_CONFLICT", "ANKI_VERIFY_FAILED",
        "WORKER_EXITED", "ARTIFACT_CORRUPT", "INTERNAL_UNCLASSIFIED",
    }
)


class StudyTaskError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _require_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 256 or any(character not in ID_CHARS for character in value):
        raise StudyTaskError("TASK_SCHEMA_INVALID", f"{label} is invalid")
    return value


def _require_digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise StudyTaskError("TASK_SCHEMA_INVALID", f"{label} must be a lowercase SHA-256 digest")
    return value


def _ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise StudyTaskError("TASK_STORAGE_UNSAFE", "Task storage contains a link or reparse directory")
    return path


def _temporary_file(path: Path, data: bytes) -> Path:
    temporary = path.parent / f".{path.name}.{secrets.token_hex(12)}.partial"
    with temporary.open("xb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())
    return temporary


class StudyTaskCoordinator:
    def __init__(
        self,
        root: Path,
        *,
        authentication_key: bytes,
        service_instance_id: str,
        artifact_registry: ArtifactRegistry,
        key_id: str = "study-task-store-v1",
    ) -> None:
        if not isinstance(authentication_key, bytes) or len(authentication_key) < 32:
            raise StudyTaskError("TASK_AUTH_KEY_INVALID", "Task authentication key must contain at least 256 bits")
        self._service_instance_id = _require_id(service_instance_id, "service_instance_id")
        self._key_id = _require_id(key_id, "key_id")
        self._authentication_key = bytes(authentication_key)
        self._artifacts = artifact_registry
        self._root = _ensure_directory(Path(root).absolute())
        self._tasks_root = _ensure_directory(self._root / "tasks")
        self._checkpoints_root = _ensure_directory(self._root / "checkpoints")
        self._lineage_locks_root = _ensure_directory(self._root / "lineage-locks")
        self._lock_path = self._root / "coordinator.lock"
        try:
            with self._lock_path.open("xb") as lock_file:
                lock_file.write(b"\x00")
                lock_file.flush()
                os.fsync(lock_file.fileno())
        except FileExistsError:
            pass
        self._thread_lock = threading.RLock()
        self._lineage_thread_guard = threading.Lock()
        self._lineage_thread_locks: dict[str, threading.RLock] = {}

    def _ensure_parent(self, path: Path) -> None:
        absolute = path.absolute()
        try:
            relative = absolute.relative_to(self._root)
        except ValueError as error:
            raise StudyTaskError("TASK_STORAGE_UNSAFE", "Task storage path escapes its root") from error
        current = _ensure_directory(self._root)
        for part in relative.parts:
            current = _ensure_directory(current / part)

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        with self._thread_lock:
            self._ensure_parent(self._lock_path.parent)
            lock_info = self._lock_path.lstat()
            lock_attributes = getattr(lock_info, "st_file_attributes", 0)
            if not stat.S_ISREG(lock_info.st_mode) or stat.S_ISLNK(lock_info.st_mode) or lock_attributes & 0x400 or lock_info.st_nlink != 1:
                raise StudyTaskError("TASK_STORAGE_UNSAFE", "Coordinator lock is not a private regular file")
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

    @contextmanager
    def _successor_lineage_transaction(
        self, lineage_task_id: str
    ) -> Iterator[None]:
        lineage = _require_id(lineage_task_id, "lineageTaskId")
        identity = _sha(lineage.encode("utf-8"))
        lock_path = self._lineage_locks_root / f"{identity}.lock"
        self._ensure_parent(lock_path.parent)
        try:
            with lock_path.open("xb") as lock_file:
                lock_file.write(b"\x00")
                lock_file.flush()
                os.fsync(lock_file.fileno())
        except FileExistsError:
            pass
        with self._lineage_thread_guard:
            thread_lock = self._lineage_thread_locks.setdefault(
                identity, threading.RLock()
            )
        with thread_lock:
            info = lock_path.lstat()
            attributes = getattr(info, "st_file_attributes", 0)
            if (
                not stat.S_ISREG(info.st_mode)
                or stat.S_ISLNK(info.st_mode)
                or attributes & 0x400
                or info.st_nlink != 1
            ):
                raise StudyTaskError(
                    "TASK_STORAGE_UNSAFE",
                    "Successor lineage lock is not a private regular file",
                )
            with lock_path.open("r+b") as lock_file:
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

    def _mac(self, domain: str, value: Mapping[str, Any]) -> str:
        message = domain.encode("ascii") + b"\x00" + canonical_json_bytes(dict(value))
        return hmac.new(self._authentication_key, message, hashlib.sha256).hexdigest()

    def _authenticate(self, domain: str, value: Mapping[str, Any]) -> dict[str, Any]:
        unsigned = {**dict(value), "authKeyId": self._key_id}
        return {**unsigned, "authTag": self._mac(domain, unsigned)}

    def _verify_authenticated(self, domain: str, value: Mapping[str, Any]) -> None:
        if value.get("authKeyId") != self._key_id:
            raise StudyTaskError("TASK_AUTH_INVALID", "Task record authentication key is unavailable")
        tag = value.get("authTag")
        unsigned = dict(value)
        unsigned.pop("authTag", None)
        if not isinstance(tag, str) or not hmac.compare_digest(tag, self._mac(domain, unsigned)):
            raise StudyTaskError("TASK_AUTH_INVALID", "Task record authentication failed")

    def _task_path(self, task_id: str) -> Path:
        identity = _sha(task_id.encode("utf-8"))
        return self._tasks_root / identity[:2] / f"{identity}.json"

    def _checkpoint_path(self, scope_id: str) -> Path:
        identity = _sha(scope_id.encode("utf-8"))
        return self._checkpoints_root / identity[:2] / f"{identity}.json"

    def _safe_read(self, path: Path) -> bytes:
        self._ensure_parent(path.parent)
        try:
            info = path.lstat()
        except FileNotFoundError as error:
            raise StudyTaskError("TASK_NOT_FOUND", "Task record was not found") from error
        attributes = getattr(info, "st_file_attributes", 0)
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or attributes & 0x400 or info.st_nlink != 1:
            raise StudyTaskError("TASK_STORAGE_UNSAFE", "Task record is not a private regular file")
        if info.st_size > MAX_RECORD_BYTES:
            raise StudyTaskError("TASK_RECORD_TOO_LARGE", "Task record exceeds its size limit")
        data = path.read_bytes()
        after = path.lstat()
        before_identity = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
        after_identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        if len(data) != info.st_size or before_identity != after_identity:
            raise StudyTaskError("TASK_RECORD_CHANGED", "Task record changed while being read")
        return data

    def _decode(self, raw: bytes, *, domain: str, schema: str) -> dict[str, Any]:
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise StudyTaskError("TASK_RECORD_INVALID", "Task record is not valid JSON") from error
        if not isinstance(value, dict) or canonical_json_bytes(value) != raw:
            raise StudyTaskError("TASK_RECORD_INVALID", "Task record is not canonical JSON")
        if value.get("schema") != schema or value.get("schemaVersion") != 1:
            raise StudyTaskError("TASK_RECORD_INVALID", "Task record schema is invalid")
        self._verify_authenticated(domain, value)
        return value

    def _load_with_backup(self, path: Path, *, domain: str, schema: str) -> tuple[dict[str, Any], bytes, bool]:
        errors: list[StudyTaskError] = []
        candidates = ((path, False), (path.with_suffix(path.suffix + ".bak"), True))
        for candidate, recovered in candidates:
            try:
                raw = self._safe_read(candidate)
                return self._decode(raw, domain=domain, schema=schema), raw, recovered
            except StudyTaskError as error:
                errors.append(error)
        if errors and all(error.code == "TASK_NOT_FOUND" for error in errors):
            raise errors[0]
        raise StudyTaskError("TASK_RECORD_CORRUPT", "Task record and its backup are unavailable or invalid")

    def _publish_new(self, path: Path, raw: bytes) -> None:
        self._ensure_parent(path.parent)
        temporary = _temporary_file(path, raw)
        try:
            try:
                os.link(temporary, path)
            except FileExistsError as error:
                raise StudyTaskError("TASK_ALREADY_EXISTS", "Task record already exists") from error
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def _replace_with_backup(self, path: Path, raw: bytes, previous_raw: bytes) -> None:
        self._ensure_parent(path.parent)
        backup = path.with_suffix(path.suffix + ".bak")
        backup_temp = _temporary_file(backup, previous_raw)
        current_temp = _temporary_file(path, raw)
        try:
            os.replace(backup_temp, backup)
            os.replace(current_temp, path)
        finally:
            for temporary in (backup_temp, current_temp):
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass

    @staticmethod
    def _scope_id(task_input_manifest: Mapping[str, Any]) -> str:
        subject = task_input_manifest.get("subject")
        if not isinstance(subject, Mapping):
            raise StudyTaskError("TASK_SCHEMA_INVALID", "Task input subject is invalid")
        if subject.get("kind") == "project_task":
            return _require_id(subject.get("projectId"), "projectId")
        if subject.get("kind") == "profile_validation":
            profile_ref = _require_id(subject.get("profileRef"), "profileRef")
            return "profile-" + _sha(profile_ref.encode("utf-8"))
        raise StudyTaskError("TASK_SCHEMA_INVALID", "Task input subject kind is invalid")

    def _verify_result_ref(
        self, ref: Mapping[str, Any], audience: ArtifactAudienceBinding, scope_id: str
    ) -> dict[str, Any]:
        try:
            envelope = self._artifacts.verify_ref(ref, audience)
        except ArtifactRegistryError as error:
            raise StudyTaskError(
                "TASK_RESULT_INVALID", "Task result failed authenticated artifact verification"
            ) from error
        if envelope["projectId"] != scope_id:
            raise StudyTaskError("TASK_RESULT_SCOPE_MISMATCH", "Task result belongs to another project scope")
        return envelope

    def _validate_bundle(
        self,
        *,
        audience: ArtifactAudienceBinding,
        work_reuse_manifest: Mapping[str, Any],
        task_input_manifest: Mapping[str, Any],
        capability_binding: Mapping[str, Any],
        authorization_binding: Mapping[str, Any],
    ) -> tuple[str, str, str]:
        expected_audience = {
            "osUserSidDigest": audience.owner_digest,
            "hostInstanceId": audience.host_id,
            "pluginInstanceId": audience.plugin_id,
            "serviceInstanceId": self._service_instance_id,
            "sessionId": audience.session_id,
        }
        # Report a crossed trust boundary before canonical reconstruction. The
        # authorization builder binds entries to the current audience, so
        # rebuilding first would turn this precise failure into the less useful
        # TASK_MANIFEST_INVALID error.
        if authorization_binding.get("audience") != expected_audience:
            raise StudyTaskError("TASK_AUDIENCE_MISMATCH", "Task authorization is not bound to the current trusted audience")
        try:
            rebuilt_work, _ = build_work_reuse_manifest(
                action_id=work_reuse_manifest.get("actionId"),
                subject=work_reuse_manifest.get("subject"),
                component_versions=work_reuse_manifest.get("componentVersions"),
                service_configurations=work_reuse_manifest.get("serviceConfigurations"),
                generation_policy_digest=work_reuse_manifest.get("generationPolicyDigest"),
                work_partition_policy_digest=work_reuse_manifest.get("workPartitionPolicyDigest"),
            )
            rebuilt_capability, _ = build_capability_binding(capability_binding.get("required"))
            rebuilt_authorization, _ = build_authorization_binding(
                audience=audience,
                service_instance_id=self._service_instance_id,
                bindings=authorization_binding.get("bindings"),
            )
            rebuilt_input, _ = build_task_input_manifest(
                action_id=task_input_manifest.get("actionId"),
                work_reuse_manifest=rebuilt_work,
                work_reuse_digest=task_input_manifest.get("workReuseDigest"),
                subject=task_input_manifest.get("subject"),
                authorization_binding_digest=task_input_manifest.get("authorizationBindingDigest"),
                capability_binding_digest=task_input_manifest.get("capabilityBindingDigest"),
                component_versions=task_input_manifest.get("componentVersions"),
                service_bindings=task_input_manifest.get("serviceBindings"),
                operation_intent_digest=task_input_manifest.get("operationIntentDigest"),
                generation_policy_digest=task_input_manifest.get("generationPolicyDigest"),
                cost_budget_digest=task_input_manifest.get("costBudgetDigest"),
                batch_policy_digest=task_input_manifest.get("batchPolicyDigest"),
                successor_rebase_digest=task_input_manifest.get("successorRebaseDigest"),
            )
            if rebuilt_work != dict(work_reuse_manifest):
                raise TaskManifestError("TASK_MANIFEST_INVALID", "Work reuse manifest is not canonical")
            if rebuilt_capability != dict(capability_binding):
                raise TaskManifestError("TASK_MANIFEST_INVALID", "Capability binding is not canonical")
            if rebuilt_authorization != dict(authorization_binding):
                raise TaskManifestError("TASK_MANIFEST_INVALID", "Authorization binding is not canonical")
            if rebuilt_input != dict(task_input_manifest):
                raise TaskManifestError("TASK_MANIFEST_INVALID", "Task input manifest is not canonical")
            work_digest = manifest_digest(work_reuse_manifest)
            input_digest = manifest_digest(task_input_manifest)
            capability_digest = manifest_digest(capability_binding)
            authorization_digest = manifest_digest(authorization_binding)
        except TaskManifestError as error:
            raise StudyTaskError(error.code, error.message) from error
        schemas = (
            (work_reuse_manifest, "study.work-reuse.manifest", "Work reuse"),
            (task_input_manifest, "study.task.input-manifest", "Task input"),
            (capability_binding, "study.capability.binding", "Capability binding"),
            (authorization_binding, "study.authorization.binding", "Authorization binding"),
        )
        for value, schema, label in schemas:
            if value.get("schema") != schema or value.get("schemaVersion") != 1:
                raise StudyTaskError("TASK_SCHEMA_INVALID", f"{label} schema is invalid")
        if task_input_manifest.get("workReuseDigest") != work_digest:
            raise StudyTaskError("TASK_INPUT_MISMATCH", "Task input does not bind its work reuse manifest")
        if task_input_manifest.get("capabilityBindingDigest") != capability_digest:
            raise StudyTaskError("TASK_INPUT_MISMATCH", "Task input does not bind its capability manifest")
        if task_input_manifest.get("authorizationBindingDigest") != authorization_digest:
            raise StudyTaskError("TASK_INPUT_MISMATCH", "Task input does not bind its authorization manifest")
        if task_input_manifest.get("actionId") != work_reuse_manifest.get("actionId"):
            raise StudyTaskError("TASK_INPUT_MISMATCH", "Task action and work identity differ")
        capability_services = {
            (item["capability"], item["profileRef"], item["configurationFingerprint"], item["credentialRevision"])
            for item in capability_binding.get("required", [])
            if item.get("kind") == "service_profile"
        }
        task_services = {
            (item["capability"], item["profileRef"], item["configurationFingerprint"], item["credentialRevision"])
            for item in task_input_manifest.get("serviceBindings", [])
        }
        if capability_services != task_services:
            raise StudyTaskError("TASK_INPUT_MISMATCH", "Task service bindings and required service capabilities differ")
        return work_digest, input_digest, self._scope_id(task_input_manifest)

    @staticmethod
    def _unit_reuse_digest(work_reuse_digest: str, work_unit_id: str, phase: str) -> str:
        value = {
            "schema": "study.work-unit-reuse", "schemaVersion": 1,
            "taskWorkReuseDigest": work_reuse_digest, "workUnitId": work_unit_id, "phase": phase,
        }
        return _sha(canonical_json_bytes(value))

    def create_task(
        self,
        *,
        audience: ArtifactAudienceBinding,
        work_reuse_manifest: Mapping[str, Any],
        task_input_manifest: Mapping[str, Any],
        capability_binding: Mapping[str, Any],
        authorization_binding: Mapping[str, Any],
        work_units: Sequence[Mapping[str, Any]],
        cancellable: bool = True,
        resumability: str = "resume_remaining",
        predecessor_task_id: str | None = None,
        _task_id: str | None = None,
        _initial_completed_units: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
        _successor_rebase: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if resumability not in {"none", "restart_phase", "resume_remaining"}:
            raise StudyTaskError("TASK_SCHEMA_INVALID", "Task resumability is invalid")
        work_digest, input_digest, scope_id = self._validate_bundle(
            audience=audience, work_reuse_manifest=work_reuse_manifest,
            task_input_manifest=task_input_manifest, capability_binding=capability_binding,
            authorization_binding=authorization_binding,
        )
        if not isinstance(work_units, Sequence) or isinstance(work_units, (str, bytes)):
            raise StudyTaskError("TASK_SCHEMA_INVALID", "Work units must be a list")
        task_id = _require_id(_task_id, "taskId") if _task_id is not None else "task_" + secrets.token_urlsafe(24)
        initial_completed = dict(_initial_completed_units or {})
        normalized_units: list[dict[str, Any]] = []
        for item in work_units:
            if not isinstance(item, Mapping) or set(item) != {"workUnitId", "phase"}:
                raise StudyTaskError("TASK_SCHEMA_INVALID", "Work unit fields are invalid")
            work_unit_id = _require_id(item["workUnitId"], "workUnitId")
            phase = item["phase"]
            if phase not in TASK_STAGES:
                raise StudyTaskError("TASK_SCHEMA_INVALID", "Work unit phase is invalid")
            result_refs = [dict(ref) for ref in initial_completed.pop(work_unit_id, [])]
            for ref in result_refs:
                self._verify_result_ref(ref, audience, scope_id)
            normalized_units.append({
                "workUnitId": work_unit_id, "phase": phase,
                "workReuseDigest": self._unit_reuse_digest(work_digest, work_unit_id, phase),
                "state": "completed" if result_refs else "pending", "attempt": 0, "resultRefs": result_refs,
            })
        if initial_completed:
            raise StudyTaskError("TASK_WORK_UNIT_NOT_FOUND", "Initial completed results name an unknown work unit")
        if len(normalized_units) != len({item["workUnitId"] for item in normalized_units}):
            raise StudyTaskError("TASK_SCHEMA_INVALID", "Work unit IDs must be unique")
        created_at = _now()
        snapshot: dict[str, Any] = {
            "schema": "study.task.snapshot", "schemaVersion": 1, "taskRevision": 1,
            "taskId": task_id, "intent": task_input_manifest["actionId"], "state": "queued",
            "inputFingerprint": input_digest, "workReuseDigest": work_digest,
            "progress": {"phase": "request", "phasePercent": None, "overallPercent": None, "lastProgressAt": created_at},
            "cancellable": bool(cancellable), "resumability": resumability,
            "workUnits": normalized_units, "resultRefs": [], "issueRefs": [],
            "createdAt": created_at, "updatedAt": created_at,
        }
        if predecessor_task_id is not None:
            snapshot["predecessorTaskId"] = _require_id(predecessor_task_id, "predecessorTaskId")
        scope_digest = _sha(canonical_json_bytes(audience.project_scope(scope_id)))
        unsigned_record = {
            "schema": "study.task.record", "schemaVersion": 1, "scopeId": scope_id,
            "projectScopeDigest": scope_digest,
            "createdAudienceDigest": _sha(canonical_json_bytes(audience.audience(self._service_instance_id))),
            "createdServiceInstanceId": self._service_instance_id, "task": snapshot,
            "workReuseManifest": dict(work_reuse_manifest), "taskInputManifest": dict(task_input_manifest),
            "capabilityBinding": dict(capability_binding), "authorizationBinding": dict(authorization_binding),
            "operations": [],
        }
        if _successor_rebase is not None:
            if manifest_digest(_successor_rebase) != task_input_manifest.get("successorRebaseDigest"):
                raise StudyTaskError("TASK_INPUT_MISMATCH", "Successor rebase is not bound by task input")
            if _successor_rebase.get("successorTaskId") != task_id:
                raise StudyTaskError("TASK_INPUT_MISMATCH", "Successor rebase names another task")
            unsigned_record["successorRebase"] = dict(_successor_rebase)
        record = self._authenticate("study.task.record.v1", unsigned_record)
        validate_persistable_json(record)
        raw = canonical_json_bytes(record)
        with self._transaction():
            self._publish_new(self._task_path(task_id), raw)
            self._write_checkpoint(record, raw)
        return self._public_snapshot(record, audience)

    def _load_task(self, task_id: str) -> tuple[dict[str, Any], bytes, bool]:
        _require_id(task_id, "taskId")
        record, raw, recovered = self._load_with_backup(
            self._task_path(task_id), domain="study.task.record.v1", schema="study.task.record"
        )
        if recovered:
            raise StudyTaskError(
                "TASK_RECORD_CORRUPT",
                "The current task record is unavailable; its backup is retained for diagnosis but cannot replace newer state",
            )
        return record, raw, False

    def _authorize_scope(self, record: Mapping[str, Any], audience: ArtifactAudienceBinding) -> None:
        scope_id = record.get("scopeId")
        if not isinstance(scope_id, str):
            raise StudyTaskError("TASK_RECORD_INVALID", "Task scope is invalid")
        expected = _sha(canonical_json_bytes(audience.project_scope(scope_id)))
        if record.get("projectScopeDigest") != expected:
            raise StudyTaskError("TASK_SCOPE_MISMATCH", "Task does not belong to the current owner/host/plugin scope")

    def _public_snapshot(self, record: Mapping[str, Any], audience: ArtifactAudienceBinding) -> dict[str, Any]:
        self._authorize_scope(record, audience)
        task = json.loads(json.dumps(record["task"], ensure_ascii=False))
        task["resultHandles"] = [self._artifacts.issue_handle(ref, audience) for ref in task.pop("resultRefs", [])]
        for unit in task["workUnits"]:
            unit["resultHandles"] = [self._artifacts.issue_handle(ref, audience) for ref in unit.pop("resultRefs", [])]
        failure = task.get("failure")
        if isinstance(failure, dict):
            refs = failure.pop("preservedArtifactRefs", [])
            failure["preservedArtifactHandles"] = [self._artifacts.issue_handle(ref, audience) for ref in refs]
        return task

    def get_task(self, task_id: str, audience: ArtifactAudienceBinding) -> dict[str, Any]:
        with self._transaction():
            record, _, _ = self._load_task(task_id)
            return self._public_snapshot(record, audience)

    def get_recovery_record(
        self, task_id: str, audience: ArtifactAudienceBinding
    ) -> dict[str, Any]:
        """Return an authenticated internal record for recovery planning only."""

        with self._transaction():
            record, _, _ = self._load_task(task_id)
            self._authorize_scope(record, audience)
            return json.loads(json.dumps(record, ensure_ascii=False))

    def authorize_local_source_binding(
        self,
        task_id: str,
        audience: ArtifactAudienceBinding,
        *,
        expected_input_fingerprint: str,
        source_revision_digest: str,
        require_prestart: bool,
    ) -> dict[str, Any]:
        """Authorize the private resource-to-task bridge without exposing manifests.

        A local grant is not task input merely because it is valid.  The exact
        source revision must already be committed by the task input manifest,
        the task must belong to the current session/service audience, and the
        authorization bundle must contain ``read_source``.  Only a minimal
        internal summary leaves this method.
        """

        expected_input = _require_digest(
            expected_input_fingerprint, "expectedInputFingerprint"
        )
        source_revision = _require_digest(
            source_revision_digest, "sourceRevisionDigest"
        )
        if not isinstance(require_prestart, bool):
            raise StudyTaskError(
                "TASK_SCHEMA_INVALID", "requirePrestart must be a boolean"
            )
        with self._transaction():
            record, _, _ = self._load_task(task_id)
            self._authorize_scope(record, audience)
            current_audience = _sha(
                canonical_json_bytes(audience.audience(self._service_instance_id))
            )
            if record.get("createdAudienceDigest") != current_audience:
                raise StudyTaskError(
                    "TASK_REAUTHORIZATION_REQUIRED",
                    "This task belongs to an earlier session or service instance",
                )
            task = record["task"]
            if task.get("inputFingerprint") != expected_input:
                raise StudyTaskError(
                    "TASK_INPUT_MISMATCH", "Task input fingerprint changed"
                )
            allowed_states = {"queued"} if require_prestart else {"queued", "running"}
            if task.get("state") not in allowed_states:
                raise StudyTaskError(
                    "TASK_STATE_CONFLICT",
                    "Local source bindings are unavailable in this task state",
                )
            subject = record.get("taskInputManifest", {}).get("subject", {})
            source_digests = subject.get("sourceSnapshotDigests", [])
            if source_revision not in source_digests:
                raise StudyTaskError(
                    "TASK_INPUT_MISMATCH",
                    "Local source revision is not bound by the task input manifest",
                )
            bindings = record.get("authorizationBinding", {}).get("bindings", [])
            if not any(
                isinstance(binding, Mapping) and binding.get("action") == "read_source"
                for binding in bindings
            ):
                raise StudyTaskError(
                    "TASK_AUTHORIZATION_MISSING",
                    "Task authorization does not permit source reads",
                )
            return {
                "taskId": task["taskId"],
                "taskRevision": task["taskRevision"],
                "state": task["state"],
                "inputFingerprint": task["inputFingerprint"],
                "scopeId": record["scopeId"],
            }

    def _write_checkpoint(self, record: Mapping[str, Any], task_raw: bytes) -> None:
        task = record["task"]
        checkpoint = self._authenticate("study.task.checkpoint.v1", {
            "schema": "study.task.checkpoint", "schemaVersion": 1,
            "scopeId": record["scopeId"], "projectScopeDigest": record["projectScopeDigest"],
            "taskId": task["taskId"], "taskRevision": task["taskRevision"],
            "taskRecordDigest": _sha(task_raw), "inputFingerprint": task["inputFingerprint"],
            "workReuseDigest": task["workReuseDigest"], "state": task["state"], "updatedAt": task["updatedAt"],
        })
        checkpoint_raw = canonical_json_bytes(checkpoint)
        path = self._checkpoint_path(record["scopeId"])
        if path.exists():
            try:
                _, old_raw, _ = self._load_with_backup(path, domain="study.task.checkpoint.v1", schema="study.task.checkpoint")
            except StudyTaskError:
                old_raw = checkpoint_raw
            self._replace_with_backup(path, checkpoint_raw, old_raw)
        else:
            self._publish_new(path, checkpoint_raw)

    @staticmethod
    def _public_checkpoint(checkpoint: Mapping[str, Any]) -> dict[str, Any]:
        public = dict(checkpoint)
        for internal_field in ("authKeyId", "authTag", "projectScopeDigest", "taskRecordDigest"):
            public.pop(internal_field, None)
        return public

    def load_checkpoint(self, scope_id: str, audience: ArtifactAudienceBinding) -> dict[str, Any]:
        _require_id(scope_id, "scopeId")
        with self._transaction():
            checkpoint, _, checkpoint_recovered = self._load_with_backup(
                self._checkpoint_path(scope_id), domain="study.task.checkpoint.v1", schema="study.task.checkpoint"
            )
            expected_scope = _sha(canonical_json_bytes(audience.project_scope(scope_id)))
            if checkpoint.get("projectScopeDigest") != expected_scope:
                raise StudyTaskError("TASK_SCOPE_MISMATCH", "Checkpoint does not belong to the current scope")
            record, task_raw, task_recovered = self._load_task(checkpoint["taskId"])
            self._authorize_scope(record, audience)
            task = record["task"]
            if checkpoint["inputFingerprint"] != task["inputFingerprint"] or checkpoint["workReuseDigest"] != task["workReuseDigest"]:
                raise StudyTaskError("TASK_CHECKPOINT_MISMATCH", "Checkpoint identity does not match its task")
            if checkpoint["taskRevision"] > task["taskRevision"]:
                raise StudyTaskError("TASK_CHECKPOINT_MISMATCH", "Checkpoint is ahead of the recoverable task record")
            exact = checkpoint["taskRevision"] == task["taskRevision"] and checkpoint["taskRecordDigest"] == _sha(task_raw)
            return {
                "checkpoint": self._public_checkpoint(checkpoint), "task": self._public_snapshot(record, audience),
                "recoveredFromBackup": checkpoint_recovered or task_recovered,
                "taskAdvancedBeyondCheckpoint": not exact and checkpoint["taskRevision"] < task["taskRevision"],
            }

    def _mutate(
        self,
        *,
        task_id: str,
        audience: ArtifactAudienceBinding,
        expected_revision: int,
        operation_id: str,
        operation_payload: Mapping[str, Any],
        mutation,
        require_created_audience: bool = True,
    ) -> dict[str, Any]:
        _require_id(operation_id, "operationId")
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision < 1:
            raise StudyTaskError("TASK_REVISION_INVALID", "expectedRevision must be positive")
        try:
            validate_persistable_json(dict(operation_payload))
        except Exception as error:
            raise StudyTaskError("TASK_OPERATION_INVALID", "Task operation contains non-persistable data") from error
        operation_digest = _sha(canonical_json_bytes({
            "schema": "study.task.operation", "schemaVersion": 1,
            "operationId": operation_id, "payload": dict(operation_payload),
        }))
        with self._transaction():
            record, previous_raw, _ = self._load_task(task_id)
            self._authorize_scope(record, audience)
            expected_audience = _sha(canonical_json_bytes(audience.audience(self._service_instance_id)))
            if require_created_audience and record.get("createdAudienceDigest") != expected_audience:
                raise StudyTaskError("TASK_REAUTHORIZATION_REQUIRED", "This task belongs to an earlier session or service instance")
            for operation in record.get("operations", []):
                if operation.get("operationId") == operation_id:
                    if operation.get("operationDigest") != operation_digest:
                        raise StudyTaskError("TASK_IDEMPOTENCY_CONFLICT", "operationId was already used with different input")
                    return self._public_snapshot(record, audience)
            task = record["task"]
            if task.get("taskRevision") != expected_revision:
                raise StudyTaskError("TASK_REVISION_CONFLICT", "Task revision changed before this operation")
            unsigned = json.loads(json.dumps(record, ensure_ascii=False))
            unsigned.pop("authKeyId", None)
            unsigned.pop("authTag", None)
            mutation(unsigned["task"])
            unsigned["task"]["taskRevision"] += 1
            unsigned["task"]["updatedAt"] = _now()
            operations = unsigned["operations"]
            if len(operations) >= MAX_OPERATIONS:
                raise StudyTaskError("TASK_OPERATION_LIMIT", "Task idempotency ledger is full")
            operations.append({
                "operationId": operation_id,
                "operationDigest": operation_digest,
                "resultingTaskRevision": unsigned["task"]["taskRevision"],
                "recordedAt": unsigned["task"]["updatedAt"],
            })
            updated = self._authenticate("study.task.record.v1", unsigned)
            validate_persistable_json(updated)
            raw = canonical_json_bytes(updated)
            self._replace_with_backup(self._task_path(task_id), raw, previous_raw)
            self._write_checkpoint(updated, raw)
            return self._public_snapshot(updated, audience)

    @staticmethod
    def _unit(task: Mapping[str, Any], work_unit_id: str) -> dict[str, Any]:
        for unit in task.get("workUnits", []):
            if unit.get("workUnitId") == work_unit_id:
                return unit
        raise StudyTaskError("TASK_WORK_UNIT_NOT_FOUND", "Work unit was not found")

    def start_task(
        self, task_id: str, audience: ArtifactAudienceBinding, *, expected_revision: int, operation_id: str
    ) -> dict[str, Any]:
        def apply(task: dict[str, Any]) -> None:
            if task["state"] != "queued":
                raise StudyTaskError("TASK_STATE_CONFLICT", "Only a queued task can start")
            task["state"] = "running"
            if task["workUnits"]:
                task["progress"]["phase"] = task["workUnits"][0]["phase"]
            task["progress"]["lastProgressAt"] = _now()

        return self._mutate(
            task_id=task_id, audience=audience, expected_revision=expected_revision,
            operation_id=operation_id, operation_payload={"action": "start"}, mutation=apply,
        )

    @staticmethod
    def _percent(value: Any, label: str, *, terminal: bool = False) -> float | int | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 or value > 100:
            raise StudyTaskError("TASK_PROGRESS_INVALID", f"{label} must be null or between 0 and 100")
        if not terminal and value >= 100:
            raise StudyTaskError("TASK_PROGRESS_INVALID", "Only a succeeded task can report 100% overall progress")
        return value

    def update_progress(
        self,
        task_id: str,
        audience: ArtifactAudienceBinding,
        *,
        expected_revision: int,
        operation_id: str,
        phase: str,
        phase_percent: float | int | None,
        overall_percent: float | int | None,
        completed_items: int | None = None,
        total_items: int | None = None,
        completed_batches: int | None = None,
        total_batches: int | None = None,
    ) -> dict[str, Any]:
        if phase not in TASK_STAGES:
            raise StudyTaskError("TASK_PROGRESS_INVALID", "Task phase is invalid")
        phase_percent = self._percent(phase_percent, "phasePercent", terminal=True)
        overall_percent = self._percent(overall_percent, "overallPercent")
        counts = {
            "completedItems": completed_items, "totalItems": total_items,
            "completedBatches": completed_batches, "totalBatches": total_batches,
        }
        for name, value in counts.items():
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
                raise StudyTaskError("TASK_PROGRESS_INVALID", f"{name} must be a non-negative integer")
        if completed_items is not None and total_items is not None and completed_items > total_items:
            raise StudyTaskError("TASK_PROGRESS_INVALID", "completedItems exceeds totalItems")
        if completed_batches is not None and total_batches is not None and completed_batches > total_batches:
            raise StudyTaskError("TASK_PROGRESS_INVALID", "completedBatches exceeds totalBatches")

        payload = {"phase": phase, "phasePercent": phase_percent, "overallPercent": overall_percent, **counts}

        def apply(task: dict[str, Any]) -> None:
            if task["state"] not in {"running", "cancelling"}:
                raise StudyTaskError("TASK_STATE_CONFLICT", "Progress can only update an active task")
            old = task["progress"]
            old_overall = old.get("overallPercent")
            if old_overall is not None and (overall_percent is None or overall_percent < old_overall):
                raise StudyTaskError("TASK_PROGRESS_REGRESSION", "Overall progress cannot decrease or become unknown")
            if old.get("phase") == phase and old.get("phasePercent") is not None:
                if phase_percent is None or phase_percent < old["phasePercent"]:
                    raise StudyTaskError("TASK_PROGRESS_REGRESSION", "Progress within the same phase cannot decrease")
            for name, value in counts.items():
                if value is not None:
                    if name.startswith("completed") and old.get(name) is not None and value < old[name]:
                        raise StudyTaskError("TASK_PROGRESS_REGRESSION", f"{name} cannot decrease")
                    old[name] = value
            old.update({"phase": phase, "phasePercent": phase_percent, "overallPercent": overall_percent, "lastProgressAt": _now()})

        return self._mutate(
            task_id=task_id, audience=audience, expected_revision=expected_revision,
            operation_id=operation_id, operation_payload=payload, mutation=apply,
        )

    def begin_work_unit(
        self, task_id: str, audience: ArtifactAudienceBinding, *, expected_revision: int,
        operation_id: str, work_unit_id: str,
    ) -> dict[str, Any]:
        work_unit_id = _require_id(work_unit_id, "workUnitId")

        def apply(task: dict[str, Any]) -> None:
            if task["state"] != "running":
                raise StudyTaskError("TASK_STATE_CONFLICT", "Work can begin only while the task is running")
            if any(unit["state"] == "active" for unit in task["workUnits"]):
                raise StudyTaskError("TASK_WORK_UNIT_CONFLICT", "Another work unit is already active")
            unit = self._unit(task, work_unit_id)
            if unit["state"] not in {"pending", "failed"}:
                raise StudyTaskError("TASK_WORK_UNIT_CONFLICT", "Work unit is not pending or retryable")
            unit["state"] = "active"
            unit["attempt"] += 1
            unit["resultRefs"] = []
            task["progress"]["phase"] = unit["phase"]
            task["progress"]["phasePercent"] = 0
            task["progress"]["lastProgressAt"] = _now()

        return self._mutate(
            task_id=task_id, audience=audience, expected_revision=expected_revision,
            operation_id=operation_id, operation_payload={"action": "begin_work_unit", "workUnitId": work_unit_id}, mutation=apply,
        )

    def _refs_from_handles(
        self, handles: Sequence[str], audience: ArtifactAudienceBinding, scope_id: str
    ) -> list[dict[str, Any]]:
        if not isinstance(handles, Sequence) or isinstance(handles, (str, bytes)):
            raise StudyTaskError("TASK_RESULT_INVALID", "Artifact handles must be a list")
        refs: list[dict[str, Any]] = []
        for handle in handles:
            try:
                ref, envelope = self._artifacts.resolve_with_ref(handle, audience)
            except ArtifactRegistryError as error:
                raise StudyTaskError("TASK_RESULT_INVALID", "Artifact result handle failed verification") from error
            if envelope["projectId"] != scope_id:
                raise StudyTaskError("TASK_RESULT_SCOPE_MISMATCH", "Work result belongs to another project scope")
            refs.append(ref)
        keys = [(ref["artifactId"], ref["artifactRevision"], ref["artifactDigest"]) for ref in refs]
        if len(keys) != len(set(keys)):
            raise StudyTaskError("TASK_RESULT_INVALID", "Artifact results contain a duplicate")
        return refs

    def complete_work_unit(
        self, task_id: str, audience: ArtifactAudienceBinding, *, expected_revision: int,
        operation_id: str, work_unit_id: str, result_handles: Sequence[str],
    ) -> dict[str, Any]:
        work_unit_id = _require_id(work_unit_id, "workUnitId")
        handle_digests = self._handle_digests(result_handles)

        def apply(task: dict[str, Any]) -> None:
            if task["state"] != "running":
                raise StudyTaskError("TASK_STATE_CONFLICT", "Work can complete only while the task is running")
            unit = self._unit(task, work_unit_id)
            if unit["state"] != "active":
                raise StudyTaskError("TASK_WORK_UNIT_CONFLICT", "Work unit is not active")
            unit["resultRefs"] = self._refs_from_handles(result_handles, audience, self._scope_id_from_task(task))
            unit["state"] = "completed"
            task["progress"]["phasePercent"] = 100
            task["progress"]["lastProgressAt"] = _now()

        return self._mutate(
            task_id=task_id, audience=audience, expected_revision=expected_revision,
            operation_id=operation_id,
            operation_payload={"action": "complete_work_unit", "workUnitId": work_unit_id, "handleDigests": handle_digests},
            mutation=apply,
        )

    def _scope_id_from_task(self, task: Mapping[str, Any]) -> str:
        record, _, _ = self._load_task(task["taskId"])
        return record["scopeId"]

    def succeed_task(
        self,
        task_id: str,
        audience: ArtifactAudienceBinding,
        *,
        expected_revision: int,
        operation_id: str,
        result_handles: Sequence[str] = (),
    ) -> dict[str, Any]:
        handle_digests = self._handle_digests(result_handles)

        def apply(task: dict[str, Any]) -> None:
            if task["state"] != "running":
                raise StudyTaskError("TASK_STATE_CONFLICT", "Only a running task can succeed")
            if any(unit["state"] != "completed" for unit in task["workUnits"]):
                raise StudyTaskError("TASK_WORK_INCOMPLETE", "All work units must complete before task success")
            if result_handles:
                refs = self._refs_from_handles(result_handles, audience, self._scope_id_from_task(task))
            else:
                refs = [dict(ref) for unit in task["workUnits"] for ref in unit["resultRefs"]]
            keys = [(ref["artifactId"], ref["artifactRevision"], ref["artifactDigest"]) for ref in refs]
            if len(keys) != len(set(keys)):
                raise StudyTaskError("TASK_RESULT_INVALID", "Final task results contain a duplicate")
            task["resultRefs"] = refs
            task["state"] = "succeeded"
            task["cancellable"] = False
            task["progress"]["phasePercent"] = 100
            task["progress"]["overallPercent"] = 100
            task["progress"]["lastProgressAt"] = _now()

        return self._mutate(
            task_id=task_id, audience=audience, expected_revision=expected_revision,
            operation_id=operation_id,
            operation_payload={"action": "succeed", "handleDigests": handle_digests}, mutation=apply,
        )

    @staticmethod
    def _handle_digests(handles: Sequence[str]) -> list[str]:
        if not isinstance(handles, Sequence) or isinstance(handles, (str, bytes)):
            raise StudyTaskError("TASK_RESULT_INVALID", "Artifact handles must be a list")
        result: list[str] = []
        for handle in handles:
            if not isinstance(handle, str):
                raise StudyTaskError("TASK_RESULT_INVALID", "Artifact handle must be a string")
            result.append(_sha(handle.encode("utf-8")))
        return result

    def fail_task(
        self,
        task_id: str,
        audience: ArtifactAudienceBinding,
        *,
        expected_revision: int,
        operation_id: str,
        code: str,
        stage: str,
        retryable: bool,
        remote_cost_state: str,
        retry_scope: str,
        authorization_state: str,
        preserved_artifact_handles: Sequence[str] = (),
        required_action: str | None = None,
        required_action_context_ref: str | None = None,
    ) -> dict[str, Any]:
        if code not in TOOL_ERROR_CODES or stage not in TASK_STAGES:
            raise StudyTaskError("TASK_FAILURE_INVALID", "Task failure code or stage is invalid")
        if remote_cost_state not in {"none", "possible", "incurred", "unknown"}:
            raise StudyTaskError("TASK_FAILURE_INVALID", "Remote cost state is invalid")
        if retry_scope not in {"none", "item", "batch", "phase", "whole_task"}:
            raise StudyTaskError("TASK_FAILURE_INVALID", "Retry scope is invalid")
        if authorization_state not in {"not_required", "valid", "required", "expired", "revoked"}:
            raise StudyTaskError("TASK_FAILURE_INVALID", "Authorization state is invalid")
        if required_action is not None and required_action not in WORKFLOW_ACTIONS:
            raise StudyTaskError("TASK_FAILURE_INVALID", "Required action is invalid")
        if required_action_context_ref is not None:
            _require_id(required_action_context_ref, "requiredActionContextRef")
        handle_digests = self._handle_digests(preserved_artifact_handles)
        payload = {
            "action": "fail", "code": code, "stage": stage, "retryable": bool(retryable),
            "remoteCostState": remote_cost_state, "retryScope": retry_scope,
            "authorizationState": authorization_state, "handleDigests": handle_digests,
            "requiredAction": required_action, "requiredActionContextRef": required_action_context_ref,
        }

        def apply(task: dict[str, Any]) -> None:
            if task["state"] not in {"running", "cancelling"}:
                raise StudyTaskError("TASK_STATE_CONFLICT", "Only an active task can fail")
            refs = self._refs_from_handles(preserved_artifact_handles, audience, self._scope_id_from_task(task))
            failure: dict[str, Any] = {
                "code": code, "stage": stage, "retryable": bool(retryable),
                "remoteCostState": remote_cost_state, "retryScope": retry_scope,
                "authorizationState": authorization_state, "preservedArtifactRefs": refs,
            }
            if required_action is not None:
                failure["requiredAction"] = required_action
            if required_action_context_ref is not None:
                failure["requiredActionContextRef"] = required_action_context_ref
            for unit in task["workUnits"]:
                if unit["state"] == "active":
                    unit["state"] = "failed"
            task["failure"] = failure
            task["state"] = "failed"
            task["cancellable"] = False
            task["progress"]["lastProgressAt"] = _now()

        return self._mutate(
            task_id=task_id, audience=audience, expected_revision=expected_revision,
            operation_id=operation_id, operation_payload=payload, mutation=apply,
        )

    def request_cancel(
        self, task_id: str, audience: ArtifactAudienceBinding, *, expected_revision: int, operation_id: str
    ) -> dict[str, Any]:
        def apply(task: dict[str, Any]) -> None:
            if not task["cancellable"] or task["state"] not in {"queued", "running"}:
                raise StudyTaskError("TASK_NOT_CANCELLABLE", "Task is not cancellable")
            if task["state"] == "queued":
                task["state"] = "cancelled"
                task["cancellable"] = False
                for unit in task["workUnits"]:
                    unit["state"] = "cancelled"
            else:
                task["state"] = "cancelling"
            task["progress"]["phase"] = "cancellation"
            task["progress"]["phasePercent"] = None
            task["progress"]["lastProgressAt"] = _now()

        return self._mutate(
            task_id=task_id, audience=audience, expected_revision=expected_revision,
            operation_id=operation_id, operation_payload={"action": "request_cancel"}, mutation=apply,
        )

    def finish_cancellation(
        self,
        task_id: str,
        audience: ArtifactAudienceBinding,
        *,
        expected_revision: int,
        operation_id: str,
        safe_checkpoint_proven: bool,
    ) -> dict[str, Any]:
        def apply(task: dict[str, Any]) -> None:
            if task["state"] != "cancelling":
                raise StudyTaskError("TASK_STATE_CONFLICT", "Task is not cancelling")
            task["state"] = "cancelled" if safe_checkpoint_proven else "interrupted"
            task["cancellable"] = False
            for unit in task["workUnits"]:
                if unit["state"] == "active":
                    unit["state"] = "cancelled" if safe_checkpoint_proven else "failed"
            task["progress"]["phasePercent"] = 100 if safe_checkpoint_proven else None
            task["progress"]["lastProgressAt"] = _now()

        return self._mutate(
            task_id=task_id, audience=audience, expected_revision=expected_revision,
            operation_id=operation_id,
            operation_payload={"action": "finish_cancellation", "safeCheckpointProven": bool(safe_checkpoint_proven)},
            mutation=apply,
        )

    def interrupt_stale_task(
        self,
        task_id: str,
        audience: ArtifactAudienceBinding,
        *,
        expected_revision: int,
        operation_id: str,
        allow_current_audience_orphan: bool = False,
    ) -> dict[str, Any]:
        if not isinstance(allow_current_audience_orphan, bool):
            raise StudyTaskError(
                "TASK_SCHEMA_INVALID", "allowCurrentAudienceOrphan must be a boolean"
            )
        def apply(task: dict[str, Any]) -> None:
            if task["state"] not in ACTIVE_TASK_STATES:
                raise StudyTaskError("TASK_STATE_CONFLICT", "Only an active predecessor can be marked interrupted")
            task["state"] = "interrupted"
            task["cancellable"] = False
            for unit in task["workUnits"]:
                if unit["state"] == "active":
                    unit["state"] = "failed"
            task["failure"] = {
                "code": "WORKER_EXITED", "stage": "recovery", "retryable": True,
                "remoteCostState": "unknown", "retryScope": "phase",
                "authorizationState": "required", "preservedArtifactRefs": [],
                "requiredAction": "resume_task",
            }
            task["progress"]["phase"] = "recovery"
            task["progress"]["phasePercent"] = None
            task["progress"]["lastProgressAt"] = _now()

        with self._transaction():
            record, _, _ = self._load_task(task_id)
            current = _sha(canonical_json_bytes(audience.audience(self._service_instance_id)))
            if (
                record.get("createdAudienceDigest") == current
                and not allow_current_audience_orphan
            ):
                raise StudyTaskError("TASK_STATE_CONFLICT", "Current-session tasks cannot be marked stale")
        return self._mutate(
            task_id=task_id, audience=audience, expected_revision=expected_revision,
            operation_id=operation_id, operation_payload={"action": "interrupt_stale_task"}, mutation=apply,
            require_created_audience=False,
        )

    def list_recoverable_tasks(
        self,
        audience: ArtifactAudienceBinding,
        *,
        scope_id: str | None = None,
        limit: int = 100,
        include_active: bool = False,
        exclude_task_ids: frozenset[str] = frozenset(),
        intent: str | None = None,
    ) -> list[dict[str, Any]]:
        if scope_id is not None:
            _require_id(scope_id, "scopeId")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise StudyTaskError("TASK_SCHEMA_INVALID", "Recoverable task limit is invalid")
        if not isinstance(include_active, bool):
            raise StudyTaskError("TASK_SCHEMA_INVALID", "includeActive must be a boolean")
        if not isinstance(exclude_task_ids, frozenset) or len(exclude_task_ids) > 512:
            raise StudyTaskError(
                "TASK_SCHEMA_INVALID", "Excluded active task identifiers are invalid"
            )
        if intent is not None and intent not in WORKFLOW_ACTIONS:
            raise StudyTaskError(
                "TASK_SCHEMA_INVALID", "Recoverable task intent is invalid"
            )
        for task_id in exclude_task_ids:
            _require_id(task_id, "excludedTaskId")
        selected: list[dict[str, Any]] = []
        isolated_codes = {
            "TASK_AUTH_INVALID",
            "TASK_NOT_FOUND",
            "TASK_RECORD_CHANGED",
            "TASK_RECORD_CORRUPT",
            "TASK_RECORD_INVALID",
            "TASK_RECORD_TOO_LARGE",
            "TASK_SCOPE_MISMATCH",
        }
        with self._transaction():
            paths: list[Path] = []
            for path in self._tasks_root.glob("*/*.json"):
                paths.append(path)
                if len(paths) > MAX_RECOVERY_SCAN_RECORDS:
                    raise StudyTaskError(
                        "TASK_LIST_SCAN_LIMIT",
                        "Recoverable task storage exceeds the bounded scan limit",
                    )
            for path in paths:
                try:
                    record, _, _ = self._load_with_backup(
                        path,
                        domain="study.task.record.v1",
                        schema="study.task.record",
                    )
                    self._authorize_scope(record, audience)
                except StudyTaskError as error:
                    if error.code in isolated_codes:
                        continue
                    raise
                task = record["task"]
                if intent is not None and task["intent"] != intent:
                    continue
                if scope_id is not None and record["scopeId"] != scope_id:
                    continue
                if task["taskId"] in exclude_task_ids:
                    continue
                terminal = (
                    task["state"] in {"failed", "cancelled", "interrupted"}
                    and task["resumability"] != "none"
                )
                orphan_candidate = (
                    include_active
                    and task["state"] in ACTIVE_TASK_STATES
                    and task["resumability"] != "none"
                )
                if not terminal and not orphan_candidate:
                    continue
                selected.append(record)
                selected.sort(
                    key=lambda item: (
                        item["task"]["updatedAt"],
                        item["task"]["taskId"],
                    ),
                    reverse=True,
                )
                if len(selected) > limit:
                    selected.pop()
        return [self._public_snapshot(record, audience) for record in selected]

    @staticmethod
    def _capabilities_compatible(previous: Mapping[str, Any], current: Mapping[str, Any]) -> bool:
        def indexed(binding: Mapping[str, Any]) -> dict[tuple[str, str, str], dict[str, Any]]:
            result: dict[tuple[str, str, str], dict[str, Any]] = {}
            for item in binding.get("required", []):
                if item.get("kind") == "fixed":
                    key = ("fixed", item.get("capabilityId", ""), "")
                else:
                    key = ("service_profile", item.get("capability", ""), item.get("profileRef", ""))
                result[key] = dict(item)
            return result

        old = indexed(previous)
        new = indexed(current)
        if set(old) != set(new):
            return False
        for key in old:
            left = dict(old[key])
            right = dict(new[key])
            if key[0] == "service_profile":
                left.pop("credentialRevision", None)
                right.pop("credentialRevision", None)
            if left != right:
                return False
        return True

    @staticmethod
    def _authorization_relation(
        previous: Mapping[str, Any],
        current: Mapping[str, Any],
        relation: str,
        *,
        allow_reauthorization: bool,
    ) -> bool:
        if allow_reauthorization:
            old_actions = {
                str(item.get("action"))
                for item in previous.get("bindings", [])
                if isinstance(item, Mapping)
            }
            new_actions = {
                str(item.get("action"))
                for item in current.get("bindings", [])
                if isinstance(item, Mapping)
            }
            return (
                new_actions == old_actions
                if relation == "equivalent"
                else bool(new_actions) and new_actions.issubset(old_actions)
            )
        def scopes(binding: Mapping[str, Any]) -> set[tuple[str, str, str]]:
            return {
                (item["action"], item["constraintsDigest"], item["exactScopeDigest"])
                for item in binding.get("bindings", [])
            }

        old = scopes(previous)
        new = scopes(current)
        return new == old if relation == "equivalent" else bool(new) and new.issubset(old)

    def _successor_task_id(self, predecessor_task_id: str, operation_id: str) -> str:
        message = b"study.task.successor-id.v1\x00" + predecessor_task_id.encode("utf-8") + b"\x00" + operation_id.encode("utf-8")
        raw = hmac.new(self._authentication_key, message, hashlib.sha256).digest()[:24]
        return "task_" + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    def _task_lineage_root(
        self, task_id: str, audience: ArtifactAudienceBinding
    ) -> str:
        current = _require_id(task_id, "taskId")
        seen: set[str] = set()
        with self._transaction():
            while True:
                if current in seen:
                    raise StudyTaskError(
                        "TASK_RECORD_INVALID", "Task predecessor lineage contains a cycle"
                    )
                seen.add(current)
                record, _, _ = self._load_task(current)
                self._authorize_scope(record, audience)
                predecessor = record["task"].get("predecessorTaskId")
                if predecessor is None:
                    return current
                current = _require_id(predecessor, "predecessorTaskId")

    def _assert_lineage_successor_available(
        self,
        lineage_task_id: str,
        proposed_successor_id: str,
        audience: ArtifactAudienceBinding,
    ) -> None:
        records: dict[str, dict[str, Any]] = {}
        isolated_codes = {
            "TASK_AUTH_INVALID",
            "TASK_NOT_FOUND",
            "TASK_RECORD_CHANGED",
            "TASK_RECORD_CORRUPT",
            "TASK_RECORD_INVALID",
            "TASK_RECORD_TOO_LARGE",
            "TASK_SCOPE_MISMATCH",
        }
        with self._transaction():
            paths: list[Path] = []
            for path in self._tasks_root.glob("*/*.json"):
                paths.append(path)
                if len(paths) > MAX_RECOVERY_SCAN_RECORDS:
                    raise StudyTaskError(
                        "TASK_LIST_SCAN_LIMIT",
                        "Successor lineage storage exceeds the bounded scan limit",
                    )
            for path in paths:
                try:
                    record, _, _ = self._load_with_backup(
                        path,
                        domain="study.task.record.v1",
                        schema="study.task.record",
                    )
                    self._authorize_scope(record, audience)
                except StudyTaskError as error:
                    if error.code in isolated_codes:
                        continue
                    raise
                task = record["task"]
                records[str(task["taskId"])] = task

        def root_for(task_id: str) -> str:
            current = task_id
            seen: set[str] = set()
            while True:
                if current in seen:
                    raise StudyTaskError(
                        "TASK_RECORD_INVALID", "Task predecessor lineage contains a cycle"
                    )
                seen.add(current)
                task = records.get(current)
                predecessor = (
                    task.get("predecessorTaskId")
                    if isinstance(task, Mapping)
                    else None
                )
                if predecessor is None:
                    return current
                current = _require_id(predecessor, "predecessorTaskId")

        for task_id, task in records.items():
            if (
                task_id == proposed_successor_id
                or task.get("state") not in ACTIVE_TASK_STATES
                or task.get("predecessorTaskId") is None
            ):
                continue
            if root_for(task_id) == lineage_task_id:
                raise StudyTaskError(
                    "TASK_SUCCESSOR_ACTIVE",
                    "This recovery lineage already has an active successor",
                )

    def get_successor_task(
        self,
        predecessor_task_id: str,
        operation_id: str,
        audience: ArtifactAudienceBinding,
    ) -> dict[str, Any] | None:
        _require_id(predecessor_task_id, "predecessorTaskId")
        _require_id(operation_id, "operationId")
        successor_id = self._successor_task_id(predecessor_task_id, operation_id)
        try:
            return self.get_task(successor_id, audience)
        except StudyTaskError as error:
            if error.code == "TASK_NOT_FOUND":
                return None
            raise

    def create_successor_task(
        self,
        predecessor_task_id: str,
        audience: ArtifactAudienceBinding,
        *,
        operation_id: str,
        authorization_binding: Mapping[str, Any],
        capability_binding: Mapping[str, Any],
        service_bindings: Sequence[Mapping[str, Any]],
        scope_relation: str,
        predecessor_authorization_audit_ref: str,
        successor_authorization_audit_ref: str,
        operation_intent_digest: str | None = None,
        cost_budget_digest: str | None = None,
        batch_policy_digest: str | None = None,
        allow_reauthorization: bool = False,
    ) -> dict[str, Any]:
        lineage_task_id = self._task_lineage_root(predecessor_task_id, audience)
        proposed_successor_id = self._successor_task_id(
            predecessor_task_id, operation_id
        )
        with self._successor_lineage_transaction(lineage_task_id):
            self._assert_lineage_successor_available(
                lineage_task_id, proposed_successor_id, audience
            )
            return self._create_successor_task_locked(
                predecessor_task_id,
                audience,
                operation_id=operation_id,
                authorization_binding=authorization_binding,
                capability_binding=capability_binding,
                service_bindings=service_bindings,
                scope_relation=scope_relation,
                predecessor_authorization_audit_ref=predecessor_authorization_audit_ref,
                successor_authorization_audit_ref=successor_authorization_audit_ref,
                operation_intent_digest=operation_intent_digest,
                cost_budget_digest=cost_budget_digest,
                batch_policy_digest=batch_policy_digest,
                allow_reauthorization=allow_reauthorization,
            )

    def _create_successor_task_locked(
        self,
        predecessor_task_id: str,
        audience: ArtifactAudienceBinding,
        *,
        operation_id: str,
        authorization_binding: Mapping[str, Any],
        capability_binding: Mapping[str, Any],
        service_bindings: Sequence[Mapping[str, Any]],
        scope_relation: str,
        predecessor_authorization_audit_ref: str,
        successor_authorization_audit_ref: str,
        operation_intent_digest: str | None = None,
        cost_budget_digest: str | None = None,
        batch_policy_digest: str | None = None,
        allow_reauthorization: bool = False,
    ) -> dict[str, Any]:
        _require_id(predecessor_task_id, "predecessorTaskId")
        _require_id(operation_id, "operationId")
        if not isinstance(allow_reauthorization, bool):
            raise StudyTaskError(
                "TASK_SCHEMA_INVALID", "allowReauthorization must be a boolean"
            )
        if scope_relation not in {"equivalent", "narrower"}:
            raise StudyTaskError("TASK_SUCCESSOR_INVALID", "Successor scope relation is invalid")
        try:
            rebuilt_capability, _ = build_capability_binding(capability_binding.get("required"))
            rebuilt_authorization, _ = build_authorization_binding(
                audience=audience,
                service_instance_id=self._service_instance_id,
                bindings=authorization_binding.get("bindings"),
            )
        except TaskManifestError as error:
            raise StudyTaskError(error.code, error.message) from error
        if rebuilt_capability != dict(capability_binding) or rebuilt_authorization != dict(authorization_binding):
            raise StudyTaskError("TASK_SCHEMA_INVALID", "Successor capability or authorization binding is not canonical")
        with self._transaction():
            predecessor, _, _ = self._load_task(predecessor_task_id)
            self._authorize_scope(predecessor, audience)
            previous_task = predecessor["task"]
            if previous_task["state"] not in {"failed", "cancelled", "interrupted"}:
                raise StudyTaskError("TASK_SUCCESSOR_INVALID", "Only a recoverable terminal task can have a successor")
            if previous_task["resumability"] == "none":
                raise StudyTaskError("TASK_SUCCESSOR_INVALID", "Task does not permit recovery")
            if not self._capabilities_compatible(predecessor["capabilityBinding"], capability_binding):
                raise StudyTaskError("TASK_CAPABILITY_INCOMPATIBLE", "Successor capabilities are not stable-compatible")
            if not self._authorization_relation(
                predecessor["authorizationBinding"],
                authorization_binding,
                scope_relation,
                allow_reauthorization=allow_reauthorization,
            ):
                raise StudyTaskError("TASK_AUTHORIZATION_SCOPE_EXPANDED", "Successor authorization is not equivalent or narrower")
            work_reuse = dict(predecessor["workReuseManifest"])
            work_digest = previous_task["workReuseDigest"]
            completed: dict[str, list[dict[str, Any]]] = {}
            reused_units: list[dict[str, Any]] = []
            for unit in previous_task["workUnits"]:
                refs = [dict(ref) for ref in unit["resultRefs"]]
                if unit["state"] != "completed" or not refs:
                    continue
                for ref in refs:
                    self._verify_result_ref(ref, audience, predecessor["scopeId"])
                completed[unit["workUnitId"]] = refs
                reused_units.append({
                    "workUnitId": unit["workUnitId"],
                    "resultArtifactDigests": [ref["artifactDigest"] for ref in refs],
                })
            successor_id = self._successor_task_id(predecessor_task_id, operation_id)
            rebase, rebase_digest = build_successor_rebase(
                predecessor_task_id=predecessor_task_id,
                predecessor_task_input_digest=previous_task["inputFingerprint"],
                successor_task_id=successor_id,
                work_reuse_digest=work_digest,
                scope_relation=scope_relation,
                reused_work_units=reused_units,
                predecessor_authorization_audit_ref=predecessor_authorization_audit_ref,
                successor_authorization_audit_ref=successor_authorization_audit_ref,
            )
        subject = dict(work_reuse["subject"])
        subject.pop("cardPlanSetDigest", None)
        capability_digest = manifest_digest(capability_binding)
        authorization_digest = manifest_digest(authorization_binding)
        task_input, expected_input_digest = build_task_input_manifest(
            action_id=work_reuse["actionId"],
            work_reuse_manifest=work_reuse,
            work_reuse_digest=work_digest,
            subject=subject,
            authorization_binding_digest=authorization_digest,
            capability_binding_digest=capability_digest,
            component_versions=work_reuse["componentVersions"],
            service_bindings=service_bindings,
            operation_intent_digest=operation_intent_digest,
            generation_policy_digest=work_reuse.get("generationPolicyDigest"),
            cost_budget_digest=cost_budget_digest,
            batch_policy_digest=batch_policy_digest,
            successor_rebase_digest=rebase_digest,
        )
        specs = [{"workUnitId": unit["workUnitId"], "phase": unit["phase"]} for unit in previous_task["workUnits"]]
        try:
            return self.create_task(
                audience=audience,
                work_reuse_manifest=work_reuse,
                task_input_manifest=task_input,
                capability_binding=capability_binding,
                authorization_binding=authorization_binding,
                work_units=specs,
                cancellable=True,
                resumability=previous_task["resumability"],
                predecessor_task_id=predecessor_task_id,
                _task_id=successor_id,
                _initial_completed_units=completed,
                _successor_rebase=rebase,
            )
        except StudyTaskError as error:
            if error.code != "TASK_ALREADY_EXISTS":
                raise
            with self._transaction():
                existing, _, _ = self._load_task(successor_id)
                self._authorize_scope(existing, audience)
                if manifest_digest(existing["taskInputManifest"]) != expected_input_digest:
                    raise StudyTaskError("TASK_IDEMPOTENCY_CONFLICT", "Successor operationId was reused with different execution input") from error
                return self._public_snapshot(existing, audience)
