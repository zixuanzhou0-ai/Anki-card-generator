from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from card_service.mcp_system_tools import (
    AUTHORIZE_DISCOVERY_TOOL,
    McpSystemToolInputError,
    call_system_tool,
    system_tool_definitions,
)
from card_service.credentials import InMemoryCredentialBackend
from card_service.service import CardService


ROOT = Path(__file__).resolve().parents[1]
FAKE_WORKER = ROOT / "tests" / "fixtures" / "card_service" / "fake_worker.py"
FAKE_SURFACE = ROOT / "tests" / "fixtures" / "card_service" / "fake_surface.py"


class StubService:
    def __init__(self, terminal: dict[str, Any]) -> None:
        self.terminal = terminal
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.polls = 0

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
            "baseUrl": "http://127.0.0.1:8317/v1",
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
