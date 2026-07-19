from __future__ import annotations

import json

import pytest

from card_service.mcp_candidate_tools import (
    GET_CANDIDATE_TOOL_NAME,
    LIST_CANDIDATES_TOOL_NAME,
    PREVIEW_EVIDENCE_TOOL_NAME,
    START_DISCOVERY_TOOL_NAME,
    McpCandidateToolInputError,
    call_candidate_tool,
    candidate_tool_definitions,
)
from card_service.trusted_mcp_audience import create_development_mcp_audience


DISCOVERY_HANDLE = "study_" + "a" * 43
CANDIDATE_HANDLE = "study_" + "b" * 43
SOURCE_HANDLE = "study_" + "c" * 43
CURSOR = "study_cursor_" + "d" * 80
EVIDENCE_ID = "evidence_" + "e" * 40


class RecordingService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def start_study_candidate_discovery(self, **kwargs):
        self.calls.append(("start", kwargs))
        return {
            "schemaVersion": 1,
            "taskId": "task_discovery_1",
            "intent": "discover_candidates",
            "state": "running",
            "cancellable": True,
            "resumability": "resume_remaining",
            "progress": {
                "phase": "discovery",
                "phasePercent": None,
                "overallPercent": None,
                "lastProgressAt": "2026-07-19T00:00:00Z",
            },
            "nextAction": "poll_task",
        }

    def list_study_candidates(self, **kwargs):
        self.calls.append(("list", kwargs))
        return {
            "schemaVersion": 1,
            "projectId": "project_1",
            "discoveryHandle": DISCOVERY_HANDLE,
            "totalCandidates": 1,
            "returnedCandidates": 1,
            "items": [{"candidateHandle": CANDIDATE_HANDLE}],
            "nextCursor": None,
        }

    def get_study_candidate(self, **kwargs):
        self.calls.append(("get", kwargs))
        return {
            "schemaVersion": 1,
            "projectId": "project_1",
            "discoveryHandle": DISCOVERY_HANDLE,
            "candidateHandle": CANDIDATE_HANDLE,
            "candidateId": "candidate_1",
            "summary": {},
            "objective": {},
            "scores": {},
            "gates": [],
            "evidence": [],
            "relations": [],
            "supportedRoutes": [],
            "userEditHistory": [],
            "issueCodes": [],
            "suppressed": False,
        }

    def preview_study_candidate_evidence(self, **kwargs):
        self.calls.append(("preview", kwargs))
        return {
            "schemaVersion": 1,
            "projectId": "project_1",
            "discoveryHandle": DISCOVERY_HANDLE,
            "candidateHandle": CANDIDATE_HANDLE,
            "evidenceId": EVIDENCE_ID,
            "source": {},
            "quote": "in good shape",
            "contextBefore": "Use ",
            "contextAfter": " here.",
            "locator": {},
            "quoteSha256": "f" * 64,
            "snapshotBacked": True,
            "networkAccessed": False,
        }


def test_candidate_tool_schemas_are_closed_and_mark_remote_discovery() -> None:
    definitions = candidate_tool_definitions()
    assert [value["name"] for value in definitions] == [
        START_DISCOVERY_TOOL_NAME,
        LIST_CANDIDATES_TOOL_NAME,
        GET_CANDIDATE_TOOL_NAME,
        PREVIEW_EVIDENCE_TOOL_NAME,
    ]
    assert definitions[0]["annotations"] == {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
    for definition in definitions[1:]:
        assert definition["inputSchema"]["additionalProperties"] is False
        assert definition["annotations"] == {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        }
    assert definitions[0]["inputSchema"]["additionalProperties"] is False
    list_filter = definitions[1]["inputSchema"]["properties"]["filter"]
    assert list_filter["additionalProperties"] is False
    encoded_inputs = json.dumps(
        [value["inputSchema"] for value in definitions], sort_keys=True
    ).casefold()
    for forbidden in (
        "artifactref",
        "registryauthref",
        "blobref",
        "ownerdigest",
        "sessionid",
        "modelprofileref",
        "authorization",
        '"path"',
        '"url"',
    ):
        assert forbidden not in encoded_inputs


def test_candidate_tools_call_only_the_trusted_service_boundary() -> None:
    service = RecordingService()
    session = create_development_mcp_audience()

    started = call_candidate_tool(
        service,  # type: ignore[arg-type]
        tool_name=START_DISCOVERY_TOOL_NAME,
        arguments={
            "context": {
                "projectId": "project_1",
                "expectedProjectRevision": 3,
                "idempotencyKey": "discover-1",
            },
            "inspectionHandle": DISCOVERY_HANDLE,
            "candidateBudget": {"target": 8, "maximum": 16},
        },
        audience_session=session,
    )
    listed = call_candidate_tool(
        service,  # type: ignore[arg-type]
        tool_name=LIST_CANDIDATES_TOOL_NAME,
        arguments={
            "discoveryHandle": DISCOVERY_HANDLE,
            "filter": {
                "eligibility": ["recommended"],
                "route": ["production"],
                "selectionState": ["selected"],
                "sourceHandles": [SOURCE_HANDLE],
                "query": "shape",
            },
            "sort": "review_cost",
            "cursor": CURSOR,
            "limit": 7,
        },
        audience_session=session,
    )
    loaded = call_candidate_tool(
        service,  # type: ignore[arg-type]
        tool_name=GET_CANDIDATE_TOOL_NAME,
        arguments={
            "discoveryHandle": DISCOVERY_HANDLE,
            "candidateHandle": CANDIDATE_HANDLE,
        },
        audience_session=session,
    )
    previewed = call_candidate_tool(
        service,  # type: ignore[arg-type]
        tool_name=PREVIEW_EVIDENCE_TOOL_NAME,
        arguments={
            "discoveryHandle": DISCOVERY_HANDLE,
            "candidateHandle": CANDIDATE_HANDLE,
            "evidenceId": EVIDENCE_ID,
            "contextCharacters": 240,
        },
        audience_session=session,
    )

    assert started["structuredContent"]["state"] == "running"
    assert listed["structuredContent"]["returnedCandidates"] == 1
    assert loaded["structuredContent"]["candidateHandle"] == CANDIDATE_HANDLE
    assert previewed["structuredContent"]["quote"] == "in good shape"
    assert service.calls == [
        (
            "start",
            {
                "audience": session.audience,
                "project_id": "project_1",
                "expected_project_revision": 3,
                "idempotency_key": "discover-1",
                "inspection_handle": DISCOVERY_HANDLE,
                "candidate_budget": {"target": 8, "maximum": 16},
            },
        ),
        (
            "list",
            {
                "audience": session.audience,
                "discovery_handle": DISCOVERY_HANDLE,
                "filters": {
                    "eligibility": ["recommended"],
                    "route": ["production"],
                    "selectionState": ["selected"],
                    "sourceHandles": [SOURCE_HANDLE],
                    "query": "shape",
                },
                "sort": "review_cost",
                "cursor": CURSOR,
                "limit": 7,
            },
        ),
        (
            "get",
            {
                "audience": session.audience,
                "discovery_handle": DISCOVERY_HANDLE,
                "candidate_handle": CANDIDATE_HANDLE,
            },
        ),
        (
            "preview",
            {
                "audience": session.audience,
                "discovery_handle": DISCOVERY_HANDLE,
                "candidate_handle": CANDIDATE_HANDLE,
                "evidence_id": EVIDENCE_ID,
                "context_characters": 240,
            },
        ),
    ]


@pytest.mark.parametrize(
    "tool_name,arguments",
    [
        (START_DISCOVERY_TOOL_NAME, {}),
        (
            START_DISCOVERY_TOOL_NAME,
            {
                "context": {
                    "projectId": "project_1",
                    "expectedProjectRevision": 3,
                    "idempotencyKey": "discover-1",
                },
                "inspectionHandle": DISCOVERY_HANDLE,
                "candidateBudget": {"target": 8, "maximum": 257},
            },
        ),
        (
            START_DISCOVERY_TOOL_NAME,
            {
                "context": {
                    "projectId": "project_1",
                    "expectedProjectRevision": 3,
                    "idempotencyKey": "discover-1",
                },
                "inspectionHandle": DISCOVERY_HANDLE,
                "candidateBudget": {"target": 17, "maximum": 16},
            },
        ),
        (
            START_DISCOVERY_TOOL_NAME,
            {
                "context": {
                    "projectId": "project_1",
                    "expectedProjectRevision": 3,
                    "idempotencyKey": "discover-1",
                },
                "inspectionHandle": DISCOVERY_HANDLE,
                "candidateBudget": {"target": 8, "maximum": 16},
                "provider": "hermes",
            },
        ),
        (LIST_CANDIDATES_TOOL_NAME, {}),
        (
            LIST_CANDIDATES_TOOL_NAME,
            {"discoveryHandle": DISCOVERY_HANDLE, "path": "C:/x"},
        ),
        (
            LIST_CANDIDATES_TOOL_NAME,
            {
                "discoveryHandle": DISCOVERY_HANDLE,
                "filter": {"eligibility": ["forged"]},
            },
        ),
        (
            LIST_CANDIDATES_TOOL_NAME,
            {"discoveryHandle": DISCOVERY_HANDLE, "cursor": "study_cursor_forged"},
        ),
        (
            GET_CANDIDATE_TOOL_NAME,
            {"discoveryHandle": DISCOVERY_HANDLE, "candidateHandle": "C:/candidate"},
        ),
        (
            PREVIEW_EVIDENCE_TOOL_NAME,
            {
                "discoveryHandle": DISCOVERY_HANDLE,
                "candidateHandle": CANDIDATE_HANDLE,
                "evidenceId": EVIDENCE_ID,
                "contextCharacters": 481,
            },
        ),
    ],
)
def test_candidate_tools_reject_scope_path_and_taxonomy_injection(
    tool_name: str, arguments: dict
) -> None:
    with pytest.raises(McpCandidateToolInputError):
        call_candidate_tool(
            object(),  # type: ignore[arg-type]
            tool_name=tool_name,
            arguments=arguments,
            audience_session=create_development_mcp_audience(),
        )
