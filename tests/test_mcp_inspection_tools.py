from __future__ import annotations

import json

import pytest

from card_service.mcp_inspection_tools import (
    GET_SOURCE_INSPECTION_TOOL_NAME,
    START_SOURCE_INSPECTION_TOOL_NAME,
    McpInspectionToolInputError,
    call_inspection_tool,
    inspection_tool_definitions,
)
from card_service.trusted_mcp_audience import create_development_mcp_audience


PROJECT_ID = "project_" + "a" * 48
SOURCE_HANDLE = "study_" + "b" * 43
INSPECTION_HANDLE = "study_" + "c" * 43


def result() -> dict:
    return {
        "schemaVersion": 1,
        "projectId": PROJECT_ID,
        "projectRevision": 3,
        "artifactStage": "sources_ready",
        "taskId": "task_inspect_" + "d" * 40,
        "inspectionHandle": INSPECTION_HANDLE,
        "completeness": {
            "state": "complete",
            "expectedSources": 1,
            "processedSources": 1,
            "omittedSources": 0,
            "reasonCodes": [],
        },
        "sources": [],
        "nextAction": "discover_candidates",
    }


class RecordingService:
    def __init__(self) -> None:
        self.calls = []

    def inspect_study_sources(self, **kwargs):
        self.calls.append(("start", kwargs))
        return result()

    def get_study_source_inspection(self, **kwargs):
        self.calls.append(("get", kwargs))
        return result()


def start_arguments(**changes) -> dict:
    value = {
        "context": {
            "projectId": PROJECT_ID,
            "expectedProjectRevision": 2,
            "idempotencyKey": "inspect-1",
            "locale": "zh-CN",
        },
        "sourceHandles": [SOURCE_HANDLE],
    }
    value.update(changes)
    return value


def test_inspection_schemas_are_closed_and_do_not_accept_source_content_or_paths() -> (
    None
):
    definitions = inspection_tool_definitions()
    assert [value["name"] for value in definitions] == [
        START_SOURCE_INSPECTION_TOOL_NAME,
        GET_SOURCE_INSPECTION_TOOL_NAME,
    ]
    assert definitions[0]["inputSchema"]["additionalProperties"] is False
    assert (
        definitions[0]["inputSchema"]["properties"]["context"]["additionalProperties"]
        is False
    )
    assert definitions[1]["inputSchema"]["additionalProperties"] is False
    encoded = json.dumps(definitions, sort_keys=True).casefold()
    for forbidden in (
        '"path"',
        '"url"',
        '"text"',
        "ownerdigest",
        "sessionid",
        "apikey",
    ):
        assert forbidden not in encoded
    assert definitions[0]["annotations"] == {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
    assert definitions[1]["annotations"]["readOnlyHint"] is True


def test_start_and_get_call_only_the_trusted_service_boundary() -> None:
    service = RecordingService()
    session = create_development_mcp_audience()

    started = call_inspection_tool(
        service,  # type: ignore[arg-type]
        tool_name=START_SOURCE_INSPECTION_TOOL_NAME,
        arguments=start_arguments(),
        audience_session=session,
    )
    loaded = call_inspection_tool(
        service,  # type: ignore[arg-type]
        tool_name=GET_SOURCE_INSPECTION_TOOL_NAME,
        arguments={"inspectionHandle": INSPECTION_HANDLE},
        audience_session=session,
    )

    assert started["structuredContent"]["nextAction"] == "discover_candidates"
    assert loaded["structuredContent"]["inspectionHandle"] == INSPECTION_HANDLE
    assert service.calls == [
        (
            "start",
            {
                "audience": session.audience,
                "project_id": PROJECT_ID,
                "expected_project_revision": 2,
                "idempotency_key": "inspect-1",
                "source_handles": [SOURCE_HANDLE],
            },
        ),
        (
            "get",
            {
                "audience": session.audience,
                "inspection_handle": INSPECTION_HANDLE,
            },
        ),
    ]


@pytest.mark.parametrize(
    "tool_name,arguments",
    [
        (START_SOURCE_INSPECTION_TOOL_NAME, {}),
        (
            START_SOURCE_INSPECTION_TOOL_NAME,
            {**start_arguments(), "path": "C:/private"},
        ),
        (
            START_SOURCE_INSPECTION_TOOL_NAME,
            {**start_arguments(), "sourceHandles": ["C:/private/source"]},
        ),
        (
            START_SOURCE_INSPECTION_TOOL_NAME,
            {
                **start_arguments(),
                "context": {**start_arguments()["context"], "sessionId": "forged"},
            },
        ),
        (GET_SOURCE_INSPECTION_TOOL_NAME, {"inspectionHandle": "C:/private"}),
    ],
)
def test_inspection_tools_reject_path_or_scope_injection(
    tool_name: str, arguments: dict
) -> None:
    with pytest.raises(McpInspectionToolInputError):
        call_inspection_tool(
            object(),  # type: ignore[arg-type]
            tool_name=tool_name,
            arguments=arguments,
            audience_session=create_development_mcp_audience(),
        )
