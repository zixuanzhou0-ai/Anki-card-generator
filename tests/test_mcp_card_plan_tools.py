from __future__ import annotations

import json

import pytest

from card_service.mcp_card_plan_tools import (
    EDIT_CARD_PLAN_TOOL_NAME,
    LIST_CARD_PLANS_TOOL_NAME,
    PLAN_CARDS_TOOL_NAME,
    VALIDATE_CARD_PLANS_TOOL_NAME,
    McpCardPlanToolInputError,
    call_card_plan_tool,
    card_plan_tool_definitions,
)
from card_service.trusted_mcp_audience import create_development_mcp_audience


SELECTION_HANDLE = "study_" + "a" * 43
PLAN_SET_HANDLE = "study_" + "b" * 43
VALIDATION_HANDLE = "study_" + "c" * 43
PLAN_HANDLE = "study_" + "d" * 43
CURSOR = "study_plan_cursor_" + "e" * 80


class RecordingService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def plan_study_cards(self, **kwargs):
        self.calls.append(("plan", kwargs))
        return {
            "schemaVersion": 1,
            "projectId": "project_1",
            "projectRevision": 6,
            "artifactStage": "plans_ready",
            "taskId": "task_card_plan_1",
            "planSetHandle": PLAN_SET_HANDLE,
            "validationHandle": VALIDATION_HANDLE,
            "totalPlans": 1,
            "eligiblePlans": 1,
            "blockedPlans": 0,
            "issueCodes": [],
            "nextAction": "generate_cards",
        }

    def list_study_card_plans(self, **kwargs):
        self.calls.append(("list", kwargs))
        return {
            "schemaVersion": 1,
            "projectId": "project_1",
            "projectRevision": 6,
            "artifactStage": "plans_ready",
            "planSetHandle": PLAN_SET_HANDLE,
            "totalPlans": 1,
            "returnedPlans": 1,
            "eligiblePlans": 1,
            "blockedPlans": 0,
            "items": [{"cardPlanHandle": PLAN_HANDLE}],
            "nextCursor": None,
            "nextAction": "generate_cards",
        }

    def edit_study_card_plan(self, **kwargs):
        self.calls.append(("edit", kwargs))
        return {
            "schemaVersion": 1,
            "projectId": "project_1",
            "projectRevision": 7,
            "artifactStage": "plans_ready",
            "taskId": "task_card_plan_revision_1",
            "planSetHandle": PLAN_SET_HANDLE,
            "validationHandle": VALIDATION_HANDLE,
            "cardPlanHandle": PLAN_HANDLE,
            "cardPlanId": "card_plan_1",
            "totalPlans": 1,
            "eligiblePlans": 1,
            "blockedPlans": 0,
            "issueCodes": [],
            "nextAction": "generate_cards",
        }

    def validate_study_card_plans(self, **kwargs):
        self.calls.append(("validate", kwargs))
        result = self.edit_study_card_plan(**kwargs)
        self.calls.pop()
        result.pop("cardPlanHandle")
        result.pop("cardPlanId")
        return result


def test_card_plan_tool_schemas_are_closed_and_precisely_annotated() -> None:
    definitions = card_plan_tool_definitions()
    assert [value["name"] for value in definitions] == [
        PLAN_CARDS_TOOL_NAME,
        LIST_CARD_PLANS_TOOL_NAME,
        EDIT_CARD_PLAN_TOOL_NAME,
        VALIDATE_CARD_PLANS_TOOL_NAME,
    ]
    assert definitions[0]["annotations"] == {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
    assert definitions[1]["annotations"] == {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
    for definition in definitions[2:]:
        assert definition["annotations"] == {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        }
    for definition in definitions:
        assert definition["inputSchema"]["additionalProperties"] is False
        assert definition["outputSchema"]["additionalProperties"] is False
    assert (
        definitions[0]["inputSchema"]["properties"]["context"]["additionalProperties"]
        is False
    )
    encoded = json.dumps(
        [value["inputSchema"] for value in definitions], sort_keys=True
    ).casefold()
    for forbidden in (
        "artifactref",
        "registryauthref",
        "blobref",
        "ownerdigest",
        "sessionid",
        "provider",
        "modelprofile",
        "authorization",
        '"path"',
        '"url"',
    ):
        assert forbidden not in encoded


def test_card_plan_tools_call_only_the_trusted_service_boundary() -> None:
    service = RecordingService()
    session = create_development_mcp_audience()
    planned = call_card_plan_tool(
        service,  # type: ignore[arg-type]
        tool_name=PLAN_CARDS_TOOL_NAME,
        arguments={
            "context": {
                "projectId": "project_1",
                "expectedProjectRevision": 5,
                "idempotencyKey": "plan-1",
                "locale": "zh-CN",
            },
            "selectionHandle": SELECTION_HANDLE,
        },
        audience_session=session,
    )
    listed = call_card_plan_tool(
        service,  # type: ignore[arg-type]
        tool_name=LIST_CARD_PLANS_TOOL_NAME,
        arguments={
            "planSetHandle": PLAN_SET_HANDLE,
            "cursor": CURSOR,
            "limit": 7,
        },
        audience_session=session,
    )
    edit_operation = {
        "kind": "edit_card_cue",
        "cue": {"kind": "text", "content": "Which expression fits?"},
    }
    edited = call_card_plan_tool(
        service,  # type: ignore[arg-type]
        tool_name=EDIT_CARD_PLAN_TOOL_NAME,
        arguments={
            "context": {
                "projectId": "project_1",
                "expectedProjectRevision": 6,
                "idempotencyKey": "edit-1",
            },
            "planSetHandle": PLAN_SET_HANDLE,
            "cardPlanHandle": PLAN_HANDLE,
            "operation": edit_operation,
        },
        audience_session=session,
    )
    validated = call_card_plan_tool(
        service,  # type: ignore[arg-type]
        tool_name=VALIDATE_CARD_PLANS_TOOL_NAME,
        arguments={
            "context": {
                "projectId": "project_1",
                "expectedProjectRevision": 7,
                "idempotencyKey": "validate-1",
            },
            "planSetHandle": PLAN_SET_HANDLE,
        },
        audience_session=session,
    )

    assert planned["structuredContent"]["eligiblePlans"] == 1
    assert listed["structuredContent"]["returnedPlans"] == 1
    assert edited["structuredContent"]["cardPlanId"] == "card_plan_1"
    assert validated["structuredContent"]["eligiblePlans"] == 1
    assert service.calls == [
        (
            "plan",
            {
                "audience": session.audience,
                "project_id": "project_1",
                "expected_project_revision": 5,
                "idempotency_key": "plan-1",
                "selection_handle": SELECTION_HANDLE,
            },
        ),
        (
            "list",
            {
                "audience": session.audience,
                "plan_set_handle": PLAN_SET_HANDLE,
                "cursor": CURSOR,
                "limit": 7,
            },
        ),
        (
            "edit",
            {
                "audience": session.audience,
                "project_id": "project_1",
                "expected_project_revision": 6,
                "idempotency_key": "edit-1",
                "plan_set_handle": PLAN_SET_HANDLE,
                "card_plan_handle": PLAN_HANDLE,
                "operation": edit_operation,
            },
        ),
        (
            "validate",
            {
                "audience": session.audience,
                "project_id": "project_1",
                "expected_project_revision": 7,
                "idempotency_key": "validate-1",
                "plan_set_handle": PLAN_SET_HANDLE,
            },
        ),
    ]


@pytest.mark.parametrize(
    "tool_name,arguments",
    [
        (PLAN_CARDS_TOOL_NAME, {}),
        (
            PLAN_CARDS_TOOL_NAME,
            {
                "context": {
                    "projectId": "project_1",
                    "expectedProjectRevision": 5,
                    "idempotencyKey": "plan-1",
                },
                "selectionHandle": SELECTION_HANDLE,
                "modelProfileRef": "forged",
            },
        ),
        (
            PLAN_CARDS_TOOL_NAME,
            {
                "context": {
                    "projectId": "project_1",
                    "expectedProjectRevision": True,
                    "idempotencyKey": "plan-1",
                },
                "selectionHandle": SELECTION_HANDLE,
            },
        ),
        (
            PLAN_CARDS_TOOL_NAME,
            {
                "context": {
                    "projectId": "project_1",
                    "expectedProjectRevision": 5,
                    "idempotencyKey": "plan-1",
                },
                "selectionHandle": "C:/selection",
            },
        ),
        (LIST_CARD_PLANS_TOOL_NAME, {"planSetHandle": PLAN_SET_HANDLE, "limit": 0}),
        (
            LIST_CARD_PLANS_TOOL_NAME,
            {"planSetHandle": PLAN_SET_HANDLE, "cursor": "study_plan_cursor_forged"},
        ),
        (
            LIST_CARD_PLANS_TOOL_NAME,
            {"planSetHandle": PLAN_SET_HANDLE, "path": "C:/plans"},
        ),
        (
            EDIT_CARD_PLAN_TOOL_NAME,
            {
                "context": {
                    "projectId": "project_1",
                    "expectedProjectRevision": 6,
                    "idempotencyKey": "edit-1",
                },
                "planSetHandle": PLAN_SET_HANDLE,
                "cardPlanHandle": PLAN_HANDLE,
                "operation": {"kind": "exclude"},
            },
        ),
        (
            EDIT_CARD_PLAN_TOOL_NAME,
            {
                "context": {
                    "projectId": "project_1",
                    "expectedProjectRevision": 6,
                    "idempotencyKey": "edit-1",
                },
                "planSetHandle": PLAN_SET_HANDLE,
                "cardPlanHandle": PLAN_HANDLE,
                "operation": {
                    "kind": "edit_card_cue",
                    "cue": {"kind": "text", "content": "Which expression fits?"},
                    "provenance": {"actor": "user"},
                },
            },
        ),
        (
            EDIT_CARD_PLAN_TOOL_NAME,
            {
                "context": {
                    "projectId": "project_1",
                    "expectedProjectRevision": 6,
                    "idempotencyKey": "edit-1",
                },
                "planSetHandle": PLAN_SET_HANDLE,
                "cardPlanHandle": PLAN_HANDLE,
                "operation": {
                    "kind": "edit_card_feedback",
                    "feedback": {
                        "explanation": "Explanation",
                        "examples": [],
                        "nonexamples": [],
                        "evidenceRefs": [],
                    },
                },
            },
        ),
        (
            VALIDATE_CARD_PLANS_TOOL_NAME,
            {
                "context": {
                    "projectId": "project_1",
                    "expectedProjectRevision": 6,
                    "idempotencyKey": "validate-1",
                },
                "planSetHandle": PLAN_SET_HANDLE,
                "authorization": "forged",
            },
        ),
    ],
)
def test_card_plan_tools_reject_scope_capability_and_path_injection(
    tool_name: str, arguments: dict
) -> None:
    with pytest.raises(McpCardPlanToolInputError):
        call_card_plan_tool(
            object(),  # type: ignore[arg-type]
            tool_name=tool_name,
            arguments=arguments,
            audience_session=create_development_mcp_audience(),
        )
