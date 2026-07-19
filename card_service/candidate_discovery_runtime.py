"""Recoverable candidate discovery over a service-bound model authorization."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .artifact_registry import (
    ArtifactAudienceBinding,
    ArtifactRegistry,
    ArtifactRegistryError,
    canonical_json_bytes,
)
from .candidate_discovery import (
    CandidateDiscoveryEngine,
    CandidateDiscoveryError,
    CandidateDiscoveryModel,
    DISCOVERY_POLICY_VERSION,
    PROPOSAL_ROLE_VERSION,
    REVIEW_ROLE_VERSION,
)
from .project_registry import ProjectRegistry, ProjectRegistryError
from .task_coordinator import StudyTaskCoordinator, StudyTaskError
from .task_manifests import (
    TaskManifestError,
    build_authorization_binding,
    build_capability_binding,
    build_task_input_manifest,
    build_work_reuse_manifest,
)


_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_HANDLE_RE = re.compile(r"^study_[A-Za-z0-9_-]{43}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_CANDIDATES = 256
_COMPONENTS = {
    "cardService": "2.0.0",
    "worker": "not-invoked",
    "sourceAdapterSetDigest": hashlib.sha256(
        b"speakright.study.candidate-discovery.authenticated-representations-v1"
    ).hexdigest(),
    "gateRuleSetVersion": DISCOVERY_POLICY_VERSION,
}


class CandidateDiscoveryRuntimeError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _digest(value: Any) -> str:
    return _sha(canonical_json_bytes(value))


def _require_digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise CandidateDiscoveryRuntimeError(
            "DISCOVERY_AUTHORIZATION_INVALID", f"{label} is invalid"
        )
    return value


@dataclass(frozen=True)
class CandidateDiscoveryAuthorization:
    """Non-secret proof material resolved by the trusted authorization boundary."""

    operation_intent_digest: str
    authorization_record_digest: str
    constraints_digest: str
    exact_scope_digest: str
    expected_revocation_epoch: int
    cost_budget_digest: str
    egress_manifest_digest: str

    def __post_init__(self) -> None:
        for name in (
            "operation_intent_digest",
            "authorization_record_digest",
            "constraints_digest",
            "exact_scope_digest",
            "cost_budget_digest",
            "egress_manifest_digest",
        ):
            _require_digest(getattr(self, name), name)
        if (
            isinstance(self.expected_revocation_epoch, bool)
            or not isinstance(self.expected_revocation_epoch, int)
            or self.expected_revocation_epoch < 0
        ):
            raise CandidateDiscoveryRuntimeError(
                "DISCOVERY_AUTHORIZATION_INVALID",
                "expected revocation epoch is invalid",
            )

    def task_binding(self) -> dict[str, Any]:
        return {
            "action": "call_model",
            "authorizationRecordDigest": self.authorization_record_digest,
            "constraintsDigest": self.constraints_digest,
            "exactScopeDigest": self.exact_scope_digest,
            "expectedRevocationEpoch": self.expected_revocation_epoch,
        }

    def public_identity(self) -> dict[str, Any]:
        return {
            "operationIntentDigest": self.operation_intent_digest,
            "authorizationRecordDigest": self.authorization_record_digest,
            "constraintsDigest": self.constraints_digest,
            "exactScopeDigest": self.exact_scope_digest,
            "expectedRevocationEpoch": self.expected_revocation_epoch,
            "costBudgetDigest": self.cost_budget_digest,
            "egressManifestDigest": self.egress_manifest_digest,
        }


class CandidateDiscoveryRuntime:
    """Bind discovery artifacts to a resumable task and atomic project transition."""

    def __init__(
        self,
        *,
        service_instance_id: str,
        artifacts: ArtifactRegistry,
        projects: ProjectRegistry,
        tasks: StudyTaskCoordinator,
        model: CandidateDiscoveryModel,
    ) -> None:
        self._service_instance_id = service_instance_id
        self._artifacts = artifacts
        self._projects = projects
        self._tasks = tasks
        if not callable(getattr(model, "propose", None)) or not callable(
            getattr(model, "review", None)
        ):
            raise CandidateDiscoveryRuntimeError(
                "DISCOVERY_MODEL_INVALID", "candidate discovery model is invalid"
            )
        self._model = model
        try:
            self._engine = CandidateDiscoveryEngine(artifacts=artifacts, model=model)
        except CandidateDiscoveryError as error:
            raise CandidateDiscoveryRuntimeError(error.code, error.message) from error

    @staticmethod
    def _budget(value: Mapping[str, Any]) -> dict[str, int]:
        if not isinstance(value, Mapping) or set(value) != {"target", "maximum"}:
            raise CandidateDiscoveryRuntimeError(
                "DISCOVERY_REQUEST_INVALID", "candidateBudget fields are invalid"
            )
        target = value.get("target")
        maximum = value.get("maximum")
        if (
            isinstance(target, bool)
            or not isinstance(target, int)
            or isinstance(maximum, bool)
            or not isinstance(maximum, int)
            or target < 1
            or maximum < target
            or maximum > _MAX_CANDIDATES
        ):
            raise CandidateDiscoveryRuntimeError(
                "DISCOVERY_REQUEST_INVALID", "candidateBudget is invalid"
            )
        return {"target": target, "maximum": maximum}

    def _resolve_inspection(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_id: str,
        inspection_handle: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if not isinstance(inspection_handle, str) or not _HANDLE_RE.fullmatch(
            inspection_handle
        ):
            raise CandidateDiscoveryRuntimeError(
                "DISCOVERY_REQUEST_INVALID", "inspectionHandle is invalid"
            )
        try:
            ref, envelope = self._artifacts.resolve_with_ref(
                inspection_handle, audience
            )
        except ArtifactRegistryError as error:
            raise CandidateDiscoveryRuntimeError(error.code, error.message) from error
        if (
            ref.get("projectId") != project_id
            or envelope.get("payloadSchema") != "study.inspection"
            or envelope.get("payloadSchemaVersion") != 1
            or not isinstance(envelope.get("payload"), Mapping)
        ):
            raise CandidateDiscoveryRuntimeError(
                "DISCOVERY_INSPECTION_INVALID",
                "inspectionHandle is not a project InspectionArtifact",
            )
        return _clone(ref), _clone(envelope)

    @staticmethod
    def _operation_digest(
        *,
        project_id: str,
        expected_project_revision: int,
        inspection_ref: Mapping[str, Any],
        learning_contract_digest: str,
        candidate_budget: Mapping[str, int],
        model_identity: Mapping[str, Any],
        authorization: CandidateDiscoveryAuthorization,
    ) -> str:
        return _digest(
            {
                "schema": "study.candidate-discovery.request",
                "schemaVersion": 1,
                "projectId": project_id,
                "expectedProjectRevision": expected_project_revision,
                "inspectionRef": dict(inspection_ref),
                "learningContractDigest": learning_contract_digest,
                "candidateBudget": dict(candidate_budget),
                "modelIdentity": dict(model_identity),
                "authorization": authorization.public_identity(),
                "discoveryPolicyVersion": DISCOVERY_POLICY_VERSION,
                "proposalRoleVersion": PROPOSAL_ROLE_VERSION,
                "reviewRoleVersion": REVIEW_ROLE_VERSION,
            }
        )

    def _bundle(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project: Mapping[str, Any],
        inspection_ref: Mapping[str, Any],
        inspection: Mapping[str, Any],
        candidate_budget: Mapping[str, int],
        authorization: CandidateDiscoveryAuthorization,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], str]:
        payload = inspection["payload"]
        representation_refs = payload.get("representationRefs")
        source_refs = payload.get("sourceRefs")
        if (
            not isinstance(representation_refs, list)
            or not isinstance(source_refs, list)
            or not all(isinstance(value, Mapping) for value in representation_refs)
            or not all(isinstance(value, Mapping) for value in source_refs)
        ):
            raise CandidateDiscoveryRuntimeError(
                "DISCOVERY_INSPECTION_INVALID", "inspection graph is invalid"
            )
        input_refs = [dict(inspection_ref), *[dict(value) for value in representation_refs]]
        subject = {
            "kind": "project_task",
            "projectId": project["projectId"],
            "projectRevision": project["projectRevision"],
            "inputArtifacts": [
                {
                    "artifactId": value["artifactId"],
                    "artifactRevision": value["artifactRevision"],
                    "artifactDigest": value["artifactDigest"],
                }
                for value in input_refs
            ],
            "sourceSnapshotDigests": [
                str(value["artifactDigest"]) for value in source_refs
            ],
            "learningContractRevision": project["learningContract"][
                "contractRevision"
            ],
        }
        identity = self._model.identity
        service_configuration = {
            "capability": "model",
            "profileRef": identity.profile_ref,
            "configurationFingerprint": identity.configuration_fingerprint,
        }
        partition_digest = _digest(
            {
                "schema": "study.candidate-discovery.partition",
                "schemaVersion": 1,
                "phases": ["proposal", "review", "gate_publication"],
                "candidateBudget": dict(candidate_budget),
            }
        )
        work, work_digest = build_work_reuse_manifest(
            action_id="discover_candidates",
            subject=subject,
            component_versions=_COMPONENTS,
            service_configurations=[service_configuration],
            work_partition_policy_digest=partition_digest,
        )
        capability, capability_digest = build_capability_binding(
            [
                {
                    "kind": "fixed",
                    "capabilityId": "runtime.card_service",
                    "implementationVersionOrDigest": "2.0.0",
                    "compatibilityContractVersion": "candidate-discovery-v1",
                },
                {
                    "kind": "service_profile",
                    **service_configuration,
                    "credentialRevision": identity.credential_revision,
                    "implementationVersionOrDigest": identity.implementation_version,
                    "compatibilityContractVersion": "candidate-discovery-model-v1",
                },
            ]
        )
        authorization_binding, authorization_digest = build_authorization_binding(
            audience=audience,
            service_instance_id=self._service_instance_id,
            bindings=[authorization.task_binding()],
        )
        service_binding = {
            **service_configuration,
            "credentialRevision": identity.credential_revision,
            "egressManifestDigest": authorization.egress_manifest_digest,
        }
        task_input, input_fingerprint = build_task_input_manifest(
            action_id="discover_candidates",
            work_reuse_manifest=work,
            work_reuse_digest=work_digest,
            subject=subject,
            authorization_binding_digest=authorization_digest,
            capability_binding_digest=capability_digest,
            component_versions=_COMPONENTS,
            service_bindings=[service_binding],
            operation_intent_digest=authorization.operation_intent_digest,
            cost_budget_digest=authorization.cost_budget_digest,
            batch_policy_digest=_digest(
                {
                    "schema": "study.candidate-discovery.batch-policy",
                    "schemaVersion": 1,
                    "candidateBudget": dict(candidate_budget),
                    "proposalRoleVersion": PROPOSAL_ROLE_VERSION,
                    "reviewRoleVersion": REVIEW_ROLE_VERSION,
                }
            ),
        )
        return (
            work,
            task_input,
            capability,
            authorization_binding,
            input_fingerprint,
        )

    @staticmethod
    def _discovery_handles(result: Mapping[str, Any]) -> list[str]:
        handles = [
            result["proposalBatchHandle"],
            result["reviewBatchHandle"],
            result["discoveryHandle"],
        ]
        for publication in result["candidatePublications"]:
            handles.extend(
                [
                    publication["candidateHandle"],
                    publication["gateEvaluationHandle"],
                ]
            )
        if any(not isinstance(value, str) for value in handles):
            raise CandidateDiscoveryRuntimeError(
                "DISCOVERY_RESULT_INVALID", "discovery result handles are invalid"
            )
        if len(handles) != len(set(handles)):
            raise CandidateDiscoveryRuntimeError(
                "DISCOVERY_RESULT_INVALID", "discovery result handles contain a duplicate"
            )
        return handles

    def _public_result(
        self,
        *,
        audience: ArtifactAudienceBinding,
        committed: Mapping[str, Any],
        task_id: str,
    ) -> dict[str, Any]:
        discovery_ref: Mapping[str, Any] | None = None
        discovery: Mapping[str, Any] | None = None
        issue_codes: list[str] = []
        for ref in committed["artifactRefs"]:
            envelope = self._artifacts.verify_ref(ref, audience)
            if envelope.get("payloadSchema") == "study.discovery":
                if discovery is not None:
                    raise CandidateDiscoveryRuntimeError(
                        "DISCOVERY_RESULT_INVALID",
                        "project result contains multiple DiscoveryArtifacts",
                    )
                discovery_ref = ref
                discovery = envelope
                issue_codes = list(envelope.get("issueRefs", []))
        if discovery is None or discovery_ref is None:
            raise CandidateDiscoveryRuntimeError(
                "DISCOVERY_RESULT_INVALID", "project result has no DiscoveryArtifact"
            )
        payload = discovery["payload"]
        candidate_count = len(payload["candidateRefs"])
        return {
            "schemaVersion": 1,
            "projectId": committed["projectId"],
            "projectRevision": committed["projectRevision"],
            "artifactStage": committed["artifactStage"],
            "taskId": task_id,
            "inputFingerprint": discovery["inputFingerprint"],
            "discoveryHandle": self._artifacts.issue_handle(discovery_ref, audience),
            "candidateCount": candidate_count,
            "counts": _clone(payload["counts"]),
            "completeness": _clone(payload["completeness"]),
            "issueCodes": sorted(set(issue_codes)),
            "nextAction": "review_candidates" if candidate_count else "resolve_issue",
        }

    @staticmethod
    def _failure_code(error: Exception) -> str:
        code = getattr(error, "code", "")
        if code == "DISCOVERY_MODEL_RESPONSE_INVALID":
            return "MODEL_OUTPUT_INVALID"
        if code.startswith("ARTIFACT_") or code.startswith("CANDIDATE_ARTIFACT"):
            return "ARTIFACT_CORRUPT"
        if code in {
            "DISCOVERY_SOURCE_UNREADABLE",
            "DISCOVERY_INSPECTION_INVALID",
        }:
            return "SOURCE_UNREADABLE"
        return "INTERNAL_UNCLASSIFIED"

    def start_discovery(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_id: str,
        expected_project_revision: int,
        idempotency_key: str,
        inspection_handle: str,
        candidate_budget: Mapping[str, Any],
        authorization: CandidateDiscoveryAuthorization,
    ) -> dict[str, Any]:
        if not isinstance(idempotency_key, str) or not _IDEMPOTENCY_RE.fullmatch(
            idempotency_key
        ):
            raise CandidateDiscoveryRuntimeError(
                "DISCOVERY_REQUEST_INVALID", "idempotencyKey is invalid"
            )
        if (
            isinstance(expected_project_revision, bool)
            or not isinstance(expected_project_revision, int)
            or expected_project_revision < 1
        ):
            raise CandidateDiscoveryRuntimeError(
                "DISCOVERY_REQUEST_INVALID", "expectedProjectRevision is invalid"
            )
        budget = self._budget(candidate_budget)
        inspection_ref, inspection = self._resolve_inspection(
            audience=audience,
            project_id=project_id,
            inspection_handle=inspection_handle,
        )
        try:
            project = self._projects.get_project(project_id, audience)
        except ProjectRegistryError as error:
            raise CandidateDiscoveryRuntimeError(error.code, error.message) from error
        operation_digest = self._operation_digest(
            project_id=project_id,
            expected_project_revision=expected_project_revision,
            inspection_ref=inspection_ref,
            learning_contract_digest=project["learningContractDigest"],
            candidate_budget=budget,
            model_identity=self._model.identity.public(),
            authorization=authorization,
        )
        operation_id = "discover:" + idempotency_key
        try:
            prior = self._projects.get_operation_result(
                audience=audience,
                project_id=project_id,
                operation_id=operation_id,
                operation_digest=operation_digest,
            )
        except ProjectRegistryError as error:
            raise CandidateDiscoveryRuntimeError(error.code, error.message) from error
        if prior is not None:
            return self._public_result(
                audience=audience,
                committed=prior,
                task_id=str(prior["taskId"]),
            )
        if project["projectRevision"] != expected_project_revision:
            raise CandidateDiscoveryRuntimeError(
                "PROJECT_REVISION_CONFLICT",
                "Project revision changed before candidate discovery",
            )
        if project["workflow"]["artifactStage"] != "sources_ready":
            raise CandidateDiscoveryRuntimeError(
                "DISCOVERY_STAGE_CONFLICT",
                "Project sources are not ready for candidate discovery",
            )
        if dict(inspection_ref) not in project["latestArtifactRefs"]:
            raise CandidateDiscoveryRuntimeError(
                "DISCOVERY_INSPECTION_STALE",
                "inspectionHandle is not the current project inspection",
            )
        if inspection["payload"].get("resultingProjectRevision") != expected_project_revision:
            raise CandidateDiscoveryRuntimeError(
                "DISCOVERY_INSPECTION_STALE",
                "inspectionHandle does not match the current project revision",
            )
        try:
            work, task_input, capability, task_authorization, input_fingerprint = (
                self._bundle(
                    audience=audience,
                    project=project,
                    inspection_ref=inspection_ref,
                    inspection=inspection,
                    candidate_budget=budget,
                    authorization=authorization,
                )
            )
        except TaskManifestError as error:
            raise CandidateDiscoveryRuntimeError(error.code, error.message) from error
        task_id = "task_discovery_" + operation_digest[:40]
        try:
            task = self._tasks.create_task(
                audience=audience,
                work_reuse_manifest=work,
                task_input_manifest=task_input,
                capability_binding=capability,
                authorization_binding=task_authorization,
                work_units=[
                    {
                        "workUnitId": "candidate-discovery",
                        "phase": "discovery",
                    }
                ],
                _task_id=task_id,
            )
        except StudyTaskError as error:
            if error.code != "TASK_ALREADY_EXISTS":
                raise CandidateDiscoveryRuntimeError(error.code, error.message) from error
            task = self._tasks.get_task(task_id, audience)
            if task.get("inputFingerprint") != input_fingerprint:
                raise CandidateDiscoveryRuntimeError(
                    "TASK_INPUT_MISMATCH", "Recoverable discovery task input changed"
                )
        if task["state"] not in {"queued", "running", "succeeded"}:
            raise CandidateDiscoveryRuntimeError(
                "TASK_RECOVERY_REQUIRED",
                "Candidate discovery task requires explicit recovery",
            )
        try:
            if task["state"] != "succeeded":
                if task["state"] == "queued":
                    task = self._tasks.start_task(
                        task_id,
                        audience,
                        expected_revision=task["taskRevision"],
                        operation_id="start-" + operation_digest[:40],
                    )
                unit = task["workUnits"][0]
                if unit["state"] != "completed":
                    if unit["state"] in {"pending", "failed"}:
                        task = self._tasks.begin_work_unit(
                            task_id,
                            audience,
                            expected_revision=task["taskRevision"],
                            operation_id="begin-" + operation_digest[:40],
                            work_unit_id="candidate-discovery",
                        )
                    elif unit["state"] != "active":
                        raise CandidateDiscoveryRuntimeError(
                            "TASK_RECOVERY_REQUIRED",
                            "Candidate discovery work unit is not recoverable",
                        )
                    result = self._engine.discover(
                        audience=audience,
                        project_id=project_id,
                        project_revision=expected_project_revision,
                        input_fingerprint=input_fingerprint,
                        inspection_ref=inspection_ref,
                        learning_contract=project["learningContract"],
                        evaluated_at=task["createdAt"],
                        maximum_proposals=budget["maximum"],
                    )
                    task = self._tasks.get_task(task_id, audience)
                    task = self._tasks.complete_work_unit(
                        task_id,
                        audience,
                        expected_revision=task["taskRevision"],
                        operation_id="complete-" + operation_digest[:37],
                        work_unit_id="candidate-discovery",
                        result_handles=self._discovery_handles(result),
                    )
                task = self._tasks.get_task(task_id, audience)
                if task["state"] == "running":
                    task = self._tasks.succeed_task(
                        task_id,
                        audience,
                        expected_revision=task["taskRevision"],
                        operation_id="succeed-" + operation_digest[:38],
                    )
            final_task = self._tasks.get_task(task_id, audience)
            paired = []
            for handle in final_task["resultHandles"]:
                ref, _envelope = self._artifacts.resolve_with_ref(handle, audience)
                paired.append((ref, handle))
            paired.sort(key=lambda value: value[0]["artifactId"].encode("utf-8"))
            committed = self._projects.commit_artifact_stage(
                audience=audience,
                project_id=project_id,
                expected_project_revision=expected_project_revision,
                operation_id=operation_id,
                operation_digest=operation_digest,
                task_id=task_id,
                artifact_stage="candidates_ready",
                artifact_refs=[value[0] for value in paired],
                artifact_handles=[value[1] for value in paired],
            )
            return self._public_result(
                audience=audience,
                committed=committed,
                task_id=task_id,
            )
        except (
            ArtifactRegistryError,
            CandidateDiscoveryError,
            CandidateDiscoveryRuntimeError,
            ProjectRegistryError,
            StudyTaskError,
            TaskManifestError,
            OSError,
        ) as error:
            try:
                current = self._tasks.get_task(task_id, audience)
                if current["state"] == "running":
                    preserved = [
                        handle
                        for unit in current["workUnits"]
                        if unit["state"] == "completed"
                        for handle in unit["resultHandles"]
                    ]
                    self._tasks.fail_task(
                        task_id,
                        audience,
                        expected_revision=current["taskRevision"],
                        operation_id="fail-" + operation_digest[:40],
                        code=self._failure_code(error),
                        stage="discovery",
                        retryable=isinstance(error, CandidateDiscoveryError),
                        remote_cost_state="possible",
                        retry_scope="phase",
                        authorization_state="valid",
                        preserved_artifact_handles=preserved,
                        required_action="retry",
                    )
            except (ArtifactRegistryError, StudyTaskError):
                pass
            if isinstance(error, CandidateDiscoveryRuntimeError):
                raise
            raise CandidateDiscoveryRuntimeError(
                getattr(error, "code", "DISCOVERY_FAILED"),
                getattr(error, "message", "Candidate discovery failed safely"),
            ) from error


__all__ = [
    "CandidateDiscoveryAuthorization",
    "CandidateDiscoveryRuntime",
    "CandidateDiscoveryRuntimeError",
]