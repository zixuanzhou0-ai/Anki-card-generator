from __future__ import annotations

import hashlib

import pytest

from card_service.artifact_registry import ArtifactAudienceBinding
from card_service.task_manifests import (
    TaskManifestError,
    build_authorization_binding,
    build_capability_binding,
    build_successor_rebase,
    build_task_input_manifest,
    build_work_reuse_manifest,
)


def digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def project_subject(**changes):
    value = {
        "kind": "project_task",
        "projectId": "project-1",
        "projectRevision": 3,
        "inputArtifacts": [
            {"artifactId": "source-b", "artifactRevision": 2, "artifactDigest": digest("source-b")},
            {"artifactId": "source-a", "artifactRevision": 1, "artifactDigest": digest("source-a")},
        ],
        "sourceSnapshotDigests": [digest("snapshot-b"), digest("snapshot-a")],
        "learningContractRevision": 4,
        "cardPlanSetDigest": digest("plans"),
    }
    value.update(changes)
    return value


def components(**changes):
    value = {
        "cardService": "2.0.0",
        "worker": "1.4.0",
        "sourceAdapterSetDigest": digest("adapters"),
        "gateRuleSetVersion": "gates-v3",
        "templateFamily": "immersive_v11",
        "templateSchemaVersion": "15",
        "compatibilityContractVersion": "anki-v15",
    }
    value.update(changes)
    return value


def work_services():
    return [
        {"capability": "tts", "profileRef": "tts-main", "configurationFingerprint": digest("tts-config")},
        {"capability": "model", "profileRef": "model-main", "configurationFingerprint": digest("model-config")},
    ]


def task_services(*, model_revision: int = 7, tts_revision: int = 2):
    return [
        {
            "capability": "tts",
            "profileRef": "tts-main",
            "configurationFingerprint": digest("tts-config"),
            "credentialRevision": tts_revision,
            "egressManifestDigest": digest("tts-egress"),
        },
        {
            "capability": "model",
            "profileRef": "model-main",
            "configurationFingerprint": digest("model-config"),
            "credentialRevision": model_revision,
            "egressManifestDigest": digest("model-egress"),
        },
    ]


def work_manifest(**overrides):
    values = {
        "action_id": "generate_cards",
        "subject": project_subject(),
        "component_versions": components(),
        "service_configurations": work_services(),
        "generation_policy_digest": digest("generation-policy"),
        "work_partition_policy_digest": digest("partition-policy"),
    }
    values.update(overrides)
    return build_work_reuse_manifest(**values)


def test_work_reuse_digest_is_order_independent_for_declared_sets() -> None:
    manifest, first = work_manifest()
    reversed_subject = project_subject(
        inputArtifacts=list(reversed(project_subject()["inputArtifacts"])),
        sourceSnapshotDigests=list(reversed(project_subject()["sourceSnapshotDigests"])),
    )
    reordered, second = work_manifest(subject=reversed_subject, service_configurations=list(reversed(work_services())))
    assert first == second
    assert manifest == reordered
    assert [item["artifactId"] for item in manifest["subject"]["inputArtifacts"]] == ["source-a", "source-b"]


@pytest.mark.parametrize(
    "override",
    [
        {"subject": project_subject(projectRevision=4)},
        {"subject": project_subject(learningContractRevision=5)},
        {"subject": project_subject(cardPlanSetDigest=digest("other-plans"))},
        {"component_versions": components(worker="1.4.1")},
        {"service_configurations": [{**work_services()[0]}, {**work_services()[1], "configurationFingerprint": digest("new-model")}]},
        {"generation_policy_digest": digest("new-generation-policy")},
        {"work_partition_policy_digest": digest("new-partition-policy")},
    ],
)
def test_semantic_work_changes_change_work_reuse_digest(override) -> None:
    _, baseline = work_manifest()
    _, changed = work_manifest(**override)
    assert changed != baseline


def test_project_work_identity_cannot_include_credential_revision_or_session() -> None:
    invalid = [{**work_services()[0], "credentialRevision": 9}, work_services()[1]]
    with pytest.raises(TaskManifestError) as credential:
        work_manifest(service_configurations=invalid)
    assert credential.value.code == "TASK_MANIFEST_INVALID"
    with pytest.raises(TaskManifestError):
        work_manifest(subject={**project_subject(), "sessionId": "session-1"})


def test_profile_validation_work_identity_includes_credential_revision() -> None:
    subject = {
        "kind": "profile_validation",
        "profileRef": "model-main",
        "configurationFingerprint": digest("model-config"),
        "credentialRevision": 7,
    }
    _, first = build_work_reuse_manifest(
        action_id="validate_profile",
        subject=subject,
        component_versions=components(),
        service_configurations=[],
    )
    _, second = build_work_reuse_manifest(
        action_id="validate_profile",
        subject={**subject, "credentialRevision": 8},
        component_versions=components(),
        service_configurations=[],
    )
    assert first != second


def test_capability_binding_is_sorted_and_credential_bound() -> None:
    requirements = [
        {
            "kind": "service_profile",
            "capability": "model",
            "profileRef": "model-main",
            "configurationFingerprint": digest("model-config"),
            "credentialRevision": 7,
            "implementationVersionOrDigest": "provider-v1",
            "compatibilityContractVersion": "model-contract-v1",
        },
        {
            "kind": "fixed",
            "capabilityId": "runtime.card_service",
            "implementationVersionOrDigest": "2.0.0",
            "compatibilityContractVersion": "service-contract-v1",
        },
    ]
    manifest, first = build_capability_binding(requirements)
    _, reordered = build_capability_binding(list(reversed(requirements)))
    changed = [dict(item) for item in requirements]
    changed[0]["credentialRevision"] = 8
    _, second = build_capability_binding(changed)
    assert first == reordered
    assert first != second
    assert len(manifest["required"]) == 2
    with pytest.raises(TaskManifestError) as duplicate:
        build_capability_binding(requirements + [requirements[0]])
    assert duplicate.value.code == "TASK_MANIFEST_DUPLICATE"


def test_authorization_binding_is_order_independent_but_audience_and_epoch_bound() -> None:
    bound = ArtifactAudienceBinding(digest("owner"), "codex", "study-plugin", "session-1")
    bindings = [
        {
            "action": "call_model",
            "authorizationRecordDigest": digest("record-b"),
            "constraintsDigest": digest("constraints-b"),
            "exactScopeDigest": digest("scope-b"),
            "expectedRevocationEpoch": 2,
        },
        {
            "action": "read_source",
            "authorizationRecordDigest": digest("record-a"),
            "constraintsDigest": digest("constraints-a"),
            "exactScopeDigest": digest("scope-a"),
            "expectedRevocationEpoch": 0,
        },
    ]
    _, first = build_authorization_binding(audience=bound, service_instance_id="service-1", bindings=bindings)
    _, reordered = build_authorization_binding(audience=bound, service_instance_id="service-1", bindings=list(reversed(bindings)))
    _, new_session = build_authorization_binding(
        audience=ArtifactAudienceBinding(bound.owner_digest, bound.host_id, bound.plugin_id, "session-2"),
        service_instance_id="service-1",
        bindings=bindings,
    )
    changed_epoch = [dict(item) for item in bindings]
    changed_epoch[0]["expectedRevocationEpoch"] = 3
    _, new_epoch = build_authorization_binding(audience=bound, service_instance_id="service-1", bindings=changed_epoch)
    assert first == reordered
    assert new_session != first
    assert new_epoch != first


def task_input(*, model_revision: int = 7, authorization: str | None = None, capability: str | None = None, **changes):
    work, work_digest = work_manifest()
    subject = dict(project_subject())
    subject.pop("cardPlanSetDigest")
    values = {
        "action_id": "generate_cards",
        "work_reuse_manifest": work,
        "work_reuse_digest": work_digest,
        "subject": subject,
        "authorization_binding_digest": authorization or digest("authorization"),
        "capability_binding_digest": capability or digest("capability"),
        "component_versions": components(),
        "service_bindings": task_services(model_revision=model_revision),
        "operation_intent_digest": digest("intent"),
        "generation_policy_digest": digest("generation-policy"),
        "cost_budget_digest": digest("cost"),
        "batch_policy_digest": digest("batch"),
    }
    values.update(changes)
    return build_task_input_manifest(**values)


def test_task_input_changes_do_not_change_work_identity_but_do_change_execution_identity() -> None:
    baseline_manifest, baseline = task_input()
    _, new_credential = task_input(model_revision=8)
    _, new_authorization = task_input(authorization=digest("authorization-2"))
    _, new_capability = task_input(capability=digest("capability-2"))
    _, new_cost = task_input(cost_budget_digest=digest("cost-2"))
    _, work_digest = work_manifest()
    assert baseline_manifest["workReuseDigest"] == work_digest
    assert len({baseline, new_credential, new_authorization, new_capability, new_cost}) == 5
    assert baseline_manifest["workReuseDigest"] == task_input(model_revision=8)[0]["workReuseDigest"]


@pytest.mark.parametrize(
    "change, code",
    [
        ({"subject": {**{key: value for key, value in project_subject().items() if key != "cardPlanSetDigest"}, "projectRevision": 99}}, "TASK_MANIFEST_MISMATCH"),
        ({"component_versions": components(worker="different")}, "TASK_MANIFEST_MISMATCH"),
        ({"service_bindings": [{**task_services()[0]}, {**task_services()[1], "configurationFingerprint": digest("different")}]}, "TASK_MANIFEST_MISMATCH"),
        ({"generation_policy_digest": digest("different")}, "TASK_MANIFEST_MISMATCH"),
    ],
)
def test_task_input_cannot_drift_from_work_reuse_identity(change, code: str) -> None:
    with pytest.raises(TaskManifestError) as captured:
        task_input(**change)
    assert captured.value.code == code


def test_successor_rebase_is_sorted_and_binds_both_authorization_audits() -> None:
    units = [
        {"workUnitId": "batch-2", "resultArtifactDigests": [digest("b2-2"), digest("b2-1")]},
        {"workUnitId": "batch-1", "resultArtifactDigests": [digest("b1")]},
    ]
    values = {
        "predecessor_task_id": "task-old",
        "predecessor_task_input_digest": digest("old-input"),
        "successor_task_id": "task-new",
        "work_reuse_digest": digest("reuse"),
        "scope_relation": "narrower",
        "reused_work_units": units,
        "predecessor_authorization_audit_ref": "audit-old",
        "successor_authorization_audit_ref": "audit-new",
    }
    manifest, first = build_successor_rebase(**values)
    _, reordered = build_successor_rebase(**{**values, "reused_work_units": list(reversed(units))})
    _, changed = build_successor_rebase(**{**values, "successor_authorization_audit_ref": "audit-newer"})
    assert first == reordered
    assert changed != first
    assert [item["workUnitId"] for item in manifest["reusedWorkUnits"]] == ["batch-1", "batch-2"]
    with pytest.raises(TaskManifestError):
        build_successor_rebase(**{**values, "scope_relation": "broader"})


@pytest.mark.parametrize(
    "builder",
    [
        lambda: work_manifest(subject=project_subject(projectId=r"C:\\secret\\project")),
        lambda: work_manifest(component_versions=components(apiKey="canary")),
        lambda: task_input(service_bindings=[{**task_services()[0], "token": "canary"}, task_services()[1]]),
    ],
)
def test_manifests_reject_paths_secret_fields_and_unknown_control_values(builder) -> None:
    with pytest.raises(TaskManifestError) as captured:
        builder()
    assert captured.value.code in {"TASK_MANIFEST_INVALID", "TASK_MANIFEST_FORBIDDEN_DATA"}
    with pytest.raises(TaskManifestError):
        work_manifest(action_id="model_says_run_shell")
