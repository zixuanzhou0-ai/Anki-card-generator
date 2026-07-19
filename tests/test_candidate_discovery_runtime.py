from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import pytest

from card_service.artifact_registry import ArtifactAudienceBinding
from card_service.candidate_discovery import CandidateDiscoveryModelIdentity
from card_service.candidate_discovery_runtime import CandidateDiscoveryAuthorization
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
            "routes": ["production", "reading_recognition"],
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


def task_record(runtime: StudyRuntime, task_id: str) -> dict[str, Any]:
    for path in (runtime.root / "tasks" / "tasks").rglob("*.json"):
        value = json.loads(path.read_text(encoding="utf-8"))
        if (
            value.get("schema") == "study.task.record"
            and value["task"]["taskId"] == task_id
        ):
            return value
    raise AssertionError("task record not found")


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
