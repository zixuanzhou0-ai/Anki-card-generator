from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from card_service.credentials import InMemoryCredentialBackend
from card_service.mcp_artifact_tools import (
    GET_ARTIFACT_TOOL_NAME,
    GET_AUDIT_TOOL_NAME,
    McpArtifactToolInputError,
    artifact_tool_definitions,
    call_artifact_tool,
)
from card_service.mcp_stdio import serve
from card_service.service import CardService, CardServiceError
from card_service.trusted_mcp_audience import create_development_mcp_audience


def service(tmp_path: Path) -> CardService:
    return CardService(
        state_dir=(tmp_path / "service").resolve(),
        credential_backend=InMemoryCredentialBackend(),
        resource_gesture_verifier=lambda *_args: True,
        use_restricted_launcher=False,
    )


def publish(card_service: CardService, *, audience_session):
    runtime = card_service._ensure_study_runtime()
    project = runtime.create_project(
        audience=audience_session.audience,
        idempotency_key="artifact-query-project",
        learning_contract={
            "purpose": "Test authenticated artifact reads",
            "targetBehavior": "Recall one fact",
        },
        title="Artifact query test",
    )
    return runtime.artifacts.publish(
        audience=audience_session.audience,
        project_id=project["projectId"],
        project_revision=1,
        artifact_id="verification-test",
        artifact_revision=1,
        payload_schema="study.anki-verification",
        payload_schema_version=1,
        payload={
            "dataVerification": "passed",
            "runtimeVerification": "not_assessed",
            "cardCount": 1,
            "expectedCardCount": 1,
            "mediaCountExpected": 0,
            "mediaCountChecked": 0,
            "failedChecks": [],
        },
        producer={"component": "test-suite", "version": "1.0.0"},
        parents=[],
        input_fingerprint="a" * 64,
        completeness={
            "state": "complete",
            "expectedUnits": 1,
            "processedUnits": 1,
            "omittedLocators": [],
            "reasonCodes": [],
        },
        issue_refs=[],
    )


def test_artifact_tool_definitions_are_closed_read_only_and_pathless() -> None:
    definitions = artifact_tool_definitions()
    assert [item["name"] for item in definitions] == [
        GET_ARTIFACT_TOOL_NAME,
        GET_AUDIT_TOOL_NAME,
    ]
    for definition in definitions:
        assert definition["inputSchema"]["additionalProperties"] is False
        assert set(definition["inputSchema"]["properties"]) == {"artifactHandle"}
        assert definition["annotations"] == {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        }
        output = definition["outputSchema"]["properties"]
        summary_key = (
            "summary"
            if definition["name"] == GET_ARTIFACT_TOOL_NAME
            else "certificateSummary"
        )
        assert all(
            variant["additionalProperties"] is False
            for variant in output[summary_key]["oneOf"]
        )
        if definition["name"] == GET_AUDIT_TOOL_NAME:
            assert output["producer"]["additionalProperties"] is False
            assert output["completeness"]["additionalProperties"] is False
            assert output["parents"]["items"]["additionalProperties"] is False
        serialized = json.dumps(definition, sort_keys=True).casefold()
        for forbidden in ('path"', 'url"', "registryauthref", "credential", "token"):
            assert forbidden not in serialized


def test_artifact_and_audit_tools_return_safe_authenticated_projections(
    tmp_path: Path,
) -> None:
    card_service = service(tmp_path)
    audience_session = create_development_mcp_audience()
    publication = publish(card_service, audience_session=audience_session)

    artifact = call_artifact_tool(
        card_service,
        tool_name=GET_ARTIFACT_TOOL_NAME,
        arguments={"artifactHandle": publication.handle},
        audience_session=audience_session,
    )["structuredContent"]
    audit = call_artifact_tool(
        card_service,
        tool_name=GET_AUDIT_TOOL_NAME,
        arguments={"artifactHandle": publication.handle},
        audience_session=audience_session,
    )["structuredContent"]

    assert artifact["contentKind"] == "verification_summary"
    assert artifact["summary"]["cardCount"] == 1
    assert audit["integrityVerified"] is True
    assert audit["certificateSummary"]["runtimeVerification"] == "not_assessed"
    serialized = json.dumps({"artifact": artifact, "audit": audit}, sort_keys=True)
    assert "registryAuthRef" not in serialized
    assert "artifactId" not in serialized
    assert str(tmp_path) not in serialized


def test_stdio_hides_artifact_tools_without_trusted_audience(tmp_path: Path) -> None:
    card_service = service(tmp_path)
    audience_session = create_development_mcp_audience()
    publication = publish(card_service, audience_session=audience_session)
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": GET_ARTIFACT_TOOL_NAME,
            "arguments": {"artifactHandle": publication.handle},
        },
    }

    output = io.StringIO()
    serve(card_service, io.StringIO(json.dumps(request) + "\n"), output)
    assert json.loads(output.getvalue())["error"] == {
        "code": -32602,
        "message": "Unknown tool",
    }

    output = io.StringIO()
    serve(
        card_service,
        io.StringIO(json.dumps(request) + "\n"),
        output,
        audience_session=audience_session,
    )
    assert (
        json.loads(output.getvalue())["result"]["structuredContent"]["artifactDigest"]
        == publication.artifact_ref["artifactDigest"]
    )


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"artifactHandle": "bad"},
        {"artifactHandle": "study_" + "A" * 43, "path": "C:/private"},
        {"artifactHandle": 7},
    ],
)
def test_artifact_tool_rejects_open_or_invalid_arguments(
    tmp_path: Path, arguments: dict
) -> None:
    with pytest.raises(McpArtifactToolInputError):
        call_artifact_tool(
            service(tmp_path),
            tool_name=GET_ARTIFACT_TOOL_NAME,
            arguments=arguments,
            audience_session=create_development_mcp_audience(),
        )


def test_cross_session_handle_fails_closed(tmp_path: Path) -> None:
    card_service = service(tmp_path)
    original = create_development_mcp_audience()
    publication = publish(card_service, audience_session=original)

    with pytest.raises(CardServiceError) as captured:
        call_artifact_tool(
            card_service,
            tool_name=GET_ARTIFACT_TOOL_NAME,
            arguments={"artifactHandle": publication.handle},
            audience_session=create_development_mcp_audience(),
        )

    assert captured.value.code == "ARTIFACT_HANDLE_SCOPE_MISMATCH"
