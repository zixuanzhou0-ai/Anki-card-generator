from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from card_service.mcp_system_tools import (
    AUTHORIZE_DISCOVERY_TOOL,
    LIST_PROFILES_TOOL,
    McpSystemToolInputError,
    OPEN_LOCAL_SETTINGS_TOOL,
    REQUEST_OPERATION_CONFIRMATION_TOOL,
    REVOKE_GRANT_TOOL,
    VALIDATE_PROFILE_TOOL,
    call_system_tool,
    system_tool_definitions,
)
from card_service.credentials import InMemoryCredentialBackend
from card_service.service import CardService
from card_service.trusted_mcp_audience import create_development_mcp_audience


ROOT = Path(__file__).resolve().parents[1]
FAKE_WORKER = ROOT / "tests" / "fixtures" / "card_service" / "fake_worker.py"
FAKE_SURFACE = ROOT / "tests" / "fixtures" / "card_service" / "fake_surface.py"


class StubService:
    def __init__(self, terminal: dict[str, Any]) -> None:
        self.terminal = terminal
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.polls = 0
        self.provider_checks = 0

    def ensure_candidate_discovery_provider(self) -> dict[str, Any]:
        self.provider_checks += 1
        return {"state": "ready"}

    def dispatch(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((method, params))
        if method == "system.open_broker_authorization":
            return {"sessionRef": "trusted-session", "state": "open"}
        if method == "system.get_trusted_surface":
            self.polls += 1
            if self.polls == 1:
                return {"state": "open"}
            return dict(self.terminal)
        raise AssertionError(f"unexpected method: {method}")


class StubHermesProxyManager:
    def probe(self) -> dict[str, Any]:
        return {"state": "ready"}

    def ensure_ready(self) -> dict[str, Any]:
        return {"state": "ready"}

    def close(self) -> None:
        return None


def test_system_authorization_tool_is_a_closed_fixed_preset() -> None:
    definition = system_tool_definitions()[0]

    assert definition["name"] == AUTHORIZE_DISCOVERY_TOOL
    assert definition["inputSchema"] == {
        "type": "object",
        "properties": {
            "preset": {"type": "string", "const": "hermes_grok_4_5"}
        },
        "required": ["preset"],
        "additionalProperties": False,
    }
    assert definition["annotations"] == {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    }
    assert "baseUrl" not in json.dumps(definition["inputSchema"])
    assert "credential" not in json.dumps(definition["inputSchema"]).casefold()


def test_system_authorization_tool_activates_only_fixed_hermes_scope() -> None:
    service = StubService(
        {
            "state": "approved",
            "authorization": {
                "schemaVersion": 1,
                "authorizationDigest": "a" * 64,
                "expiresAtUnixMs": 123,
                "profileCount": 1,
                "methodCount": 1,
                "youtubeSubtitleAcquisition": False,
            },
        }
    )

    result = call_system_tool(
        service,  # type: ignore[arg-type]
        tool_name=AUTHORIZE_DISCOVERY_TOOL,
        arguments={"preset": "hermes_grok_4_5"},
        user_action_timeout_seconds=1,
    )

    public = result["structuredContent"]
    assert public["state"] == "approved"
    assert public["capabilityAvailable"] is True
    draft = service.calls[0][1]
    assert draft["methodBindings"] == {
        "study.discover_candidates": {"model": "model.hermes-grok-4.5"}
    }
    assert draft["profiles"] == [
        {
            "profileRef": "model.hermes-grok-4.5",
            "capability": "model",
            "provider": "hermes",
            "baseUrl": "http://127.0.0.1:8645/v1",
            "model": "grok-4.5",
            "voice": "",
            "timeoutSeconds": 120,
            "maximumResponseBytes": 900 * 1024,
            "reservedCostMinorUnits": 0,
        }
    ]
    assert draft["sourceAcquisition"]["youtubeSubtitles"]["enabled"] is False
    assert "secret" not in json.dumps(draft).casefold()


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"preset": "custom"},
        {"preset": "hermes_grok_4_5", "baseUrl": "http://attacker.invalid"},
        {"preset": "hermes_grok_4_5", "apiKey": "secret"},
    ],
)
def test_system_authorization_tool_rejects_agent_controlled_scope(
    arguments: dict[str, Any],
) -> None:
    with pytest.raises(McpSystemToolInputError):
        call_system_tool(
            StubService({"state": "approved"}),  # type: ignore[arg-type]
            tool_name=AUTHORIZE_DISCOVERY_TOOL,
            arguments=arguments,
            user_action_timeout_seconds=0,
        )


def test_system_authorization_tool_returns_user_decline_without_activation() -> None:
    service = StubService({"state": "declined", "userGestureRecorded": True})

    result = call_system_tool(
        service,  # type: ignore[arg-type]
        tool_name=AUTHORIZE_DISCOVERY_TOOL,
        arguments={"preset": "hermes_grok_4_5"},
        user_action_timeout_seconds=1,
    )

    assert result["structuredContent"] == {
        "schemaVersion": 1,
        "preset": "hermes_grok_4_5",
        "state": "declined",
        "capabilityAvailable": False,
    }


def test_system_authorization_tool_times_out_without_exposing_session_reference() -> None:
    service = StubService({"state": "approved"})

    result = call_system_tool(
        service,  # type: ignore[arg-type]
        tool_name=AUTHORIZE_DISCOVERY_TOOL,
        arguments={"preset": "hermes_grok_4_5"},
        user_action_timeout_seconds=0,
    )

    serialized = json.dumps(result)
    assert result["structuredContent"]["state"] == "timed_out"
    assert "trusted-session" not in serialized

def test_fixed_authorization_hot_loads_candidate_discovery_broker(tmp_path: Path) -> None:
    service = CardService(
        state_dir=(tmp_path / "state").resolve(),
        worker_path=FAKE_WORKER.resolve(),
        python_path=Path(sys.executable).resolve(),
        method_policies={},
        credential_backend=InMemoryCredentialBackend(),
        trusted_surface_path=FAKE_SURFACE.resolve(),
        use_restricted_launcher=False,
        hermes_proxy_manager=StubHermesProxyManager(),  # type: ignore[arg-type]
    )

    result = call_system_tool(
        service,
        tool_name=AUTHORIZE_DISCOVERY_TOOL,
        arguments={"preset": "hermes_grok_4_5"},
        user_action_timeout_seconds=5,
    )

    assert result["structuredContent"]["state"] == "approved"
    capabilities = service.capabilities()["studyRuntime"]
    assert capabilities["publicCandidateDiscovery"] is True
    assert capabilities["candidateDiscoveryAuthorizationReady"] is True


def _remote_model_profile() -> dict[str, Any]:
    return {
        "profileRef": "model.primary",
        "capability": "model",
        "provider": "openai",
        "baseUrl": "https://api.openai.com/v1",
        "model": "gpt-5.6",
        "voice": "",
        "timeoutSeconds": 120,
        "maximumResponseBytes": 512 * 1024,
        "authMode": "bearer",
    }


def _profile_service(tmp_path: Path) -> CardService:
    service = CardService(
        state_dir=(tmp_path / "state").resolve(),
        worker_path=FAKE_WORKER.resolve(),
        python_path=Path(sys.executable).resolve(),
        method_policies={},
        credential_backend=InMemoryCredentialBackend(),
        trusted_surface_path=FAKE_SURFACE.resolve(),
        use_restricted_launcher=False,
        hermes_proxy_manager=StubHermesProxyManager(),  # type: ignore[arg-type]
    )
    service.save_service_profile(
        _remote_model_profile(),
        expected_revision=0,
        operation_id="trusted-settings-seed",
    )
    return service


def test_profile_tools_have_closed_non_secret_contracts() -> None:
    definitions = {item["name"]: item for item in system_tool_definitions()}
    assert set(definitions) == {
        AUTHORIZE_DISCOVERY_TOOL,
        LIST_PROFILES_TOOL,
        OPEN_LOCAL_SETTINGS_TOOL,
        REVOKE_GRANT_TOOL,
        VALIDATE_PROFILE_TOOL,
        REQUEST_OPERATION_CONFIRMATION_TOOL,
    }
    assert definitions[LIST_PROFILES_TOOL]["inputSchema"] == {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }
    assert definitions[LIST_PROFILES_TOOL]["annotations"] == {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
    encoded = json.dumps(definitions[OPEN_LOCAL_SETTINGS_TOOL], sort_keys=True).casefold()
    for forbidden in ("apikey", "oauth", "cookie", "authorization", "baseurl"):
        assert forbidden not in encoded
    validate = definitions[VALIDATE_PROFILE_TOOL]
    assert validate["annotations"] == {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
    confirmation = definitions[REQUEST_OPERATION_CONFIRMATION_TOOL]
    assert confirmation["inputSchema"]["additionalProperties"] is False
    assert confirmation["annotations"] == {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    }


def test_list_profiles_returns_exact_binding_without_secrets(tmp_path: Path) -> None:
    service = _profile_service(tmp_path)
    result = call_system_tool(
        service,
        tool_name=LIST_PROFILES_TOOL,
        arguments={},
        user_action_timeout_seconds=0,
    )
    profiles = result["structuredContent"]["profiles"]
    assert profiles == [
        {
            "schemaVersion": 1,
            "profileRef": "model.primary",
            "capability": "model",
            "profileRevision": 1,
            "configurationFingerprint": profiles[0]["configurationFingerprint"],
            "provider": "openai",
            "endpointOrigin": "https://api.openai.com",
            "credentialRevision": 0,
            "credentialState": "missing",
            "secretRequired": True,
            "secretExists": False,
            "state": "action_required",
            "model": "gpt-5.6",
            "reasonCode": "CREDENTIAL_REQUIRED",
        }
    ]
    encoded = json.dumps(result, sort_keys=True).casefold()
    for forbidden in ("secretref", "apikey", "oauth", "cookie", "authorization"):
        assert forbidden not in encoded


def test_local_settings_opens_only_existing_secret_profile_and_polls_safely(
    tmp_path: Path,
) -> None:
    service = _profile_service(tmp_path)
    opened = call_system_tool(
        service,
        tool_name=OPEN_LOCAL_SETTINGS_TOOL,
        arguments={"profileRef": "model.primary", "capability": "model"},
        user_action_timeout_seconds=0,
    )["structuredContent"]
    assert opened["state"] == "open"
    session_ref = opened["configurationSessionRef"]
    deadline = time.monotonic() + 5
    while True:
        polled = call_system_tool(
            service,
            tool_name=OPEN_LOCAL_SETTINGS_TOOL,
            arguments={"configurationSessionRef": session_ref},
            user_action_timeout_seconds=0,
        )["structuredContent"]
        if polled["state"] not in {"open", "created"}:
            break
        if time.monotonic() >= deadline:
            raise AssertionError("trusted settings fixture did not finish")
        time.sleep(0.02)
    assert polled == {
        "schemaVersion": 1,
        "configurationSessionRef": session_ref,
        "state": "completed",
        "credentialRevision": 0,
        "credentialState": "missing",
        "secretExists": False,
    }
    encoded = json.dumps(polled, sort_keys=True).casefold()
    assert "secretref" not in encoded


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"profileRef": "model.primary"},
        {"profileRef": "model.primary", "capability": "model", "apiKey": "x"},
        {"configurationSessionRef": "x", "profileRef": "model.primary"},
    ],
)
def test_local_settings_rejects_open_ended_arguments(arguments: dict[str, Any]) -> None:
    with pytest.raises(McpSystemToolInputError):
        call_system_tool(
            StubService({"state": "completed"}),  # type: ignore[arg-type]
            tool_name=OPEN_LOCAL_SETTINGS_TOOL,
            arguments=arguments,
            user_action_timeout_seconds=0,
        )


def test_revoke_grant_has_closed_destructive_contract_without_private_ids() -> None:
    definition = {
        item["name"]: item for item in system_tool_definitions()
    }[REVOKE_GRANT_TOOL]
    assert definition["annotations"] == {
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    }
    encoded = json.dumps(
        {
            "inputSchema": definition["inputSchema"],
            "outputSchema": definition["outputSchema"],
        },
        sort_keys=True,
    ).casefold()
    for forbidden in (
        "authorizationid",
        "resourceRef".casefold(),
        "importintentid",
        "ledger",
        "attestation",
        "path\"",
        "url\"",
        "bearer",
    ):
        assert forbidden not in encoded


def test_revoke_grant_uses_trusted_audience_and_returns_only_bounded_summary() -> None:
    class RevocationService:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def request_authorization_revocation(self, **values: Any) -> dict[str, Any]:
            self.calls.append(values)
            return {
                "schemaVersion": 1,
                "state": "completed",
                "availableCount": 1,
                "selectedCount": 1,
                "revokedCount": 1,
                "alreadyConsumedCount": 0,
                "alreadyRevokedCount": 0,
                "notFoundCount": 0,
                "failedCount": 0,
                "results": [
                    {"kind": "local_resource", "disposition": "revoked"}
                ],
            }

    service = RevocationService()
    audience = create_development_mcp_audience()
    result = call_system_tool(
        service,  # type: ignore[arg-type]
        tool_name=REVOKE_GRANT_TOOL,
        arguments={},
        audience_session=audience,
        user_action_timeout_seconds=0,
    )
    assert service.calls == [
        {"audience": audience.audience, "authorization_session_ref": None}
    ]
    assert result["structuredContent"]["revokedCount"] == 1
    serialized = json.dumps(result, sort_keys=True).casefold()
    for forbidden in ("resource_", "anki_intent_", "attestation", "ledger"):
        assert forbidden not in serialized


@pytest.mark.parametrize(
    "arguments",
    [
        {"resourceRef": "resource_private"},
        {"authorizationSessionRef": "not-a-uuid"},
        {"authorizationSessionRef": "00000000-0000-4000-8000-000000000000", "all": True},
    ],
)
def test_revoke_grant_rejects_private_or_open_ended_arguments(
    arguments: dict[str, Any],
) -> None:
    with pytest.raises(McpSystemToolInputError):
        call_system_tool(
            StubService({"state": "completed"}),  # type: ignore[arg-type]
            tool_name=REVOKE_GRANT_TOOL,
            arguments=arguments,
            audience_session=create_development_mcp_audience(),
            user_action_timeout_seconds=0,
        )
