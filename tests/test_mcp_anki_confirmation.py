from __future__ import annotations

import json

import pytest

from card_service.mcp_anki_tools import (
    REQUEST_IMPORT_CONFIRMATION_TOOL_NAME,
    McpAnkiToolInputError,
    anki_tool_definitions,
    call_anki_tool,
)
from card_service.trusted_mcp_audience import create_development_mcp_audience


INTENT_ID = "anki_intent_" + "a" * 48


class _ConfirmationService:
    def __init__(self, state: str = "approved") -> None:
        self.state = state
        self.calls: list[dict[str, object]] = []

    def request_study_anki_import_confirmation(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "schemaVersion": 1,
            "importIntentId": INTENT_ID,
            "approvalState": self.state,
            "expiresAt": "2026-07-18T12:30:00.000Z",
        }


def test_confirmation_tool_has_only_an_intent_locator_and_no_bearer() -> None:
    definitions = {item["name"]: item for item in anki_tool_definitions()}
    definition = definitions[REQUEST_IMPORT_CONFIRMATION_TOOL_NAME]
    assert set(definition["inputSchema"]["properties"]) == {"importIntentId"}
    assert definition["inputSchema"]["additionalProperties"] is False
    assert definition["annotations"] == {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    }
    encoded = json.dumps(definition, sort_keys=True).casefold()
    assert "approved" in encoded
    assert "approvaltoken" not in encoded
    assert "attestationref" not in encoded


def test_confirmation_result_exposes_state_but_no_execution_authority() -> None:
    service = _ConfirmationService()
    result = call_anki_tool(
        service,
        tool_name=REQUEST_IMPORT_CONFIRMATION_TOOL_NAME,
        arguments={"importIntentId": INTENT_ID},
        audience_session=create_development_mcp_audience(),
        user_action_timeout_seconds=0,
    )
    assert result["structuredContent"]["approvalState"] == "approved"
    assert service.calls[0]["import_intent_id"] == INTENT_ID
    encoded = json.dumps(result, sort_keys=True).casefold()
    for forbidden in ("token", "bearer", "gesture", "attestation", "sessionref"):
        assert forbidden not in encoded


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"importIntentId": "bad"},
        {"importIntentId": INTENT_ID, "approved": True},
        {"importIntentId": INTENT_ID, "approvalToken": "copied"},
    ],
)
def test_confirmation_rejects_chat_approval_and_open_ended_fields(arguments) -> None:
    with pytest.raises(McpAnkiToolInputError):
        call_anki_tool(
            _ConfirmationService(),
            tool_name=REQUEST_IMPORT_CONFIRMATION_TOOL_NAME,
            arguments=arguments,
            audience_session=create_development_mcp_audience(),
            user_action_timeout_seconds=0,
        )
