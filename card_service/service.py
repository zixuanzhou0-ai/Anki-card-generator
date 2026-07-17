from __future__ import annotations

import hashlib
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
from .storage import AtomicJsonStore
from .trusted_surfaces import TrustedSurfaceError, TrustedSurfaceManager


SCHEMA_VERSION = 1
PROGRESS_PREFIX = "__ANKI_CARD_PROGRESS__"
ERROR_PREFIX = "__ANKI_CARD_ERROR__"
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


@dataclass
class _RuntimeTask:
    snapshot: dict[str, Any]
    request: dict[str, Any]
    cancel_event: threading.Event = field(default_factory=threading.Event)
    process: subprocess.Popen[str] | None = None
    process_group: TaskOwnedProcessGroup | None = None
    broker_session: TaskBrokerChannel | None = None
    lock: threading.RLock = field(default_factory=threading.RLock)


class CardService:
    """Restricted task API that supervises the existing one-shot Python worker."""

    def __init__(
        self,
        *,
        state_dir: str | Path,
        worker_path: str | Path | None = None,
        python_path: str | Path | None = None,
        managed_tool_directories: list[str | Path] | None = None,
        method_policies: dict[str, MethodPolicy] | None = None,
        max_stdout_bytes: int = 64 * 1024 * 1024,
        max_stderr_bytes: int = 8 * 1024 * 1024,
        cancellation_grace_seconds: float = 2.0,
        task_memory_limit_bytes: int = 2 * 1024 * 1024 * 1024,
        task_active_process_limit: int = 16,
        broker_handler_factory: BrokerHandlerFactory | None = None,
    ) -> None:
        repository_root = Path(__file__).resolve().parent.parent
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
        self.worker_sha256 = self._file_sha256(self.worker_path)
        self.bootstrap_path = (Path(__file__).resolve().parent / "worker_bootstrap.py").resolve()
        self.broker_client_path = (repository_root / "workers" / "acg" / "broker_client.py").resolve()
        try:
            runtime_entries = worker_runtime_entries(
                self.worker_path,
                self.bootstrap_path,
                self.broker_client_path,
                self.python_path,
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
            "processIsolation": {
                "taskOwnedJobObject": os.name == "nt",
                "killOnClose": os.name == "nt",
                "noBreakawayRequested": os.name == "nt",
                "activeProcessLimit": self.task_active_process_limit,
                "memoryLimitBytes": self.task_memory_limit_bytes,
                "appContainerOrRestrictedSidDacl": False,
                "forcedOutboundBroker": False,
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
        runtime = _RuntimeTask(snapshot=snapshot, request=request)
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
                self.runtime_manifest.verify()
            except RuntimeManifestError as error:
                raise CardServiceError(error.code, str(error)) from error
            process = subprocess.Popen(
                [
                    str(self.python_path),
                    str(self.bootstrap_path),
                    str(self.worker_path),
                    policy.worker_command,
                    self.worker_sha256,
                    str(self.runtime_manifest_path),
                    self.runtime_manifest.digest,
                ],
                cwd=str(self.worker_path.parent),
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
                }
                self._persist_runtime(runtime)
            assert process.stdin is not None and process.stdout is not None and process.stderr is not None
            launch_envelope: dict[str, Any] = {
                "schemaVersion": 1,
                "request": runtime.request,
            }
            if runtime.broker_session is not None:
                launch_envelope["brokerDescriptor"] = runtime.broker_session.descriptor()
            process.stdin.write(json.dumps(launch_envelope, ensure_ascii=False, separators=(",", ":")) + "\n")
            process.stdin.flush()
            stdin_lock = threading.RLock()

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
                message = payload.get("message") or next((line for line in reversed(stderr_parts) if line), "Legacy worker failed")
                raise CardServiceError(str(payload.get("error_code") or "WORKER_FAILED"), _safe_error(str(message)))
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
