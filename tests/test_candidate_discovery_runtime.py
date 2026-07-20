from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any, Mapping

import pytest

from card_service.artifact_registry import ArtifactAudienceBinding
from card_service.candidate_discovery import CandidateDiscoveryModelIdentity
from card_service.candidate_discovery_runtime import (
    CandidateDiscoveryAuthorization,
    CandidateDiscoveryRuntime,
)
from card_service.credentials import CredentialStore, InMemoryCredentialBackend
from card_service.resource_runtime import ServiceResourceRuntime
from card_service.study_runtime import StudyRuntime, StudyRuntimeError


OWNER = hashlib.sha256(b"candidate-runtime-owner").hexdigest()
FORM = "in good shape"
SOURCE_TEXT = (
    "Use in good shape when something remains in good condition. "
    "Staying in good shape takes work."
)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def audience(**changes: str) -> ArtifactAudienceBinding:
    values = {
        "owner_digest": OWNER,
        "host_id": "codex-desktop",
        "plugin_id": "speakright.study",
        "session_id": "session-1",
    }
    values.update(changes)
    return ArtifactAudienceBinding(**values)


class FakeDiscoveryModel:
    def __init__(self, *, invalid: bool = False, proposal_count: int = 1) -> None:
        self.identity = CandidateDiscoveryModelIdentity(
            profile_ref="model.primary",
            configuration_fingerprint=digest("model-configuration-v1"),
            credential_revision=7,
            implementation_version="fake-provider-v1",
        )
        self.invalid = invalid
        self.proposal_count = proposal_count
        self.proposal_calls = 0
        self.review_calls = 0

    def propose(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        self.proposal_calls += 1
        window = request["sources"][0]["windows"][0]
        start = window["start"] + window["text"].index(FORM)
        item = {
            "representationId": request["sources"][0]["representationId"],
            "language": "en",
            "form": FORM,
            "formType": "phrase",
            "meaningOrFunction": "healthy or in a good condition",
            "route": "production",
            "spans": [
                {"nodeId": window["nodeId"], "start": start, "end": start + len(FORM)}
            ],
        }
        if self.invalid:
            item["eligibility"] = "recommended"
        proposals = []
        for index in range(self.proposal_count):
            proposal = dict(item)
            if index:
                proposal["meaningOrFunction"] = f"meaning {index}"
            proposals.append(proposal)
        return {
            "schema": "study.candidate-discovery.proposals",
            "schemaVersion": 1,
            "proposals": proposals,
        }

    def review(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        self.review_calls += 1
        return {
            "schema": "study.candidate-discovery.reviews",
            "schemaVersion": 1,
            "reviews": [
                {
                    "reviewKey": item["reviewKey"],
                    "semanticEvidence": "verified",
                    "conflict": "clear",
                    "learnerFit": "new",
                    "reasonCodes": ["SEMANTIC_ALIGNMENT_VERIFIED"],
                }
                for item in request["proposals"]
            ],
        }


class FakeDiscoveryModelProvider:
    def __init__(
        self,
        model: FakeDiscoveryModel,
        *,
        bound_model: FakeDiscoveryModel | None = None,
    ) -> None:
        self.identity = model.identity
        self.model = bound_model or model
        self.bound_task_ids: list[str] = []

    def bind(self, task_id: str) -> FakeDiscoveryModel:
        self.bound_task_ids.append(task_id)
        return self.model


class BlockingDiscoveryModel(FakeDiscoveryModel):
    def __init__(self) -> None:
        super().__init__()
        self.proposal_started = threading.Event()
        self.release_proposal = threading.Event()

    def propose(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        self.proposal_started.set()
        if not self.release_proposal.wait(10):
            raise RuntimeError("test proposal was never released")
        return super().propose(request)


def authorization(*, suffix: str = "v1") -> CandidateDiscoveryAuthorization:
    return CandidateDiscoveryAuthorization(
        operation_intent_digest=digest("operation-intent-" + suffix),
        authorization_record_digest=digest("authorization-record-" + suffix),
        constraints_digest=digest("constraints-" + suffix),
        exact_scope_digest=digest("scope-" + suffix),
        expected_revocation_epoch=0,
        cost_budget_digest=digest("cost-budget-" + suffix),
        egress_manifest_digest=digest("egress-" + suffix),
    )


def environment(
    tmp_path: Path,
    model: FakeDiscoveryModel | None,
    provider: FakeDiscoveryModelProvider | None = None,
    *,
    routes: list[str] | None = None,
):
    backend = InMemoryCredentialBackend()
    credentials = (tmp_path / "credentials").resolve()
    resources = ServiceResourceRuntime(
        state_dir=(tmp_path / "resources").resolve(),
        credential_store=CredentialStore(state_dir=credentials, backend=backend),
        gesture_verifier=lambda *_args: True,
        harden_callback=None,
        require_hardening=False,
    )
    runtime = StudyRuntime(
        state_dir=(tmp_path / "study").resolve(),
        credential_store=CredentialStore(state_dir=credentials, backend=backend),
        resource_runtime=resources,
        candidate_discovery_model=model,
        candidate_discovery_model_provider=provider,
    )
    project = runtime.create_project(
        audience=audience(),
        idempotency_key="project-1",
        learning_contract={
            "purpose": "Learn reusable spoken English",
            "targetBehavior": "Recall and use the expression",
            "routes": routes or ["production", "reading_recognition"],
            "maxNewCards": 20,
            "learnerLevel": "B1",
        },
    )
    source = (tmp_path / "lesson.txt").resolve()
    source.write_text(SOURCE_TEXT, encoding="utf-8")
    grant = resources.issue_local_grant(
        audience=audience(),
        grant_request_id="source-grant-1",
        raw_path=source,
        kind="file",
        constraints={"actions": ["read"], "maxBytes": source.stat().st_size},
        attestation_ref="gesture-source-grant-1",
    )
    input_ref = {
        "schemaVersion": 1,
        "kind": "file",
        "fileResourceRef": grant["resourceRef"],
        "displayName": grant["displayName"],
        "resourceRevisionDigest": grant["resourceRevisionDigest"],
        "constraints": grant["constraints"],
        "expiresAt": grant["expiresAt"],
    }
    registered = runtime.register_inputs(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=1,
        idempotency_key="register-1",
        input_refs=[input_ref],
    )
    inspected = runtime.start_source_inspection(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=2,
        idempotency_key="inspect-1",
        source_handles=[registered["sources"][0]["sourceHandle"]],
    )
    return runtime, project, inspected, source


def discover(
    runtime: StudyRuntime,
    project: Mapping[str, Any],
    inspected: Mapping[str, Any],
    *,
    key: str = "discover-1",
    auth: CandidateDiscoveryAuthorization | None = None,
    maximum: int = 8,
):
    return runtime.start_candidate_discovery(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=inspected["projectRevision"],
        idempotency_key=key,
        inspection_handle=inspected["inspectionHandle"],
        candidate_budget={"target": 1, "maximum": maximum},
        authorization=auth or authorization(),
    )


def start_async_discovery(
    runtime: StudyRuntime,
    project: Mapping[str, Any],
    inspected: Mapping[str, Any],
    provider: FakeDiscoveryModelProvider,
    *,
    key: str = "discover-async-1",
) -> dict[str, Any]:
    return runtime.start_candidate_discovery_task(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=inspected["projectRevision"],
        idempotency_key=key,
        inspection_handle=inspected["inspectionHandle"],
        candidate_budget={"target": 1, "maximum": 8},
        authorization=authorization(),
        model_provider=provider,
    )


def await_public_task(
    runtime: StudyRuntime,
    task_id: str,
    *,
    expected_states: set[str],
    timeout: float = 10.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        task = runtime.get_study_task(audience=audience(), task_id=task_id)
        if task["state"] in expected_states:
            return task
        time.sleep(0.02)
    raise AssertionError(f"task {task_id} did not reach {sorted(expected_states)}")

def task_record(runtime: StudyRuntime, task_id: str) -> dict[str, Any]:
    for path in (runtime.root / "tasks" / "tasks").rglob("*.json"):
        value = json.loads(path.read_text(encoding="utf-8"))
        if (
            value.get("schema") == "study.task.record"
            and value["task"]["taskId"] == task_id
        ):
            return value
    raise AssertionError("task record not found")


def test_public_discovery_start_returns_before_model_completion_and_polls_success(
    tmp_path: Path,
) -> None:
    model = BlockingDiscoveryModel()
    provider = FakeDiscoveryModelProvider(model)
    runtime, project, inspected, _source = environment(tmp_path, None, provider)

    started_at = time.monotonic()
    started = start_async_discovery(runtime, project, inspected, provider)
    elapsed = time.monotonic() - started_at

    assert elapsed < 2.0
    assert started["state"] in {"queued", "running"}
    assert started["intent"] == "discover_candidates"
    assert model.proposal_started.wait(2)
    serialized = json.dumps(started, ensure_ascii=False, sort_keys=True)
    for forbidden in (
        "inputFingerprint",
        "authorization",
        "profileRef",
        "configurationFingerprint",
        "credentialRevision",
    ):
        assert forbidden not in serialized

    model.release_proposal.set()
    completed = await_public_task(
        runtime,
        started["taskId"],
        expected_states={"succeeded"},
    )

    assert completed["progress"]["overallPercent"] == 100
    assert completed["result"]["artifactStage"] == "candidates_ready"
    assert completed["result"]["candidateCount"] == 1
    assert model.proposal_calls == 1
    assert model.review_calls == 1


def test_duplicate_public_discovery_start_reuses_active_task_without_model_replay(
    tmp_path: Path,
) -> None:
    model = BlockingDiscoveryModel()
    provider = FakeDiscoveryModelProvider(model)
    runtime, project, inspected, _source = environment(tmp_path, None, provider)

    first = start_async_discovery(runtime, project, inspected, provider)
    assert model.proposal_started.wait(2)
    second = start_async_discovery(runtime, project, inspected, provider)

    assert second["taskId"] == first["taskId"]
    assert len(provider.bound_task_ids) == 1
    model.release_proposal.set()
    await_public_task(runtime, first["taskId"], expected_states={"succeeded"})
    assert model.proposal_calls == 1
    assert model.review_calls == 1


def test_synchronous_discovery_lease_blocks_parallel_model_replay(
    tmp_path: Path,
) -> None:
    model = BlockingDiscoveryModel()
    provider = FakeDiscoveryModelProvider(model)
    runtime, project, inspected, _source = environment(tmp_path, None, provider)
    holder: dict[str, Any] = {}

    def run_first() -> None:
        try:
            holder["result"] = discover(runtime, project, inspected)
        except Exception as error:  # pragma: no cover - assertion below reports it
            holder["error"] = error

    thread = threading.Thread(target=run_first, daemon=True)
    thread.start()
    assert model.proposal_started.wait(2)
    with pytest.raises(StudyRuntimeError) as duplicate:
        discover(runtime, project, inspected)
    assert duplicate.value.code == "DISCOVERY_ALREADY_RUNNING"

    model.release_proposal.set()
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert "error" not in holder
    assert holder["result"]["artifactStage"] == "candidates_ready"
    assert model.proposal_calls == 1
    assert model.review_calls == 1


def test_terminal_race_reloads_task_before_any_second_model_call(
    tmp_path: Path,
) -> None:
    outer_model = FakeDiscoveryModel()
    outer_provider = FakeDiscoveryModelProvider(outer_model)
    winner_model = FakeDiscoveryModel()
    winner_provider = FakeDiscoveryModelProvider(winner_model)
    runtime, project, inspected, _source = environment(
        tmp_path, None, winner_provider
    )
    outer = CandidateDiscoveryRuntime(
        service_instance_id=runtime.service_instance_id,
        artifacts=runtime.artifacts,
        projects=runtime.projects,
        tasks=runtime.tasks,
        model_provider=outer_provider,
    )

    def winner_finishes(_task_id: str) -> bool:
        completed = runtime.start_candidate_discovery(
            audience=audience(),
            project_id=project["projectId"],
            expected_project_revision=inspected["projectRevision"],
            idempotency_key="terminal-race",
            inspection_handle=inspected["inspectionHandle"],
            candidate_budget={"target": 1, "maximum": 8},
            authorization=authorization(),
            model_provider=winner_provider,
        )
        assert completed["artifactStage"] == "candidates_ready"
        return True

    result = outer.start_discovery(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=inspected["projectRevision"],
        idempotency_key="terminal-race",
        inspection_handle=inspected["inspectionHandle"],
        candidate_budget={"target": 1, "maximum": 8},
        authorization=authorization(),
        task_ready_callback=winner_finishes,
    )

    assert result["artifactStage"] == "candidates_ready"
    assert outer_provider.bound_task_ids == []
    assert outer_model.proposal_calls == 0
    assert outer_model.review_calls == 0
    assert winner_model.proposal_calls == 1
    assert winner_model.review_calls == 1


def test_public_discovery_cancel_waits_for_remote_call_then_finishes_safely(
    tmp_path: Path,
) -> None:
    model = BlockingDiscoveryModel()
    provider = FakeDiscoveryModelProvider(model)
    runtime, project, inspected, _source = environment(tmp_path, None, provider)

    started = start_async_discovery(runtime, project, inspected, provider)
    assert model.proposal_started.wait(2)
    cancelling = runtime.cancel_study_task(
        audience=audience(),
        task_id=started["taskId"],
    )

    assert cancelling["state"] == "cancelling"
    model.release_proposal.set()
    cancelled = await_public_task(
        runtime,
        started["taskId"],
        expected_states={"cancelled"},
    )

    assert cancelled["cancellable"] is False
    assert model.proposal_calls == 1
    assert model.review_calls == 0
    current = runtime.get_project(project["projectId"], audience())
    assert current["workflow"]["artifactStage"] == "sources_ready"

def test_discovery_runtime_commits_candidates_and_binds_authorized_model_identity(
    tmp_path: Path,
) -> None:
    model = FakeDiscoveryModel()
    runtime, project, inspected, source = environment(tmp_path, model)

    result = discover(runtime, project, inspected)

    assert result["projectRevision"] == 4
    assert result["artifactStage"] == "candidates_ready"
    assert result["candidateCount"] == 1
    assert result["counts"]["recommended"] == 1
    assert result["nextAction"] == "review_candidates"
    assert model.proposal_calls == 1
    assert model.review_calls == 1
    current = runtime.get_project(project["projectId"], audience())
    assert current["workflow"] == {
        **current["workflow"],
        "productStep": "select",
        "artifactStage": "candidates_ready",
        "operationState": "succeeded",
        "primaryActionId": "review_candidates",
    }
    task = runtime.tasks.get_task(result["taskId"], audience())
    assert task["state"] == "succeeded"
    assert task["progress"]["overallPercent"] == 100
    record = task_record(runtime, result["taskId"])
    assert (
        record["taskInputManifest"]["operationIntentDigest"]
        == authorization().operation_intent_digest
    )
    assert (
        record["taskInputManifest"]["costBudgetDigest"]
        == authorization().cost_budget_digest
    )
    assert record["taskInputManifest"]["serviceBindings"] == [
        {
            "capability": "model",
            "profileRef": "model.primary",
            "configurationFingerprint": model.identity.configuration_fingerprint,
            "credentialRevision": 7,
            "egressManifestDigest": authorization().egress_manifest_digest,
        }
    ]
    assert record["authorizationBinding"]["bindings"][0]["action"] == "call_model"
    serialized = json.dumps(record, ensure_ascii=False, sort_keys=True)
    assert SOURCE_TEXT not in serialized
    assert str(source) not in serialized
    assert "api_key" not in serialized.casefold()


def test_runtime_binds_provider_to_the_deterministic_task_once(
    tmp_path: Path,
) -> None:
    model = FakeDiscoveryModel()
    provider = FakeDiscoveryModelProvider(model)
    runtime, project, inspected, _source = environment(
        tmp_path,
        None,
        provider,
    )

    first = discover(runtime, project, inspected)
    second = discover(runtime, project, inspected)

    assert first["taskId"] == second["taskId"]
    assert provider.bound_task_ids == [first["taskId"]]
    assert model.proposal_calls == 1
    assert model.review_calls == 1


def test_runtime_rejects_a_provider_that_changes_identity_after_task_binding(
    tmp_path: Path,
) -> None:
    expected = FakeDiscoveryModel()
    changed = FakeDiscoveryModel()
    changed.identity = CandidateDiscoveryModelIdentity(
        profile_ref="model.changed",
        configuration_fingerprint=digest("changed-model-configuration"),
        credential_revision=8,
        implementation_version="fake-provider-v2",
    )
    provider = FakeDiscoveryModelProvider(expected, bound_model=changed)
    runtime, project, inspected, _source = environment(
        tmp_path,
        None,
        provider,
    )

    with pytest.raises(StudyRuntimeError) as captured:
        discover(runtime, project, inspected)

    assert captured.value.code == "DISCOVERY_MODEL_IDENTITY_CHANGED"
    assert changed.proposal_calls == 0
    assert (
        runtime.get_project(project["projectId"], audience())["workflow"][
            "artifactStage"
        ]
        == "sources_ready"
    )


def test_exact_retry_reuses_succeeded_task_without_repeating_model_calls(
    tmp_path: Path,
) -> None:
    model = FakeDiscoveryModel()
    runtime, project, inspected, _source = environment(tmp_path, model)

    first = discover(runtime, project, inspected)
    second = discover(runtime, project, inspected)

    first_ref, _ = runtime.artifacts.resolve_with_ref(
        first["discoveryHandle"], audience()
    )
    second_ref, _ = runtime.artifacts.resolve_with_ref(
        second["discoveryHandle"], audience()
    )
    assert first_ref == second_ref
    assert {
        key: value for key, value in second.items() if key != "discoveryHandle"
    } == {key: value for key, value in first.items() if key != "discoveryHandle"}
    assert model.proposal_calls == 1
    assert model.review_calls == 1


def test_project_commit_interruption_recovers_without_repeating_model_calls(
    tmp_path: Path,
) -> None:
    model = FakeDiscoveryModel()
    runtime, project, inspected, _source = environment(tmp_path, model)
    original = runtime.projects.commit_artifact_stage
    attempts = 0

    def interrupted_once(**kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("simulated commit interruption")
        return original(**kwargs)

    runtime.projects.commit_artifact_stage = interrupted_once  # type: ignore[method-assign]
    with pytest.raises(StudyRuntimeError) as captured:
        discover(runtime, project, inspected)
    assert captured.value.code == "DISCOVERY_FAILED"
    assert model.proposal_calls == 1
    assert model.review_calls == 1
    runtime.projects.commit_artifact_stage = original  # type: ignore[method-assign]

    result = discover(runtime, project, inspected)

    assert result["artifactStage"] == "candidates_ready"
    assert model.proposal_calls == 1
    assert model.review_calls == 1


def test_same_idempotency_key_cannot_rebind_a_different_authorization(
    tmp_path: Path,
) -> None:
    model = FakeDiscoveryModel()
    runtime, project, inspected, _source = environment(tmp_path, model)
    discover(runtime, project, inspected, auth=authorization(suffix="a"))

    with pytest.raises(StudyRuntimeError) as captured:
        discover(runtime, project, inspected, auth=authorization(suffix="b"))

    assert captured.value.code == "PROJECT_IDEMPOTENCY_CONFLICT"
    assert model.proposal_calls == 1
    assert model.review_calls == 1


def test_invalid_model_output_fails_task_without_advancing_project(
    tmp_path: Path,
) -> None:
    model = FakeDiscoveryModel(invalid=True)
    runtime, project, inspected, _source = environment(tmp_path, model)

    with pytest.raises(StudyRuntimeError) as captured:
        discover(runtime, project, inspected)

    assert captured.value.code == "DISCOVERY_MODEL_RESPONSE_INVALID"
    recoverable = runtime.tasks.list_recoverable_tasks(
        audience(), scope_id=project["projectId"]
    )
    assert len(recoverable) == 1
    assert recoverable[0]["state"] == "failed"
    assert recoverable[0]["failure"]["code"] == "MODEL_OUTPUT_INVALID"
    assert recoverable[0]["failure"]["requiredAction"] == "retry"
    current = runtime.get_project(project["projectId"], audience())
    assert current["workflow"]["artifactStage"] == "sources_ready"


def test_budget_is_enforced_before_unbounded_model_output_is_persisted(
    tmp_path: Path,
) -> None:
    model = FakeDiscoveryModel(proposal_count=2)
    runtime, project, inspected, _source = environment(tmp_path, model)

    with pytest.raises(StudyRuntimeError) as captured:
        discover(runtime, project, inspected, maximum=1)

    assert captured.value.code == "DISCOVERY_MODEL_RESPONSE_INVALID"
    assert model.review_calls == 0


def test_candidate_discovery_is_unavailable_without_a_service_bound_model(
    tmp_path: Path,
) -> None:
    runtime, project, inspected, _source = environment(tmp_path, None)

    assert runtime.capabilities()["candidateDiscoveryRuntime"] is False
    assert runtime.capabilities()["publicCandidateDiscovery"] is False
    with pytest.raises(StudyRuntimeError) as captured:
        discover(runtime, project, inspected)
    assert captured.value.code == "DISCOVERY_MODEL_UNAVAILABLE"


def test_candidate_queries_page_filter_and_bind_cursors(tmp_path: Path) -> None:
    model = FakeDiscoveryModel(proposal_count=3)
    runtime, project, inspected, source = environment(tmp_path, model)
    discovered = discover(runtime, project, inspected, maximum=8)

    first = runtime.list_candidates(
        audience=audience(),
        discovery_handle=discovered["discoveryHandle"],
        filters={"eligibility": ["recommended"], "route": ["production"]},
        limit=1,
    )
    assert first["totalCandidates"] == 3
    assert first["returnedCandidates"] == 1
    assert first["nextCursor"].startswith("study_cursor_")
    assert first["items"][0]["target"]["form"] == FORM
    assert first["items"][0]["selectionState"] == "unselected"
    assert first["items"][0]["gateSummary"] == {"pass": 8, "review": 0, "fail": 0}

    second = runtime.list_candidates(
        audience=audience(),
        discovery_handle=discovered["discoveryHandle"],
        filters={"eligibility": ["recommended"], "route": ["production"]},
        cursor=first["nextCursor"],
        limit=1,
    )
    assert second["items"][0]["candidateId"] != first["items"][0]["candidateId"]

    by_source = runtime.list_candidates(
        audience=audience(),
        discovery_handle=discovered["discoveryHandle"],
        filters={"sourceHandles": [first["items"][0]["source"]["sourceHandle"]]},
        sort="source_order",
        limit=10,
    )
    assert by_source["returnedCandidates"] == 3

    serialized = json.dumps(first, ensure_ascii=False, sort_keys=True)
    assert SOURCE_TEXT not in serialized
    assert str(source) not in serialized
    for forbidden in ("artifactRef", "registryAuthRef", "plainTextBlobRef", "inputFingerprint"):
        assert forbidden not in serialized

    with pytest.raises(StudyRuntimeError) as mismatch:
        runtime.list_candidates(
            audience=audience(),
            discovery_handle=discovered["discoveryHandle"],
            filters={"query": FORM},
            cursor=first["nextCursor"],
            limit=1,
        )
    assert mismatch.value.code == "CANDIDATE_CURSOR_MISMATCH"


def test_candidate_detail_and_evidence_preview_replay_authenticated_snapshot(
    tmp_path: Path,
) -> None:
    runtime, project, inspected, source = environment(tmp_path, FakeDiscoveryModel())
    discovered = discover(runtime, project, inspected)
    listed = runtime.list_candidates(
        audience=audience(),
        discovery_handle=discovered["discoveryHandle"],
    )
    candidate_handle = listed["items"][0]["candidateHandle"]

    detail = runtime.get_candidate(
        audience=audience(),
        discovery_handle=discovered["discoveryHandle"],
        candidate_handle=candidate_handle,
    )
    assert detail["summary"]["eligibility"] == "recommended"
    assert detail["objective"]["responseSpec"] == FORM
    assert len(detail["gates"]) == 8
    assert len(detail["evidence"]) == 1
    evidence_id = detail["evidence"][0]["evidenceId"]

    preview = runtime.preview_candidate_evidence(
        audience=audience(),
        discovery_handle=discovered["discoveryHandle"],
        candidate_handle=candidate_handle,
        evidence_id=evidence_id,
        context_characters=12,
    )
    assert preview["quote"] == FORM
    assert preview["snapshotBacked"] is True
    assert preview["networkAccessed"] is False
    assert len(preview["contextBefore"]) <= 12
    assert len(preview["contextAfter"]) <= 12
    assert preview["quoteSha256"] == hashlib.sha256(FORM.encode("utf-8")).hexdigest()
    serialized = json.dumps(preview, ensure_ascii=False, sort_keys=True)
    assert str(source) not in serialized
    for forbidden in ("artifactRef", "registryAuthRef", "plainTextBlobRef"):
        assert forbidden not in serialized


def test_candidate_query_rejects_tampered_cursor_and_cross_session_handle(
    tmp_path: Path,
) -> None:
    runtime, project, inspected, _source = environment(
        tmp_path, FakeDiscoveryModel(proposal_count=2)
    )
    discovered = discover(runtime, project, inspected)
    page = runtime.list_candidates(
        audience=audience(),
        discovery_handle=discovered["discoveryHandle"],
        limit=1,
    )
    cursor = page["nextCursor"]
    replacement = "A" if cursor[-1] != "A" else "B"
    with pytest.raises(StudyRuntimeError) as tampered:
        runtime.list_candidates(
            audience=audience(),
            discovery_handle=discovered["discoveryHandle"],
            cursor=cursor[:-1] + replacement,
            limit=1,
        )
    assert tampered.value.code == "CANDIDATE_CURSOR_INVALID"

    with pytest.raises(StudyRuntimeError) as cross_session:
        runtime.get_candidate(
            audience=audience(session_id="session-2"),
            discovery_handle=discovered["discoveryHandle"],
            candidate_handle=page["items"][0]["candidateHandle"],
        )
    assert cross_session.value.code == "ARTIFACT_HANDLE_SCOPE_MISMATCH"


def test_candidate_query_requires_candidate_membership_in_the_same_discovery(
    tmp_path: Path,
) -> None:
    runtime_one, project_one, inspected_one, _ = environment(
        tmp_path / "one", FakeDiscoveryModel()
    )
    discovery_one = discover(runtime_one, project_one, inspected_one)
    candidate_one = runtime_one.list_candidates(
        audience=audience(), discovery_handle=discovery_one["discoveryHandle"]
    )["items"][0]["candidateHandle"]

    runtime_two, project_two, inspected_two, _ = environment(
        tmp_path / "two", FakeDiscoveryModel()
    )
    discovery_two = discover(runtime_two, project_two, inspected_two)
    with pytest.raises(StudyRuntimeError) as captured:
        runtime_two.get_candidate(
            audience=audience(),
            discovery_handle=discovery_two["discoveryHandle"],
            candidate_handle=candidate_one,
        )
    assert captured.value.code in {
        "ARTIFACT_HANDLE_INVALID",
        "ARTIFACT_HANDLE_AUTH_INVALID",
        "ARTIFACT_HANDLE_SCOPE_MISMATCH",
        "ARTIFACT_NOT_FOUND",
    }


def test_candidate_query_rejects_discovery_invalidated_by_contract_change(
    tmp_path: Path,
) -> None:
    runtime, project, inspected, _source = environment(tmp_path, FakeDiscoveryModel())
    discovered = discover(runtime, project, inspected)

    updated = runtime.projects.update_learning_contract(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=discovered["projectRevision"],
        expected_contract_revision=1,
        operation_id="change-learning-purpose",
        operations=[
            {"op": "set_purpose", "purpose": "Learn formal written English"}
        ],
    )
    assert updated["invalidatedStages"][0] == "discovery"

    with pytest.raises(StudyRuntimeError) as captured:
        runtime.list_candidates(
            audience=audience(),
            discovery_handle=discovered["discoveryHandle"],
        )
    assert captured.value.code == "CANDIDATE_DISCOVERY_STALE"


def test_evidence_preview_rechecks_disclosure_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, project, inspected, _source = environment(tmp_path, FakeDiscoveryModel())
    discovered = discover(runtime, project, inspected)
    listed = runtime.list_candidates(
        audience=audience(), discovery_handle=discovered["discoveryHandle"]
    )
    candidate_handle = listed["items"][0]["candidateHandle"]
    detail = runtime.get_candidate(
        audience=audience(),
        discovery_handle=discovered["discoveryHandle"],
        candidate_handle=candidate_handle,
    )
    monkeypatch.setattr(
        "card_service.candidate_queries.sensitive_disclosure_reason",
        lambda _value: "DISCOVERY_SECRET_TEXT_OMITTED",
    )

    with pytest.raises(StudyRuntimeError) as captured:
        runtime.preview_candidate_evidence(
            audience=audience(),
            discovery_handle=discovered["discoveryHandle"],
            candidate_handle=candidate_handle,
            evidence_id=detail["evidence"][0]["evidenceId"],
        )
    assert captured.value.code == "EVIDENCE_PREVIEW_REDACTED"


def test_selection_add_is_idempotent_and_projects_selected_state(
    tmp_path: Path,
) -> None:
    model = FakeDiscoveryModel(proposal_count=2)
    runtime, project, inspected, source = environment(tmp_path, model)
    discovered = discover(runtime, project, inspected)
    listed = runtime.list_candidates(
        audience=audience(), discovery_handle=discovered["discoveryHandle"]
    )
    candidate = listed["items"][0]

    selected = runtime.set_selection(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=discovered["projectRevision"],
        idempotency_key="selection-add-1",
        discovery_handle=discovered["discoveryHandle"],
        operation="add",
        candidate_handles=[candidate["candidateHandle"]],
        budget={"maxNewCards": 2, "targetDailyReviewMinutes": 10},
    )
    repeated = runtime.set_selection(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=discovered["projectRevision"],
        idempotency_key="selection-add-1",
        discovery_handle=discovered["discoveryHandle"],
        operation="add",
        candidate_handles=[candidate["candidateHandle"]],
        budget={"maxNewCards": 2, "targetDailyReviewMinutes": 10},
    )

    assert selected["projectRevision"] == discovered["projectRevision"] + 1
    assert selected["artifactStage"] == "selection_ready"
    assert selected["selectedCount"] == 1
    assert selected["nextAction"] == "plan_cards"
    assert repeated["projectRevision"] == selected["projectRevision"]
    assert repeated["selectedCount"] == 1
    assert model.proposal_calls == 1
    assert model.review_calls == 1
    projected = runtime.list_candidates(
        audience=audience(),
        discovery_handle=discovered["discoveryHandle"],
        filters={"selectionState": ["selected"]},
    )
    assert [item["candidateId"] for item in projected["items"]] == [
        candidate["candidateId"]
    ]
    task = runtime.tasks.get_task(selected["taskId"], audience())
    assert task["state"] == "succeeded"
    selection = runtime.artifacts.resolve(selected["selectionHandle"], audience())
    assert selection["payloadSchema"] == "study.portfolio-selection"
    assert len(selection["payload"]["candidateRefs"]) == 1
    serialized = json.dumps(selection, ensure_ascii=False, sort_keys=True)
    assert str(source) not in serialized
    assert SOURCE_TEXT not in serialized


def test_accept_recommended_builds_a_bounded_coverage_portfolio(tmp_path: Path) -> None:
    model = FakeDiscoveryModel(proposal_count=4)
    runtime, project, inspected, _source = environment(tmp_path, model)
    discovered = discover(runtime, project, inspected, maximum=8)

    selected = runtime.set_selection(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=discovered["projectRevision"],
        idempotency_key="selection-auto-1",
        discovery_handle=discovered["discoveryHandle"],
        operation="accept_recommended",
        budget={"maxNewCards": 2},
    )

    assert selected["selectedCount"] == 2
    assert selected["budget"] == {"maxNewCards": 2}
    assert selected["coverage"] == [
        {
            "objectiveGroup": "production",
            "selectedCount": 2,
            "availableCount": 4,
            "reasonCode": "ROUTE_REPRESENTED",
        }
    ]
    assert "SELECTION_BUDGET_LIMIT_REACHED" in selected["issueCodes"]
    assert selected["estimatedReviewDebt"]["confidence"] == "low"
    assert model.proposal_calls == 1
    assert model.review_calls == 1


def test_selection_warns_when_conservative_review_debt_exceeds_target(
    tmp_path: Path,
) -> None:
    runtime, project, inspected, _source = environment(
        tmp_path, FakeDiscoveryModel(proposal_count=12)
    )
    discovered = discover(runtime, project, inspected, maximum=20)

    selected = runtime.set_selection(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=discovered["projectRevision"],
        idempotency_key="selection-review-budget-risk",
        discovery_handle=discovered["discoveryHandle"],
        operation="accept_recommended",
        budget={"maxNewCards": 12, "targetDailyReviewMinutes": 1},
    )

    assert selected["selectedCount"] == 12
    assert selected["estimatedReviewDebt"]["expectedDailyMinutesAtDay7"] > 1
    assert "SELECTION_REVIEW_BUDGET_RISK" in selected["redundancyWarnings"]
    assert "SELECTION_REVIEW_BUDGET_RISK" in selected["issueCodes"]


def test_selection_remove_publishes_a_new_selection_with_prior_parent(
    tmp_path: Path,
) -> None:
    runtime, project, inspected, _source = environment(
        tmp_path, FakeDiscoveryModel(proposal_count=3)
    )
    discovered = discover(runtime, project, inspected)
    listed = runtime.list_candidates(
        audience=audience(), discovery_handle=discovered["discoveryHandle"]
    )
    first = runtime.set_selection(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=discovered["projectRevision"],
        idempotency_key="selection-add-two",
        discovery_handle=discovered["discoveryHandle"],
        operation="add",
        candidate_handles=[
            listed["items"][0]["candidateHandle"],
            listed["items"][1]["candidateHandle"],
        ],
        budget={"maxNewCards": 3},
    )
    second = runtime.set_selection(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=first["projectRevision"],
        idempotency_key="selection-remove-one",
        discovery_handle=discovered["discoveryHandle"],
        operation="remove",
        candidate_handles=[listed["items"][0]["candidateHandle"]],
        budget={"maxNewCards": 3},
    )

    assert second["selectedCount"] == 1
    first_ref, first_envelope = runtime.artifacts.resolve_with_ref(
        first["selectionHandle"], audience()
    )
    _second_ref, second_envelope = runtime.artifacts.resolve_with_ref(
        second["selectionHandle"], audience()
    )
    assert first_ref in second_envelope["parents"]
    assert (
        first_envelope["payload"]["selectionId"]
        != second_envelope["payload"]["selectionId"]
    )
    projected = runtime.list_candidates(
        audience=audience(),
        discovery_handle=discovered["discoveryHandle"],
        filters={"selectionState": ["selected"]},
    )
    assert projected["returnedCandidates"] == 1
    assert projected["items"][0]["candidateId"] == listed["items"][1]["candidateId"]


def test_selection_rejects_hard_blocked_and_contract_over_budget(
    tmp_path: Path,
) -> None:
    class HardBlockedModel(FakeDiscoveryModel):
        def review(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
            self.review_calls += 1
            return {
                "schema": "study.candidate-discovery.reviews",
                "schemaVersion": 1,
                "reviews": [
                    {
                        "reviewKey": item["reviewKey"],
                        "semanticEvidence": "verified",
                        "conflict": "conflict",
                        "learnerFit": "new",
                        "reasonCodes": ["UNRESOLVED_CONFLICT"],
                    }
                    for item in request["proposals"]
                ],
            }

    runtime, project, inspected, _source = environment(tmp_path, HardBlockedModel())
    discovered = discover(runtime, project, inspected)
    listed = runtime.list_candidates(
        audience=audience(), discovery_handle=discovered["discoveryHandle"]
    )
    assert listed["items"][0]["eligibility"] == "hard_blocked"

    with pytest.raises(StudyRuntimeError) as blocked:
        runtime.set_selection(
            audience=audience(),
            project_id=project["projectId"],
            expected_project_revision=discovered["projectRevision"],
            idempotency_key="selection-blocked",
            discovery_handle=discovered["discoveryHandle"],
            operation="add",
            candidate_handles=[listed["items"][0]["candidateHandle"]],
        )
    assert blocked.value.code == "SELECTION_CANDIDATE_HARD_BLOCKED"

    with pytest.raises(StudyRuntimeError) as over_budget:
        runtime.set_selection(
            audience=audience(),
            project_id=project["projectId"],
            expected_project_revision=discovered["projectRevision"],
            idempotency_key="selection-over-budget",
            discovery_handle=discovered["discoveryHandle"],
            operation="accept_recommended",
            budget={"maxNewCards": 21},
        )
    assert over_budget.value.code == "SELECTION_BUDGET_EXCEEDED"


def test_selection_does_not_reuse_invalidated_state_and_rejects_alias_duplicates(
    tmp_path: Path,
) -> None:
    runtime, project, inspected, _source = environment(
        tmp_path, FakeDiscoveryModel(proposal_count=2)
    )
    discovered = discover(runtime, project, inspected)
    listed = runtime.list_candidates(
        audience=audience(), discovery_handle=discovered["discoveryHandle"]
    )
    first_candidate_ref, _ = runtime.artifacts.resolve_with_ref(
        listed["items"][0]["candidateHandle"], audience()
    )
    alias_handle = runtime.artifacts.issue_handle(first_candidate_ref, audience())
    with pytest.raises(StudyRuntimeError) as duplicate:
        runtime.set_selection(
            audience=audience(),
            project_id=project["projectId"],
            expected_project_revision=discovered["projectRevision"],
            idempotency_key="selection-alias-duplicate",
            discovery_handle=discovered["discoveryHandle"],
            operation="add",
            candidate_handles=[
                listed["items"][0]["candidateHandle"],
                alias_handle,
            ],
        )
    assert duplicate.value.code == "CANDIDATE_QUERY_INVALID"

    first = runtime.set_selection(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=discovered["projectRevision"],
        idempotency_key="selection-before-budget-change",
        discovery_handle=discovered["discoveryHandle"],
        operation="add",
        candidate_handles=[listed["items"][0]["candidateHandle"]],
    )
    changed = runtime.projects.update_learning_contract(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=first["projectRevision"],
        expected_contract_revision=1,
        operation_id="selection-budget-change",
        operations=[{"op": "set_budget", "maxNewCards": 1}],
    )
    assert changed["invalidatedStages"][0] == "selection"
    after_change = runtime.list_candidates(
        audience=audience(), discovery_handle=discovered["discoveryHandle"]
    )
    assert {item["selectionState"] for item in after_change["items"]} == {"unselected"}

    second = runtime.set_selection(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=changed["projectRevision"],
        idempotency_key="selection-after-budget-change",
        discovery_handle=discovered["discoveryHandle"],
        operation="add",
        candidate_handles=[listed["items"][1]["candidateHandle"]],
        budget={"maxNewCards": 1},
    )
    assert second["selectedCount"] == 1
    selected = runtime.list_candidates(
        audience=audience(),
        discovery_handle=discovered["discoveryHandle"],
        filters={"selectionState": ["selected"]},
    )
    assert selected["items"][0]["candidateId"] == listed["items"][1]["candidateId"]


def _selection_for_card_planning(
    tmp_path: Path,
    model: FakeDiscoveryModel,
    *,
    candidate_count: int = 1,
) -> tuple[StudyRuntime, dict[str, Any], dict[str, Any], dict[str, Any], Path]:
    runtime, project, inspected, source = environment(tmp_path, model)
    discovered = discover(runtime, project, inspected, maximum=max(8, candidate_count))
    listed = runtime.list_candidates(
        audience=audience(), discovery_handle=discovered["discoveryHandle"]
    )
    selected = runtime.set_selection(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=discovered["projectRevision"],
        idempotency_key="selection-for-card-planning",
        discovery_handle=discovered["discoveryHandle"],
        operation="add",
        candidate_handles=[
            item["candidateHandle"] for item in listed["items"][:candidate_count]
        ],
        budget={"maxNewCards": candidate_count},
    )
    return runtime, project, discovered, selected, source


def test_card_plan_runtime_publishes_idempotent_validated_plans(
    tmp_path: Path,
) -> None:
    model = FakeDiscoveryModel(proposal_count=2)
    runtime, project, _discovered, selected, source = _selection_for_card_planning(
        tmp_path, model, candidate_count=2
    )

    planned = runtime.plan_cards(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=selected["projectRevision"],
        idempotency_key="plan-cards-1",
        selection_handle=selected["selectionHandle"],
    )
    repeated = runtime.plan_cards(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=selected["projectRevision"],
        idempotency_key="plan-cards-1",
        selection_handle=selected["selectionHandle"],
    )

    assert planned["projectRevision"] == selected["projectRevision"] + 1
    stable_keys = set(planned) - {"planSetHandle", "validationHandle"}
    assert {key: repeated[key] for key in stable_keys} == {
        key: planned[key] for key in stable_keys
    }
    for key in ("planSetHandle", "validationHandle"):
        first_ref, _ = runtime.artifacts.resolve_with_ref(planned[key], audience())
        repeated_ref, _ = runtime.artifacts.resolve_with_ref(repeated[key], audience())
        assert repeated_ref == first_ref
    assert planned == {
        **planned,
        "artifactStage": "plans_ready",
        "totalPlans": 2,
        "eligiblePlans": 2,
        "blockedPlans": 0,
        "issueCodes": [],
        "nextAction": "generate_cards",
    }
    task = runtime.tasks.get_task(planned["taskId"], audience())
    assert task["state"] == "succeeded"
    plan_set = runtime.artifacts.resolve(planned["planSetHandle"], audience())
    validation = runtime.artifacts.resolve(planned["validationHandle"], audience())
    assert plan_set["payloadSchema"] == "study.card-plan-set"
    assert validation["payloadSchema"] == "study.card-plan-validation"
    assert len(plan_set["payload"]["cardPlanRefs"]) == 2
    assert len(validation["payload"]["records"]) == 16
    assert all(
        record["state"] == "passed" for record in validation["payload"]["records"]
    )
    for entity in plan_set["payload"]["cardPlanRefs"]:
        plan = runtime.artifacts.verify_ref(entity["artifactRef"], audience())
        assert plan["payloadSchema"] == "study.card-plan"
        payload = plan["payload"]
        assert payload["route"] == "production"
        assert (
            payload["expectedResponse"]["coreAnswer"].casefold()
            not in payload["cue"]["content"].casefold()
        )
        assert payload["mediaPolicy"] == {
            "sourceAudio": False,
            "sourceVideo": False,
            "sentenceTts": False,
            "expressionTts": False,
        }
    serialized = json.dumps([plan_set, validation], ensure_ascii=False, sort_keys=True)
    assert str(source) not in serialized
    assert SOURCE_TEXT not in serialized


def test_card_plan_answer_leakage_is_blocked_without_rewriting_the_cue(
    tmp_path: Path,
) -> None:
    class LeakingCueModel(FakeDiscoveryModel):
        def propose(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
            result = dict(super().propose(request))
            result["proposals"][0][
                "meaningOrFunction"
            ] = "Use in good shape to describe healthy condition"
            return result

    runtime, project, _discovered, selected, _source = _selection_for_card_planning(
        tmp_path, LeakingCueModel()
    )
    planned = runtime.plan_cards(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=selected["projectRevision"],
        idempotency_key="plan-leaking-cue",
        selection_handle=selected["selectionHandle"],
    )

    assert planned["eligiblePlans"] == 0
    assert planned["blockedPlans"] == 1
    assert planned["nextAction"] == "review_card_plans"
    validation = runtime.artifacts.resolve(planned["validationHandle"], audience())
    leakage = [
        record
        for record in validation["payload"]["records"]
        if record["checkId"] == "answer_leakage"
    ]
    assert [record["state"] for record in leakage] == ["failed"]


def test_card_plan_preserves_explicit_needs_review_as_blocked(
    tmp_path: Path,
) -> None:
    class ReviewRequiredModel(FakeDiscoveryModel):
        def review(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
            self.review_calls += 1
            return {
                "schema": "study.candidate-discovery.reviews",
                "schemaVersion": 1,
                "reviews": [
                    {
                        "reviewKey": item["reviewKey"],
                        "semanticEvidence": "review",
                        "conflict": "clear",
                        "learnerFit": "new",
                        "reasonCodes": ["SEMANTIC_EVIDENCE_REQUIRES_REVIEW"],
                    }
                    for item in request["proposals"]
                ],
            }

    runtime, project, _discovered, selected, _source = _selection_for_card_planning(
        tmp_path, ReviewRequiredModel()
    )
    planned = runtime.plan_cards(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=selected["projectRevision"],
        idempotency_key="plan-needs-review",
        selection_handle=selected["selectionHandle"],
    )

    assert planned["eligiblePlans"] == 0
    assert planned["blockedPlans"] == 1
    assert planned["issueCodes"] == ["CARD_PLAN_REVIEW_REQUIRED"]
    validation = runtime.artifacts.resolve(planned["validationHandle"], audience())
    evidence = [
        record
        for record in validation["payload"]["records"]
        if record["checkId"] == "evidence_coverage"
    ]
    assert [record["state"] for record in evidence] == ["needs_review"]


def test_card_plan_rejects_routes_that_require_missing_semantics(
    tmp_path: Path,
) -> None:
    class PragmaticsModel(FakeDiscoveryModel):
        def propose(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
            result = dict(super().propose(request))
            result["proposals"][0]["route"] = "pragmatics_register"
            return result

    model = PragmaticsModel()
    runtime, project, inspected, _source = environment(
        tmp_path, model, routes=["pragmatics_register"]
    )
    discovered = discover(runtime, project, inspected)
    listed = runtime.list_candidates(
        audience=audience(), discovery_handle=discovered["discoveryHandle"]
    )
    selected = runtime.set_selection(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=discovered["projectRevision"],
        idempotency_key="select-pragmatics",
        discovery_handle=discovered["discoveryHandle"],
        operation="add",
        candidate_handles=[listed["items"][0]["candidateHandle"]],
    )

    with pytest.raises(StudyRuntimeError) as captured:
        runtime.plan_cards(
            audience=audience(),
            project_id=project["projectId"],
            expected_project_revision=selected["projectRevision"],
            idempotency_key="plan-pragmatics",
            selection_handle=selected["selectionHandle"],
        )
    assert captured.value.code == "UNSUPPORTED_CARD_PLAN"
    current = runtime.get_project(project["projectId"], audience())
    assert current["workflow"]["artifactStage"] == "selection_ready"


def test_card_plan_rejects_unavailable_translation_instead_of_guessing(
    tmp_path: Path,
) -> None:
    runtime, project, _discovered, selected, _source = _selection_for_card_planning(
        tmp_path, FakeDiscoveryModel()
    )
    changed = runtime.projects.update_learning_contract(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=selected["projectRevision"],
        expected_contract_revision=1,
        operation_id="request-chinese-card-plan",
        operations=[
            {
                "op": "set_languages",
                "promptLanguage": "zh-CN",
                "answerLanguage": "en",
            }
        ],
    )

    with pytest.raises(StudyRuntimeError) as captured:
        runtime.plan_cards(
            audience=audience(),
            project_id=project["projectId"],
            expected_project_revision=changed["projectRevision"],
            idempotency_key="plan-requires-translation",
            selection_handle=selected["selectionHandle"],
        )
    assert captured.value.code == "UNSUPPORTED_CARD_PLAN"
    current = runtime.get_project(project["projectId"], audience())
    assert current["workflow"]["artifactStage"] == "selection_ready"


def test_card_plan_idempotency_does_not_return_an_invalidated_plan(
    tmp_path: Path,
) -> None:
    runtime, project, _discovered, selected, _source = _selection_for_card_planning(
        tmp_path, FakeDiscoveryModel()
    )
    planned = runtime.plan_cards(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=selected["projectRevision"],
        idempotency_key="plan-before-language-change",
        selection_handle=selected["selectionHandle"],
    )
    changed = runtime.projects.update_learning_contract(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=planned["projectRevision"],
        expected_contract_revision=1,
        operation_id="invalidate-existing-card-plan",
        operations=[
            {
                "op": "set_languages",
                "promptLanguage": "English",
                "answerLanguage": "English",
            }
        ],
    )
    assert changed["invalidatedStages"][0] == "planning"

    with pytest.raises(StudyRuntimeError) as captured:
        runtime.plan_cards(
            audience=audience(),
            project_id=project["projectId"],
            expected_project_revision=selected["projectRevision"],
            idempotency_key="plan-before-language-change",
            selection_handle=selected["selectionHandle"],
        )
    assert captured.value.code == "CARD_PLAN_NOT_CURRENT"


def test_card_plan_public_query_is_paginated_and_redacted(tmp_path: Path) -> None:
    runtime, project, _discovered, selected, source = _selection_for_card_planning(
        tmp_path, FakeDiscoveryModel(proposal_count=2), candidate_count=2
    )
    planned = runtime.plan_cards(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=selected["projectRevision"],
        idempotency_key="plan-for-public-query",
        selection_handle=selected["selectionHandle"],
    )

    first = runtime.list_card_plans(
        audience=audience(), plan_set_handle=planned["planSetHandle"], limit=1
    )
    second = runtime.list_card_plans(
        audience=audience(),
        plan_set_handle=planned["planSetHandle"],
        cursor=first["nextCursor"],
        limit=1,
    )

    assert first["totalPlans"] == 2
    assert first["returnedPlans"] == 1
    assert first["eligiblePlans"] == 2
    assert first["blockedPlans"] == 0
    assert first["nextCursor"].startswith("study_plan_cursor_")
    assert second["returnedPlans"] == 1
    assert second["nextCursor"] is None
    assert {
        first["items"][0]["cardPlanId"],
        second["items"][0]["cardPlanId"],
    } == {
        entity["entityId"]
        for entity in runtime.artifacts.resolve(planned["planSetHandle"], audience())[
            "payload"
        ]["cardPlanRefs"]
    }
    for item in first["items"] + second["items"]:
        assert item["validationState"] == "eligible"
        assert len(item["checks"]) == 8
        assert all(check["state"] == "passed" for check in item["checks"])
        assert item["feedback"]["evidenceCount"] == 1
    serialized = json.dumps([first, second], ensure_ascii=False, sort_keys=True)
    assert str(source) not in serialized
    assert SOURCE_TEXT not in serialized
    for forbidden in (
        "artifactRef",
        "registryAuthRef",
        "plainTextBlobRef",
        "inputFingerprint",
        "selectionRef",
        "candidateRef",
        "objectiveRef",
        "evidenceRefs",
    ):
        assert forbidden not in serialized


def test_card_plan_public_query_rejects_tampered_cursor_and_cross_session_handle(
    tmp_path: Path,
) -> None:
    runtime, project, _discovered, selected, _source = _selection_for_card_planning(
        tmp_path, FakeDiscoveryModel(proposal_count=2), candidate_count=2
    )
    planned = runtime.plan_cards(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=selected["projectRevision"],
        idempotency_key="plan-for-cursor-security",
        selection_handle=selected["selectionHandle"],
    )
    first = runtime.list_card_plans(
        audience=audience(), plan_set_handle=planned["planSetHandle"], limit=1
    )
    cursor = first["nextCursor"]
    replacement = "a" if cursor[-1] != "a" else "b"

    with pytest.raises(StudyRuntimeError) as tampered:
        runtime.list_card_plans(
            audience=audience(),
            plan_set_handle=planned["planSetHandle"],
            cursor=cursor[:-1] + replacement,
            limit=1,
        )
    assert tampered.value.code == "CARD_PLAN_CURSOR_INVALID"

    with pytest.raises(StudyRuntimeError):
        runtime.list_card_plans(
            audience=audience(session_id="another-session"),
            plan_set_handle=planned["planSetHandle"],
        )


def test_card_plan_public_query_rejects_invalidated_plan_set(tmp_path: Path) -> None:
    runtime, project, _discovered, selected, _source = _selection_for_card_planning(
        tmp_path, FakeDiscoveryModel()
    )
    planned = runtime.plan_cards(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=selected["projectRevision"],
        idempotency_key="plan-before-public-query-invalidation",
        selection_handle=selected["selectionHandle"],
    )
    runtime.projects.update_learning_contract(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=planned["projectRevision"],
        expected_contract_revision=1,
        operation_id="invalidate-public-plan-query",
        operations=[
            {
                "op": "set_languages",
                "promptLanguage": "English",
                "answerLanguage": "English",
            }
        ],
    )

    with pytest.raises(StudyRuntimeError) as captured:
        runtime.list_card_plans(
            audience=audience(), plan_set_handle=planned["planSetHandle"]
        )
    assert captured.value.code == "CARD_PLAN_SET_STALE"


def test_card_plan_synchronous_bound_fails_before_publication(tmp_path: Path) -> None:
    runtime, project, _discovered, selected, _source = _selection_for_card_planning(
        tmp_path, FakeDiscoveryModel(proposal_count=2), candidate_count=2
    )

    with pytest.raises(StudyRuntimeError) as captured:
        runtime.plan_cards(
            audience=audience(),
            project_id=project["projectId"],
            expected_project_revision=selected["projectRevision"],
            idempotency_key="plan-over-sync-bound",
            selection_handle=selected["selectionHandle"],
            maximum_plans=1,
        )
    assert captured.value.code == "CARD_PLAN_ASYNC_REQUIRED"
    current = runtime.get_project(project["projectId"], audience())
    assert current["workflow"]["artifactStage"] == "selection_ready"
    assert all(
        ref["payloadSchema"]
        not in {"study.card-plan-set", "study.card-plan-validation"}
        for ref in current["latestArtifactRefs"]
    )
