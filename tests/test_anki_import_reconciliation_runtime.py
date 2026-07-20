from __future__ import annotations

from pathlib import Path

import pytest

from card_service.anki_import_execution import AnkiImportExecutionError
from card_service.anki_import_reconciliation import (
    AnkiImportReconciliationError,
    AnkiImportReconciliationRuntime,
)
from card_service.artifact_registry import ArtifactAudienceBinding
from tests.test_anki_import_execution_runtime import _runtime
from tests.test_candidate_discovery_runtime import audience


class _Inspector:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls = 0
        self.bundles = []

    def __call__(self, bundle):
        self.calls += 1
        self.bundles.append(bundle)
        if self.error is not None:
            raise self.error
        return self.result


def _setup(tmp_path: Path, inspector: _Inspector):
    execution, projects, project, _intent, import_executor = _runtime(tmp_path)
    plan_ref = next(
        ref
        for ref in project["latestArtifactRefs"]
        if ref["payloadSchema"] == "study.anki-import-plan"
    )
    plan_handle = execution._artifacts.issue_handle(plan_ref, audience())
    runtime = AnkiImportReconciliationRuntime(
        service_instance_id=execution._service_instance_id,
        artifacts=execution._artifacts,
        projects=projects,
        tasks=execution._tasks,
        preparation=execution._preparation,
        execution=execution,
        inspector=inspector,
    )
    return runtime, projects, project, plan_handle, import_executor


def _arguments(project, plan_handle, key="inspect-1"):
    return {
        "audience": audience(),
        "project_id": project["projectId"],
        "expected_project_revision": project["projectRevision"],
        "idempotency_key": key,
        "import_plan_handle": plan_handle,
    }


def _present_result():
    return {
        "ok": True,
        "failed_checks": [],
        "query": 'deck:"Study"',
        "card_count": 1,
        "imported_card_count": 1,
        "media_count_expected": 0,
        "media_count_checked": 0,
    }


def test_present_is_promoted_without_calling_import_executor(tmp_path: Path) -> None:
    inspector = _Inspector(_present_result())
    runtime, projects, project, plan_handle, import_executor = _setup(
        tmp_path, inspector
    )

    completed = runtime.start(**_arguments(project, plan_handle))

    assert completed["state"] == "succeeded"
    assert completed["result"]["reconciliationState"] == "present"
    assert completed["result"]["dataVerification"] == "passed"
    assert completed["result"]["runtimeVerification"] == "not_assessed"
    assert projects.get_project(project["projectId"], audience())["workflow"][
        "artifactStage"
    ] == "anki_data_verified"
    assert inspector.calls == 1
    assert import_executor.calls == 0
    assert set(inspector.bundles[0]) == {
        "schemaVersion",
        "apkgBlobRef",
        "apkgSha256",
        "sizeBytes",
        "deckNames",
        "cardCount",
        "mediaCount",
        "templateFamily",
        "templateSchemaVersion",
        "cardIdentities",
        "mediaEntries",
    }


@pytest.mark.parametrize(
    ("result", "expected_state"),
    [
        (
            {
                "ok": False,
                "failed_checks": ["no_imported_cards", "card_count_mismatch"],
                "query": 'deck:"Study"',
                "card_count": 0,
                "imported_card_count": 0,
                "media_count_expected": 0,
                "media_count_checked": 0,
            },
            "absent",
        ),
        (
            {
                "ok": False,
                "failed_checks": ["field_content_mismatch"],
                "query": 'deck:"Study"',
                "card_count": 1,
                "imported_card_count": 1,
                "media_count_expected": 0,
                "media_count_checked": 0,
            },
            "partial",
        ),
    ],
)
def test_non_present_states_fail_closed_without_project_promotion(
    tmp_path: Path, result, expected_state: str
) -> None:
    inspector = _Inspector(result)
    runtime, projects, project, plan_handle, import_executor = _setup(
        tmp_path, inspector
    )

    completed = runtime.start(**_arguments(project, plan_handle))

    assert completed["state"] == "succeeded"
    assert completed["result"]["reconciliationState"] == expected_state
    assert completed["result"]["dataVerification"] == "not_verified"
    assert projects.get_project(project["projectId"], audience())["workflow"][
        "artifactStage"
    ] == "apkg_ready"
    assert import_executor.calls == 0


def test_offline_inspection_is_unknown_and_never_imports(tmp_path: Path) -> None:
    inspector = _Inspector(
        error=AnkiImportExecutionError("ANKI_OFFLINE", "Anki is offline")
    )
    runtime, projects, project, plan_handle, import_executor = _setup(
        tmp_path, inspector
    )

    completed = runtime.start(**_arguments(project, plan_handle))

    assert completed["result"]["reconciliationState"] == "unknown"
    assert completed["result"]["reasonCodes"] == ["anki_offline"]
    assert projects.get_project(project["projectId"], audience())["workflow"][
        "artifactStage"
    ] == "apkg_ready"
    assert import_executor.calls == 0


def test_import_plan_handle_is_audience_bound(tmp_path: Path) -> None:
    runtime, _projects, project, plan_handle, _import_executor = _setup(
        tmp_path, _Inspector(_present_result())
    )
    other = ArtifactAudienceBinding(
        owner_digest="f" * 64,
        host_id="other-host",
        plugin_id="other-plugin",
        session_id="other-session",
    )

    with pytest.raises(AnkiImportReconciliationError):
        runtime.start(
            **{
                **_arguments(project, plan_handle),
                "audience": other,
            }
        )
