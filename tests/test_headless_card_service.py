from __future__ import annotations

import base64
import hashlib
import hmac
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from card_service.service import CardService, CardServiceError, MethodPolicy, _verify_sandbox_attestation


ROOT = Path(__file__).resolve().parents[1]
FAKE_WORKER = ROOT / "tests" / "fixtures" / "card_service" / "fake_worker.py"


def service(tmp_path: Path, **overrides: object) -> CardService:
    options: dict[str, object] = {
        "state_dir": tmp_path / "state",
        "worker_path": FAKE_WORKER,
        "python_path": Path(sys.executable),
        "method_policies": {
            "runtime.check_environment": MethodPolicy("check_env", 2.0),
            "runtime.extract_learning_points": MethodPolicy("extract_learning_points", 2.0),
        },
    }
    options.update(overrides)
    return CardService(**options)  # type: ignore[arg-type]


def wait_terminal(card_service: CardService, task_id: str, timeout: float = 4.0) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snapshot = card_service.get_task(task_id)
        assert snapshot is not None
        if snapshot["state"] in {"succeeded", "failed", "cancelled", "interrupted"}:
            return snapshot
        time.sleep(0.02)
    raise AssertionError("task did not reach a terminal state")


def test_capabilities_expose_only_restricted_high_level_methods(tmp_path: Path) -> None:
    card_service = service(tmp_path)
    capabilities = card_service.capabilities()
    assert capabilities["genericShell"] is False
    assert capabilities["genericWorkerCommand"] is False
    assert capabilities["secretBearingRequests"] is False
    assert capabilities["processIsolation"]["taskOwnedJobObject"] is (sys.platform == "win32")
    assert capabilities["processIsolation"]["restrictedPrimaryToken"] is (sys.platform == "win32")
    assert capabilities["processIsolation"]["appContainerOrRestrictedSidDacl"] is False
    assert capabilities["processIsolation"]["forcedOutboundBroker"] is False
    assert capabilities["processIsolation"]["complete"] is False
    assert capabilities["trustedSurfaces"]["localSettings"] is True
    assert capabilities["trustedSurfaces"]["authorizationLedger"] is False
    assert capabilities["methods"] == ["runtime.check_environment", "runtime.extract_learning_points"]
    assert capabilities["worker"]["resourceId"] == "managed:legacy-worker"
    assert "path" not in capabilities["worker"]
    assert "path" not in capabilities["python"]
    with pytest.raises(CardServiceError, match="not allowed") as caught:
        card_service.dispatch("runtime.run_worker", {"command": "anything"})
    assert caught.value.code == "METHOD_NOT_ALLOWED"

    production_service = CardService(
        state_dir=(tmp_path / "production-state").resolve(),
        worker_path=FAKE_WORKER.resolve(),
        python_path=Path(sys.executable).resolve(),
    )
    assert production_service.capabilities()["methodAvailability"]["runtime.generate_cards"] == {
        "available": False,
        "blocker": "model_tts_broker_not_ready",
    }
    with pytest.raises(CardServiceError) as broker_error:
        production_service.start_task("runtime.generate_cards", {})
    assert broker_error.value.code == "BROKER_REQUIRED"
    with pytest.raises(CardServiceError) as settings_error:
        production_service.dispatch(
            "system.open_local_settings",
            {"profileRef": "../escape", "capability": "model"},
        )
    assert settings_error.value.code == "INVALID_PROFILE_REF"


def test_sandbox_attestation_rejects_forgery_wrong_task_and_missing_claims() -> None:
    key = b"k" * 32
    task_id = "task-boundary"
    value: dict[str, object] = {
        "schemaVersion": 1,
        "taskId": task_id,
        "restrictedPrimaryToken": True,
        "maxPrivilegesDisabled": True,
        "authenticatedUsersSidDisabled": True,
        "createdSuspended": True,
        "jobInheritedBeforeResume": True,
        "filesystemRestrictedByDedicatedSidDacl": False,
        "networkRestricted": False,
    }
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    value["mac"] = base64.urlsafe_b64encode(hmac.new(key, canonical, hashlib.sha256).digest()).decode("ascii").rstrip("=")
    verified = _verify_sandbox_attestation(value, key=key, task_id=task_id)
    assert verified["restrictedPrimaryToken"] is True
    assert verified["filesystemRestrictedByDedicatedSidDacl"] is False

    forged = dict(value, mac="forged")
    with pytest.raises(ValueError, match="binding"):
        _verify_sandbox_attestation(forged, key=key, task_id=task_id)
    with pytest.raises(ValueError, match="binding"):
        _verify_sandbox_attestation(value, key=key, task_id="different-task")
    missing_claim = dict(value)
    missing_claim.pop("maxPrivilegesDisabled")
    with pytest.raises(ValueError, match="binding"):
        _verify_sandbox_attestation(missing_claim, key=key, task_id=task_id)


def test_all_runtime_and_state_paths_must_be_absolute(tmp_path: Path) -> None:
    with pytest.raises((CardServiceError, ValueError), match="absolute"):
        CardService(state_dir=Path("relative-state"))
    with pytest.raises(CardServiceError) as worker_error:
        CardService(state_dir=tmp_path / "state", worker_path=Path("worker.py"))
    assert worker_error.value.code == "RELATIVE_RUNTIME_PATH"
    with pytest.raises(CardServiceError) as tool_error:
        CardService(state_dir=tmp_path / "state", managed_tool_directories=[Path("tools")])
    assert tool_error.value.code == "INVALID_TOOL_PATH"


@pytest.mark.parametrize(
    "payload",
    [
        {"api_key": "secret-canary"},
        {"nested": {"oauth_token": "secret-canary"}},
        {"url": "https://example.invalid/source?token=secret-canary"},
        {"url": "https://user:secret@example.invalid/source"},
    ],
)
def test_secret_bearing_requests_fail_before_task_persistence(tmp_path: Path, payload: dict[str, object]) -> None:
    card_service = service(tmp_path)
    with pytest.raises(CardServiceError) as caught:
        card_service.start_task("runtime.check_environment", payload)
    assert caught.value.code == "SECRET_IN_REQUEST"
    persisted = list((tmp_path / "state" / "tasks").glob("*.json"))
    assert persisted == []
    assert "secret-canary" not in json.dumps(card_service.store.list_tasks())


def test_successful_task_persists_snapshot_without_raw_request_and_reads_result(tmp_path: Path) -> None:
    card_service = service(tmp_path)
    started = card_service.start_task("runtime.check_environment", {"ordinary": "input-canary"})
    finished = wait_terminal(card_service, started["id"])
    assert finished["state"] == "succeeded"
    assert finished["progress"]["overallPercent"] == 100
    assert finished["isolation"]["taskOwnedJobObject"] is (sys.platform == "win32")
    assert finished["isolation"]["restrictedPrimaryToken"] is (sys.platform == "win32")
    assert finished["isolation"]["createdSuspended"] is (sys.platform == "win32")
    assert finished["isolation"]["jobInheritedBeforeResume"] is (sys.platform == "win32")
    assert finished["isolation"]["filesystemRestrictedByDedicatedSidDacl"] is False
    assert finished["isolation"]["networkRestricted"] is False
    if sys.platform == "win32":
        assert finished["isolation"]["authenticatedUsersSidDisabled"] is True
    assert card_service.read_result(started["id"]) == {
        "ok": True,
        "command": "check_env",
        "echo": {"ordinary": "input-canary"},
    }
    snapshot_text = (tmp_path / "state" / "tasks" / f"{started['id']}.json").read_text(encoding="utf-8")
    assert "input-canary" not in snapshot_text
    assert "inputFingerprint" in snapshot_text


def test_worker_error_is_structured_and_safe(tmp_path: Path) -> None:
    card_service = service(tmp_path)
    started = card_service.start_task("runtime.check_environment", {"mode": "fail"})
    finished = wait_terminal(card_service, started["id"])
    assert finished["state"] == "failed"
    assert finished["error"]["code"] == "FAKE_FAILURE"
    assert finished["error"]["message"] == "safe fake failure"


def test_worker_digest_change_after_service_start_fails_closed(tmp_path: Path) -> None:
    mutable_worker = tmp_path / "managed-worker.py"
    mutable_worker.write_bytes(FAKE_WORKER.read_bytes())
    card_service = service(tmp_path, worker_path=mutable_worker.resolve())
    mutable_worker.write_text(mutable_worker.read_text(encoding="utf-8") + chr(10) + "# changed", encoding="utf-8")
    started = card_service.start_task("runtime.check_environment", {})
    finished = wait_terminal(card_service, started["id"])
    assert finished["state"] == "failed"
    assert finished["error"]["code"] == "MANAGED_RUNTIME_CHANGED"
    assert "changed" in finished["error"]["message"]


def test_importable_worker_module_change_after_start_is_detected_before_launch(tmp_path: Path) -> None:
    worker_root = tmp_path / "worker-runtime"
    module_root = worker_root / "acg"
    module_root.mkdir(parents=True)
    mutable_worker = worker_root / "fake_worker.py"
    mutable_worker.write_bytes(FAKE_WORKER.read_bytes())
    module = module_root / "managed_dependency.py"
    module.write_text("VALUE = 1\n", encoding="utf-8")
    card_service = service(tmp_path, worker_path=mutable_worker.resolve())
    module.write_text("VALUE = 2\n", encoding="utf-8")
    started = card_service.start_task("runtime.check_environment", {})
    finished = wait_terminal(card_service, started["id"])
    assert finished["state"] == "failed"
    assert finished["error"]["code"] == "MANAGED_RUNTIME_CHANGED"


def test_runtime_manifest_is_internal_and_bootstrap_rejects_manifest_tampering(tmp_path: Path) -> None:
    card_service = service(tmp_path)
    capabilities = card_service.capabilities()
    summary = capabilities["runtimeSupplyChain"]
    assert summary["entryCount"] >= 4
    assert summary["pathDisclosure"] is False
    assert summary["signedReleaseManifest"] is False
    assert summary["complete"] is False
    assert str(tmp_path) not in json.dumps(capabilities)
    card_service.runtime_manifest_path.write_text("{}", encoding="utf-8")
    started = card_service.start_task("runtime.check_environment", {})
    finished = wait_terminal(card_service, started["id"])
    assert finished["state"] == "failed"
    assert finished["error"]["code"] == "MANAGED_RUNTIME_CHANGED"
    assert "manifest digest changed" in finished["error"]["message"]


def test_secret_bearing_worker_result_is_rejected_and_not_persisted(tmp_path: Path) -> None:
    card_service = service(tmp_path)
    started = card_service.start_task("runtime.check_environment", {"mode": "secret_result"})
    finished = wait_terminal(card_service, started["id"])
    assert finished["state"] == "failed"
    assert finished["error"]["code"] == "SECRET_IN_RESULT"
    assert list((tmp_path / "state" / "results").glob("*.json")) == []


def test_task_can_be_cancelled_to_a_terminal_state(tmp_path: Path) -> None:
    card_service = service(tmp_path, cancellation_grace_seconds=0.1)
    started = card_service.start_task("runtime.check_environment", {"mode": "slow"})
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        snapshot = card_service.get_task(started["id"])
        assert snapshot is not None
        if snapshot["state"] == "running":
            break
        time.sleep(0.01)
    cancelling = card_service.cancel_task(started["id"])
    assert cancelling["state"] in {"cancelling", "cancelled"}
    finished = wait_terminal(card_service, started["id"])
    assert finished["state"] == "cancelled"
    assert finished["error"]["code"] == "TASK_CANCELLED"


def test_timeout_and_output_limits_fail_closed(tmp_path: Path) -> None:
    timeout_service = service(
        tmp_path / "timeout",
        method_policies={"runtime.check_environment": MethodPolicy("check_env", 0.1)},
        cancellation_grace_seconds=0.1,
    )
    timed = timeout_service.start_task("runtime.check_environment", {"mode": "slow"})
    timed_result = wait_terminal(timeout_service, timed["id"])
    assert timed_result["error"]["code"] == "TASK_TIMEOUT"

    limited_service = service(tmp_path / "limit", max_stdout_bytes=1_024)
    oversized = limited_service.start_task("runtime.check_environment", {"mode": "overflow"})
    oversized_result = wait_terminal(limited_service, oversized["id"])
    assert oversized_result["error"]["code"] == "WORKER_OUTPUT_LIMIT"


def test_restart_marks_active_snapshot_interrupted_without_request_material(tmp_path: Path) -> None:
    first = service(tmp_path)
    task_id = "00000000-0000-0000-0000-000000000001"
    first.store.write_task(
        task_id,
        {
            "schemaVersion": 1,
            "id": task_id,
            "state": "running",
            "inputFingerprint": "sha256:abc",
            "progress": {},
        },
    )
    restarted = service(tmp_path)
    recovered = restarted.get_task(task_id)
    assert recovered is not None
    assert recovered["state"] == "interrupted"
    assert recovered["error"]["code"] == "SERVICE_RESTARTED"
    assert restarted.list_recoverable_tasks()[0]["id"] == task_id


def test_stdio_transport_stays_local_and_supports_task_polling(tmp_path: Path) -> None:
    state_dir = (tmp_path / "stdio-state").resolve()
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "card_service",
            "--state-dir",
            str(state_dir),
            "--worker",
            str(FAKE_WORKER.resolve()),
            "--python",
            str(Path(sys.executable).resolve()),
        ],
        cwd=str(ROOT),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    assert process.stdin is not None and process.stdout is not None

    def rpc(request_id: int, method: str, params: dict[str, object]) -> dict[str, object]:
        request = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        process.stdin.write(json.dumps(request) + chr(10))
        process.stdin.flush()
        return json.loads(process.stdout.readline())

    try:
        capabilities = rpc(1, "system.get_capabilities", {})
        assert capabilities["result"]["transport"] == "local-stdio"
        assert capabilities["result"]["genericShell"] is False
        started = rpc(2, "runtime.check_environment", {"ordinary": "stdio"})
        task_id = started["result"]["id"]
        deadline = time.monotonic() + 4
        terminal: dict[str, object] | None = None
        while time.monotonic() < deadline:
            polled = rpc(3, "task.get", {"taskId": task_id})
            if polled["result"]["state"] in {"succeeded", "failed", "cancelled", "interrupted"}:
                terminal = polled["result"]
                break
            time.sleep(0.02)
        assert terminal is not None and terminal["state"] == "succeeded"
        result = rpc(4, "task.read_result", {"taskId": task_id})
        assert result["result"]["ok"] is True
        rejected = rpc(5, "runtime.run_worker", {"command": "check_env"})
        assert rejected["error"]["code"] == "METHOD_NOT_ALLOWED"
    finally:
        process.stdin.close()
        process.wait(timeout=3)


def test_real_legacy_worker_check_environment_runs_headlessly(tmp_path: Path) -> None:
    real_worker = ROOT / "workers" / "anki_worker.py"
    card_service = CardService(
        state_dir=(tmp_path / "real-state").resolve(),
        worker_path=real_worker.resolve(),
        python_path=Path(sys.executable).resolve(),
        method_policies={"runtime.check_environment": MethodPolicy("check_env", 60.0)},
    )
    started = card_service.start_task("runtime.check_environment", {})
    finished = wait_terminal(card_service, started["id"], timeout=60)
    assert finished["state"] == "succeeded", finished.get("error")
    result = card_service.read_result(started["id"])
    assert result["schema_version"] == 2
    assert isinstance(result["status_items"], list)
    assert {item["id"] for item in result["status_items"]} >= {"python", "ffmpeg", "genanki", "yt_dlp"}


def test_task_owned_authenticated_stdio_broker_reaches_worker_without_persisting_channel_proof(tmp_path: Path) -> None:
    observed: list[tuple[str, str, str, dict[str, object]]] = []

    def factory(task_id: str, method: str, request: dict[str, object]):
        assert request == {"mode": "broker"}

        def handler(operation: str, payload: dict[str, object]) -> dict[str, object]:
            observed.append((task_id, method, operation, payload))
            return {"accepted": True, "workUnitRef": payload["workUnitRef"]}

        return handler

    card_service = service(tmp_path, broker_handler_factory=factory)
    assert card_service.capabilities()["modelTtsBroker"]["taskOwnedWorkerTransport"] is True
    started = card_service.start_task("runtime.check_environment", {"mode": "broker"})
    finished = wait_terminal(card_service, started["id"])
    assert finished["state"] == "succeeded", finished.get("error")
    assert finished["isolation"]["authenticatedBrokerStdio"] is True
    result = card_service.read_result(started["id"])
    assert result["brokered"] == {"accepted": True, "workUnitRef": "unit-1"}
    assert observed == [
        (
            started["id"],
            "runtime.check_environment",
            "model.openai_chat",
            {"workUnitRef": "unit-1", "value": 7},
        )
    ]
    persisted = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (tmp_path / "state").rglob("*.json")
    )
    assert "channelProof" not in persisted
    assert "__ANKI_CARD_BROKER" not in persisted
