from __future__ import annotations

import json

import pytest

from card_service.mcp_package_tools import (
    EXPORT_APKG_TOOL_NAME,
    McpPackageToolInputError,
    call_package_tool,
    package_tool_definitions,
)
from card_service.mcp_task_tools import (
    CANCEL_TASK_TOOL_NAME,
    GET_TASK_TOOL_NAME,
    McpTaskToolInputError,
    call_task_tool,
    task_tool_definitions,
)
from card_service.trusted_mcp_audience import create_development_mcp_audience


def task(state: str = "running"):
    value = {
        "schemaVersion": 1,
        "taskId": "task_package_export_" + "a" * 40,
        "intent": "export_apkg",
        "state": state,
        "cancellable": state == "running",
        "resumability": "restart_phase",
        "progress": {
            "phase": "export",
            "phasePercent": 25 if state == "running" else 100,
            "overallPercent": 25 if state == "running" else 100,
            "lastProgressAt": "2026-07-19T00:00:00.000Z",
        },
        "nextAction": "poll_task" if state == "running" else "prepare_anki_import",
    }
    if state == "succeeded":
        value["result"] = {
            "packageArtifactHandle": "study_" + "A" * 43,
            "artifactStage": "apkg_ready",
            "projectRevision": 8,
            "apkgSha256": "b" * 64,
            "sizeBytes": 1234,
            "fileName": "Study-bbbbbbbbbbbb.apkg",
            "deckNames": ["Study"],
            "noteCount": 1,
            "cardCount": 1,
            "mediaCount": 0,
            "deliveryState": "written",
            "nextAction": "prepare_anki_import",
        }
    return value


class PackageService:
    def __init__(self) -> None:
        self.calls = []

    def start_study_apkg_export(self, **kwargs):
        self.calls.append(("export", kwargs))
        return task()

    def get_public_study_task(self, **kwargs):
        self.calls.append(("get", kwargs))
        return task("succeeded")

    def cancel_public_study_task(self, **kwargs):
        self.calls.append(("cancel", kwargs))
        return {**task(), "state": "cancelling", "nextAction": "poll_task"}


def arguments():
    return {
        "context": {
            "projectId": "project-1",
            "expectedProjectRevision": 7,
            "idempotencyKey": "export-1",
        },
        "projectArtifactHandle": "study_" + "B" * 43,
        "outputRef": {
            "schemaVersion": 1,
            "displayName": "Selected output folder",
            "resourceRevisionDigest": "c" * 64,
            "constraints": {
                "actions": ["create", "versioned"],
                "maxFiles": 1024,
                "maxTotalBytes": 32 * 1024 * 1024 * 1024,
            },
            "expiresAt": "2026-07-19T01:00:00.000Z",
            "kind": "output_directory",
            "outputResourceRef": "resource_" + "D" * 43,
        },
    }


def test_package_export_tool_has_closed_async_contract() -> None:
    definition = package_tool_definitions()[0]
    assert definition["name"] == EXPORT_APKG_TOOL_NAME
    assert definition["inputSchema"]["additionalProperties"] is False
    assert definition["outputSchema"]["additionalProperties"] is False
    assert definition["annotations"] == {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }


def test_package_export_passes_only_opaque_refs_and_returns_task() -> None:
    service = PackageService()
    session = create_development_mcp_audience()
    result = call_package_tool(
        service,
        tool_name=EXPORT_APKG_TOOL_NAME,
        arguments=arguments(),
        audience_session=session,
    )
    assert result["structuredContent"] == task()
    call = service.calls[0][1]
    assert call["project_id"] == "project-1"
    assert call["project_artifact_handle"].startswith("study_")
    assert call["output_ref"]["outputResourceRef"].startswith("resource_")
    encoded = json.dumps(result, ensure_ascii=False).casefold()
    for forbidden in (
        "c:\\",
        "e:\\",
        "apkg_path",
        "inputfingerprint",
        "registryauthref",
    ):
        assert forbidden not in encoded


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update({"path": "E:\\private"}),
        lambda value: value["outputRef"].update({"replace": True}),
        lambda value: value["context"].update({"provider": "arbitrary"}),
        lambda value: value["outputRef"]["constraints"].update(
            {"actions": ["replace"]}
        ),
    ],
)
def test_package_export_rejects_open_ended_or_overwrite_inputs(mutation) -> None:
    value = arguments()
    mutation(value)
    with pytest.raises(McpPackageToolInputError):
        call_package_tool(
            PackageService(),
            tool_name=EXPORT_APKG_TOOL_NAME,
            arguments=value,
            audience_session=create_development_mcp_audience(),
        )


def test_task_tools_poll_and_cancel_without_private_task_fields() -> None:
    definitions = {value["name"]: value for value in task_tool_definitions()}
    assert set(definitions) == {GET_TASK_TOOL_NAME, CANCEL_TASK_TOOL_NAME}
    service = PackageService()
    session = create_development_mcp_audience()
    task_id = "task_package_export_" + "a" * 40
    loaded = call_task_tool(
        service,
        tool_name=GET_TASK_TOOL_NAME,
        arguments={"taskId": task_id},
        audience_session=session,
    )
    cancelled = call_task_tool(
        service,
        tool_name=CANCEL_TASK_TOOL_NAME,
        arguments={"taskId": task_id},
        audience_session=session,
    )
    assert loaded["structuredContent"]["state"] == "succeeded"
    assert cancelled["structuredContent"]["state"] == "cancelling"
    encoded = json.dumps([loaded, cancelled], ensure_ascii=False).casefold()
    for forbidden in ("resultref", "workunits", "inputfingerprint", "artifactref"):
        assert forbidden not in encoded


def test_task_tools_reject_extra_fields_and_malformed_ids() -> None:
    session = create_development_mcp_audience()
    with pytest.raises(McpTaskToolInputError):
        call_task_tool(
            PackageService(),
            tool_name=GET_TASK_TOOL_NAME,
            arguments={"taskId": "bad task", "debug": True},
            audience_session=session,
        )
