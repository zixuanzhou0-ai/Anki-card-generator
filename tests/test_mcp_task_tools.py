from __future__ import annotations

import json

import pytest

from card_service.mcp_task_tools import (
    CANCEL_TASK_TOOL_NAME,
    GET_TASK_TOOL_NAME,
    LIST_RECOVERABLE_TASKS_TOOL_NAME,
    RESUME_TASK_TOOL_NAME,
    McpTaskToolInputError,
    call_task_tool,
    task_tool_definitions,
)
from card_service.trusted_mcp_audience import create_development_mcp_audience


TASK_ID = "task_discovery_" + "a" * 40


def _task(state: str = "failed") -> dict:
    return {
        "schemaVersion": 1,
        "taskId": TASK_ID,
        "intent": "discover_candidates",
        "state": state,
        "cancellable": False,
        "resumability": "resume_remaining",
        "progress": {
            "phase": "discovery",
            "phasePercent": 0,
            "overallPercent": 0,
            "lastProgressAt": "2026-07-19T00:00:00Z",
        },
        "error": {
            "code": "MODEL_OUTPUT_INVALID",
            "retryable": True,
            "stage": "discovery",
        },
        "nextAction": "resume_task",
    }


class RecordingService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def get_public_study_task(self, **kwargs):
        self.calls.append(("get", kwargs))
        return _task()

    def cancel_public_study_task(self, **kwargs):
        self.calls.append(("cancel", kwargs))
        return _task("cancelled")

    def list_public_recoverable_study_tasks(self, **kwargs):
        self.calls.append(("list", kwargs))
        return {
            "schemaVersion": 1,
            "tasks": [_task()],
            "returnedTasks": 1,
            "nextAction": "resume_task",
        }

    def resume_public_study_task(self, **kwargs):
        self.calls.append(("resume", kwargs))
        return _task("running")


def test_task_recovery_tool_schemas_are_closed_and_do_not_accept_control_plane_data() -> (
    None
):
    definitions = task_tool_definitions()
    assert [value["name"] for value in definitions] == [
        GET_TASK_TOOL_NAME,
        CANCEL_TASK_TOOL_NAME,
        LIST_RECOVERABLE_TASKS_TOOL_NAME,
        RESUME_TASK_TOOL_NAME,
    ]
    for definition in definitions:
        assert definition["inputSchema"]["additionalProperties"] is False
    by_name = {value["name"]: value for value in definitions}
    assert (
        by_name[LIST_RECOVERABLE_TASKS_TOOL_NAME]["annotations"]["readOnlyHint"] is True
    )
    assert by_name[RESUME_TASK_TOOL_NAME]["annotations"] == {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
    encoded = json.dumps(
        [value["inputSchema"] for value in definitions], sort_keys=True
    ).casefold()
    for forbidden in (
        "authorization",
        "provider",
        "modelprofileref",
        "baseurl",
        "credential",
        "fingerprint",
        '"path"',
        '"url"',
        "artifactref",
        "blobref",
    ):
        assert forbidden not in encoded


def test_task_recovery_tools_call_only_the_trusted_service_boundary() -> None:
    service = RecordingService()
    session = create_development_mcp_audience()

    call_task_tool(
        service,
        tool_name=GET_TASK_TOOL_NAME,
        arguments={"taskId": TASK_ID},
        audience_session=session,
    )
    call_task_tool(
        service,
        tool_name=CANCEL_TASK_TOOL_NAME,
        arguments={"taskId": TASK_ID},
        audience_session=session,
    )
    listed = call_task_tool(
        service,
        tool_name=LIST_RECOVERABLE_TASKS_TOOL_NAME,
        arguments={"limit": 7},
        audience_session=session,
    )
    resumed = call_task_tool(
        service,
        tool_name=RESUME_TASK_TOOL_NAME,
        arguments={"taskId": TASK_ID, "idempotencyKey": "resume-1"},
        audience_session=session,
    )

    assert listed["structuredContent"]["returnedTasks"] == 1
    assert resumed["structuredContent"]["state"] == "running"
    assert service.calls == [
        ("get", {"audience": session.audience, "task_id": TASK_ID}),
        ("cancel", {"audience": session.audience, "task_id": TASK_ID}),
        ("list", {"audience": session.audience, "limit": 7}),
        (
            "resume",
            {
                "audience": session.audience,
                "task_id": TASK_ID,
                "idempotency_key": "resume-1",
            },
        ),
    ]


@pytest.mark.parametrize(
    "tool_name,arguments",
    [
        (LIST_RECOVERABLE_TASKS_TOOL_NAME, {"limit": True}),
        (LIST_RECOVERABLE_TASKS_TOOL_NAME, {"path": "C:/private"}),
        (RESUME_TASK_TOOL_NAME, {"taskId": TASK_ID}),
        (
            RESUME_TASK_TOOL_NAME,
            {
                "taskId": TASK_ID,
                "idempotencyKey": "resume-1",
                "provider": "forged",
            },
        ),
        (
            RESUME_TASK_TOOL_NAME,
            {"taskId": TASK_ID, "idempotencyKey": "bad key"},
        ),
    ],
)
def test_task_recovery_tools_reject_injected_or_invalid_fields(
    tool_name: str, arguments: dict
) -> None:
    with pytest.raises(McpTaskToolInputError):
        call_task_tool(
            object(),
            tool_name=tool_name,
            arguments=arguments,
            audience_session=create_development_mcp_audience(),
        )
