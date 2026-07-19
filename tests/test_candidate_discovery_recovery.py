from __future__ import annotations

import hashlib
import json
import time
from dataclasses import replace

import pytest

from card_service.study_runtime import StudyRuntimeError
from card_service.artifact_registry import canonical_json_bytes
from tests.test_candidate_discovery_runtime import (
    BlockingDiscoveryModel,
    FakeDiscoveryModel,
    FakeDiscoveryModelProvider,
    audience,
    digest,
    authorization,
    await_public_task,
    environment,
    start_async_discovery,
)


def _recovery_authorization(
    runtime,
    task_id: str,
    *,
    audience_binding=None,
    base=None,
):
    binding = audience_binding or audience()
    request = runtime.candidate_discovery_recovery_request(
        audience=binding, task_id=task_id
    )
    exact_scope_digest = hashlib.sha256(
        canonical_json_bytes(
            {
                "schema": "study.candidate-discovery.exact-scope",
                "schemaVersion": 1,
                "audience": binding.audience(runtime.service_instance_id),
                "projectId": request["projectId"],
                "projectRevision": request["expectedProjectRevision"],
                "inspectionHandle": request["inspectionHandle"],
                "candidateBudget": request["candidateBudget"],
            }
        )
    ).hexdigest()
    return request, replace(
        base or authorization(),
        exact_scope_digest=exact_scope_digest,
    )


def _resume(
    runtime,
    task_id: str,
    provider: FakeDiscoveryModelProvider,
    *,
    key: str,
    audience_binding=None,
    base_authorization=None,
):
    binding = audience_binding or audience()
    existing = runtime.get_existing_recovery_successor(
        audience=binding,
        task_id=task_id,
        idempotency_key=key,
    )
    if existing is not None:
        return existing
    recovery_request, recovery_auth = _recovery_authorization(
        runtime,
        task_id,
        audience_binding=binding,
        base=base_authorization,
    )
    return runtime.resume_candidate_discovery_task(
        audience=binding,
        task_id=task_id,
        idempotency_key=key,
        authorization=recovery_auth,
        model_provider=provider,
        recovery_request=recovery_request,
    )


def _wait_until_inactive(runtime, task_id: str, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with runtime._active_discovery_lock:
            if task_id not in runtime._active_discoveries:
                return
        time.sleep(0.02)
    raise AssertionError(f"discovery task {task_id} remained active")


def test_failed_discovery_lists_and_resumes_as_idempotent_successor(tmp_path) -> None:
    invalid = FakeDiscoveryModel(invalid=True)
    first_provider = FakeDiscoveryModelProvider(invalid)
    runtime, project, inspected, _source = environment(tmp_path, None, first_provider)

    started = start_async_discovery(runtime, project, inspected, first_provider)
    failed = await_public_task(runtime, started["taskId"], expected_states={"failed"})
    assert failed["nextAction"] == "resume_task"

    listed = runtime.list_recoverable_study_tasks(audience=audience())
    assert listed["returnedTasks"] == 1
    assert listed["tasks"][0]["taskId"] == started["taskId"]
    encoded = json.dumps(listed, ensure_ascii=False, sort_keys=True)
    for forbidden in (
        "inputFingerprint",
        "workReuseDigest",
        "authorizationRecordDigest",
        "profileRef",
        "configurationFingerprint",
        "credentialRevision",
        "artifactRefs",
        "blobRef",
    ):
        assert forbidden not in encoded

    valid = FakeDiscoveryModel()
    successor_provider = FakeDiscoveryModelProvider(valid)
    resumed = _resume(
        runtime, started["taskId"], successor_provider, key="resume-failed-1"
    )
    completed = await_public_task(
        runtime, resumed["taskId"], expected_states={"succeeded"}
    )

    assert completed["result"]["artifactStage"] == "candidates_ready"
    successor = runtime.tasks.get_task(resumed["taskId"], audience())
    assert successor["predecessorTaskId"] == started["taskId"]
    assert valid.proposal_calls == 1
    assert valid.review_calls == 1

    repeated = _resume(
        runtime, started["taskId"], successor_provider, key="resume-failed-1"
    )
    assert repeated["taskId"] == completed["taskId"]
    assert repeated["result"]["candidateCount"] == completed["result"]["candidateCount"]
    assert valid.proposal_calls == 1
    assert valid.review_calls == 1


def test_cancelled_discovery_can_resume_without_reusing_the_terminal_task(
    tmp_path,
) -> None:
    blocking = BlockingDiscoveryModel()
    provider = FakeDiscoveryModelProvider(blocking)
    runtime, project, inspected, _source = environment(tmp_path, None, provider)
    started = start_async_discovery(runtime, project, inspected, provider)
    assert blocking.proposal_started.wait(2)

    cancelling = runtime.cancel_study_task(
        audience=audience(), task_id=started["taskId"]
    )
    assert cancelling["state"] == "cancelling"
    blocking.release_proposal.set()
    cancelled = await_public_task(
        runtime, started["taskId"], expected_states={"cancelled"}
    )
    assert cancelled["nextAction"] == "resume_task"

    valid = FakeDiscoveryModel()
    resumed = _resume(
        runtime,
        started["taskId"],
        FakeDiscoveryModelProvider(valid),
        key="resume-cancelled-1",
    )
    completed = await_public_task(
        runtime, resumed["taskId"], expected_states={"succeeded"}
    )
    assert completed["result"]["candidateCount"] == 1
    assert resumed["taskId"] != started["taskId"]


def test_interrupted_discovery_can_resume_from_a_successor(tmp_path) -> None:
    blocking = BlockingDiscoveryModel()
    provider = FakeDiscoveryModelProvider(blocking)
    runtime, project, inspected, _source = environment(tmp_path, None, provider)
    started = start_async_discovery(runtime, project, inspected, provider)
    assert blocking.proposal_started.wait(2)

    task = runtime.tasks.get_task(started["taskId"], audience())
    task = runtime.tasks.request_cancel(
        started["taskId"],
        audience(),
        expected_revision=task["taskRevision"],
        operation_id="test-request-interruption",
    )
    runtime.tasks.finish_cancellation(
        started["taskId"],
        audience(),
        expected_revision=task["taskRevision"],
        operation_id="test-finish-interruption",
        safe_checkpoint_proven=False,
    )
    blocking.release_proposal.set()
    _wait_until_inactive(runtime, started["taskId"])
    interrupted = runtime.get_study_task(audience=audience(), task_id=started["taskId"])
    assert interrupted["state"] == "interrupted"
    assert interrupted["nextAction"] == "resume_task"

    valid = FakeDiscoveryModel()
    resumed = _resume(
        runtime,
        started["taskId"],
        FakeDiscoveryModelProvider(valid),
        key="resume-interrupted-1",
    )
    completed = await_public_task(
        runtime, resumed["taskId"], expected_states={"succeeded"}
    )
    assert completed["result"]["candidateCount"] == 1


def test_non_discovery_recovery_fails_closed_before_model_binding(
    tmp_path, monkeypatch
) -> None:
    model = FakeDiscoveryModel()
    provider = FakeDiscoveryModelProvider(model)
    runtime, _project, _inspected, _source = environment(tmp_path, None, provider)

    monkeypatch.setattr(
        runtime.tasks,
        "get_recovery_record",
        lambda *_args, **_kwargs: {
            "task": {
                "intent": "export_apkg",
                "state": "failed",
                "resumability": "restart_phase",
            },
            "workReuseManifest": {"actionId": "export_apkg"},
            "authorizationBinding": {"bindings": []},
        },
    )

    with pytest.raises(StudyRuntimeError) as caught:
        runtime.candidate_discovery_recovery_request(
            audience=audience(), task_id="task_export_failed"
        )
    assert caught.value.code == "TASK_RESUME_UNSUPPORTED"
    assert provider.bound_task_ids == []


def _failed_discovery(tmp_path):
    invalid = FakeDiscoveryModel(invalid=True)
    provider = FakeDiscoveryModelProvider(invalid)
    runtime, project, inspected, _source = environment(tmp_path, None, provider)
    started = start_async_discovery(runtime, project, inspected, provider)
    await_public_task(runtime, started["taskId"], expected_states={"failed"})
    return runtime, started["taskId"]


def test_recovery_accepts_fresh_authorization_from_a_new_session(tmp_path) -> None:
    runtime, task_id = _failed_discovery(tmp_path)
    new_session = audience(session_id="session-2")
    fresh_authorization = replace(
        authorization(suffix="session-2"),
        cost_budget_digest=authorization().cost_budget_digest,
    )
    valid = FakeDiscoveryModel()

    resumed = _resume(
        runtime,
        task_id,
        FakeDiscoveryModelProvider(valid),
        key="resume-new-session",
        audience_binding=new_session,
        base_authorization=fresh_authorization,
    )
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        completed = runtime.get_study_task(
            audience=new_session, task_id=resumed["taskId"]
        )
        if completed["state"] == "succeeded":
            break
        time.sleep(0.02)
    else:
        raise AssertionError("cross-session recovery did not succeed")

    assert completed["result"]["candidateCount"] == 1
    assert valid.proposal_calls == 1
    assert valid.review_calls == 1


def test_recovery_rejects_tampered_scope_budget_and_inspection(tmp_path) -> None:
    runtime, task_id = _failed_discovery(tmp_path)
    request, valid_authorization = _recovery_authorization(runtime, task_id)
    provider = FakeDiscoveryModelProvider(FakeDiscoveryModel())

    with pytest.raises(StudyRuntimeError) as scope_error:
        runtime.resume_candidate_discovery_task(
            audience=audience(),
            task_id=task_id,
            idempotency_key="resume-bad-scope",
            authorization=replace(
                valid_authorization,
                exact_scope_digest=digest("tampered-recovery-scope"),
            ),
            model_provider=provider,
            recovery_request=request,
        )
    assert scope_error.value.code == "DISCOVERY_RECOVERY_AUTH_SCOPE_MISMATCH"

    expanded_budget = dict(request)
    expanded_budget["candidateBudget"] = dict(request["candidateBudget"])
    expanded_budget["candidateBudget"]["maximum"] += 1
    with pytest.raises(StudyRuntimeError) as budget_error:
        runtime.resume_candidate_discovery_task(
            audience=audience(),
            task_id=task_id,
            idempotency_key="resume-expanded-budget",
            authorization=valid_authorization,
            model_provider=provider,
            recovery_request=expanded_budget,
        )
    assert budget_error.value.code == "DISCOVERY_RECOVERY_AUTH_SCOPE_MISMATCH"

    changed_inspection = dict(request)
    changed_inspection["inspectionHandle"] = "not-an-artifact-handle"
    with pytest.raises(StudyRuntimeError) as inspection_error:
        runtime.resume_candidate_discovery_task(
            audience=audience(),
            task_id=task_id,
            idempotency_key="resume-changed-inspection",
            authorization=valid_authorization,
            model_provider=provider,
            recovery_request=changed_inspection,
        )
    assert inspection_error.value.code in {
        "ARTIFACT_HANDLE_INVALID",
        "ARTIFACT_HANDLE_AUTH_INVALID",
    }

    with pytest.raises(StudyRuntimeError) as cost_error:
        runtime.resume_candidate_discovery_task(
            audience=audience(),
            task_id=task_id,
            idempotency_key="resume-expanded-cost",
            authorization=replace(
                valid_authorization,
                cost_budget_digest=digest("expanded-remote-cost-budget"),
            ),
            model_provider=provider,
            recovery_request=request,
        )
    assert cost_error.value.code == "DISCOVERY_RECOVERY_BUDGET_CHANGED"
    assert provider.bound_task_ids == []

def test_listing_marks_an_orphaned_active_discovery_interrupted(tmp_path) -> None:
    blocking = BlockingDiscoveryModel()
    provider = FakeDiscoveryModelProvider(blocking)
    runtime, project, inspected, _source = environment(tmp_path, None, provider)
    started = start_async_discovery(runtime, project, inspected, provider)
    assert blocking.proposal_started.wait(2)

    with runtime._active_discovery_lock:
        runtime._active_discoveries.pop(started["taskId"])
    try:
        listed = runtime.list_recoverable_study_tasks(audience=audience())
        orphan = next(
            item for item in listed["tasks"] if item["taskId"] == started["taskId"]
        )
        assert orphan["state"] == "interrupted"
        assert orphan["nextAction"] == "resume_task"
        persisted = runtime.get_study_task(
            audience=audience(), task_id=started["taskId"]
        )
        assert persisted["state"] == "interrupted"
    finally:
        blocking.release_proposal.set()

def test_different_recovery_keys_cannot_run_parallel_successors(tmp_path) -> None:
    runtime, task_id = _failed_discovery(tmp_path)
    blocking = BlockingDiscoveryModel()
    first = _resume(
        runtime,
        task_id,
        FakeDiscoveryModelProvider(blocking),
        key="resume-active-first",
    )
    assert blocking.proposal_started.wait(2)

    second_provider = FakeDiscoveryModelProvider(FakeDiscoveryModel())
    try:
        with pytest.raises(StudyRuntimeError) as conflict:
            _resume(
                runtime,
                task_id,
                second_provider,
                key="resume-active-second",
            )
        assert conflict.value.code == "TASK_SUCCESSOR_ACTIVE"
        assert second_provider.bound_task_ids == []
    finally:
        blocking.release_proposal.set()

    completed = await_public_task(
        runtime, first["taskId"], expected_states={"succeeded"}
    )
    assert completed["result"]["candidateCount"] == 1

def test_direct_resume_replaces_an_orphaned_active_successor(tmp_path) -> None:
    runtime, task_id = _failed_discovery(tmp_path)
    blocking = BlockingDiscoveryModel()
    first = _resume(
        runtime,
        task_id,
        FakeDiscoveryModelProvider(blocking),
        key="resume-orphaned-successor",
    )
    assert blocking.proposal_started.wait(2)

    with runtime._active_discovery_lock:
        runtime._active_discoveries.pop(first["taskId"])

    valid = FakeDiscoveryModel()
    try:
        resumed = _resume(
            runtime,
            task_id,
            FakeDiscoveryModelProvider(valid),
            key="resume-orphaned-successor",
        )
        assert resumed["taskId"] != first["taskId"]
        completed = await_public_task(
            runtime, resumed["taskId"], expected_states={"succeeded"}
        )
        assert completed["result"]["candidateCount"] == 1
    finally:
        blocking.release_proposal.set()

    persisted = runtime.get_study_task(
        audience=audience(), task_id=first["taskId"]
    )
    assert persisted["state"] == "interrupted"
