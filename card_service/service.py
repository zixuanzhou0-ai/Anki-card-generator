from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qsl, urlsplit

from workers.acg.secret_scrub import is_runtime_secret_key, is_sensitive_url_query_key

from .broker_ipc import BROKER_REQUEST_PREFIX, BROKER_RESPONSE_PREFIX, TaskBrokerChannel
from .process_isolation import ProcessIsolationError, TaskOwnedProcessGroup
from .runtime_manifest import (
    ManagedRuntimeManifest,
    RuntimeManifestError,
    managed_tool_runtime_entries,
    worker_runtime_entries,
)
from .runtime_package import ManagedRuntimePackage, RuntimePackageError
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
    runtime_sandbox_sid,
    verify_runtime_tree_dacl,
)


SCHEMA_VERSION = 1
PROGRESS_PREFIX = "__ANKI_CARD_PROGRESS__"
ERROR_PREFIX = "__ANKI_CARD_ERROR__"
SANDBOX_ATTESTATION_PREFIX = "__ANKI_CARD_SANDBOX_ATTESTATION__"
RESTRICTED_CHILD_EXIT_PREFIX = "__ANKI_CARD_RESTRICTED_CHILD_EXIT__"
TERMINAL_STATES = frozenset({"succeeded", "failed", "cancelled", "interrupted"})
ACTIVE_STATES = frozenset({"queued", "running", "cancelling"})
BrokerOperationHandler = Callable[[str, dict[str, Any]], Any]
BrokerHandlerFactory = Callable[[str, str, dict[str, Any]], BrokerOperationHandler]


class CardServiceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class MethodPolicy:
    worker_command: str
    timeout_seconds: float
    cancellable: bool = True
    requires_broker: bool = False


METHOD_POLICIES: dict[str, MethodPolicy] = {
    "runtime.check_environment": MethodPolicy("check_env", 60.0),
    "runtime.extract_learning_points": MethodPolicy("extract_learning_points", 300.0, requires_broker=True),
    "runtime.generate_cards": MethodPolicy("generate_cards_from_learning_points", 420.0, requires_broker=True),
    "runtime.generate_legacy_project": MethodPolicy("generate", 420.0, requires_broker=True),
    "runtime.export_apkg": MethodPolicy("export", 600.0, requires_broker=True),
    "runtime.verify_anki_import": MethodPolicy("verify_anki_import", 120.0),
}


def _now_ms() -> int:
    return int(time.time() * 1000)


def _canonical_fingerprint(value: Any) -> str:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()


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


def _safe_error(message: str, limit: int = 2_000) -> str:
    value = str(message).replace("\x00", "").strip()
    value = re.sub(r"(?i)(?:[a-z]:\\|\\\\)[^\r\n\t\"<>|]+", "<local-path>", value)
    return value[:limit] or "Card Service task failed"


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
        broker_handler_factory: BrokerHandlerFactory | None = None,
        use_restricted_launcher: bool | None = None,
    ) -> None:
        repository_root = Path(__file__).resolve().parent.parent
        self.runtime_package: ManagedRuntimePackage | None = None
        self.runtime_trust_policy: RuntimePackageTrustPolicy | None = None
        self.runtime_sandbox_sid: str | None = None
        self.runtime_package_dacl = False
        if runtime_package is None and runtime_trust_policy is not None:
            raise CardServiceError(
                "RUNTIME_TRUST_POLICY_CONFLICT",
                "Runtime trust policy is only valid with a packaged runtime",
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
        )
        self.method_policies = dict(method_policies or METHOD_POLICIES)
        self.max_stdout_bytes = max(1, int(max_stdout_bytes))
        self.max_stderr_bytes = max(1, int(max_stderr_bytes))
        self.cancellation_grace_seconds = max(0.1, float(cancellation_grace_seconds))
        self.task_memory_limit_bytes = max(64 * 1024 * 1024, int(task_memory_limit_bytes))
        self.task_active_process_limit = max(1, int(task_active_process_limit))
        self.broker_handler_factory = broker_handler_factory
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
            self.runtime_manifest = ManagedRuntimeManifest(runtime_entries)
            self.runtime_manifest_path = (self.store.root / "runtime" / "manifest-v1.json").resolve()
            self.runtime_manifest.write(self.runtime_manifest_path)
        except RuntimeManifestError as error:
            raise CardServiceError(error.code, str(error)) from error
        self._tasks: dict[str, _RuntimeTask] = {}
        self._tasks_lock = threading.RLock()
        self._recover_orphaned_tasks()

    def capabilities(self) -> dict[str, Any]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "service": "codex-study-card-service",
            "transport": "local-stdio",
            "methods": sorted(self.method_policies),
            "methodAvailability": {
                method: {
                    "available": not policy.requires_broker,
                    "blocker": (
                        None
                        if not policy.requires_broker
                        else "model_tts_broker_not_ready"
                    ),
                }
                for method, policy in sorted(self.method_policies.items())
            },
            "taskMethods": ["task.get", "task.cancel", "task.list_recoverable", "task.read_result"],
            "systemMethods": ["system.get_capabilities", "system.open_local_settings", "system.get_trusted_surface"],
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
                "appContainerOrRestrictedSidDacl": self.runtime_package_dacl,
                "forcedOutboundBroker": self.runtime_package_dacl,
                "complete": False,
            },
            "modelTtsBroker": {
                "credentialManager": os.name == "nt",
                "reservationLedger": True,
                "taskOwnedWorkerTransport": self.broker_handler_factory is not None,
                "complete": False,
            },
            "trustedSurfaces": self.trusted_surfaces.capabilities(),
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

    def start_task(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        policy = self.method_policies.get(method)
        if policy is None:
            raise CardServiceError("METHOD_NOT_ALLOWED", f"Card Service method is not allowed: {method}")
        if policy.requires_broker:
            raise CardServiceError(
                "BROKER_REQUIRED",
                "This operation is blocked until the task-owned model/TTS broker is available",
            )
        request = dict(params or {})
        secret_path = _find_secret_path(request)
        if secret_path:
            raise CardServiceError(
                "SECRET_IN_REQUEST",
                f"Secret-bearing requests are not accepted by the legacy Worker boundary ({secret_path})",
            )
        task_id = str(uuid.uuid4())
        sandbox_workspace: Path | None = None
        task_sid: str | None = None
        if self.runtime_package_dacl:
            try:
                sandbox_workspace, task_sid = create_task_workspace(
                    (self.store.root / "sandboxes").resolve(),
                    task_id,
                )
            except WindowsSandboxAclError as error:
                raise CardServiceError(error.code, str(error)) from error
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
        runtime = _RuntimeTask(
            snapshot=snapshot,
            request=request,
            sandbox_workspace=sandbox_workspace,
            task_sandbox_sid=task_sid,
        )
        with self._tasks_lock:
            self._tasks[task_id] = runtime
        self.store.write_task(task_id, snapshot)
        thread = threading.Thread(target=self._run_task, args=(runtime, policy), daemon=True, name=f"card-task-{task_id}")
        thread.start()
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
        if method == "task.get":
            return self.get_task(str(values.get("taskId") or ""))
        if method == "task.cancel":
            return self.cancel_task(str(values.get("taskId") or ""))
        if method == "task.list_recoverable":
            return {"tasks": self.list_recoverable_tasks()}
        if method == "task.read_result":
            return self.read_result(str(values.get("taskId") or ""))
        if method == "system.open_local_settings":
            try:
                session = self.trusted_surfaces.create_local_settings_session(
                    profile_ref=str(values.get("profileRef") or ""),
                    capability=str(values.get("capability") or ""),
                )
                return self.trusted_surfaces.launch(str(session["sessionRef"]))
            except TrustedSurfaceError as error:
                raise CardServiceError(error.code, str(error)) from error
        if method == "system.get_trusted_surface":
            try:
                return self.trusted_surfaces.get_session(str(values.get("sessionRef") or ""))
            except TrustedSurfaceError as error:
                raise CardServiceError(error.code, str(error)) from error
        return self.start_task(method, values)

    def _managed_environment(self) -> dict[str, str]:
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
        path_entries = [str(self.python_path.parent), *(str(value) for value in self.managed_tool_directories)]
        environment["PATH"] = os.pathsep.join(dict.fromkeys(path_entries))
        environment["PYTHONIOENCODING"] = "utf-8"
        environment["PYTHONUTF8"] = "1"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        return environment

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

    def _run_task(self, runtime: _RuntimeTask, policy: MethodPolicy) -> None:
        task_id = str(runtime.snapshot["id"])
        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        stdout_bytes = 0
        stderr_bytes = 0
        stream_limit_error: list[str] = []
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
            worker_command = [
                str(self.python_path),
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
                    str(self.restricted_launcher_path),
                    "--task-id",
                    task_id,
                    "--cwd",
                    str(self.worker_path.parent),
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
                process_cwd = str(self.worker_path.parent)
            process = subprocess.Popen(
                process_command,
                cwd=process_cwd,
                env=self._managed_environment(),
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
            if self.broker_handler_factory is not None:
                handler = self.broker_handler_factory(task_id, str(runtime.snapshot["method"]), dict(runtime.request))
                runtime.broker_session = TaskBrokerChannel(
                    task_id=task_id,
                    handler=handler,
                    transport="authenticated_stdio_json",
                )
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
                    "networkRestricted": None if self.use_restricted_launcher else False,
                }
                self._persist_runtime(runtime)
            assert process.stdin is not None and process.stdout is not None and process.stderr is not None
            stdin_lock = threading.RLock()
            if self.use_restricted_launcher:
                start_key = base64.urlsafe_b64encode(sandbox_attestation_key).decode("ascii").rstrip("=")
                process.stdin.write(f"START {start_key}\n")
                process.stdin.flush()
            launch_envelope: dict[str, Any] = {
                "schemaVersion": 1,
                "request": runtime.request,
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

            def read_stderr() -> None:
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

            readers = [
                threading.Thread(target=read_stdout, daemon=True, name=f"card-stdout-{task_id}"),
                threading.Thread(target=read_stderr, daemon=True, name=f"card-stderr-{task_id}"),
            ]
            for reader in readers:
                reader.start()
            deadline = time.monotonic() + policy.timeout_seconds
            if self.use_restricted_launcher:
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
                    with stdin_lock:
                        process.stdin.write(
                            json.dumps(
                                self.runtime_manifest.value,
                                ensure_ascii=False,
                                sort_keys=True,
                                separators=(",", ":"),
                            )
                            + "\n"
                        )
                        process.stdin.flush()
            if process.poll() is None:
                with stdin_lock:
                    process.stdin.write(
                        json.dumps(launch_envelope, ensure_ascii=False, separators=(",", ":")) + "\n"
                    )
                    process.stdin.flush()
            while process.poll() is None:
                if runtime.cancel_event.is_set():
                    self._terminate(process)
                    break
                if time.monotonic() >= deadline:
                    self._terminate(process)
                    raise CardServiceError("TASK_TIMEOUT", f"Task exceeded its {policy.timeout_seconds:g} second timeout")
                time.sleep(0.02)
            for reader in readers:
                reader.join(timeout=2.0)
            if runtime.cancel_event.is_set():
                raise CardServiceError("TASK_CANCELLED", "Task cancelled")
            if stream_limit_error:
                raise CardServiceError("WORKER_OUTPUT_LIMIT", stream_limit_error[0])
            if process.returncode != 0:
                payload = worker_error[-1] if worker_error else {}
                stderr_message = next((line for line in reversed(stderr_parts) if line), "")
                if not payload and not stderr_message and restricted_child_exit:
                    payload = restricted_child_exit[-1]
                message = payload.get("message") or stderr_message or "Legacy worker failed"
                raise CardServiceError(str(payload.get("error_code") or "WORKER_FAILED"), _safe_error(str(message)))
            if self.use_restricted_launcher and (
                sandbox_attestation_errors or not sandbox_attestation_seen.is_set()
            ):
                raise CardServiceError(
                    "SANDBOX_ATTESTATION_FAILED",
                    sandbox_attestation_errors[-1]
                    if sandbox_attestation_errors
                    else "Restricted launcher did not prove its pre-resume Job binding",
                )
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
            state = "cancelled" if error.code == "TASK_CANCELLED" else "failed"
            with runtime.lock:
                runtime.snapshot["state"] = state
                runtime.snapshot["error"] = {
                    "code": error.code,
                    "message": _safe_error(str(error)),
                    "retryable": error.code in {"TASK_CANCELLED", "TASK_TIMEOUT", "WORKER_FAILED"},
                }
                runtime.snapshot["progress"]["message"] = _safe_error(str(error), 500)
                self._persist_runtime(runtime)
        except Exception as error:  # defensive service boundary
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
