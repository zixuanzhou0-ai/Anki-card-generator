from __future__ import annotations

import json

import pytest

from card_service.project_registry import ProjectRegistryError
from card_service.study_runtime import StudyRuntimeError
from card_service.task_coordinator import StudyTaskError
from tests.test_candidate_discovery_runtime import (
    FORM,
    FakeDiscoveryModel,
    _selection_for_card_planning,
    audience,
)


def planned_runtime(tmp_path):
    runtime, project, _discovered, selected, _source = _selection_for_card_planning(
        tmp_path, FakeDiscoveryModel()
    )
    planned = runtime.plan_cards(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=selected["projectRevision"],
        idempotency_key="revision-plan-base",
        selection_handle=selected["selectionHandle"],
    )
    listed = runtime.list_card_plans(
        audience=audience(), plan_set_handle=planned["planSetHandle"]
    )
    return runtime, project, planned, listed


def test_agent_cue_edit_republishes_and_revalidates_current_graph(tmp_path) -> None:
    runtime, project, planned, listed = planned_runtime(tmp_path)
    result = runtime.edit_card_plan(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=planned["projectRevision"],
        idempotency_key="edit-safe-cue",
        plan_set_handle=planned["planSetHandle"],
        card_plan_handle=listed["items"][0]["cardPlanHandle"],
        operation={
            "kind": "edit_card_cue",
            "cue": {
                "kind": "text",
                "content": "Which expression describes being healthy or in a good condition?",
            },
        },
    )
    repeated = runtime.edit_card_plan(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=planned["projectRevision"],
        idempotency_key="edit-safe-cue",
        plan_set_handle=planned["planSetHandle"],
        card_plan_handle=listed["items"][0]["cardPlanHandle"],
        operation={
            "kind": "edit_card_cue",
            "cue": {
                "kind": "text",
                "content": "Which expression describes being healthy or in a good condition?",
            },
        },
    )

    assert result["projectRevision"] == planned["projectRevision"] + 1
    assert result["eligiblePlans"] == 1
    assert result["blockedPlans"] == 0
    for key in ("planSetHandle", "validationHandle", "cardPlanHandle"):
        first_ref, _ = runtime.artifacts.resolve_with_ref(result[key], audience())
        repeated_ref, _ = runtime.artifacts.resolve_with_ref(repeated[key], audience())
        assert repeated_ref == first_ref
    current = runtime.list_card_plans(
        audience=audience(), plan_set_handle=result["planSetHandle"]
    )
    assert current["items"][0]["cue"]["content"].startswith("Which expression")
    assert all(check["state"] == "passed" for check in current["items"][0]["checks"])
    plan = runtime.artifacts.resolve(result["cardPlanHandle"], audience())
    history = plan["payload"]["editHistory"][-1]
    assert history == {
        "actor": "agent",
        "taskId": result["taskId"],
        "operation": "edit_card_cue",
        "changedFields": ["card.cue"],
        "baseArtifactDigest": plan["parents"][0]["artifactDigest"],
    }
    serialized = json.dumps(plan, ensure_ascii=False)
    for forbidden in ("attestationDigest", "hostEventRef", "userGestureId"):
        assert forbidden not in serialized
    with pytest.raises(StudyRuntimeError) as stale:
        runtime.list_card_plans(
            audience=audience(), plan_set_handle=planned["planSetHandle"]
        )
    assert stale.value.code == "CARD_PLAN_SET_STALE"


def test_answer_edit_that_breaks_frozen_boundary_is_published_but_blocked(
    tmp_path,
) -> None:
    runtime, project, planned, listed = planned_runtime(tmp_path)
    result = runtime.edit_card_plan(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=planned["projectRevision"],
        idempotency_key="edit-invalid-answer",
        plan_set_handle=planned["planSetHandle"],
        card_plan_handle=listed["items"][0]["cardPlanHandle"],
        operation={
            "kind": "edit_card_answer",
            "expectedResponse": {
                "modality": "text",
                "coreAnswer": "healthy",
                "scoringPoints": ["healthy"],
                "acceptedVariants": [],
            },
        },
    )

    assert result["eligiblePlans"] == 0
    assert result["blockedPlans"] == 1
    current = runtime.list_card_plans(
        audience=audience(), plan_set_handle=result["planSetHandle"]
    )
    checks = {item["checkId"]: item["state"] for item in current["items"][0]["checks"]}
    assert checks["scoring_boundary"] == "failed"
    assert current["items"][0]["validationState"] == "blocked"


def test_semantic_feedback_edit_requires_review_instead_of_claiming_evidence(
    tmp_path,
) -> None:
    runtime, project, planned, listed = planned_runtime(tmp_path)
    result = runtime.edit_card_plan(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=planned["projectRevision"],
        idempotency_key="edit-feedback-review",
        plan_set_handle=planned["planSetHandle"],
        card_plan_handle=listed["items"][0]["cardPlanHandle"],
        operation={
            "kind": "edit_card_feedback",
            "feedback": {
                "explanation": "A new explanation not present in frozen evidence.",
                "examples": ["I stayed in good shape."],
                "nonexamples": [],
            },
        },
    )

    current = runtime.list_card_plans(
        audience=audience(), plan_set_handle=result["planSetHandle"]
    )
    checks = {item["checkId"]: item["state"] for item in current["items"][0]["checks"]}
    assert checks["evidence_coverage"] == "needs_review"
    assert result["nextAction"] == "review_card_plans"


def test_media_edit_fails_closed_until_a_media_generator_is_available(tmp_path) -> None:
    runtime, project, planned, listed = planned_runtime(tmp_path)
    result = runtime.edit_card_plan(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=planned["projectRevision"],
        idempotency_key="edit-media-unsupported",
        plan_set_handle=planned["planSetHandle"],
        card_plan_handle=listed["items"][0]["cardPlanHandle"],
        operation={
            "kind": "edit_media_policy",
            "mediaPolicy": {
                "sourceAudio": True,
                "sourceVideo": False,
                "sentenceTts": False,
                "expressionTts": False,
            },
        },
    )
    current = runtime.list_card_plans(
        audience=audience(), plan_set_handle=result["planSetHandle"]
    )
    checks = {item["checkId"]: item["state"] for item in current["items"][0]["checks"]}
    assert checks["media_generatability"] == "failed"


def test_standalone_validation_replays_all_checks_and_is_idempotent(tmp_path) -> None:
    runtime, project, planned, listed = planned_runtime(tmp_path)
    result = runtime.validate_card_plans(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=planned["projectRevision"],
        idempotency_key="revalidate-current-plans",
        plan_set_handle=planned["planSetHandle"],
    )
    repeated = runtime.validate_card_plans(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=planned["projectRevision"],
        idempotency_key="revalidate-current-plans",
        plan_set_handle=planned["planSetHandle"],
    )

    assert result["projectRevision"] == planned["projectRevision"] + 1
    assert result["eligiblePlans"] == 1
    assert "cardPlanHandle" not in result
    for key in ("planSetHandle", "validationHandle"):
        first_ref, _ = runtime.artifacts.resolve_with_ref(result[key], audience())
        repeated_ref, _ = runtime.artifacts.resolve_with_ref(repeated[key], audience())
        assert repeated_ref == first_ref
    current = runtime.list_card_plans(
        audience=audience(), plan_set_handle=result["planSetHandle"]
    )
    assert current["items"][0]["expectedResponse"]["coreAnswer"] == FORM
    assert len(current["items"][0]["checks"]) == 8


def test_card_plan_edit_rejects_cross_domain_operations_and_stale_revision(
    tmp_path,
) -> None:
    runtime, project, planned, listed = planned_runtime(tmp_path)
    with pytest.raises(StudyRuntimeError) as wrong_domain:
        runtime.edit_card_plan(
            audience=audience(),
            project_id=project["projectId"],
            expected_project_revision=planned["projectRevision"],
            idempotency_key="wrong-edit-domain",
            plan_set_handle=planned["planSetHandle"],
            card_plan_handle=listed["items"][0]["cardPlanHandle"],
            operation={"kind": "exclude"},
        )
    assert wrong_domain.value.code == "CARD_PLAN_EDIT_INVALID"

    with pytest.raises(StudyRuntimeError) as stale:
        runtime.validate_card_plans(
            audience=audience(),
            project_id=project["projectId"],
            expected_project_revision=planned["projectRevision"] - 1,
            idempotency_key="stale-validation",
            plan_set_handle=planned["planSetHandle"],
        )
    assert stale.value.code == "PROJECT_REVISION_CONFLICT"


def test_card_plan_edit_recovers_after_completed_work_unit_before_task_success(
    tmp_path,
) -> None:
    runtime, project, planned, listed = planned_runtime(tmp_path)
    original = runtime.tasks.succeed_task
    failed = False

    def fail_once(*args, **kwargs):
        nonlocal failed
        if not failed:
            failed = True
            raise StudyTaskError(
                "SIMULATED_INTERRUPTION", "simulated task interruption"
            )
        return original(*args, **kwargs)

    runtime.tasks.succeed_task = fail_once
    arguments = {
        "audience": audience(),
        "project_id": project["projectId"],
        "expected_project_revision": planned["projectRevision"],
        "idempotency_key": "recover-completed-edit",
        "plan_set_handle": planned["planSetHandle"],
        "card_plan_handle": listed["items"][0]["cardPlanHandle"],
        "operation": {
            "kind": "edit_card_cue",
            "cue": {"kind": "text", "content": "Which healthy-state expression fits?"},
        },
    }
    with pytest.raises(StudyRuntimeError) as interrupted:
        runtime.edit_card_plan(**arguments)
    assert interrupted.value.code == "SIMULATED_INTERRUPTION"

    runtime.tasks.succeed_task = original
    recovered = runtime.edit_card_plan(**arguments)
    assert recovered["eligiblePlans"] == 1
    task = runtime.tasks.get_task(recovered["taskId"], audience())
    assert task["state"] == "succeeded"


def test_old_idempotent_edit_cannot_revive_after_a_new_plan_revision(tmp_path) -> None:
    runtime, project, planned, listed = planned_runtime(tmp_path)
    first_arguments = {
        "audience": audience(),
        "project_id": project["projectId"],
        "expected_project_revision": planned["projectRevision"],
        "idempotency_key": "first-edit-that-will-be-stale",
        "plan_set_handle": planned["planSetHandle"],
        "card_plan_handle": listed["items"][0]["cardPlanHandle"],
        "operation": {
            "kind": "edit_card_cue",
            "cue": {
                "kind": "text",
                "content": "Which expression describes good health?",
            },
        },
    }
    first = runtime.edit_card_plan(**first_arguments)
    current = runtime.list_card_plans(
        audience=audience(), plan_set_handle=first["planSetHandle"]
    )
    second = runtime.edit_card_plan(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=first["projectRevision"],
        idempotency_key="second-edit-makes-first-stale",
        plan_set_handle=first["planSetHandle"],
        card_plan_handle=current["items"][0]["cardPlanHandle"],
        operation={
            "kind": "edit_media_policy",
            "mediaPolicy": {
                "sourceAudio": False,
                "sourceVideo": False,
                "sentenceTts": False,
                "expressionTts": False,
            },
        },
    )
    assert second["projectRevision"] == first["projectRevision"] + 1
    with pytest.raises(StudyRuntimeError) as stale:
        runtime.edit_card_plan(**first_arguments)
    assert stale.value.code == "CARD_PLAN_NOT_CURRENT"


def test_card_plan_edit_recovers_after_task_success_before_project_commit(
    tmp_path,
) -> None:
    runtime, project, planned, listed = planned_runtime(tmp_path)
    original = runtime.projects.commit_artifact_stage
    failed = False

    def fail_once(**kwargs):
        nonlocal failed
        if not failed:
            failed = True
            raise ProjectRegistryError(
                "SIMULATED_COMMIT_INTERRUPTION", "simulated project commit interruption"
            )
        return original(**kwargs)

    runtime.projects.commit_artifact_stage = fail_once
    arguments = {
        "audience": audience(),
        "project_id": project["projectId"],
        "expected_project_revision": planned["projectRevision"],
        "idempotency_key": "recover-succeeded-edit",
        "plan_set_handle": planned["planSetHandle"],
        "card_plan_handle": listed["items"][0]["cardPlanHandle"],
        "operation": {
            "kind": "edit_card_cue",
            "cue": {"kind": "text", "content": "Which good-condition expression fits?"},
        },
    }
    with pytest.raises(StudyRuntimeError) as interrupted:
        runtime.edit_card_plan(**arguments)
    assert interrupted.value.code == "SIMULATED_COMMIT_INTERRUPTION"

    runtime.projects.commit_artifact_stage = original
    recovered = runtime.edit_card_plan(**arguments)
    assert recovered["eligiblePlans"] == 1
    assert recovered["projectRevision"] == planned["projectRevision"] + 1
