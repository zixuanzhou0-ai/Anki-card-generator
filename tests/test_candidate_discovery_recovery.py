from __future__ import annotations

import hashlib
import json
import time
from dataclasses import replace

import pytest

from card_service.study_runtime import StudyRuntimeError
from card_service.artifact_registry import canonical_json_bytes
from card_service.project_registry import ProjectRegistryError
from card_service.task_coordinator import StudyTaskError
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


def _strip_completion_binding(runtime, task_id: str) -> None:
    path = runtime.tasks._task_path(task_id)
    record = json.loads(path.read_text(encoding="utf-8"))
    record.pop("completionBinding", None)
    record.pop("authKeyId", None)
    record.pop("authTag", None)
    authenticated = runtime.tasks._authenticate("study.task.record.v1", record)
    path.write_bytes(canonical_json_bytes(authenticated))


def _force_recovery_index_rebuild(runtime) -> None:
    for path in (
        runtime.tasks._recovery_index_path,
        runtime.tasks._recovery_index_path.with_suffix(".json.bak"),
    ):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


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


def test_succeeded_discovery_with_pending_project_commit_resumes_without_model_replay(
    tmp_path, monkeypatch
) -> None:
    model = FakeDiscoveryModel()
    provider = FakeDiscoveryModelProvider(model)
    runtime, project, inspected, _source = environment(tmp_path, None, provider)
    original_commit = runtime.projects.commit_artifact_stage
    commit_attempts = 0

    def fail_first_commit(**kwargs):
        nonlocal commit_attempts
        commit_attempts += 1
        if commit_attempts == 1:
            raise ProjectRegistryError(
                "PROJECT_COMMIT_INTERRUPTED",
                "simulated crash after task success and before project commit",
            )
        return original_commit(**kwargs)

    monkeypatch.setattr(runtime.projects, "commit_artifact_stage", fail_first_commit)
    started = start_async_discovery(runtime, project, inspected, provider)
    _wait_until_inactive(runtime, started["taskId"])

    persisted = runtime.tasks.get_task(started["taskId"], audience())
    assert persisted["state"] == "succeeded"
    _strip_completion_binding(runtime, started["taskId"])
    _force_recovery_index_rebuild(runtime)
    pending = runtime.get_study_task(
        audience=audience(), task_id=started["taskId"]
    )
    assert pending["state"] == "interrupted"
    assert pending["error"]["code"] == "PROJECT_COMMIT_PENDING"
    listed = runtime.list_recoverable_study_tasks(audience=audience())
    assert [item["taskId"] for item in listed["tasks"]] == [started["taskId"]]
    assert listed["tasks"][0]["nextAction"] == "resume_task"

    recovery_provider = FakeDiscoveryModelProvider(FakeDiscoveryModel())
    resumed = runtime.resume_candidate_discovery_task(
        audience=audience(),
        task_id=started["taskId"],
        idempotency_key="resume-pending-project-commit",
        authorization=authorization(),
        model_provider=recovery_provider,
    )
    assert resumed["taskId"] == started["taskId"]
    assert resumed["artifactStage"] == "candidates_ready"
    assert recovery_provider.bound_task_ids == []
    assert model.proposal_calls == 1
    assert model.review_calls == 1
    assert commit_attempts == 2
    assert runtime.list_recoverable_study_tasks(audience=audience())["tasks"] == []


def test_legacy_committed_discovery_replay_does_not_require_completion_binding(
    tmp_path,
) -> None:
    model = FakeDiscoveryModel()
    runtime, project, inspected, _source = environment(tmp_path, model)
    first = runtime.start_candidate_discovery(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=inspected["projectRevision"],
        idempotency_key="legacy-committed-replay",
        inspection_handle=inspected["inspectionHandle"],
        candidate_budget={"target": 1, "maximum": 8},
        authorization=authorization(),
    )
    _strip_completion_binding(runtime, first["taskId"])

    repeated = runtime.start_candidate_discovery(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=inspected["projectRevision"],
        idempotency_key="legacy-committed-replay",
        inspection_handle=inspected["inspectionHandle"],
        candidate_budget={"target": 1, "maximum": 8},
        authorization=authorization(),
    )

    assert repeated["taskId"] == first["taskId"]
    assert repeated["artifactStage"] == "candidates_ready"
    assert model.proposal_calls == 1
    assert model.review_calls == 1


def test_invalid_pending_discovery_bundle_does_not_commit_or_close_lineage(
    tmp_path, monkeypatch
) -> None:
    model = FakeDiscoveryModel()
    provider = FakeDiscoveryModelProvider(model)
    runtime, project, inspected, _source = environment(tmp_path, None, provider)
    original_commit = runtime.projects.commit_artifact_stage

    def interrupted_commit(**_kwargs):
        raise ProjectRegistryError(
            "PROJECT_COMMIT_INTERRUPTED", "simulated pending commit"
        )

    monkeypatch.setattr(runtime.projects, "commit_artifact_stage", interrupted_commit)
    started = start_async_discovery(runtime, project, inspected, provider)
    _wait_until_inactive(runtime, started["taskId"])
    monkeypatch.setattr(runtime.projects, "commit_artifact_stage", original_commit)
    original_resolve = runtime.artifacts.resolve_with_ref

    def invalid_discovery(handle, binding):
        ref, envelope = original_resolve(handle, binding)
        if envelope.get("payloadSchema") == "study.discovery":
            envelope = json.loads(json.dumps(envelope))
            envelope["payload"]["counts"] = "invalid"
        return ref, envelope

    monkeypatch.setattr(runtime.artifacts, "resolve_with_ref", invalid_discovery)
    with pytest.raises(StudyRuntimeError) as invalid:
        runtime.finalize_pending_candidate_discovery_commit(
            audience=audience(), task_id=started["taskId"]
        )
    assert invalid.value.code == "DISCOVERY_RESULT_INVALID"
    current = runtime.get_project(project["projectId"], audience())
    assert current["workflow"]["artifactStage"] == "sources_ready"
    assert not runtime.tasks._lineage_closure_path(started["taskId"]).exists()


def test_legacy_binding_is_not_written_before_input_fingerprint_match(
    tmp_path, monkeypatch
) -> None:
    model = FakeDiscoveryModel()
    provider = FakeDiscoveryModelProvider(model)
    runtime, project, inspected, _source = environment(tmp_path, None, provider)

    def interrupted_commit(**_kwargs):
        raise ProjectRegistryError(
            "PROJECT_COMMIT_INTERRUPTED", "simulated pending commit"
        )

    monkeypatch.setattr(runtime.projects, "commit_artifact_stage", interrupted_commit)
    started = start_async_discovery(
        runtime, project, inspected, provider, key="legacy-input-mismatch"
    )
    _wait_until_inactive(runtime, started["taskId"])
    path = runtime.tasks._task_path(started["taskId"])
    record = json.loads(path.read_text(encoding="utf-8"))
    record.pop("completionBinding", None)
    record["task"]["inputFingerprint"] = "f" * 64
    record.pop("authKeyId", None)
    record.pop("authTag", None)
    path.write_bytes(
        canonical_json_bytes(
            runtime.tasks._authenticate("study.task.record.v1", record)
        )
    )

    with pytest.raises(StudyRuntimeError) as mismatch:
        runtime.start_candidate_discovery(
            audience=audience(),
            project_id=project["projectId"],
            expected_project_revision=inspected["projectRevision"],
            idempotency_key="legacy-input-mismatch",
            inspection_handle=inspected["inspectionHandle"],
            candidate_budget={"target": 1, "maximum": 8},
            authorization=authorization(),
            model_provider=provider,
        )
    assert mismatch.value.code == "TASK_INPUT_MISMATCH"
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert "completionBinding" not in persisted


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
    lease = runtime.tasks.acquire_worker_lease(
        started["taskId"],
        audience(),
        owner_id=runtime._worker_owner_id,
    )
    runtime.tasks.finish_cancellation(
        started["taskId"],
        audience(),
        expected_revision=task["taskRevision"],
        operation_id="test-finish-interruption",
        safe_checkpoint_proven=False,
        worker_owner_id=runtime._worker_owner_id,
        worker_fencing_token=lease["fencingToken"],
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
    lease = runtime.tasks.acquire_worker_lease(
        started["taskId"],
        audience(),
        owner_id=runtime._worker_owner_id,
    )
    runtime.tasks.release_worker_lease(
        started["taskId"],
        owner_id=runtime._worker_owner_id,
        fencing_token=lease["fencingToken"],
    )
    runtime._worker_startup_grace_seconds = 0
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
    lease = runtime.tasks.acquire_worker_lease(
        first["taskId"],
        audience(),
        owner_id=runtime._worker_owner_id,
    )
    runtime.tasks.release_worker_lease(
        first["taskId"],
        owner_id=runtime._worker_owner_id,
        fencing_token=lease["fencingToken"],
    )
    runtime._worker_startup_grace_seconds = 0

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


def test_persistent_worker_lease_prevents_false_orphan_interrupt(tmp_path) -> None:
    blocking = BlockingDiscoveryModel()
    provider = FakeDiscoveryModelProvider(blocking)
    runtime, project, inspected, _source = environment(tmp_path, None, provider)
    started = start_async_discovery(runtime, project, inspected, provider)
    assert blocking.proposal_started.wait(2)

    with runtime._active_discovery_lock:
        runtime._active_discoveries.pop(started["taskId"])
    try:
        listed = runtime.list_recoverable_study_tasks(audience=audience())
        assert listed["tasks"] == []
        persisted = runtime.get_study_task(
            audience=audience(), task_id=started["taskId"]
        )
        assert persisted["state"] == "running"
    finally:
        blocking.release_proposal.set()


def test_recoverable_listing_fills_limit_after_stale_tasks_are_filtered(
    tmp_path, monkeypatch
) -> None:
    invalid = FakeDiscoveryModel(invalid=True)
    provider = FakeDiscoveryModelProvider(invalid)
    runtime, project, inspected, _source = environment(tmp_path, None, provider)
    started = start_async_discovery(runtime, project, inspected, provider)
    failed = await_public_task(runtime, started["taskId"], expected_states={"failed"})
    stale_one = {**failed, "taskId": "task_stale_one"}
    stale_two = {**failed, "taskId": "task_stale_two"}
    valid = {**failed, "taskId": "task_valid_older"}
    pages = {
        None: {
            "tasks": [stale_one, stale_two],
            "positions": [
                {"taskId": stale_one["taskId"], "updatedAt": "2026-07-20T00:00:03Z"},
                {"taskId": stale_two["taskId"], "updatedAt": "2026-07-20T00:00:02Z"},
            ],
            "nextCursor": "second-page",
        },
        "second-page": {
            "tasks": [valid],
            "positions": [
                {"taskId": valid["taskId"], "updatedAt": "2026-07-20T00:00:01Z"}
            ],
            "nextCursor": None,
        },
    }

    def page(_audience, **kwargs):
        return pages[kwargs.get("cursor")]

    monkeypatch.setattr(runtime.tasks, "list_recoverable_task_page", page)
    stale_ids = {stale_one["taskId"], stale_two["taskId"]}

    def current_only(*, audience, task_id):
        if task_id in stale_ids:
            raise StudyRuntimeError(
                "TASK_RECOVERY_STALE", "Project state changed after this task"
            )
        assert task_id == valid["taskId"]
        return {}

    monkeypatch.setattr(runtime, "candidate_discovery_recovery_request", current_only)
    listed = runtime.list_recoverable_study_tasks(audience=audience(), limit=1)

    assert listed["returnedTasks"] == 1
    assert listed["tasks"][0]["taskId"] == valid["taskId"]


def test_external_stale_recovery_cursor_is_not_silently_restarted(
    tmp_path, monkeypatch
) -> None:
    runtime, _task_id = _failed_discovery(tmp_path)

    def stale_page(*_args, **_kwargs):
        raise StudyTaskError(
            "TASK_CURSOR_STALE", "Recovery index generation changed"
        )

    monkeypatch.setattr(runtime.tasks, "list_recoverable_task_page", stale_page)
    with pytest.raises(StudyRuntimeError) as stale:
        runtime.list_recoverable_study_tasks(
            audience=audience(), cursor="external-stale-cursor"
        )
    assert stale.value.code == "TASK_CURSOR_STALE"
