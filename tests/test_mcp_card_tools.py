from __future__ import annotations

import json

import pytest

from card_service.mcp_card_tools import (
    CARD_TOOL_NAMES,
    GENERATE_CARDS_TOOL_NAME,
    LIST_CARDS_TOOL_NAME,
    McpCardToolInputError,
    call_card_tool,
    card_tool_definitions,
)
from card_service.trusted_mcp_audience import create_development_mcp_audience


PLAN_SET_HANDLE = "study_" + "p" * 43
PROJECT_ARTIFACT_HANDLE = "study_" + "a" * 43
CARD_CURSOR = "study_card_cursor_" + "c" * 80


class RecordingService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def generate_study_cards(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "schemaVersion": 1,
            "projectId": "project_1",
            "projectRevision": 8,
            "artifactStage": "cards_ready",
            "taskId": "task_card_generation_1",
            "projectArtifactHandle": PROJECT_ARTIFACT_HANDLE,
            "generatedCards": 2,
            "verifiedCards": 2,
            "needsReviewCards": 0,
            "hardFailedCards": 0,
            "mediaCount": 0,
            "generationMode": "deterministic_projection",
            "nextAction": "export_apkg",
        }

    def list_study_generated_cards(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "schemaVersion": 1,
            "projectId": "project_1",
            "projectRevision": 8,
            "artifactStage": "cards_ready",
            "projectArtifactHandle": PROJECT_ARTIFACT_HANDLE,
            "totalCards": 2,
            "returnedCards": 1,
            "items": [{"cardId": "card_1"}],
            "nextCursor": None,
            "nextAction": "export_apkg",
        }


def valid_arguments() -> dict:
    return {
        "context": {
            "projectId": "project_1",
            "expectedProjectRevision": 7,
            "idempotencyKey": "generate-1",
            "locale": "zh-CN",
        },
        "planSetHandle": PLAN_SET_HANDLE,
    }


def test_card_generation_tool_is_closed_world_and_precisely_annotated() -> None:
    definitions = card_tool_definitions()
    assert CARD_TOOL_NAMES == {GENERATE_CARDS_TOOL_NAME, LIST_CARDS_TOOL_NAME}
    assert [value["name"] for value in definitions] == [
        GENERATE_CARDS_TOOL_NAME,
        LIST_CARDS_TOOL_NAME,
    ]
    definition = definitions[0]
    assert definition["annotations"] == {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
    assert definition["inputSchema"]["additionalProperties"] is False
    assert (
        definition["inputSchema"]["properties"]["context"]["additionalProperties"]
        is False
    )
    assert definition["outputSchema"]["additionalProperties"] is False
    assert definitions[1]["annotations"]["readOnlyHint"] is True
    assert definitions[1]["inputSchema"]["additionalProperties"] is False
    assert definitions[1]["outputSchema"]["additionalProperties"] is False
    encoded = json.dumps(
        [value["inputSchema"] for value in definitions], sort_keys=True
    ).casefold()
    for forbidden in (
        "artifactref",
        "registryauthref",
        "modelprofile",
        "ttsprofile",
        "batchpolicy",
        "provider",
        "authorization",
        '"path"',
        '"url"',
        "media",
    ):
        assert forbidden not in encoded


def test_card_generation_tool_calls_only_trusted_service_boundary() -> None:
    service = RecordingService()
    session = create_development_mcp_audience()
    result = call_card_tool(
        service,  # type: ignore[arg-type]
        tool_name=GENERATE_CARDS_TOOL_NAME,
        arguments=valid_arguments(),
        audience_session=session,
    )

    assert result["structuredContent"]["verifiedCards"] == 2
    assert "Generated and verified 2" in result["content"][0]["text"]
    assert service.calls == [
        {
            "audience": session.audience,
            "project_id": "project_1",
            "expected_project_revision": 7,
            "idempotency_key": "generate-1",
            "plan_set_handle": PLAN_SET_HANDLE,
        }
    ]


def test_card_list_tool_calls_only_trusted_service_boundary() -> None:
    service = RecordingService()
    session = create_development_mcp_audience()
    result = call_card_tool(
        service,  # type: ignore[arg-type]
        tool_name=LIST_CARDS_TOOL_NAME,
        arguments={
            "projectArtifactHandle": PROJECT_ARTIFACT_HANDLE,
            "cursor": CARD_CURSOR,
            "limit": 1,
        },
        audience_session=session,
    )

    assert result["structuredContent"]["returnedCards"] == 1
    assert "Loaded 1 of 2" in result["content"][0]["text"]
    assert service.calls == [
        {
            "audience": session.audience,
            "project_artifact_handle": PROJECT_ARTIFACT_HANDLE,
            "cursor": CARD_CURSOR,
            "limit": 1,
        }
    ]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update({"modelProfileRef": "model.private"}),
        lambda value: value.update({"cardPlanRefs": [PLAN_SET_HANDLE]}),
        lambda value: value["context"].update({"authorization": "allow"}),
        lambda value: value["context"].update({"path": r"E:\\secret"}),
        lambda value: value.update({"planSetHandle": "not-a-handle"}),
        lambda value: value["context"].update({"expectedProjectRevision": True}),
        lambda value: value["context"].update({"idempotencyKey": "bad key"}),
    ],
)
def test_card_generation_tool_rejects_injected_or_malformed_fields(mutation) -> None:
    arguments = valid_arguments()
    mutation(arguments)
    with pytest.raises(McpCardToolInputError):
        call_card_tool(
            RecordingService(),  # type: ignore[arg-type]
            tool_name=GENERATE_CARDS_TOOL_NAME,
            arguments=arguments,
            audience_session=create_development_mcp_audience(),
        )


def test_card_generation_tool_rejects_unknown_tool() -> None:
    with pytest.raises(McpCardToolInputError):
        call_card_tool(
            RecordingService(),  # type: ignore[arg-type]
            tool_name="cards.unknown",
            arguments=valid_arguments(),
            audience_session=create_development_mcp_audience(),
        )
