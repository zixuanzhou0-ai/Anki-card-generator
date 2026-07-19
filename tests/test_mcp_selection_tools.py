from __future__ import annotations

import json

import pytest

from card_service.mcp_selection_tools import (
    SET_SELECTION_TOOL_NAME,
    McpSelectionToolInputError,
    call_selection_tool,
    selection_tool_definitions,
)
from card_service.trusted_mcp_audience import create_development_mcp_audience


DISCOVERY_HANDLE = "study_" + "a" * 43
CANDIDATE_HANDLE = "study_" + "b" * 43


class RecordingService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def set_study_selection(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "schemaVersion": 1,
            "projectId": "project_1",
            "projectRevision": 5,
            "artifactStage": "selection_ready",
            "taskId": "task_selection_1",
            "selectionHandle": "study_" + "c" * 43,
            "selectedCount": 1,
            "budget": {"maxNewCards": 10},
            "coverage": [],
            "redundancyWarnings": [],
            "estimatedReviewDebt": {},
            "issueCodes": [],
            "nextAction": "plan_cards",
        }


def test_selection_schema_is_closed_local_and_non_destructive() -> None:
    definition = selection_tool_definitions()[0]
    assert definition["name"] == SET_SELECTION_TOOL_NAME
    assert definition["inputSchema"]["additionalProperties"] is False
    assert (
        definition["inputSchema"]["properties"]["context"]["additionalProperties"]
        is False
    )
    assert (
        definition["inputSchema"]["properties"]["budget"]["additionalProperties"]
        is False
    )
    assert definition["outputSchema"]["additionalProperties"] is False
    assert definition["annotations"] == {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
    encoded = json.dumps(definition["inputSchema"], sort_keys=True).casefold()
    for forbidden in (
        "artifactref",
        "registryauthref",
        "blobref",
        "ownerdigest",
        "sessionid",
        "provider",
        "authorization",
        '"path"',
        '"url"',
    ):
        assert forbidden not in encoded


def test_selection_tool_calls_only_the_trusted_service_boundary() -> None:
    service = RecordingService()
    session = create_development_mcp_audience()
    result = call_selection_tool(
        service,  # type: ignore[arg-type]
        tool_name=SET_SELECTION_TOOL_NAME,
        arguments={
            "context": {
                "projectId": "project_1",
                "expectedProjectRevision": 4,
                "idempotencyKey": "selection-1",
                "locale": "zh-CN",
            },
            "discoveryHandle": DISCOVERY_HANDLE,
            "operation": "add",
            "candidateHandles": [CANDIDATE_HANDLE],
            "budget": {"maxNewCards": 10, "targetDailyReviewMinutes": 15},
        },
        audience_session=session,
    )
    assert result["structuredContent"]["selectedCount"] == 1
    assert service.calls == [
        {
            "audience": session.audience,
            "project_id": "project_1",
            "expected_project_revision": 4,
            "idempotency_key": "selection-1",
            "discovery_handle": DISCOVERY_HANDLE,
            "operation": "add",
            "candidate_handles": [CANDIDATE_HANDLE],
            "budget": {"maxNewCards": 10, "targetDailyReviewMinutes": 15},
        }
    ]


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {
            "context": {
                "projectId": "project_1",
                "expectedProjectRevision": 4,
                "idempotencyKey": "selection-1",
            },
            "discoveryHandle": DISCOVERY_HANDLE,
            "operation": "add",
        },
        {
            "context": {
                "projectId": "project_1",
                "expectedProjectRevision": 4,
                "idempotencyKey": "selection-1",
            },
            "discoveryHandle": DISCOVERY_HANDLE,
            "operation": "accept_recommended",
            "candidateHandles": [CANDIDATE_HANDLE],
        },
        {
            "context": {
                "projectId": "project_1",
                "expectedProjectRevision": 4,
                "idempotencyKey": "selection-1",
            },
            "discoveryHandle": DISCOVERY_HANDLE,
            "operation": "add",
            "candidateHandles": ["C:/candidate"],
        },
        {
            "context": {
                "projectId": "project_1",
                "expectedProjectRevision": 4,
                "idempotencyKey": "selection-1",
            },
            "discoveryHandle": DISCOVERY_HANDLE,
            "operation": "forged",
            "candidateHandles": [CANDIDATE_HANDLE],
        },
        {
            "context": {
                "projectId": "project_1",
                "expectedProjectRevision": 4,
                "idempotencyKey": "selection-1",
            },
            "discoveryHandle": DISCOVERY_HANDLE,
            "operation": "accept_recommended",
            "budget": {"maxNewCards": 1001},
        },
    ],
)
def test_selection_tool_rejects_scope_operation_and_budget_injection(
    arguments: dict,
) -> None:
    with pytest.raises(McpSelectionToolInputError):
        call_selection_tool(
            object(),  # type: ignore[arg-type]
            tool_name=SET_SELECTION_TOOL_NAME,
            arguments=arguments,
            audience_session=create_development_mcp_audience(),
        )
