from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from card_service.broker_configuration import (
    AUTHORIZATION_SCHEMA,
    BrokerAuthorizationConfiguration,
    BrokerConfigurationError,
    ServiceBrokerRuntime,
    profile_configuration_fingerprint,
)
from card_service.credentials import CredentialStore, InMemoryCredentialBackend
from card_service.broker_ipc import BrokerIpcError
from card_service.provider_egress import ProviderProfile, ProviderTransportResponse
from card_service.runtime_manifest import canonical_bytes
from card_service.service import CardService, CardServiceError, MethodPolicy
from card_service.source_acquisition import SourceFetchResponse


ROOT = Path(__file__).resolve().parents[1]
FAKE_WORKER = ROOT / "tests" / "fixtures" / "card_service" / "fake_worker.py"
REAL_WORKERS = ROOT / "workers"


def _profile(*, hermes: bool = False) -> ProviderProfile:
    return ProviderProfile(
        profile_ref="model.primary",
        capability="model",
        provider="hermes" if hermes else "openai",
        base_url="http://127.0.0.1:8317/v1" if hermes else "https://api.openai.com/v1",
        model="grok-4.5" if hermes else "gpt-service-owned",
        maximum_response_bytes=4096,
    )


def _manifest_value(
    profile: ProviderProfile,
    *,
    credential_revision: int,
    expires_at: int | None = None,
    source_enabled: bool = False,
    source_binding: bool = False,
) -> dict[str, object]:
    extraction_binding = {"model": profile.profile_ref}
    if source_binding:
        extraction_binding["source"] = "source.youtube_subtitles"
    return {
        "schema": AUTHORIZATION_SCHEMA,
        "schemaVersion": 1,
        "operationIntentRef": "intent-approved-startup-1",
        "expiresAtUnixMs": expires_at or int(time.time() * 1000) + 60_000,
        "budget": {
            "maxRemoteCalls": 8,
            "maxRequestBytes": 500_000,
            "maxResponseBytes": 8 * 1024 * 1024,
            "maxCostMinorUnits": 100,
        },
        "profiles": [
            {
                "profileRef": profile.profile_ref,
                "capability": profile.capability,
                "provider": profile.provider,
                "baseUrl": profile.base_url,
                "model": profile.model,
                "voice": profile.voice,
                "timeoutSeconds": profile.timeout_seconds,
                "maximumResponseBytes": profile.maximum_response_bytes,
                "configurationFingerprint": profile_configuration_fingerprint(profile),
                "credentialRevision": credential_revision,
                "reservedCostMinorUnits": 5,
            }
        ],
        "methodBindings": {
            "runtime.extract_learning_points": extraction_binding,
        },
        "sourceAcquisition": {
            "youtubeSubtitles": {
                "enabled": source_enabled,
                "timeoutSeconds": 30,
            }
        },
    }


def _write_manifest(path: Path, value: dict[str, object]) -> Path:
    path.write_bytes(canonical_bytes(value))
    return path.resolve()


def _configured_runtime(tmp_path: Path) -> tuple[ServiceBrokerRuntime, list[object]]:
    state_dir = (tmp_path / "state").resolve()
    backend = InMemoryCredentialBackend()
    credentials = CredentialStore(
        state_dir=(state_dir / "trusted-surfaces" / "credentials").resolve(),
        backend=backend,
    )
    metadata = credentials.set_secret("model.primary", "provider-secret-canary")
    profile = _profile()
    authorization_dir = state_dir / "trusted-surfaces" / "authorizations"
    authorization_dir.mkdir(parents=True, exist_ok=True)
    manifest = _write_manifest(
        authorization_dir / "broker-authorization.json",
        _manifest_value(profile, credential_revision=int(metadata["credentialRevision"])),
    )
    observed: list[object] = []

    def transport(request):
        observed.append(request)
        body = json.loads(request.body)
        assert body["model"] == "gpt-service-owned"
        assert request.headers["Authorization"] == "Bearer provider-secret-canary"
        return ProviderTransportResponse(
            200,
            request.url,
            {"content-type": "application/json"},
            b'{"choices":[{"message":{"content":"service-owned-ok"}}]}',
        )

    runtime = ServiceBrokerRuntime.from_manifest(
        manifest,
        state_dir=state_dir,
        credential_backend=backend,
        transport_overrides={"model.primary": transport},
    )
    return runtime, observed


def test_service_owned_configuration_resolves_profile_intent_secret_and_budget(tmp_path: Path) -> None:
    runtime, observed = _configured_runtime(tmp_path)
    assert runtime.method_blocker("runtime.extract_learning_points") is None
    assert runtime.method_blocker("runtime.generate_cards") == "broker_authorization_missing"
    capabilities = runtime.capabilities()
    assert capabilities["serviceOwnedAuthorizationResolver"] is True
    assert capabilities["pathDisclosure"] is False
    assert str(tmp_path) not in json.dumps(capabilities, ensure_ascii=False)

    handler = runtime.handler_factory("task-formal-runtime", "runtime.extract_learning_points", {})
    result = handler(
        "model.openai_chat",
        {
            "workUnitId": "batch-1",
            "request": {
                "model": "worker-spoofed-model",
                "messages": [{"role": "user", "content": "hello"}],
                "max_tokens": 50,
            },
        },
    )
    assert result["choices"][0]["message"]["content"] == "service-owned-ok"
    assert len(observed) == 1
    record = runtime.ledger.list_records()[0]
    assert record["profileRef"] == "model.primary"
    assert record["operationIntentRef"] == "intent-approved-startup-1"
    persisted = (tmp_path / "state" / "broker" / "reservation-ledger-v1.json").read_text(encoding="utf-8")
    assert "provider-secret-canary" not in persisted


def test_formal_runtime_drives_card_service_and_rejects_task_owned_authorization(tmp_path: Path) -> None:
    runtime, observed = _configured_runtime(tmp_path)
    service = CardService(
        state_dir=(tmp_path / "state").resolve(),
        worker_path=FAKE_WORKER.resolve(),
        python_path=Path(sys.executable).resolve(),
        method_policies={
            "runtime.check_environment": MethodPolicy("check_env", 4.0),
            "runtime.extract_learning_points": MethodPolicy(
                "extract_learning_points",
                4.0,
                requires_broker=True,
            )
        },
        broker_handler_factory=runtime.handler_factory,
        broker_method_blocker=runtime.method_blocker,
        broker_runtime_capabilities=runtime.capabilities(),
        use_restricted_launcher=False,
    )
    assert service.capabilities()["methodAvailability"]["runtime.extract_learning_points"] == {
        "available": True,
        "blocker": None,
    }
    started = service.start_task("runtime.extract_learning_points", {"mode": "broker_typed"})
    deadline = time.monotonic() + 5
    snapshot = service.get_task(str(started["id"]))
    while snapshot is not None and snapshot["state"] not in {"succeeded", "failed", "cancelled", "interrupted"}:
        assert time.monotonic() < deadline
        time.sleep(0.02)
        snapshot = service.get_task(str(started["id"]))
    assert snapshot is not None and snapshot["state"] == "succeeded"
    result = service.read_result(str(started["id"]))
    assert result["brokered"]["choices"][0]["message"]["content"] == "service-owned-ok"
    assert len(observed) == 1

    environment = service.start_task("runtime.check_environment", {"ordinary": "input-canary"})
    deadline = time.monotonic() + 5
    environment_snapshot = service.get_task(str(environment["id"]))
    while environment_snapshot is not None and environment_snapshot["state"] not in {
        "succeeded",
        "failed",
        "cancelled",
        "interrupted",
    }:
        assert time.monotonic() < deadline
        time.sleep(0.02)
        environment_snapshot = service.get_task(str(environment["id"]))
    assert environment_snapshot is not None and environment_snapshot["state"] == "succeeded"
    assert len(observed) == 1

    with pytest.raises(CardServiceError) as caught:
        service.start_task(
            "runtime.extract_learning_points",
            {"mode": "broker_typed", "profileRef": "attacker-selected"},
        )
    assert caught.value.code == "SERVICE_OWNED_AUTHORIZATION_IN_REQUEST"
    assert len(service.list_recoverable_tasks()) == 0


def test_stale_credential_revision_blocks_method_before_task_creation(tmp_path: Path) -> None:
    runtime, _ = _configured_runtime(tmp_path)
    runtime.credential_store.set_secret("model.primary", "rotated-secret")
    assert runtime.method_blocker("runtime.extract_learning_points") == "broker_profile_unavailable"


def test_formal_runtime_authorizes_only_task_bound_youtube_subtitle_acquisition(tmp_path: Path) -> None:
    state_dir = (tmp_path / "state").resolve()
    backend = InMemoryCredentialBackend()
    credentials = CredentialStore(
        state_dir=(state_dir / "trusted-surfaces" / "credentials").resolve(),
        backend=backend,
    )
    metadata = credentials.set_secret("model.primary", "provider-secret")
    profile = _profile()
    authorization_dir = state_dir / "trusted-surfaces" / "authorizations"
    authorization_dir.mkdir(parents=True, exist_ok=True)
    manifest = _write_manifest(
        authorization_dir / "source-authorization.json",
        _manifest_value(
            profile,
            credential_revision=int(metadata["credentialRevision"]),
            source_enabled=True,
            source_binding=True,
        ),
    )
    caption_url = "https://www.youtube.com/api/timedtext?v=dQw4w9WgXcQ&lang=en&sig=secret-canary"
    player = {
        "captions": {
            "playerCaptionsTracklistRenderer": {
                "captionTracks": [{"baseUrl": caption_url, "languageCode": "en"}]
            }
        },
        "videoDetails": {"title": "Task-bound video"},
    }
    watch = ("<script>ytInitialPlayerResponse = " + json.dumps(player) + ";</script>").encode("utf-8")
    vtt = b"WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHello\n"
    source_sends: list[str] = []

    def source_transport(url: str, _maximum_bytes: int, _timeout_seconds: float) -> SourceFetchResponse:
        source_sends.append(url)
        body = watch if "/watch?" in url else vtt
        return SourceFetchResponse(200, url, {}, body, "142.250.1.1")

    runtime = ServiceBrokerRuntime.from_manifest(
        manifest,
        state_dir=state_dir,
        credential_backend=backend,
        source_transport=source_transport,
    )
    task_request = {
        "source_mode": "url",
        "source_url": "https://youtu.be/dQw4w9WgXcQ",
        "language": "English",
    }
    handler = runtime.handler_factory("task-source", "runtime.extract_learning_points", task_request)
    result = handler(
        "source.youtube_subtitles",
        {
            "workUnitId": "source:subtitle:1",
            "request": {"videoId": "dQw4w9WgXcQ", "language": "en", "format": "vtt"},
        },
    )
    assert result["title"] == "Task-bound video"
    assert len(source_sends) == 2
    record = runtime.ledger.list_records()[0]
    assert record["capability"] == "source"
    assert record["profileRef"] == "source.youtube_subtitles"
    assert "secret-canary" not in (state_dir / "broker" / "reservation-ledger-v1.json").read_text(encoding="utf-8")

    blocked = runtime.handler_factory(
        "task-local",
        "runtime.extract_learning_points",
        {"source_mode": "local", "language": "English"},
    )
    with pytest.raises(BrokerIpcError) as caught:
        blocked(
            "source.youtube_subtitles",
            {
                "workUnitId": "source:subtitle:1",
                "request": {"videoId": "dQw4w9WgXcQ", "language": "en", "format": "vtt"},
            },
        )
    assert getattr(caught.value, "code", "") == "SOURCE_NOT_AUTHORIZED"


def test_existing_v1_manifest_without_source_policy_remains_compatible(tmp_path: Path) -> None:
    state_dir = (tmp_path / "state").resolve()
    backend = InMemoryCredentialBackend()
    credentials = CredentialStore(
        state_dir=(state_dir / "trusted-surfaces" / "credentials").resolve(),
        backend=backend,
    )
    metadata = credentials.set_secret("model.primary", "provider-secret")
    profile = _profile()
    value = _manifest_value(profile, credential_revision=int(metadata["credentialRevision"]))
    value.pop("sourceAcquisition")
    authorization_dir = state_dir / "trusted-surfaces" / "authorizations"
    authorization_dir.mkdir(parents=True, exist_ok=True)
    manifest = _write_manifest(authorization_dir / "legacy-v1-authorization.json", value)

    runtime = ServiceBrokerRuntime.from_manifest(
        manifest,
        state_dir=state_dir,
        credential_backend=backend,
    )
    assert runtime.method_blocker("runtime.extract_learning_points") is None
    assert runtime.capabilities()["youtubeSubtitleAcquisition"] is False



def test_broker_factory_failure_happens_before_worker_process_launch(tmp_path: Path) -> None:
    def fail_factory(_task_id: str, _method: str, _request: dict[str, object]):
        raise RuntimeError("authorization race")

    service = CardService(
        state_dir=(tmp_path / "state").resolve(),
        worker_path=FAKE_WORKER.resolve(),
        python_path=Path(sys.executable).resolve(),
        method_policies={
            "runtime.extract_learning_points": MethodPolicy(
                "extract_learning_points",
                4.0,
                requires_broker=True,
            )
        },
        broker_handler_factory=fail_factory,
        broker_method_blocker=lambda _method: None,
        use_restricted_launcher=False,
    )
    with patch("card_service.service.subprocess.Popen") as popen:
        started = service.start_task("runtime.extract_learning_points", {"mode": "broker_typed"})
        deadline = time.monotonic() + 5
        snapshot = service.get_task(str(started["id"]))
        while snapshot is not None and snapshot["state"] not in {"succeeded", "failed", "cancelled", "interrupted"}:
            assert time.monotonic() < deadline
            time.sleep(0.02)
            snapshot = service.get_task(str(started["id"]))
    assert snapshot is not None and snapshot["state"] == "failed"
    assert snapshot["error"]["code"] == "BROKER_AUTHORIZATION_UNAVAILABLE"
    popen.assert_not_called()


def test_runtime_rejects_authorization_manifest_outside_trusted_surface(tmp_path: Path) -> None:
    profile = _profile(hermes=True)
    manifest = _write_manifest(
        tmp_path / "attacker-controlled-authorization.json",
        _manifest_value(profile, credential_revision=0),
    )
    with pytest.raises(BrokerConfigurationError) as caught:
        ServiceBrokerRuntime.from_manifest(manifest, state_dir=(tmp_path / "state").resolve())
    assert caught.value.code == "BROKER_MANIFEST_OUTSIDE_TRUSTED_SURFACE"


@pytest.mark.parametrize(
    ("mutate", "expected_code"),
    [
        (lambda value: value.update(unexpected=True), "BROKER_MANIFEST_INVALID"),
        (
            lambda value: value["profiles"][0].update(configurationFingerprint="sha256:" + "0" * 64),
            "BROKER_PROFILE_FINGERPRINT_MISMATCH",
        ),
        (
            lambda value: value["methodBindings"].update(
                {"runtime.test_tts": {"tts": "model.primary"}}
            ),
            "BROKER_METHOD_BINDING_INVALID",
        ),
    ],
)
def test_manifest_validation_fails_closed(tmp_path: Path, mutate, expected_code: str) -> None:
    profile = _profile(hermes=True)
    value = _manifest_value(profile, credential_revision=0)
    mutate(value)
    path = _write_manifest(tmp_path / "authorization.json", value)
    with pytest.raises(BrokerConfigurationError) as caught:
        BrokerAuthorizationConfiguration.load(path)
    assert caught.value.code == expected_code


def test_manifest_rejects_noncanonical_expired_and_overlong_authorization(tmp_path: Path) -> None:
    now = int(time.time() * 1000)
    profile = _profile(hermes=True)
    value = _manifest_value(profile, credential_revision=0)
    pretty = tmp_path / "pretty.json"
    pretty.write_text(json.dumps(value, indent=2), encoding="utf-8")
    with pytest.raises(BrokerConfigurationError) as noncanonical:
        BrokerAuthorizationConfiguration.load(pretty.resolve(), now_unix_ms=now)
    assert noncanonical.value.code == "BROKER_MANIFEST_NONCANONICAL"

    expired = _write_manifest(
        tmp_path / "expired.json",
        _manifest_value(profile, credential_revision=0, expires_at=now - 1),
    )
    with pytest.raises(BrokerConfigurationError) as expired_error:
        BrokerAuthorizationConfiguration.load(expired, now_unix_ms=now)
    assert expired_error.value.code == "BROKER_AUTHORIZATION_EXPIRED"

    overlong = _write_manifest(
        tmp_path / "overlong.json",
        _manifest_value(profile, credential_revision=0, expires_at=now + 24 * 60 * 60 * 1000 + 1),
    )
    with pytest.raises(BrokerConfigurationError) as overlong_error:
        BrokerAuthorizationConfiguration.load(overlong, now_unix_ms=now)
    assert overlong_error.value.code == "BROKER_AUTHORIZATION_INVALID"


def test_stdio_launcher_composes_service_owned_runtime_without_disclosing_manifest_path(tmp_path: Path) -> None:
    profile = _profile(hermes=True)
    state_dir = (tmp_path / "stdio-state").resolve()
    authorization_dir = state_dir / "trusted-surfaces" / "authorizations"
    authorization_dir.mkdir(parents=True, exist_ok=True)
    manifest = _write_manifest(
        authorization_dir / "authorization.json",
        _manifest_value(profile, credential_revision=0),
    )
    command = [
        sys.executable,
        "-m",
        "card_service.stdio",
        "--state-dir",
        str(state_dir),
        "--development-unpackaged-runtime",
        "--worker",
        str(FAKE_WORKER.resolve()),
        "--python",
        str(Path(sys.executable).resolve()),
        "--broker-authorization-manifest",
        str(manifest),
    ]
    request = '{"jsonrpc":"2.0","id":1,"method":"system.get_capabilities","params":{}}\n'
    completed = subprocess.run(
        command,
        cwd=ROOT,
        input=request,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    response = json.loads(completed.stdout.strip())
    broker = response["result"]["modelTtsBroker"]
    assert broker["serviceOwnedAuthorizationResolver"] is True
    assert broker["taskOwnedWorkerTransport"] is True
    assert broker["pathDisclosure"] is False
    assert str(manifest) not in completed.stdout


def test_real_restricted_worker_extracts_learning_points_through_source_and_model_brokers(tmp_path: Path) -> None:
    runtime_root = tmp_path / "managed-runtime"
    shutil.copytree(REAL_WORKERS, runtime_root)
    real_worker = (runtime_root / "anki_worker.py").resolve()
    state_dir = (tmp_path / "service-state").resolve()
    backend = InMemoryCredentialBackend()
    credentials = CredentialStore(
        state_dir=(state_dir / "trusted-surfaces" / "credentials").resolve(),
        backend=backend,
    )
    metadata = credentials.set_secret("model.primary", "model-secret-canary")
    profile = _profile()
    authorization_dir = state_dir / "trusted-surfaces" / "authorizations"
    authorization_dir.mkdir(parents=True, exist_ok=True)
    manifest = _write_manifest(
        authorization_dir / "real-worker-source-authorization.json",
        _manifest_value(
            profile,
            credential_revision=int(metadata["credentialRevision"]),
            source_enabled=True,
            source_binding=True,
        ),
    )

    caption_url = (
        "https://www.youtube.com/api/timedtext?v=dQw4w9WgXcQ&lang=en&sig=caption-secret-canary"
    )
    player = {
        "captions": {
            "playerCaptionsTracklistRenderer": {
                "captionTracks": [{"baseUrl": caption_url, "languageCode": "en"}]
            }
        },
        "videoDetails": {"title": "Brokered learning source"},
    }
    watch = ("<script>ytInitialPlayerResponse = " + json.dumps(player) + ";</script>").encode("utf-8")
    vtt = (
        b"WEBVTT\n\n00:00:01.000 --> 00:00:04.000\n"
        b"I'm not really in the mood for this right now.\n"
    )
    source_sends: list[str] = []
    model_sends: list[object] = []

    def source_transport(url: str, _maximum_bytes: int, _timeout_seconds: float) -> SourceFetchResponse:
        source_sends.append(url)
        return SourceFetchResponse(200, url, {}, watch if "/watch?" in url else vtt, "142.250.1.1")

    def model_transport(request):
        model_sends.append(request)
        body = json.loads(request.body)
        assert body["model"] == "gpt-service-owned"
        prompt = str(body["messages"][-1]["content"])
        marker = "字幕和候选_JSON_START"
        assert marker in prompt
        compact = json.loads(prompt.split(marker, 1)[1].strip())
        sources = []
        for source in compact:
            reviews = []
            for candidate in source.get("local_candidates") or []:
                answer = candidate.get("answer_core") or candidate.get("exact_span")
                reviews.append(
                    {
                        "id": candidate["id"],
                        "decision": "recommend",
                        "value_score": 5,
                        "estimated_level": candidate.get("local_level") or "B1",
                        "exact_span": candidate.get("exact_span"),
                        "answer_core": answer,
                        "normalized_answer": candidate.get("normalized_answer") or answer,
                        "candidate_kind": candidate.get("candidate_kind"),
                        "phrase_type": candidate.get("phrase_type"),
                        "learning_action": candidate.get("learning_action") or f"Practice {answer}.",
                        "reason": "Service-owned model review.",
                        "status_reason": "Recommended by bounded review.",
                    }
                )
            sources.append(
                {
                    "source_segment_id": source["source_segment_id"],
                    "reviews": reviews,
                    "new_learning_points": [],
                }
            )
        response = {"choices": [{"message": {"content": json.dumps({"sources": sources})}}]}
        return ProviderTransportResponse(
            200,
            request.url,
            {"content-type": "application/json"},
            json.dumps(response).encode("utf-8"),
        )

    broker_runtime = ServiceBrokerRuntime.from_manifest(
        manifest,
        state_dir=state_dir,
        credential_backend=backend,
        transport_overrides={"model.primary": model_transport},
        source_transport=source_transport,
    )
    service = CardService(
        state_dir=state_dir,
        worker_path=real_worker,
        python_path=Path(sys.executable).resolve(),
        method_policies={
            "runtime.extract_learning_points": MethodPolicy(
                "extract_learning_points",
                60.0,
                requires_broker=True,
            )
        },
        broker_handler_factory=broker_runtime.handler_factory,
        broker_method_blocker=broker_runtime.method_blocker,
        broker_runtime_capabilities=broker_runtime.capabilities(),
    )
    request = {
        "source_mode": "url",
        "source_url": "https://youtu.be/dQw4w9WgXcQ",
        "url_import_mode": "subtitles",
        "skip_video_slicing": True,
        "title": "Brokered source proof",
        "language": "English",
        "level": "B1",
        "language_focus": ["phrases", "vocabulary", "grammar", "listening"],
        "api_config": {"provider": "openai-compatible", "model": "worker-model-hint"},
    }
    started = service.start_task("runtime.extract_learning_points", request)
    deadline = time.monotonic() + 60
    snapshot = service.get_task(str(started["id"]))
    while snapshot is not None and snapshot["state"] not in {"succeeded", "failed", "cancelled", "interrupted"}:
        assert time.monotonic() < deadline
        time.sleep(0.05)
        snapshot = service.get_task(str(started["id"]))
    assert snapshot is not None and snapshot["state"] == "succeeded", snapshot.get("error") if snapshot else None
    result = service.read_result(str(started["id"]))
    assert result["learning_points"]
    assert result["source_info"]["source_acquisition"] == "card_service_broker"
    assert len(source_sends) == 2
    assert model_sends
    records = broker_runtime.ledger.list_records()
    assert {record["capability"] for record in records} == {"source", "model"}
    persisted = "\n".join(path.read_text(encoding="utf-8") for path in state_dir.rglob("*.json"))
    assert "model-secret-canary" not in persisted
    assert "caption-secret-canary" not in persisted
