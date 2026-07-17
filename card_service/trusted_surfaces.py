from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .credentials import PROFILE_REF_PATTERN
from .process_isolation import ProcessIsolationError, TaskOwnedProcessGroup
from .storage import AtomicJsonStore


class TrustedSurfaceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class _SurfaceProcess:
    process: subprocess.Popen[str]
    process_group: TaskOwnedProcessGroup


class TrustedSurfaceManager:
    """Launches digest-pinned local settings/consent windows outside model context."""

    def __init__(
        self,
        *,
        state_dir: str | Path,
        python_path: str | Path | None = None,
        surface_path: str | Path | None = None,
    ) -> None:
        root = Path(state_dir).expanduser()
        if not root.is_absolute():
            raise TrustedSurfaceError("INVALID_STATE_PATH", "Trusted surface state directory must be absolute")
        self.root = root.resolve()
        self.sessions_dir = self.root / "sessions"
        self.responses_dir = self.root / "responses"
        self.credential_state_dir = self.root / "credentials"
        for directory in (self.sessions_dir, self.responses_dir, self.credential_state_dir):
            directory.mkdir(parents=True, exist_ok=True)
        package_dir = Path(__file__).resolve().parent
        python_candidate = Path(python_path) if python_path is not None else Path(sys.executable)
        surface_candidate = Path(surface_path) if surface_path is not None else package_dir / "trusted_surface_ui.py"
        if not python_candidate.is_absolute() or not surface_candidate.is_absolute():
            raise TrustedSurfaceError("RELATIVE_RUNTIME_PATH", "Trusted surface runtime paths must be absolute")
        self.python_path = python_candidate.resolve(strict=True)
        self.surface_path = surface_candidate.resolve(strict=True)
        self.bootstrap_path = (package_dir / "trusted_surface_bootstrap.py").resolve(strict=True)
        self.surface_sha256 = self._sha256(self.surface_path)
        self._processes: dict[str, _SurfaceProcess] = {}
        self._session_digests: dict[str, str] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def capabilities(self) -> dict[str, Any]:
        return {
            "localSettings": True,
            "consentWindow": True,
            "digestPinned": True,
            "secretViaModel": False,
            "authorizationLedger": False,
            "complete": False,
        }

    def _write_request(self, request: dict[str, Any]) -> Path:
        path = self.sessions_dir / f"{request['sessionRef']}.json"
        AtomicJsonStore._write_atomic(path, request)
        serialized = json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        self._session_digests[str(request["sessionRef"])] = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        return path

    def create_local_settings_session(self, *, profile_ref: str, capability: str) -> dict[str, Any]:
        if not PROFILE_REF_PATTERN.fullmatch(profile_ref):
            raise TrustedSurfaceError("INVALID_PROFILE_REF", "Invalid local settings profile reference")
        if capability not in {"model", "tts", "anki_connect"}:
            raise TrustedSurfaceError("INVALID_CAPABILITY", "Invalid local settings capability")
        return self._create_session(
            "local_settings",
            profileRef=profile_ref,
            capability=capability,
            credentialStateDir=str(self.credential_state_dir),
        )

    def create_consent_session(self, *, title: str, summary: str, purpose: str) -> dict[str, Any]:
        if purpose not in {"source_access", "output_access", "network_access", "operation", "anki_import"}:
            raise TrustedSurfaceError("INVALID_CONSENT_PURPOSE", "Invalid consent purpose")
        if not title.strip() or not summary.strip() or len(title) > 120 or len(summary) > 2_000:
            raise TrustedSurfaceError("INVALID_CONSENT_COPY", "Consent title or summary is invalid")
        return self._create_session("consent", title=title.strip(), summary=summary.strip(), purpose=purpose)

    def _create_session(self, surface: str, **fields: Any) -> dict[str, Any]:
        session_ref = str(uuid.uuid4())
        nonce = uuid.uuid4().hex + uuid.uuid4().hex
        response_path = (self.responses_dir / f"{session_ref}.json").resolve()
        request = {
            "schemaVersion": 1,
            "sessionRef": session_ref,
            "requestNonce": nonce,
            "surface": surface,
            "responsePath": str(response_path),
            "createdAt": int(time.time() * 1000),
            **fields,
        }
        self._write_request(request)
        return {
            "sessionRef": session_ref,
            "surface": surface,
            "state": "created",
        }

    def _load_request(self, session_ref: str) -> tuple[Path, dict[str, Any]]:
        request_path = self.sessions_dir / f"{session_ref}.json"
        if not request_path.is_file():
            raise TrustedSurfaceError("SESSION_NOT_FOUND", "Trusted surface session does not exist")
        with request_path.open("r", encoding="utf-8") as handle:
            request = json.load(handle)
        expected_response = (self.responses_dir / f"{session_ref}.json").resolve()
        if (
            not isinstance(request, dict)
            or request.get("sessionRef") != session_ref
            or request.get("surface") not in {"local_settings", "consent"}
            or not isinstance(request.get("requestNonce"), str)
            or len(request["requestNonce"]) != 64
            or Path(str(request.get("responsePath") or "")) != expected_response
        ):
            raise TrustedSurfaceError("SESSION_REQUEST_INVALID", "Trusted surface request was modified")
        serialized = json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        expected_digest = self._session_digests.get(session_ref)
        if expected_digest is None or hashlib.sha256(serialized.encode("utf-8")).hexdigest() != expected_digest:
            raise TrustedSurfaceError("SESSION_REQUEST_INVALID", "Trusted surface request digest changed")
        return request_path, request

    def launch(self, session_ref: str) -> dict[str, Any]:
        request_path, request = self._load_request(session_ref)
        if self._sha256(self.surface_path) != self.surface_sha256:
            raise TrustedSurfaceError("SURFACE_DIGEST_CHANGED", "Trusted surface code changed after service start")
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        process = subprocess.Popen(
            [
                str(self.python_path), str(self.bootstrap_path), str(self.surface_path),
                self.surface_sha256, str(request["surface"]), str(request_path.resolve()),
            ],
            cwd=str(self.surface_path.parent.parent),
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            creationflags=creationflags,
        )
        process_group = TaskOwnedProcessGroup(memory_limit_bytes=512 * 1024 * 1024, active_process_limit=2)
        try:
            process_group.assign(process)
        except ProcessIsolationError as error:
            process.terminate()
            process_group.close()
            raise TrustedSurfaceError("SURFACE_ISOLATION_FAILED", str(error)) from error
        assert process.stdin is not None
        frozen_request = json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        process.stdin.write(b"START\n" + frozen_request)
        process.stdin.close()
        with self._lock:
            self._processes[session_ref] = _SurfaceProcess(process=process, process_group=process_group)
        threading.Thread(target=self._monitor, args=(session_ref,), daemon=True).start()
        return {"sessionRef": session_ref, "surface": request["surface"], "state": "open"}

    def _monitor(self, session_ref: str) -> None:
        with self._lock:
            runtime = self._processes.get(session_ref)
        if runtime is None:
            return
        exit_code = runtime.process.wait()
        try:
            runtime.process_group.close()
        except ProcessIsolationError:
            pass
        with self._lock:
            self._processes.pop(session_ref, None)
        response_path = self.responses_dir / f"{session_ref}.json"
        if exit_code != 0 and not response_path.exists():
            AtomicJsonStore._write_atomic(
                response_path,
                {"schemaVersion": 1, "sessionRef": session_ref, "state": "failed", "errorCode": "SURFACE_EXITED"},
            )

    def get_session(self, session_ref: str) -> dict[str, Any]:
        _, request = self._load_request(session_ref)
        response_path = self.responses_dir / f"{session_ref}.json"
        if not response_path.is_file():
            with self._lock:
                running = session_ref in self._processes
            return {"sessionRef": session_ref, "surface": request["surface"], "state": "open" if running else "created"}
        with response_path.open("r", encoding="utf-8") as handle:
            response = json.load(handle)
        if response.get("sessionRef") != session_ref:
            raise TrustedSurfaceError("SESSION_RESPONSE_INVALID", "Trusted surface response session mismatch")
        if response.get("requestNonce") != request.get("requestNonce") and response.get("state") != "failed":
            raise TrustedSurfaceError("SESSION_RESPONSE_INVALID", "Trusted surface response nonce mismatch")
        allowed = {"schemaVersion", "sessionRef", "state", "credential", "userGestureRecorded", "errorCode"}
        return {key: value for key, value in response.items() if key in allowed}
