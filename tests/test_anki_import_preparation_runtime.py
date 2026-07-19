from __future__ import annotations

import json

import pytest

from card_service.anki_import_preparation import AnkiImportPreparationRuntime
from card_service.anki_target_probe import AnkiTargetProbeError
from card_service.study_runtime import StudyRuntimeError
from tests.test_candidate_discovery_runtime import audience
from tests.test_package_artifact_runtime import (
    RealExportExecutor,
    _await,
    _output_ref,
    _with_exporter,
)


class FakeAnkiTargetInspector:
    def __init__(self, *, offline: bool = False) -> None:
        self.calls = 0
        self.offline = offline

    def __call__(self):
        self.calls += 1
        if self.offline:
            raise AnkiTargetProbeError("ANKI_OFFLINE", "Anki is offline")
        return {
            "schemaVersion": 1,
            "profileRef": "anki_current_" + "a" * 32,
            "configurationFingerprint": "b" * 64,
            "credentialRevision": 0,
            "ankiConnectVersion": 6,
            "profileIdentityDigest": "c" * 64,
            "collectionIdentityDigest": "d" * 64,
            "deckInventoryDigest": "e" * 64,
            "deckCount": 2,
            "transportAuthentication": "none",
            "observedAt": 1_786_000_000_000,
        }


def _preparation(runtime, inspector):
    return AnkiImportPreparationRuntime(
        service_instance_id=runtime.service_instance_id,
        artifacts=runtime.artifacts,
        projects=runtime.projects,
        packages=runtime.package_artifacts,
        target_inspector=inspector,
    )


def test_exported_package_prepares_authenticated_idempotent_import_plan(
    tmp_path,
) -> None:
    executor = RealExportExecutor(tmp_path / "worker-exports")
    runtime, project, _planned, _listed, generated = _with_exporter(tmp_path, executor)
    output = tmp_path / "delivery"
    started = runtime.start_apkg_export(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=generated["projectRevision"],
        idempotency_key="export-before-import-plan",
        project_artifact_handle=generated["projectArtifactHandle"],
        output_ref=_output_ref(runtime, output),
    )
    completed = _await(runtime, started["taskId"])
    assert completed["state"] == "succeeded"

    inspector = FakeAnkiTargetInspector()
    runtime.anki_import_preparation = _preparation(runtime, inspector)
    arguments = {
        "audience": audience(),
        "project_id": project["projectId"],
        "expected_project_revision": completed["result"]["projectRevision"],
        "idempotency_key": "prepare-import-1",
        "package_artifact_handle": completed["result"]["packageArtifactHandle"],
    }
    prepared = runtime.prepare_anki_import(**arguments)
    assert prepared["importIntentId"].startswith("anki_intent_")
    assert prepared["approvalState"] == "pending"
    assert runtime.get_anki_import_approval(
        audience=audience(), import_intent_id=prepared["importIntentId"]
    )["approvalState"] == "pending"
    with pytest.raises(StudyRuntimeError) as cross_session:
        runtime.get_anki_import_approval(
            audience=audience(session_id="session-2"),
            import_intent_id=prepared["importIntentId"],
        )
    assert cross_session.value.code == "IMPORT_APPROVAL_AUDIENCE_MISMATCH"

    assert prepared == {
        **prepared,
        "artifactStage": "apkg_ready",
        "projectRevision": completed["result"]["projectRevision"] + 1,
        "duplicatePolicy": "detect_and_report",
        "dataVerificationCheckCount": 11,
        "runtimeVerification": "not_assessed",
        "confirmationRequired": True,
        "nextAction": "request_import_confirmation",
    }
    assert prepared["package"]["apkgSha256"] == completed["result"]["apkgSha256"]
    assert prepared["target"] == {
        "profileRef": "anki_current_" + "a" * 32,
        "ankiConnectVersion": 6,
        "deckCount": 2,
        "transportAuthentication": "none",
    }
    plan_ref, plan = runtime.artifacts.resolve_with_ref(
        prepared["importPlanHandle"], audience()
    )
    assert plan["payloadSchema"] == "study.anki-import-plan"
    assert len(plan["payload"]["requiredDataChecks"]) == 11
    assert any(
        parent["payloadSchema"] == "study.anki-verification-contract"
        for parent in plan["parents"]
    )
    assert (
        plan_ref
        in runtime.get_project(project["projectId"], audience())["latestArtifactRefs"]
    )
    encoded = json.dumps(prepared, ensure_ascii=False).casefold()
    for forbidden in (
        "media_directory",
        "profileidentitydigest",
        "collectionidentitydigest",
        "registryauthref",
        str(tmp_path).casefold(),
    ):
        assert forbidden not in encoded

    retried = runtime.prepare_anki_import(**arguments)
    assert retried == prepared
    assert inspector.calls == 1

    with pytest.raises(StudyRuntimeError) as captured:
        runtime.prepare_anki_import(
            **{**arguments, "audience": audience(plugin_id="other.plugin")}
        )
    assert captured.value.code == "ARTIFACT_HANDLE_SCOPE_MISMATCH"

    offline = FakeAnkiTargetInspector(offline=True)
    runtime.anki_import_preparation = _preparation(runtime, offline)
    with pytest.raises(StudyRuntimeError) as captured:
        runtime.prepare_anki_import(
            **{
                **arguments,
                "expected_project_revision": prepared["projectRevision"],
                "idempotency_key": "prepare-import-offline",
            }
        )
    assert captured.value.code == "ANKI_OFFLINE"
    assert offline.calls == 1
