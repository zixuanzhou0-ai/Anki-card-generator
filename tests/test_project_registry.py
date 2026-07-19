from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

import pytest

from card_service.artifact_registry import ArtifactAudienceBinding
from card_service.project_registry import ProjectRegistry, ProjectRegistryError


KEY = bytes(range(32))
OWNER = hashlib.sha256(b"owner").hexdigest()


def audience(**changes: str) -> ArtifactAudienceBinding:
    values = {
        "owner_digest": OWNER,
        "host_id": "codex-desktop",
        "plugin_id": "speakright.study",
        "session_id": "session-1",
    }
    values.update(changes)
    return ArtifactAudienceBinding(**values)


def registry(tmp_path: Path, *, key: bytes = KEY) -> ProjectRegistry:
    return ProjectRegistry(
        tmp_path / "projects",
        authentication_key=key,
        service_instance_id="service-1",
    )


def contract(**changes):
    value = {
        "purpose": "Learn reliable ideas",
        "targetBehavior": "Recall and apply each selected idea",
    }
    value.update(changes)
    return value


def create(
    store: ProjectRegistry,
    bound: ArtifactAudienceBinding,
    *,
    key: str = "create-1",
    **changes,
):
    return store.create_project(
        audience=bound,
        idempotency_key=key,
        title=changes.pop("title", "Study Project"),
        learning_contract=contract(**changes),
    )


def test_create_get_list_and_defaults_are_canonical(tmp_path: Path) -> None:
    store = registry(tmp_path)
    bound = audience()
    project = create(store, bound)
    assert project["projectRevision"] == 1
    assert project["learningContract"]["contractRevision"] == 1
    assert project["learningContract"]["routes"] == ["reading_recognition"]
    assert project["workflow"]["artifactStage"] == "empty"
    assert project["workflow"]["primaryActionId"] == "select_source"
    assert store.get_project(project["projectId"], bound) == project
    assert [item["projectId"] for item in store.list_projects(bound)] == [
        project["projectId"]
    ]


def test_create_idempotency_returns_same_project_and_rejects_changed_input(
    tmp_path: Path,
) -> None:
    store = registry(tmp_path)
    bound = audience()
    first = create(store, bound, key="same-key")
    repeated = create(store, bound, key="same-key")
    assert repeated["projectId"] == first["projectId"]
    with pytest.raises(ProjectRegistryError) as captured:
        create(store, bound, key="same-key", title="Different")
    assert captured.value.code == "PROJECT_IDEMPOTENCY_CONFLICT"


def test_project_scope_is_owner_host_and_plugin_bound_but_not_session_bound(
    tmp_path: Path,
) -> None:
    store = registry(tmp_path)
    project = create(store, audience())
    assert store.get_project(
        project["projectId"], audience(session_id="session-2")
    )["projectId"] == project["projectId"]
    with pytest.raises(ProjectRegistryError) as captured:
        store.get_project(project["projectId"], audience(plugin_id="other.plugin"))
    assert captured.value.code == "PROJECT_SCOPE_MISMATCH"


def test_same_create_key_in_different_project_scopes_has_distinct_identity(
    tmp_path: Path,
) -> None:
    store = registry(tmp_path)
    first = create(store, audience(), key="same-key")
    second = create(
        store,
        audience(plugin_id="other.plugin"),
        key="same-key",
    )
    assert first["projectId"] != second["projectId"]
    assert [item["projectId"] for item in store.list_projects(audience())] == [
        first["projectId"]
    ]


@pytest.mark.parametrize(
    "operation,invalidated",
    [
        ({"op": "set_purpose", "purpose": "A changed purpose"}, "discovery"),
        ({"op": "set_target_behavior", "targetBehavior": "Explain it"}, "discovery"),
        ({"op": "set_learner_level", "learnerLevel": "B2"}, "discovery"),
        ({"op": "replace_routes", "routes": ["production"]}, "discovery"),
        ({"op": "set_budget", "maxNewCards": 10}, "selection"),
        (
            {
                "op": "set_languages",
                "promptLanguage": "en",
                "answerLanguage": "zh-CN",
            },
            "planning",
        ),
        (
            {"op": "set_evidence_policy", "evidencePolicy": "draft_only"},
            "discovery",
        ),
        (
            {"op": "add_exclusion", "exclusion": "Already mastered facts"},
            "discovery",
        ),
    ],
)
def test_learning_contract_operations_use_fixed_invalidation_matrix(
    tmp_path: Path, operation: dict, invalidated: str
) -> None:
    store = registry(tmp_path)
    bound = audience()
    project = create(store, bound)
    result = store.update_learning_contract(
        audience=bound,
        project_id=project["projectId"],
        expected_project_revision=1,
        expected_contract_revision=1,
        operation_id="update-1",
        operations=[operation],
    )
    assert result["projectRevision"] == 2
    assert result["contractRevision"] == 2
    assert result["invalidatedStages"][0] == invalidated


def test_update_revision_cas_and_operation_idempotency(tmp_path: Path) -> None:
    store = registry(tmp_path)
    bound = audience()
    project = create(store, bound)
    arguments = {
        "audience": bound,
        "project_id": project["projectId"],
        "expected_project_revision": 1,
        "expected_contract_revision": 1,
        "operation_id": "update-1",
        "operations": [{"op": "set_purpose", "purpose": "Changed"}],
    }
    first = store.update_learning_contract(**arguments)
    repeated = store.update_learning_contract(**arguments)
    assert repeated == first
    with pytest.raises(ProjectRegistryError) as conflict:
        store.update_learning_contract(
            **{
                **arguments,
                "operations": [{"op": "set_purpose", "purpose": "Other"}],
            }
        )
    assert conflict.value.code == "PROJECT_IDEMPOTENCY_CONFLICT"
    with pytest.raises(ProjectRegistryError) as stale:
        store.update_learning_contract(
            audience=bound,
            project_id=project["projectId"],
            expected_project_revision=1,
            expected_contract_revision=1,
            operation_id="update-2",
            operations=[
                {"op": "set_target_behavior", "targetBehavior": "Changed"}
            ],
        )
    assert stale.value.code == "PROJECT_REVISION_CONFLICT"

    with pytest.raises(ProjectRegistryError) as stale_contract:
        store.update_learning_contract(
            audience=bound,
            project_id=project["projectId"],
            expected_project_revision=2,
            expected_contract_revision=1,
            operation_id="update-3",
            operations=[
                {"op": "set_target_behavior", "targetBehavior": "Changed again"}
            ],
        )
    assert stale_contract.value.code == "CONTRACT_REVISION_CONFLICT"


def test_idempotent_replay_returns_original_result_after_later_updates(
    tmp_path: Path,
) -> None:
    store = registry(tmp_path)
    bound = audience()
    project = create(store, bound)
    first_arguments = {
        "audience": bound,
        "project_id": project["projectId"],
        "expected_project_revision": 1,
        "expected_contract_revision": 1,
        "operation_id": "update-1",
        "operations": [{"op": "set_purpose", "purpose": "Changed"}],
    }
    first = store.update_learning_contract(**first_arguments)
    store.update_learning_contract(
        audience=bound,
        project_id=project["projectId"],
        expected_project_revision=2,
        expected_contract_revision=2,
        operation_id="update-2",
        operations=[
            {"op": "set_target_behavior", "targetBehavior": "Explain it"}
        ],
    )
    assert store.update_learning_contract(**first_arguments) == first


def test_unchanged_operations_do_not_over_invalidate_a_mixed_change_set(
    tmp_path: Path,
) -> None:
    store = registry(tmp_path)
    bound = audience()
    project = create(store, bound)
    result = store.update_learning_contract(
        audience=bound,
        project_id=project["projectId"],
        expected_project_revision=1,
        expected_contract_revision=1,
        operation_id="language-only",
        operations=[
            {"op": "set_purpose", "purpose": "Learn reliable ideas"},
            {
                "op": "set_budget",
                "maxNewCards": 20,
                "targetDailyReviewMinutes": 20,
            },
            {
                "op": "set_languages",
                "promptLanguage": "en",
                "answerLanguage": "zh-CN",
            },
        ],
    )
    assert result["invalidatedStages"][0] == "planning"


def test_cross_registry_concurrent_cas_has_one_winner(tmp_path: Path) -> None:
    first_store = registry(tmp_path)
    second_store = registry(tmp_path)
    bound = audience()
    project = create(first_store, bound)
    barrier = threading.Barrier(3)
    outcomes: list[str] = []

    def update(store: ProjectRegistry, number: int) -> None:
        barrier.wait()
        try:
            store.update_learning_contract(
                audience=bound,
                project_id=project["projectId"],
                expected_project_revision=1,
                expected_contract_revision=1,
                operation_id=f"update-{number}",
                operations=[
                    {"op": "set_purpose", "purpose": f"Purpose {number}"}
                ],
            )
            outcomes.append("ok")
        except ProjectRegistryError as error:
            outcomes.append(error.code)

    threads = [
        threading.Thread(target=update, args=(first_store, 1)),
        threading.Thread(target=update, args=(second_store, 2)),
    ]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["PROJECT_REVISION_CONFLICT", "ok"]


@pytest.mark.parametrize(
    "bad_contract",
    [
        contract(routes=["not-a-route"]),
        contract(routes=["production", "production"]),
        contract(maxNewCards=0),
        contract(exclusions=["duplicate", "duplicate"]),
        contract(purpose="sk-" + "A" * 32),
        contract(targetBehavior=r"C:\Users\Someone\secret.txt"),
    ],
)
def test_contract_rejects_invalid_control_values_secrets_and_paths(
    tmp_path: Path, bad_contract: dict
) -> None:
    store = registry(tmp_path)
    with pytest.raises(ProjectRegistryError):
        store.create_project(
            audience=audience(),
            idempotency_key="bad",
            title="Bad",
            learning_contract=bad_contract,
        )


def test_unknown_operation_noop_and_remove_missing_are_rejected(
    tmp_path: Path,
) -> None:
    store = registry(tmp_path)
    bound = audience()
    project = create(store, bound)
    cases = (
        (
            {"op": "json_patch", "path": "/purpose", "value": "x"},
            "PROJECT_SCHEMA_INVALID",
        ),
        (
            {"op": "set_purpose", "purpose": "Learn reliable ideas"},
            "PROJECT_NO_CHANGE",
        ),
        (
            {"op": "remove_exclusion", "exclusion": "missing"},
            "PROJECT_NO_CHANGE",
        ),
    )
    for number, (operation, code) in enumerate(cases):
        with pytest.raises(ProjectRegistryError) as captured:
            store.update_learning_contract(
                audience=bound,
                project_id=project["projectId"],
                expected_project_revision=1,
                expected_contract_revision=1,
                operation_id=f"attempt-{number}",
                operations=[operation],
            )
        assert captured.value.code == code


def test_nfc_normalization_makes_equivalent_create_retries_idempotent(
    tmp_path: Path,
) -> None:
    store = registry(tmp_path)
    first = store.create_project(
        audience=audience(),
        idempotency_key="unicode",
        title="Café",
        learning_contract=contract(purpose="Café learning"),
    )
    repeated = store.create_project(
        audience=audience(),
        idempotency_key="unicode",
        title="Cafe\u0301",
        learning_contract=contract(purpose="Cafe\u0301 learning"),
    )
    assert repeated["projectId"] == first["projectId"]


def test_authenticated_record_tamper_and_wrong_key_fail_closed(
    tmp_path: Path,
) -> None:
    store = registry(tmp_path)
    bound = audience()
    project = create(store, bound)
    with pytest.raises(ProjectRegistryError) as wrong_key:
        registry(tmp_path, key=b"x" * 32).get_project(
            project["projectId"], bound
        )
    assert wrong_key.value.code == "PROJECT_RECORD_CORRUPT"
    path = store._project_path(project["projectId"])
    value = json.loads(path.read_text(encoding="utf-8"))
    value["project"]["title"] = "Forged"
    path.write_text(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ),
        encoding="utf-8",
    )
    with pytest.raises(ProjectRegistryError) as tampered:
        store.get_project(project["projectId"], bound)
    assert tampered.value.code == "PROJECT_RECORD_CORRUPT"


def test_valid_backup_is_not_used_to_roll_back_corrupt_current_project(
    tmp_path: Path,
) -> None:
    store = registry(tmp_path)
    bound = audience()
    project = create(store, bound)
    store.update_learning_contract(
        audience=bound,
        project_id=project["projectId"],
        expected_project_revision=1,
        expected_contract_revision=1,
        operation_id="update-1",
        operations=[{"op": "set_purpose", "purpose": "Changed"}],
    )
    store._project_path(project["projectId"]).write_bytes(b"corrupt-current")
    with pytest.raises(ProjectRegistryError) as captured:
        store.get_project(project["projectId"], bound)
    assert captured.value.code in {
        "PROJECT_RECORD_INVALID",
        "PROJECT_RECORD_CORRUPT",
    }


def test_backup_is_authenticated_prior_revision_and_create_key_is_not_stored(
    tmp_path: Path,
) -> None:
    store = registry(tmp_path)
    bound = audience()
    raw_create_key = "raw-create-idempotency-canary"
    project = create(store, bound, key=raw_create_key)
    store.update_learning_contract(
        audience=bound,
        project_id=project["projectId"],
        expected_project_revision=1,
        expected_contract_revision=1,
        operation_id="update-1",
        operations=[{"op": "set_purpose", "purpose": "Changed"}],
    )
    path = store._project_path(project["projectId"])
    backup = path.with_suffix(path.suffix + ".bak")
    prior = store._decode(backup.read_bytes())
    assert prior["project"]["projectRevision"] == 1
    assert raw_create_key.encode("utf-8") not in path.read_bytes()
    assert raw_create_key.encode("utf-8") not in backup.read_bytes()


@pytest.mark.parametrize(
    "title",
    ["sk-" + "A" * 32, r"C:\Users\Someone\private.txt"],
)
def test_project_title_rejects_secret_canaries_and_absolute_paths(
    tmp_path: Path, title: str
) -> None:
    with pytest.raises(ProjectRegistryError):
        registry(tmp_path).create_project(
            audience=audience(),
            idempotency_key="bad-title",
            title=title,
            learning_contract=contract(),
        )


def test_public_project_never_exposes_authentication_or_operation_ledger(
    tmp_path: Path,
) -> None:
    store = registry(tmp_path)
    bound = audience()
    project = create(store, bound)
    store.update_learning_contract(
        audience=bound,
        project_id=project["projectId"],
        expected_project_revision=1,
        expected_contract_revision=1,
        operation_id="update-1",
        operations=[{"op": "set_purpose", "purpose": "Changed"}],
    )
    encoded = json.dumps(
        store.get_project(project["projectId"], bound), ensure_ascii=False
    )
    assert "authTag" not in encoded
    assert "authKeyId" not in encoded
    assert "operationId" not in encoded


def artifact_ref(project_id: str, *, artifact_id: str, project_revision: int) -> dict:
    return {
        "artifactId": artifact_id,
        "projectId": project_id,
        "projectRevision": project_revision,
        "artifactRevision": 1,
        "payloadSchema": "study.source-asset",
        "payloadSchemaVersion": 1,
        "artifactDigest": hashlib.sha256(artifact_id.encode("utf-8")).hexdigest(),
        "registryAuthRef": f"auth-{artifact_id}",
    }


def test_artifact_commit_advances_one_stage_and_is_exactly_idempotent(tmp_path: Path) -> None:
    store = registry(tmp_path)
    bound = audience()
    project = create(store, bound)
    operation_digest = hashlib.sha256(b"register-inputs-1").hexdigest()
    ref = artifact_ref(project["projectId"], artifact_id="source-1", project_revision=1)
    handle = "study_" + "a" * 43

    result = store.commit_artifact_stage(
        audience=bound,
        project_id=project["projectId"],
        expected_project_revision=1,
        operation_id="register-1",
        operation_digest=operation_digest,
        task_id="task-register-1",
        artifact_stage="sources_ready",
        artifact_refs=[ref],
        artifact_handles=[handle],
    )
    assert result["projectRevision"] == 2
    assert result["artifactStage"] == "sources_ready"
    assert result["artifactHandles"] == [handle]
    current = store.get_project(project["projectId"], bound)
    assert current["workflow"]["productStep"] == "source"
    assert current["workflow"]["primaryActionId"] == "inspect_source"
    assert current["workflow"]["currentTaskId"] == "task-register-1"
    assert current["latestArtifactRefs"] == [ref]

    repeated = store.commit_artifact_stage(
        audience=bound,
        project_id=project["projectId"],
        expected_project_revision=1,
        operation_id="register-1",
        operation_digest=operation_digest,
        task_id="task-register-1",
        artifact_stage="sources_ready",
        artifact_refs=[ref],
        artifact_handles=[handle],
    )
    assert repeated == result
    assert store.get_operation_result(
        audience=bound,
        project_id=project["projectId"],
        operation_id="register-1",
        operation_digest=operation_digest,
    ) == result

    with pytest.raises(ProjectRegistryError) as conflict:
        store.get_operation_result(
            audience=bound,
            project_id=project["projectId"],
            operation_id="register-1",
            operation_digest=hashlib.sha256(b"different").hexdigest(),
        )
    assert conflict.value.code == "PROJECT_IDEMPOTENCY_CONFLICT"


def test_artifact_commit_rejects_stage_skip_scope_and_revision_mismatch(tmp_path: Path) -> None:
    store = registry(tmp_path)
    bound = audience()
    project = create(store, bound)
    operation_digest = hashlib.sha256(b"invalid-register").hexdigest()
    ref = artifact_ref(project["projectId"], artifact_id="source-1", project_revision=1)
    base = {
        "audience": bound,
        "project_id": project["projectId"],
        "expected_project_revision": 1,
        "operation_id": "register-invalid",
        "operation_digest": operation_digest,
        "task_id": "task-register-invalid",
        "artifact_refs": [ref],
        "artifact_handles": ["study_" + "b" * 43],
    }
    with pytest.raises(ProjectRegistryError) as skipped:
        store.commit_artifact_stage(**base, artifact_stage="candidates_ready")
    assert skipped.value.code == "PROJECT_ARTIFACT_STAGE_CONFLICT"

    wrong_scope = {**ref, "projectId": "other-project"}
    with pytest.raises(ProjectRegistryError) as scoped:
        store.commit_artifact_stage(
            **{**base, "artifact_refs": [wrong_scope]}, artifact_stage="sources_ready"
        )
    assert scoped.value.code == "PROJECT_ARTIFACT_SCOPE_MISMATCH"

    wrong_revision = {**ref, "projectRevision": 2}
    with pytest.raises(ProjectRegistryError) as revised:
        store.commit_artifact_stage(
            **{**base, "artifact_refs": [wrong_revision]}, artifact_stage="sources_ready"
        )
    assert revised.value.code == "PROJECT_ARTIFACT_REVISION_MISMATCH"
