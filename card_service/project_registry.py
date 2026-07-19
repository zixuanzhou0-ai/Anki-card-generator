from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import stat
import threading
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from .artifact_registry import (
    ArtifactAudienceBinding,
    ArtifactRegistryError,
    canonical_json_bytes,
    validate_persistable_json,
)


MAX_PROJECT_BYTES = 4 * 1024 * 1024
MAX_OPERATIONS = 512
MAX_PATCH_OPERATIONS = 64
MAX_TEXT_LENGTH = 4_000
MAX_TITLE_LENGTH = 240
MAX_EXCLUSIONS = 256
MAX_ROUTES = 32
MAX_SAFE_INTEGER = 9_007_199_254_740_991

ID_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-")
LEARNING_ROUTES = frozenset(
    {
        "reading_recognition", "listening_recognition", "production", "grammar_cloze",
        "pronunciation", "pragmatics_register", "chunk_collocation", "contrast",
        "fact_recall", "definition", "concept_discrimination", "causal_reconstruction",
        "comparison", "process_recall", "argument_attribution", "formula_application",
        "application_transfer", "procedural_decision", "error_repair",
    }
)
EVIDENCE_POLICIES = frozenset({"automatic", "review_tier_b", "draft_only"})
ARTIFACT_STAGES = (
    "empty", "sources_ready", "candidates_ready", "selection_ready", "plans_ready",
    "cards_ready", "apkg_ready", "imported_unverified", "anki_data_verified", "anki_verified",
)
SECRET_VALUE_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~-]{20,}\b", re.IGNORECASE),
)


class ProjectRegistryError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _require_id(value: Any, label: str) -> str:
    if (
        not isinstance(value, str) or not value or len(value) > 256
        or any(character not in ID_CHARS for character in value)
    ):
        raise ProjectRegistryError("PROJECT_SCHEMA_INVALID", f"{label} is invalid")
    return value


def _require_digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ProjectRegistryError(
            "PROJECT_SCHEMA_INVALID",
            f"{label} must be a lowercase SHA-256 digest",
        )
    return value


def _require_revision(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > MAX_SAFE_INTEGER:
        raise ProjectRegistryError("PROJECT_SCHEMA_INVALID", f"{label} must be a positive safe integer")
    return value


def _text(value: Any, label: str, *, maximum: int = MAX_TEXT_LENGTH) -> str:
    if not isinstance(value, str):
        raise ProjectRegistryError("PROJECT_SCHEMA_INVALID", f"{label} must be text")
    normalized = unicodedata.normalize("NFC", value).strip()
    if not normalized or len(normalized) > maximum:
        raise ProjectRegistryError("PROJECT_SCHEMA_INVALID", f"{label} length is invalid")
    if any(pattern.search(normalized) for pattern in SECRET_VALUE_PATTERNS):
        raise ProjectRegistryError("PROJECT_SECRET_FORBIDDEN", f"{label} appears to contain a credential")
    return normalized


def _require_exact_fields(
    value: Mapping[str, Any], required: set[str], optional: set[str], label: str
) -> None:
    if (
        not isinstance(value, Mapping) or not required.issubset(value)
        or not set(value).issubset(required | optional)
    ):
        raise ProjectRegistryError("PROJECT_SCHEMA_INVALID", f"{label} fields are invalid")


def _positive_integer(value: Any, label: str, *, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > maximum:
        raise ProjectRegistryError("PROJECT_SCHEMA_INVALID", f"{label} is outside its allowed range")
    return value


def _normalize_routes(values: Any) -> list[str]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise ProjectRegistryError("PROJECT_SCHEMA_INVALID", "routes must be a list")
    routes = list(values)
    if not routes or len(routes) > MAX_ROUTES or any(route not in LEARNING_ROUTES for route in routes):
        raise ProjectRegistryError("PROJECT_SCHEMA_INVALID", "routes contain an unsupported value")
    if len(routes) != len(set(routes)):
        raise ProjectRegistryError("PROJECT_SCHEMA_INVALID", "routes contain a duplicate")
    return routes


def _normalize_exclusions(values: Any) -> list[str]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise ProjectRegistryError("PROJECT_SCHEMA_INVALID", "exclusions must be a list")
    exclusions = [_text(value, "exclusion", maximum=500) for value in values]
    if len(exclusions) > MAX_EXCLUSIONS:
        raise ProjectRegistryError("PROJECT_SCHEMA_INVALID", "too many exclusions")
    exclusions.sort(key=lambda value: value.encode("utf-8"))
    if len(exclusions) != len(set(exclusions)):
        raise ProjectRegistryError("PROJECT_SCHEMA_INVALID", "exclusions contain a duplicate")
    return exclusions


def _temporary_file(path: Path, data: bytes) -> Path:
    temporary = path.parent / f".{path.name}.{secrets.token_hex(12)}.partial"
    with temporary.open("xb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())
    return temporary


def _ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    info = path.lstat()
    attributes = getattr(info, "st_file_attributes", 0)
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or attributes & 0x400:
        raise ProjectRegistryError("PROJECT_STORAGE_UNSAFE", "Project storage contains a link or reparse directory")
    return path


def _stage_at_most(current: str, maximum: str) -> str:
    if current not in ARTIFACT_STAGES:
        raise ProjectRegistryError("PROJECT_RECORD_INVALID", "Project artifact stage is invalid")
    return ARTIFACT_STAGES[min(ARTIFACT_STAGES.index(current), ARTIFACT_STAGES.index(maximum))]


def _workflow_for_stage(stage: str) -> tuple[str, str]:
    if stage == "empty":
        return "source", "select_source"
    if stage == "sources_ready":
        return "source", "inspect_source"
    if stage in {"candidates_ready", "selection_ready"}:
        return "select", "review_candidates" if stage == "candidates_ready" else "plan_cards"
    if stage in {"plans_ready", "cards_ready"}:
        return "deliver", "generate_cards" if stage == "plans_ready" else "export_apkg"
    if stage == "apkg_ready":
        return "deliver", "prepare_anki_import"
    if stage in {"imported_unverified", "anki_data_verified"}:
        return "deliver", "import_and_verify"
    return "deliver", "view_results"


def _validate_persistable(value: Mapping[str, Any]) -> None:
    try:
        validate_persistable_json(dict(value))
    except ArtifactRegistryError as error:
        raise ProjectRegistryError("PROJECT_FORBIDDEN_DATA", error.message) from error


class ProjectRegistry:
    def __init__(
        self,
        root: Path,
        *,
        authentication_key: bytes,
        service_instance_id: str,
        key_id: str = "study-project-store-v1",
    ) -> None:
        if not isinstance(authentication_key, bytes) or len(authentication_key) < 32:
            raise ProjectRegistryError(
                "PROJECT_AUTH_KEY_INVALID", "Project authentication key must contain at least 256 bits"
            )
        self._authentication_key = bytes(authentication_key)
        self._service_instance_id = _require_id(service_instance_id, "serviceInstanceId")
        self._key_id = _require_id(key_id, "keyId")
        self._root = _ensure_directory(Path(root).absolute())
        self._projects_root = _ensure_directory(self._root / "projects")
        self._lock_path = self._root / "project-registry.lock"
        try:
            with self._lock_path.open("xb") as output:
                output.write(b"\x00")
                output.flush()
                os.fsync(output.fileno())
        except FileExistsError:
            pass
        self._thread_lock = threading.RLock()

    def _ensure_parent(self, path: Path) -> None:
        absolute = path.absolute()
        try:
            relative = absolute.relative_to(self._root)
        except ValueError as error:
            raise ProjectRegistryError("PROJECT_STORAGE_UNSAFE", "Project storage path escapes its root") from error
        current = _ensure_directory(self._root)
        for part in relative.parts:
            current = _ensure_directory(current / part)

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        with self._thread_lock:
            self._ensure_parent(self._lock_path.parent)
            info = self._lock_path.lstat()
            attributes = getattr(info, "st_file_attributes", 0)
            if (
                not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
                or attributes & 0x400 or info.st_nlink != 1
            ):
                raise ProjectRegistryError(
                    "PROJECT_STORAGE_UNSAFE", "Project registry lock is not a private regular file"
                )
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

    def _mac(self, domain: str, value: Mapping[str, Any]) -> str:
        message = domain.encode("ascii") + b"\x00" + canonical_json_bytes(dict(value))
        return hmac.new(self._authentication_key, message, hashlib.sha256).hexdigest()

    def _authenticate(self, value: Mapping[str, Any]) -> dict[str, Any]:
        unsigned = {**dict(value), "authKeyId": self._key_id}
        return {**unsigned, "authTag": self._mac("study.project.record.v1", unsigned)}

    def _project_path(self, project_id: str) -> Path:
        identity = _sha(_require_id(project_id, "projectId").encode("utf-8"))
        return self._projects_root / identity[:2] / f"{identity}.json"

    def _derive_project_id(self, audience: ArtifactAudienceBinding, idempotency_key: str) -> str:
        if (
            not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key) <= 512
            or any(ord(character) < 0x20 for character in idempotency_key)
        ):
            raise ProjectRegistryError("PROJECT_IDEMPOTENCY_INVALID", "idempotencyKey is invalid")
        stable_audience = {
            "ownerDigest": audience.owner_digest,
            "hostId": audience.host_id,
            "pluginId": audience.plugin_id,
        }
        message = (
            b"study.project-id.v1\x00" + canonical_json_bytes(stable_audience)
            + b"\x00" + idempotency_key.encode("utf-8")
        )
        return "project_" + hmac.new(self._authentication_key, message, hashlib.sha256).hexdigest()[:48]

    def _safe_read(self, path: Path) -> bytes:
        self._ensure_parent(path.parent)
        try:
            info = path.lstat()
        except FileNotFoundError as error:
            raise ProjectRegistryError("PROJECT_NOT_FOUND", "Project was not found") from error
        attributes = getattr(info, "st_file_attributes", 0)
        if (
            not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or attributes & 0x400 or info.st_nlink != 1
        ):
            raise ProjectRegistryError("PROJECT_STORAGE_UNSAFE", "Project record is not a private regular file")
        if info.st_size > MAX_PROJECT_BYTES:
            raise ProjectRegistryError("PROJECT_RECORD_TOO_LARGE", "Project record exceeds its size limit")
        raw = path.read_bytes()
        after = path.lstat()
        before_identity = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
        after_identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        if len(raw) != info.st_size or before_identity != after_identity:
            raise ProjectRegistryError("PROJECT_RECORD_CHANGED", "Project record changed while being read")
        return raw

    def _decode(self, raw: bytes) -> dict[str, Any]:
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ProjectRegistryError("PROJECT_RECORD_INVALID", "Project record is not valid JSON") from error
        if not isinstance(value, dict) or canonical_json_bytes(value) != raw:
            raise ProjectRegistryError("PROJECT_RECORD_INVALID", "Project record is not canonical JSON")
        if value.get("schema") != "study.project.record" or value.get("schemaVersion") != 1:
            raise ProjectRegistryError("PROJECT_RECORD_INVALID", "Project record schema is invalid")
        tag = value.get("authTag")
        unsigned = dict(value)
        unsigned.pop("authTag", None)
        if value.get("authKeyId") != self._key_id or not isinstance(tag, str):
            raise ProjectRegistryError(
                "PROJECT_RECORD_CORRUPT", "Project record authentication key is unavailable"
            )
        if not hmac.compare_digest(tag, self._mac("study.project.record.v1", unsigned)):
            raise ProjectRegistryError("PROJECT_RECORD_CORRUPT", "Project record authentication failed")
        return value

    def _load(self, project_id: str) -> tuple[dict[str, Any], bytes]:
        raw = self._safe_read(self._project_path(project_id))
        return self._decode(raw), raw

    def _publish_new(self, path: Path, raw: bytes) -> None:
        self._ensure_parent(path.parent)
        temporary = _temporary_file(path, raw)
        try:
            try:
                os.link(temporary, path)
            except FileExistsError as error:
                raise ProjectRegistryError("PROJECT_ALREADY_EXISTS", "Project already exists") from error
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def _replace(self, path: Path, raw: bytes, previous_raw: bytes) -> None:
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
    def _authorize(record: Mapping[str, Any], audience: ArtifactAudienceBinding) -> None:
        project_id = record.get("project", {}).get("projectId")
        if not isinstance(project_id, str):
            raise ProjectRegistryError("PROJECT_RECORD_INVALID", "Project identity is invalid")
        expected = _sha(canonical_json_bytes(audience.project_scope(project_id)))
        if record.get("projectScopeDigest") != expected:
            raise ProjectRegistryError(
                "PROJECT_SCOPE_MISMATCH", "Project does not belong to the current owner/host/plugin scope"
            )

    @staticmethod
    def _public(record: Mapping[str, Any]) -> dict[str, Any]:
        return json.loads(json.dumps(record["project"], ensure_ascii=False))

    @staticmethod
    def _normalize_contract_input(
        value: Mapping[str, Any],
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        _require_exact_fields(
            value,
            {"purpose", "targetBehavior"},
            {
                "learnerLevel", "routes", "maxNewCards", "targetDailyReviewMinutes",
                "promptLanguage", "answerLanguage", "exclusions", "evidencePolicy",
            },
            "learningContract",
        )
        defaults: list[dict[str, Any]] = []

        def default(field: str, default_value: Any, reason: str) -> Any:
            defaults.append({"field": field, "value": default_value, "reason": reason})
            return default_value

        routes = (
            _normalize_routes(value["routes"])
            if "routes" in value
            else default(
                "routes", ["reading_recognition"],
                "Safe default for a new mixed-source study project",
            )
        )
        max_cards = (
            _positive_integer(value["maxNewCards"], "maxNewCards", maximum=1_000)
            if "maxNewCards" in value
            else default("maxNewCards", 20, "Bounded first-session workload")
        )
        daily_minutes = (
            _positive_integer(
                value["targetDailyReviewMinutes"], "targetDailyReviewMinutes", maximum=1_440
            )
            if "targetDailyReviewMinutes" in value
            else default(
                "targetDailyReviewMinutes", 20, "Short sustainable daily review budget"
            )
        )
        prompt_language = (
            _text(value["promptLanguage"], "promptLanguage", maximum=64)
            if "promptLanguage" in value
            else default(
                "promptLanguage", "auto",
                "Defer prompt language selection until source inspection",
            )
        )
        answer_language = (
            _text(value["answerLanguage"], "answerLanguage", maximum=64)
            if "answerLanguage" in value
            else default(
                "answerLanguage", "auto",
                "Defer answer language selection until learner context is known",
            )
        )
        evidence_policy = value.get("evidencePolicy", "automatic")
        if evidence_policy not in EVIDENCE_POLICIES:
            raise ProjectRegistryError("PROJECT_SCHEMA_INVALID", "evidencePolicy is invalid")
        if "evidencePolicy" not in value:
            default(
                "evidencePolicy", evidence_policy,
                "Use reliability gates without mandatory manual review",
            )
        learner_level = value.get("learnerLevel")
        if learner_level is not None:
            learner_level = _text(learner_level, "learnerLevel", maximum=200)
        contract = {
            "purpose": _text(value["purpose"], "purpose"),
            "targetBehavior": _text(value["targetBehavior"], "targetBehavior"),
            "routes": routes,
            "budget": {
                "maxNewCards": max_cards,
                "targetDailyReviewMinutes": daily_minutes,
            },
            "promptLanguage": prompt_language,
            "answerLanguage": answer_language,
            "evidencePolicy": evidence_policy,
            "exclusions": _normalize_exclusions(value.get("exclusions", [])),
        }
        if learner_level is not None:
            contract["learnerLevel"] = learner_level
        _validate_persistable(contract)
        return contract, defaults

    def create_project(
        self,
        *,
        audience: ArtifactAudienceBinding,
        idempotency_key: str,
        learning_contract: Mapping[str, Any],
        title: str | None = None,
    ) -> dict[str, Any]:
        project_id = self._derive_project_id(audience, idempotency_key)
        normalized_contract, inferred_defaults = self._normalize_contract_input(learning_contract)
        normalized_title = (
            _text(title, "title", maximum=MAX_TITLE_LENGTH)
            if title is not None
            else "Untitled Study Project"
        )
        if title is None:
            inferred_defaults.insert(
                0,
                {
                    "field": "title",
                    "value": normalized_title,
                    "reason": "No project title was provided",
                },
            )
        contract = {
            "contractId": "contract_" + _sha(project_id.encode("utf-8"))[:40],
            **normalized_contract,
            "contractRevision": 1,
        }
        request_digest = _sha(canonical_json_bytes({
            "title": normalized_title,
            "learningContract": contract,
        }))
        created_at = _now()
        product_step, primary_action = _workflow_for_stage("empty")
        project = {
            "schema": "study.project.snapshot",
            "schemaVersion": 1,
            "projectId": project_id,
            "projectRevision": 1,
            "title": normalized_title,
            "learningContract": contract,
            "learningContractDigest": _sha(canonical_json_bytes(contract)),
            "inferredDefaults": inferred_defaults,
            "workflow": {
                "projectId": project_id,
                "projectRevision": 1,
                "productStep": product_step,
                "artifactStage": "empty",
                "operationState": "idle",
                "primaryActionId": primary_action,
                "blockerIssueRefs": [],
            },
            "latestArtifactRefs": [],
            "createdAt": created_at,
            "updatedAt": created_at,
        }
        _validate_persistable(project)
        record = self._authenticate({
            "schema": "study.project.record",
            "schemaVersion": 1,
            "createdByServiceInstanceId": self._service_instance_id,
            "projectScopeDigest": _sha(
                canonical_json_bytes(audience.project_scope(project_id))
            ),
            "creationRequestDigest": request_digest,
            "project": project,
            "operations": [],
        })
        raw = canonical_json_bytes(record)
        path = self._project_path(project_id)
        with self._transaction():
            try:
                self._publish_new(path, raw)
                return self._public(record)
            except ProjectRegistryError as error:
                if error.code != "PROJECT_ALREADY_EXISTS":
                    raise
                existing, _ = self._load(project_id)
                self._authorize(existing, audience)
                if existing.get("creationRequestDigest") != request_digest:
                    raise ProjectRegistryError(
                        "PROJECT_IDEMPOTENCY_CONFLICT",
                        "idempotencyKey was already used with different project input",
                    ) from error
                return self._public(existing)

    def get_project(
        self, project_id: str, audience: ArtifactAudienceBinding
    ) -> dict[str, Any]:
        with self._transaction():
            record, _ = self._load(project_id)
            self._authorize(record, audience)
            return self._public(record)

    def list_projects(
        self, audience: ArtifactAudienceBinding
    ) -> list[dict[str, Any]]:
        projects: list[dict[str, Any]] = []
        with self._transaction():
            paths = sorted(
                self._projects_root.glob("*/*.json"),
                key=lambda item: str(item).casefold(),
            )
            for path in paths:
                record = self._decode(self._safe_read(path))
                try:
                    self._authorize(record, audience)
                except ProjectRegistryError as error:
                    if error.code == "PROJECT_SCOPE_MISMATCH":
                        continue
                    raise
                projects.append(self._public(record))
        projects.sort(
            key=lambda item: (item["updatedAt"], item["projectId"]),
            reverse=True,
        )
        return projects

    @staticmethod
    def _artifact_refs(
        values: Sequence[Mapping[str, Any]], project_id: str
    ) -> list[dict[str, Any]]:
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
            raise ProjectRegistryError(
                "PROJECT_ARTIFACT_INVALID", "artifactRefs must be a list"
            )
        if not values or len(values) > 512:
            raise ProjectRegistryError(
                "PROJECT_ARTIFACT_INVALID", "artifactRefs count is invalid"
            )
        required = {
            "artifactId",
            "projectId",
            "projectRevision",
            "artifactRevision",
            "payloadSchema",
            "payloadSchemaVersion",
            "artifactDigest",
            "registryAuthRef",
        }
        normalized: list[dict[str, Any]] = []
        for value in values:
            if not isinstance(value, Mapping) or set(value) != required:
                raise ProjectRegistryError(
                    "PROJECT_ARTIFACT_INVALID", "artifact reference fields are invalid"
                )
            item = dict(value)
            _require_id(item["artifactId"], "artifactId")
            if _require_id(item["projectId"], "artifactProjectId") != project_id:
                raise ProjectRegistryError(
                    "PROJECT_ARTIFACT_SCOPE_MISMATCH",
                    "artifact belongs to another project",
                )
            _require_revision(item["projectRevision"], "artifactProjectRevision")
            _require_revision(item["artifactRevision"], "artifactRevision")
            _require_id(item["payloadSchema"], "payloadSchema")
            _require_revision(item["payloadSchemaVersion"], "payloadSchemaVersion")
            _require_digest(item["artifactDigest"], "artifactDigest")
            _require_id(item["registryAuthRef"], "registryAuthRef")
            normalized.append(item)
        normalized.sort(
            key=lambda item: (
                item["artifactId"].encode("utf-8"),
                item["artifactRevision"],
                item["artifactDigest"],
            )
        )
        identities = [
            (item["artifactId"], item["artifactRevision"], item["artifactDigest"])
            for item in normalized
        ]
        if len(identities) != len(set(identities)):
            raise ProjectRegistryError(
                "PROJECT_ARTIFACT_INVALID", "artifactRefs contain a duplicate"
            )
        return normalized

    def get_operation_result(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_id: str,
        operation_id: str,
        operation_digest: str,
    ) -> dict[str, Any] | None:
        project_id = _require_id(project_id, "projectId")
        operation_id = _require_id(operation_id, "operationId")
        operation_digest = _require_digest(operation_digest, "operationDigest")
        with self._transaction():
            record, _ = self._load(project_id)
            self._authorize(record, audience)
            for previous in record.get("operations", []):
                if previous.get("operationId") != operation_id:
                    continue
                if previous.get("operationDigest") != operation_digest:
                    raise ProjectRegistryError(
                        "PROJECT_IDEMPOTENCY_CONFLICT",
                        "operationId was already used with different input",
                    )
                return json.loads(json.dumps(previous["result"], ensure_ascii=False))
            return None

    def commit_artifact_stage(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_id: str,
        expected_project_revision: int,
        operation_id: str,
        operation_digest: str,
        task_id: str,
        artifact_stage: str,
        artifact_refs: Sequence[Mapping[str, Any]],
        artifact_handles: Sequence[str],
    ) -> dict[str, Any]:
        project_id = _require_id(project_id, "projectId")
        expected_revision = _require_revision(
            expected_project_revision, "expectedProjectRevision"
        )
        operation_id = _require_id(operation_id, "operationId")
        operation_digest = _require_digest(operation_digest, "operationDigest")
        task_id = _require_id(task_id, "taskId")
        if artifact_stage not in ARTIFACT_STAGES or artifact_stage == "empty":
            raise ProjectRegistryError(
                "PROJECT_ARTIFACT_STAGE_INVALID", "artifactStage is invalid"
            )
        refs = self._artifact_refs(artifact_refs, project_id)
        if (
            not isinstance(artifact_handles, Sequence)
            or isinstance(artifact_handles, (str, bytes))
            or len(artifact_handles) != len(refs)
            or any(
                not isinstance(handle, str)
                or not re.fullmatch(r"study_[A-Za-z0-9_-]{43}", handle)
                for handle in artifact_handles
            )
        ):
            raise ProjectRegistryError(
                "PROJECT_ARTIFACT_INVALID", "artifact handles are invalid"
            )
        handles = list(artifact_handles)
        with self._transaction():
            record, previous_raw = self._load(project_id)
            self._authorize(record, audience)
            for previous in record.get("operations", []):
                if previous.get("operationId") != operation_id:
                    continue
                if previous.get("operationDigest") != operation_digest:
                    raise ProjectRegistryError(
                        "PROJECT_IDEMPOTENCY_CONFLICT",
                        "operationId was already used with different input",
                    )
                return json.loads(json.dumps(previous["result"], ensure_ascii=False))
            project = record["project"]
            if project["projectRevision"] != expected_revision:
                raise ProjectRegistryError(
                    "PROJECT_REVISION_CONFLICT",
                    "Project revision changed before artifact commit",
                )
            if any(ref["projectRevision"] != expected_revision for ref in refs):
                raise ProjectRegistryError(
                    "PROJECT_ARTIFACT_REVISION_MISMATCH",
                    "Artifact project revision does not match the commit base",
                )
            current_stage = project["workflow"]["artifactStage"]
            current_index = ARTIFACT_STAGES.index(current_stage)
            target_index = ARTIFACT_STAGES.index(artifact_stage)
            if target_index < current_index or target_index > current_index + 1:
                raise ProjectRegistryError(
                    "PROJECT_ARTIFACT_STAGE_CONFLICT",
                    "Artifact stage cannot regress or skip a reliability stage",
                )
            unsigned = json.loads(json.dumps(record, ensure_ascii=False))
            unsigned.pop("authKeyId", None)
            unsigned.pop("authTag", None)
            updated = unsigned["project"]
            updated["projectRevision"] += 1
            updated["updatedAt"] = _now()
            by_artifact = {
                item["artifactId"]: item for item in updated["latestArtifactRefs"]
            }
            for ref in refs:
                by_artifact[ref["artifactId"]] = ref
            updated["latestArtifactRefs"] = sorted(
                by_artifact.values(), key=lambda item: item["artifactId"].encode("utf-8")
            )
            workflow = updated["workflow"]
            old_task_id = workflow.get("currentTaskId")
            if old_task_id is not None and old_task_id != task_id:
                workflow["lastAcknowledgedTaskId"] = old_task_id
                workflow["terminalOutcomeAcknowledgedAt"] = updated["updatedAt"]
            workflow.update(
                {
                    "projectRevision": updated["projectRevision"],
                    "artifactStage": artifact_stage,
                    "operationState": "succeeded",
                    "currentTaskId": task_id,
                }
            )
            workflow["productStep"], workflow["primaryActionId"] = _workflow_for_stage(
                artifact_stage
            )
            result = {
                "projectId": project_id,
                "projectRevision": updated["projectRevision"],
                "artifactStage": artifact_stage,
                "taskId": task_id,
                "artifactRefs": refs,
                "artifactHandles": handles,
            }
            if len(unsigned["operations"]) >= MAX_OPERATIONS:
                raise ProjectRegistryError(
                    "PROJECT_OPERATION_LIMIT", "Project idempotency ledger is full"
                )
            unsigned["operations"].append(
                {
                    "operationId": operation_id,
                    "operationDigest": operation_digest,
                    "result": result,
                    "recordedAt": updated["updatedAt"],
                }
            )
            _validate_persistable(updated)
            _validate_persistable(result)
            updated_record = self._authenticate(unsigned)
            raw = canonical_json_bytes(updated_record)
            self._replace(self._project_path(project_id), raw, previous_raw)
            return json.loads(json.dumps(result, ensure_ascii=False))

    @staticmethod
    def _normalize_change_set(
        operations: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        if not isinstance(operations, Sequence) or isinstance(operations, (str, bytes)):
            raise ProjectRegistryError("PROJECT_SCHEMA_INVALID", "operations must be a list")
        if not operations or len(operations) > MAX_PATCH_OPERATIONS:
            raise ProjectRegistryError("PROJECT_SCHEMA_INVALID", "operations count is invalid")
        normalized: list[dict[str, Any]] = []
        for operation in operations:
            if not isinstance(operation, Mapping):
                raise ProjectRegistryError("PROJECT_SCHEMA_INVALID", "operation must be an object")
            kind = operation.get("op")
            if kind == "set_purpose":
                _require_exact_fields(operation, {"op", "purpose"}, set(), kind)
                normalized.append({
                    "op": kind,
                    "purpose": _text(operation["purpose"], "purpose"),
                })
            elif kind == "set_target_behavior":
                _require_exact_fields(
                    operation, {"op", "targetBehavior"}, set(), kind
                )
                normalized.append({
                    "op": kind,
                    "targetBehavior": _text(
                        operation["targetBehavior"], "targetBehavior"
                    ),
                })
            elif kind == "set_learner_level":
                _require_exact_fields(operation, {"op", "learnerLevel"}, set(), kind)
                level = operation["learnerLevel"]
                normalized.append({
                    "op": kind,
                    "learnerLevel": (
                        None if level is None
                        else _text(level, "learnerLevel", maximum=200)
                    ),
                })
            elif kind == "replace_routes":
                _require_exact_fields(operation, {"op", "routes"}, set(), kind)
                normalized.append({
                    "op": kind,
                    "routes": _normalize_routes(operation["routes"]),
                })
            elif kind == "set_budget":
                _require_exact_fields(
                    operation,
                    {"op", "maxNewCards"},
                    {"targetDailyReviewMinutes"},
                    kind,
                )
                result = {
                    "op": kind,
                    "maxNewCards": _positive_integer(
                        operation["maxNewCards"], "maxNewCards", maximum=1_000
                    ),
                }
                if "targetDailyReviewMinutes" in operation:
                    result["targetDailyReviewMinutes"] = _positive_integer(
                        operation["targetDailyReviewMinutes"],
                        "targetDailyReviewMinutes",
                        maximum=1_440,
                    )
                normalized.append(result)
            elif kind == "set_languages":
                _require_exact_fields(
                    operation,
                    {"op", "promptLanguage", "answerLanguage"},
                    set(),
                    kind,
                )
                normalized.append({
                    "op": kind,
                    "promptLanguage": _text(
                        operation["promptLanguage"], "promptLanguage", maximum=64
                    ),
                    "answerLanguage": _text(
                        operation["answerLanguage"], "answerLanguage", maximum=64
                    ),
                })
            elif kind == "set_evidence_policy":
                _require_exact_fields(
                    operation, {"op", "evidencePolicy"}, set(), kind
                )
                if operation["evidencePolicy"] not in EVIDENCE_POLICIES:
                    raise ProjectRegistryError(
                        "PROJECT_SCHEMA_INVALID", "evidencePolicy is invalid"
                    )
                normalized.append({
                    "op": kind,
                    "evidencePolicy": operation["evidencePolicy"],
                })
            elif kind in {"add_exclusion", "remove_exclusion"}:
                _require_exact_fields(operation, {"op", "exclusion"}, set(), kind)
                normalized.append({
                    "op": kind,
                    "exclusion": _text(
                        operation["exclusion"], "exclusion", maximum=500
                    ),
                })
            else:
                raise ProjectRegistryError(
                    "PROJECT_SCHEMA_INVALID", "operation kind is invalid"
                )
        _validate_persistable({"operations": normalized})
        return normalized

    @staticmethod
    def _apply_changes(
        contract: dict[str, Any], operations: Sequence[Mapping[str, Any]]
    ) -> tuple[dict[str, Any], set[str]]:
        updated = json.loads(json.dumps(contract, ensure_ascii=False))
        changed_groups: set[str] = set()
        for operation in operations:
            kind = operation["op"]
            if kind == "set_purpose":
                before = updated.get("purpose")
                updated["purpose"] = operation["purpose"]
                if updated["purpose"] != before:
                    changed_groups.add("discovery")
            elif kind == "set_target_behavior":
                before = updated.get("targetBehavior")
                updated["targetBehavior"] = operation["targetBehavior"]
                if updated["targetBehavior"] != before:
                    changed_groups.add("discovery")
            elif kind == "set_learner_level":
                before = updated.get("learnerLevel")
                if operation["learnerLevel"] is None:
                    updated.pop("learnerLevel", None)
                else:
                    updated["learnerLevel"] = operation["learnerLevel"]
                if updated.get("learnerLevel") != before:
                    changed_groups.add("discovery")
            elif kind == "replace_routes":
                before = updated.get("routes")
                updated["routes"] = list(operation["routes"])
                if updated["routes"] != before:
                    changed_groups.add("discovery")
            elif kind == "set_budget":
                before = updated.get("budget")
                budget = {"maxNewCards": operation["maxNewCards"]}
                if "targetDailyReviewMinutes" in operation:
                    budget["targetDailyReviewMinutes"] = operation[
                        "targetDailyReviewMinutes"
                    ]
                updated["budget"] = budget
                if updated["budget"] != before:
                    changed_groups.add("selection")
            elif kind == "set_languages":
                before = (updated.get("promptLanguage"), updated.get("answerLanguage"))
                updated["promptLanguage"] = operation["promptLanguage"]
                updated["answerLanguage"] = operation["answerLanguage"]
                after = (updated["promptLanguage"], updated["answerLanguage"])
                if after != before:
                    changed_groups.add("planning")
            elif kind == "set_evidence_policy":
                before = updated.get("evidencePolicy")
                updated["evidencePolicy"] = operation["evidencePolicy"]
                if updated["evidencePolicy"] != before:
                    changed_groups.add("discovery")
            elif kind == "add_exclusion":
                before = list(updated["exclusions"])
                exclusions = set(updated["exclusions"])
                exclusions.add(operation["exclusion"])
                updated["exclusions"] = sorted(
                    exclusions, key=lambda value: value.encode("utf-8")
                )
                if updated["exclusions"] != before:
                    changed_groups.add("discovery")
            elif kind == "remove_exclusion":
                before = list(updated["exclusions"])
                exclusions = set(updated["exclusions"])
                exclusions.discard(operation["exclusion"])
                updated["exclusions"] = sorted(
                    exclusions, key=lambda value: value.encode("utf-8")
                )
                if updated["exclusions"] != before:
                    changed_groups.add("discovery")
        return updated, changed_groups

    @staticmethod
    def _invalidation(changed_groups: set[str]) -> tuple[list[str], str]:
        if "discovery" in changed_groups:
            return (
                ["discovery", "selection", "planning", "cards", "apkg", "anki"],
                "sources_ready",
            )
        if "selection" in changed_groups:
            return (
                ["selection", "planning", "cards", "apkg", "anki"],
                "candidates_ready",
            )
        return ["planning", "cards", "apkg", "anki"], "selection_ready"

    def update_learning_contract(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_id: str,
        expected_project_revision: int,
        expected_contract_revision: int,
        operation_id: str,
        operations: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        project_id = _require_id(project_id, "projectId")
        expected_project_revision = _require_revision(
            expected_project_revision, "expectedProjectRevision"
        )
        expected_contract_revision = _require_revision(
            expected_contract_revision, "expectedContractRevision"
        )
        operation_id = _require_id(operation_id, "operationId")
        normalized_operations = self._normalize_change_set(operations)
        operation_digest = _sha(canonical_json_bytes({
            "schema": "study.project.learning-contract-change",
            "schemaVersion": 1,
            "operationId": operation_id,
            "operations": normalized_operations,
        }))
        with self._transaction():
            record, previous_raw = self._load(project_id)
            self._authorize(record, audience)
            for previous in record.get("operations", []):
                if previous.get("operationId") != operation_id:
                    continue
                if previous.get("operationDigest") != operation_digest:
                    raise ProjectRegistryError(
                        "PROJECT_IDEMPOTENCY_CONFLICT",
                        "operationId was already used with different input",
                    )
                return json.loads(json.dumps(previous["result"], ensure_ascii=False))
            project = record["project"]
            contract = project["learningContract"]
            if project["projectRevision"] != expected_project_revision:
                raise ProjectRegistryError(
                    "PROJECT_REVISION_CONFLICT",
                    "Project revision changed before this update",
                )
            if contract["contractRevision"] != expected_contract_revision:
                raise ProjectRegistryError(
                    "CONTRACT_REVISION_CONFLICT",
                    "Learning Contract revision changed before this update",
                )
            updated_contract, changed_groups = self._apply_changes(
                contract, normalized_operations
            )
            if canonical_json_bytes(updated_contract) == canonical_json_bytes(contract):
                raise ProjectRegistryError(
                    "PROJECT_NO_CHANGE",
                    "Learning Contract update has no semantic effect",
                )
            if len(updated_contract.get("exclusions", [])) > MAX_EXCLUSIONS:
                raise ProjectRegistryError(
                    "PROJECT_SCHEMA_INVALID", "too many exclusions"
                )
            updated_contract["contractRevision"] = contract["contractRevision"] + 1
            invalidated_stages, maximum_stage = self._invalidation(changed_groups)
            unsigned = json.loads(json.dumps(record, ensure_ascii=False))
            unsigned.pop("authKeyId", None)
            unsigned.pop("authTag", None)
            updated_project = unsigned["project"]
            updated_project["projectRevision"] += 1
            updated_project["learningContract"] = updated_contract
            updated_project["learningContractDigest"] = _sha(
                canonical_json_bytes(updated_contract)
            )
            updated_project["updatedAt"] = _now()
            workflow = updated_project["workflow"]
            old_task_id = workflow.pop("currentTaskId", None)
            if old_task_id is not None:
                workflow["lastAcknowledgedTaskId"] = old_task_id
                workflow["terminalOutcomeAcknowledgedAt"] = updated_project["updatedAt"]
            workflow["projectRevision"] = updated_project["projectRevision"]
            workflow["artifactStage"] = _stage_at_most(
                workflow["artifactStage"], maximum_stage
            )
            workflow["operationState"] = "idle"
            workflow["productStep"], workflow["primaryActionId"] = (
                _workflow_for_stage(workflow["artifactStage"])
            )
            result = {
                "projectId": project_id,
                "projectRevision": updated_project["projectRevision"],
                "contractRevision": updated_contract["contractRevision"],
                "learningContractDigest": updated_project[
                    "learningContractDigest"
                ],
                "invalidatedStages": invalidated_stages,
                "preservedArtifactRefs": list(
                    updated_project["latestArtifactRefs"]
                ),
            }
            if len(unsigned["operations"]) >= MAX_OPERATIONS:
                raise ProjectRegistryError(
                    "PROJECT_OPERATION_LIMIT",
                    "Project idempotency ledger is full",
                )
            unsigned["operations"].append({
                "operationId": operation_id,
                "operationDigest": operation_digest,
                "result": result,
                "recordedAt": updated_project["updatedAt"],
            })
            _validate_persistable(updated_project)
            updated_record = self._authenticate(unsigned)
            raw = canonical_json_bytes(updated_record)
            self._replace(self._project_path(project_id), raw, previous_raw)
            return json.loads(json.dumps(result, ensure_ascii=False))
