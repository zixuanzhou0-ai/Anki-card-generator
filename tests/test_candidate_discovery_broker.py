from __future__ import annotations

import json
import time
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from card_service.artifact_registry import ArtifactAudienceBinding
from card_service.broker_configuration import (
    AUTHORIZATION_SCHEMA,
    BrokerAuthorizationConfiguration,
    ServiceBrokerRuntime,
    profile_configuration_fingerprint,
)
from card_service.candidate_discovery import CandidateDiscoveryModelIdentity
from card_service.candidate_discovery_runtime import CandidateDiscoveryRuntime
from card_service.candidate_discovery_broker import (
    BrokerCandidateDiscoveryModel,
    BrokerCandidateDiscoveryModelProvider,
    CandidateDiscoveryBrokerError,
)
from card_service.credentials import CredentialStore, InMemoryCredentialBackend
from card_service.provider_egress import ProviderProfile, ProviderTransportResponse
from card_service.runtime_manifest import canonical_bytes
from card_service.service import CardService, CardServiceError


IDENTITY = CandidateDiscoveryModelIdentity(
    profile_ref="model.discovery",
    configuration_fingerprint="a" * 64,
    credential_revision=1,
    implementation_version="service-broker-candidate-json-v1",
)


def _proposal_request() -> dict[str, Any]:
    return {
        "schema": "study.candidate-discovery.proposal-request",
        "schemaVersion": 1,
        "role": "high-recall-language-proposer-v1",
        "learningContract": {"purpose": "learn"},
        "sources": [
            {
                "representationId": "representation-1",
                "sourceId": "source-1",
                "supportTier": "full",
                "windows": [
                    {
                        "nodeId": "node-1",
                        "start": 0,
                        "end": 11,
                        "text": "hello world",
                    }
                ],
            }
        ],
        "constraints": {
            "maximumProposals": 8,
            "maximumSpansPerProposal": 4,
            "submitEligibility": False,
            "submitScores": False,
            "submitGateResults": False,
            "submitUserLocks": False,
        },
    }


def _review_request() -> dict[str, Any]:
    return {
        "schema": "study.candidate-discovery.review-request",
        "schemaVersion": 1,
        "role": "independent-learning-reviewer-v1",
        "learningContract": {"purpose": "learn"},
        "proposals": [],
        "constraints": {
            "submitEligibility": False,
            "submitScores": False,
            "submitGateResults": False,
            "duplicateDecisionOwnedByService": True,
        },
    }


def _outer(operation: str, value: dict[str, Any]) -> dict[str, Any]:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if operation == "model.openai_chat":
        return {"choices": [{"message": {"content": text}}]}
    if operation == "model.anthropic_messages":
        return {"content": [{"type": "text", "text": text}]}
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


@pytest.mark.parametrize(
    ("operation", "request_key"),
    [
        ("model.openai_chat", "messages"),
        ("model.anthropic_messages", "messages"),
        ("model.gemini_content", "contents"),
    ],
)
def test_adapter_builds_provider_specific_json_request_and_parses_one_object(
    operation: str,
    request_key: str,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def handler(op: str, payload: dict[str, Any]) -> dict[str, Any]:
        calls.append((op, payload))
        return _outer(op, {"schema": "result", "schemaVersion": 1})

    model = BrokerCandidateDiscoveryModel(
        identity=IDENTITY,
        operation=operation,
        handler=handler,
    )
    assert model.propose(_proposal_request()) == {
        "schema": "result",
        "schemaVersion": 1,
    }
    assert calls[0][0] == operation
    assert calls[0][1]["workUnitId"] == "candidate-proposer-v1"
    provider_request = calls[0][1]["request"]
    assert request_key in provider_request
    encoded = json.dumps(provider_request, ensure_ascii=False)
    assert "INPUT_JSON" in encoded
    assert "hello world" in encoded
    assert "profileRef" not in encoded
    assert "baseUrl" not in encoded
    assert "credentialRevision" not in encoded
    if operation == "model.openai_chat":
        assert provider_request["response_format"] == {"type": "json_object"}
        assert provider_request["stream"] is False
    elif operation == "model.gemini_content":
        assert (
            provider_request["generationConfig"]["responseMimeType"]
            == "application/json"
        )


def test_proposer_and_reviewer_use_distinct_stable_work_units() -> None:
    calls: list[dict[str, Any]] = []

    def handler(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        calls.append(payload)
        value = (
            {
                "schema": "study.candidate-discovery.proposals",
                "schemaVersion": 1,
                "proposals": [],
            }
            if payload["workUnitId"] == "candidate-proposer-v1"
            else {
                "schema": "study.candidate-discovery.reviews",
                "schemaVersion": 1,
                "reviews": [],
            }
        )
        return _outer(operation, value)

    model = BrokerCandidateDiscoveryModel(
        identity=IDENTITY,
        operation="model.openai_chat",
        handler=handler,
    )
    assert model.propose(_proposal_request())["proposals"] == []
    assert model.review(_review_request())["reviews"] == []
    assert [item["workUnitId"] for item in calls] == [
        "candidate-proposer-v1",
        "candidate-reviewer-v1",
    ]


@pytest.mark.parametrize(
    "content",
    [
        '\u0060\u0060\u0060json\n{"schemaVersion":1}\n\u0060\u0060\u0060',
        '{"schemaVersion":1,"schemaVersion":1}',
        "[]",
        "",
    ],
)
def test_adapter_rejects_markdown_duplicate_keys_non_object_and_empty_text(
    content: str,
) -> None:
    model = BrokerCandidateDiscoveryModel(
        identity=IDENTITY,
        operation="model.openai_chat",
        handler=lambda _operation, _payload: {
            "choices": [{"message": {"content": content}}]
        },
    )
    with pytest.raises(CandidateDiscoveryBrokerError) as caught:
        model.propose(_proposal_request())
    assert caught.value.code == "DISCOVERY_PROVIDER_RESPONSE_INVALID"


def test_adapter_rejects_a_prompt_over_the_broker_character_limit() -> None:
    calls = 0

    def handler(_operation: str, _payload: dict[str, Any]) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {}

    model = BrokerCandidateDiscoveryModel(
        identity=IDENTITY,
        operation="model.openai_chat",
        handler=handler,
    )
    with pytest.raises(CandidateDiscoveryBrokerError) as caught:
        model.propose({"oversized": "x" * 400_001})
    assert caught.value.code == "DISCOVERY_PROVIDER_REQUEST_INVALID"
    assert calls == 0


def test_provider_json_failure_is_classified_as_invalid_model_output() -> None:
    error = CandidateDiscoveryBrokerError(
        "DISCOVERY_PROVIDER_RESPONSE_INVALID",
        "invalid provider response",
    )
    assert CandidateDiscoveryRuntime._failure_code(error) == "MODEL_OUTPUT_INVALID"


@pytest.mark.parametrize(
    "code",
    [
        "PROVIDER_UNAVAILABLE",
        "PROVIDER_HTTP_ERROR",
        "CREDENTIAL_UNAVAILABLE",
        "BROKER_AUTHORIZATION_EXPIRED",
        "DISCOVERY_MODEL_UNAVAILABLE",
    ],
)
def test_provider_infrastructure_failure_is_classified_as_model_stale(code: str) -> None:
    error = CandidateDiscoveryBrokerError(code, "provider unavailable")
    assert CandidateDiscoveryRuntime._failure_code(error) == "MODEL_STALE"


def test_adapter_rejects_tool_or_multi_part_provider_content() -> None:
    anthropic = BrokerCandidateDiscoveryModel(
        identity=IDENTITY,
        operation="model.anthropic_messages",
        handler=lambda _operation, _payload: {
            "content": [{"type": "tool_use", "name": "unsafe"}]
        },
    )
    with pytest.raises(CandidateDiscoveryBrokerError):
        anthropic.propose(_proposal_request())

    gemini = BrokerCandidateDiscoveryModel(
        identity=IDENTITY,
        operation="model.gemini_content",
        handler=lambda _operation, _payload: {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "{}"},
                            {"text": '{"second":true}'},
                        ]
                    }
                }
            ]
        },
    )
    with pytest.raises(CandidateDiscoveryBrokerError):
        gemini.propose(_proposal_request())


def _runtime(tmp_path: Path) -> tuple[ServiceBrokerRuntime, list[dict[str, Any]], str]:
    state_dir = (tmp_path / "state").resolve()
    backend = InMemoryCredentialBackend()
    credentials = CredentialStore(
        state_dir=(state_dir / "trusted-surfaces" / "credentials").resolve(),
        backend=backend,
    )
    secret = "provider-secret-candidate-canary"
    metadata = credentials.set_secret("model.discovery", secret)
    profile = ProviderProfile(
        profile_ref="model.discovery",
        capability="model",
        provider="openai",
        base_url="https://api.openai.com/v1",
        model="gpt-service-owned",
        maximum_response_bytes=900 * 1024,
    )
    authorization_dir = state_dir / "trusted-surfaces" / "authorizations"
    authorization_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema": AUTHORIZATION_SCHEMA,
        "schemaVersion": 1,
        "operationIntentRef": "intent-candidate-discovery-1",
        "expiresAtUnixMs": int(time.time() * 1000) + 60_000,
        "budget": {
            "maxRemoteCalls": 4,
            "maxRequestBytes": 2 * 1024 * 1024,
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
                "credentialRevision": int(metadata["credentialRevision"]),
                "reservedCostMinorUnits": 5,
            }
        ],
        "methodBindings": {
            "study.discover_candidates": {"model": profile.profile_ref},
        },
        "sourceAcquisition": {
            "youtubeSubtitles": {"enabled": False, "timeoutSeconds": 30}
        },
    }
    manifest_path = authorization_dir / "candidate-discovery.json"
    manifest_path.write_bytes(canonical_bytes(manifest))
    observed: list[dict[str, Any]] = []

    def transport(request: Any) -> ProviderTransportResponse:
        body = json.loads(request.body)
        observed.append(
            {
                "body": body,
                "headers": dict(request.headers),
                "url": request.url,
            }
        )
        user_text = body["messages"][-1]["content"]
        value = (
            {
                "schema": "study.candidate-discovery.proposals",
                "schemaVersion": 1,
                "proposals": [],
            }
            if "proposal-request" in user_text
            else {
                "schema": "study.candidate-discovery.reviews",
                "schemaVersion": 1,
                "reviews": [],
            }
        )
        response = _outer("model.openai_chat", value)
        encoded = json.dumps(response, separators=(",", ":")).encode("utf-8")
        return ProviderTransportResponse(
            200,
            request.url,
            {"content-type": "application/json"},
            encoded,
        )

    runtime = ServiceBrokerRuntime.from_manifest(
        manifest_path.resolve(),
        state_dir=state_dir,
        credential_backend=backend,
        transport_overrides={"model.discovery": transport},
    )
    return runtime, observed, secret


def test_provider_uses_trusted_service_configuration_and_two_ledger_reservations(
    tmp_path: Path,
) -> None:
    runtime, observed, secret = _runtime(tmp_path)
    provider = BrokerCandidateDiscoveryModelProvider(runtime)
    model = provider.bind("task-candidate-adapter")
    assert model.identity == provider.identity
    assert model.propose(_proposal_request())["proposals"] == []
    assert model.review(_review_request())["reviews"] == []

    assert len(observed) == 2
    for call in observed:
        assert call["body"]["model"] == "gpt-service-owned"
        assert call["headers"]["Authorization"] == "Bearer " + secret
        serialized_body = json.dumps(call["body"], ensure_ascii=False)
        assert secret not in serialized_body
        assert "https://api.openai.com" not in serialized_body
        assert "model.discovery" not in serialized_body

    records = runtime.ledger.list_records()
    assert [record["workUnitId"] for record in records] == [
        "candidate-proposer-v1",
        "candidate-reviewer-v1",
    ]
    assert {record["taskId"] for record in records} == {"task-candidate-adapter"}
    assert {record["operationIntentRef"] for record in records} == {
        "intent-candidate-discovery-1"
    }
    persisted = runtime.ledger.path.read_text(encoding="utf-8")
    assert secret not in persisted


def test_provider_derives_non_secret_authorization_from_exact_runtime_scope(
    tmp_path: Path,
) -> None:
    runtime, _observed, secret = _runtime(tmp_path)
    provider = BrokerCandidateDiscoveryModelProvider(runtime)
    audience = ArtifactAudienceBinding(
        owner_digest="b" * 64,
        host_id="codex-desktop",
        plugin_id="speakright.study",
        session_id="session-authorization",
    )
    first = provider.authorization_for(
        audience=audience,
        service_instance_id="service-instance-1",
        project_id="project-1",
        project_revision=3,
        inspection_handle="study_" + "A" * 43,
        candidate_budget={"target": 12, "maximum": 24},
    )
    repeated = provider.authorization_for(
        audience=audience,
        service_instance_id="service-instance-1",
        project_id="project-1",
        project_revision=3,
        inspection_handle="study_" + "A" * 43,
        candidate_budget={"target": 12, "maximum": 24},
    )
    changed_scope = provider.authorization_for(
        audience=audience,
        service_instance_id="service-instance-1",
        project_id="project-1",
        project_revision=4,
        inspection_handle="study_" + "B" * 43,
        candidate_budget={"target": 12, "maximum": 24},
    )

    assert first == repeated
    assert (
        first.authorization_record_digest
        == runtime.configuration.manifest_digest.removeprefix("sha256:")
    )
    assert first.exact_scope_digest != changed_scope.exact_scope_digest
    assert first.constraints_digest == changed_scope.constraints_digest
    serialized = json.dumps(first.public_identity(), sort_keys=True)
    assert secret not in serialized
    assert "api.openai.com" not in serialized
    assert "gpt-service-owned" not in serialized


class _RecordingStudyRuntime:
    service_instance_id = "service-instance-card-service"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def start_candidate_discovery(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {
            "schemaVersion": 1,
            "projectId": kwargs["project_id"],
            "projectRevision": kwargs["expected_project_revision"] + 1,
            "artifactStage": "candidates_ready",
            "taskId": "task-discovery-card-service",
        }


class _RecoveryStudyRuntime:
    service_instance_id = "service-instance-card-service"

    @staticmethod
    def resolve_candidate_discovery_recovery_target(**_kwargs: Any) -> tuple[str, None]:
        return "task-recovery-source", None

    @staticmethod
    def candidate_discovery_recovery_request(**_kwargs: Any) -> dict[str, Any]:
        return {
            "projectId": "project-1",
            "expectedProjectRevision": 3,
            "inspectionHandle": "study_" + "R" * 43,
            "candidateBudget": {"target": 8, "maximum": 16},
        }


def _card_service_shell(
    study: _RecordingStudyRuntime,
    broker_runtime: ServiceBrokerRuntime | None,
) -> CardService:
    service = object.__new__(CardService)
    service._study_runtime = study
    service._study_runtime_lock = threading.RLock()
    service._broker_runtime_lock = threading.RLock()
    service._active_broker_runtime = broker_runtime
    return service


def test_card_service_derives_authorization_and_provider_internally(
    tmp_path: Path,
) -> None:
    broker_runtime, _observed, _secret = _runtime(tmp_path)
    study = _RecordingStudyRuntime()
    service = _card_service_shell(study, broker_runtime)
    audience = ArtifactAudienceBinding(
        owner_digest="c" * 64,
        host_id="codex-desktop",
        plugin_id="speakright.study",
        session_id="session-card-service",
    )

    result = service.discover_study_candidates(
        audience=audience,
        project_id="project-1",
        expected_project_revision=3,
        idempotency_key="discovery-1",
        inspection_handle="study_" + "C" * 43,
        candidate_budget={"target": 8, "maximum": 16},
    )

    assert result["artifactStage"] == "candidates_ready"
    assert len(study.calls) == 1
    call = study.calls[0]
    assert isinstance(call["model_provider"], BrokerCandidateDiscoveryModelProvider)
    assert call["authorization"].authorization_record_digest == (
        broker_runtime.configuration.manifest_digest.removeprefix("sha256:")
    )
    assert set(call) == {
        "audience",
        "project_id",
        "expected_project_revision",
        "idempotency_key",
        "inspection_handle",
        "candidate_budget",
        "authorization",
        "model_provider",
    }


def test_card_service_requires_trusted_broker_before_candidate_discovery() -> None:
    study = _RecordingStudyRuntime()
    service = _card_service_shell(study, None)
    with pytest.raises(CardServiceError) as caught:
        service.discover_study_candidates(
            audience=ArtifactAudienceBinding(
                owner_digest="d" * 64,
                host_id="codex-desktop",
                plugin_id="speakright.study",
                session_id="session-no-broker",
            ),
            project_id="project-1",
            expected_project_revision=3,
            idempotency_key="discovery-1",
            inspection_handle="study_" + "D" * 43,
            candidate_budget={"target": 8, "maximum": 16},
        )
    assert caught.value.code == "AUTHORIZATION_REQUIRED"
    assert caught.value.stage == "authorization"
    assert study.calls == []


def test_card_service_rechecks_hermes_before_recovering_discovery() -> None:
    service = object.__new__(CardService)
    service._study_runtime = _RecoveryStudyRuntime()
    service._study_runtime_lock = threading.RLock()
    service._broker_runtime_lock = threading.RLock()
    hermes_binding = SimpleNamespace(profile=SimpleNamespace(provider="hermes"))
    service._active_broker_runtime = SimpleNamespace(
        configuration=SimpleNamespace(
            method_bindings={"study.discover_candidates": {"model": "model.hermes"}},
            profiles={"model.hermes": hermes_binding},
        )
    )
    calls: list[str] = []

    def fail_preflight() -> None:
        calls.append("preflight")
        raise CardServiceError(
            "HERMES_PROXY_START_FAILED",
            "Hermes local proxy could not be started.",
            retryable=True,
            stage="model",
        )

    service.ensure_candidate_discovery_provider = fail_preflight

    with pytest.raises(CardServiceError) as caught:
        service.resume_public_study_task(
            audience=ArtifactAudienceBinding(
                owner_digest="e" * 64,
                host_id="codex-desktop",
                plugin_id="speakright.study",
                session_id="session-recovery-preflight",
            ),
            task_id="task-recovery-source",
            idempotency_key="resume-hermes-preflight",
        )

    assert caught.value.code == "HERMES_PROXY_START_FAILED"
    assert calls == ["preflight"]


def test_provider_fails_closed_when_method_is_not_authorized(tmp_path: Path) -> None:
    runtime, _observed, _secret = _runtime(tmp_path)
    configuration = runtime.configuration
    unauthorized = BrokerAuthorizationConfiguration(
        manifest_digest=configuration.manifest_digest,
        operation_intent_ref=configuration.operation_intent_ref,
        expires_at_unix_ms=configuration.expires_at_unix_ms,
        budget=configuration.budget,
        profiles=configuration.profiles,
        method_bindings={},
        youtube_subtitles_enabled=False,
        source_timeout_seconds=30,
    )
    runtime_without_method = ServiceBrokerRuntime(
        configuration=unauthorized,
        credential_store=runtime.credential_store,
        ledger=runtime.ledger,
    )
    with pytest.raises(CandidateDiscoveryBrokerError) as caught:
        BrokerCandidateDiscoveryModelProvider(runtime_without_method)
    assert caught.value.code == "DISCOVERY_BROKER_UNAVAILABLE"
