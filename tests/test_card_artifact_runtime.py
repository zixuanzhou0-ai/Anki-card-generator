from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from card_service.card_artifact_runtime import CardArtifactRuntimeError
from card_service.project_registry import ProjectRegistryError
from card_service.study_runtime import StudyRuntimeError
from card_service.task_coordinator import StudyTaskError
from tests.test_card_plan_revision_runtime import planned_runtime
from tests.test_candidate_discovery_runtime import audience
from tests.test_candidate_discovery_runtime import (
    FakeDiscoveryModel,
    _selection_for_card_planning,
)


def generated_runtime(tmp_path):
    runtime, project, planned, listed = planned_runtime(tmp_path)
    generated = runtime.generate_cards(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=planned["projectRevision"],
        idempotency_key="generate-cards-1",
        plan_set_handle=planned["planSetHandle"],
    )
    return runtime, project, planned, listed, generated


def test_generation_publishes_verified_cards_and_export_compatible_projection(
    tmp_path,
) -> None:
    runtime, project, planned, _listed, result = generated_runtime(tmp_path)

    assert result == {
        "schemaVersion": 1,
        "projectId": project["projectId"],
        "projectRevision": planned["projectRevision"] + 1,
        "artifactStage": "cards_ready",
        "taskId": result["taskId"],
        "projectArtifactHandle": result["projectArtifactHandle"],
        "generatedCards": 1,
        "verifiedCards": 1,
        "needsReviewCards": 0,
        "hardFailedCards": 0,
        "mediaCount": 0,
        "generationMode": "deterministic_projection",
        "nextAction": "export_apkg",
    }
    resolved = runtime.card_artifacts.resolve_current_project_artifact(
        audience=audience(),
        project_artifact_handle=result["projectArtifactHandle"],
    )
    assert len(resolved["cardEnvelopes"]) == 1
    card = resolved["cardEnvelopes"][0]["payload"]
    assert (
        card["front"]["prompt"] == "Intended function: healthy or in a good condition"
    )
    assert card["back"]["coreAnswer"] == "in good shape"
    assert card["scoring"]["points"] == ["in good shape"]
    assert card["verification"]["state"] == "verified"
    assert card["mediaRefs"] == []
    assert card["generation"] == {
        "mode": "deterministic_projection",
        "policyVersion": "deterministic-card-artifact-v1",
        "modelUsed": False,
        "ttsUsed": False,
        "mediaUsed": False,
    }
    legacy = resolved["legacyProjection"]["projection"]["project"]
    assert legacy["source_mode"] == "document"
    assert legacy["video_path"] == ""
    assert legacy["subtitle_path"] == ""
    assert legacy["reliability_manifest"]["decision"] == "pass"
    legacy_card = legacy["segments"][0]["cards"][0]
    assert legacy_card["answer_core"] == "in good shape"
    assert legacy_card["verification_status"] == "verified"
    assert legacy_card["quality"]["status"] == "recommended"


def test_generation_is_idempotent_without_duplicate_card_artifacts(tmp_path) -> None:
    runtime, project, planned, _listed = planned_runtime(tmp_path)
    arguments = {
        "audience": audience(),
        "project_id": project["projectId"],
        "expected_project_revision": planned["projectRevision"],
        "idempotency_key": "generate-idempotent",
        "plan_set_handle": planned["planSetHandle"],
    }
    first = runtime.generate_cards(**arguments)
    repeated = runtime.generate_cards(**arguments)

    first_ref, _ = runtime.artifacts.resolve_with_ref(
        first["projectArtifactHandle"], audience()
    )
    repeated_ref, _ = runtime.artifacts.resolve_with_ref(
        repeated["projectArtifactHandle"], audience()
    )
    assert repeated_ref == first_ref
    assert {
        key: value for key, value in repeated.items() if key != "projectArtifactHandle"
    } == {key: value for key, value in first.items() if key != "projectArtifactHandle"}
    current = runtime.get_project(project["projectId"], audience())
    project_artifacts = [
        value
        for value in current["latestArtifactRefs"]
        if value["payloadSchema"] == "study.project-artifact"
    ]
    assert len(project_artifacts) == 1


def test_generation_fails_closed_when_one_plan_needs_review(tmp_path) -> None:
    runtime, project, planned, listed = planned_runtime(tmp_path)
    edited = runtime.edit_card_plan(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=planned["projectRevision"],
        idempotency_key="feedback-review-before-generate",
        plan_set_handle=planned["planSetHandle"],
        card_plan_handle=listed["items"][0]["cardPlanHandle"],
        operation={
            "kind": "edit_card_feedback",
            "feedback": {
                "explanation": "Unsupported new explanation.",
                "examples": ["A new example."],
                "nonexamples": [],
            },
        },
    )

    with pytest.raises(StudyRuntimeError) as captured:
        runtime.generate_cards(
            audience=audience(),
            project_id=project["projectId"],
            expected_project_revision=edited["projectRevision"],
            idempotency_key="blocked-generation",
            plan_set_handle=edited["planSetHandle"],
        )
    assert captured.value.code == "CARD_GENERATION_PLAN_BLOCKED"
    current = runtime.get_project(project["projectId"], audience())
    assert current["workflow"]["artifactStage"] == "plans_ready"
    assert not any(
        value["payloadSchema"] == "study.project-artifact"
        for value in current["latestArtifactRefs"]
    )


def test_generation_rejects_model_media_and_path_injection_fields(tmp_path) -> None:
    runtime, project, planned, _listed = planned_runtime(tmp_path)
    with pytest.raises(TypeError):
        runtime.generate_cards(
            audience=audience(),
            project_id=project["projectId"],
            expected_project_revision=planned["projectRevision"],
            idempotency_key="reject-injection",
            plan_set_handle=planned["planSetHandle"],
            model_profile_ref="model.private",  # type: ignore[call-arg]
        )


def test_project_artifact_is_bound_to_audience_and_current_revision(tmp_path) -> None:
    runtime, _project, _planned, _listed, result = generated_runtime(tmp_path)
    with pytest.raises(CardArtifactRuntimeError):
        runtime.card_artifacts.resolve_current_project_artifact(
            audience=audience(session_id="session-other"),
            project_artifact_handle=result["projectArtifactHandle"],
        )


def test_persisted_generation_graph_contains_no_raw_path_or_credentials(
    tmp_path,
) -> None:
    runtime, _project, _planned, _listed, result = generated_runtime(tmp_path)
    resolved = runtime.card_artifacts.resolve_current_project_artifact(
        audience=audience(),
        project_artifact_handle=result["projectArtifactHandle"],
    )
    encoded = json.dumps(resolved["projectArtifact"], ensure_ascii=False).casefold()
    for forbidden in (
        "apikey",
        "access_token",
        "authorization",
        "e:\\",
        "c:\\users",
        "lesson.txt",
    ):
        assert forbidden not in encoded


def _load_worker():
    path = Path(__file__).resolve().parents[1] / "workers" / "anki_worker.py"
    spec = importlib.util.spec_from_file_location(
        "anki_worker_card_artifact_projection_tests", path
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_legacy_projection_exports_through_the_real_apkg_worker(tmp_path) -> None:
    runtime, _project, _planned, _listed, result = generated_runtime(tmp_path)
    resolved = runtime.card_artifacts.resolve_current_project_artifact(
        audience=audience(),
        project_artifact_handle=result["projectArtifactHandle"],
    )
    legacy_project = resolved["legacyProjection"]["projection"]["project"]
    output_dir = tmp_path / "export"
    output_dir.mkdir()

    exported = _load_worker().handle_export(
        {"project": legacy_project, "output_dir": str(output_dir)}
    )

    apkg_path = Path(exported["apkg_path"])
    assert apkg_path.is_file()
    assert apkg_path.resolve().is_relative_to(output_dir.resolve())
    assert exported["cards"] == 1


def test_generation_recovers_after_work_unit_completion_before_task_success(
    tmp_path,
) -> None:
    runtime, project, planned, _listed = planned_runtime(tmp_path)
    original = runtime.tasks.succeed_task
    failed = False

    def fail_once(*args, **kwargs):
        nonlocal failed
        if not failed:
            failed = True
            raise StudyTaskError(
                "SIMULATED_INTERRUPTION", "simulated generation interruption"
            )
        return original(*args, **kwargs)

    runtime.tasks.succeed_task = fail_once
    arguments = {
        "audience": audience(),
        "project_id": project["projectId"],
        "expected_project_revision": planned["projectRevision"],
        "idempotency_key": "recover-completed-generation",
        "plan_set_handle": planned["planSetHandle"],
    }
    with pytest.raises(StudyRuntimeError) as interrupted:
        runtime.generate_cards(**arguments)
    assert interrupted.value.code == "SIMULATED_INTERRUPTION"

    runtime.tasks.succeed_task = original
    recovered = runtime.generate_cards(**arguments)
    assert recovered["artifactStage"] == "cards_ready"
    task = runtime.tasks.get_task(recovered["taskId"], audience())
    assert task["state"] == "succeeded"


def test_generation_recovers_after_task_success_before_project_commit(tmp_path) -> None:
    runtime, project, planned, _listed = planned_runtime(tmp_path)
    original = runtime.projects.commit_artifact_stage
    failed = False

    def fail_once(**kwargs):
        nonlocal failed
        if not failed:
            failed = True
            raise ProjectRegistryError(
                "SIMULATED_COMMIT_INTERRUPTION",
                "simulated generation commit interruption",
            )
        return original(**kwargs)

    runtime.projects.commit_artifact_stage = fail_once
    arguments = {
        "audience": audience(),
        "project_id": project["projectId"],
        "expected_project_revision": planned["projectRevision"],
        "idempotency_key": "recover-succeeded-generation",
        "plan_set_handle": planned["planSetHandle"],
    }
    with pytest.raises(StudyRuntimeError) as interrupted:
        runtime.generate_cards(**arguments)
    assert interrupted.value.code == "SIMULATED_COMMIT_INTERRUPTION"

    runtime.projects.commit_artifact_stage = original
    recovered = runtime.generate_cards(**arguments)
    assert recovered["artifactStage"] == "cards_ready"
    assert recovered["projectRevision"] == planned["projectRevision"] + 1


def test_generated_cards_are_reviewable_through_authenticated_pagination(
    tmp_path,
) -> None:
    runtime, project, _discovered, selected, _source = _selection_for_card_planning(
        tmp_path,
        FakeDiscoveryModel(proposal_count=2),
        candidate_count=2,
    )
    planned = runtime.plan_cards(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=selected["projectRevision"],
        idempotency_key="plan-two-reviewable-cards",
        selection_handle=selected["selectionHandle"],
    )
    generated = runtime.generate_cards(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=planned["projectRevision"],
        idempotency_key="generate-two-reviewable-cards",
        plan_set_handle=planned["planSetHandle"],
    )

    first = runtime.list_generated_cards(
        audience=audience(),
        project_artifact_handle=generated["projectArtifactHandle"],
        limit=1,
    )
    second = runtime.list_generated_cards(
        audience=audience(),
        project_artifact_handle=generated["projectArtifactHandle"],
        cursor=first["nextCursor"],
        limit=1,
    )

    assert first["totalCards"] == 2
    assert first["returnedCards"] == 1
    assert second["returnedCards"] == 1
    assert second["nextCursor"] is None
    assert first["items"][0]["cardId"] != second["items"][0]["cardId"]
    for item in [*first["items"], *second["items"]]:
        assert item["verification"]["state"] == "verified"
        assert item["mediaRoles"] == []
        assert item["front"]["prompt"]
        assert item["back"]["coreAnswer"] == "in good shape"
        encoded = json.dumps(item, ensure_ascii=False).casefold()
        for forbidden in (
            "artifactref",
            "registryauthref",
            "evidenceref",
            "inputfingerprint",
            "lesson.txt",
            "e:\\",
        ):
            assert forbidden not in encoded

    cursor = first["nextCursor"]
    replacement = "A" if cursor[-1] != "A" else "B"
    with pytest.raises(StudyRuntimeError) as tampered:
        runtime.list_generated_cards(
            audience=audience(),
            project_artifact_handle=generated["projectArtifactHandle"],
            cursor=cursor[:-1] + replacement,
            limit=1,
        )
    assert tampered.value.code == "CARD_CURSOR_INVALID"
