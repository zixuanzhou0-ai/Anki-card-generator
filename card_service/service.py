from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import parse_qsl, urlsplit

from workers.acg.secret_scrub import is_runtime_secret_key, is_sensitive_url_query_key

from .anki_import_execution import (
    AnkiImportExecutionError,
    materialize_anki_worker_request,
)
from .anki_target_probe import (
    ANKI_CONNECT_URL,
    AnkiTargetProbeError,
    LocalAnkiConnectTargetProbe,
    normalize_anki_connect_url,
)
from .artifact_registry import (
    ArtifactAudienceBinding,
    ArtifactRegistryError,
    canonical_json_bytes,
)
from .authorization_ledger import AuthorizationLedger, AuthorizationLedgerError
from .broker import BrokerError
from .broker_configuration import BrokerConfigurationError, ServiceBrokerRuntime
from .candidate_discovery_broker import (
    CANDIDATE_DISCOVERY_BROKER_METHOD,
    BrokerCandidateDiscoveryModelProvider,
    CandidateDiscoveryBrokerError,
)
from .broker_ipc import BROKER_REQUEST_PREFIX, BROKER_RESPONSE_PREFIX, TaskBrokerChannel
from .credentials import (
    PROFILE_REF_PATTERN,
    CredentialBackend,
    CredentialStore,
    CredentialStoreError,
)
from .hermes_proxy import HermesProxyError, HermesProxyManager
from .local_resource_registry import (
    MAX_DEPTH,
    MAX_DIRECTORY_BYTES,
    MAX_DIRECTORY_ENTRIES,
    MAX_FILE_BYTES,
    MAX_OUTPUT_BYTES,
    MAX_OUTPUT_FILES,
)
from .network_resource_registry import (
    NetworkResourceGrantRegistry,
    NetworkResourceRegistryError,
)
from .process_isolation import ProcessIsolationError, TaskOwnedProcessGroup
from .package_artifact_runtime import PackageExportCancelled
from .runtime_manifest import (
    ManagedRuntimeManifest,
    RuntimeManifestError,
    managed_tool_runtime_entries,
    worker_runtime_entries,
)
from .runtime_package import ManagedRuntimePackage, RuntimePackageError
from .resource_runtime import ServiceResourceRuntime, ServiceResourceRuntimeError
from .service_profile_registry import (
    ServiceProfileRegistry,
    ServiceProfileRegistryError,
)
from .service_profiles import (
    ServiceProfileVerificationError,
    ServiceProfileVerificationRegistry,
)
from .profile_validation import (
    ProfileValidationPlan,
    build_profile_validation_plan,
    make_profile_validation_broker_factory,
    validate_anki_connect_profile,
)
from .provider_egress import ProviderTransport
from .study_runtime import StudyRuntime, StudyRuntimeError
from .runtime_trust import (
    RuntimePackageTrustPolicy,
    RuntimeTrustError,
    enforce_runtime_rollback_floor,
)
from .storage import AtomicJsonStore
from .trusted_surfaces import TrustedSurfaceError, TrustedSurfaceManager
from .windows_sandbox_acl import (
    WindowsSandboxAclError,
    create_task_workspace,
    harden_task_writable_path,
    harden_staged_path,
    runtime_sandbox_sid,
    task_sandbox_sid,
    verify_runtime_tree_dacl,
)


SCHEMA_VERSION = 1
PROGRESS_PREFIX = "__ANKI_CARD_PROGRESS__"
ERROR_PREFIX = "__ANKI_CARD_ERROR__"
SANDBOX_ATTESTATION_PREFIX = "__ANKI_CARD_SANDBOX_ATTESTATION__"
RESTRICTED_CHILD_EXIT_PREFIX = "__ANKI_CARD_RESTRICTED_CHILD_EXIT__"
TERMINAL_STATES = frozenset({"succeeded", "failed", "cancelled", "interrupted"})
ACTIVE_STATES = frozenset({"queued", "running", "cancelling"})
MIN_TASK_WORKSPACE_BYTES = 64 * 1024
MAX_TASK_WORKSPACE_BYTES = 8 * 1024 * 1024 * 1024
MIN_TASK_WORKSPACE_ENTRIES = 16
MAX_TASK_WORKSPACE_ENTRIES = 100_000
DEFAULT_TASK_WORKSPACE_BYTES = 2 * 1024 * 1024 * 1024
DEFAULT_TASK_WORKSPACE_ENTRIES = 20_000
MAX_TASK_WORKSPACE_SERVICE_BYTES = 64 * 1024 * 1024 * 1024
MAX_TASK_WORKSPACE_SERVICE_ENTRIES = 1_000_000
DEFAULT_TASK_WORKSPACE_SERVICE_BYTES = 8 * 1024 * 1024 * 1024
DEFAULT_TASK_WORKSPACE_SERVICE_ENTRIES = 100_000
MIN_TASK_WORKSPACE_VOLUME_RESERVE_BYTES = 64 * 1024 * 1024
MAX_TASK_WORKSPACE_VOLUME_RESERVE_BYTES = 128 * 1024 * 1024 * 1024
DEFAULT_TASK_WORKSPACE_VOLUME_RESERVE_BYTES = 4 * 1024 * 1024 * 1024
TASK_WORKSPACE_REPARSE_ATTRIBUTE = 0x400
BrokerOperationHandler = Callable[[str, dict[str, Any]], Any]
BrokerHandlerFactory = Callable[[str, str, dict[str, Any]], BrokerOperationHandler]
BrokerMethodBlocker = Callable[[str], str | None]
_RESOURCE_GRANT_REQUEST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_VALIDATION_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_DEFAULT_BROKER_RUNTIME = object()

SERVICE_OWNED_BROKER_REQUEST_KEYS = frozenset(
    {
        "profileref",
        "credentialrevision",
        "operationintentref",
        "budget",
        "reservedcostminorunits",
        "servicebindings",
        "brokerdescriptor",
        "brokerauthorization",
        "configurationfingerprint",
        "egressmanifestdigest",
    }
)


class CardServiceError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool | None = None,
        stage: str | None = None,
        fallbacks: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.stage = stage
        self.fallbacks = fallbacks


@dataclass(frozen=True)
class MethodPolicy:
    worker_command: str
    timeout_seconds: float
    cancellable: bool = True
    requires_broker: bool = False


METHOD_POLICIES: dict[str, MethodPolicy] = {
    "runtime.check_environment": MethodPolicy("check_env", 60.0),
    "runtime.test_model": MethodPolicy("test_api", 120.0, requires_broker=True),
    "runtime.test_tts": MethodPolicy("test_tts", 120.0, requires_broker=True),
    "runtime.extract_learning_points": MethodPolicy("extract_learning_points", 300.0, requires_broker=True),
    "runtime.generate_cards": MethodPolicy("generate_cards_from_learning_points", 420.0, requires_broker=True),
    "runtime.generate_legacy_project": MethodPolicy("generate", 420.0, requires_broker=True),
    "runtime.export_apkg": MethodPolicy("export", 600.0, requires_broker=True),
    "internal.export_study_apkg": MethodPolicy("export", 600.0),
    "internal.verify_study_anki_import": MethodPolicy("verify_anki_import", 120.0),
    "runtime.verify_anki_import": MethodPolicy("verify_anki_import", 120.0),
}


def _now_ms() -> int:
    return int(time.time() * 1000)


def _canonical_fingerprint(value: Any) -> str:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TaskWorkspaceUsage:
    logical_bytes: int
    entry_count: int


@dataclass(frozen=True)
class TaskWorkspaceFleetUsage:
    logical_bytes: int
    entry_count: int
    workspace_count: int
    by_task: dict[str, TaskWorkspaceUsage]


def _has_reparse_attribute(value: os.stat_result) -> bool:
    return bool(int(getattr(value, "st_file_attributes", 0)) & TASK_WORKSPACE_REPARSE_ATTRIBUTE)


def _assert_no_reparse_components(path: Path) -> os.stat_result:
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    latest: os.stat_result | None = None
    try:
        for part in absolute.parts[1:]:
            current /= part
            latest = os.lstat(current)
            if stat.S_ISLNK(latest.st_mode) or _has_reparse_attribute(latest):
                raise CardServiceError(
                    "TASK_WORKSPACE_REPARSE_BLOCKED",
                    "Task workspace paths cannot contain links or reparse points",
                    retryable=False,
                    stage="workspace",
                )
    except CardServiceError:
        raise
    except OSError as error:
        raise CardServiceError(
            "TASK_WORKSPACE_UNAVAILABLE",
            "The isolated task workspace is unavailable",
            retryable=False,
            stage="workspace",
        ) from error
    if latest is None:
        raise CardServiceError(
            "TASK_WORKSPACE_UNAVAILABLE",
            "The isolated task workspace is unavailable",
            retryable=False,
            stage="workspace",
        )
    return latest


def _task_workspace_usage(
    root: Path,
    *,
    byte_limit: int,
    entry_limit: int,
) -> TaskWorkspaceUsage:
    """Account a task tree without following links or reparse points."""

    root_stat = _assert_no_reparse_components(root)
    if not stat.S_ISDIR(root_stat.st_mode) or stat.S_ISLNK(root_stat.st_mode) or _has_reparse_attribute(root_stat):
        raise CardServiceError(
            "TASK_WORKSPACE_REPARSE_BLOCKED",
            "The isolated task workspace cannot be a link or reparse point",
            retryable=False,
            stage="workspace",
        )

    logical_bytes = 0
    entry_count = 0
    pending = [root]
    while pending:
        directory = pending.pop()
        directory_stat = _assert_no_reparse_components(directory)
        if not stat.S_ISDIR(directory_stat.st_mode):
            raise CardServiceError(
                "TASK_WORKSPACE_REPARSE_BLOCKED",
                "Task workspace directories changed during inspection",
                retryable=False,
                stage="workspace",
            )
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    try:
                        entry_stat = entry.stat(follow_symlinks=False)
                    except FileNotFoundError:
                        continue
                    except OSError as error:
                        raise CardServiceError(
                            "TASK_WORKSPACE_UNAVAILABLE",
                            "The isolated task workspace could not be inspected",
                            retryable=False,
                            stage="workspace",
                        ) from error
                    entry_count += 1
                    if entry_count > entry_limit:
                        raise CardServiceError(
                            "TASK_WORKSPACE_ENTRY_LIMIT",
                            f"Task workspace exceeded its {entry_limit} entry limit",
                            retryable=True,
                            stage="workspace",
                            fallbacks=("reduce_media_batch",),
                        )
                    if stat.S_ISLNK(entry_stat.st_mode) or _has_reparse_attribute(entry_stat):
                        raise CardServiceError(
                            "TASK_WORKSPACE_REPARSE_BLOCKED",
                            "Task workspace links and reparse points are not allowed",
                            retryable=False,
                            stage="workspace",
                        )
                    if stat.S_ISDIR(entry_stat.st_mode):
                        pending.append(Path(entry.path))
                        continue
                    if not stat.S_ISREG(entry_stat.st_mode):
                        raise CardServiceError(
                            "TASK_WORKSPACE_SPECIAL_FILE_BLOCKED",
                            "Task workspace special files are not allowed",
                            retryable=False,
                            stage="workspace",
                        )
                    try:
                        file_stat = os.stat(entry.path, follow_symlinks=False)
                    except FileNotFoundError:
                        # Exporters create and atomically replace/delete temporary
                        # files while the service performs periodic accounting. A
                        # file that vanished after DirEntry.stat no longer consumes
                        # workspace quota and is not evidence of path indirection.
                        continue
                    except OSError as error:
                        raise CardServiceError(
                            "TASK_WORKSPACE_UNAVAILABLE",
                            "The isolated task workspace changed during inspection",
                            retryable=False,
                            stage="workspace",
                        ) from error
                    if (
                        stat.S_ISLNK(file_stat.st_mode)
                        or _has_reparse_attribute(file_stat)
                        or (
                            bool(entry_stat.st_dev or entry_stat.st_ino)
                            and (
                                file_stat.st_dev != entry_stat.st_dev
                                or file_stat.st_ino != entry_stat.st_ino
                            )
                        )
                    ):
                        raise CardServiceError(
                            "TASK_WORKSPACE_REPARSE_BLOCKED",
                            "Task workspace paths changed or became reparse points during inspection",
                            retryable=False,
                            stage="workspace",
                        )
                    if int(getattr(file_stat, "st_nlink", 1)) != 1:
                        raise CardServiceError(
                            "TASK_WORKSPACE_HARDLINK_BLOCKED",
                            "Task workspace hard links are not allowed",
                            retryable=False,
                            stage="workspace",
                        )
                    logical_bytes += max(0, int(file_stat.st_size))
                    if logical_bytes > byte_limit:
                        raise CardServiceError(
                            "TASK_WORKSPACE_BYTE_LIMIT",
                            f"Task workspace exceeded its {byte_limit} byte limit",
                            retryable=True,
                            stage="workspace",
                            fallbacks=("reduce_media_batch",),
                        )
        except CardServiceError:
            raise
        except OSError as error:
            raise CardServiceError(
                "TASK_WORKSPACE_UNAVAILABLE",
                "The isolated task workspace could not be inspected",
                retryable=False,
                stage="workspace",
            ) from error
    return TaskWorkspaceUsage(logical_bytes=logical_bytes, entry_count=entry_count)


def _task_workspace_fleet_usage(
    root: Path,
    *,
    service_byte_limit: int,
    service_entry_limit: int,
) -> TaskWorkspaceFleetUsage:
    """Account all managed task workspaces without following path indirection."""

    root_stat = _assert_no_reparse_components(root)
    if not stat.S_ISDIR(root_stat.st_mode) or stat.S_ISLNK(root_stat.st_mode) or _has_reparse_attribute(root_stat):
        raise CardServiceError(
            "TASK_WORKSPACE_REPARSE_BLOCKED",
            "The task workspace root cannot be a link or reparse point",
            retryable=False,
            stage="workspace",
        )
    logical_bytes = 0
    entry_count = 0
    by_task: dict[str, TaskWorkspaceUsage] = {}
    try:
        with os.scandir(root) as entries:
            for entry in entries:
                try:
                    entry_stat = entry.stat(follow_symlinks=False)
                except FileNotFoundError:
                    continue
                except OSError as error:
                    raise CardServiceError(
                        "TASK_WORKSPACE_UNAVAILABLE",
                        "The task workspace fleet could not be inspected",
                        retryable=False,
                        stage="workspace",
                    ) from error
                if stat.S_ISLNK(entry_stat.st_mode) or _has_reparse_attribute(entry_stat):
                    raise CardServiceError(
                        "TASK_WORKSPACE_REPARSE_BLOCKED",
                        "Task workspace fleet entries cannot be links or reparse points",
                        retryable=False,
                        stage="workspace",
                    )
                if not stat.S_ISDIR(entry_stat.st_mode):
                    raise CardServiceError(
                        "TASK_WORKSPACE_UNMANAGED_ENTRY",
                        "The task workspace root contains an unmanaged entry",
                        retryable=False,
                        stage="workspace",
                    )
                try:
                    parsed_task_id = uuid.UUID(entry.name)
                except ValueError as error:
                    raise CardServiceError(
                        "TASK_WORKSPACE_UNMANAGED_ENTRY",
                        "The task workspace root contains an unmanaged directory",
                        retryable=False,
                        stage="workspace",
                    ) from error
                task_id = str(parsed_task_id)
                if task_id != entry.name.casefold() or task_id in by_task:
                    raise CardServiceError(
                        "TASK_WORKSPACE_UNMANAGED_ENTRY",
                        "The task workspace root contains a non-canonical task directory",
                        retryable=False,
                        stage="workspace",
                    )
                usage = _task_workspace_usage(
                    Path(entry.path),
                    byte_limit=service_byte_limit,
                    entry_limit=service_entry_limit,
                )
                by_task[task_id] = usage
                logical_bytes += usage.logical_bytes
                entry_count += usage.entry_count + 1
                if logical_bytes > service_byte_limit:
                    raise CardServiceError(
                        "TASK_WORKSPACE_SERVICE_LIMIT",
                        f"Retained task workspaces exceeded the {service_byte_limit} byte service limit",
                        retryable=True,
                        stage="workspace",
                        fallbacks=("release_old_tasks", "reduce_media_batch"),
                    )
                if entry_count > service_entry_limit:
                    raise CardServiceError(
                        "TASK_WORKSPACE_SERVICE_ENTRY_LIMIT",
                        f"Retained task workspaces exceeded the {service_entry_limit} entry service limit",
                        retryable=True,
                        stage="workspace",
                        fallbacks=("release_old_tasks", "reduce_media_batch"),
                    )
    except CardServiceError:
        raise
    except OSError as error:
        raise CardServiceError(
            "TASK_WORKSPACE_UNAVAILABLE",
            "The task workspace fleet could not be inspected",
            retryable=False,
            stage="workspace",
        ) from error
    return TaskWorkspaceFleetUsage(
        logical_bytes=logical_bytes,
        entry_count=entry_count,
        workspace_count=len(by_task),
        by_task=by_task,
    )


def _remove_empty_task_workspace(path: Path) -> bool:
    """Rollback only a never-launched empty workspace; never recurse over artifacts."""

    try:
        path_stat = _assert_no_reparse_components(path)
        if not stat.S_ISDIR(path_stat.st_mode):
            return False
        with os.scandir(path) as entries:
            if next(entries, None) is not None:
                return False
        os.rmdir(path)
        return True
    except (CardServiceError, OSError):
        return False


def _find_secret_path(value: Any, path: str = "$") -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if is_runtime_secret_key(key):
                return child_path
            found = _find_secret_path(child, child_path)
            if found:
                return found
        return None
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            found = _find_secret_path(child, f"{path}[{index}]")
            if found:
                return found
        return None
    if isinstance(value, str):
        try:
            parsed = urlsplit(value.strip())
        except ValueError:
            return None
        if parsed.username or parsed.password:
            return path
        if parsed.netloc:
            for key, _ in parse_qsl(parsed.query, keep_blank_values=True):
                if is_sensitive_url_query_key(key):
                    return path
    return None


def _find_service_owned_broker_path(value: Any, path: str = "$") -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            normalized = re.sub(r"[^a-z0-9]", "", str(key).casefold())
            if normalized in SERVICE_OWNED_BROKER_REQUEST_KEYS:
                return child_path
            found = _find_service_owned_broker_path(child, child_path)
            if found:
                return found
        return None
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            found = _find_service_owned_broker_path(child, f"{path}[{index}]")
            if found:
                return found
    return None


def _safe_error(message: str, limit: int = 2_000) -> str:
    value = str(message).replace("\x00", "").strip()
    value = re.sub(r"(?i)(?:[a-z]:\\|\\\\)[^\r\n\t\"<>|]+", "<local-path>", value)
    return value[:limit] or "Card Service task failed"


def _worker_failure(payload: dict[str, Any], fallback_message: str) -> CardServiceError:
    raw_code = str(payload.get("error_code") or "WORKER_FAILED")
    code = raw_code if re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", raw_code) else "WORKER_FAILED"
    raw_stage = str(payload.get("stage") or "")
    stage = raw_stage if re.fullmatch(r"[a-z][a-z0-9._-]{0,79}", raw_stage) else None
    raw_fallbacks = payload.get("fallbacks")
    fallbacks: list[str] = []
    if isinstance(raw_fallbacks, list):
        for item in raw_fallbacks[:16]:
            value = str(item)
            if re.fullmatch(r"[a-z][a-z0-9._-]{0,79}", value) and value not in fallbacks:
                fallbacks.append(value)
    raw_retryable = payload.get("retryable")
    return CardServiceError(
        code,
        _safe_error(str(payload.get("message") or fallback_message)),
        retryable=(raw_retryable if isinstance(raw_retryable, bool) else code == "WORKER_FAILED"),
        stage=stage,
        fallbacks=tuple(fallbacks),
    )


def _sid_binding_digest(domain: str, sid: str) -> str:
    return hashlib.sha256(domain.encode("ascii") + b"\x00" + sid.encode("ascii")).hexdigest()


def _verify_sandbox_attestation(
    value: Any,
    *,
    key: bytes,
    task_id: str,
    expected_filesystem_restricted: bool = False,
    expected_network_restricted: bool = False,
    expected_runtime_sid_digest: str | None = None,
    expected_task_sid_digest: str | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("sandbox attestation is not an object")
    supplied_mac = str(value.get("mac") or "")
    unsigned = {name: child for name, child in value.items() if name != "mac"}
    expected_mac = base64.urlsafe_b64encode(
        hmac.new(
            key,
            json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            hashlib.sha256,
        ).digest()
    ).decode("ascii").rstrip("=")
    required_true = (
        "restrictedPrimaryToken",
        "maxPrivilegesDisabled",
        "authenticatedUsersSidDisabled",
        "createdSuspended",
        "jobInheritedBeforeResume",
    )
    if (
        not hmac.compare_digest(supplied_mac, expected_mac)
        or value.get("schemaVersion") != 1
        or value.get("taskId") != task_id
        or any(value.get(name) is not True for name in required_true)
        or value.get("filesystemRestrictedByDedicatedSidDacl") is not expected_filesystem_restricted
        or value.get("networkRestricted") is not expected_network_restricted
    ):
        raise ValueError("sandbox attestation binding mismatch")
    if expected_filesystem_restricted and (
        value.get("runtimeAppContainerSidDigest") != expected_runtime_sid_digest
        or value.get("taskCapabilitySidDigest") != expected_task_sid_digest
        or value.get("appContainerToken") is not True
        or value.get("taskCapabilityPresent") is not True
    ):
        raise ValueError("sandbox attestation SID binding mismatch")
    public_fields = required_true + (
        "filesystemRestrictedByDedicatedSidDacl",
        "networkRestricted",
    )
    if expected_filesystem_restricted:
        public_fields += (
            "runtimeAppContainerSidDigest",
            "taskCapabilitySidDigest",
            "appContainerToken",
            "taskCapabilityPresent",
        )
    return {name: unsigned[name] for name in public_fields}


@dataclass
class _RuntimeTask:
    snapshot: dict[str, Any]
    request: dict[str, Any]
    cancel_event: threading.Event = field(default_factory=threading.Event)
    process: subprocess.Popen[str] | None = None
    process_group: TaskOwnedProcessGroup | None = None
    broker_session: TaskBrokerChannel | None = None
    sandbox_workspace: Path | None = None
    task_sandbox_sid: str | None = None
    broker_handler_factory: BrokerHandlerFactory | None = None
    broker_method_blocker: BrokerMethodBlocker | None = None
    lock: threading.RLock = field(default_factory=threading.RLock)


class CardService:
    """Restricted task API that supervises the existing one-shot Python worker."""

    def __init__(
        self,
        *,
        state_dir: str | Path,
        worker_path: str | Path | None = None,
        python_path: str | Path | None = None,
        runtime_package: str | Path | None = None,
        runtime_trust_policy: RuntimePackageTrustPolicy | str | Path | None = None,
        managed_tool_directories: list[str | Path] | None = None,
        method_policies: dict[str, MethodPolicy] | None = None,
        max_stdout_bytes: int = 64 * 1024 * 1024,
        max_stderr_bytes: int = 8 * 1024 * 1024,
        cancellation_grace_seconds: float = 2.0,
        task_memory_limit_bytes: int = 2 * 1024 * 1024 * 1024,
        task_active_process_limit: int = 16,
        task_workspace_limit_bytes: int = DEFAULT_TASK_WORKSPACE_BYTES,
        task_workspace_entry_limit: int = DEFAULT_TASK_WORKSPACE_ENTRIES,
        task_workspace_service_limit_bytes: int = DEFAULT_TASK_WORKSPACE_SERVICE_BYTES,
        task_workspace_service_entry_limit: int = DEFAULT_TASK_WORKSPACE_SERVICE_ENTRIES,
        task_workspace_volume_reserve_bytes: int = DEFAULT_TASK_WORKSPACE_VOLUME_RESERVE_BYTES,
        broker_handler_factory: BrokerHandlerFactory | None = None,
        broker_method_blocker: BrokerMethodBlocker | None = None,
        broker_runtime_capabilities: dict[str, Any] | None = None,
        broker_runtime: ServiceBrokerRuntime | None = None,
        credential_backend: CredentialBackend | None = None,
        trusted_surface_path: str | Path | None = None,
        use_restricted_launcher: bool | None = None,
        resource_gesture_verifier: Callable[[str, str, str, str], bool] | None = None,
        network_resource_resolver: Callable[..., Any] | None = None,
        anki_connect_url: str = ANKI_CONNECT_URL,
        hermes_proxy_manager: HermesProxyManager | None = None,
        profile_validation_transports: Mapping[str, ProviderTransport] | None = None,
    ) -> None:
        repository_root = Path(__file__).resolve().parent.parent
        self.runtime_package: ManagedRuntimePackage | None = None
        self.runtime_trust_policy: RuntimePackageTrustPolicy | None = None
        self.managed_media_tools: dict[str, Path] = {}
        self.runtime_sandbox_sid: str | None = None
        self.runtime_package_dacl = False
        if runtime_package is None and runtime_trust_policy is not None:
            raise CardServiceError(
                "RUNTIME_TRUST_POLICY_CONFLICT",
                "Runtime trust policy is only valid with a packaged runtime",
            )
        if runtime_package is not None and (
            resource_gesture_verifier is not None
            or network_resource_resolver is not None
        ):
            raise CardServiceError(
                "RESOURCE_GESTURE_VERIFIER_INJECTION_FORBIDDEN",
                "Packaged runtime resource trust dependencies must use production defaults",
            )

        if runtime_package is not None:
            if worker_path is not None or python_path is not None or managed_tool_directories:
                raise CardServiceError(
                    "RUNTIME_PACKAGE_CONFLICT",
                    "Packaged runtime cannot be combined with unpackaged runtime paths",
                )
            try:
                if runtime_trust_policy is None:
                    raise RuntimePackageError(
                        "RUNTIME_TRUST_POLICY_REQUIRED",
                        "A trusted publisher policy is required for packaged runtime mode",
                    )
                self.runtime_trust_policy = (
                    runtime_trust_policy
                    if isinstance(runtime_trust_policy, RuntimePackageTrustPolicy)
                    else RuntimePackageTrustPolicy.load(runtime_trust_policy)
                )
                self.runtime_package = ManagedRuntimePackage(
                    runtime_package,
                    trust_policy=self.runtime_trust_policy,
                    require_signature=True,
                )
                worker_candidate = self.runtime_package.resource_path("legacy-worker:entry")
                python_candidate = self.runtime_package.resource_path("managed-python:executable")
                self.managed_media_tools = {
                    "ACG_MANAGED_FFMPEG": self.runtime_package.resource_path("managed-tool:ffmpeg"),
                    "ACG_MANAGED_FFPROBE": self.runtime_package.resource_path("managed-tool:ffprobe"),
                    "ACG_MANAGED_YTDLP": self.runtime_package.resource_path("managed-tool:yt-dlp"),
                }
            except (RuntimePackageError, RuntimeTrustError) as error:
                raise CardServiceError(error.code, str(error)) from error
            if os.name == "nt":
                try:
                    self.runtime_sandbox_sid = runtime_sandbox_sid(self.runtime_package.package_id)
                    verify_runtime_tree_dacl(self.runtime_package.root, self.runtime_sandbox_sid)
                    self.runtime_package_dacl = True
                except WindowsSandboxAclError as error:
                    raise CardServiceError(error.code, str(error)) from error
        else:
            worker_candidate = Path(worker_path) if worker_path is not None else repository_root / "workers" / "anki_worker.py"
            python_candidate = Path(python_path) if python_path is not None else Path(sys.executable)
        if not worker_candidate.is_absolute() or not python_candidate.is_absolute():
            raise CardServiceError("RELATIVE_RUNTIME_PATH", "Managed runtime paths must be absolute")
        self.worker_path = worker_candidate.resolve()
        self.python_path = python_candidate.resolve()
        if not self.worker_path.is_absolute() or not self.worker_path.is_file():
            raise CardServiceError("WORKER_NOT_FOUND", "Managed worker path must be an existing absolute file")
        if not self.python_path.is_absolute() or not self.python_path.is_file():
            raise CardServiceError("PYTHON_NOT_FOUND", "Managed Python path must be an existing absolute file")
        directory_candidates = [Path(value) for value in (managed_tool_directories or [])]
        if any(not value.is_absolute() for value in directory_candidates):
            raise CardServiceError("INVALID_TOOL_PATH", "Managed tool directories must be existing absolute directories")
        directories = [value.resolve() for value in directory_candidates]
        if any(not value.is_dir() for value in directories):
            raise CardServiceError("INVALID_TOOL_PATH", "Managed tool directories must be existing absolute directories")
        self.managed_tool_directories = directories
        try:
            self.anki_connect_url = normalize_anki_connect_url(anki_connect_url)
        except AnkiTargetProbeError as error:
            raise CardServiceError(error.code, error.message) from error
        self.store = AtomicJsonStore(Path(state_dir))
        if self.runtime_package is not None and self.runtime_package.signature is not None:
            try:
                enforce_runtime_rollback_floor(
                    self.store.root,
                    package_version=self.runtime_package.version,
                    manifest_sha256=self.runtime_package.digest,
                    signature=self.runtime_package.signature,
                )
            except RuntimeTrustError as error:
                raise CardServiceError(error.code, str(error)) from error
        self.trusted_surfaces = TrustedSurfaceManager(
            state_dir=self.store.root / "trusted-surfaces",
            python_path=self.python_path,
            surface_path=trusted_surface_path,
            credential_backend=credential_backend,
        )
        self.method_policies = dict(method_policies or METHOD_POLICIES)
        self.max_stdout_bytes = max(1, int(max_stdout_bytes))
        self.max_stderr_bytes = max(1, int(max_stderr_bytes))
        self.cancellation_grace_seconds = max(0.1, float(cancellation_grace_seconds))
        self.task_memory_limit_bytes = max(64 * 1024 * 1024, int(task_memory_limit_bytes))
        self.task_active_process_limit = max(1, int(task_active_process_limit))
        self.task_workspace_limit_bytes = int(task_workspace_limit_bytes)
        self.task_workspace_entry_limit = int(task_workspace_entry_limit)
        self.task_workspace_service_limit_bytes = int(task_workspace_service_limit_bytes)
        self.task_workspace_service_entry_limit = int(task_workspace_service_entry_limit)
        self.task_workspace_volume_reserve_bytes = int(task_workspace_volume_reserve_bytes)
        if not MIN_TASK_WORKSPACE_BYTES <= self.task_workspace_limit_bytes <= MAX_TASK_WORKSPACE_BYTES:
            raise CardServiceError(
                "TASK_WORKSPACE_POLICY_INVALID",
                "Task workspace byte limit is outside the supported safety range",
            )
        if not MIN_TASK_WORKSPACE_ENTRIES <= self.task_workspace_entry_limit <= MAX_TASK_WORKSPACE_ENTRIES:
            raise CardServiceError(
                "TASK_WORKSPACE_POLICY_INVALID",
                "Task workspace entry limit is outside the supported safety range",
            )
        if not (
            self.task_workspace_limit_bytes
            <= self.task_workspace_service_limit_bytes
            <= MAX_TASK_WORKSPACE_SERVICE_BYTES
        ):
            raise CardServiceError(
                "TASK_WORKSPACE_POLICY_INVALID",
                "Service workspace byte limit must cover one task and remain inside the hard cap",
            )
        if not (
            self.task_workspace_entry_limit + 1
            <= self.task_workspace_service_entry_limit
            <= MAX_TASK_WORKSPACE_SERVICE_ENTRIES
        ):
            raise CardServiceError(
                "TASK_WORKSPACE_POLICY_INVALID",
                "Service workspace entry limit must cover one task and remain inside the hard cap",
            )
        if not (
            MIN_TASK_WORKSPACE_VOLUME_RESERVE_BYTES
            <= self.task_workspace_volume_reserve_bytes
            <= MAX_TASK_WORKSPACE_VOLUME_RESERVE_BYTES
        ):
            raise CardServiceError(
                "TASK_WORKSPACE_POLICY_INVALID",
                "Task workspace volume reserve is outside the supported safety range",
            )
        self.broker_handler_factory = broker_handler_factory
        self.broker_method_blocker = broker_method_blocker
        self.broker_runtime_capabilities = dict(broker_runtime_capabilities or {})
        self._credential_backend = credential_backend
        self.hermes_proxy_manager = hermes_proxy_manager or HermesProxyManager()
        self._profile_validation_transports = dict(
            profile_validation_transports or {}
        )
        self._resource_gesture_verifier = resource_gesture_verifier
        self._network_resource_resolver = network_resource_resolver
        self._resource_runtime: ServiceResourceRuntime | None = None
        self._network_resource_registry: NetworkResourceGrantRegistry | None = None
        self._study_runtime: StudyRuntime | None = None
        self._study_runtime_lock = threading.RLock()
        self._service_profile_registry: ServiceProfileRegistry | None = None
        self._service_profile_verifications: ServiceProfileVerificationRegistry | None = None
        self._service_profile_runtime_lock = threading.RLock()
        self._authorization_ledger: AuthorizationLedger | None = None
        self._authorization_ledger_lock = threading.RLock()
        self._operation_confirmation_requests: dict[
            tuple[str, str, str, str, str], str
        ] = {}
        self._operation_confirmation_lock = threading.RLock()
        self._profile_validation_lock = threading.RLock()
        self._local_settings_sessions: dict[str, tuple[str, str]] = {}
        self._local_settings_lock = threading.RLock()
        self._local_picker_requests: dict[str, dict[str, Any]] = {}
        self._completed_local_picker_grants: dict[str, dict[str, Any]] = {}
        self._local_picker_request_index: dict[tuple[str, str, str, str, str], dict[str, str]] = {}
        self._network_resource_requests: dict[str, dict[str, Any]] = {}
        self._completed_network_resource_grants: dict[str, dict[str, Any]] = {}
        self._network_resource_request_index: dict[
            tuple[str, str, str, str, str], dict[str, str]
        ] = {}
        self._resource_runtime_lock = threading.RLock()
        self._anki_import_confirmation_requests: dict[
            tuple[str, str, str, str, str], str
        ] = {}
        self._completed_anki_import_confirmations: dict[
            tuple[str, str, str, str, str], dict[str, Any]
        ] = {}
        self._anki_import_confirmation_lock = threading.RLock()
        self._authorization_manager_sessions: dict[str, dict[str, Any]] = {}
        self._completed_authorization_revocations: dict[str, dict[str, Any]] = {}
        self._authorization_manager_lock = threading.RLock()

        self._active_broker_runtime: ServiceBrokerRuntime | None = broker_runtime
        self._broker_runtime_lock = threading.RLock()
        self.use_restricted_launcher = os.name == "nt" if use_restricted_launcher is None else bool(use_restricted_launcher)
        if self.use_restricted_launcher and os.name != "nt":
            raise CardServiceError("RESTRICTED_LAUNCHER_UNAVAILABLE", "Restricted launcher is only available on Windows")
        self.worker_sha256 = self._file_sha256(self.worker_path)
        if self.runtime_package is not None:
            self.bootstrap_path = self.runtime_package.resource_path("card-service:worker-bootstrap")
            self.restricted_launcher_path = self.runtime_package.resource_path(
                "card-service:windows-restricted-launcher"
            )
            self.broker_client_path = self.runtime_package.resource_path("card-service:broker-client")
        else:
            self.bootstrap_path = (Path(__file__).resolve().parent / "worker_bootstrap.py").resolve()
            self.restricted_launcher_path = (Path(__file__).resolve().parent / "windows_restricted_launcher.py").resolve()
            self.broker_client_path = (repository_root / "workers" / "acg" / "broker_client.py").resolve()
        try:
            if self.runtime_package is not None:
                runtime_entries = self.runtime_package.runtime_entries()
            else:
                runtime_entries = worker_runtime_entries(
                    self.worker_path,
                    self.bootstrap_path,
                    self.broker_client_path,
                    self.python_path,
                    self.restricted_launcher_path if self.use_restricted_launcher else None,
                )
                runtime_entries.extend(managed_tool_runtime_entries(self.managed_tool_directories))
            self.runtime_manifest = ManagedRuntimeManifest(
                runtime_entries,
                runtime_root=self.runtime_package.root if self.runtime_package is not None else None,
            )
            self.runtime_manifest_path = (self.store.root / "runtime" / "manifest-v1.json").resolve()
            self.runtime_manifest.write(self.runtime_manifest_path)
        except RuntimeManifestError as error:
            raise CardServiceError(error.code, str(error)) from error
        self._tasks: dict[str, _RuntimeTask] = {}
        self._tasks_lock = threading.RLock()
        self._workspace_budget_lock = threading.RLock()
        self._workspace_reservations: set[str] = set()
        self._recover_orphaned_tasks()

    def _ensure_service_profile_runtime(
        self,
    ) -> tuple[ServiceProfileRegistry, ServiceProfileVerificationRegistry]:
        with self._service_profile_runtime_lock:
            if (
                self._service_profile_registry is not None
                and self._service_profile_verifications is not None
            ):
                return (
                    self._service_profile_registry,
                    self._service_profile_verifications,
                )
            try:
                credential_store = CredentialStore(
                    state_dir=self.store.root / "trusted-surfaces" / "credentials",
                    backend=self._credential_backend,
                )
                profile_registry = ServiceProfileRegistry(
                    (self.store.root / "service-profiles").resolve(),
                    authentication_key=credential_store.derive_service_key(
                        "service-profile-registry-v1",
                        context=b"codex-study-card-service",
                    ),
                    credential_store=credential_store,
                )
                verifications = ServiceProfileVerificationRegistry(
                    (self.store.root / "service-profile-verifications").resolve(),
                    authentication_key=credential_store.derive_service_key(
                        "service-profile-verification-v1",
                        context=b"codex-study-card-service",
                    ),
                    binding_resolver=profile_registry.resolve_binding,
                )
            except (
                CredentialStoreError,
                ServiceProfileRegistryError,
                ServiceProfileVerificationError,
                OSError,
            ) as error:
                raise CardServiceError(
                    getattr(error, "code", "SERVICE_PROFILE_RUNTIME_UNAVAILABLE"),
                    "Card Service profile storage is unavailable",
                    retryable=False,
                    stage="settings",
                ) from error
            self._service_profile_registry = profile_registry
            self._service_profile_verifications = verifications
            return profile_registry, verifications

    def _ensure_authorization_ledger(self) -> AuthorizationLedger:
        with self._authorization_ledger_lock:
            if self._authorization_ledger is not None:
                return self._authorization_ledger
            try:
                credential_store = CredentialStore(
                    state_dir=self.store.root / "trusted-surfaces" / "credentials",
                    backend=self._credential_backend,
                )
                ledger = AuthorizationLedger(
                    (self.store.root / "authorization-ledger").resolve(),
                    authentication_key=credential_store.derive_service_key(
                        "authorization-ledger-v1",
                        context=b"codex-study-card-service",
                    ),
                    service_instance_id=self._ensure_resource_runtime().service_instance_id,
                    gesture_attestation_verifier=(
                        self.trusted_surfaces.verify_operation_consent_gesture
                    ),
                )
            except (
                AuthorizationLedgerError,
                CredentialStoreError,
                ServiceResourceRuntimeError,
                OSError,
            ) as error:
                raise CardServiceError(
                    getattr(error, "code", "AUTHORIZATION_RUNTIME_UNAVAILABLE"),
                    "Card Service authorization storage is unavailable",
                    retryable=False,
                    stage="authorization",
                ) from error
            self._authorization_ledger = ledger
            return ledger

    def save_service_profile(
        self,
        configuration: Mapping[str, Any],
        *,
        expected_revision: int,
        operation_id: str,
    ) -> dict[str, Any]:
        """Trusted-adapter composition hook; this is intentionally not an MCP tool."""

        registry, _ = self._ensure_service_profile_runtime()
        try:
            return registry.save_profile(
                configuration,
                expected_revision=expected_revision,
                operation_id=operation_id,
            )
        except ServiceProfileRegistryError as error:
            raise CardServiceError(
                error.code,
                str(error),
                retryable=False,
                stage="settings",
            ) from error

    @staticmethod
    def _public_service_profile(
        profile: Mapping[str, Any],
        verification: Mapping[str, Any],
    ) -> dict[str, Any]:
        configuration = profile["configuration"]
        endpoint = urlsplit(str(configuration["baseUrl"]))
        result: dict[str, Any] = {
            "schemaVersion": 1,
            "profileRef": profile["profileRef"],
            "capability": profile["capability"],
            "profileRevision": profile["profileRevision"],
            "configurationFingerprint": profile["configurationFingerprint"],
            "provider": configuration["provider"],
            "endpointOrigin": f"{endpoint.scheme}://{endpoint.netloc}",
            "credentialRevision": profile["credentialRevision"],
            "credentialState": profile["credentialState"],
            "secretRequired": profile["secretRequired"],
            "secretExists": profile["secretExists"],
            "state": verification["state"],
        }
        if configuration.get("model"):
            result["model"] = configuration["model"]
        if configuration.get("voice"):
            result["voice"] = configuration["voice"]
        if configuration.get("apiVersion") is not None:
            result["apiVersion"] = configuration["apiVersion"]
        if verification.get("reasonCode") is not None:
            result["reasonCode"] = verification["reasonCode"]
        if verification.get("latestVerification") is not None:
            result["latestVerification"] = verification["latestVerification"]
        return result

    def list_service_profiles(self) -> dict[str, Any]:
        registry, verifications = self._ensure_service_profile_runtime()
        try:
            profiles = registry.list_profiles()
            return {
                "schemaVersion": 1,
                "profiles": [
                    self._public_service_profile(
                        profile,
                        verifications.profile_snapshot(
                            str(profile["capability"]),
                            str(profile["profileRef"]),
                        ),
                    )
                    for profile in profiles
                ],
            }
        except (
            ServiceProfileRegistryError,
            ServiceProfileVerificationError,
        ) as error:
            raise CardServiceError(
                error.code,
                str(error),
                retryable=False,
                stage="settings",
            ) from error

    def open_local_settings(self, *, profile_ref: str, capability: str) -> dict[str, Any]:
        if not PROFILE_REF_PATTERN.fullmatch(profile_ref):
            raise CardServiceError(
                "INVALID_PROFILE_REF",
                "Invalid local settings profile reference",
                retryable=False,
                stage="settings",
            )
        if capability not in {"model", "tts", "anki_connect"}:
            raise CardServiceError(
                "INVALID_CAPABILITY",
                "Invalid local settings capability",
                retryable=False,
                stage="settings",
            )
        registry, _ = self._ensure_service_profile_runtime()
        try:
            binding = registry.resolve_binding(capability, profile_ref)
            if binding is None:
                raise CardServiceError(
                    "SERVICE_PROFILE_NOT_CONFIGURED",
                    "The requested service profile is not configured for this capability",
                    retryable=False,
                    stage="settings",
                )
            if not binding["secretRequired"]:
                raise CardServiceError(
                    "SERVICE_PROFILE_CREDENTIAL_NOT_REQUIRED",
                    "The requested service profile does not use a local credential",
                    retryable=False,
                    stage="settings",
                )
            session = self.trusted_surfaces.create_local_settings_session(
                profile_ref=profile_ref,
                capability=capability,
            )
            launched = self.trusted_surfaces.launch(str(session["sessionRef"]))
        except ServiceProfileRegistryError as error:
            raise CardServiceError(
                error.code,
                str(error),
                retryable=False,
                stage="settings",
            ) from error
        except TrustedSurfaceError as error:
            raise CardServiceError(error.code, str(error)) from error
        configuration_session_ref = str(launched["sessionRef"])
        with self._local_settings_lock:
            self._local_settings_sessions[configuration_session_ref] = (
                capability,
                profile_ref,
            )
        return {
            "schemaVersion": 1,
            "configurationSessionRef": configuration_session_ref,
            "state": "open",
        }

    def get_local_settings(self, configuration_session_ref: str) -> dict[str, Any]:
        with self._local_settings_lock:
            binding = self._local_settings_sessions.get(configuration_session_ref)
        if binding is None:
            raise CardServiceError(
                "LOCAL_SETTINGS_SESSION_NOT_FOUND",
                "The local settings session is unavailable",
                retryable=False,
                stage="settings",
            )
        capability, profile_ref = binding
        try:
            session = self.trusted_surfaces.get_session(configuration_session_ref)
            state = str(session.get("state") or "failed")
            result: dict[str, Any] = {
                "schemaVersion": 1,
                "configurationSessionRef": configuration_session_ref,
                "state": state if state in {"open", "created", "completed", "cancelled", "failed"} else "failed",
            }
            if result["state"] == "completed":
                registry, _ = self._ensure_service_profile_runtime()
                current = registry.resolve_binding(capability, profile_ref)
                if current is None:
                    raise CardServiceError(
                        "SERVICE_PROFILE_NOT_CONFIGURED",
                        "The service profile changed while settings were open",
                        retryable=False,
                        stage="settings",
                    )
                result.update(
                    credentialRevision=current["credentialRevision"],
                    credentialState=current["credentialState"],
                    secretExists=current["secretExists"],
                )
            if result["state"] == "failed" and isinstance(session.get("errorCode"), str):
                result["errorCode"] = session["errorCode"]
            return result
        except ServiceProfileRegistryError as error:
            raise CardServiceError(
                error.code,
                str(error),
                retryable=False,
                stage="settings",
            ) from error
        except TrustedSurfaceError as error:
            raise CardServiceError(error.code, str(error)) from error

    def _resource_runtime_capabilities(self) -> dict[str, Any]:
        with self._resource_runtime_lock:
            runtime = self._resource_runtime
        if runtime is not None:
            return {**runtime.capabilities(), "initialized": True}
        return {
            "schemaVersion": 1,
            "initialized": False,
            "credentialProtectionAvailable": (
                self._credential_backend is not None or os.name == "nt"
            ),
            "trustedGrantIssuance": True,
            "taskStaging": True,
            "productionHardeningRequired": self.runtime_package is not None,
            "productionHardeningAvailable": (
                os.name == "nt" and self.runtime_package_dacl
            ),
            "workerLocatorRelativeOnly": True,
            "sourcePathDisclosure": False,
            "complete": False,
        }

    def _ensure_resource_runtime(self) -> ServiceResourceRuntime:
        with self._resource_runtime_lock:
            if self._resource_runtime is not None:
                return self._resource_runtime
            try:
                credential_store = CredentialStore(
                    state_dir=self.store.root / "trusted-surfaces" / "credentials",
                    backend=self._credential_backend,
                )
                hardener = (
                    harden_staged_path
                    if os.name == "nt" and self.runtime_package_dacl
                    else None
                )
                runtime = ServiceResourceRuntime(
                    state_dir=self.store.root / "resource-runtime",
                    credential_store=credential_store,
                    gesture_verifier=(
                        self._resource_gesture_verifier or self.trusted_surfaces.verify_resource_gesture
                    ),
                    harden_callback=hardener,
                    forbidden_roots=(self.store.root,),
                    require_hardening=self.runtime_package is not None,
                )
            except (CredentialStoreError, ServiceResourceRuntimeError, OSError) as error:
                raise CardServiceError(
                    getattr(error, "code", "RESOURCE_RUNTIME_UNAVAILABLE"),
                    "Card Service local resource runtime is unavailable",
                    retryable=False,
                    stage="resource_authorization",
                ) from error
            self._resource_runtime = runtime
            return runtime

    def initialize_local_resource_runtime(self) -> dict[str, Any]:
        """Internal trusted-adapter composition hook; it is not an MCP tool."""

        return {**self._ensure_resource_runtime().capabilities(), "initialized": True}

    def _ensure_network_resource_registry(self) -> NetworkResourceGrantRegistry:
        with self._resource_runtime_lock:
            if self._network_resource_registry is not None:
                return self._network_resource_registry
            try:
                credential_store = CredentialStore(
                    state_dir=self.store.root / "trusted-surfaces" / "credentials",
                    backend=self._credential_backend,
                )
                resource_runtime = self._ensure_resource_runtime()
                kwargs: dict[str, Any] = {}
                if self._network_resource_resolver is not None:
                    kwargs["resolver"] = self._network_resource_resolver
                registry = NetworkResourceGrantRegistry(
                    (self.store.root / "network-resource-runtime").resolve(),
                    authentication_key=credential_store.derive_service_key(
                        "network-resource-registry-v1",
                        context=b"codex-study-card-service",
                    ),
                    service_instance_id=resource_runtime.service_instance_id,
                    gesture_verifier=(
                        self._resource_gesture_verifier
                        or self.trusted_surfaces.verify_resource_gesture
                    ),
                    **kwargs,
                )
            except (
                CredentialStoreError,
                NetworkResourceRegistryError,
                ServiceResourceRuntimeError,
                OSError,
            ) as error:
                raise CardServiceError(
                    getattr(error, "code", "NETWORK_RESOURCE_RUNTIME_UNAVAILABLE"),
                    "Card Service network resource runtime is unavailable",
                    retryable=False,
                    stage="resource_authorization",
                ) from error
            self._network_resource_registry = registry
            return registry

    def _study_runtime_capabilities(self) -> dict[str, Any]:
        with self._study_runtime_lock:
            runtime = self._study_runtime
        with self._broker_runtime_lock:
            broker_runtime = self._active_broker_runtime
        discovery_authorized = (
            broker_runtime is not None
            and broker_runtime.method_blocker(CANDIDATE_DISCOVERY_BROKER_METHOD) is None
        )
        provider_status = self.hermes_proxy_manager.probe()
        if (
            discovery_authorized
            and broker_runtime is not None
            and self._candidate_discovery_uses_hermes(broker_runtime)
        ):
            discovery_authorized = provider_status["state"] == "ready"
        if runtime is not None:
            return {
                **runtime.capabilities(),
                "initialized": True,
                "candidateDiscoveryRuntime": True,
                "publicCandidateDiscovery": True,
                "publicRecoverableTaskListing": True,
                "publicCandidateDiscoveryRecovery": True,
                "candidateDiscoveryAuthorizationReady": discovery_authorized,
                "candidateDiscoveryProvider": provider_status,
            }
        return {
            "schemaVersion": 1,
            "initialized": False,
            "credentialProtectionRequired": True,
            "projectRegistry": True,
            "artifactRegistry": True,
            "publicArtifactQueries": True,
            "publicAuditQueries": True,
            "studyTaskCoordinator": True,
            "taskSourceBinding": True,
            "sourceAssetPublication": True,
            "sourceInspection": True,
            "candidateDiscoveryRuntime": True,
            "publicCandidateDiscovery": True,
            "publicRecoverableTaskListing": True,
            "publicCandidateDiscoveryRecovery": True,
            "candidateDiscoveryAuthorizationReady": discovery_authorized,
            "candidateDiscoveryProvider": provider_status,
            "publicProjectTools": True,
            "publicInputRegistration": True,
            "publicSourceInspection": True,
            "publicCandidateQueries": True,
            "publicCandidateSelection": True,
            "cardPlanRuntime": True,
            "publicCardPlanPlanning": True,
            "publicCardPlanQueries": True,
            "publicCardPlanEditing": True,
            "publicCardPlanValidation": True,
            "cardArtifactRuntime": True,
            "publicCardGeneration": True,
            "publicCardQueries": True,
            "packageArtifactRuntime": True,
            "publicApkgExport": True,
            "ankiImportPreparation": True,
            "publicAnkiImportPreparation": True,
            "ankiImportApprovalLedger": True,
            "publicAnkiImportConfirmation": True,
            "publicAnkiWrite": True,
            "pathDisclosure": False,
            "publicProjectQueries": True,
            "complete": False,
        }

    def _create_study_task_workspace(self, task_id: str) -> tuple[Path, str | None]:
        with self._workspace_budget_lock:
            root = self._sandboxes_root()
            expected = root / task_id
            if expected.exists():
                self._workspace_reservations.add(task_id)
                try:
                    self._enforce_workspace_capacity()
                    _assert_no_reparse_components(expected)
                    workspace = expected.resolve(strict=True)
                    if workspace.parent != root or not workspace.is_dir():
                        raise CardServiceError(
                            "TASK_WORKSPACE_REPARSE_BLOCKED",
                            "Recovered Study workspace escaped its root",
                        )
                    _task_workspace_usage(
                        workspace,
                        byte_limit=self.task_workspace_limit_bytes,
                        entry_limit=self.task_workspace_entry_limit,
                    )
                    sandbox_id = (
                        task_sandbox_sid(task_id) if self.runtime_package_dacl else None
                    )
                    return workspace, sandbox_id
                except Exception:
                    self._workspace_reservations.discard(task_id)
                    raise
            root = self._enforce_workspace_capacity(proposed_task_id=task_id)
            try:
                if self.runtime_package_dacl:
                    workspace, sandbox_id = create_task_workspace(root, task_id)
                else:
                    workspace = (root / task_id).resolve()
                    if workspace.parent != root:
                        raise OSError("Study task workspace escaped its root")
                    workspace.mkdir(mode=0o700, exist_ok=False)
                    sandbox_id = None
                _task_workspace_usage(
                    workspace,
                    byte_limit=self.task_workspace_limit_bytes,
                    entry_limit=self.task_workspace_entry_limit,
                )
            except WindowsSandboxAclError as error:
                _remove_empty_task_workspace(expected)
                raise CardServiceError(error.code, str(error)) from error
            except (CardServiceError, OSError):
                _remove_empty_task_workspace(expected)
                raise
            self._workspace_reservations.add(task_id)
            return workspace, sandbox_id

    def _ensure_study_runtime(self) -> StudyRuntime:
        with self._study_runtime_lock:
            if self._study_runtime is not None:
                return self._study_runtime
            try:
                credential_store = CredentialStore(
                    state_dir=self.store.root / "trusted-surfaces" / "credentials",
                    backend=self._credential_backend,
                )
                runtime = StudyRuntime(
                    state_dir=self.store.root / "study-runtime",
                    credential_store=credential_store,
                    resource_runtime=self._ensure_resource_runtime(),
                    network_resource_registry=self._ensure_network_resource_registry(),
                    workspace_factory=self._create_study_task_workspace,
                    workspace_releaser=self._release_workspace_reservation,
                    package_export_executor=self._execute_study_apkg_export,
                    anki_target_inspector=LocalAnkiConnectTargetProbe(
                        endpoint=self.anki_connect_url
                    ),
                    anki_import_executor=self._execute_study_anki_import,
                    anki_import_gesture_verifier=(
                        self.trusted_surfaces.verify_import_consent_gesture
                    ),
                )
            except (CredentialStoreError, StudyRuntimeError, OSError) as error:
                raise CardServiceError(
                    getattr(error, "code", "STUDY_RUNTIME_UNAVAILABLE"),
                    "Card Service Study runtime is unavailable",
                    retryable=False,
                    stage="request",
                ) from error
            self._study_runtime = runtime
            return runtime

    def initialize_study_runtime(self) -> dict[str, Any]:
        """Internal composition hook used by the trusted MCP project adapter."""

        return {**self._ensure_study_runtime().capabilities(), "initialized": True}

    def create_study_project(
        self,
        *,
        audience: ArtifactAudienceBinding,
        idempotency_key: str,
        learning_contract: Mapping[str, Any],
        title: str | None = None,
    ) -> dict[str, Any]:
        try:
            return self._ensure_study_runtime().create_project(
                audience=audience,
                idempotency_key=idempotency_key,
                learning_contract=learning_contract,
                title=title,
            )
        except StudyRuntimeError as error:
            raise CardServiceError(
                error.code,
                error.message,
                retryable=error.code.endswith("_CONFLICT"),
                stage="request",
            ) from error

    def get_study_project(
        self, *, audience: ArtifactAudienceBinding, project_id: str
    ) -> dict[str, Any]:
        try:
            return self._ensure_study_runtime().get_public_project(
                audience=audience, project_id=project_id
            )
        except StudyRuntimeError as error:
            raise CardServiceError(
                error.code,
                error.message,
                retryable=False,
                stage="project_query",
            ) from error

    def list_study_projects(
        self,
        *,
        audience: ArtifactAudienceBinding,
        cursor: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        try:
            return self._ensure_study_runtime().list_public_projects(
                audience=audience,
                cursor=cursor,
                limit=limit,
            )
        except StudyRuntimeError as error:
            raise CardServiceError(
                error.code,
                error.message,
                retryable=False,
                stage="project_query",
            ) from error

    @staticmethod
    def _profile_validation_state(
        profile: Mapping[str, Any], verification: Mapping[str, Any]
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schemaVersion": 1,
            "profileRef": profile["profileRef"],
            "capability": profile["capability"],
            "configurationFingerprint": profile["configurationFingerprint"],
            "credentialRevision": profile["credentialRevision"],
            "state": verification["state"],
            "nextAction": (
                "none" if verification["state"] == "ready" else "validate_profile"
            ),
        }
        if verification.get("reasonCode") is not None:
            result["reasonCode"] = verification["reasonCode"]
        if verification.get("latestVerification") is not None:
            result["verification"] = verification["latestVerification"]
        return result

    def _resolve_profile_validation_binding(
        self,
        *,
        profile_ref: str,
        capability: str,
        expected_configuration_fingerprint: str,
        credential_revision: int,
    ) -> tuple[
        dict[str, Any],
        ServiceProfileRegistry,
        ServiceProfileVerificationRegistry,
    ]:
        if capability not in {"model", "tts", "anki_connect"}:
            raise CardServiceError(
                "INVALID_CAPABILITY", "Profile validation capability is invalid"
            )
        if not PROFILE_REF_PATTERN.fullmatch(profile_ref):
            raise CardServiceError(
                "INVALID_PROFILE_REF", "Profile validation reference is invalid"
            )
        if (
            not isinstance(expected_configuration_fingerprint, str)
            or re.fullmatch(r"[0-9a-f]{64}", expected_configuration_fingerprint)
            is None
            or isinstance(credential_revision, bool)
            or not isinstance(credential_revision, int)
            or credential_revision < 0
        ):
            raise CardServiceError(
                "PROFILE_VALIDATION_BINDING_INVALID",
                "Profile validation binding is invalid",
            )
        registry, verifications = self._ensure_service_profile_runtime()
        try:
            profile = registry.get_profile(profile_ref)
        except ServiceProfileRegistryError as error:
            raise CardServiceError(
                error.code, str(error), retryable=False, stage="profile_validation"
            ) from error
        if not profile["active"] or profile["capability"] != capability:
            raise CardServiceError(
                "SERVICE_PROFILE_NOT_CONFIGURED",
                "The requested profile is not active for this capability",
                retryable=False,
                stage="profile_validation",
            )
        if (
            profile["configurationFingerprint"]
            != expected_configuration_fingerprint
            or int(profile["credentialRevision"]) != credential_revision
        ):
            raise CardServiceError(
                "PROFILE_VALIDATION_BINDING_STALE",
                "The profile configuration or credential revision changed",
                retryable=True,
                stage="profile_validation",
            )
        return profile, registry, verifications

    def _record_profile_validation_result(
        self, task_id: str
    ) -> dict[str, Any] | None:
        snapshot = self.get_task(task_id)
        if not isinstance(snapshot, Mapping):
            return None
        context = snapshot.get("profileValidation")
        if not isinstance(context, Mapping):
            return None
        existing = snapshot.get("profileValidationOutcome")
        if isinstance(existing, Mapping):
            return json.loads(json.dumps(existing, ensure_ascii=False))
        state = str(snapshot.get("state") or "")
        if state not in TERMINAL_STATES or state in {"cancelled", "interrupted"}:
            return None
        _, verifications = self._ensure_service_profile_runtime()
        status = "failed"
        error_code: str | None = "PROFILE_VALIDATION_FAILED"
        retryable: bool | None = True
        latency_ms: int | None = None
        if state == "succeeded":
            worker_result = self.read_result(task_id)
            if isinstance(worker_result, Mapping):
                raw_latency = worker_result.get("latency_ms")
                if isinstance(raw_latency, int) and not isinstance(raw_latency, bool):
                    latency_ms = max(0, min(raw_latency, 600_000))
                if worker_result.get("ok") is True:
                    status = "passed"
                    error_code = None
                    retryable = None
                else:
                    raw_code = str(
                        worker_result.get("error_code")
                        or "PROFILE_VALIDATION_FAILED"
                    )
                    error_code = (
                        raw_code
                        if re.fullmatch(r"[A-Za-z0-9._:-]{1,256}", raw_code)
                        else "PROFILE_VALIDATION_FAILED"
                    )
                    retryable = bool(worker_result.get("retryable"))
        else:
            failure = snapshot.get("error")
            if isinstance(failure, Mapping):
                raw_code = str(failure.get("code") or "PROFILE_VALIDATION_FAILED")
                error_code = (
                    raw_code
                    if re.fullmatch(r"[A-Za-z0-9._:-]{1,256}", raw_code)
                    else "PROFILE_VALIDATION_FAILED"
                )
                retryable = bool(failure.get("retryable"))
        try:
            record = verifications.record_result(
                operation_id=f"profile-validation-result:{task_id}",
                capability=str(context["capability"]),
                profile_ref=str(context["profileRef"]),
                configuration_fingerprint=str(
                    context["configurationFingerprint"]
                ),
                credential_revision=int(context["credentialRevision"]),
                status=status,
                error_code=error_code,
                retryable=retryable,
                latency_ms=latency_ms,
            )
        except ServiceProfileVerificationError as error:
            raise CardServiceError(
                error.code,
                str(error),
                retryable=False,
                stage="profile_validation",
            ) from error
        outcome = {
            "schemaVersion": 1,
            "status": status,
            "verification": record,
        }
        with self._tasks_lock:
            runtime = self._tasks.get(task_id)
        if runtime is not None:
            with runtime.lock:
                runtime.snapshot["profileValidationOutcome"] = outcome
                self._persist_runtime(runtime)
        else:
            persisted = dict(snapshot)
            persisted["profileValidationOutcome"] = outcome
            self.store.write_task(task_id, persisted)
        return json.loads(json.dumps(outcome, ensure_ascii=False))

    def _watch_profile_validation(self, task_id: str) -> None:
        def watch() -> None:
            while True:
                snapshot = self.get_task(task_id)
                if not isinstance(snapshot, Mapping):
                    return
                if snapshot.get("state") in TERMINAL_STATES:
                    try:
                        self._record_profile_validation_result(task_id)
                    except CardServiceError:
                        pass
                    return
                time.sleep(0.1)

        threading.Thread(
            target=watch,
            daemon=True,
            name=f"profile-validation-{task_id}",
        ).start()

    def _public_profile_validation_task(
        self, *, audience: ArtifactAudienceBinding, task_id: str
    ) -> dict[str, Any]:
        snapshot = self.get_task(task_id)
        if not isinstance(snapshot, Mapping) or not isinstance(
            snapshot.get("profileValidation"), Mapping
        ):
            raise CardServiceError(
                "TASK_NOT_FOUND", "Profile validation task was not found"
            )
        context = snapshot["profileValidation"]
        try:
            self._ensure_authorization_ledger().get_operation_intent(
                str(context["operationIntentId"]), audience
            )
        except AuthorizationLedgerError as error:
            raise CardServiceError(
                error.code, str(error), retryable=False, stage="task"
            ) from error
        if snapshot.get("state") in TERMINAL_STATES:
            self._record_profile_validation_result(task_id)
            snapshot = self.get_task(task_id) or snapshot
        state = str(snapshot.get("state") or "failed")
        public: dict[str, Any] = {
            "schemaVersion": 1,
            "taskId": task_id,
            "intent": "validate_profile",
            "state": state,
            "cancellable": bool(snapshot.get("cancellable")),
            "resumability": "none",
            "progress": json.loads(
                json.dumps(snapshot.get("progress") or {}, ensure_ascii=False)
            ),
            "nextAction": (
                "get_task"
                if state in ACTIVE_STATES
                else "none"
                if state == "succeeded"
                else "validate_profile"
            ),
        }
        outcome = snapshot.get("profileValidationOutcome")
        if isinstance(outcome, Mapping):
            public["result"] = json.loads(json.dumps(outcome, ensure_ascii=False))
        failure = snapshot.get("error")
        if isinstance(failure, Mapping):
            public["error"] = json.loads(json.dumps(failure, ensure_ascii=False))
        return public

    def validate_service_profile(
        self,
        *,
        audience: ArtifactAudienceBinding,
        profile_ref: str,
        capability: str,
        expected_configuration_fingerprint: str,
        credential_revision: int,
        idempotency_key: str,
        configuration_session_ref: str | None = None,
    ) -> dict[str, Any]:
        if not _VALIDATION_IDEMPOTENCY_RE.fullmatch(idempotency_key):
            raise CardServiceError(
                "PROFILE_VALIDATION_IDEMPOTENCY_INVALID",
                "Profile validation idempotency key is invalid",
            )
        if configuration_session_ref is not None:
            raise CardServiceError(
                "PROFILE_DRAFT_VALIDATION_UNAVAILABLE",
                "Unsaved profile draft validation is not available yet",
                retryable=False,
                stage="profile_validation",
            )
        profile, _, verifications = self._resolve_profile_validation_binding(
            profile_ref=profile_ref,
            capability=capability,
            expected_configuration_fingerprint=expected_configuration_fingerprint,
            credential_revision=credential_revision,
        )
        verification = verifications.profile_snapshot(capability, profile_ref)
        if verification["state"] == "ready":
            return self._profile_validation_state(profile, verification)
        if profile["credentialState"] != "committed":
            return self._profile_validation_state(profile, verification)
        if profile["secretRequired"] and not profile["secretExists"]:
            return self._profile_validation_state(profile, verification)
        if capability == "anki_connect":
            started = time.monotonic()
            try:
                credential_store = CredentialStore(
                    state_dir=self.store.root / "trusted-surfaces" / "credentials",
                    backend=self._credential_backend,
                )
                result = validate_anki_connect_profile(
                    profile, credential_store=credential_store
                )
                record = verifications.record_result(
                    operation_id=f"anki-profile-validation:{idempotency_key}",
                    capability=capability,
                    profile_ref=profile_ref,
                    configuration_fingerprint=expected_configuration_fingerprint,
                    credential_revision=credential_revision,
                    status="passed",
                    latency_ms=int(result["latencyMs"]),
                )
            except (CredentialStoreError, RuntimeError) as error:
                code = str(error) if str(error).startswith("ANKI_") else "ANKI_OFFLINE"
                record = verifications.record_result(
                    operation_id=f"anki-profile-validation:{idempotency_key}",
                    capability=capability,
                    profile_ref=profile_ref,
                    configuration_fingerprint=expected_configuration_fingerprint,
                    credential_revision=credential_revision,
                    status="failed",
                    error_code=code,
                    retryable=code == "ANKI_OFFLINE",
                    latency_ms=max(0, int((time.monotonic() - started) * 1000)),
                )
            current = verifications.profile_snapshot(capability, profile_ref)
            return {
                **self._profile_validation_state(profile, current),
                "verification": record,
            }
        plan = build_profile_validation_plan(
            profile, configuration_session_ref=configuration_session_ref
        )
        ledger = self._ensure_authorization_ledger()
        try:
            intent = ledger.find_operation_intent(
                audience=audience, idempotency_key=idempotency_key
            )
            if intent is None:
                intent = ledger.create_operation_intent(
                    audience=audience,
                    idempotency_key=idempotency_key,
                    operation_request_manifest=plan.operation_request_manifest,
                    disclosure_manifest=plan.disclosure_manifest,
                    cost_budget=plan.cost_budget,
                )
            else:
                if (
                    intent["subject"]
                    != plan.operation_request_manifest["subject"]
                    or intent["serviceBindings"]
                    != plan.operation_request_manifest["serviceBindings"]
                ):
                    raise CardServiceError(
                        "PROFILE_VALIDATION_IDEMPOTENCY_CONFLICT",
                        "Profile validation idempotency key targets another binding",
                    )
        except AuthorizationLedgerError as error:
            raise CardServiceError(
                error.code,
                str(error),
                retryable=False,
                stage="authorization",
            ) from error
        public = {
            "schemaVersion": 1,
            "profileRef": profile_ref,
            "capability": capability,
            "configurationFingerprint": expected_configuration_fingerprint,
            "credentialRevision": credential_revision,
            "operationIntentId": intent["operationIntentId"],
            "intentDigest": intent["intentDigest"],
        }
        intent_state = str(intent["state"])
        if intent_state == "pending":
            return {
                **public,
                "state": "confirmation_required",
                "nextAction": "request_operation_confirmation",
            }
        if intent_state in {"declined", "expired", "revoked"}:
            return {
                **public,
                "state": intent_state,
                "nextAction": "validate_profile",
            }
        if intent_state not in {"approved", "consumed"}:
            raise CardServiceError(
                "OPERATION_APPROVAL_STATE_INVALID",
                "Profile validation approval state cannot start a task",
            )
        return self._start_remote_profile_validation(
            audience=audience,
            profile=profile,
            profile_ref=profile_ref,
            capability=capability,
            expected_configuration_fingerprint=expected_configuration_fingerprint,
            credential_revision=credential_revision,
            intent=intent,
            plan=plan,
            ledger=ledger,
        )

    def _start_remote_profile_validation(
        self,
        *,
        audience: ArtifactAudienceBinding,
        profile: Mapping[str, Any],
        profile_ref: str,
        capability: str,
        expected_configuration_fingerprint: str,
        credential_revision: int,
        intent: Mapping[str, Any],
        plan: ProfileValidationPlan,
        ledger: AuthorizationLedger,
    ) -> dict[str, Any]:
        task_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"codex-study:profile-validation:{intent['operationIntentId']}",
            )
        )
        with self._profile_validation_lock:
            existing_task = self.get_task(task_id)
            if existing_task is not None:
                return self._public_profile_validation_task(
                    audience=audience, task_id=task_id
                )
            if profile["configuration"]["provider"] == "hermes":
                self.ensure_candidate_discovery_provider()
            try:
                approval = ledger.consume_operation_approval(
                    operation_intent_id=str(intent["operationIntentId"]),
                    audience=audience,
                    task_id=task_id,
                    consumption_id=f"profile-validation:{task_id}",
                    expected_intent_digest=str(intent["intentDigest"]),
                    expected_operation_request_digest=str(
                        intent["operationRequestManifestDigest"]
                    ),
                    current_service_bindings=[plan.current_service_binding],
                )
                broker_factory = make_profile_validation_broker_factory(
                    state_dir=self.store.root,
                    credential_backend=self._credential_backend,
                    authorization_ledger=ledger,
                    audience=audience,
                    operation_intent_id=str(intent["operationIntentId"]),
                    authorization_expires_at=str(intent["expiresAt"]),
                    plan=plan,
                    approval_consumption=approval,
                    transport=self._profile_validation_transports.get(profile_ref),
                )
                started_task = self.start_task(
                    plan.worker_method,
                    dict(plan.worker_request),
                    task_id_override=task_id,
                    broker_handler_factory_override=broker_factory,
                    broker_method_blocker_override=lambda _method: None,
                    snapshot_extra={
                        "profileValidation": {
                            "schemaVersion": 1,
                            "operationIntentId": intent["operationIntentId"],
                            "capability": capability,
                            "profileRef": profile_ref,
                            "configurationFingerprint": expected_configuration_fingerprint,
                            "credentialRevision": credential_revision,
                        }
                    },
                )
            except (
                AuthorizationLedgerError,
                BrokerError,
                CredentialStoreError,
            ) as error:
                raise CardServiceError(
                    getattr(error, "code", "PROFILE_VALIDATION_START_FAILED"),
                    "Profile validation authorization could not start",
                    retryable=True,
                    stage="profile_validation",
                ) from error
            self._watch_profile_validation(str(started_task["id"]))
            return self._public_profile_validation_task(
                audience=audience, task_id=str(started_task["id"])
            )

    def request_operation_confirmation(
        self,
        *,
        audience: ArtifactAudienceBinding,
        operation_intent_id: str,
    ) -> dict[str, Any]:
        ledger = self._ensure_authorization_ledger()
        try:
            intent = ledger.get_operation_intent_context(
                operation_intent_id, audience
            )
        except AuthorizationLedgerError as error:
            raise CardServiceError(
                error.code, str(error), retryable=False, stage="authorization"
            ) from error
        state = str(intent["state"])
        if state != "pending":
            return {
                "schemaVersion": 1,
                "operationIntentId": operation_intent_id,
                "actionId": intent["actionId"],
                "state": state,
                "expiresAt": intent["expiresAt"],
            }
        subject = intent["subject"]
        if subject.get("kind") != "profile_validation":
            raise CardServiceError(
                "OPERATION_CONFIRMATION_UNSUPPORTED",
                "This operation intent is not supported by the current trusted surface",
            )
        profile, _, _ = self._resolve_profile_validation_binding(
            profile_ref=str(subject["profileRef"]),
            capability=str(intent["serviceBindings"][0]["capability"]),
            expected_configuration_fingerprint=str(
                subject["configurationFingerprint"]
            ),
            credential_revision=int(subject["credentialRevision"]),
        )
        plan = build_profile_validation_plan(profile)
        try:
            audience_digest = ledger.audience_digest(audience)
        except AuthorizationLedgerError as error:
            raise CardServiceError(
                error.code, str(error), retryable=False, stage="authorization"
            ) from error
        key = (
            audience.owner_digest,
            audience.host_id,
            audience.plugin_id,
            audience.session_id,
            operation_intent_id,
        )
        with self._operation_confirmation_lock:
            session_ref = self._operation_confirmation_requests.get(key)
            if session_ref is None:
                try:
                    session = self.trusted_surfaces.create_operation_consent_session(
                        operation_intent_id=operation_intent_id,
                        audience_digest=audience_digest,
                        intent_digest=str(intent["intentDigest"]),
                        action_id=str(intent["actionId"]),
                        summary=plan.consent_summary,
                    )
                    session_ref = str(session["sessionRef"])
                    self._operation_confirmation_requests[key] = session_ref
                    self.trusted_surfaces.launch(session_ref)
                except TrustedSurfaceError as error:
                    self._operation_confirmation_requests.pop(key, None)
                    raise CardServiceError(
                        error.code,
                        str(error),
                        retryable=True,
                        stage="authorization",
                    ) from error
                return {
                    "schemaVersion": 1,
                    "operationIntentId": operation_intent_id,
                    "actionId": intent["actionId"],
                    "state": "open",
                    "expiresAt": intent["expiresAt"],
                }
        try:
            surface = self.trusted_surfaces.get_session(session_ref)
            surface_state = str(surface.get("state") or "failed")
            if surface_state in {"created", "open"}:
                return {
                    "schemaVersion": 1,
                    "operationIntentId": operation_intent_id,
                    "actionId": intent["actionId"],
                    "state": "open",
                    "expiresAt": intent["expiresAt"],
                }
            if surface_state in {"approved", "declined"}:
                decision = self.trusted_surfaces.operation_consent_decision(
                    session_ref
                )
                if decision is None:
                    raise CardServiceError(
                        "TRUSTED_GESTURE_INVALID",
                        "Trusted operation decision is unavailable",
                    )
                decided = ledger.record_operation_decision(
                    operation_intent_id=operation_intent_id,
                    audience=audience,
                    decision=decision.decision,
                    gesture_attestation_digest=decision.attestation_digest,
                )
                self.trusted_surfaces.complete_operation_consent(session_ref)
                with self._operation_confirmation_lock:
                    self._operation_confirmation_requests.pop(key, None)
                return {
                    "schemaVersion": 1,
                    "operationIntentId": operation_intent_id,
                    "actionId": decided["actionId"],
                    "state": decided["state"],
                    "expiresAt": decided["expiresAt"],
                }
            self.trusted_surfaces.complete_operation_consent(session_ref)
            with self._operation_confirmation_lock:
                self._operation_confirmation_requests.pop(key, None)
            return {
                "schemaVersion": 1,
                "operationIntentId": operation_intent_id,
                "actionId": intent["actionId"],
                "state": (
                    surface_state
                    if surface_state in {"cancelled", "failed"}
                    else "failed"
                ),
                "expiresAt": intent["expiresAt"],
            }
        except (TrustedSurfaceError, AuthorizationLedgerError) as error:
            raise CardServiceError(
                getattr(error, "code", "OPERATION_CONFIRMATION_FAILED"),
                "Trusted operation confirmation failed",
                retryable=True,
                stage="authorization",
            ) from error

    def get_study_artifact(
        self, *, audience: ArtifactAudienceBinding, artifact_handle: str
    ) -> dict[str, Any]:
        try:
            return self._ensure_study_runtime().get_public_artifact(
                audience=audience, artifact_handle=artifact_handle
            )
        except StudyRuntimeError as error:
            raise CardServiceError(
                error.code,
                error.message,
                retryable=False,
                stage="artifact_query",
            ) from error

    def get_study_audit(
        self, *, audience: ArtifactAudienceBinding, artifact_handle: str
    ) -> dict[str, Any]:
        try:
            return self._ensure_study_runtime().get_public_audit(
                audience=audience, artifact_handle=artifact_handle
            )
        except StudyRuntimeError as error:
            raise CardServiceError(
                error.code,
                error.message,
                retryable=False,
                stage="artifact_query",
            ) from error

    def register_study_inputs(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_id: str,
        expected_project_revision: int,
        idempotency_key: str,
        input_refs: list[Mapping[str, Any]],
        snapshot_policy: str = "require_stable",
    ) -> dict[str, Any]:
        try:
            return self._ensure_study_runtime().register_inputs(
                audience=audience,
                project_id=project_id,
                expected_project_revision=expected_project_revision,
                idempotency_key=idempotency_key,
                input_refs=input_refs,
                snapshot_policy=snapshot_policy,
            )
        except StudyRuntimeError as error:
            raise CardServiceError(
                error.code,
                error.message,
                retryable=error.code.endswith(("_CONFLICT", "_UNAVAILABLE", "_REQUIRED")),
                stage="source_registration",
            ) from error

    def inspect_study_sources(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_id: str,
        expected_project_revision: int,
        idempotency_key: str,
        source_handles: list[str],
    ) -> dict[str, Any]:
        try:
            return self._ensure_study_runtime().start_source_inspection(
                audience=audience,
                project_id=project_id,
                expected_project_revision=expected_project_revision,
                idempotency_key=idempotency_key,
                source_handles=source_handles,
            )
        except StudyRuntimeError as error:
            raise CardServiceError(
                error.code,
                error.message,
                retryable=error.code.endswith(("_CONFLICT", "_UNAVAILABLE", "_REQUIRED")),
                stage="source_inspection",
            ) from error

    def get_study_source_inspection(
        self,
        *,
        audience: ArtifactAudienceBinding,
        inspection_handle: str,
    ) -> dict[str, Any]:
        try:
            return self._ensure_study_runtime().get_source_inspection(
                audience=audience,
                inspection_handle=inspection_handle,
            )
        except StudyRuntimeError as error:
            raise CardServiceError(
                error.code,
                error.message,
                retryable=False,
                stage="source_inspection",
            ) from error

    def plan_study_cards(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_id: str,
        expected_project_revision: int,
        idempotency_key: str,
        selection_handle: str,
    ) -> dict[str, Any]:
        try:
            return self._ensure_study_runtime().plan_cards(
                audience=audience,
                project_id=project_id,
                expected_project_revision=expected_project_revision,
                idempotency_key=idempotency_key,
                selection_handle=selection_handle,
                maximum_plans=100,
            )
        except StudyRuntimeError as error:
            raise CardServiceError(
                error.code,
                error.message,
                retryable=False,
                stage="planning",
            ) from error

    def list_study_generated_cards(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_artifact_handle: str,
        cursor: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        try:
            return self._ensure_study_runtime().list_generated_cards(
                audience=audience,
                project_artifact_handle=project_artifact_handle,
                cursor=cursor,
                limit=limit,
            )
        except StudyRuntimeError as error:
            raise CardServiceError(
                error.code,
                error.message,
                retryable=False,
                stage="card_query",
            ) from error

    def generate_study_cards(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_id: str,
        expected_project_revision: int,
        idempotency_key: str,
        plan_set_handle: str,
    ) -> dict[str, Any]:
        try:
            return self._ensure_study_runtime().generate_cards(
                audience=audience,
                project_id=project_id,
                expected_project_revision=expected_project_revision,
                idempotency_key=idempotency_key,
                plan_set_handle=plan_set_handle,
            )
        except StudyRuntimeError as error:
            raise CardServiceError(
                error.code,
                error.message,
                retryable=False,
                stage="card_generation",
            ) from error

    def start_study_apkg_export(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_id: str,
        expected_project_revision: int,
        idempotency_key: str,
        project_artifact_handle: str,
        output_ref: Mapping[str, Any],
    ) -> dict[str, Any]:
        try:
            return self._ensure_study_runtime().start_apkg_export(
                audience=audience,
                project_id=project_id,
                expected_project_revision=expected_project_revision,
                idempotency_key=idempotency_key,
                project_artifact_handle=project_artifact_handle,
                output_ref=output_ref,
            )
        except StudyRuntimeError as error:
            raise CardServiceError(
                error.code,
                error.message,
                retryable=error.code.endswith(
                    ("_CONFLICT", "_UNAVAILABLE", "_REQUIRED", "_WRITABLE")
                ),
                stage="export",
            ) from error

    def prepare_study_anki_import(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_id: str,
        expected_project_revision: int,
        idempotency_key: str,
        package_artifact_handle: str,
    ) -> dict[str, Any]:
        try:
            return self._ensure_study_runtime().prepare_anki_import(
                audience=audience,
                project_id=project_id,
                expected_project_revision=expected_project_revision,
                idempotency_key=idempotency_key,
                package_artifact_handle=package_artifact_handle,
            )
        except StudyRuntimeError as error:
            raise CardServiceError(
                error.code,
                error.message,
                retryable=error.code in {"ANKI_OFFLINE", "ANKI_TARGET_INVALID"},
                stage="anki_prepare",
                fallbacks=("open_anki",) if error.code == "ANKI_OFFLINE" else (),
            ) from error

    def start_study_anki_import(
        self,
        *,
        audience: ArtifactAudienceBinding,
        import_intent_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        try:
            return self._ensure_study_runtime().start_anki_import(
                audience=audience,
                import_intent_id=import_intent_id,
                idempotency_key=idempotency_key,
            )
        except StudyRuntimeError as error:
            raise CardServiceError(
                error.code,
                error.message,
                retryable=False,
                stage="anki_import",
                fallbacks=(
                    ("confirm_anki_import",)
                    if error.code.endswith(("_REQUIRED", "_EXPIRED"))
                    else ()
                ),
            ) from error
    @staticmethod
    def _anki_import_confirmation_key(
        audience: ArtifactAudienceBinding, import_intent_id: str
    ) -> tuple[str, str, str, str, str]:
        return (
            audience.owner_digest,
            audience.host_id,
            audience.plugin_id,
            audience.session_id,
            import_intent_id,
        )

    def request_study_anki_import_confirmation(
        self,
        *,
        audience: ArtifactAudienceBinding,
        import_intent_id: str,
    ) -> dict[str, Any]:
        """Begin or poll a model-external trusted Anki import confirmation."""

        runtime = self._ensure_study_runtime()
        try:
            approval = runtime.get_anki_import_approval(
                audience=audience, import_intent_id=import_intent_id
            )
            if approval["approvalState"] in {
                "approved",
                "declined",
                "expired",
                "revoked",
                "consumed",
            }:
                return approval
            key = self._anki_import_confirmation_key(audience, import_intent_id)
            with self._anki_import_confirmation_lock:
                completed = self._completed_anki_import_confirmations.get(key)
                if completed is not None:
                    return json.loads(json.dumps(completed, ensure_ascii=False))
                session_ref = self._anki_import_confirmation_requests.get(key)
                if session_ref is None:
                    context = runtime.get_anki_import_confirmation_context(
                        audience=audience, import_intent_id=import_intent_id
                    )
                    session = self.trusted_surfaces.create_anki_import_consent_session(
                        import_intent_id=import_intent_id,
                        audience_digest=str(context["audienceDigest"]),
                        import_plan_digest=str(context["importPlanDigest"]),
                        summary=str(context["summary"]),
                    )
                    session_ref = str(session["sessionRef"])
                    self.trusted_surfaces.launch(session_ref)
                    self._anki_import_confirmation_requests[key] = session_ref
                    return approval
                surface = self.trusted_surfaces.get_session(session_ref)
                state = str(surface.get("state") or "")
                if state in {"created", "open"}:
                    return approval
                if state in {"approved", "declined"}:
                    decision = self.trusted_surfaces.import_consent_decision(
                        session_ref
                    )
                    if (
                        decision is None
                        or decision.import_intent_id != import_intent_id
                        or decision.decision != state
                    ):
                        raise CardServiceError(
                            "IMPORT_CONSENT_STATE_INVALID",
                            "Trusted Anki consent decision is unavailable",
                            stage="anki_confirmation",
                        )
                    finalized = runtime.record_anki_import_decision(
                        audience=audience,
                        import_intent_id=import_intent_id,
                        decision=decision.decision,
                        gesture_attestation_ref=decision.attestation_ref,
                    )
                    self.trusted_surfaces.complete_import_consent(session_ref)
                    self._anki_import_confirmation_requests.pop(key, None)
                    self._completed_anki_import_confirmations[key] = finalized
                    return json.loads(json.dumps(finalized, ensure_ascii=False))
                if state == "cancelled":
                    self.trusted_surfaces.complete_import_consent(session_ref)
                    self._anki_import_confirmation_requests.pop(key, None)
                    return {**approval, "approvalState": "cancelled"}
                raise CardServiceError(
                    str(surface.get("errorCode") or "IMPORT_CONSENT_FAILED"),
                    "Trusted Anki import confirmation failed",
                    retryable=True,
                    stage="anki_confirmation",
                )
        except TrustedSurfaceError as error:
            raise CardServiceError(
                error.code,
                str(error),
                retryable=error.code.endswith(("_UNAVAILABLE", "_FAILED")),
                stage="anki_confirmation",
            ) from error
        except StudyRuntimeError as error:
            raise CardServiceError(
                error.code,
                error.message,
                retryable=error.code.endswith(("_UNAVAILABLE", "_EXPIRED")),
                stage="anki_confirmation",
            ) from error

    def get_public_study_task(
        self, *, audience: ArtifactAudienceBinding, task_id: str
    ) -> dict[str, Any]:
        legacy = self.get_task(task_id)
        if isinstance(legacy, Mapping) and isinstance(
            legacy.get("profileValidation"), Mapping
        ):
            return self._public_profile_validation_task(
                audience=audience, task_id=task_id
            )
        try:
            return self._ensure_study_runtime().get_study_task(
                audience=audience, task_id=task_id
            )
        except StudyRuntimeError as error:
            raise CardServiceError(
                error.code,
                error.message,
                retryable=error.code.endswith(("_UNAVAILABLE", "_REQUIRED")),
                stage="task",
            ) from error

    def cancel_public_study_task(
        self, *, audience: ArtifactAudienceBinding, task_id: str
    ) -> dict[str, Any]:
        legacy = self.get_task(task_id)
        if isinstance(legacy, Mapping) and isinstance(
            legacy.get("profileValidation"), Mapping
        ):
            self._public_profile_validation_task(
                audience=audience, task_id=task_id
            )
            self.cancel_task(task_id)
            return self._public_profile_validation_task(
                audience=audience, task_id=task_id
            )
        try:
            return self._ensure_study_runtime().cancel_study_task(
                audience=audience, task_id=task_id
            )
        except StudyRuntimeError as error:
            raise CardServiceError(
                error.code,
                error.message,
                retryable=False,
                stage="cancellation",
            ) from error

    def list_public_recoverable_study_tasks(
        self, *, audience: ArtifactAudienceBinding, limit: int = 20
    ) -> dict[str, Any]:
        try:
            return self._ensure_study_runtime().list_recoverable_study_tasks(
                audience=audience, limit=limit
            )
        except StudyRuntimeError as error:
            raise CardServiceError(
                error.code,
                error.message,
                retryable=False,
                stage="recovery",
            ) from error

    def list_study_card_plans(
        self,
        *,
        audience: ArtifactAudienceBinding,
        plan_set_handle: str,
        cursor: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        try:
            return self._ensure_study_runtime().list_card_plans(
                audience=audience,
                plan_set_handle=plan_set_handle,
                cursor=cursor,
                limit=limit,
            )
        except StudyRuntimeError as error:
            raise CardServiceError(
                error.code,
                error.message,
                retryable=False,
                stage="card_plan_query",
            ) from error

    def edit_study_card_plan(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_id: str,
        expected_project_revision: int,
        idempotency_key: str,
        plan_set_handle: str,
        card_plan_handle: str,
        operation: Mapping[str, Any],
    ) -> dict[str, Any]:
        try:
            return self._ensure_study_runtime().edit_card_plan(
                audience=audience,
                project_id=project_id,
                expected_project_revision=expected_project_revision,
                idempotency_key=idempotency_key,
                plan_set_handle=plan_set_handle,
                card_plan_handle=card_plan_handle,
                operation=operation,
            )
        except StudyRuntimeError as error:
            raise CardServiceError(
                error.code,
                error.message,
                retryable=False,
                stage="card_plan_edit",
            ) from error

    def validate_study_card_plans(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_id: str,
        expected_project_revision: int,
        idempotency_key: str,
        plan_set_handle: str,
    ) -> dict[str, Any]:
        try:
            return self._ensure_study_runtime().validate_card_plans(
                audience=audience,
                project_id=project_id,
                expected_project_revision=expected_project_revision,
                idempotency_key=idempotency_key,
                plan_set_handle=plan_set_handle,
            )
        except StudyRuntimeError as error:
            raise CardServiceError(
                error.code,
                error.message,
                retryable=False,
                stage="card_plan_validation",
            ) from error

    def set_study_selection(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_id: str,
        expected_project_revision: int,
        idempotency_key: str,
        discovery_handle: str,
        operation: str,
        candidate_handles: Sequence[str] | None = None,
        budget: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            return self._ensure_study_runtime().set_selection(
                audience=audience,
                project_id=project_id,
                expected_project_revision=expected_project_revision,
                idempotency_key=idempotency_key,
                discovery_handle=discovery_handle,
                operation=operation,
                candidate_handles=candidate_handles,
                budget=budget,
            )
        except StudyRuntimeError as error:
            raise CardServiceError(
                error.code,
                error.message,
                retryable=False,
                stage="selection",
            ) from error

    def list_study_candidates(
        self,
        *,
        audience: ArtifactAudienceBinding,
        discovery_handle: str,
        filters: Mapping[str, Any] | None = None,
        sort: str = "recommended",
        cursor: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        try:
            return self._ensure_study_runtime().list_candidates(
                audience=audience,
                discovery_handle=discovery_handle,
                filters=filters,
                sort=sort,
                cursor=cursor,
                limit=limit,
            )
        except StudyRuntimeError as error:
            raise CardServiceError(
                error.code,
                error.message,
                retryable=False,
                stage="candidate_query",
            ) from error

    def get_study_candidate(
        self,
        *,
        audience: ArtifactAudienceBinding,
        discovery_handle: str,
        candidate_handle: str,
    ) -> dict[str, Any]:
        try:
            return self._ensure_study_runtime().get_candidate(
                audience=audience,
                discovery_handle=discovery_handle,
                candidate_handle=candidate_handle,
            )
        except StudyRuntimeError as error:
            raise CardServiceError(
                error.code,
                error.message,
                retryable=False,
                stage="candidate_query",
            ) from error

    def preview_study_candidate_evidence(
        self,
        *,
        audience: ArtifactAudienceBinding,
        discovery_handle: str,
        candidate_handle: str,
        evidence_id: str,
        context_characters: int = 160,
    ) -> dict[str, Any]:
        try:
            return self._ensure_study_runtime().preview_candidate_evidence(
                audience=audience,
                discovery_handle=discovery_handle,
                candidate_handle=candidate_handle,
                evidence_id=evidence_id,
                context_characters=context_characters,
            )
        except StudyRuntimeError as error:
            raise CardServiceError(
                error.code,
                error.message,
                retryable=False,
                stage="candidate_query",
            ) from error

    def discover_study_candidates(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_id: str,
        expected_project_revision: int,
        idempotency_key: str,
        inspection_handle: str,
        candidate_budget: Mapping[str, Any],
    ) -> dict[str, Any]:
        study = self._ensure_study_runtime()
        with self._broker_runtime_lock:
            broker_runtime = self._active_broker_runtime
        if broker_runtime is None:
            raise CardServiceError(
                "AUTHORIZATION_REQUIRED",
                "Candidate discovery requires a current trusted model authorization",
                retryable=True,
                stage="authorization",
            )
        if self._candidate_discovery_uses_hermes(broker_runtime):
            self.ensure_candidate_discovery_provider()
        try:
            provider = BrokerCandidateDiscoveryModelProvider(broker_runtime)
            authorization = provider.authorization_for(
                audience=audience,
                service_instance_id=study.service_instance_id,
                project_id=project_id,
                project_revision=expected_project_revision,
                inspection_handle=inspection_handle,
                candidate_budget=candidate_budget,
            )
            return study.start_candidate_discovery(
                audience=audience,
                project_id=project_id,
                expected_project_revision=expected_project_revision,
                idempotency_key=idempotency_key,
                inspection_handle=inspection_handle,
                candidate_budget=candidate_budget,
                authorization=authorization,
                model_provider=provider,
            )
        except CandidateDiscoveryBrokerError as error:
            code = (
                "AUTHORIZATION_REQUIRED"
                if error.code in {
                    "DISCOVERY_BROKER_UNAVAILABLE",
                    "BROKER_AUTHORIZATION_UNAVAILABLE",
                    "BROKER_AUTHORIZATION_EXPIRED",
                }
                else error.code
            )
            raise CardServiceError(
                code,
                error.message,
                retryable=code == "AUTHORIZATION_REQUIRED",
                stage="authorization",
            ) from error
        except StudyRuntimeError as error:
            raise CardServiceError(
                error.code,
                error.message,
                retryable=error.code.endswith(("_CONFLICT", "_UNAVAILABLE", "_REQUIRED")),
                stage="discovery",
            ) from error

    def start_study_candidate_discovery(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_id: str,
        expected_project_revision: int,
        idempotency_key: str,
        inspection_handle: str,
        candidate_budget: Mapping[str, Any],
    ) -> dict[str, Any]:
        study = self._ensure_study_runtime()
        with self._broker_runtime_lock:
            broker_runtime = self._active_broker_runtime
        if broker_runtime is None:
            raise CardServiceError(
                "AUTHORIZATION_REQUIRED",
                "Candidate discovery requires a current trusted model authorization",
                retryable=True,
                stage="authorization",
                fallbacks=("request_model_authorization",),
            )
        if self._candidate_discovery_uses_hermes(broker_runtime):
            self.ensure_candidate_discovery_provider()
        try:
            provider = BrokerCandidateDiscoveryModelProvider(broker_runtime)
            authorization = provider.authorization_for(
                audience=audience,
                service_instance_id=study.service_instance_id,
                project_id=project_id,
                project_revision=expected_project_revision,
                inspection_handle=inspection_handle,
                candidate_budget=candidate_budget,
            )
            return study.start_candidate_discovery_task(
                audience=audience,
                project_id=project_id,
                expected_project_revision=expected_project_revision,
                idempotency_key=idempotency_key,
                inspection_handle=inspection_handle,
                candidate_budget=candidate_budget,
                authorization=authorization,
                model_provider=provider,
            )
        except CandidateDiscoveryBrokerError as error:
            code = (
                "AUTHORIZATION_REQUIRED"
                if error.code in {
                    "DISCOVERY_BROKER_UNAVAILABLE",
                    "BROKER_AUTHORIZATION_UNAVAILABLE",
                    "BROKER_AUTHORIZATION_EXPIRED",
                }
                else error.code
            )
            raise CardServiceError(
                code,
                error.message,
                retryable=code == "AUTHORIZATION_REQUIRED",
                stage="authorization",
                fallbacks=(
                    ("request_model_authorization",)
                    if code == "AUTHORIZATION_REQUIRED"
                    else ()
                ),
            ) from error
        except StudyRuntimeError as error:
            raise CardServiceError(
                error.code,
                error.message,
                retryable=error.code.endswith(
                    ("_CONFLICT", "_UNAVAILABLE", "_REQUIRED", "_TIMEOUT")
                ),
                stage="discovery",
            ) from error

    def resume_public_study_task(
        self,
        *,
        audience: ArtifactAudienceBinding,
        task_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        study = self._ensure_study_runtime()
        try:
            recovery_task_id, existing = study.resolve_candidate_discovery_recovery_target(
                audience=audience,
                task_id=task_id,
                idempotency_key=idempotency_key,
            )
            if existing is not None:
                return existing
            request = study.candidate_discovery_recovery_request(
                audience=audience, task_id=recovery_task_id
            )
        except StudyRuntimeError as error:
            raise CardServiceError(
                error.code,
                error.message,
                retryable=False,
                stage="recovery",
            ) from error
        with self._broker_runtime_lock:
            broker_runtime = self._active_broker_runtime
        if broker_runtime is None:
            raise CardServiceError(
                "AUTHORIZATION_REQUIRED",
                "Candidate discovery recovery requires current model authorization",
                retryable=True,
                stage="authorization",
                fallbacks=("request_model_authorization",),
            )
        if self._candidate_discovery_uses_hermes(broker_runtime):
            self.ensure_candidate_discovery_provider()
        try:
            provider = BrokerCandidateDiscoveryModelProvider(broker_runtime)
            authorization = provider.authorization_for(
                audience=audience,
                service_instance_id=study.service_instance_id,
                project_id=request["projectId"],
                project_revision=request["expectedProjectRevision"],
                inspection_handle=request["inspectionHandle"],
                candidate_budget=request["candidateBudget"],
            )
            return study.resume_candidate_discovery_task(
                audience=audience,
                task_id=recovery_task_id,
                idempotency_key=idempotency_key,
                authorization=authorization,
                model_provider=provider,
                recovery_request=request,
            )
        except CandidateDiscoveryBrokerError as error:
            code = (
                "AUTHORIZATION_REQUIRED"
                if error.code in {
                    "DISCOVERY_BROKER_UNAVAILABLE",
                    "BROKER_AUTHORIZATION_UNAVAILABLE",
                    "BROKER_AUTHORIZATION_EXPIRED",
                }
                else error.code
            )
            raise CardServiceError(
                code,
                error.message,
                retryable=code == "AUTHORIZATION_REQUIRED",
                stage="authorization",
                fallbacks=(
                    ("request_model_authorization",)
                    if code == "AUTHORIZATION_REQUIRED"
                    else ()
                ),
            ) from error
        except StudyRuntimeError as error:
            raise CardServiceError(
                error.code,
                error.message,
                retryable=error.code.endswith(
                    ("_CONFLICT", "_UNAVAILABLE", "_REQUIRED", "_TIMEOUT")
                ),
                stage="recovery",
            ) from error

    @staticmethod
    def public_local_resource_constraints(kind: str) -> dict[str, Any]:
        if kind == "file":
            return {"actions": ["read"], "maxBytes": MAX_FILE_BYTES}
        if kind == "directory":
            return {
                "actions": ["enumerate", "read"],
                "maxDepth": MAX_DEPTH,
                "maxEntries": MAX_DIRECTORY_ENTRIES,
                "maxTotalBytes": MAX_DIRECTORY_BYTES,
            }
        if kind == "output_directory":
            return {
                "actions": ["create", "versioned"],
                "maxFiles": min(MAX_OUTPUT_FILES, 1_024),
                "maxTotalBytes": min(MAX_OUTPUT_BYTES, 32 * 1024 * 1024 * 1024),
            }
        raise CardServiceError("INVALID_RESOURCE_KIND", "Unsupported public resource kind")

    @staticmethod
    def _local_picker_request_key(
        audience: ArtifactAudienceBinding, grant_request_id: str
    ) -> tuple[str, str, str, str, str]:
        return (
            audience.owner_digest,
            audience.host_id,
            audience.plugin_id,
            audience.session_id,
            grant_request_id,
        )

    @staticmethod
    def _local_resource_scope_summary(
        kind: str, constraints: Mapping[str, Any], max_uses: int
    ) -> str:
        if kind == "file":
            maximum = constraints.get("maxBytes")
            return f"读取所选文件，最多 {maximum} 字节；授权最多使用 {max_uses} 次。"
        if kind == "directory":
            return (
                "读取所选文件夹；最多深度 "
                f"{constraints.get('maxDepth')}，最多 {constraints.get('maxEntries')} 项，"
                f"总计不超过 {constraints.get('maxTotalBytes')} 字节；授权最多使用 {max_uses} 次。"
            )
        return (
            f"向所选输出文件夹创建最多 {constraints.get('maxFiles')} 个文件，"
            f"总计不超过 {constraints.get('maxTotalBytes')} 字节；授权最多使用 {max_uses} 次。"
        )

    def open_local_resource_picker(
        self,
        *,
        audience: ArtifactAudienceBinding,
        grant_request_id: str,
        kind: str,
        constraints: Mapping[str, Any],
        max_uses: int = 1,
    ) -> dict[str, Any]:
        """Internal trusted-adapter entry; raw paths never enter MCP parameters."""

        if not isinstance(audience, ArtifactAudienceBinding):
            raise CardServiceError(
                "RESOURCE_AUDIENCE_INVALID", "Trusted resource audience is invalid"
            )
        if not isinstance(constraints, Mapping):
            raise CardServiceError(
                "RESOURCE_CONSTRAINT_INVALID", "Trusted resource constraints are invalid"
            )
        try:
            frozen_constraints = json.loads(
                json.dumps(
                    dict(constraints), ensure_ascii=False, sort_keys=True, allow_nan=False
                )
            )
        except (TypeError, ValueError) as error:
            raise CardServiceError(
                "RESOURCE_CONSTRAINT_INVALID", "Trusted resource constraints must be finite JSON values"
            ) from error
        try:
            session = self.trusted_surfaces.create_local_resource_session(
                kind=kind,
                scope_summary=self._local_resource_scope_summary(
                    kind, frozen_constraints, max_uses
                ),
            )
        except TrustedSurfaceError as error:
            raise CardServiceError(error.code, str(error)) from error
        session_ref = str(session["sessionRef"])
        with self._resource_runtime_lock:
            self._local_picker_requests[session_ref] = {
                "audience": audience,
                "grantRequestId": grant_request_id,
                "kind": kind,
                "constraints": frozen_constraints,
                "maxUses": max_uses,
            }
        try:
            return self.trusted_surfaces.launch(session_ref)
        except TrustedSurfaceError as error:
            with self._resource_runtime_lock:
                self._local_picker_requests.pop(session_ref, None)
            raise CardServiceError(error.code, str(error)) from error

    def complete_local_resource_picker(self, session_ref: str) -> dict[str, Any]:
        """Finalize a trusted selection into an opaque local resource grant."""

        with self._resource_runtime_lock:
            completed = self._completed_local_picker_grants.get(session_ref)
        if completed is not None:
            return json.loads(json.dumps(completed, ensure_ascii=False))
        try:
            result = self.trusted_surfaces.get_session(session_ref)
        except TrustedSurfaceError as error:
            raise CardServiceError(error.code, str(error)) from error
        if result.get("state") != "selected":
            if result.get("state") in {"cancelled", "declined", "failed"}:
                self.trusted_surfaces.complete_resource_selection(session_ref)
                with self._resource_runtime_lock:
                    self._local_picker_requests.pop(session_ref, None)
            return result
        with self._resource_runtime_lock:
            pending = self._local_picker_requests.get(session_ref)
        selection = self.trusted_surfaces.selected_local_resource(session_ref)
        if pending is None or selection is None or selection.kind != pending["kind"]:
            raise CardServiceError(
                "RESOURCE_SELECTION_STATE_INVALID",
                "Trusted local resource selection state is unavailable",
            )
        try:
            grant = self._ensure_resource_runtime().issue_local_grant(
                audience=pending["audience"],
                grant_request_id=str(pending["grantRequestId"]),
                raw_path=selection.path,
                kind=selection.kind,
                constraints=pending["constraints"],
                attestation_ref=selection.attestation_ref,
                max_uses=int(pending["maxUses"]),
            )
        except ServiceResourceRuntimeError as error:
            raise CardServiceError(error.code, error.message) from error
        finalized = {**result, "resourceGrant": grant}
        self.trusted_surfaces.complete_resource_selection(session_ref)
        with self._resource_runtime_lock:
            self._local_picker_requests.pop(session_ref, None)
            self._completed_local_picker_grants[session_ref] = finalized
        return json.loads(json.dumps(finalized, ensure_ascii=False))

    def request_local_resource_picker(
        self,
        *,
        audience: ArtifactAudienceBinding,
        grant_request_id: str,
        kind: str,
    ) -> dict[str, Any]:
        """Idempotently begin or poll one trusted public resource request."""

        if not _RESOURCE_GRANT_REQUEST_RE.fullmatch(grant_request_id):
            raise CardServiceError(
                "RESOURCE_GRANT_REQUEST_INVALID", "Resource grant request identifier is invalid"
            )
        constraints = self.public_local_resource_constraints(kind)
        max_uses = 8 if kind != "output_directory" else 16
        fingerprint = hashlib.sha256(
            json.dumps(
                {"kind": kind, "constraints": constraints, "maxUses": max_uses},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        key = self._local_picker_request_key(audience, grant_request_id)
        with self._resource_runtime_lock:
            indexed = self._local_picker_request_index.get(key)
            if indexed is not None:
                if indexed["fingerprint"] != fingerprint:
                    raise CardServiceError(
                        "RESOURCE_GRANT_REQUEST_CONFLICT",
                        "Resource grant request identifier was reused with different scope",
                    )
                session_ref = indexed["sessionRef"]
            else:
                opened = self.open_local_resource_picker(
                    audience=audience,
                    grant_request_id=grant_request_id,
                    kind=kind,
                    constraints=constraints,
                    max_uses=max_uses,
                )
                session_ref = str(opened["sessionRef"])
                self._local_picker_request_index[key] = {
                    "sessionRef": session_ref,
                    "fingerprint": fingerprint,
                }
                return opened
        return self.complete_local_resource_picker(session_ref)

    @staticmethod
    def _network_resource_scope_summary(source_kind: str, max_uses: int) -> str:
        label = {
            "public_video": "一个公开视频",
            "web": "一个网页",
            "podcast": "一个播客资源",
            "other": "一个 HTTPS 资源",
        }.get(source_kind)
        if label is None:
            raise CardServiceError(
                "NETWORK_SOURCE_KIND_INVALID", "Unsupported network source kind"
            )
        return (
            f"读取{label}；只允许公网 HTTPS（443）匿名 GET，"
            f"不携带浏览器凭据或环境代理；授权最多使用 {max_uses} 次。"
        )

    def open_network_resource_input(
        self,
        *,
        audience: ArtifactAudienceBinding,
        grant_request_id: str,
        source_kind: str,
        max_uses: int = 8,
    ) -> dict[str, Any]:
        """Open a trusted URL entry surface; raw URLs never enter MCP."""

        if not isinstance(audience, ArtifactAudienceBinding):
            raise CardServiceError(
                "NETWORK_AUDIENCE_INVALID", "Trusted network audience is invalid"
            )
        if not _RESOURCE_GRANT_REQUEST_RE.fullmatch(grant_request_id):
            raise CardServiceError(
                "NETWORK_GRANT_REQUEST_INVALID",
                "Network grant request identifier is invalid",
            )
        if source_kind not in {"public_video", "web", "podcast", "other"}:
            raise CardServiceError(
                "NETWORK_SOURCE_KIND_INVALID", "Unsupported network source kind"
            )
        try:
            session = self.trusted_surfaces.create_network_resource_session(
                source_kind=source_kind,
                scope_summary=self._network_resource_scope_summary(
                    source_kind, max_uses
                ),
            )
        except TrustedSurfaceError as error:
            raise CardServiceError(error.code, str(error)) from error
        session_ref = str(session["sessionRef"])
        with self._resource_runtime_lock:
            self._network_resource_requests[session_ref] = {
                "audience": audience,
                "grantRequestId": grant_request_id,
                "sourceKind": source_kind,
                "maxUses": max_uses,
            }
        try:
            return self.trusted_surfaces.launch(session_ref)
        except TrustedSurfaceError as error:
            with self._resource_runtime_lock:
                self._network_resource_requests.pop(session_ref, None)
            raise CardServiceError(error.code, str(error)) from error

    def complete_network_resource_input(self, session_ref: str) -> dict[str, Any]:
        """Finalize one trusted URL into an opaque, audience-bound grant."""

        with self._resource_runtime_lock:
            completed = self._completed_network_resource_grants.get(session_ref)
        if completed is not None:
            return json.loads(json.dumps(completed, ensure_ascii=False))
        try:
            result = self.trusted_surfaces.get_session(session_ref)
        except TrustedSurfaceError as error:
            raise CardServiceError(error.code, str(error)) from error
        state = str(result.get("state") or "failed")
        if state != "selected":
            if state in {"cancelled", "declined", "failed"}:
                self.trusted_surfaces.complete_network_resource_selection(
                    session_ref
                )
                with self._resource_runtime_lock:
                    pending = self._network_resource_requests.pop(
                        session_ref, None
                    )
                    if pending is not None:
                        self._completed_network_resource_grants[session_ref] = (
                            dict(result)
                        )
            return result
        with self._resource_runtime_lock:
            pending = self._network_resource_requests.get(session_ref)
        selection = self.trusted_surfaces.selected_network_resource(session_ref)
        if (
            pending is None
            or selection is None
            or selection.source_kind != pending["sourceKind"]
        ):
            raise CardServiceError(
                "NETWORK_SELECTION_STATE_INVALID",
                "Trusted network resource input state is unavailable",
            )
        try:
            grant = self._ensure_network_resource_registry().issue_grant(
                audience=pending["audience"],
                grant_request_id=str(pending["grantRequestId"]),
                raw_url=selection.raw_url,
                source_kind=selection.source_kind,
                attestation_ref=selection.attestation_ref,
                max_uses=int(pending["maxUses"]),
            )
        except NetworkResourceRegistryError as error:
            finalized = {
                "schemaVersion": 1,
                "sessionRef": session_ref,
                "state": "failed",
                "errorCode": error.code,
            }
        else:
            finalized = {**result, "networkGrant": grant}
        self.trusted_surfaces.complete_network_resource_selection(session_ref)
        with self._resource_runtime_lock:
            self._network_resource_requests.pop(session_ref, None)
            self._completed_network_resource_grants[session_ref] = finalized
        return json.loads(json.dumps(finalized, ensure_ascii=False))

    def request_network_resource_grant(
        self,
        *,
        audience: ArtifactAudienceBinding,
        grant_request_id: str,
        source_kind: str,
    ) -> dict[str, Any]:
        """Idempotently open or poll one trusted network resource request."""

        if not _RESOURCE_GRANT_REQUEST_RE.fullmatch(grant_request_id):
            raise CardServiceError(
                "NETWORK_GRANT_REQUEST_INVALID",
                "Network grant request identifier is invalid",
            )
        if source_kind not in {"public_video", "web", "podcast", "other"}:
            raise CardServiceError(
                "NETWORK_SOURCE_KIND_INVALID", "Unsupported network source kind"
            )
        max_uses = 8
        fingerprint = hashlib.sha256(
            canonical_json_bytes(
                {
                    "sourceKind": source_kind,
                    "maxUses": max_uses,
                    "policy": "anonymous-public-https-v1",
                }
            )
        ).hexdigest()
        key = self._local_picker_request_key(audience, grant_request_id)
        with self._resource_runtime_lock:
            indexed = self._network_resource_request_index.get(key)
            if indexed is not None:
                if indexed["fingerprint"] != fingerprint:
                    raise CardServiceError(
                        "NETWORK_GRANT_REQUEST_CONFLICT",
                        "Network grant request identifier was reused with different scope",
                    )
                session_ref = indexed["sessionRef"]
            else:
                opened = self.open_network_resource_input(
                    audience=audience,
                    grant_request_id=grant_request_id,
                    source_kind=source_kind,
                    max_uses=max_uses,
                )
                session_ref = str(opened["sessionRef"])
                self._network_resource_request_index[key] = {
                    "sessionRef": session_ref,
                    "fingerprint": fingerprint,
                }
                return opened
        return self.complete_network_resource_input(session_ref)

    def _broker_blocker(self, method: str, policy: MethodPolicy) -> str | None:
        with self._broker_runtime_lock:
            if not policy.requires_broker:
                return None
            if self.broker_handler_factory is None:
                return "model_tts_broker_not_ready"
            if self.broker_method_blocker is None:
                return None
            blocker = self.broker_method_blocker(method)
            if blocker is not None:
                return blocker
            if (
                method == CANDIDATE_DISCOVERY_BROKER_METHOD
                and self._active_broker_runtime is not None
                and self._candidate_discovery_uses_hermes(self._active_broker_runtime)
                and self.hermes_proxy_manager.probe()["state"] != "ready"
            ):
                return "hermes_proxy_not_ready"
            return None

    @staticmethod
    def _candidate_discovery_uses_hermes(
        broker_runtime: ServiceBrokerRuntime,
    ) -> bool:
        bindings = broker_runtime.configuration.method_bindings.get(
            CANDIDATE_DISCOVERY_BROKER_METHOD
        )
        if not isinstance(bindings, Mapping):
            return False
        profile_ref = bindings.get("model")
        binding = broker_runtime.configuration.profiles.get(str(profile_ref or ""))
        return binding is not None and binding.profile.provider == "hermes"

    def ensure_candidate_discovery_provider(self) -> dict[str, Any]:
        try:
            return self.hermes_proxy_manager.ensure_ready()
        except HermesProxyError as error:
            fallbacks = (
                ("authenticate_hermes",)
                if error.code == "HERMES_OAUTH_REQUIRED"
                else ("retry_model_preflight",)
            )
            raise CardServiceError(
                error.code,
                error.message,
                retryable=error.retryable,
                stage="model",
                fallbacks=fallbacks,
            ) from error

    def _method_availability(self, method: str, policy: MethodPolicy) -> dict[str, Any]:
        blocker = self._broker_blocker(method, policy)
        return {"available": blocker is None, "blocker": blocker}

    def capabilities(self) -> dict[str, Any]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "service": "codex-study-card-service",
            "transport": "local-stdio",
            "methods": sorted(self.method_policies),
            "methodAvailability": {
                method: self._method_availability(method, policy)
                for method, policy in sorted(self.method_policies.items())
            },
            "taskMethods": ["task.get", "task.cancel", "task.list_recoverable", "task.read_result"],
            "systemMethods": [
                "system.get_capabilities",
                "system.list_profiles",
                "system.request_source_grant",
                "system.request_output_grant",
                "system.request_network_grant",
                "system.revoke_grant",
                "system.open_local_settings",
                "system.get_local_settings",
                "system.open_broker_authorization",
                "system.get_trusted_surface",
            ],
            "genericShell": False,
            "genericWorkerCommand": False,
            "secretBearingRequests": False,
            "worker": {
                "resourceId": "managed:legacy-worker",
                "sha256": self.worker_sha256,
            },
            "python": {
                "resourceId": "managed:python-runtime",
                "version": sys.version.split()[0],
            },
            "managedToolDirectoryCount": len(self.managed_tool_directories),
            "runtimeSupplyChain": self.runtime_manifest.public_summary(),
            "runtimePackage": (
                self.runtime_package.public_summary()
                if self.runtime_package is not None
                else {
                    "schemaVersion": 1,
                    "mode": "development-unpackaged",
                    "pathDisclosure": False,
                    "signatureVerified": False,
                    "complete": False,
                }
            ),
            "processIsolation": {
                "taskOwnedJobObject": os.name == "nt",
                "killOnClose": os.name == "nt",
                "noBreakawayRequested": os.name == "nt",
                "restrictedPrimaryToken": self.use_restricted_launcher,
                "activeProcessLimit": self.task_active_process_limit,
                "memoryLimitBytes": self.task_memory_limit_bytes,
                "runtimePackageDacl": self.runtime_package_dacl,
                "taskWorkspaceDacl": self.runtime_package_dacl,
                "taskWorkspaceWorkingDirectory": True,
                "taskWorkspaceLimitBytes": self.task_workspace_limit_bytes,
                "taskWorkspaceEntryLimit": self.task_workspace_entry_limit,
                "taskWorkspaceServiceLimitBytes": self.task_workspace_service_limit_bytes,
                "taskWorkspaceServiceEntryLimit": self.task_workspace_service_entry_limit,
                "taskWorkspaceVolumeReserveBytes": self.task_workspace_volume_reserve_bytes,
                "appContainerOrRestrictedSidDacl": self.runtime_package_dacl,
                "forcedOutboundBroker": self.runtime_package_dacl,
                "complete": False,
            },
            "modelTtsBroker": {
                "credentialManager": os.name == "nt",
                "reservationLedger": True,
                "taskOwnedWorkerTransport": self.broker_handler_factory is not None,
                "complete": False,
                **self.broker_runtime_capabilities,
            },
            "mediaToolPolicy": {
                "managedAbsoluteTools": self.runtime_package is not None,
                "fixedProtocolAllowlist": self.runtime_package is not None,
                "fixedDemuxerAllowlist": self.runtime_package is not None,
                "externalConfigDisabled": self.runtime_package is not None,
                "resourceEvidencePreflight": self.runtime_package is not None,
                "perOutputFileLimit": self.runtime_package is not None,
                "taskWorkspaceBudget": True,
                "aggregateWorkspaceBudget": True,
                "aggregateWorkspaceBudgetScope": "service_process",
                "volumeFreeSpaceReserve": True,
                "volumeFreeSpaceReserveEnforcement": "admission_and_periodic",
                "externalWriterHardQuota": False,
                "automaticArtifactRetentionCleanup": False,
                "subprocessTimeoutSeconds": 300,
                "complete": False,
            },
            "trustedSurfaces": self.trusted_surfaces.capabilities(),
            "serviceProfiles": {
                "persistentRegistry": True,
                "verificationLedger": True,
                "publicListProfiles": True,
                "trustedCredentialSettings": True,
                "publicProfileValidation": True,
                "trustedOperationConfirmation": True,
                "profileDraftValidation": False,
                "complete": False,
            },
            "localResourceRuntime": self._resource_runtime_capabilities(),
            "studyRuntime": self._study_runtime_capabilities(),
        }

    @staticmethod
    def _file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _recover_orphaned_tasks(self) -> None:
        for snapshot in self.store.list_tasks():
            if snapshot.get("state") not in ACTIVE_STATES:
                continue
            now = _now_ms()
            snapshot = dict(snapshot)
            snapshot["state"] = "interrupted"
            snapshot["updatedAt"] = now
            snapshot["error"] = {
                "code": "SERVICE_RESTARTED",
                "message": "Card Service restarted before the task reached a terminal state",
                "retryable": True,
            }
            self.store.write_task(str(snapshot.get("id") or ""), snapshot)

    def _sandboxes_root(self) -> Path:
        candidate = self.store.root / "sandboxes"
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            _assert_no_reparse_components(candidate)
            root = candidate.resolve(strict=True)
        except CardServiceError:
            raise
        except OSError as error:
            raise CardServiceError(
                "TASK_WORKSPACE_CREATE_FAILED",
                "Could not create the isolated task workspace root",
            ) from error
        if root.parent != self.store.root:
            raise CardServiceError(
                "TASK_WORKSPACE_REPARSE_BLOCKED",
                "Task workspace root escaped the Card Service state directory",
                retryable=False,
                stage="workspace",
            )
        return root

    def _enforce_workspace_capacity(
        self,
        *,
        proposed_task_id: str | None = None,
    ) -> Path:
        """Reserve worst-case active-task growth before it can consume the volume."""

        with self._workspace_budget_lock:
            root = self._sandboxes_root()
            fleet = _task_workspace_fleet_usage(
                root,
                service_byte_limit=self.task_workspace_service_limit_bytes,
                service_entry_limit=self.task_workspace_service_entry_limit,
            )
            reserved_byte_headroom = 0
            reserved_entry_headroom = 0
            for task_id in self._workspace_reservations:
                usage = fleet.by_task.get(task_id)
                if usage is None:
                    reserved_byte_headroom += self.task_workspace_limit_bytes
                    reserved_entry_headroom += self.task_workspace_entry_limit + 1
                    continue
                reserved_byte_headroom += max(
                    0,
                    self.task_workspace_limit_bytes - usage.logical_bytes,
                )
                reserved_entry_headroom += max(
                    0,
                    self.task_workspace_entry_limit - usage.entry_count,
                )
            proposed_bytes = 0
            proposed_entries = 0
            if proposed_task_id is not None and proposed_task_id not in self._workspace_reservations:
                proposed_bytes = self.task_workspace_limit_bytes
                proposed_entries = self.task_workspace_entry_limit + 1
            projected_bytes = fleet.logical_bytes + reserved_byte_headroom + proposed_bytes
            projected_entries = fleet.entry_count + reserved_entry_headroom + proposed_entries
            if projected_bytes > self.task_workspace_service_limit_bytes:
                raise CardServiceError(
                    "TASK_WORKSPACE_SERVICE_LIMIT",
                    f"Task admission would exceed the {self.task_workspace_service_limit_bytes} byte service workspace limit",
                    retryable=True,
                    stage="workspace",
                    fallbacks=("release_old_tasks", "reduce_media_batch"),
                )
            if projected_entries > self.task_workspace_service_entry_limit:
                raise CardServiceError(
                    "TASK_WORKSPACE_SERVICE_ENTRY_LIMIT",
                    f"Task admission would exceed the {self.task_workspace_service_entry_limit} entry service workspace limit",
                    retryable=True,
                    stage="workspace",
                    fallbacks=("release_old_tasks", "reduce_media_batch"),
                )
            try:
                volume_free_bytes = max(0, int(shutil.disk_usage(root).free))
            except OSError as error:
                raise CardServiceError(
                    "TASK_WORKSPACE_VOLUME_UNAVAILABLE",
                    "The task workspace volume capacity could not be inspected",
                    retryable=True,
                    stage="workspace",
                ) from error
            required_free_bytes = (
                self.task_workspace_volume_reserve_bytes
                + reserved_byte_headroom
                + proposed_bytes
            )
            if volume_free_bytes < required_free_bytes:
                raise CardServiceError(
                    "TASK_WORKSPACE_VOLUME_RESERVE",
                    "Task admission would consume the configured minimum free-space reserve",
                    retryable=True,
                    stage="workspace",
                    fallbacks=("release_old_tasks", "change_storage_volume", "reduce_media_batch"),
                )
            return root

    def _release_workspace_reservation(self, task_id: str) -> None:
        with self._workspace_budget_lock:
            self._workspace_reservations.discard(task_id)

    def start_task(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        task_id_override: str | None = None,
        broker_handler_factory_override: BrokerHandlerFactory | None | object = _DEFAULT_BROKER_RUNTIME,
        broker_method_blocker_override: BrokerMethodBlocker | None | object = _DEFAULT_BROKER_RUNTIME,
        snapshot_extra: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        policy = self.method_policies.get(method)
        if policy is None:
            raise CardServiceError("METHOD_NOT_ALLOWED", f"Card Service method is not allowed: {method}")
        if broker_handler_factory_override is _DEFAULT_BROKER_RUNTIME:
            with self._broker_runtime_lock:
                blocker = self._broker_blocker(method, policy)
                task_broker_factory = self.broker_handler_factory
                task_broker_blocker = self.broker_method_blocker
        else:
            task_broker_factory = broker_handler_factory_override
            task_broker_blocker = (
                None
                if broker_method_blocker_override is _DEFAULT_BROKER_RUNTIME
                else broker_method_blocker_override
            )
            blocker = None
            if policy.requires_broker and task_broker_factory is None:
                blocker = "model_tts_broker_not_ready"
            elif callable(task_broker_blocker):
                blocker = task_broker_blocker(method)
        if blocker is not None:
            raise CardServiceError(
                "BROKER_REQUIRED" if blocker == "model_tts_broker_not_ready" else "BROKER_AUTHORIZATION_UNAVAILABLE",
                f"This operation is blocked by the Service-owned broker authorization ({blocker})",
            )
        request = dict(params or {})
        secret_path = _find_secret_path(request)
        if secret_path:
            raise CardServiceError(
                "SECRET_IN_REQUEST",
                f"Secret-bearing requests are not accepted by the legacy Worker boundary ({secret_path})",
            )
        if policy.requires_broker:
            service_owned_path = _find_service_owned_broker_path(request)
            if service_owned_path:
                raise CardServiceError(
                    "SERVICE_OWNED_AUTHORIZATION_IN_REQUEST",
                    f"Broker authorization is owned by Card Service and cannot be supplied by a task ({service_owned_path})",
                )
        task_id = str(task_id_override or uuid.uuid4())
        try:
            uuid.UUID(task_id)
        except (ValueError, AttributeError) as error:
            raise CardServiceError(
                "TASK_ID_INVALID", "Card Service task identifier is invalid"
            ) from error
        if self.get_task(task_id) is not None:
            raise CardServiceError(
                "TASK_ALREADY_EXISTS", "Card Service task identifier already exists"
            )
        sandbox_workspace: Path | None = None
        task_sid: str | None = None
        with self._workspace_budget_lock:
            sandboxes_root = self._enforce_workspace_capacity(proposed_task_id=task_id)
            expected_workspace = sandboxes_root / task_id
            try:
                if self.runtime_package_dacl:
                    sandbox_workspace, task_sid = create_task_workspace(
                        sandboxes_root,
                        task_id,
                    )
                else:
                    sandbox_workspace = (sandboxes_root / task_id).resolve()
                    if sandbox_workspace.parent != sandboxes_root:
                        raise OSError("task workspace escaped its root")
                    sandbox_workspace.mkdir(mode=0o700, exist_ok=False)
                assert sandbox_workspace is not None
                _task_workspace_usage(
                    sandbox_workspace,
                    byte_limit=self.task_workspace_limit_bytes,
                    entry_limit=self.task_workspace_entry_limit,
                )
            except WindowsSandboxAclError as error:
                _remove_empty_task_workspace(expected_workspace)
                raise CardServiceError(error.code, str(error)) from error
            except CardServiceError:
                _remove_empty_task_workspace(expected_workspace)
                raise
            except OSError as error:
                _remove_empty_task_workspace(expected_workspace)
                raise CardServiceError(
                    "TASK_WORKSPACE_CREATE_FAILED",
                    "Could not create the isolated task workspace",
                ) from error
            self._workspace_reservations.add(task_id)
        now = _now_ms()
        snapshot: dict[str, Any] = {
            "schemaVersion": SCHEMA_VERSION,
            "id": task_id,
            "method": method,
            "workerCommand": policy.worker_command,
            "state": "queued",
            "startedAt": now,
            "updatedAt": now,
            "cancellable": policy.cancellable,
            "inputFingerprint": _canonical_fingerprint(request),
            "progress": {
                "phase": "queued",
                "phaseLabel": "Waiting for Card Service",
                "phasePercent": None,
                "overallPercent": None,
                "message": "Task queued",
                "lastProgressAt": now,
            },
            "resultRef": None,
            "error": None,
        }
        if snapshot_extra is not None:
            overlap = set(snapshot).intersection(snapshot_extra)
            if overlap:
                raise CardServiceError(
                    "TASK_METADATA_INVALID",
                    "Private task metadata overlaps the public task snapshot",
                )
            snapshot.update(
                json.loads(json.dumps(dict(snapshot_extra), ensure_ascii=False))
            )
        runtime = _RuntimeTask(
            snapshot=snapshot,
            request=request,
            sandbox_workspace=sandbox_workspace,
            task_sandbox_sid=task_sid,
            broker_handler_factory=task_broker_factory,
            broker_method_blocker=task_broker_blocker,
        )
        registered = False
        try:
            with self._tasks_lock:
                self._tasks[task_id] = runtime
                registered = True
            self.store.write_task(task_id, snapshot)
            thread = threading.Thread(
                target=self._run_task,
                args=(runtime, policy),
                daemon=True,
                name=f"card-task-{task_id}",
            )
            thread.start()
        except Exception as error:
            self._release_workspace_reservation(task_id)
            if registered:
                with self._tasks_lock:
                    self._tasks.pop(task_id, None)
            _remove_empty_task_workspace(sandbox_workspace)
            failed_snapshot = dict(snapshot)
            failed_snapshot["state"] = "failed"
            failed_snapshot["updatedAt"] = _now_ms()
            failed_snapshot["error"] = {
                "code": "TASK_START_FAILED",
                "message": "Card Service could not start the managed task",
                "retryable": True,
            }
            try:
                self.store.write_task(task_id, failed_snapshot)
            except OSError:
                pass
            raise CardServiceError(
                "TASK_START_FAILED",
                "Card Service could not start the managed task",
                retryable=True,
                stage="workspace",
            ) from error
        return self.get_task(task_id) or dict(snapshot)

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._tasks_lock:
            runtime = self._tasks.get(task_id)
        if runtime is not None:
            with runtime.lock:
                return json.loads(json.dumps(runtime.snapshot, ensure_ascii=False))
        return self.store.read_task(task_id)

    def list_recoverable_tasks(self) -> list[dict[str, Any]]:
        return [
            snapshot
            for snapshot in self.store.list_tasks()
            if snapshot.get("state") in {"interrupted", "failed", "cancelled"}
        ]

    def read_result(self, task_id: str) -> Any:
        snapshot = self.get_task(task_id)
        if not snapshot:
            raise CardServiceError("TASK_NOT_FOUND", "Card Service task does not exist")
        if snapshot.get("state") != "succeeded" or not snapshot.get("resultRef"):
            raise CardServiceError("RESULT_NOT_READY", "Card Service task has no successful result")
        return self.store.read_result(str(snapshot["resultRef"]))

    def cancel_task(self, task_id: str) -> dict[str, Any]:
        with self._tasks_lock:
            runtime = self._tasks.get(task_id)
        if runtime is None:
            snapshot = self.store.read_task(task_id)
            if snapshot is None:
                raise CardServiceError("TASK_NOT_FOUND", "Card Service task does not exist")
            return snapshot
        with runtime.lock:
            if runtime.snapshot.get("state") in TERMINAL_STATES:
                return dict(runtime.snapshot)
            runtime.cancel_event.set()
            runtime.snapshot["state"] = "cancelling"
            runtime.snapshot["updatedAt"] = _now_ms()
            runtime.snapshot["progress"]["message"] = "Cancellation requested"
            self.store.write_task(task_id, runtime.snapshot)
            return json.loads(json.dumps(runtime.snapshot, ensure_ascii=False))

    def dispatch(self, method: str, params: dict[str, Any] | None = None) -> Any:
        values = dict(params or {})
        if method == "system.get_capabilities":
            return self.capabilities()
        if method == "system.list_profiles":
            return self.list_service_profiles()
        if method == "system.validate_profile":
            audience = values.pop("audience", None)
            if not isinstance(audience, ArtifactAudienceBinding):
                raise CardServiceError(
                    "TRUSTED_AUDIENCE_REQUIRED",
                    "Profile validation requires a trusted audience",
                )
            return self.validate_service_profile(audience=audience, **values)
        if method == "system.request_operation_confirmation":
            audience = values.pop("audience", None)
            if not isinstance(audience, ArtifactAudienceBinding):
                raise CardServiceError(
                    "TRUSTED_AUDIENCE_REQUIRED",
                    "Operation confirmation requires a trusted audience",
                )
            return self.request_operation_confirmation(audience=audience, **values)
        if method == "task.get":
            return self.get_task(str(values.get("taskId") or ""))
        if method == "task.cancel":
            return self.cancel_task(str(values.get("taskId") or ""))
        if method == "task.list_recoverable":
            return {"tasks": self.list_recoverable_tasks()}
        if method == "task.read_result":
            return self.read_result(str(values.get("taskId") or ""))
        if method == "system.open_local_settings":
            return self.open_local_settings(
                profile_ref=str(values.get("profileRef") or ""),
                capability=str(values.get("capability") or ""),
            )
        if method == "system.get_local_settings":
            return self.get_local_settings(
                str(values.get("configurationSessionRef") or "")
            )
        if method == "system.open_broker_authorization":
            try:
                session = self.trusted_surfaces.create_broker_authorization_session(values)
                return self.trusted_surfaces.launch(str(session["sessionRef"]))
            except TrustedSurfaceError as error:
                raise CardServiceError(error.code, str(error)) from error
        if method == "system.get_trusted_surface":
            try:
                session_ref = str(values.get("sessionRef") or "")
                result = self.trusted_surfaces.get_session(session_ref)
                issued = self.trusted_surfaces.issued_authorization(session_ref)
                if result.get("authorization") is not None and issued is not None:
                    self._activate_broker_authorization(
                        issued.manifest_path,
                        expected_digest=str(issued.public_summary["authorizationDigest"]),
                    )
                return result
            except TrustedSurfaceError as error:
                raise CardServiceError(error.code, str(error)) from error
        return self.start_task(method, values)

    def _activate_broker_authorization(self, manifest_path: Path, *, expected_digest: str) -> None:
        expected = (self.store.root / "trusted-surfaces" / "authorizations").resolve()
        try:
            candidate = manifest_path.resolve(strict=True)
        except OSError as error:
            raise CardServiceError(
                "BROKER_MANIFEST_UNAVAILABLE",
                "Issued broker authorization is unavailable",
            ) from error
        if candidate.parent != expected:
            raise CardServiceError(
                "BROKER_MANIFEST_OUTSIDE_TRUSTED_SURFACE",
                "Issued broker authorization is outside the trusted state directory",
            )
        with self._broker_runtime_lock:
            current_digest = self.broker_runtime_capabilities.get("authorizationManifestDigest")
            issued_digest = None
            try:
                runtime = ServiceBrokerRuntime.from_manifest(
                    candidate,
                    state_dir=self.store.root,
                    credential_backend=self._credential_backend,
                )
                issued_digest = runtime.configuration.manifest_digest
            except BrokerConfigurationError as error:
                raise CardServiceError(error.code, str(error)) from error
            if issued_digest != expected_digest:
                raise CardServiceError(
                    "BROKER_MANIFEST_DIGEST_MISMATCH",
                    "Issued broker authorization changed before activation",
                )
            if current_digest == issued_digest and self._active_broker_runtime is not None:
                return
            self._active_broker_runtime = runtime
            self.broker_handler_factory = runtime.handler_factory
            self.broker_method_blocker = runtime.method_blocker
            self.broker_runtime_capabilities = runtime.capabilities()

    def _active_broker_authorization_summary(self) -> dict[str, Any] | None:
        """Return a bounded internal manager view of the active broker grant."""

        with self._broker_runtime_lock:
            runtime = self._active_broker_runtime
            if runtime is None:
                return None
            configuration = runtime.configuration
            capabilities = sorted(
                {
                    str(capability)
                    for bindings in configuration.method_bindings.values()
                    for capability in bindings
                }
            )
            return {
                "schemaVersion": 1,
                "kind": "broker_authorization",
                "authorizationDigest": configuration.manifest_digest,
                "capabilities": capabilities,
                "profileCount": len(
                    {
                        str(profile_ref)
                        for bindings in configuration.method_bindings.values()
                        for profile_ref in bindings.values()
                    }
                ),
                "expiresAtUnixMs": int(configuration.expires_at_unix_ms),
                "state": (
                    "expired"
                    if int(time.time() * 1000)
                    >= int(configuration.expires_at_unix_ms)
                    else "active"
                ),
            }

    def _revoke_active_broker_authorization(
        self, *, expected_authorization_digest: str | None = None
    ) -> dict[str, Any]:
        """Atomically revoke every profile in the current broker authorization.

        Running calls are not represented as rolled back. New reservations and
        later safe-point calls fail through the shared reservation ledger.
        """

        with self._broker_runtime_lock:
            runtime = self._active_broker_runtime
            if runtime is None:
                return {
                    "schemaVersion": 1,
                    "kind": "broker_authorization",
                    "state": "not_found",
                    "revokedProfileCount": 0,
                }
            current_digest = runtime.configuration.manifest_digest
            if (
                expected_authorization_digest is not None
                and current_digest != expected_authorization_digest
            ):
                return {
                    "schemaVersion": 1,
                    "kind": "broker_authorization",
                    "state": "stale",
                    "revokedProfileCount": 0,
                }
            profile_refs = {
                str(profile_ref)
                for bindings in runtime.configuration.method_bindings.values()
                for profile_ref in bindings.values()
            }
            newly_revoked = runtime.ledger.revoke_profiles(profile_refs)
            if self._active_broker_runtime is runtime:
                self._active_broker_runtime = None
                self.broker_handler_factory = None
                self.broker_method_blocker = None
                self.broker_runtime_capabilities = {}
            return {
                "schemaVersion": 1,
                "kind": "broker_authorization",
                "state": "revoked",
                "revokedProfileCount": len(profile_refs),
                "newlyRevokedProfileCount": newly_revoked,
            }

    @staticmethod
    def _authorization_session_matches(
        pending: Mapping[str, Any], audience: ArtifactAudienceBinding
    ) -> bool:
        return pending.get("audience") == audience

    def _authorization_audience_digest(
        self, audience: ArtifactAudienceBinding
    ) -> str:
        if not isinstance(audience, ArtifactAudienceBinding):
            raise CardServiceError(
                "AUTHORIZATION_AUDIENCE_INVALID",
                "Trusted authorization audience is invalid",
                retryable=False,
                stage="authorization",
            )
        runtime = self._ensure_resource_runtime()
        return hashlib.sha256(
            canonical_json_bytes(audience.audience(runtime.service_instance_id))
        ).hexdigest()

    def _authorization_inventory(
        self, audience: ArtifactAudienceBinding
    ) -> tuple[str, list[dict[str, Any]]]:
        audience_digest = self._authorization_audience_digest(audience)
        try:
            local_grants = self._ensure_resource_runtime().list_local_grants(
                audience=audience,
                include_terminal=False,
                maximum=257,
            )
            network_grants = self._ensure_network_resource_registry().list_grants(
                audience,
                include_terminal=False,
                maximum=257,
            )
            import_approvals = self._ensure_study_runtime().list_anki_import_approvals(
                audience=audience,
                include_terminal=False,
                maximum=257,
            )
            operation_approvals = (
                self._ensure_authorization_ledger().list_revocable_operation_approvals(
                    audience=audience,
                    limit=256,
                )
            )
        except (
            ServiceResourceRuntimeError,
            NetworkResourceRegistryError,
            StudyRuntimeError,
            AuthorizationLedgerError,
        ) as error:
            raise CardServiceError(
                error.code,
                "Authorization inventory is unavailable",
                retryable=False,
                stage="authorization",
            ) from error

        items: list[dict[str, Any]] = []
        for grant in local_grants:
            actions = ", ".join(str(value) for value in grant.get("actions") or [])
            items.append(
                {
                    "kind": "local_resource",
                    "title": f"本地资源 · {str(grant.get('displayName') or '已选择资源')[:120]}",
                    "detail": (
                        f"允许操作：{actions or '读取'}；剩余 {int(grant.get('remainingUses') or 0)} 次；"
                        f"有效期至 {str(grant.get('expiresAt') or '未知')}"
                    )[:500],
                    "state": "active",
                    "locator": {
                        "resourceRef": str(grant["resourceRef"]),
                        "revocationEpoch": int(grant["revocationEpoch"]),
                    },
                }
            )
        for grant in network_grants:
            items.append(
                {
                    "kind": "network_resource",
                    "title": (
                        "网络资源 · "
                        + str(grant.get("displayOrigin") or "已授权来源")[:120]
                    ),
                    "detail": (
                        f"类型：{str(grant.get('sourceKind') or 'HTTPS')}；"
                        f"剩余 {int(grant.get('remainingUses') or 0)} 次；"
                        f"有效期至 {str(grant.get('expiresAt') or '未知')}"
                    )[:500],
                    "state": "active",
                    "locator": {
                        "networkResourceRef": str(
                            grant["networkResourceRef"]
                        ),
                        "revocationEpoch": int(grant["revocationEpoch"]),
                    },
                }
            )
        for approval in import_approvals:
            approval_state = str(approval.get("approvalState") or "pending")
            if approval_state not in {"pending", "approved"}:
                continue
            items.append(
                {
                    "kind": "anki_import",
                    "title": "Anki 导入批准",
                    "detail": (
                        f"状态：{'已批准' if approval_state == 'approved' else '待确认'}；"
                        f"有效期至 {str(approval.get('expiresAt') or '未知')}"
                    )[:500],
                    "state": approval_state,
                    "locator": {
                        "importIntentId": str(approval["importIntentId"]),
                    },
                }
            )
        for approval in operation_approvals:
            subject_label = (
                str(approval.get("profileRef") or "服务配置")
                if approval.get("subjectKind") == "profile_validation"
                else "学习任务"
            )
            items.append(
                {
                    "kind": "operation_approval",
                    "title": f"待执行操作 · {str(approval['actionId'])[:120]}",
                    "detail": (
                        f"范围：{subject_label}；已批准但尚未消费；"
                        f"有效期至 {str(approval['expiresAt'])}"
                    )[:500],
                    "state": "approved",
                    "locator": {
                        "operationIntentId": str(
                            approval["operationIntentId"]
                        ),
                        "intentDigest": str(approval["intentDigest"]),
                        "audienceDigest": self._ensure_authorization_ledger().audience_digest(
                            audience
                        ),
                    },
                }
            )
        broker = self._active_broker_authorization_summary()
        if broker is not None and broker["state"] == "active":
            capabilities = "、".join(str(value) for value in broker["capabilities"])
            items.append(
                {
                    "kind": "broker_authorization",
                    "title": "模型、语音与来源服务授权",
                    "detail": (
                        f"能力：{capabilities or '远程服务'}；配置 {broker['profileCount']} 项；"
                        f"有效期至 {broker['expiresAtUnixMs']}"
                    )[:500],
                    "state": "active",
                    "locator": {
                        "activeAuthorization": True,
                        "authorizationDigest": str(broker["authorizationDigest"]),
                    },
                }
            )
        if (
            len(local_grants) > 256
            or len(network_grants) > 256
            or len(import_approvals) > 256
            or len(operation_approvals) > 256
            or len(items) > 256
        ):
            raise CardServiceError(
                "AUTHORIZATION_MANAGER_LIMIT_EXCEEDED",
                "Authorization inventory exceeds the bounded management limit",
                retryable=False,
                stage="authorization",
            )
        return audience_digest, items

    @staticmethod
    def _authorization_disposition(error_code: str) -> str:
        if error_code in {"IMPORT_APPROVAL_CONSUMED", "OPERATION_APPROVAL_CONSUMED"}:
            return "already_consumed"
        if error_code in {
            "RESOURCE_ALREADY_REVOKED",
            "RESOURCE_REVOKED",
            "NETWORK_ALREADY_REVOKED",
            "NETWORK_RESOURCE_REVOKED",
            "IMPORT_APPROVAL_ALREADY_REVOKED",
            "IMPORT_APPROVAL_REVOKED",
            "OPERATION_APPROVAL_REVOKED",
        }:
            return "already_revoked"
        if error_code in {
            "RESOURCE_NOT_FOUND",
            "NETWORK_RESOURCE_NOT_FOUND",
            "IMPORT_INTENT_NOT_FOUND",
            "IMPORT_APPROVAL_NOT_FOUND",
            "OPERATION_INTENT_NOT_FOUND",
        }:
            return "not_found"
        return "failed"

    def request_authorization_revocation(
        self,
        *,
        audience: ArtifactAudienceBinding,
        authorization_session_ref: str | None = None,
    ) -> dict[str, Any]:
        """Open or poll the trusted, pathless authorization revocation manager."""

        if authorization_session_ref is None:
            audience_digest, items = self._authorization_inventory(audience)
            if not items:
                return {
                    "schemaVersion": 1,
                    "state": "empty",
                    "availableCount": 0,
                    "selectedCount": 0,
                    "revokedCount": 0,
                    "alreadyConsumedCount": 0,
                    "alreadyRevokedCount": 0,
                    "notFoundCount": 0,
                    "failedCount": 0,
                    "results": [],
                }
            try:
                session = self.trusted_surfaces.create_authorization_manager_session(
                    audience_digest=audience_digest,
                    items=items,
                )
                session_ref = str(session["sessionRef"])
                with self._authorization_manager_lock:
                    self._authorization_manager_sessions[session_ref] = {
                        "audience": audience,
                        "audienceDigest": audience_digest,
                        "availableCount": len(items),
                        "processing": False,
                    }
                opened = self.trusted_surfaces.launch(session_ref)
            except TrustedSurfaceError as error:
                if "session_ref" in locals():
                    with self._authorization_manager_lock:
                        self._authorization_manager_sessions.pop(session_ref, None)
                raise CardServiceError(
                    error.code,
                    str(error),
                    retryable=False,
                    stage="authorization",
                ) from error
            return {
                "schemaVersion": 1,
                "authorizationSessionRef": session_ref,
                "state": str(opened.get("state") or "open"),
                "availableCount": len(items),
            }

        session_ref = str(authorization_session_ref)
        with self._authorization_manager_lock:
            completed = self._completed_authorization_revocations.get(session_ref)
            pending = self._authorization_manager_sessions.get(session_ref)
            if completed is not None:
                if not self._authorization_session_matches(completed, audience):
                    raise CardServiceError(
                        "AUTHORIZATION_SESSION_NOT_FOUND",
                        "Authorization manager session was not found",
                        retryable=False,
                        stage="authorization",
                    )
                return json.loads(
                    json.dumps(completed["result"], ensure_ascii=False)
                )
            if pending is None or not self._authorization_session_matches(
                pending, audience
            ):
                raise CardServiceError(
                    "AUTHORIZATION_SESSION_NOT_FOUND",
                    "Authorization manager session was not found",
                    retryable=False,
                    stage="authorization",
                )
        try:
            surface = self.trusted_surfaces.get_session(session_ref)
        except TrustedSurfaceError as error:
            raise CardServiceError(
                error.code,
                str(error),
                retryable=False,
                stage="authorization",
            ) from error
        surface_state = str(surface.get("state") or "failed")
        summary = surface.get("authorizationRevocation") or {}
        if surface_state in {"open", "created"}:
            return {
                "schemaVersion": 1,
                "authorizationSessionRef": session_ref,
                "state": surface_state,
                "availableCount": int(
                    summary.get("availableCount")
                    or pending.get("availableCount")
                    or 0
                ),
            }
        if surface_state in {"cancelled", "failed"}:
            result = {
                "schemaVersion": 1,
                "authorizationSessionRef": session_ref,
                "state": surface_state,
                "availableCount": int(
                    summary.get("availableCount")
                    or pending.get("availableCount")
                    or 0
                ),
                "selectedCount": 0,
                "revokedCount": 0,
                "alreadyConsumedCount": 0,
                "alreadyRevokedCount": 0,
                "notFoundCount": 0,
                "failedCount": 0,
                "results": [],
            }
            if isinstance(surface.get("errorCode"), str):
                result["errorCode"] = surface["errorCode"]
            self.trusted_surfaces.complete_authorization_manager(session_ref)
            with self._authorization_manager_lock:
                pending = self._authorization_manager_sessions.pop(session_ref)
                self._completed_authorization_revocations[session_ref] = {
                    "audience": pending["audience"],
                    "result": result,
                }
            return json.loads(json.dumps(result, ensure_ascii=False))
        if surface_state != "approved":
            raise CardServiceError(
                "AUTHORIZATION_SESSION_INVALID",
                "Authorization manager returned an invalid state",
                retryable=False,
                stage="authorization",
            )

        with self._authorization_manager_lock:
            pending = self._authorization_manager_sessions.get(session_ref)
            if pending is None or not self._authorization_session_matches(
                pending, audience
            ):
                raise CardServiceError(
                    "AUTHORIZATION_SESSION_NOT_FOUND",
                    "Authorization manager session was not found",
                    retryable=False,
                    stage="authorization",
                )
            if pending["processing"]:
                return {
                    "schemaVersion": 1,
                    "authorizationSessionRef": session_ref,
                    "state": "processing",
                    "availableCount": int(
                        summary.get("availableCount")
                        or pending.get("availableCount")
                        or 0
                    ),
                }
            pending["processing"] = True

        selections = self.trusted_surfaces.authorization_revocation_selections(
            session_ref
        )
        results: list[dict[str, str]] = []
        try:
            for index, selection in enumerate(selections):
                disposition = "failed"
                try:
                    if selection.kind == "local_resource":
                        self._ensure_resource_runtime().revoke_local_grant(
                            resource_ref=str(selection.locator["resourceRef"]),
                            audience=audience,
                            revocation_id=f"revoke-{session_ref}-{index}",
                            expected_revocation_epoch=int(
                                selection.locator["revocationEpoch"]
                            ),
                            attestation_ref=selection.attestation_ref,
                        )
                        disposition = "revoked"
                    elif selection.kind == "network_resource":
                        self._ensure_network_resource_registry().revoke(
                            str(selection.locator["networkResourceRef"]),
                            audience,
                            revocation_id=f"revoke-{session_ref}-{index}",
                            expected_revocation_epoch=int(
                                selection.locator["revocationEpoch"]
                            ),
                            attestation_ref=selection.attestation_ref,
                        )
                        disposition = "revoked"
                    elif selection.kind == "anki_import":
                        self._ensure_study_runtime().revoke_anki_import_approval(
                            audience=audience,
                            import_intent_id=str(
                                selection.locator["importIntentId"]
                            ),
                            revocation_id=f"revoke-{session_ref}-{index}",
                            gesture_attestation_ref=selection.attestation_ref,
                        )
                        disposition = "revoked"
                    elif selection.kind == "broker_authorization":
                        verified = self.trusted_surfaces.verify_authorization_revocation(
                            attestation_ref=selection.attestation_ref,
                            audience_digest=str(pending["audienceDigest"]),
                            selection_ref=selection.selection_ref,
                            action="revoke_broker_authorization",
                        )
                        if verified is not True:
                            raise CardServiceError(
                                "TRUSTED_GESTURE_INVALID",
                                "Trusted broker revocation gesture is invalid",
                            )
                        revoked = self._revoke_active_broker_authorization(
                            expected_authorization_digest=str(
                                selection.locator["authorizationDigest"]
                            )
                        )
                        disposition = (
                            "revoked"
                            if revoked["state"] == "revoked"
                            else "not_found"
                        )
                    elif selection.kind == "operation_approval":
                        self._ensure_authorization_ledger().revoke_operation_approval(
                            operation_intent_id=str(
                                selection.locator["operationIntentId"]
                            ),
                            audience=audience,
                            revocation_attestation_digest=selection.attestation_ref,
                        )
                        disposition = "revoked"
                except (
                    ServiceResourceRuntimeError,
                    NetworkResourceRegistryError,
                    StudyRuntimeError,
                    AuthorizationLedgerError,
                ) as error:
                    disposition = self._authorization_disposition(error.code)
                except CardServiceError as error:
                    disposition = self._authorization_disposition(error.code)
                results.append(
                    {"kind": selection.kind, "disposition": disposition}
                )
        except Exception:
            with self._authorization_manager_lock:
                current = self._authorization_manager_sessions.get(session_ref)
                if current is not None:
                    current["processing"] = False
            raise

        counts = {
            disposition: sum(
                1 for item in results if item["disposition"] == disposition
            )
            for disposition in {
                "revoked",
                "already_consumed",
                "already_revoked",
                "not_found",
                "failed",
            }
        }
        result = {
            "schemaVersion": 1,
            "authorizationSessionRef": session_ref,
            "state": "completed",
            "availableCount": int(summary.get("availableCount") or len(selections)),
            "selectedCount": len(selections),
            "revokedCount": counts["revoked"],
            "alreadyConsumedCount": counts["already_consumed"],
            "alreadyRevokedCount": counts["already_revoked"],
            "notFoundCount": counts["not_found"],
            "failedCount": counts["failed"],
            "results": results,
        }
        self.trusted_surfaces.complete_authorization_manager(session_ref)
        with self._authorization_manager_lock:
            pending = self._authorization_manager_sessions.pop(session_ref)
            self._completed_authorization_revocations[session_ref] = {
                "audience": pending["audience"],
                "result": result,
            }
        return json.loads(json.dumps(result, ensure_ascii=False))

    def _managed_environment(self, task_workspace: Path | None = None) -> dict[str, str]:
        safe_keys = (
            "SYSTEMROOT",
            "WINDIR",
            "COMSPEC",
            "TEMP",
            "TMP",
            "USERPROFILE",
            "APPDATA",
            "LOCALAPPDATA",
            "PROGRAMDATA",
            "LANG",
        )
        environment = {key: os.environ[key] for key in safe_keys if key in os.environ}
        path_entries = [
            str(self.python_path.parent),
            *(str(value.parent) for value in self.managed_media_tools.values()),
            *(str(value) for value in self.managed_tool_directories),
        ]
        environment["PATH"] = os.pathsep.join(dict.fromkeys(path_entries))
        if self.runtime_package is not None:
            environment["ACG_MANAGED_RUNTIME"] = "1"
            environment["ACG_MANAGED_RUNTIME_ROOT"] = str(self.runtime_package.root)
            environment.update({name: str(path) for name, path in self.managed_media_tools.items()})
        environment["PYTHONIOENCODING"] = "utf-8"
        environment["PYTHONUTF8"] = "1"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        if task_workspace is not None:
            workspace_value = str(task_workspace)
            environment["ACG_TASK_WORKSPACE"] = workspace_value
            environment["TEMP"] = workspace_value
            environment["TMP"] = workspace_value
            environment["TMPDIR"] = workspace_value
        return environment

    def _execute_study_apkg_export(
        self,
        legacy_project: Mapping[str, Any],
        progress: Callable[[Mapping[str, Any]], None],
        cancel_event: threading.Event,
    ) -> Mapping[str, Any]:
        snapshot = self.start_task(
            "internal.export_study_apkg", {"project": copy.deepcopy(dict(legacy_project))}
        )
        task_id = str(snapshot["id"])
        last_progress: tuple[Any, Any] | None = None
        while snapshot.get("state") in ACTIVE_STATES:
            if cancel_event.is_set():
                snapshot = self.cancel_task(task_id)
            raw_progress = snapshot.get("progress")
            if isinstance(raw_progress, Mapping):
                marker = (
                    raw_progress.get("phase"),
                    raw_progress.get("overallPercent"),
                )
                if marker != last_progress:
                    progress(dict(raw_progress))
                    last_progress = marker
            if snapshot.get("state") in ACTIVE_STATES:
                time.sleep(0.05)
                snapshot = self.get_task(task_id) or snapshot
        if cancel_event.is_set() or snapshot.get("state") == "cancelled":
            raise PackageExportCancelled("APKG export was cancelled")
        if snapshot.get("state") != "succeeded":
            failure = snapshot.get("error")
            raise CardServiceError(
                str(failure.get("code") if isinstance(failure, Mapping) else "WORKER_EXITED"),
                "Managed APKG export failed",
                retryable=bool(
                    failure.get("retryable") if isinstance(failure, Mapping) else True
                ),
                stage="export",
            )
        result = self.read_result(task_id)
        if not isinstance(result, Mapping):
            raise CardServiceError(
                "WORKER_INVALID_JSON",
                "Managed APKG export returned an invalid result",
                retryable=True,
                stage="export",
            )
        return dict(result)

    def _execute_study_anki_import(
        self,
        bundle: Mapping[str, Any],
        progress: Callable[[Mapping[str, Any]], None],
        cancel_event: threading.Event,
    ) -> Mapping[str, Any]:
        snapshot = self.start_task(
            "internal.verify_study_anki_import",
            {"bundle": copy.deepcopy(dict(bundle))},
        )
        task_id = str(snapshot["id"])
        last_progress: tuple[Any, Any] | None = None
        while snapshot.get("state") in ACTIVE_STATES:
            if cancel_event.is_set():
                snapshot = self.cancel_task(task_id)
            raw_progress = snapshot.get("progress")
            if isinstance(raw_progress, Mapping):
                marker = (
                    raw_progress.get("phase"),
                    raw_progress.get("overallPercent"),
                )
                if marker != last_progress:
                    progress(
                        {
                            "stage": raw_progress.get("phase"),
                            "percent": raw_progress.get("overallPercent"),
                            "message": raw_progress.get("message"),
                        }
                    )
                    last_progress = marker
            if snapshot.get("state") in ACTIVE_STATES:
                time.sleep(0.05)
                snapshot = self.get_task(task_id) or snapshot
        if cancel_event.is_set() or snapshot.get("state") == "cancelled":
            raise AnkiImportExecutionError(
                "TASK_CANCELLED", "Anki import was cancelled"
            )
        if snapshot.get("state") != "succeeded":
            failure = snapshot.get("error")
            code = str(
                failure.get("code")
                if isinstance(failure, Mapping)
                else "WORKER_EXITED"
            )
            if code in {"WORKER_TIMEOUT", "WORKER_EXITED"}:
                code = "ANKI_OFFLINE"
            raise AnkiImportExecutionError(
                code, "Managed Anki import verification failed"
            )
        result = self.read_result(task_id)
        if not isinstance(result, Mapping):
            raise AnkiImportExecutionError(
                "ANKI_VERIFY_FAILED",
                "Managed Anki verification returned an invalid result",
            )
        return dict(result)
    def _worker_request(self, runtime: _RuntimeTask) -> dict[str, Any]:
        request = copy.deepcopy(runtime.request)
        method = str(runtime.snapshot.get("method") or "")
        if method not in {
            "runtime.export_apkg",
            "internal.export_study_apkg",
            "internal.verify_study_anki_import",
        }:
            return request
        workspace = runtime.sandbox_workspace
        if workspace is None:
            raise CardServiceError(
                "TASK_WORKSPACE_UNAVAILABLE",
                "The isolated task workspace was not created",
                retryable=False,
                stage="workspace",
            )
        if method == "internal.verify_study_anki_import":
            bundle = request.get("bundle")
            if not isinstance(bundle, Mapping) or set(request) != {"bundle"}:
                raise CardServiceError(
                    "ANKI_IMPORT_BUNDLE_INVALID",
                    "Authenticated Anki import bundle is invalid",
                    retryable=False,
                    stage="anki_import",
                )
            try:
                return materialize_anki_worker_request(
                    bundle,
                    workspace,
                    self._ensure_study_runtime().artifacts,
                    anki_connect_url=self.anki_connect_url,
                )
            except (AnkiImportExecutionError, ArtifactRegistryError) as error:
                raise CardServiceError(
                    getattr(error, "code", "PACKAGE_VERIFY_FAILED"),
                    "Authenticated APKG could not be prepared for Anki",
                    retryable=False,
                    stage="anki_import",
                ) from error
        export_root = workspace / "exports"
        try:
            export_root.mkdir(mode=0o700, exist_ok=False)
            resolved = export_root.resolve()
        except OSError as error:
            raise CardServiceError(
                "TASK_EXPORT_WORKSPACE_CREATE_FAILED",
                "Could not create the service-owned export workspace",
                retryable=False,
                stage="workspace",
            ) from error
        _assert_no_reparse_components(resolved)
        if resolved.parent != workspace.resolve():
            raise CardServiceError(
                "TASK_EXPORT_WORKSPACE_INVALID",
                "The service-owned export workspace escaped the task boundary",
                retryable=False,
                stage="workspace",
            )
        if runtime.task_sandbox_sid is not None:
            try:
                harden_task_writable_path(resolved, runtime.task_sandbox_sid)
            except WindowsSandboxAclError as error:
                raise CardServiceError(
                    "TASK_EXPORT_WORKSPACE_ACL_FAILED",
                    "Could not grant the isolated task access to its export workspace",
                    retryable=False,
                    stage="workspace",
                ) from error
        request["output_dir"] = str(resolved)
        request.pop("canonical_apkg_path", None)
        return request

    def _persist_runtime(self, runtime: _RuntimeTask) -> None:
        with runtime.lock:
            runtime.snapshot["updatedAt"] = _now_ms()
            self.store.write_task(str(runtime.snapshot["id"]), runtime.snapshot)

    def _set_progress(self, runtime: _RuntimeTask, payload: dict[str, Any]) -> None:
        with runtime.lock:
            previous = runtime.snapshot.get("progress") or {}
            raw_percent = payload.get("percent")
            percent = int(raw_percent) if isinstance(raw_percent, (int, float)) else None
            previous_percent = previous.get("overallPercent")
            if percent is not None and isinstance(previous_percent, (int, float)):
                percent = max(int(previous_percent), percent)
            now = _now_ms()
            runtime.snapshot["progress"] = {
                "phase": str(payload.get("stage") or "running"),
                "phaseLabel": str(payload.get("stage") or "Running legacy worker"),
                "phasePercent": percent,
                "overallPercent": percent,
                "message": _safe_error(str(payload.get("message") or "Worker progress"), 500),
                "lastProgressAt": now,
            }
            runtime.snapshot["updatedAt"] = now
            self.store.write_task(str(runtime.snapshot["id"]), runtime.snapshot)

    def _terminate(self, process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        process.terminate()
        deadline = time.monotonic() + self.cancellation_grace_seconds
        while process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        if process.poll() is None:
            process.kill()
            try:
                process.wait(timeout=self.cancellation_grace_seconds)
            except subprocess.TimeoutExpired:
                pass

    def _run_task(self, runtime: _RuntimeTask, policy: MethodPolicy) -> None:
        task_id = str(runtime.snapshot["id"])
        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        stdout_bytes = 0
        stderr_bytes = 0
        stream_limit_error: list[str] = []
        control_channel_error: list[CardServiceError] = []
        workspace_limit_error: list[CardServiceError] = []
        worker_error: list[dict[str, Any]] = []
        restricted_child_exit: list[dict[str, Any]] = []
        try:
            with runtime.lock:
                if runtime.cancel_event.is_set():
                    raise CardServiceError("TASK_CANCELLED", "Task was cancelled before it started")
                runtime.snapshot["state"] = "running"
                runtime.snapshot["progress"] = {
                    "phase": "starting_worker",
                    "phaseLabel": "Starting managed legacy worker",
                    "phasePercent": 0,
                    "overallPercent": 0,
                    "message": "Starting managed legacy worker",
                    "lastProgressAt": _now_ms(),
                }
                self._persist_runtime(runtime)
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            try:
                if self.runtime_package is not None:
                    self.runtime_package.verify()
                self.runtime_manifest.verify()
                self.runtime_manifest.verify_serialized(self.runtime_manifest_path)
            except (RuntimeManifestError, RuntimePackageError) as error:
                raise CardServiceError(error.code, str(error)) from error
            if runtime.sandbox_workspace is None:
                raise CardServiceError(
                    "TASK_WORKSPACE_UNAVAILABLE",
                    "The isolated task workspace was not created",
                    retryable=False,
                    stage="workspace",
                )
            worker_request = self._worker_request(runtime)
            initial_workspace_usage = _task_workspace_usage(
                runtime.sandbox_workspace,
                byte_limit=self.task_workspace_limit_bytes,
                entry_limit=self.task_workspace_entry_limit,
            )
            self._enforce_workspace_capacity()
            attach_broker = runtime.broker_handler_factory is not None and (
                policy.requires_broker or runtime.broker_method_blocker is None
            )
            if attach_broker:
                if runtime.broker_handler_factory is None:
                    raise CardServiceError("BROKER_REQUIRED", "Task-owned model/TTS broker is unavailable")
                try:
                    handler = runtime.broker_handler_factory(
                        task_id,
                        str(runtime.snapshot["method"]),
                        copy.deepcopy(worker_request),
                    )
                except Exception as error:
                    raise CardServiceError(
                        "BROKER_AUTHORIZATION_UNAVAILABLE",
                        "Task broker authorization became unavailable before Worker launch",
                    ) from error
                runtime.broker_session = TaskBrokerChannel(
                    task_id=task_id,
                    handler=handler,
                    transport="authenticated_stdio_json",
                )
            worker_command = [
                str(self.python_path),
                "-I",
                "-B",
                str(self.bootstrap_path),
                str(self.worker_path),
                policy.worker_command,
                self.worker_sha256,
                "@stdin" if self.use_restricted_launcher else str(self.runtime_manifest_path),
                self.runtime_manifest.digest,
            ]
            sandbox_attestation_key = os.urandom(32) if self.use_restricted_launcher else b""
            sandbox_attestation_seen = threading.Event()
            sandbox_attestation_errors: list[str] = []
            if self.use_restricted_launcher:
                process_command = [
                    str(self.python_path),
                    "-I",
                    "-B",
                    str(self.restricted_launcher_path),
                    "--task-id",
                    task_id,
                    "--cwd",
                    str(runtime.sandbox_workspace),
                ]
                if self.runtime_sandbox_sid is not None and runtime.task_sandbox_sid is not None:
                    process_command.extend(
                        [
                            "--runtime-sid",
                            self.runtime_sandbox_sid,
                            "--task-sid",
                            runtime.task_sandbox_sid,
                        ]
                    )
                process_command.extend(["--", *worker_command])
                process_cwd = str(self.restricted_launcher_path.parent)
            else:
                process_command = worker_command
                process_cwd = str(runtime.sandbox_workspace)
            process = subprocess.Popen(
                process_command,
                cwd=process_cwd,
                env=self._managed_environment(runtime.sandbox_workspace),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
                creationflags=creationflags,
            )
            runtime.process = process
            process_group = TaskOwnedProcessGroup(
                memory_limit_bytes=self.task_memory_limit_bytes,
                active_process_limit=self.task_active_process_limit,
            )
            runtime.process_group = process_group
            try:
                process_group.assign(process)
            except ProcessIsolationError:
                self._terminate(process)
                raise
            with runtime.lock:
                runtime.snapshot["isolation"] = {
                    "taskOwnedJobObject": process_group.enabled,
                    "killOnClose": process_group.enabled,
                    "activeProcessLimit": self.task_active_process_limit,
                    "memoryLimitBytes": self.task_memory_limit_bytes,
                    "authenticatedBrokerStdio": runtime.broker_session is not None,
                    "restrictedPrimaryToken": None if self.use_restricted_launcher else False,
                    "createdSuspended": None if self.use_restricted_launcher else False,
                    "jobInheritedBeforeResume": None if self.use_restricted_launcher else False,
                    "filesystemRestrictedByDedicatedSidDacl": False,
                    "runtimePackageDacl": self.runtime_package_dacl,
                    "taskWorkspaceDacl": runtime.task_sandbox_sid is not None,
                    "taskWorkspaceWorkingDirectory": True,
                    "taskWorkspaceLimitBytes": self.task_workspace_limit_bytes,
                    "taskWorkspaceEntryLimit": self.task_workspace_entry_limit,
                    "taskWorkspaceServiceLimitBytes": self.task_workspace_service_limit_bytes,
                    "taskWorkspaceServiceEntryLimit": self.task_workspace_service_entry_limit,
                    "taskWorkspaceVolumeReserveBytes": self.task_workspace_volume_reserve_bytes,
                    "taskWorkspaceLogicalBytes": initial_workspace_usage.logical_bytes,
                    "taskWorkspaceEntries": initial_workspace_usage.entry_count,
                    "networkRestricted": None if self.use_restricted_launcher else False,
                    "fixedMediaToolPolicy": self.runtime_package is not None,
                }
                self._persist_runtime(runtime)
            assert process.stdin is not None and process.stdout is not None and process.stderr is not None
            stdin_lock = threading.RLock()
            launch_envelope: dict[str, Any] = {
                "schemaVersion": 1,
                "request": worker_request,
            }
            if runtime.broker_session is not None:
                launch_envelope["brokerDescriptor"] = runtime.broker_session.descriptor()

            def read_stdout() -> None:
                nonlocal stdout_bytes
                while True:
                    chunk = process.stdout.read(65_536)
                    if not chunk:
                        return
                    stdout_bytes += len(chunk.encode("utf-8", errors="replace"))
                    if stdout_bytes > self.max_stdout_bytes:
                        stream_limit_error.append("Worker stdout exceeded the Card Service limit")
                        self._terminate(process)
                        return
                    stdout_parts.append(chunk)

            def read_stderr_loop() -> None:
                nonlocal stderr_bytes
                for line in process.stderr:
                    stderr_bytes += len(line.encode("utf-8", errors="replace"))
                    if stderr_bytes > self.max_stderr_bytes:
                        stream_limit_error.append("Worker stderr exceeded the Card Service limit")
                        self._terminate(process)
                        return
                    stripped = line.rstrip("\r\n")
                    if stripped.startswith(SANDBOX_ATTESTATION_PREFIX):
                        try:
                            attestation = json.loads(stripped[len(SANDBOX_ATTESTATION_PREFIX) :])
                            if sandbox_attestation_seen.is_set():
                                raise ValueError("duplicate attestation")
                            verified_attestation = _verify_sandbox_attestation(
                                attestation,
                                key=sandbox_attestation_key,
                                task_id=task_id,
                                expected_filesystem_restricted=self.runtime_package_dacl,
                                expected_network_restricted=self.runtime_package_dacl,
                                expected_runtime_sid_digest=(
                                    _sid_binding_digest(
                                        "study.runtime-appcontainer-sid.v1",
                                        self.runtime_sandbox_sid,
                                    )
                                    if self.runtime_sandbox_sid is not None
                                    else None
                                ),
                                expected_task_sid_digest=(
                                    _sid_binding_digest(
                                        "study.task-capability-sid.v1",
                                        runtime.task_sandbox_sid,
                                    )
                                    if runtime.task_sandbox_sid is not None
                                    else None
                                ),
                            )
                            with runtime.lock:
                                runtime.snapshot["isolation"].update(verified_attestation)
                                self._persist_runtime(runtime)
                            sandbox_attestation_seen.set()
                        except (TypeError, ValueError):
                            sandbox_attestation_errors.append("Restricted launcher attestation was invalid")
                            self._terminate(process)
                            return
                        continue
                    if stripped.startswith(BROKER_REQUEST_PREFIX):
                        if runtime.broker_session is None:
                            stream_limit_error.append("Worker requested an unavailable Card Service broker")
                            self._terminate(process)
                            return
                        try:
                            broker_request = json.loads(stripped[len(BROKER_REQUEST_PREFIX) :])
                            if not isinstance(broker_request, dict):
                                raise ValueError("not an object")
                            broker_response = runtime.broker_session.process_message(broker_request)
                            encoded_response = json.dumps(
                                broker_response,
                                ensure_ascii=False,
                                sort_keys=True,
                                separators=(",", ":"),
                            )
                            if len(encoded_response.encode("utf-8")) > runtime.broker_session.max_message_bytes:
                                raise ValueError("response too large")
                            with stdin_lock:
                                process.stdin.write(BROKER_RESPONSE_PREFIX + encoded_response + "\n")
                                process.stdin.flush()
                        except (OSError, ValueError) as error:
                            stream_limit_error.append(f"Worker broker transport failed: {error}")
                            self._terminate(process)
                            return
                        continue
                    if stripped.startswith(PROGRESS_PREFIX):
                        try:
                            payload = json.loads(stripped[len(PROGRESS_PREFIX) :])
                        except ValueError:
                            continue
                        if isinstance(payload, dict):
                            self._set_progress(runtime, payload)
                        continue
                    if stripped.startswith(RESTRICTED_CHILD_EXIT_PREFIX):
                        try:
                            payload = json.loads(stripped[len(RESTRICTED_CHILD_EXIT_PREFIX) :])
                        except ValueError:
                            payload = {
                                "error_code": "RESTRICTED_CHILD_FAILED",
                                "message": "Restricted worker failed before returning a structured error",
                            }
                        if isinstance(payload, dict):
                            restricted_child_exit.append(payload)
                        continue
                    if stripped.startswith(ERROR_PREFIX):
                        try:
                            payload = json.loads(stripped[len(ERROR_PREFIX) :])
                        except ValueError:
                            payload = {"message": "Legacy worker returned an invalid error envelope"}
                        if isinstance(payload, dict):
                            worker_error.append(payload)
                        continue
                    stderr_parts.append(stripped)

            def read_stderr() -> None:
                try:
                    read_stderr_loop()
                except Exception:
                    control_channel_error.append(
                        CardServiceError(
                            "WORKER_CONTROL_CHANNEL_FAILED",
                            "Managed Worker control channel failed unexpectedly",
                            retryable=True,
                            stage="runtime_control",
                        )
                    )
                    self._terminate(process)

            readers = [
                threading.Thread(target=read_stdout, daemon=True, name=f"card-stdout-{task_id}"),
                threading.Thread(target=read_stderr, daemon=True, name=f"card-stderr-{task_id}"),
            ]
            for reader in readers:
                reader.start()

            def write_worker_control(value: str, *, stage: str) -> None:
                try:
                    with stdin_lock:
                        process.stdin.write(value)
                        process.stdin.flush()
                except OSError as error:
                    try:
                        process.wait(timeout=0.5)
                    except subprocess.TimeoutExpired:
                        pass
                    for reader in readers:
                        reader.join(timeout=0.5)
                    payload = worker_error[-1] if worker_error else {}
                    stderr_message = next((line for line in reversed(stderr_parts) if line), "")
                    if not payload and not stderr_message and restricted_child_exit:
                        payload = restricted_child_exit[-1]
                    if payload or stderr_message:
                        raise _worker_failure(
                            payload,
                            stderr_message or "Managed Worker exited during startup",
                        ) from error
                    raise CardServiceError(
                        "WORKER_CONTROL_CHANNEL_CLOSED",
                        f"Managed Worker closed its control channel during {stage}",
                        retryable=False,
                        stage="runtime_startup",
                    ) from error

            deadline = time.monotonic() + policy.timeout_seconds
            if self.use_restricted_launcher:
                start_key = base64.urlsafe_b64encode(sandbox_attestation_key).decode("ascii").rstrip("=")
                write_worker_control(f"START {start_key}\n", stage="sandbox handshake")
                handshake_deadline = min(deadline, time.monotonic() + 5.0)
                while (
                    not sandbox_attestation_seen.is_set()
                    and process.poll() is None
                    and not sandbox_attestation_errors
                    and not stream_limit_error
                    and not runtime.cancel_event.is_set()
                    and time.monotonic() < handshake_deadline
                ):
                    time.sleep(0.01)
                if process.poll() is None and not sandbox_attestation_seen.is_set():
                    self._terminate(process)
                    if runtime.cancel_event.is_set():
                        raise CardServiceError("TASK_CANCELLED", "Task cancelled")
                    if time.monotonic() >= deadline:
                        raise CardServiceError(
                            "TASK_TIMEOUT",
                            f"Task exceeded its {policy.timeout_seconds:g} second timeout",
                        )
                    raise CardServiceError(
                        "SANDBOX_ATTESTATION_FAILED",
                        sandbox_attestation_errors[-1]
                        if sandbox_attestation_errors
                        else "Restricted launcher did not complete its pre-resume handshake",
                    )
                if sandbox_attestation_seen.is_set():
                    write_worker_control(
                        json.dumps(
                            self.runtime_manifest.value,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                        + "\n",
                        stage="runtime manifest transfer",
                    )
            if process.poll() is None:
                write_worker_control(
                    json.dumps(launch_envelope, ensure_ascii=False, separators=(",", ":")) + "\n",
                    stage="launch envelope transfer",
                )
            next_workspace_check = time.monotonic()
            next_service_capacity_check = next_workspace_check + 1.0
            while process.poll() is None:
                if runtime.cancel_event.is_set():
                    self._terminate(process)
                    break
                now = time.monotonic()
                if now >= deadline:
                    self._terminate(process)
                    raise CardServiceError("TASK_TIMEOUT", f"Task exceeded its {policy.timeout_seconds:g} second timeout")
                if now >= next_workspace_check:
                    try:
                        _task_workspace_usage(
                            runtime.sandbox_workspace,
                            byte_limit=self.task_workspace_limit_bytes,
                            entry_limit=self.task_workspace_entry_limit,
                        )
                    except CardServiceError as error:
                        workspace_limit_error.append(error)
                        self._terminate(process)
                        break
                    next_workspace_check = now + 0.1
                if now >= next_service_capacity_check:
                    try:
                        self._enforce_workspace_capacity()
                    except CardServiceError as error:
                        workspace_limit_error.append(error)
                        self._terminate(process)
                        break
                    next_service_capacity_check = now + 1.0
                time.sleep(0.02)
            for reader in readers:
                reader.join(timeout=2.0)
            if runtime.cancel_event.is_set():
                raise CardServiceError("TASK_CANCELLED", "Task cancelled")
            if workspace_limit_error:
                raise workspace_limit_error[0]
            if control_channel_error:
                raise control_channel_error[0]
            if stream_limit_error:
                raise CardServiceError("WORKER_OUTPUT_LIMIT", stream_limit_error[0])
            if process.returncode != 0:
                payload = worker_error[-1] if worker_error else {}
                stderr_message = next((line for line in reversed(stderr_parts) if line), "")
                if not payload and not stderr_message and restricted_child_exit:
                    payload = restricted_child_exit[-1]
                raise _worker_failure(payload, stderr_message or "Legacy worker failed")
            if self.use_restricted_launcher and (
                sandbox_attestation_errors or not sandbox_attestation_seen.is_set()
            ):
                raise CardServiceError(
                    "SANDBOX_ATTESTATION_FAILED",
                    sandbox_attestation_errors[-1]
                    if sandbox_attestation_errors
                    else "Restricted launcher did not prove its pre-resume Job binding",
                )
            final_workspace_usage = _task_workspace_usage(
                runtime.sandbox_workspace,
                byte_limit=self.task_workspace_limit_bytes,
                entry_limit=self.task_workspace_entry_limit,
            )
            self._enforce_workspace_capacity()
            with runtime.lock:
                runtime.snapshot["isolation"]["taskWorkspaceLogicalBytes"] = final_workspace_usage.logical_bytes
                runtime.snapshot["isolation"]["taskWorkspaceEntries"] = final_workspace_usage.entry_count
                self._persist_runtime(runtime)
            raw_result = "".join(stdout_parts).strip().lstrip("\ufeff")
            if not raw_result:
                raise CardServiceError("WORKER_EMPTY_RESULT", "Legacy worker returned no JSON result")
            try:
                result = json.loads(raw_result)
            except ValueError as error:
                raise CardServiceError("WORKER_INVALID_JSON", "Legacy worker returned invalid JSON") from error
            secret_path = _find_secret_path(result)
            if secret_path:
                raise CardServiceError("SECRET_IN_RESULT", "Legacy worker result contained secret-bearing material")
            result_ref = self.store.write_result(task_id, result)
            self._release_workspace_reservation(task_id)
            with runtime.lock:
                runtime.snapshot["state"] = "succeeded"
                runtime.snapshot["resultRef"] = result_ref
                runtime.snapshot["error"] = None
                runtime.snapshot["progress"] = {
                    "phase": "completed",
                    "phaseLabel": "Completed",
                    "phasePercent": 100,
                    "overallPercent": 100,
                    "message": "Task completed",
                    "lastProgressAt": _now_ms(),
                }
                self._persist_runtime(runtime)
        except CardServiceError as error:
            if runtime.process is not None and runtime.process.poll() is None:
                self._terminate(runtime.process)
            self._release_workspace_reservation(task_id)
            state = "cancelled" if error.code == "TASK_CANCELLED" else "failed"
            with runtime.lock:
                runtime.snapshot["state"] = state
                failure: dict[str, Any] = {
                    "code": error.code,
                    "message": _safe_error(str(error)),
                    "retryable": (
                        error.retryable
                        if error.retryable is not None
                        else error.code in {"TASK_CANCELLED", "TASK_TIMEOUT", "WORKER_FAILED"}
                    ),
                }
                if error.stage is not None:
                    failure["stage"] = error.stage
                if error.fallbacks:
                    failure["fallbacks"] = list(error.fallbacks)
                runtime.snapshot["error"] = failure
                runtime.snapshot["progress"]["message"] = _safe_error(str(error), 500)
                self._persist_runtime(runtime)
        except Exception as error:  # defensive service boundary
            if runtime.process is not None and runtime.process.poll() is None:
                self._terminate(runtime.process)
            self._release_workspace_reservation(task_id)
            with runtime.lock:
                runtime.snapshot["state"] = "failed"
                runtime.snapshot["error"] = {
                    "code": "CARD_SERVICE_INTERNAL",
                    "message": _safe_error(str(error)),
                    "retryable": False,
                }
                self._persist_runtime(runtime)
        finally:
            runtime.request.clear()
            if runtime.process is not None and runtime.process.stdin is not None:
                try:
                    runtime.process.stdin.close()
                except OSError:
                    pass
            runtime.process = None
            if runtime.broker_session is not None:
                runtime.broker_session.close()
                runtime.broker_session = None
            if runtime.process_group is not None:
                try:
                    runtime.process_group.close()
                except ProcessIsolationError:
                    pass
                runtime.process_group = None
            self._release_workspace_reservation(task_id)
