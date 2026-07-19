from __future__ import annotations

import json
from typing import Any

import pytest

from card_service.mcp_resource_tools import (
    McpResourceToolInputError,
    OUTPUT_GRANT_TOOL_NAME,
    SOURCE_GRANT_TOOL_NAME,
    call_resource_tool,
    resource_tool_definitions,
)
from card_service.service import CardService
from card_service.trusted_mcp_audience import create_development_mcp_audience


class ResourceService:
    def __init__(self, kind: str, *, state: str = "selected") -> None:
        self.kind = kind
        self.state = state
        self.calls: list[dict[str, Any]] = []

    @staticmethod
    def public_local_resource_constraints(kind: str) -> dict[str, Any]:
        return CardService.public_local_resource_constraints(kind)

    def request_local_resource_picker(self, **values: Any) -> dict[str, Any]:
        self.calls.append(values)
        if self.state != "selected":
            return {"schemaVersion": 1, "sessionRef": "private", "state": self.state}
        return {
            "schemaVersion": 1,
            "sessionRef": "private",
            "state": "selected",
            "resourceSelection": {
                "kind": self.kind,
                "displayName": "Selected file",
                "pathDisclosure": False,
            },
            "resourceGrant": {
                "kind": self.kind,
                "resourceRef": "resource_" + "a" * 43,
                "displayName": "lesson.mp4" if self.kind == "file" else "Selected output folder",
                "constraints": self.public_local_resource_constraints(self.kind),
                "resourceRevisionDigest": "b" * 64,
                "expiresAt": "2026-07-19T00:00:00Z",
            },
        }


def test_resource_tool_schemas_have_no_path_url_audience_or_replace_inputs() -> None:
    definitions = resource_tool_definitions()
    assert [item["name"] for item in definitions] == [
        SOURCE_GRANT_TOOL_NAME,
        OUTPUT_GRANT_TOOL_NAME,
    ]
    serialized = json.dumps(definitions, sort_keys=True).lower()
    for forbidden in ("path\"", "url\"", "audience", "raw", "replace\""):
        assert forbidden not in serialized
    assert all(item["inputSchema"]["additionalProperties"] is False for item in definitions)


def test_source_tool_returns_only_opaque_input_ref() -> None:
    service = ResourceService("file")
    audience = create_development_mcp_audience()
    result = call_resource_tool(
        service,  # type: ignore[arg-type]
        tool_name=SOURCE_GRANT_TOOL_NAME,
        arguments={"grantRequestId": "source-1", "selectionKind": "file"},
        audience_session=audience,
        user_action_timeout_seconds=0,
    )

    structured = result["structuredContent"]
    assert structured["state"] == "selected"
    assert structured["inputRef"]["fileResourceRef"] == "resource_" + "a" * 43
    serialized = json.dumps(result, sort_keys=True)
    assert "sessionRef" not in serialized
    assert "resourceGrant" not in serialized
    assert "attestation" not in serialized.lower()
    assert service.calls[0]["audience"] == audience.audience
    assert "audience" not in {"grantRequestId", "selectionKind"}


def test_output_tool_excludes_replace_and_returns_output_ref() -> None:
    service = ResourceService("output_directory")
    result = call_resource_tool(
        service,  # type: ignore[arg-type]
        tool_name=OUTPUT_GRANT_TOOL_NAME,
        arguments={"grantRequestId": "output-1"},
        audience_session=create_development_mcp_audience(),
        user_action_timeout_seconds=0,
    )
    output_ref = result["structuredContent"]["outputRef"]
    assert output_ref["outputResourceRef"] == "resource_" + "a" * 43
    assert output_ref["constraints"]["actions"] == ["create", "versioned"]
    assert "replace" not in output_ref["constraints"]["actions"]


def test_waiting_and_cancelled_states_disclose_no_private_session() -> None:
    for state, expected in (("open", "awaiting_user"), ("cancelled", "cancelled")):
        result = call_resource_tool(
            ResourceService("file", state=state),  # type: ignore[arg-type]
            tool_name=SOURCE_GRANT_TOOL_NAME,
            arguments={"grantRequestId": f"state-{state}", "selectionKind": "file"},
            audience_session=create_development_mcp_audience(),
            user_action_timeout_seconds=0,
        )
        assert result["structuredContent"] == {"schemaVersion": 1, "state": expected}
        assert "private" not in json.dumps(result)


@pytest.mark.parametrize(
    "tool_name,arguments",
    [
        (SOURCE_GRANT_TOOL_NAME, {"grantRequestId": "x", "selectionKind": "file", "path": "C:/x"}),
        (SOURCE_GRANT_TOOL_NAME, {"grantRequestId": "../x", "selectionKind": "file"}),
        (SOURCE_GRANT_TOOL_NAME, {"grantRequestId": "x", "selectionKind": "network"}),
        (OUTPUT_GRANT_TOOL_NAME, {"grantRequestId": "x", "replace": True}),
    ],
)
def test_resource_tool_rejects_scope_injection(tool_name: str, arguments: dict[str, Any]) -> None:
    with pytest.raises(McpResourceToolInputError):
        call_resource_tool(
            ResourceService("file"),  # type: ignore[arg-type]
            tool_name=tool_name,
            arguments=arguments,
            audience_session=create_development_mcp_audience(),
            user_action_timeout_seconds=0,
        )


@pytest.mark.parametrize("tamper", ["constraints", "resource_ref", "revision"])
def test_private_or_malformed_grant_payload_fails_closed(tamper: str) -> None:
    class TamperedResourceService(ResourceService):
        def request_local_resource_picker(self, **values: Any) -> dict[str, Any]:
            result = super().request_local_resource_picker(**values)
            grant = result["resourceGrant"]
            if tamper == "constraints":
                grant["constraints"] = {
                    **grant["constraints"],
                    "privatePath": "C:/private/source.mp4",
                }
            elif tamper == "resource_ref":
                grant["resourceRef"] = "not-an-opaque-resource-ref"
            else:
                grant["resourceRevisionDigest"] = "not-a-sha256"
            return result

    result = call_resource_tool(
        TamperedResourceService("file"),  # type: ignore[arg-type]
        tool_name=SOURCE_GRANT_TOOL_NAME,
        arguments={"grantRequestId": f"tamper-{tamper}", "selectionKind": "file"},
        audience_session=create_development_mcp_audience(),
        user_action_timeout_seconds=0,
    )

    assert result["isError"] is True
    assert result["structuredContent"] == {
        "schemaVersion": 1,
        "state": "failed",
        "error": {"code": "RESOURCE_GRANT_INVALID"},
    }
    assert "privatePath" not in json.dumps(result)
