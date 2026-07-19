from __future__ import annotations

import hashlib
import json

import pytest

from card_service.mcp_input_tools import (
    REGISTER_INPUTS_TOOL_NAME,
    McpInputToolInputError,
    call_input_tool,
    input_tool_definitions,
)
from card_service.trusted_mcp_audience import create_development_mcp_audience


def arguments(**changes):
    value = {
        "context": {
            "projectId": "project_" + "a" * 48,
            "expectedProjectRevision": 1,
            "idempotencyKey": "register-inputs-1",
            "locale": "zh-CN",
        },
        "inputRefs": [
            {
                "schemaVersion": 1,
                "kind": "file",
                "fileResourceRef": "resource_" + "b" * 43,
                "displayName": "lesson.mp4",
                "resourceRevisionDigest": hashlib.sha256(b"lesson").hexdigest(),
                "constraints": {"actions": ["read"], "maxBytes": 4096},
                "expiresAt": "2026-07-18T12:00:00.000Z",
            }
        ],
        "snapshotPolicy": "require_stable",
    }
    value.update(changes)
    return value


class RecordingService:
    def __init__(self) -> None:
        self.calls = []

    def register_study_inputs(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "schemaVersion": 1,
            "projectId": kwargs["project_id"],
            "projectRevision": 2,
            "artifactStage": "sources_ready",
            "taskId": "task_register_" + "c" * 40,
            "sources": [
                {
                    "sourceHandle": "study_" + "d" * 43,
                    "sourceId": "source_" + "e" * 40,
                    "displayName": "lesson.mp4",
                    "inputKind": "file",
                    "sourceType": "video",
                    "sourceRevision": 1,
                    "contentSha256": "f" * 64,
                    "supportTier": "B",
                    "status": "conditional",
                }
            ],
            "completeness": {
                "state": "complete",
                "registeredSources": 1,
                "omittedSources": 0,
            },
        }


def test_register_inputs_schema_is_closed_and_cannot_accept_paths_or_audience() -> None:
    definition = input_tool_definitions()[0]
    assert definition["name"] == REGISTER_INPUTS_TOOL_NAME
    assert definition["inputSchema"]["additionalProperties"] is False
    assert (
        definition["inputSchema"]["properties"]["context"]["additionalProperties"]
        is False
    )
    alternatives = definition["inputSchema"]["properties"]["inputRefs"]["items"][
        "oneOf"
    ]
    assert all(item["additionalProperties"] is False for item in alternatives)
    encoded = json.dumps(definition, sort_keys=True).casefold()
    for forbidden in ('"path"', '"url"', "ownerdigest", "sessionid", "apikey"):
        assert forbidden not in encoded
    assert definition["annotations"] == {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }


def test_register_inputs_calls_only_the_trusted_service_boundary() -> None:
    service = RecordingService()
    session = create_development_mcp_audience()
    result = call_input_tool(
        service,  # type: ignore[arg-type]
        tool_name=REGISTER_INPUTS_TOOL_NAME,
        arguments=arguments(),
        audience_session=session,
    )

    assert result["structuredContent"]["artifactStage"] == "sources_ready"
    assert service.calls == [
        {
            "audience": session.audience,
            "project_id": "project_" + "a" * 48,
            "expected_project_revision": 1,
            "idempotency_key": "register-inputs-1",
            "input_refs": arguments()["inputRefs"],
            "snapshot_policy": "require_stable",
        }
    ]
    encoded = json.dumps(result, sort_keys=True)
    assert "resource_" not in encoded
    assert "fileResourceRef" not in encoded


@pytest.mark.parametrize(
    "invalid",
    [
        {},
        {**arguments(), "path": "C:/private/lesson.mp4"},
        {
            **arguments(),
            "context": {**arguments()["context"], "ownerDigest": "forged"},
        },
        {
            **arguments(),
            "inputRefs": [
                {**arguments()["inputRefs"][0], "fileResourceRef": "C:/private"}
            ],
        },
        {**arguments(), "snapshotPolicy": "trust_model_output"},
    ],
)
def test_register_inputs_rejects_scope_or_path_injection(invalid: dict) -> None:
    with pytest.raises(McpInputToolInputError):
        call_input_tool(
            object(),  # type: ignore[arg-type]
            tool_name=REGISTER_INPUTS_TOOL_NAME,
            arguments=invalid,
            audience_session=create_development_mcp_audience(),
        )
