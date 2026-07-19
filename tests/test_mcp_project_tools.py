from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from card_service.credentials import InMemoryCredentialBackend
from card_service.mcp_project_tools import (
    CREATE_PROJECT_TOOL_NAME,
    McpProjectToolInputError,
    call_project_tool,
    project_tool_definitions,
)
from card_service.mcp_stdio import serve
from card_service.service import CardService, CardServiceError
from card_service.trusted_mcp_audience import create_development_mcp_audience


def service(tmp_path: Path) -> CardService:
    return CardService(
        state_dir=(tmp_path / "service").resolve(),
        credential_backend=InMemoryCredentialBackend(),
        resource_gesture_verifier=lambda *_args: True,
        use_restricted_launcher=False,
    )


def arguments(**changes):
    value = {
        "context": {"idempotencyKey": "create-project-1", "locale": "zh-CN"},
        "title": "English from videos",
        "learningContract": {
            "purpose": "Learn reusable English",
            "targetBehavior": "Recall and use each item in a new situation",
            "routes": ["listening_recognition", "production"],
            "maxNewCards": 20,
            "promptLanguage": "zh-CN",
            "answerLanguage": "en",
        },
    }
    value.update(changes)
    return value


def test_project_tool_schema_is_closed_local_and_idempotent() -> None:
    definitions = project_tool_definitions()
    assert [item["name"] for item in definitions] == [CREATE_PROJECT_TOOL_NAME]
    definition = definitions[0]
    assert definition["inputSchema"]["additionalProperties"] is False
    assert (
        definition["inputSchema"]["properties"]["context"]["additionalProperties"]
        is False
    )
    assert (
        definition["inputSchema"]["properties"]["learningContract"][
            "additionalProperties"
        ]
        is False
    )
    assert definition["annotations"] == {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
    serialized = json.dumps(definition, sort_keys=True).casefold()
    for forbidden in ('path"', 'url"', "apikey", "authorization", "credential"):
        assert forbidden not in serialized


def test_create_project_returns_minimal_project_control_plane(tmp_path: Path) -> None:
    card_service = service(tmp_path)
    audience_session = create_development_mcp_audience()
    first = call_project_tool(
        card_service,
        tool_name=CREATE_PROJECT_TOOL_NAME,
        arguments=arguments(),
        audience_session=audience_session,
    )
    second = call_project_tool(
        card_service,
        tool_name=CREATE_PROJECT_TOOL_NAME,
        arguments=arguments(),
        audience_session=audience_session,
    )

    assert second == first
    structured = first["structuredContent"]
    assert structured["projectRevision"] == 1
    assert structured["contractRevision"] == 1
    assert structured["learningContractRef"].startswith("contract_")
    assert structured["workflow"]["artifactStage"] == "empty"
    serialized = json.dumps(first, ensure_ascii=False, sort_keys=True)
    assert "Learn reusable English" not in serialized
    assert "Recall and use each item" not in serialized
    assert str(tmp_path) not in serialized
    assert "secret" not in serialized.casefold()


def test_stdio_exposes_and_calls_project_tool_only_with_trusted_audience(
    tmp_path: Path,
) -> None:
    card_service = service(tmp_path)
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": CREATE_PROJECT_TOOL_NAME, "arguments": arguments()},
    }

    untrusted_output = io.StringIO()
    serve(card_service, io.StringIO(json.dumps(request) + "\n"), untrusted_output)
    untrusted = json.loads(untrusted_output.getvalue())
    assert untrusted["error"] == {"code": -32602, "message": "Unknown tool"}

    trusted_output = io.StringIO()
    serve(
        card_service,
        io.StringIO(json.dumps(request) + "\n"),
        trusted_output,
        audience_session=create_development_mcp_audience(),
    )
    trusted = json.loads(trusted_output.getvalue())
    assert trusted["result"]["structuredContent"]["projectRevision"] == 1
    assert (
        trusted["result"]["structuredContent"]["workflow"]["artifactStage"] == "empty"
    )


def test_same_idempotency_key_with_different_contract_fails(tmp_path: Path) -> None:
    card_service = service(tmp_path)
    audience_session = create_development_mcp_audience()
    call_project_tool(
        card_service,
        tool_name=CREATE_PROJECT_TOOL_NAME,
        arguments=arguments(),
        audience_session=audience_session,
    )
    changed = arguments()
    changed["learningContract"] = {
        **changed["learningContract"],
        "purpose": "A different purpose",
    }
    with pytest.raises(CardServiceError) as captured:
        call_project_tool(
            card_service,
            tool_name=CREATE_PROJECT_TOOL_NAME,
            arguments=changed,
            audience_session=audience_session,
        )
    assert captured.value.code == "PROJECT_IDEMPOTENCY_CONFLICT"


@pytest.mark.parametrize(
    "invalid",
    [
        {},
        {"context": {"idempotencyKey": "../escape"}, "learningContract": {}},
        {**arguments(), "path": "C:/private"},
        {
            **arguments(),
            "context": {"idempotencyKey": "create-2", "ownerDigest": "forged"},
        },
    ],
)
def test_project_tool_rejects_missing_or_scope_injecting_fields(invalid: dict) -> None:
    with pytest.raises(McpProjectToolInputError):
        call_project_tool(
            object(),  # type: ignore[arg-type]
            tool_name=CREATE_PROJECT_TOOL_NAME,
            arguments=invalid,
            audience_session=create_development_mcp_audience(),
        )
