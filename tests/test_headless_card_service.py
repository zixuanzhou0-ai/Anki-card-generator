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

from card_service.broker import BrokerBudget, BrokerReservationLedger, ModelTtsBroker
from card_service.broker_runtime import AuthorizedProviderCall, TaskBrokerAuthorization, make_task_broker_handler
from card_service.credentials import CredentialStore, InMemoryCredentialBackend
from card_service.provider_egress import ProviderProfile, ProviderTransportResponse
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
    assert capabilities["mediaToolPolicy"]["managedAbsoluteTools"] is False
    assert capabilities["mediaToolPolicy"]["complete"] is False
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

    def sign(payload: dict[str, object]) -> dict[str, object]:
        signed = dict(payload)
        canonical_payload = json.dumps(
            signed,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        signed["mac"] = (
            base64.urlsafe_b64encode(hmac.new(key, canonical_payload, hashlib.sha256).digest())
            .decode("ascii")
            .rstrip("=")
        )
        return signed

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
    value = sign(value)
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

    runtime_sid = "S-1-15-2-1-2-3-4"
    task_sid = "S-1-15-3-1024-5-6-7-8"
    runtime_digest = hashlib.sha256(
        b"study.runtime-appcontainer-sid.v1\x00" + runtime_sid.encode("ascii")
    ).hexdigest()
    task_digest = hashlib.sha256(
        b"study.task-capability-sid.v1\x00" + task_sid.encode("ascii")
    ).hexdigest()
    dacl_bound = dict(value)
    dacl_bound.pop("mac")
    dacl_bound.update(
        {
            "filesystemRestrictedByDedicatedSidDacl": True,
            "networkRestricted": True,
            "runtimeAppContainerSidDigest": runtime_digest,
            "taskCapabilitySidDigest": task_digest,
            "appContainerToken": True,
            "taskCapabilityPresent": True,
        }
    )
    dacl_bound = sign(dacl_bound)
    verified_dacl = _verify_sandbox_attestation(
        dacl_bound,
        key=key,
        task_id=task_id,
        expected_filesystem_restricted=True,
        expected_network_restricted=True,
        expected_runtime_sid_digest=runtime_digest,
        expected_task_sid_digest=task_digest,
    )
    assert verified_dacl["filesystemRestrictedByDedicatedSidDacl"] is True
    wrong_binding = dict(dacl_bound)
    wrong_binding.pop("mac")
    wrong_binding["taskCapabilitySidDigest"] = "0" * 64
    with pytest.raises(ValueError, match="SID binding"):
        _verify_sandbox_attestation(
            sign(wrong_binding),
            key=key,
            task_id=task_id,
            expected_filesystem_restricted=True,
            expected_network_restricted=True,
            expected_runtime_sid_digest=runtime_digest,
            expected_task_sid_digest=task_digest,
        )


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
            "--development-unpackaged-runtime",
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


def test_restricted_worker_reaches_service_owned_provider_egress_over_authenticated_stdio(tmp_path: Path) -> None:
    backend = InMemoryCredentialBackend()
    credentials = CredentialStore(state_dir=(tmp_path / "credentials").resolve(), backend=backend)
    metadata = credentials.set_secret("model.primary", "provider-secret-canary")
    ledger = BrokerReservationLedger((tmp_path / "broker-ledger.json").resolve())
    broker = ModelTtsBroker(credential_store=credentials, ledger=ledger)
    observed = []

    def transport(request):
        observed.append(request)
        assert request.headers["Authorization"] == "Bearer provider-secret-canary"
        body = json.loads(request.body)
        assert body["model"] == "gpt-service-owned"
        return ProviderTransportResponse(200, request.url, {}, b'{"text":"brokered"}')

    binding = AuthorizedProviderCall(
        profile=ProviderProfile(
            profile_ref="model.primary",
            capability="model",
            provider="openai",
            base_url="https://api.openai.com/v1",
            model="gpt-service-owned",
            maximum_response_bytes=4096,
        ),
        credential_revision=int(metadata["credentialRevision"]),
        reserved_cost_minor_units=3,
        transport=transport,
    )
    authorization = TaskBrokerAuthorization(
        operation_intent_ref="intent-approved-1",
        budget=BrokerBudget(4, 100_000, 100_000, 100),
        operations={"model.openai_chat": binding},
    )

    def factory(task_id: str, method: str, request: dict[str, object]):
        assert method == "runtime.extract_learning_points"
        assert request == {"mode": "broker_typed"}
        return make_task_broker_handler(task_id=task_id, authorization=authorization, broker=broker)

    card_service = service(
        tmp_path,
        method_policies={
            "runtime.extract_learning_points": MethodPolicy(
                "extract_learning_points",
                5.0,
                requires_broker=True,
            )
        },
        broker_handler_factory=factory,
    )
    assert card_service.capabilities()["methodAvailability"]["runtime.extract_learning_points"] == {
        "available": True,
        "blocker": None,
    }
    started = card_service.start_task("runtime.extract_learning_points", {"mode": "broker_typed"})
    finished = wait_terminal(card_service, started["id"], timeout=10)
    assert finished["state"] == "succeeded", finished.get("error")
    assert card_service.read_result(started["id"])["brokered"] == {"text": "brokered"}
    assert len(observed) == 1
    assert ledger.list_records()[0]["state"] == "settled"
    persisted = "\n".join(path.read_text(encoding="utf-8") for path in tmp_path.rglob("*.json"))
    assert "provider-secret-canary" not in persisted


def test_real_legacy_card_generation_uses_service_broker_without_worker_secret_or_origin(tmp_path: Path) -> None:
    credentials = CredentialStore(
        state_dir=(tmp_path / "credentials").resolve(),
        backend=InMemoryCredentialBackend(),
    )
    metadata = credentials.set_secret("model.primary", "provider-secret-canary")
    ledger = BrokerReservationLedger((tmp_path / "broker-ledger.json").resolve())
    broker = ModelTtsBroker(credential_store=credentials, ledger=ledger)
    observed = []
    model_cards = {
        "segments": [
            {
                "id": "seg_lp_0001",
                "cards": [
                    {
                        "id": "card_0001",
                        "type": "phrase",
                        "learning_point_id": "lp-common-sense",
                        "phrase": "common sense",
                        "answer_core": "common sense",
                        "normalized_answer": "common sense",
                        "exact_span": "common sense",
                        "english": "Use common sense here.",
                        "chinese": "这里要用常识判断。",
                        "definition": "ordinary practical judgment",
                        "collocations": "use common sense",
                        "context": "Use common sense here.",
                        "example": "Use common sense when deciding.",
                        "chinese_feel": "常识判断",
                        "why": "高频且可迁移",
                        "difficulty": "B1",
                        "estimated_level": "B1",
                        "teacher_note": "用于提醒对方作基本判断。",
                        "cloze": "Use ____ here.",
                        "quality": {"score": 90, "status": "recommended", "issues": []},
                    }
                ],
            }
        ]
    }

    def transport(request):
        observed.append(request)
        assert request.headers["Authorization"] == "Bearer provider-secret-canary"
        provider_body = json.loads(request.body)
        assert provider_body["model"] == "gpt-service-owned"
        assert "api_key" not in json.dumps(provider_body).casefold()
        response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(model_cards, ensure_ascii=False),
                    }
                }
            ]
        }
        return ProviderTransportResponse(
            200,
            request.url,
            {"content-type": "application/json"},
            json.dumps(response, ensure_ascii=False).encode("utf-8"),
        )

    authorization = TaskBrokerAuthorization(
        operation_intent_ref="intent-generate-cards-1",
        budget=BrokerBudget(4, 500_000, 500_000, 100),
        operations={
            "model.openai_chat": AuthorizedProviderCall(
                profile=ProviderProfile(
                    profile_ref="model.primary",
                    capability="model",
                    provider="openai",
                    base_url="https://api.openai.com/v1",
                    model="gpt-service-owned",
                    maximum_response_bytes=100_000,
                ),
                credential_revision=int(metadata["credentialRevision"]),
                reserved_cost_minor_units=3,
                transport=transport,
            )
        },
    )

    def factory(task_id: str, method: str, request: dict[str, object]):
        assert method == "runtime.generate_cards"
        serialized = json.dumps(request).casefold()
        assert "api_key" not in serialized
        assert "base_url" not in serialized
        return make_task_broker_handler(task_id=task_id, authorization=authorization, broker=broker)

    real_worker = ROOT / "workers" / "anki_worker.py"
    card_service = CardService(
        state_dir=(tmp_path / "real-broker-state").resolve(),
        worker_path=real_worker.resolve(),
        python_path=Path(sys.executable).resolve(),
        method_policies={
            "runtime.generate_cards": MethodPolicy(
                "generate_cards_from_learning_points",
                60.0,
                requires_broker=True,
            )
        },
        broker_handler_factory=factory,
    )
    request = {
        "title": "Managed broker proof",
        "language": "en",
        "level": "B1",
        "card_types": ["phrase"],
        "api_config": {
            "provider": "openai-compatible",
            "model": "worker-model-hint",
        },
        "learning_points": [
            {
                "id": "lp-common-sense",
                "status": "recommended",
                "candidate_kind": "expression",
                "phrase_type": "spoken_phrase",
                "source_sentence": "Use common sense here.",
                "exact_span": "common sense",
                "answer_core": "common sense",
                "normalized_answer": "common sense",
                "reason": "高频且可迁移",
                "learning_action": "理解并会使用 common sense。",
                "value_score": 5,
                "start": 0,
                "end": 2,
            }
        ],
        "selected_learning_point_ids": ["lp-common-sense"],
        "disable_card_generation_cache_read": True,
        "disable_card_generation_cache_write": True,
    }
    started = card_service.start_task("runtime.generate_cards", request)
    finished = wait_terminal(card_service, started["id"], timeout=60)
    assert finished["state"] == "succeeded", finished.get("error")
    result = card_service.read_result(started["id"])
    assert result["generated_learning_point_ids"] == ["lp-common-sense"]
    assert result["segments"][0]["cards"][0]["phrase"] == "common sense"
    assert len(observed) == 1
    assert ledger.list_records()[0]["state"] == "settled"
    persisted = "\n".join(path.read_text(encoding="utf-8") for path in tmp_path.rglob("*.json"))
    assert "provider-secret-canary" not in persisted


def test_real_legacy_tts_test_uses_service_broker_without_worker_secret_or_origin(tmp_path: Path) -> None:
    credentials = CredentialStore(
        state_dir=(tmp_path / "tts-credentials").resolve(),
        backend=InMemoryCredentialBackend(),
    )
    metadata = credentials.set_secret("tts.primary", "tts-provider-secret-canary")
    ledger = BrokerReservationLedger((tmp_path / "tts-broker-ledger.json").resolve())
    broker = ModelTtsBroker(credential_store=credentials, ledger=ledger)
    observed = []
    audio = b"ID3" + b"\x00" * 128

    def transport(request):
        observed.append(request)
        assert request.headers["Authorization"] == "Bearer tts-provider-secret-canary"
        body = json.loads(request.body)
        assert request.url == "https://api.x.ai/v1/tts"
        assert body["voice_id"] == "eve"
        assert body["text"] == "This is a TTS test for your Anki cards."
        assert "model" not in body
        return ProviderTransportResponse(200, request.url, {"content-type": "audio/mpeg"}, audio)

    authorization = TaskBrokerAuthorization(
        operation_intent_ref="intent-test-tts-1",
        budget=BrokerBudget(2, 100_000, 100_000, 100),
        operations={
            "tts.synthesize": AuthorizedProviderCall(
                profile=ProviderProfile(
                    profile_ref="tts.primary",
                    capability="tts",
                    provider="xai",
                    base_url="https://api.x.ai/v1",
                    model="service-owned-tts-model",
                    voice="eve",
                    maximum_response_bytes=10_000,
                ),
                credential_revision=int(metadata["credentialRevision"]),
                reserved_cost_minor_units=3,
                transport=transport,
            )
        },
    )

    def factory(task_id: str, method: str, request: dict[str, object]):
        assert method == "runtime.test_tts"
        serialized = json.dumps(request).casefold()
        assert "api_key" not in serialized
        assert "base_url" not in serialized
        assert "voice" not in serialized
        assert "model" not in serialized
        return make_task_broker_handler(task_id=task_id, authorization=authorization, broker=broker)

    card_service = CardService(
        state_dir=(tmp_path / "real-tts-broker-state").resolve(),
        worker_path=(ROOT / "workers" / "anki_worker.py").resolve(),
        python_path=Path(sys.executable).resolve(),
        method_policies={
            "runtime.test_tts": MethodPolicy("test_tts", 60.0, requires_broker=True)
        },
        broker_handler_factory=factory,
    )
    request = {
        "language": "English",
        "api_config": {
            "tts_config": {
                "enabled": True,
                "provider": "xai",
                "language": "auto",
                "sample_rate": 24000,
                "bit_rate": 128000,
            }
        },
    }
    started = card_service.start_task("runtime.test_tts", request)
    finished = wait_terminal(card_service, started["id"], timeout=60)
    assert finished["state"] == "succeeded", finished.get("error")
    result = card_service.read_result(started["id"])
    assert result["ok"] is True
    assert result["bytes"] == len(audio)
    assert len(observed) == 1
    assert ledger.list_records()[0]["state"] == "settled"
    persisted = "\n".join(path.read_text(encoding="utf-8") for path in tmp_path.rglob("*.json"))
    assert "tts-provider-secret-canary" not in persisted
