from __future__ import annotations

import atexit
import http.client
import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any


HERMES_PROXY_HOST = "127.0.0.1"
HERMES_PROXY_PORT = 8645
HERMES_PROXY_BASE_URL = f"http://{HERMES_PROXY_HOST}:{HERMES_PROXY_PORT}/v1"
HERMES_PROXY_MODEL = "grok-4.5"


class HermesProxyError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


def _hidden_process_flags() -> int:
    if os.name != "nt":
        return 0
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _parse_health_payload(status: int, body: bytes) -> dict[str, Any] | None:
    if status != 200 or not body or len(body) > 64 * 1024:
        return None
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("status") != "ok":
        return None
    upstream = str(payload.get("upstream") or "").casefold()
    if "xai" not in upstream and "grok" not in upstream:
        return None
    authenticated = payload.get("authenticated")
    if not isinstance(authenticated, bool):
        return None
    return {"authenticated": authenticated, "upstream": str(payload["upstream"])}


class HermesProxyManager:
    """Own and health-check the fixed local Hermes xAI proxy."""

    def __init__(self, *, startup_timeout_seconds: float = 20.0) -> None:
        self.startup_timeout_seconds = max(1.0, float(startup_timeout_seconds))
        self._lock = threading.RLock()
        self._managed_child: subprocess.Popen[bytes] | None = None
        atexit.register(self.close)

    @staticmethod
    def _candidate_executables() -> list[Path]:
        values: list[Path] = []

        def add(value: str | os.PathLike[str] | None) -> None:
            if not value:
                return
            candidate = Path(value).expanduser()
            try:
                resolved = candidate.resolve(strict=True)
            except OSError:
                return
            if resolved.is_file() and resolved not in values:
                values.append(resolved)

        add(os.environ.get("HERMES_EXE"))
        add(shutil.which("hermes"))
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            add(
                Path(local_app_data)
                / "hermes"
                / "hermes-agent"
                / "venv"
                / "Scripts"
                / "hermes.exe"
            )
        return values

    def _find_executable(self) -> Path | None:
        candidates = self._candidate_executables()
        return candidates[0] if candidates else None

    def probe(self) -> dict[str, Any]:
        connection = http.client.HTTPConnection(
            HERMES_PROXY_HOST,
            HERMES_PROXY_PORT,
            timeout=0.7,
        )
        try:
            connection.request("GET", "/health", headers={"Connection": "close"})
            response = connection.getresponse()
            payload = _parse_health_payload(response.status, response.read(64 * 1024 + 1))
        except (OSError, TimeoutError, http.client.HTTPException):
            return self._status("stopped", authenticated=False, managed=self._child_running())
        finally:
            connection.close()
        if payload is None:
            return self._status("port_conflict", authenticated=False, managed=False)
        if payload["authenticated"]:
            return self._status("ready", authenticated=True, managed=self._child_running())
        return self._status("oauth_unready", authenticated=False, managed=self._child_running())

    def _child_running(self) -> bool:
        child = self._managed_child
        return child is not None and child.poll() is None

    @staticmethod
    def _status(state: str, *, authenticated: bool, managed: bool) -> dict[str, Any]:
        messages = {
            "ready": "Hermes Grok 4.5 local proxy is ready.",
            "stopped": "Hermes local proxy is not running.",
            "oauth_unready": "Hermes xAI OAuth is not ready.",
            "port_conflict": "Port 8645 is occupied by a service other than the Hermes xAI proxy.",
            "missing": "Hermes executable was not found.",
        }
        return {
            "schemaVersion": 1,
            "state": state,
            "message": messages[state],
            "baseUrl": HERMES_PROXY_BASE_URL,
            "model": HERMES_PROXY_MODEL,
            "authenticated": authenticated,
            "managed": managed,
        }

    @staticmethod
    def _oauth_ready(executable: Path) -> bool:
        try:
            result = subprocess.run(
                [str(executable), "proxy", "status"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10,
                check=False,
                creationflags=_hidden_process_flags(),
            )
        except (OSError, subprocess.SubprocessError):
            return False
        text = (result.stdout + b"\n" + result.stderr).decode(
            "utf-8", errors="replace"
        ).casefold()
        return result.returncode == 0 and any(
            "[xai" in line and "ready" in line for line in text.splitlines()
        )

    @staticmethod
    def _spawn(executable: Path) -> subprocess.Popen[bytes]:
        return subprocess.Popen(
            [
                str(executable),
                "proxy",
                "start",
                "--provider",
                "xai",
                "--host",
                HERMES_PROXY_HOST,
                "--port",
                str(HERMES_PROXY_PORT),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_hidden_process_flags(),
        )

    def ensure_ready(self) -> dict[str, Any]:
        with self._lock:
            current = self.probe()
            if current["state"] == "ready":
                return current
            if current["state"] == "port_conflict":
                raise HermesProxyError(
                    "HERMES_PROXY_PORT_CONFLICT",
                    current["message"],
                    retryable=False,
                )
            if current["state"] == "oauth_unready":
                raise HermesProxyError(
                    "HERMES_OAUTH_REQUIRED",
                    current["message"],
                    retryable=False,
                )
            executable = self._find_executable()
            if executable is None:
                raise HermesProxyError(
                    "HERMES_NOT_FOUND",
                    self._status(
                        "missing", authenticated=False, managed=False
                    )["message"],
                    retryable=False,
                )
            if not self._oauth_ready(executable):
                raise HermesProxyError(
                    "HERMES_OAUTH_REQUIRED",
                    "Hermes xAI OAuth is not ready. Run `hermes auth add xai-oauth` first.",
                    retryable=False,
                )
            try:
                child = self._spawn(executable)
            except OSError as error:
                raise HermesProxyError(
                    "HERMES_PROXY_START_FAILED",
                    "Hermes local proxy could not be started.",
                ) from error
            self._managed_child = child
            deadline = time.monotonic() + self.startup_timeout_seconds
            while time.monotonic() < deadline:
                if child.poll() is not None:
                    self._managed_child = None
                    raise HermesProxyError(
                        "HERMES_PROXY_START_FAILED",
                        "Hermes local proxy exited before it became ready.",
                    )
                current = self.probe()
                if current["state"] == "ready":
                    return current
                if current["state"] == "port_conflict":
                    self.close()
                    raise HermesProxyError(
                        "HERMES_PROXY_PORT_CONFLICT",
                        current["message"],
                        retryable=False,
                    )
                time.sleep(0.15)
            self.close()
            raise HermesProxyError(
                "HERMES_PROXY_START_TIMEOUT",
                "Hermes local proxy did not pass its health check within 20 seconds.",
            )

    def close(self) -> None:
        with self._lock:
            child = self._managed_child
            self._managed_child = None
            if child is None or child.poll() is not None:
                return
            try:
                child.terminate()
                child.wait(timeout=3)
            except (OSError, subprocess.SubprocessError):
                try:
                    child.kill()
                    child.wait(timeout=2)
                except (OSError, subprocess.SubprocessError):
                    pass


__all__ = [
    "HERMES_PROXY_BASE_URL",
    "HERMES_PROXY_HOST",
    "HERMES_PROXY_MODEL",
    "HERMES_PROXY_PORT",
    "HermesProxyError",
    "HermesProxyManager",
]
