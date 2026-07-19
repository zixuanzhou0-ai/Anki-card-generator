from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from card_service.hermes_proxy import (
    HERMES_PROXY_BASE_URL,
    HERMES_PROXY_PORT,
    HermesProxyError,
    HermesProxyManager,
    _parse_health_payload,
)


class FakeChild:
    def __init__(self, *, returncode: int | None = None) -> None:
        self.returncode = returncode
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        return int(self.returncode or 0)


def status(state: str) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "state": state,
        "message": state,
        "baseUrl": HERMES_PROXY_BASE_URL,
        "model": "grok-4.5",
        "authenticated": state == "ready",
        "managed": False,
    }


def test_fixed_hermes_proxy_contract_matches_desktop_port() -> None:
    assert HERMES_PROXY_PORT == 8645
    assert HERMES_PROXY_BASE_URL == "http://127.0.0.1:8645/v1"


def test_health_payload_requires_xai_identity_and_boolean_authentication() -> None:
    body = json.dumps(
        {"status": "ok", "upstream": "xAI Grok OAuth", "authenticated": True}
    ).encode()
    assert _parse_health_payload(200, body) == {
        "authenticated": True,
        "upstream": "xAI Grok OAuth",
    }
    assert _parse_health_payload(200, b'{"status":"ok","upstream":"other","authenticated":true}') is None
    assert _parse_health_payload(200, b'{"status":"ok","upstream":"xAI"}') is None
    assert _parse_health_payload(503, body) is None


def test_ready_proxy_is_reused_without_starting(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = HermesProxyManager(startup_timeout_seconds=1)
    monkeypatch.setattr(manager, "probe", lambda: status("ready"))
    monkeypatch.setattr(
        manager,
        "_spawn",
        lambda _executable: pytest.fail("ready proxy must not be started again"),
    )

    assert manager.ensure_ready()["state"] == "ready"


@pytest.mark.parametrize(
    ("state_name", "expected_code"),
    [
        ("port_conflict", "HERMES_PROXY_PORT_CONFLICT"),
        ("oauth_unready", "HERMES_OAUTH_REQUIRED"),
    ],
)
def test_unsafe_or_unauthorized_listener_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    state_name: str,
    expected_code: str,
) -> None:
    manager = HermesProxyManager(startup_timeout_seconds=1)
    monkeypatch.setattr(manager, "probe", lambda: status(state_name))

    with pytest.raises(HermesProxyError) as caught:
        manager.ensure_ready()

    assert caught.value.code == expected_code


def test_missing_executable_is_actionable(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = HermesProxyManager(startup_timeout_seconds=1)
    monkeypatch.setattr(manager, "probe", lambda: status("stopped"))
    monkeypatch.setattr(manager, "_find_executable", lambda: None)

    with pytest.raises(HermesProxyError) as caught:
        manager.ensure_ready()

    assert caught.value.code == "HERMES_NOT_FOUND"
    assert caught.value.retryable is False


def test_authenticated_stopped_proxy_is_started_and_health_checked(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    executable = tmp_path / "hermes.exe"
    executable.write_bytes(b"fixture")
    manager = HermesProxyManager(startup_timeout_seconds=1)
    states = iter([status("stopped"), status("stopped"), status("ready")])
    child = FakeChild()
    monkeypatch.setattr(manager, "probe", lambda: next(states))
    monkeypatch.setattr(manager, "_find_executable", lambda: executable)
    monkeypatch.setattr(manager, "_oauth_ready", lambda _executable: True)
    monkeypatch.setattr(manager, "_spawn", lambda _executable: child)
    monkeypatch.setattr("card_service.hermes_proxy.time.sleep", lambda _seconds: None)

    result = manager.ensure_ready()

    assert result["state"] == "ready"
    assert manager._managed_child is child
    manager.close()
    assert child.terminated is True


def test_proxy_that_exits_early_is_not_reported_ready(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    executable = tmp_path / "hermes.exe"
    executable.write_bytes(b"fixture")
    manager = HermesProxyManager(startup_timeout_seconds=1)
    monkeypatch.setattr(manager, "probe", lambda: status("stopped"))
    monkeypatch.setattr(manager, "_find_executable", lambda: executable)
    monkeypatch.setattr(manager, "_oauth_ready", lambda _executable: True)
    monkeypatch.setattr(manager, "_spawn", lambda _executable: FakeChild(returncode=2))

    with pytest.raises(HermesProxyError) as caught:
        manager.ensure_ready()

    assert caught.value.code == "HERMES_PROXY_START_FAILED"
