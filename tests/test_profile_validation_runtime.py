from __future__ import annotations

import json
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from card_service.credentials import CredentialStore, InMemoryCredentialBackend
from card_service.mcp_system_tools import (
    REQUEST_OPERATION_CONFIRMATION_TOOL,
    VALIDATE_PROFILE_TOOL,
    call_system_tool,
)
from card_service.provider_egress import ProviderTransportResponse
from card_service.service import CardService, CardServiceError, MethodPolicy
from card_service.trusted_mcp_audience import create_development_mcp_audience


ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "workers" / "anki_worker.py"
FAKE_SURFACE = ROOT / "tests" / "fixtures" / "card_service" / "fake_surface.py"


class ReadyHermesProxyManager:
    def probe(self) -> dict[str, object]:
        return {"state": "ready"}

    def ensure_ready(self) -> dict[str, object]:
        return {"state": "ready"}

    def close(self) -> None:
        return None


def _profile() -> dict[str, object]:
    return {
        "profileRef": "model.validation",
        "capability": "model",
        "provider": "openai",
        "baseUrl": "https://api.openai.com/v1",
        "model": "gpt-5.6",
        "voice": "",
        "timeoutSeconds": 120,
        "maximumResponseBytes": 512 * 1024,
        "authMode": "bearer",
    }


def _valid_openai_response() -> bytes:
    card = {
        "segments": [
            {
                "id": "seg_test",
                "cards": [
                    {
                        "type": "phrase",
                        "phrase": "in the mood",
                        "chinese": "有心情",
                        "definition": "willing or wanting to do something",
                        "collocations": "in the mood for; not in the mood to",
                        "context": "spoken reply",
                        "example": "I am not in the mood to go out.",
                        "chinese_feel": "没那个心情",
                        "why": "高频口语表达",
                        "difficulty": "B1 日常交流",
                        "teacher_note": "真实口语常用",
                        "cloze": "I am not really ____ right now.",
                    }
                ],
            }
        ]
    }
    return json.dumps(
        {"choices": [{"message": {"content": json.dumps(card)}}]}
    ).encode("utf-8")


def _service(
    tmp_path: Path,
) -> tuple[CardService, list[object], str, int, InMemoryCredentialBackend]:
    backend = InMemoryCredentialBackend()
    observed: list[object] = []

    def transport(request: object) -> ProviderTransportResponse:
        observed.append(request)
        return ProviderTransportResponse(
            200,
            "https://api.openai.com/v1/chat/completions",
            {"content-type": "application/json"},
            _valid_openai_response(),
        )

    state = (tmp_path / "state").resolve()
    service = CardService(
        state_dir=state,
        worker_path=WORKER.resolve(),
        python_path=Path(sys.executable).resolve(),
        method_policies={
            "runtime.test_model": MethodPolicy(
                "test_api", 120.0, requires_broker=True
            )
        },
        credential_backend=backend,
        trusted_surface_path=FAKE_SURFACE.resolve(),
        use_restricted_launcher=False,
        hermes_proxy_manager=ReadyHermesProxyManager(),  # type: ignore[arg-type]
        profile_validation_transports={"model.validation": transport},
    )
    saved = service.save_service_profile(
        _profile(), expected_revision=0, operation_id="seed-profile"
    )
    credentials = CredentialStore(
        state_dir=state / "trusted-surfaces" / "credentials",
        backend=backend,
    )
    metadata = credentials.set_secret(
        "model.validation", "profile-validation-secret-canary"
    )
    return (
        service,
        observed,
        str(saved["configurationFingerprint"]),
        int(metadata["credentialRevision"]),
        backend,
    )


def _validate_arguments(fingerprint: str, revision: int) -> dict[str, object]:
    return {
        "profileRef": "model.validation",
        "capability": "model",
        "expectedConfigurationFingerprint": fingerprint,
        "credentialRevision": revision,
        "idempotencyKey": "validate-model-binding-1",
    }


def _approve_operation(
    service: CardService, audience: object, operation_intent_id: str
) -> dict[str, object]:
    confirmation = call_system_tool(
        service,
        tool_name=REQUEST_OPERATION_CONFIRMATION_TOOL,
        arguments={"operationIntentId": operation_intent_id},
        audience_session=audience,
        user_action_timeout_seconds=0,
    )["structuredContent"]
    deadline = time.monotonic() + 10
    while confirmation["state"] == "open":
        confirmation = call_system_tool(
            service,
            tool_name=REQUEST_OPERATION_CONFIRMATION_TOOL,
            arguments={"operationIntentId": operation_intent_id},
            audience_session=audience,
            user_action_timeout_seconds=0,
        )["structuredContent"]
        if time.monotonic() >= deadline:
            raise AssertionError("trusted operation fixture did not finish")
        time.sleep(0.02)
    return confirmation


def test_remote_profile_validation_requires_trusted_confirmation_and_records_ready(
    tmp_path: Path,
) -> None:
    service, observed, fingerprint, revision, _ = _service(tmp_path)
    audience = create_development_mcp_audience()
    arguments = _validate_arguments(fingerprint, revision)

    first = call_system_tool(
        service,
        tool_name=VALIDATE_PROFILE_TOOL,
        arguments=arguments,
        audience_session=audience,
        user_action_timeout_seconds=0,
    )["structuredContent"]
    assert first["state"] == "confirmation_required"
    assert observed == []

    confirmation = _approve_operation(
        service, audience, str(first["operationIntentId"])
    )
    assert confirmation["state"] == "approved"
    assert observed == []

    started = call_system_tool(
        service,
        tool_name=VALIDATE_PROFILE_TOOL,
        arguments=arguments,
        audience_session=audience,
        user_action_timeout_seconds=0,
    )["structuredContent"]
    assert started["intent"] == "validate_profile"
    task_id = started["taskId"]
    deadline = time.monotonic() + 60
    task = service.get_public_study_task(
        audience=audience.audience, task_id=task_id
    )
    while task["state"] in {"queued", "running", "cancelling"}:
        if time.monotonic() >= deadline:
            raise AssertionError("profile validation task did not finish")
        time.sleep(0.05)
        task = service.get_public_study_task(
            audience=audience.audience, task_id=task_id
        )

    assert task["state"] == "succeeded", task.get("error")
    assert task["result"]["status"] == "passed"
    assert len(observed) == 1
    profiles = service.list_service_profiles()["profiles"]
    assert profiles[0]["state"] == "ready"
    persisted = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in tmp_path.rglob("*.json")
    )
    assert "profile-validation-secret-canary" not in persisted


def test_profile_validation_rejects_stale_binding_before_network(
    tmp_path: Path,
) -> None:
    service, observed, fingerprint, revision, _ = _service(tmp_path)
    audience = create_development_mcp_audience()
    with pytest.raises(CardServiceError) as captured:
        service.validate_service_profile(
            audience=audience.audience,
            profile_ref="model.validation",
            capability="model",
            expected_configuration_fingerprint="0" * 64,
            credential_revision=revision,
            idempotency_key="stale-binding",
        )
    assert captured.value.code == "PROFILE_VALIDATION_BINDING_STALE"
    assert fingerprint != "0" * 64
    assert observed == []


def test_unconsumed_profile_validation_approval_can_be_revoked_in_trusted_manager(
    tmp_path: Path,
) -> None:
    service, observed, fingerprint, revision, _ = _service(tmp_path)
    audience_session = create_development_mcp_audience()
    first = call_system_tool(
        service,
        tool_name=VALIDATE_PROFILE_TOOL,
        arguments=_validate_arguments(fingerprint, revision),
        audience_session=audience_session,
        user_action_timeout_seconds=0,
    )["structuredContent"]
    assert _approve_operation(
        service, audience_session, str(first["operationIntentId"])
    )["state"] == "approved"

    opened = service.request_authorization_revocation(
        audience=audience_session.audience
    )
    session_ref = str(opened["authorizationSessionRef"])
    deadline = time.monotonic() + 10
    while opened["state"] in {"created", "open"}:
        opened = service.request_authorization_revocation(
            audience=audience_session.audience,
            authorization_session_ref=session_ref,
        )
        if time.monotonic() >= deadline:
            raise AssertionError("authorization manager fixture did not finish")
        time.sleep(0.02)
    assert opened["state"] == "completed"
    assert opened["results"] == [
        {"kind": "operation_approval", "disposition": "revoked"}
    ]
    assert observed == []

    retried = call_system_tool(
        service,
        tool_name=VALIDATE_PROFILE_TOOL,
        arguments=_validate_arguments(fingerprint, revision),
        audience_session=audience_session,
        user_action_timeout_seconds=0,
    )["structuredContent"]
    assert retried["state"] == "revoked"
    assert observed == []


def test_credential_change_after_approval_invalidates_old_binding_without_network(
    tmp_path: Path,
) -> None:
    service, observed, fingerprint, revision, backend = _service(tmp_path)
    audience_session = create_development_mcp_audience()
    arguments = _validate_arguments(fingerprint, revision)
    first = call_system_tool(
        service,
        tool_name=VALIDATE_PROFILE_TOOL,
        arguments=arguments,
        audience_session=audience_session,
        user_action_timeout_seconds=0,
    )["structuredContent"]
    assert _approve_operation(
        service, audience_session, str(first["operationIntentId"])
    )["state"] == "approved"
    metadata = CredentialStore(
        state_dir=service.store.root / "trusted-surfaces" / "credentials",
        backend=backend,
    ).set_secret("model.validation", "replacement-profile-secret")
    assert int(metadata["credentialRevision"]) == revision + 1

    with pytest.raises(CardServiceError) as captured:
        service.validate_service_profile(
            audience=audience_session.audience,
            profile_ref="model.validation",
            capability="model",
            expected_configuration_fingerprint=fingerprint,
            credential_revision=revision,
            idempotency_key="validate-model-binding-1",
        )
    assert captured.value.code == "PROFILE_VALIDATION_BINDING_STALE"
    assert observed == []


def test_tts_profile_validation_uses_same_consent_and_single_call_boundary(
    tmp_path: Path,
) -> None:
    backend = InMemoryCredentialBackend()
    observed: list[object] = []
    audio = b"ID3" + b"\x00" * 128

    def transport(request: object) -> ProviderTransportResponse:
        observed.append(request)
        return ProviderTransportResponse(
            200,
            "https://api.x.ai/v1/tts",
            {"content-type": "audio/mpeg"},
            audio,
        )

    state = (tmp_path / "tts-state").resolve()
    service = CardService(
        state_dir=state,
        worker_path=WORKER.resolve(),
        python_path=Path(sys.executable).resolve(),
        method_policies={
            "runtime.test_tts": MethodPolicy(
                "test_tts", 120.0, requires_broker=True
            )
        },
        credential_backend=backend,
        trusted_surface_path=FAKE_SURFACE.resolve(),
        use_restricted_launcher=False,
        hermes_proxy_manager=ReadyHermesProxyManager(),  # type: ignore[arg-type]
        profile_validation_transports={"tts.validation": transport},
    )
    saved = service.save_service_profile(
        {
            "profileRef": "tts.validation",
            "capability": "tts",
            "provider": "xai",
            "baseUrl": "https://api.x.ai/v1",
            "model": "grok-tts",
            "voice": "eve",
            "timeoutSeconds": 120,
            "maximumResponseBytes": 512 * 1024,
            "authMode": "bearer",
        },
        expected_revision=0,
        operation_id="seed-tts-profile",
    )
    metadata = CredentialStore(
        state_dir=state / "trusted-surfaces" / "credentials",
        backend=backend,
    ).set_secret("tts.validation", "tts-validation-secret-canary")
    audience = create_development_mcp_audience()
    arguments = {
        "profileRef": "tts.validation",
        "capability": "tts",
        "expectedConfigurationFingerprint": saved["configurationFingerprint"],
        "credentialRevision": metadata["credentialRevision"],
        "idempotencyKey": "validate-tts-binding-1",
    }
    first = call_system_tool(
        service,
        tool_name=VALIDATE_PROFILE_TOOL,
        arguments=arguments,
        audience_session=audience,
        user_action_timeout_seconds=0,
    )["structuredContent"]
    assert first["state"] == "confirmation_required"
    assert observed == []
    assert _approve_operation(
        service, audience, str(first["operationIntentId"])
    )["state"] == "approved"
    started = call_system_tool(
        service,
        tool_name=VALIDATE_PROFILE_TOOL,
        arguments=arguments,
        audience_session=audience,
        user_action_timeout_seconds=0,
    )["structuredContent"]
    deadline = time.monotonic() + 60
    task = service.get_public_study_task(
        audience=audience.audience, task_id=str(started["taskId"])
    )
    while task["state"] in {"queued", "running", "cancelling"}:
        if time.monotonic() >= deadline:
            raise AssertionError("TTS profile validation task did not finish")
        time.sleep(0.05)
        task = service.get_public_study_task(
            audience=audience.audience, task_id=str(started["taskId"])
        )
    assert task["state"] == "succeeded", task.get("error")
    assert task["result"]["status"] == "passed"
    assert len(observed) == 1
    persisted = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in tmp_path.rglob("*.json")
    )
    assert "tts-validation-secret-canary" not in persisted


def test_anki_connect_profile_validation_is_loopback_bounded_and_needs_no_remote_consent(
    tmp_path: Path,
) -> None:
    requests: list[dict[str, object]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
            length = int(self.headers.get("Content-Length") or "0")
            requests.append(json.loads(self.rfile.read(length)))
            body = json.dumps({"result": 6, "error": None}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        service = CardService(
            state_dir=(tmp_path / "anki-state").resolve(),
            worker_path=WORKER.resolve(),
            python_path=Path(sys.executable).resolve(),
            method_policies={},
            credential_backend=InMemoryCredentialBackend(),
            trusted_surface_path=FAKE_SURFACE.resolve(),
            use_restricted_launcher=False,
            hermes_proxy_manager=ReadyHermesProxyManager(),  # type: ignore[arg-type]
        )
        saved = service.save_service_profile(
            {
                "profileRef": "anki.validation",
                "capability": "anki_connect",
                "provider": "anki_connect",
                "baseUrl": f"http://127.0.0.1:{server.server_port}",
                "apiVersion": 6,
                "timeoutSeconds": 5,
                "maximumResponseBytes": 64 * 1024,
                "authMode": "none",
            },
            expected_revision=0,
            operation_id="seed-anki-profile",
        )
        audience = create_development_mcp_audience()
        result = call_system_tool(
            service,
            tool_name=VALIDATE_PROFILE_TOOL,
            arguments={
                "profileRef": "anki.validation",
                "capability": "anki_connect",
                "expectedConfigurationFingerprint": saved[
                    "configurationFingerprint"
                ],
                "credentialRevision": 0,
                "idempotencyKey": "validate-anki-binding-1",
            },
            audience_session=audience,
            user_action_timeout_seconds=0,
        )["structuredContent"]
        assert result["state"] == "ready"
        assert result["nextAction"] == "none"
        assert result["verification"]["status"] == "passed"
        assert requests == [{"action": "version", "version": 6, "params": {}}]
        assert not list(
            (service.store.root / "authorization-ledger").glob(
                "operation-intents/*/*.json"
            )
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_failed_remote_validation_is_latest_result_and_retry_does_not_recall_service(
    tmp_path: Path,
) -> None:
    service, observed, fingerprint, revision, _ = _service(tmp_path)

    def failing_transport(request: object) -> ProviderTransportResponse:
        observed.append(request)
        return ProviderTransportResponse(
            401,
            "https://api.openai.com/v1/chat/completions",
            {"content-type": "application/json"},
            b'{"error":{"message":"credential rejected"}}',
        )

    service._profile_validation_transports["model.validation"] = failing_transport
    audience = create_development_mcp_audience()
    arguments = _validate_arguments(fingerprint, revision)
    first = call_system_tool(
        service,
        tool_name=VALIDATE_PROFILE_TOOL,
        arguments=arguments,
        audience_session=audience,
        user_action_timeout_seconds=0,
    )["structuredContent"]
    assert _approve_operation(
        service, audience, str(first["operationIntentId"])
    )["state"] == "approved"
    started = call_system_tool(
        service,
        tool_name=VALIDATE_PROFILE_TOOL,
        arguments=arguments,
        audience_session=audience,
        user_action_timeout_seconds=0,
    )["structuredContent"]
    deadline = time.monotonic() + 60
    task = service.get_public_study_task(
        audience=audience.audience, task_id=str(started["taskId"])
    )
    while task["state"] in {"queued", "running", "cancelling"}:
        if time.monotonic() >= deadline:
            raise AssertionError("failed profile validation task did not finish")
        time.sleep(0.05)
        task = service.get_public_study_task(
            audience=audience.audience, task_id=str(started["taskId"])
        )
    assert task["state"] == "succeeded"
    assert task["result"]["status"] == "failed"
    assert task["result"]["verification"]["status"] == "failed"
    assert len(observed) == 1
    profile = service.list_service_profiles()["profiles"][0]
    assert profile["state"] != "ready"
    assert profile["latestVerification"]["status"] == "failed"

    repeated = call_system_tool(
        service,
        tool_name=VALIDATE_PROFILE_TOOL,
        arguments=arguments,
        audience_session=audience,
        user_action_timeout_seconds=0,
    )["structuredContent"]
    assert repeated["taskId"] == started["taskId"]
    assert repeated["result"]["status"] == "failed"
    assert len(observed) == 1


def test_concurrent_profile_validation_start_reuses_one_task_and_one_remote_call(
    tmp_path: Path,
) -> None:
    service, observed, fingerprint, revision, _ = _service(tmp_path)
    audience = create_development_mcp_audience()
    arguments = _validate_arguments(fingerprint, revision)
    first = call_system_tool(
        service,
        tool_name=VALIDATE_PROFILE_TOOL,
        arguments=arguments,
        audience_session=audience,
        user_action_timeout_seconds=0,
    )["structuredContent"]
    assert _approve_operation(
        service, audience, str(first["operationIntentId"])
    )["state"] == "approved"
    barrier = threading.Barrier(3)
    results: list[dict[str, object]] = []
    errors: list[Exception] = []

    def start() -> None:
        barrier.wait()
        try:
            results.append(
                service.validate_service_profile(
                    audience=audience.audience,
                    profile_ref="model.validation",
                    capability="model",
                    expected_configuration_fingerprint=fingerprint,
                    credential_revision=revision,
                    idempotency_key="validate-model-binding-1",
                )
            )
        except Exception as error:  # pragma: no cover - asserted below
            errors.append(error)

    threads = [threading.Thread(target=start), threading.Thread(target=start)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=30)
    assert errors == []
    assert len(results) == 2
    assert {str(result["taskId"]) for result in results} == {
        str(results[0]["taskId"])
    }
    deadline = time.monotonic() + 60
    task = service.get_public_study_task(
        audience=audience.audience, task_id=str(results[0]["taskId"])
    )
    while task["state"] in {"queued", "running", "cancelling"}:
        if time.monotonic() >= deadline:
            raise AssertionError("concurrent validation task did not finish")
        time.sleep(0.05)
        task = service.get_public_study_task(
            audience=audience.audience, task_id=str(results[0]["taskId"])
        )
    assert task["result"]["status"] == "passed"
    assert len(observed) == 1


def test_cancelled_profile_validation_never_publishes_ready_verification(
    tmp_path: Path,
) -> None:
    service, observed, fingerprint, revision, _ = _service(tmp_path)
    entered = threading.Event()
    release = threading.Event()

    def blocking_transport(request: object) -> ProviderTransportResponse:
        observed.append(request)
        entered.set()
        release.wait(timeout=15)
        return ProviderTransportResponse(
            200,
            "https://api.openai.com/v1/chat/completions",
            {"content-type": "application/json"},
            _valid_openai_response(),
        )

    service._profile_validation_transports["model.validation"] = blocking_transport
    audience = create_development_mcp_audience()
    arguments = _validate_arguments(fingerprint, revision)
    first = call_system_tool(
        service,
        tool_name=VALIDATE_PROFILE_TOOL,
        arguments=arguments,
        audience_session=audience,
        user_action_timeout_seconds=0,
    )["structuredContent"]
    assert _approve_operation(
        service, audience, str(first["operationIntentId"])
    )["state"] == "approved"
    started = call_system_tool(
        service,
        tool_name=VALIDATE_PROFILE_TOOL,
        arguments=arguments,
        audience_session=audience,
        user_action_timeout_seconds=0,
    )["structuredContent"]
    assert entered.wait(timeout=15)
    cancelling = service.cancel_public_study_task(
        audience=audience.audience, task_id=str(started["taskId"])
    )
    assert cancelling["state"] in {"cancelling", "cancelled"}
    release.set()
    deadline = time.monotonic() + 30
    task = service.get_public_study_task(
        audience=audience.audience, task_id=str(started["taskId"])
    )
    while task["state"] in {"queued", "running", "cancelling"}:
        if time.monotonic() >= deadline:
            raise AssertionError("cancelled profile validation task did not finish")
        time.sleep(0.05)
        task = service.get_public_study_task(
            audience=audience.audience, task_id=str(started["taskId"])
        )
    assert task["state"] == "cancelled"
    assert "result" not in task
    profile = service.list_service_profiles()["profiles"][0]
    assert profile["state"] != "ready"
    assert profile.get("latestVerification") is None
    assert len(observed) == 1


def test_restart_marks_inflight_profile_validation_interrupted_without_false_ready(
    tmp_path: Path,
) -> None:
    service, observed, fingerprint, revision, backend = _service(tmp_path)
    audience = create_development_mcp_audience()
    arguments = _validate_arguments(fingerprint, revision)
    first = call_system_tool(
        service,
        tool_name=VALIDATE_PROFILE_TOOL,
        arguments=arguments,
        audience_session=audience,
        user_action_timeout_seconds=0,
    )["structuredContent"]
    assert _approve_operation(
        service, audience, str(first["operationIntentId"])
    )["state"] == "approved"
    task_id = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"codex-study:profile-validation:{first['operationIntentId']}",
        )
    )
    service.store.write_task(
        task_id,
        {
            "schemaVersion": 1,
            "id": task_id,
            "method": "runtime.test_model",
            "workerCommand": "test_api",
            "state": "running",
            "cancellable": True,
            "startedAt": int(time.time() * 1000),
            "updatedAt": int(time.time() * 1000),
            "progress": {
                "phase": "provider_call",
                "phaseLabel": "Calling provider",
                "phasePercent": None,
                "overallPercent": None,
                "message": "Waiting for provider",
                "lastProgressAt": int(time.time() * 1000),
            },
            "profileValidation": {
                "schemaVersion": 1,
                "operationIntentId": first["operationIntentId"],
                "capability": "model",
                "profileRef": "model.validation",
                "configurationFingerprint": fingerprint,
                "credentialRevision": revision,
            },
        },
    )
    restarted = CardService(
        state_dir=service.store.root,
        worker_path=WORKER.resolve(),
        python_path=Path(sys.executable).resolve(),
        method_policies={
            "runtime.test_model": MethodPolicy(
                "test_api", 120.0, requires_broker=True
            )
        },
        credential_backend=backend,
        trusted_surface_path=FAKE_SURFACE.resolve(),
        use_restricted_launcher=False,
        hermes_proxy_manager=ReadyHermesProxyManager(),  # type: ignore[arg-type]
    )
    recovered = restarted.get_task(task_id)
    assert recovered is not None
    assert recovered["state"] == "interrupted"
    assert recovered["error"]["code"] == "SERVICE_RESTARTED"
    assert "profileValidationOutcome" not in recovered
    with pytest.raises(CardServiceError) as stale_session:
        restarted.get_public_study_task(
            audience=audience.audience, task_id=task_id
        )
    assert stale_session.value.code == "AUTHORIZATION_AUDIENCE_MISMATCH"
    profile = restarted.list_service_profiles()["profiles"][0]
    assert profile["state"] != "ready"
    assert profile.get("latestVerification") is None
    assert observed == []
