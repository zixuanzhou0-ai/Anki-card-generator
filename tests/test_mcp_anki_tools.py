from __future__ import annotations

import json

import pytest

from card_service.mcp_anki_tools import (
    INSPECT_IMPORT_STATE_TOOL_NAME,
    PREPARE_IMPORT_TOOL_NAME,
    McpAnkiToolInputError,
    anki_tool_definitions,
    call_anki_tool,
)
from card_service.trusted_mcp_audience import create_development_mcp_audience


def _plan():
    return {
        "schemaVersion": 1,
        "importPlanHandle": "study_" + "A" * 43,
        "importIntentId": "anki_intent_" + "a" * 48,
        "approvalState": "pending",
        "artifactStage": "apkg_ready",
        "projectRevision": 9,
        "package": {
            "apkgSha256": "b" * 64,
            "sizeBytes": 1234,
            "fileName": "Study-bbbbbbbbbbbb.apkg",
            "deckNames": ["Study"],
            "noteCount": 1,
            "cardCount": 1,
            "mediaCount": 0,
        },
        "target": {
            "profileRef": "anki_current_" + "c" * 32,
            "ankiConnectVersion": 6,
            "deckCount": 2,
            "transportAuthentication": "none",
        },
        "duplicatePolicy": "detect_and_report",
        "dataVerificationCheckCount": 11,
        "runtimeVerification": "not_assessed",
        "confirmationRequired": True,
        "nextAction": "request_import_confirmation",
    }


class _Service:
    def __init__(self) -> None:
        self.calls = []

    def prepare_study_anki_import(self, **kwargs):
        self.calls.append(kwargs)
        return _plan()

    def inspect_study_anki_import(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "schemaVersion": 1,
            "taskId": "task_anki_reconcile_" + "a" * 40,
            "intent": "inspect_anki_import",
            "state": "succeeded",
            "cancellable": False,
            "resumability": "none",
            "progress": {},
            "result": {
                "reconciliationState": "absent",
                "artifactStage": "apkg_ready",
                "projectRevision": 9,
                "expectedCardCount": 1,
                "observedCardCount": 0,
                "expectedMediaCount": 0,
                "checkedMediaCount": 0,
                "receiptObserved": False,
                "dataVerification": "not_verified",
                "runtimeVerification": "not_assessed",
                "reasonCodes": ["no_imported_cards"],
                "nextAction": "request_import_confirmation",
            },
            "nextAction": "request_import_confirmation",
        }


def _arguments():
    return {
        "context": {
            "projectId": "project-1",
            "expectedProjectRevision": 8,
            "idempotencyKey": "prepare-1",
        },
        "packageArtifactHandle": "study_" + "B" * 43,
    }


def test_prepare_import_tool_has_closed_non_writing_contract() -> None:
    definition = anki_tool_definitions()[0]
    assert definition["name"] == PREPARE_IMPORT_TOOL_NAME
    assert definition["inputSchema"]["additionalProperties"] is False
    assert definition["outputSchema"]["additionalProperties"] is False
    assert definition["annotations"] == {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
    assert "does not import" in definition["description"]


def test_prepare_import_passes_only_authenticated_handles() -> None:
    service = _Service()
    result = call_anki_tool(
        service,
        tool_name=PREPARE_IMPORT_TOOL_NAME,
        arguments=_arguments(),
        audience_session=create_development_mcp_audience(),
    )

    assert result["structuredContent"] == _plan()
    assert service.calls[0]["project_id"] == "project-1"
    assert service.calls[0]["package_artifact_handle"].startswith("study_")
    encoded = json.dumps(result, sort_keys=True).casefold()
    for forbidden in ("c:\\", "e:\\", "media_directory", "profileidentitydigest"):
        assert forbidden not in encoded


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update({"endpoint": "http://example.test"}),
        lambda value: value["context"].update({"profile": "Account 1"}),
        lambda value: value.update({"packageArtifactHandle": "bad handle"}),
        lambda value: value["context"].update({"expectedProjectRevision": True}),
    ],
)
def test_prepare_import_rejects_open_ended_or_malformed_inputs(mutation) -> None:
    arguments = _arguments()
    mutation(arguments)
    with pytest.raises(McpAnkiToolInputError):
        call_anki_tool(
            _Service(),
            tool_name=PREPARE_IMPORT_TOOL_NAME,
            arguments=arguments,
            audience_session=create_development_mcp_audience(),
        )


def test_inspect_import_state_is_closed_and_read_only() -> None:
    definition = next(
        item
        for item in anki_tool_definitions()
        if item["name"] == INSPECT_IMPORT_STATE_TOOL_NAME
    )
    assert definition["annotations"]["readOnlyHint"] is True
    assert definition["annotations"]["destructiveHint"] is False
    assert "never calls importPackage" in definition["description"]
    service = _Service()
    result = call_anki_tool(
        service,
        tool_name=INSPECT_IMPORT_STATE_TOOL_NAME,
        arguments={
            "context": {
                "projectId": "project-1",
                "expectedProjectRevision": 9,
                "idempotencyKey": "inspect-1",
            },
            "importPlanHandle": "study_" + "C" * 43,
        },
        audience_session=create_development_mcp_audience(),
    )
    assert result["structuredContent"]["result"]["reconciliationState"] == "absent"
    assert service.calls[0]["import_plan_handle"].startswith("study_")
    encoded = json.dumps(result, sort_keys=True).casefold()
    for forbidden in ("c:\\", "e:\\", "ankiconnect_url", "import_apkg"):
        assert forbidden not in encoded


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update({"endpoint": "http://example.test"}),
        lambda value: value["context"].update({"profile": "Account 1"}),
        lambda value: value.update({"importPlanHandle": "bad handle"}),
        lambda value: value["context"].update({"expectedProjectRevision": True}),
    ],
)
def test_inspect_import_state_rejects_open_ended_inputs(mutation) -> None:
    arguments = {
        "context": {
            "projectId": "project-1",
            "expectedProjectRevision": 9,
            "idempotencyKey": "inspect-1",
        },
        "importPlanHandle": "study_" + "C" * 43,
    }
    mutation(arguments)
    with pytest.raises(McpAnkiToolInputError):
        call_anki_tool(
            _Service(),
            tool_name=INSPECT_IMPORT_STATE_TOOL_NAME,
            arguments=arguments,
            audience_session=create_development_mcp_audience(),
        )
