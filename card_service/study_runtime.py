"""Service-owned composition root for Study project, artifact, task, and source state."""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .anki_import_approval import (
    AnkiImportApprovalError,
    AnkiImportApprovalLedger,
)
from .anki_import_preparation import (
    AnkiImportPreparationError,
    AnkiImportPreparationRuntime,
)
from .anki_import_execution import (
    AnkiImportExecutionError,
    AnkiImportExecutionRuntime,
    AnkiImportExecutor,
)
from .anki_target_probe import AnkiTargetInspector
from .artifact_registry import (
    ArtifactAudienceBinding,
    ArtifactRegistry,
    ArtifactRegistryError,
    canonical_json_bytes,
)
from .artifact_queries import ArtifactQueryError, ArtifactQueryRuntime
from .candidate_discovery import (
    CandidateDiscoveryModel,
    CandidateDiscoveryModelProvider,
)
from .card_artifact_queries import CardArtifactQueryError, CardArtifactQueryRuntime
from .card_artifact_runtime import (
    CardArtifactRuntime,
    CardArtifactRuntimeError,
)
from .card_plan_queries import CardPlanQueryError, CardPlanQueryRuntime
from .card_plan_revision_runtime import (
    CardPlanRevisionError,
    CardPlanRevisionRuntime,
)
from .card_plan_runtime import CardPlanRuntime, CardPlanRuntimeError
from .candidate_discovery_runtime import (
    CandidateDiscoveryAuthorization,
    CandidateDiscoveryRuntime,
    CandidateDiscoveryRuntimeError,
)
from .candidate_queries import CandidateQueryError, CandidateQueryRuntime
from .candidate_selection import (
    CandidateSelectionError,
    CandidateSelectionRuntime,
)
from .credentials import CredentialStore, CredentialStoreError
from .project_registry import ProjectRegistry, ProjectRegistryError
from .package_artifact_runtime import (
    PackageArtifactRuntime,
    PackageArtifactRuntimeError,
    PackageExportExecutor,
)
from .resource_runtime import ServiceResourceRuntime
from .network_resource_registry import NetworkResourceGrantRegistry, PinnedNetworkFetcher
from .source_acquisition import YouTubeSubtitleAcquirer
from .source_inspection import (
    SourceInspectionError,
    SourceInspectionRuntime,
    StructuredSourceParser,
)
from .source_registration import (
    SourceRegistrationError,
    SourceRegistrationRuntime,
    WorkspaceFactory,
    WorkspaceReleaser,
)
from .task_coordinator import StudyTaskCoordinator, StudyTaskError
from .task_source_binding import TaskSourceBindingError, TaskSourceBindingRuntime


class StudyRuntimeError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _context(root: Path) -> bytes:
    return hashlib.sha256(
        b"study.runtime.state-context.v1\x00"
        + str(root.absolute()).casefold().encode("utf-8")
    ).digest()


class StudyRuntime:
    """One service identity and one credential root for all Study registries."""

    def __init__(
        self,
        *,
        state_dir: str | Path,
        credential_store: CredentialStore,
        resource_runtime: ServiceResourceRuntime,
        network_resource_registry: NetworkResourceGrantRegistry | None = None,
        network_fetcher: PinnedNetworkFetcher | None = None,
        youtube_subtitle_acquirer: YouTubeSubtitleAcquirer | None = None,
        structured_source_parser: StructuredSourceParser | None = None,
        structured_source_parser_binding: Mapping[str, Any] | None = None,
        workspace_factory: WorkspaceFactory | None = None,
        workspace_releaser: WorkspaceReleaser | None = None,
        candidate_discovery_model: CandidateDiscoveryModel | None = None,
        candidate_discovery_model_provider: (
            CandidateDiscoveryModelProvider | None
        ) = None,
        package_export_executor: PackageExportExecutor | None = None,
        anki_target_inspector: AnkiTargetInspector | None = None,
        anki_import_executor: AnkiImportExecutor | None = None,
        anki_import_gesture_verifier: (
            Callable[[str, str, str, str], bool] | None
        ) = None,
    ) -> None:
        root = Path(state_dir).expanduser()
        if not root.is_absolute():
            raise StudyRuntimeError(
                "STUDY_RUNTIME_STATE_INVALID",
                "Study runtime state directory must be absolute",
            )
        if not isinstance(resource_runtime, ServiceResourceRuntime):
            raise StudyRuntimeError(
                "STUDY_RUNTIME_RESOURCE_INVALID", "Study resource runtime is invalid"
            )
        self.root = root.absolute()
        self.root.mkdir(parents=True, exist_ok=True)
        self.resources = resource_runtime
        self.service_instance_id = resource_runtime.service_instance_id
        self._active_discovery_lock = threading.RLock()
        self._active_discoveries: dict[
            str, tuple[threading.Event, threading.Thread]
        ] = {}
        try:
            context = _context(self.root)
            artifact_key = credential_store.derive_service_key(
                "study-artifact-registry-v1", context=context
            )
            project_key = credential_store.derive_service_key(
                "study-project-registry-v1", context=context
            )
            task_key = credential_store.derive_service_key(
                "study-task-coordinator-v1", context=context
            )
            source_binding_key = credential_store.derive_service_key(
                "study-task-source-binding-v1", context=context
            )
            candidate_query_key = credential_store.derive_service_key(
                "study-candidate-query-v1", context=context
            )
            card_plan_query_key = credential_store.derive_service_key(
                "study-card-plan-query-v1", context=context
            )
            card_artifact_query_key = credential_store.derive_service_key(
                "study-card-artifact-query-v1", context=context
            )
            anki_import_approval_key = credential_store.derive_service_key(
                "study-anki-import-approval-v1", context=context
            )
            self.artifacts = ArtifactRegistry(
                self.root / "artifacts",
                authentication_key=artifact_key,
                service_instance_id=self.service_instance_id,
            )
            self.artifact_queries = ArtifactQueryRuntime(artifacts=self.artifacts)
            self.projects = ProjectRegistry(
                self.root / "projects",
                authentication_key=project_key,
                service_instance_id=self.service_instance_id,
            )
            self.anki_import_approvals = AnkiImportApprovalLedger(
                self.root / "anki-import-approvals",
                authentication_key=anki_import_approval_key,
                service_instance_id=self.service_instance_id,
                gesture_attestation_verifier=anki_import_gesture_verifier,
            )
            self._anki_import_gesture_verifier_available = (
                anki_import_gesture_verifier is not None
            )
            self.tasks = StudyTaskCoordinator(
                self.root / "tasks",
                authentication_key=task_key,
                service_instance_id=self.service_instance_id,
                artifact_registry=self.artifacts,
            )
            self.source_bindings = TaskSourceBindingRuntime(
                self.root / "source-bindings",
                authentication_key=source_binding_key,
                service_instance_id=self.service_instance_id,
                resource_runtime=resource_runtime,
                task_coordinator=self.tasks,
            )
            self.source_registration = SourceRegistrationRuntime(
                root=self.root / "source-registration",
                service_instance_id=self.service_instance_id,
                resources=resource_runtime,
                artifacts=self.artifacts,
                projects=self.projects,
                tasks=self.tasks,
                source_bindings=self.source_bindings,
                network_resources=network_resource_registry,
                network_fetcher=network_fetcher,
                youtube_subtitle_acquirer=youtube_subtitle_acquirer,
                workspace_factory=workspace_factory,
                workspace_releaser=workspace_releaser,
            )
            self.source_inspection = SourceInspectionRuntime(
                service_instance_id=self.service_instance_id,
                artifacts=self.artifacts,
                projects=self.projects,
                tasks=self.tasks,
                structured_source_parser=structured_source_parser,
                structured_source_parser_binding=structured_source_parser_binding,
            )
            self.candidate_queries = CandidateQueryRuntime(
                service_instance_id=self.service_instance_id,
                artifacts=self.artifacts,
                projects=self.projects,
                cursor_key=candidate_query_key,
            )
            self.candidate_selection = CandidateSelectionRuntime(
                service_instance_id=self.service_instance_id,
                artifacts=self.artifacts,
                projects=self.projects,
                tasks=self.tasks,
                candidate_queries=self.candidate_queries,
            )
            self.card_plans = CardPlanRuntime(
                service_instance_id=self.service_instance_id,
                artifacts=self.artifacts,
                projects=self.projects,
                tasks=self.tasks,
                candidate_selection=self.candidate_selection,
            )
            self.card_plan_queries = CardPlanQueryRuntime(
                service_instance_id=self.service_instance_id,
                artifacts=self.artifacts,
                projects=self.projects,
                cursor_key=card_plan_query_key,
            )
            self.card_plan_revisions = CardPlanRevisionRuntime(
                service_instance_id=self.service_instance_id,
                artifacts=self.artifacts,
                projects=self.projects,
                tasks=self.tasks,
                candidate_selection=self.candidate_selection,
                card_plan_queries=self.card_plan_queries,
            )
            self.card_artifacts = CardArtifactRuntime(
                service_instance_id=self.service_instance_id,
                artifacts=self.artifacts,
                projects=self.projects,
                tasks=self.tasks,
                card_plan_queries=self.card_plan_queries,
            )
            self.card_artifact_queries = CardArtifactQueryRuntime(
                service_instance_id=self.service_instance_id,
                artifacts=self.artifacts,
                card_artifacts=self.card_artifacts,
                cursor_key=card_artifact_query_key,
            )
            self.package_artifacts = (
                PackageArtifactRuntime(
                    root=self.root / "package-export",
                    service_instance_id=self.service_instance_id,
                    artifacts=self.artifacts,
                    projects=self.projects,
                    tasks=self.tasks,
                    resources=resource_runtime,
                    card_artifacts=self.card_artifacts,
                    export_executor=package_export_executor,
                )
                if package_export_executor is not None
                else None
            )
            self.anki_import_preparation = (
                AnkiImportPreparationRuntime(
                    service_instance_id=self.service_instance_id,
                    artifacts=self.artifacts,
                    projects=self.projects,
                    packages=self.package_artifacts,
                    target_inspector=anki_target_inspector,
                )
                if self.package_artifacts is not None
                and anki_target_inspector is not None
                else None
            )
            self.anki_import_execution = (
                AnkiImportExecutionRuntime(
                    service_instance_id=self.service_instance_id,
                    artifacts=self.artifacts,
                    projects=self.projects,
                    tasks=self.tasks,
                    preparation=self.anki_import_preparation,
                    approvals=self.anki_import_approvals,
                    executor=anki_import_executor,
                )
                if self.anki_import_preparation is not None
                and anki_import_executor is not None
                else None
            )
            discovery_configured = (
                candidate_discovery_model is not None
                or candidate_discovery_model_provider is not None
            )
            self.candidate_discovery = (
                CandidateDiscoveryRuntime(
                    service_instance_id=self.service_instance_id,
                    artifacts=self.artifacts,
                    projects=self.projects,
                    tasks=self.tasks,
                    model=candidate_discovery_model,
                    model_provider=candidate_discovery_model_provider,
                )
                if discovery_configured
                else None
            )
        except (
            CredentialStoreError,
            ArtifactRegistryError,
            ArtifactQueryError,
            ProjectRegistryError,
            StudyTaskError,
            TaskSourceBindingError,
            SourceRegistrationError,
            SourceInspectionError,
            CandidateDiscoveryRuntimeError,
            CandidateQueryError,
            CandidateSelectionError,
            CardPlanQueryError,
            CardPlanRevisionError,
            CardPlanRuntimeError,
            CardArtifactQueryError,
            CardArtifactRuntimeError,
            PackageArtifactRuntimeError,
            AnkiImportPreparationError,
            AnkiImportApprovalError,
            AnkiImportExecutionError,
            OSError,
        ) as error:
            raise StudyRuntimeError(
                getattr(error, "code", "STUDY_RUNTIME_INITIALIZATION_FAILED"),
                "Study runtime could not be initialized safely",
            ) from error

    def capabilities(self) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "serviceInstanceBound": True,
            "credentialProtectionRequired": True,
            "projectRegistry": True,
            "artifactRegistry": True,
            "publicArtifactQueries": True,
            "publicAuditQueries": True,
            "studyTaskCoordinator": True,
            "taskSourceBinding": True,
            "sourceAssetPublication": True,
            "sourceInspection": True,
            "sourceAdapters": {
                "pdfTextLayer": {
                    "available": self.source_inspection.pdf_text_layer_available,
                    "supportTier": "B",
                    "blockerCode": (
                        None
                        if self.source_inspection.pdf_text_layer_available
                        else "SOURCE_PARSER_NOT_AVAILABLE"
                    ),
                },
                "embeddedMediaTranscript": {
                    "available": self.source_inspection.embedded_media_transcript_available,
                    "supportTier": "B",
                    "blockerCode": (
                        None
                        if self.source_inspection.embedded_media_transcript_available
                        else "SOURCE_PARSER_NOT_AVAILABLE"
                    ),
                    "requiresEmbeddedSubtitle": True,
                },
            },
            "candidateDiscoveryRuntime": self.candidate_discovery is not None,
            "publicCandidateDiscovery": False,
            "publicRecoverableTaskListing": True,
            "publicCandidateDiscoveryRecovery": True,
            "publicCandidateQueries": True,
            "publicCandidateSelection": True,
            "cardPlanRuntime": True,
            "publicCardPlanPlanning": True,
            "publicCardPlanQueries": True,
            "publicCardPlanEditing": True,
            "publicCardPlanValidation": True,
            "cardArtifactRuntime": True,
            "publicCardGeneration": True,
            "publicCardQueries": True,
            "packageArtifactRuntime": self.package_artifacts is not None,
            "publicApkgExport": self.package_artifacts is not None,
            "ankiImportPreparation": self.anki_import_preparation is not None,
            "publicAnkiImportPreparation": self.anki_import_preparation is not None,
            "ankiImportApprovalLedger": True,
            "publicAnkiImportConfirmation": (
                self.anki_import_preparation is not None
                and self._anki_import_gesture_verifier_available
            ),
            "publicAnkiWrite": self.anki_import_execution is not None,
            "publicProjectTools": True,
            "publicProjectQueries": True,
            "publicLearningContractUpdate": True,
            "publicInputRegistration": True,
            "publicSourceInspection": True,
            "pathDisclosure": False,
            "complete": False,
        }

    def create_project(
        self,
        *,
        audience: ArtifactAudienceBinding,
        idempotency_key: str,
        learning_contract: Mapping[str, Any],
        title: str | None = None,
    ) -> dict[str, Any]:
        try:
            return self.projects.create_project(
                audience=audience,
                idempotency_key=idempotency_key,
                learning_contract=learning_contract,
                title=title,
            )
        except ProjectRegistryError as error:
            raise StudyRuntimeError(error.code, error.message) from error

    def get_project(
        self, project_id: str, audience: ArtifactAudienceBinding
    ) -> dict[str, Any]:
        try:
            return self.projects.get_project(project_id, audience)
        except ProjectRegistryError as error:
            raise StudyRuntimeError(error.code, error.message) from error

    def list_projects(self, audience: ArtifactAudienceBinding) -> list[dict[str, Any]]:
        try:
            return self.projects.list_projects(audience)
        except ProjectRegistryError as error:
            raise StudyRuntimeError(error.code, error.message) from error

    def update_learning_contract(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_id: str,
        expected_project_revision: int,
        expected_contract_revision: int,
        operation_id: str,
        operations: list[Mapping[str, Any]],
    ) -> dict[str, Any]:
        try:
            updated = self.projects.update_learning_contract(
                audience=audience,
                project_id=project_id,
                expected_project_revision=expected_project_revision,
                expected_contract_revision=expected_contract_revision,
                operation_id=operation_id,
                operations=operations,
            )
            current = self.projects.get_project(project_id, audience)
            current_refs = {
                canonical_json_bytes(artifact_ref)
                for artifact_ref in current["latestArtifactRefs"]
            }
            preserved: list[dict[str, Any]] = []
            for artifact_ref in updated["preservedArtifactRefs"]:
                if canonical_json_bytes(artifact_ref) not in current_refs:
                    continue
                preserved.append(
                    {
                        "artifactHandle": self.artifacts.issue_handle(
                            artifact_ref, audience
                        ),
                        "payloadSchema": artifact_ref["payloadSchema"],
                        "projectRevision": artifact_ref["projectRevision"],
                        "artifactRevision": artifact_ref["artifactRevision"],
                    }
                )
            return {
                "schemaVersion": 1,
                "projectId": updated["projectId"],
                "projectRevision": updated["projectRevision"],
                "learningContractRef": updated["learningContractRef"],
                "contractRevision": updated["contractRevision"],
                "invalidatedStages": updated["invalidatedStages"],
                "preservedArtifacts": preserved,
            }
        except (ProjectRegistryError, ArtifactRegistryError) as error:
            raise StudyRuntimeError(error.code, error.message) from error

    def get_public_artifact(
        self, *, audience: ArtifactAudienceBinding, artifact_handle: str
    ) -> dict[str, Any]:
        try:
            return self.artifact_queries.get_artifact(
                audience=audience, artifact_handle=artifact_handle
            )
        except (ArtifactQueryError, ArtifactRegistryError) as error:
            raise StudyRuntimeError(error.code, error.message) from error

    def get_public_audit(
        self, *, audience: ArtifactAudienceBinding, artifact_handle: str
    ) -> dict[str, Any]:
        try:
            return self.artifact_queries.get_audit(
                audience=audience, artifact_handle=artifact_handle
            )
        except (ArtifactQueryError, ArtifactRegistryError) as error:
            raise StudyRuntimeError(error.code, error.message) from error

    @staticmethod
    def _public_project_task(task: Mapping[str, Any]) -> dict[str, Any]:
        progress = task.get("progress")
        if not isinstance(progress, Mapping):
            progress = {}
        public_progress: dict[str, Any] = {
            "phase": str(progress.get("phase") or "unknown"),
            "phasePercent": progress.get("phasePercent"),
            "overallPercent": progress.get("overallPercent"),
            "lastProgressAt": str(progress.get("lastProgressAt") or ""),
        }
        for field in (
            "completedItems",
            "totalItems",
            "completedBatches",
            "totalBatches",
        ):
            if progress.get(field) is not None:
                public_progress[field] = progress[field]
        state = str(task.get("state") or "")
        resumability = str(task.get("resumability") or "none")
        return {
            "taskId": str(task.get("taskId") or ""),
            "intent": str(task.get("intent") or ""),
            "state": state,
            "cancellable": bool(task.get("cancellable")),
            "resumability": resumability,
            "recoverable": (
                state in {"failed", "cancelled", "interrupted"}
                and resumability != "none"
            ),
            "progress": public_progress,
            "updatedAt": str(task.get("updatedAt") or ""),
        }

    def _current_project_task(
        self,
        project: Mapping[str, Any],
        audience: ArtifactAudienceBinding,
    ) -> dict[str, Any] | None:
        workflow = project.get("workflow")
        task_id = workflow.get("currentTaskId") if isinstance(workflow, Mapping) else None
        if task_id is None:
            return None
        if not isinstance(task_id, str) or not task_id:
            raise StudyRuntimeError(
                "PROJECT_RECORD_INVALID", "Project current task identity is invalid"
            )
        try:
            task = self.tasks.get_task(task_id, audience)
        except StudyTaskError as error:
            raise StudyRuntimeError(error.code, error.message) from error
        public = self._public_project_task(task)
        if public["state"] != workflow.get("operationState"):
            raise StudyRuntimeError(
                "PROJECT_TASK_STATE_MISMATCH",
                "Project workflow and current task state do not match",
            )
        return public

    @staticmethod
    def _learning_contract_summary(project: Mapping[str, Any]) -> dict[str, Any]:
        contract = project.get("learningContract")
        if not isinstance(contract, Mapping):
            raise StudyRuntimeError(
                "PROJECT_RECORD_INVALID", "Project learning contract is invalid"
            )
        budget = contract.get("budget")
        if not isinstance(budget, Mapping):
            raise StudyRuntimeError(
                "PROJECT_RECORD_INVALID", "Project learning budget is invalid"
            )
        return {
            "contractRevision": int(contract.get("contractRevision") or 0),
            "learnerLevel": contract.get("learnerLevel"),
            "routes": list(contract.get("routes") or []),
            "maxNewCards": int(budget.get("maxNewCards") or 0),
            "targetDailyReviewMinutes": int(
                budget.get("targetDailyReviewMinutes") or 0
            ),
            "promptLanguage": str(contract.get("promptLanguage") or ""),
            "answerLanguage": str(contract.get("answerLanguage") or ""),
            "evidencePolicy": str(contract.get("evidencePolicy") or ""),
            "exclusionCount": len(contract.get("exclusions") or []),
        }

    def get_public_project(
        self, *, project_id: str, audience: ArtifactAudienceBinding
    ) -> dict[str, Any]:
        try:
            project = self.projects.get_project(project_id, audience)
            current_task = self._current_project_task(project, audience)
            artifacts: list[dict[str, Any]] = []
            for artifact_ref in project.get("latestArtifactRefs", []):
                if not isinstance(artifact_ref, Mapping):
                    raise StudyRuntimeError(
                        "PROJECT_RECORD_INVALID",
                        "Project artifact reference is invalid",
                    )
                artifacts.append(
                    {
                        "artifactHandle": self.artifacts.issue_handle(
                            artifact_ref, audience
                        ),
                        "payloadSchema": str(
                            artifact_ref.get("payloadSchema") or ""
                        ),
                        "projectRevision": int(
                            artifact_ref.get("projectRevision") or 0
                        ),
                        "artifactRevision": int(
                            artifact_ref.get("artifactRevision") or 0
                        ),
                    }
                )
            return {
                "schemaVersion": 1,
                "projectId": project["projectId"],
                "title": project["title"],
                "projectRevision": project["projectRevision"],
                "learningContract": project["learningContract"],
                "inferredDefaults": project["inferredDefaults"],
                "workflow": project["workflow"],
                "currentTask": current_task,
                "latestArtifacts": artifacts,
                "createdAt": project["createdAt"],
                "updatedAt": project["updatedAt"],
            }
        except (ProjectRegistryError, ArtifactRegistryError) as error:
            raise StudyRuntimeError(error.code, error.message) from error

    def list_public_projects(
        self,
        *,
        audience: ArtifactAudienceBinding,
        cursor: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        try:
            page = self.projects.list_projects_page(
                audience, cursor=cursor, limit=limit
            )
            items: list[dict[str, Any]] = []
            for project in page["items"]:
                task = self._current_project_task(project, audience)
                items.append(
                    {
                        "projectId": project["projectId"],
                        "title": project["title"],
                        "projectRevision": project["projectRevision"],
                        "learningContractSummary": self._learning_contract_summary(
                            project
                        ),
                        "artifactStage": project["workflow"]["artifactStage"],
                        "operationState": project["workflow"]["operationState"],
                        "latestTask": task,
                        "updatedAt": project["updatedAt"],
                        "recoverable": bool(task and task["recoverable"]),
                    }
                )
            return {
                "schemaVersion": 1,
                "totalProjects": page["totalProjects"],
                "returnedProjects": len(items),
                "items": items,
                "nextCursor": page["nextCursor"],
            }
        except ProjectRegistryError as error:
            raise StudyRuntimeError(error.code, error.message) from error

    def register_inputs(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_id: str,
        expected_project_revision: int,
        idempotency_key: str,
        input_refs: list[Mapping[str, Any]],
        snapshot_policy: str = "require_stable",
    ) -> dict[str, Any]:
        try:
            return self.source_registration.register_inputs(
                audience=audience,
                project_id=project_id,
                expected_project_revision=expected_project_revision,
                idempotency_key=idempotency_key,
                input_refs=input_refs,
                snapshot_policy=snapshot_policy,
            )
        except (
            SourceRegistrationError,
            ArtifactRegistryError,
            ProjectRegistryError,
            StudyTaskError,
            TaskSourceBindingError,
        ) as error:
            raise StudyRuntimeError(error.code, error.message) from error

    def start_source_inspection(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_id: str,
        expected_project_revision: int,
        idempotency_key: str,
        source_handles: list[str],
    ) -> dict[str, Any]:
        try:
            return self.source_inspection.start_inspection(
                audience=audience,
                project_id=project_id,
                expected_project_revision=expected_project_revision,
                idempotency_key=idempotency_key,
                source_handles=source_handles,
            )
        except (
            SourceInspectionError,
            ArtifactRegistryError,
            ProjectRegistryError,
            StudyTaskError,
        ) as error:
            raise StudyRuntimeError(error.code, error.message) from error

    def start_candidate_discovery(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_id: str,
        expected_project_revision: int,
        idempotency_key: str,
        inspection_handle: str,
        candidate_budget: Mapping[str, Any],
        authorization: CandidateDiscoveryAuthorization,
        model_provider: CandidateDiscoveryModelProvider | None = None,
    ) -> dict[str, Any]:
        discovery = self.candidate_discovery
        try:
            if model_provider is not None:
                discovery = CandidateDiscoveryRuntime(
                    service_instance_id=self.service_instance_id,
                    artifacts=self.artifacts,
                    projects=self.projects,
                    tasks=self.tasks,
                    model_provider=model_provider,
                )
            if discovery is None:
                raise StudyRuntimeError(
                    "DISCOVERY_MODEL_UNAVAILABLE",
                    "Candidate discovery has no service-bound model adapter",
                )
            return discovery.start_discovery(
                audience=audience,
                project_id=project_id,
                expected_project_revision=expected_project_revision,
                idempotency_key=idempotency_key,
                inspection_handle=inspection_handle,
                candidate_budget=candidate_budget,
                authorization=authorization,
            )
        except (
            CandidateDiscoveryRuntimeError,
            ArtifactRegistryError,
            ProjectRegistryError,
            StudyTaskError,
        ) as error:
            raise StudyRuntimeError(error.code, error.message) from error

    def start_candidate_discovery_task(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_id: str,
        expected_project_revision: int,
        idempotency_key: str,
        inspection_handle: str,
        candidate_budget: Mapping[str, Any],
        authorization: CandidateDiscoveryAuthorization,
        model_provider: CandidateDiscoveryModelProvider,
        predecessor_task_id: str | None = None,
        resume_operation_id: str | None = None,
        predecessor_authorization_audit_ref: str | None = None,
    ) -> dict[str, Any]:
        try:
            discovery = CandidateDiscoveryRuntime(
                service_instance_id=self.service_instance_id,
                artifacts=self.artifacts,
                projects=self.projects,
                tasks=self.tasks,
                model_provider=model_provider,
            )
        except CandidateDiscoveryRuntimeError as error:
            raise StudyRuntimeError(error.code, error.message) from error
        ready = threading.Event()
        cancel_event = threading.Event()
        holder: dict[str, Any] = {}

        def task_ready(task_id: str) -> bool:
            holder["taskId"] = task_id
            accepted = True
            with self._active_discovery_lock:
                existing = self._active_discoveries.get(task_id)
                if existing is None:
                    self._active_discoveries[task_id] = (cancel_event, thread)
                elif existing[1] is not thread:
                    accepted = False
            ready.set()
            return accepted

        def run() -> None:
            try:
                discovery.start_discovery(
                    audience=audience,
                    project_id=project_id,
                    expected_project_revision=expected_project_revision,
                    idempotency_key=idempotency_key,
                    inspection_handle=inspection_handle,
                    candidate_budget=candidate_budget,
                    authorization=authorization,
                    task_ready_callback=task_ready,
                    cancellation_requested=cancel_event.is_set,
                    predecessor_task_id=predecessor_task_id,
                    resume_operation_id=resume_operation_id,
                    predecessor_authorization_audit_ref=predecessor_authorization_audit_ref,
                )
            except Exception as error:
                holder["error"] = error
                ready.set()
            finally:
                task_id = holder.get("taskId")
                if isinstance(task_id, str):
                    with self._active_discovery_lock:
                        active = self._active_discoveries.get(task_id)
                        if active is not None and active[1] is thread:
                            self._active_discoveries.pop(task_id, None)

        thread = threading.Thread(
            target=run,
            daemon=True,
            name="study-candidate-discovery",
        )
        thread.start()
        if not ready.wait(10.0):
            cancel_event.set()
            raise StudyRuntimeError(
                "DISCOVERY_START_TIMEOUT",
                "Candidate discovery did not create a task in time",
            )
        task_id = holder.get("taskId")
        if not isinstance(task_id, str):
            error = holder.get("error")
            if isinstance(error, CandidateDiscoveryRuntimeError):
                raise StudyRuntimeError(error.code, error.message) from error
            if isinstance(error, StudyRuntimeError):
                raise error
            raise StudyRuntimeError(
                getattr(error, "code", "DISCOVERY_START_FAILED"),
                getattr(error, "message", "Candidate discovery could not start safely"),
            ) from error
        error = holder.get("error")
        if isinstance(error, StudyRuntimeError):
            raise error
        try:
            task = self.tasks.get_task(task_id, audience)
        except StudyTaskError as task_error:
            raise StudyRuntimeError(task_error.code, task_error.message) from task_error
        return self._public_discovery_task(task, audience)

    @staticmethod
    def _artifact_identity(value: Mapping[str, Any]) -> tuple[str, int, str]:
        return (
            str(value.get("artifactId") or ""),
            int(value.get("artifactRevision") or 0),
            str(value.get("artifactDigest") or ""),
        )

    def _public_discovery_task(
        self,
        task: Mapping[str, Any],
        audience: ArtifactAudienceBinding,
    ) -> dict[str, Any]:
        progress = (
            task.get("progress") if isinstance(task.get("progress"), Mapping) else {}
        )
        public: dict[str, Any] = {
            "schemaVersion": 1,
            "taskId": str(task.get("taskId") or ""),
            "intent": "discover_candidates",
            "state": str(task.get("state") or ""),
            "cancellable": bool(task.get("cancellable")),
            "resumability": str(task.get("resumability") or "none"),
            "progress": {
                "phase": str(progress.get("phase") or "discovery"),
                "phasePercent": progress.get("phasePercent"),
                "overallPercent": progress.get("overallPercent"),
                "lastProgressAt": str(progress.get("lastProgressAt") or ""),
            },
        }
        if public["state"] == "succeeded":
            handles = task.get("resultHandles")
            if not isinstance(handles, list):
                raise StudyRuntimeError(
                    "DISCOVERY_RESULT_INVALID",
                    "Candidate discovery task result is invalid",
                )
            discovery_ref: Mapping[str, Any] | None = None
            discovery_envelope: Mapping[str, Any] | None = None
            for handle in handles:
                if not isinstance(handle, str):
                    continue
                ref, envelope = self.artifacts.resolve_with_ref(handle, audience)
                if envelope.get("payloadSchema") == "study.discovery":
                    if discovery_envelope is not None:
                        raise StudyRuntimeError(
                            "DISCOVERY_RESULT_INVALID",
                            "Candidate discovery task has multiple results",
                        )
                    discovery_ref = ref
                    discovery_envelope = envelope
            if discovery_ref is None or discovery_envelope is None:
                raise StudyRuntimeError(
                    "DISCOVERY_RESULT_INVALID",
                    "Candidate discovery task has no DiscoveryArtifact",
                )
            project = self.projects.get_project(
                str(discovery_ref["projectId"]), audience
            )
            current = {
                self._artifact_identity(value)
                for value in project.get("latestArtifactRefs", [])
                if isinstance(value, Mapping)
                and value.get("payloadSchema") == "study.discovery"
            }
            committed = (
                project.get("workflow", {}).get("artifactStage")
                in {
                    "candidates_ready",
                    "selection_ready",
                    "plans_ready",
                    "cards_ready",
                    "apkg_ready",
                    "imported_unverified",
                    "anki_data_verified",
                    "anki_verified",
                }
                and self._artifact_identity(discovery_ref) in current
            )
            if not committed:
                with self._active_discovery_lock:
                    finalizing = public["taskId"] in self._active_discoveries
                public["state"] = "running" if finalizing else "interrupted"
                public["cancellable"] = False
                public["progress"] = {
                    **public["progress"],
                    "phase": "discovery",
                    "phasePercent": 99,
                    "overallPercent": 99,
                }
                public["nextAction"] = "poll_task" if finalizing else "resume_task"
                if not finalizing:
                    public["error"] = {
                        "code": "PROJECT_COMMIT_PENDING",
                        "retryable": True,
                        "stage": "discovery",
                        "requiredAction": "resume_task",
                    }
                return public
            payload = discovery_envelope.get("payload")
            if not isinstance(payload, Mapping):
                raise StudyRuntimeError(
                    "DISCOVERY_RESULT_INVALID",
                    "DiscoveryArtifact payload is invalid",
                )
            candidate_refs = payload.get("candidateRefs")
            if not isinstance(candidate_refs, list):
                raise StudyRuntimeError(
                    "DISCOVERY_RESULT_INVALID",
                    "DiscoveryArtifact candidates are invalid",
                )
            public["result"] = {
                "projectId": project["projectId"],
                "projectRevision": project["projectRevision"],
                "artifactStage": "candidates_ready",
                "discoveryHandle": self.artifacts.issue_handle(
                    discovery_ref, audience
                ),
                "candidateCount": len(candidate_refs),
                "counts": dict(payload.get("counts") or {}),
                "completeness": dict(payload.get("completeness") or {}),
                "issueCodes": sorted(
                    {
                        str(value)
                        for value in discovery_envelope.get("issueRefs", [])
                    }
                ),
                "nextAction": (
                    "review_candidates" if candidate_refs else "resolve_issue"
                ),
            }
            public["nextAction"] = public["result"]["nextAction"]
        elif public["state"] in {"failed", "cancelled", "interrupted"}:
            failure = task.get("failure")
            if isinstance(failure, Mapping):
                public["error"] = {
                    "code": str(failure.get("code") or "DISCOVERY_FAILED"),
                    "retryable": bool(failure.get("retryable")),
                    "stage": str(failure.get("stage") or "discovery"),
                }
                if failure.get("requiredAction"):
                    public["error"]["requiredAction"] = str(
                        failure["requiredAction"]
                    )
            public["nextAction"] = (
                "resume_task"
                if public["resumability"] != "none"
                else "resolve_issue"
            )
        else:
            public["nextAction"] = "poll_task"
        return public

    def list_recoverable_study_tasks(
        self, *, audience: ArtifactAudienceBinding, limit: int = 20
    ) -> dict[str, Any]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise StudyRuntimeError(
                "TASK_LIST_INVALID", "Recoverable task limit is invalid"
            )
        with self._active_discovery_lock:
            active_task_ids = frozenset(self._active_discoveries)
        try:
            recoverable = self.tasks.list_recoverable_tasks(
                audience,
                limit=limit,
                include_active=True,
                exclude_task_ids=active_task_ids,
                intent="discover_candidates",
            )
            discovery_tasks: list[dict[str, Any]] = []
            for task in recoverable:
                task_id = str(task["taskId"])
                if task["state"] in {"queued", "running", "cancelling"}:
                    with self._active_discovery_lock:
                        if task_id in self._active_discoveries:
                            continue
                    try:
                        task = self.tasks.interrupt_stale_task(
                            task_id,
                            audience,
                            expected_revision=int(task["taskRevision"]),
                            operation_id=(
                                "interrupt-orphan-"
                                + hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:32]
                            ),
                            allow_current_audience_orphan=True,
                        )
                    except StudyTaskError as error:
                        if error.code in {
                            "TASK_REVISION_CONFLICT",
                            "TASK_STATE_CONFLICT",
                        }:
                            continue
                        raise
                try:
                    self.candidate_discovery_recovery_request(
                        audience=audience, task_id=task_id
                    )
                    discovery_tasks.append(
                        self._public_discovery_task(task, audience)
                    )
                except StudyRuntimeError as error:
                    if error.code in {
                        "TASK_RECOVERY_STALE",
                        "DISCOVERY_RECOVERY_INVALID",
                        "TASK_NOT_RECOVERABLE",
                        "TASK_RESUME_UNSUPPORTED",
                    }:
                        continue
                    raise
        except (
            StudyTaskError,
            ArtifactRegistryError,
            ProjectRegistryError,
        ) as error:
            raise StudyRuntimeError(error.code, error.message) from error
        return {
            "schemaVersion": 1,
            "tasks": discovery_tasks,
            "returnedTasks": len(discovery_tasks),
            "nextAction": "resume_task" if discovery_tasks else "none",
        }

    def resolve_candidate_discovery_recovery_target(
        self,
        *,
        audience: ArtifactAudienceBinding,
        task_id: str,
        idempotency_key: str,
    ) -> tuple[str, dict[str, Any] | None]:
        current_task_id = task_id
        operation_id = "resume:" + idempotency_key
        try:
            for _ in range(64):
                successor = self.tasks.get_successor_task(
                    current_task_id, operation_id, audience
                )
                if successor is None:
                    return current_task_id, None
                if successor.get("intent") != "discover_candidates":
                    raise StudyRuntimeError(
                        "TASK_RESUME_UNSUPPORTED",
                        "This task intent does not support public recovery",
                    )
                public = self._public_discovery_task(successor, audience)
                persisted_state = str(successor.get("state"))
                if persisted_state in {"queued", "running", "cancelling"}:
                    successor_task_id = str(successor["taskId"])
                    with self._active_discovery_lock:
                        is_active_here = successor_task_id in self._active_discoveries
                    if is_active_here:
                        return current_task_id, public
                    try:
                        successor = self.tasks.interrupt_stale_task(
                            successor_task_id,
                            audience,
                            expected_revision=int(successor["taskRevision"]),
                            operation_id=(
                                "interrupt-orphan-"
                                + hashlib.sha256(
                                    successor_task_id.encode("utf-8")
                                ).hexdigest()[:32]
                            ),
                            allow_current_audience_orphan=True,
                        )
                    except StudyTaskError as error:
                        if error.code in {
                            "TASK_REVISION_CONFLICT",
                            "TASK_STATE_CONFLICT",
                        }:
                            continue
                        raise
                    current_task_id = str(successor["taskId"])
                    continue
                if persisted_state == "succeeded":
                    if public.get("state") == "succeeded":
                        return current_task_id, public
                    return current_task_id, None
                if (
                    persisted_state in {"failed", "cancelled", "interrupted"}
                    and successor.get("resumability") != "none"
                ):
                    current_task_id = str(successor["taskId"])
                    continue
                return current_task_id, public
        except (
            StudyTaskError,
            ArtifactRegistryError,
            ProjectRegistryError,
        ) as error:
            raise StudyRuntimeError(error.code, error.message) from error
        raise StudyRuntimeError(
            "TASK_LINEAGE_LIMIT",
            "Candidate discovery recovery lineage is too deep",
        )

    def get_existing_recovery_successor(
        self,
        *,
        audience: ArtifactAudienceBinding,
        task_id: str,
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        _, existing = self.resolve_candidate_discovery_recovery_target(
            audience=audience,
            task_id=task_id,
            idempotency_key=idempotency_key,
        )
        return existing

    def candidate_discovery_recovery_request(
        self, *, audience: ArtifactAudienceBinding, task_id: str
    ) -> dict[str, Any]:
        try:
            record = self.tasks.get_recovery_record(task_id, audience)
        except StudyTaskError as error:
            raise StudyRuntimeError(error.code, error.message) from error
        task = record.get("task")
        work = record.get("workReuseManifest")
        if (
            not isinstance(task, Mapping)
            or not isinstance(work, Mapping)
            or task.get("intent") != "discover_candidates"
            or work.get("actionId") != "discover_candidates"
        ):
            raise StudyRuntimeError(
                "TASK_RESUME_UNSUPPORTED",
                "This task intent does not support public recovery",
            )
        if (
            task.get("state") not in {"failed", "cancelled", "interrupted"}
            or task.get("resumability") == "none"
        ):
            raise StudyRuntimeError(
                "TASK_NOT_RECOVERABLE", "This task has no recoverable terminal state"
            )
        subject = work.get("subject")
        if not isinstance(subject, Mapping):
            raise StudyRuntimeError(
                "DISCOVERY_RECOVERY_INVALID", "Recovery subject is invalid"
            )
        project_id = subject.get("projectId")
        project_revision = subject.get("projectRevision")
        input_artifacts = subject.get("inputArtifacts")
        if (
            not isinstance(project_id, str)
            or isinstance(project_revision, bool)
            or not isinstance(project_revision, int)
            or not isinstance(input_artifacts, list)
        ):
            raise StudyRuntimeError(
                "DISCOVERY_RECOVERY_INVALID", "Recovery subject is incomplete"
            )
        try:
            project = self.projects.get_project(project_id, audience)
        except ProjectRegistryError as error:
            raise StudyRuntimeError(error.code, error.message) from error
        if (
            project.get("projectRevision") != project_revision
            or project.get("workflow", {}).get("artifactStage") != "sources_ready"
        ):
            raise StudyRuntimeError(
                "TASK_RECOVERY_STALE",
                "Project state changed after the recoverable discovery task",
            )
        input_identities = {
            self._artifact_identity(value)
            for value in input_artifacts
            if isinstance(value, Mapping)
        }
        inspections = [
            value
            for value in project.get("latestArtifactRefs", [])
            if isinstance(value, Mapping)
            and value.get("payloadSchema") == "study.inspection"
            and self._artifact_identity(value) in input_identities
        ]
        if len(inspections) != 1:
            raise StudyRuntimeError(
                "DISCOVERY_RECOVERY_INVALID",
                "The original inspection is no longer current",
            )
        try:
            budget = CandidateDiscoveryRuntime.recover_candidate_budget(
                work.get("workPartitionPolicyDigest")
            )
        except CandidateDiscoveryRuntimeError as error:
            raise StudyRuntimeError(error.code, error.message) from error
        authorization_binding = record.get("authorizationBinding")
        bindings = (
            authorization_binding.get("bindings")
            if isinstance(authorization_binding, Mapping)
            else None
        )
        if (
            not isinstance(bindings, list)
            or len(bindings) != 1
            or not isinstance(bindings[0], Mapping)
        ):
            raise StudyRuntimeError(
                "DISCOVERY_RECOVERY_INVALID",
                "Recovery authorization binding is invalid",
            )
        authorization_digest = bindings[0].get("authorizationRecordDigest")
        if (
            not isinstance(authorization_digest, str)
            or len(authorization_digest) != 64
            or any(value not in "0123456789abcdef" for value in authorization_digest)
        ):
            raise StudyRuntimeError(
                "DISCOVERY_RECOVERY_INVALID",
                "Recovery authorization audit reference is invalid",
            )
        return {
            "projectId": project_id,
            "expectedProjectRevision": project_revision,
            "inspectionHandle": self.artifacts.issue_handle(inspections[0], audience),
            "candidateBudget": budget,
            "predecessorAuthorizationAuditRef": (
                "authorization-record:" + authorization_digest
            ),
        }

    def resume_candidate_discovery_task(
        self,
        *,
        audience: ArtifactAudienceBinding,
        task_id: str,
        idempotency_key: str,
        authorization: CandidateDiscoveryAuthorization,
        model_provider: CandidateDiscoveryModelProvider,
        recovery_request: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        recovery_task_id, existing = self.resolve_candidate_discovery_recovery_target(
            audience=audience,
            task_id=task_id,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            return existing
        current_request = self.candidate_discovery_recovery_request(
            audience=audience, task_id=recovery_task_id
        )
        request = current_request
        if recovery_request is not None:
            request = dict(recovery_request)
            stable_keys = (
                "projectId",
                "expectedProjectRevision",
                "candidateBudget",
                "predecessorAuthorizationAuditRef",
            )
            if any(request.get(key) != current_request.get(key) for key in stable_keys):
                raise StudyRuntimeError(
                    "DISCOVERY_RECOVERY_AUTH_SCOPE_MISMATCH",
                    "Authorized recovery request no longer matches the recoverable task",
                )
            try:
                authorized_ref, _ = self.artifacts.resolve_with_ref(
                    str(request.get("inspectionHandle") or ""), audience
                )
                current_ref, _ = self.artifacts.resolve_with_ref(
                    current_request["inspectionHandle"], audience
                )
            except ArtifactRegistryError as error:
                raise StudyRuntimeError(error.code, error.message) from error
            if self._artifact_identity(authorized_ref) != self._artifact_identity(
                current_ref
            ):
                raise StudyRuntimeError(
                    "DISCOVERY_RECOVERY_AUTH_SCOPE_MISMATCH",
                    "Authorized recovery inspection no longer matches the recoverable task",
                )
        return self.start_candidate_discovery_task(
            audience=audience,
            project_id=request["projectId"],
            expected_project_revision=request["expectedProjectRevision"],
            idempotency_key=idempotency_key,
            inspection_handle=request["inspectionHandle"],
            candidate_budget=request["candidateBudget"],
            authorization=authorization,
            model_provider=model_provider,
            predecessor_task_id=recovery_task_id,
            resume_operation_id="resume:" + idempotency_key,
            predecessor_authorization_audit_ref=request[
                "predecessorAuthorizationAuditRef"
            ],
        )

    def get_source_inspection(
        self,
        *,
        audience: ArtifactAudienceBinding,
        inspection_handle: str,
    ) -> dict[str, Any]:
        try:
            return self.source_inspection.get_inspection(
                audience=audience,
                inspection_handle=inspection_handle,
            )
        except (SourceInspectionError, ArtifactRegistryError) as error:
            raise StudyRuntimeError(error.code, error.message) from error

    def list_candidates(
        self,
        *,
        audience: ArtifactAudienceBinding,
        discovery_handle: str,
        filters: Mapping[str, Any] | None = None,
        sort: str = "recommended",
        cursor: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        try:
            return self.candidate_queries.list_candidates(
                audience=audience,
                discovery_handle=discovery_handle,
                filters=filters,
                sort=sort,
                cursor=cursor,
                limit=limit,
            )
        except (
            CandidateQueryError,
            ArtifactRegistryError,
            ProjectRegistryError,
        ) as error:
            raise StudyRuntimeError(error.code, error.message) from error

    def get_candidate(
        self,
        *,
        audience: ArtifactAudienceBinding,
        discovery_handle: str,
        candidate_handle: str,
    ) -> dict[str, Any]:
        try:
            return self.candidate_queries.get_candidate(
                audience=audience,
                discovery_handle=discovery_handle,
                candidate_handle=candidate_handle,
            )
        except (
            CandidateQueryError,
            ArtifactRegistryError,
            ProjectRegistryError,
        ) as error:
            raise StudyRuntimeError(error.code, error.message) from error

    def preview_candidate_evidence(
        self,
        *,
        audience: ArtifactAudienceBinding,
        discovery_handle: str,
        candidate_handle: str,
        evidence_id: str,
        context_characters: int = 160,
    ) -> dict[str, Any]:
        try:
            return self.candidate_queries.preview_evidence(
                audience=audience,
                discovery_handle=discovery_handle,
                candidate_handle=candidate_handle,
                evidence_id=evidence_id,
                context_characters=context_characters,
            )
        except (
            CandidateQueryError,
            ArtifactRegistryError,
            ProjectRegistryError,
        ) as error:
            raise StudyRuntimeError(error.code, error.message) from error

    def set_selection(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_id: str,
        expected_project_revision: int,
        idempotency_key: str,
        discovery_handle: str,
        operation: str,
        candidate_handles: Sequence[str] | None = None,
        budget: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            return self.candidate_selection.set_selection(
                audience=audience,
                project_id=project_id,
                expected_project_revision=expected_project_revision,
                idempotency_key=idempotency_key,
                discovery_handle=discovery_handle,
                operation=operation,
                candidate_handles=candidate_handles,
                budget=budget,
            )
        except (
            CandidateSelectionError,
            CandidateQueryError,
            ArtifactRegistryError,
            ProjectRegistryError,
        ) as error:
            raise StudyRuntimeError(error.code, error.message) from error

    def list_card_plans(
        self,
        *,
        audience: ArtifactAudienceBinding,
        plan_set_handle: str,
        cursor: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        try:
            return self.card_plan_queries.list_card_plans(
                audience=audience,
                plan_set_handle=plan_set_handle,
                cursor=cursor,
                limit=limit,
            )
        except (
            CardPlanQueryError,
            ArtifactRegistryError,
            ProjectRegistryError,
        ) as error:
            raise StudyRuntimeError(error.code, error.message) from error

    def edit_card_plan(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_id: str,
        expected_project_revision: int,
        idempotency_key: str,
        plan_set_handle: str,
        card_plan_handle: str,
        operation: Mapping[str, Any],
    ) -> dict[str, Any]:
        try:
            return self.card_plan_revisions.edit_card_plan(
                audience=audience,
                project_id=project_id,
                expected_project_revision=expected_project_revision,
                idempotency_key=idempotency_key,
                plan_set_handle=plan_set_handle,
                card_plan_handle=card_plan_handle,
                operation=operation,
            )
        except (
            CardPlanRevisionError,
            ArtifactRegistryError,
            ProjectRegistryError,
        ) as error:
            raise StudyRuntimeError(error.code, error.message) from error

    def validate_card_plans(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_id: str,
        expected_project_revision: int,
        idempotency_key: str,
        plan_set_handle: str,
    ) -> dict[str, Any]:
        try:
            return self.card_plan_revisions.validate_card_plans(
                audience=audience,
                project_id=project_id,
                expected_project_revision=expected_project_revision,
                idempotency_key=idempotency_key,
                plan_set_handle=plan_set_handle,
            )
        except (
            CardPlanRevisionError,
            ArtifactRegistryError,
            ProjectRegistryError,
        ) as error:
            raise StudyRuntimeError(error.code, error.message) from error

    def list_generated_cards(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_artifact_handle: str,
        cursor: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        try:
            return self.card_artifact_queries.list_cards(
                audience=audience,
                project_artifact_handle=project_artifact_handle,
                cursor=cursor,
                limit=limit,
            )
        except (
            CardArtifactQueryError,
            CardArtifactRuntimeError,
            ArtifactRegistryError,
            ProjectRegistryError,
        ) as error:
            raise StudyRuntimeError(error.code, error.message) from error

    def generate_cards(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_id: str,
        expected_project_revision: int,
        idempotency_key: str,
        plan_set_handle: str,
    ) -> dict[str, Any]:
        try:
            return self.card_artifacts.generate_cards(
                audience=audience,
                project_id=project_id,
                expected_project_revision=expected_project_revision,
                idempotency_key=idempotency_key,
                plan_set_handle=plan_set_handle,
            )
        except (
            CardArtifactRuntimeError,
            ArtifactRegistryError,
            ProjectRegistryError,
            StudyTaskError,
        ) as error:
            raise StudyRuntimeError(error.code, error.message) from error

    def start_apkg_export(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_id: str,
        expected_project_revision: int,
        idempotency_key: str,
        project_artifact_handle: str,
        output_ref: Mapping[str, Any],
    ) -> dict[str, Any]:
        if self.package_artifacts is None:
            raise StudyRuntimeError(
                "PACKAGE_EXPORT_UNAVAILABLE", "APKG export executor is unavailable"
            )
        try:
            return self.package_artifacts.start_export(
                audience=audience,
                project_id=project_id,
                expected_project_revision=expected_project_revision,
                idempotency_key=idempotency_key,
                project_artifact_handle=project_artifact_handle,
                output_ref=output_ref,
            )
        except PackageArtifactRuntimeError as error:
            raise StudyRuntimeError(error.code, error.message) from error

    def prepare_anki_import(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_id: str,
        expected_project_revision: int,
        idempotency_key: str,
        package_artifact_handle: str,
    ) -> dict[str, Any]:
        if self.anki_import_preparation is None:
            raise StudyRuntimeError(
                "ANKI_IMPORT_PREPARATION_UNAVAILABLE",
                "Anki target inspection is unavailable",
            )
        try:
            prepared = self.anki_import_preparation.prepare(
                audience=audience,
                project_id=project_id,
                expected_project_revision=expected_project_revision,
                idempotency_key=idempotency_key,
                package_artifact_handle=package_artifact_handle,
            )
            resolved = self.anki_import_preparation.resolve_current_import_plan(
                audience=audience,
                import_plan_handle=str(prepared["importPlanHandle"]),
            )
            ref = resolved["importPlanRef"]
            payload = resolved["importPlanPayload"]
            target_digest = hashlib.sha256(
                canonical_json_bytes(payload["target"])
            ).hexdigest()
            intent = self.anki_import_approvals.create_intent(
                audience=audience,
                project_id=project_id,
                project_revision=int(prepared["projectRevision"]),
                import_plan_ref=ref,
                import_plan_digest=str(ref["artifactDigest"]),
                target_digest=target_digest,
                apkg_sha256=str(payload["apkgSha256"]),
            )
            return {
                **prepared,
                "importIntentId": intent["importIntentId"],
                "approvalState": intent["approvalState"],
            }
        except (AnkiImportPreparationError, AnkiImportApprovalError) as error:
            raise StudyRuntimeError(error.code, error.message) from error

    def get_anki_import_confirmation_context(
        self,
        *,
        audience: ArtifactAudienceBinding,
        import_intent_id: str,
    ) -> dict[str, Any]:
        if self.anki_import_preparation is None:
            raise StudyRuntimeError(
                "ANKI_IMPORT_PREPARATION_UNAVAILABLE",
                "Anki target inspection is unavailable",
            )
        try:
            binding = self.anki_import_approvals.get_binding(
                audience=audience, import_intent_id=import_intent_id
            )
            resolved = self.anki_import_preparation.resolve_current_import_plan_ref(
                audience=audience,
                import_plan_ref=binding["importPlanRef"],
            )
            ref = resolved["importPlanRef"]
            payload = resolved["importPlanPayload"]
            target_digest = hashlib.sha256(
                canonical_json_bytes(payload["target"])
            ).hexdigest()
            if (
                ref["artifactDigest"] != binding["importPlanDigest"]
                or payload["apkgSha256"] != binding["apkgSha256"]
                or target_digest != binding["targetDigest"]
            ):
                raise AnkiImportApprovalError(
                    "IMPORT_PLAN_STALE",
                    "ImportPlan changed before trusted confirmation",
                )
            deck_summary = "、".join(str(item) for item in payload["deckNames"][:4])
            if len(payload["deckNames"]) > 4:
                deck_summary += f" 等 {len(payload['deckNames'])} 个牌组"
            summary = "\n".join(
                [
                    f"目标：当前 Anki（{payload['target']['profileRef']}）",
                    f"牌组：{deck_summary}",
                    (
                        f"内容：{payload['noteCount']} 条笔记 / "
                        f"{payload['cardCount']} 张卡 / {payload['mediaCount']} 个媒体"
                    ),
                    f"APKG：{payload['fileName']}",
                    f"APKG SHA-256：{payload['apkgSha256']}",
                    f"模板：{payload['templateFamily']} / {payload['templateSchemaVersion']}",
                    f"Note Model ID：{payload['noteModelId']}",
                    f"媒体清单 SHA-256：{payload['mediaManifestDigest']}",
                    "重复策略：只检测并报告，不静默覆盖已有内容。",
                    "恢复策略：写入边界不明时停止，不自动重复导入。",
                    "运行时播放体验：本次确认不代表已经核验。",
                ]
            )
            return {
                "schemaVersion": 1,
                "importIntentId": import_intent_id,
                "audienceDigest": self.anki_import_approvals.audience_digest(audience),
                "importPlanDigest": binding["importPlanDigest"],
                "summary": summary,
            }
        except (AnkiImportPreparationError, AnkiImportApprovalError) as error:
            raise StudyRuntimeError(error.code, error.message) from error

    def get_anki_import_approval(
        self,
        *,
        audience: ArtifactAudienceBinding,
        import_intent_id: str,
    ) -> dict[str, Any]:
        try:
            return self.anki_import_approvals.get_intent(
                audience=audience, import_intent_id=import_intent_id
            )
        except AnkiImportApprovalError as error:
            raise StudyRuntimeError(error.code, error.message) from error

    def record_anki_import_decision(
        self,
        *,
        audience: ArtifactAudienceBinding,
        import_intent_id: str,
        decision: str,
        gesture_attestation_ref: str,
    ) -> dict[str, Any]:
        try:
            return self.anki_import_approvals.record_decision(
                audience=audience,
                import_intent_id=import_intent_id,
                decision=decision,
                gesture_attestation_ref=gesture_attestation_ref,
            )
        except AnkiImportApprovalError as error:
            raise StudyRuntimeError(error.code, error.message) from error

    def list_anki_import_approvals(
        self,
        *,
        audience: ArtifactAudienceBinding,
        include_terminal: bool = False,
        maximum: int = 256,
    ) -> list[dict[str, Any]]:
        try:
            return self.anki_import_approvals.list_intents(
                audience=audience,
                include_terminal=include_terminal,
                maximum=maximum,
            )
        except AnkiImportApprovalError as error:
            raise StudyRuntimeError(error.code, error.message) from error

    def revoke_anki_import_approval(
        self,
        *,
        audience: ArtifactAudienceBinding,
        import_intent_id: str,
        revocation_id: str,
        gesture_attestation_ref: str,
    ) -> dict[str, Any]:
        try:
            return self.anki_import_approvals.revoke(
                audience=audience,
                import_intent_id=import_intent_id,
                revocation_id=revocation_id,
                gesture_attestation_ref=gesture_attestation_ref,
            )
        except AnkiImportApprovalError as error:
            raise StudyRuntimeError(error.code, error.message) from error

    def start_anki_import(
        self,
        *,
        audience: ArtifactAudienceBinding,
        import_intent_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if self.anki_import_execution is None:
            raise StudyRuntimeError(
                "ANKI_IMPORT_UNAVAILABLE",
                "Authenticated Anki import execution is unavailable",
            )
        try:
            return self.anki_import_execution.start(
                audience=audience,
                import_intent_id=import_intent_id,
                idempotency_key=idempotency_key,
            )
        except AnkiImportExecutionError as error:
            raise StudyRuntimeError(error.code, error.message) from error

    def get_study_task(
        self, *, audience: ArtifactAudienceBinding, task_id: str
    ) -> dict[str, Any]:
        try:
            task = self.tasks.get_task(task_id, audience)
            if task.get("intent") == "discover_candidates":
                return self._public_discovery_task(task, audience)
            if task.get("intent") == "import_and_verify":
                if self.anki_import_execution is None:
                    raise StudyRuntimeError(
                        "TASK_RUNTIME_UNAVAILABLE",
                        "Anki import task runtime is unavailable",
                    )
                return self.anki_import_execution.get_task(task_id, audience)
            if task.get("intent") != "export_apkg":
                raise StudyRuntimeError(
                    "TASK_RUNTIME_UNAVAILABLE",
                    "Study task intent is not publicly supported",
                )
            if self.package_artifacts is None:
                raise StudyRuntimeError(
                    "TASK_RUNTIME_UNAVAILABLE",
                    "Study task runtime is unavailable",
                )
            return self.package_artifacts.get_task(task_id, audience)
        except (
            StudyTaskError,
            PackageArtifactRuntimeError,
            AnkiImportExecutionError,
            ArtifactRegistryError,
            ProjectRegistryError,
        ) as error:
            raise StudyRuntimeError(error.code, error.message) from error

    def cancel_study_task(
        self, *, audience: ArtifactAudienceBinding, task_id: str
    ) -> dict[str, Any]:
        try:
            task = self.tasks.get_task(task_id, audience)
            if task.get("intent") == "discover_candidates":
                if task.get("state") in {"queued", "running"}:
                    task = self.tasks.request_cancel(
                        task_id,
                        audience,
                        expected_revision=task["taskRevision"],
                        operation_id="request-public-cancel",
                    )
                    with self._active_discovery_lock:
                        active = self._active_discoveries.get(task_id)
                    if active is not None:
                        active[0].set()
                    elif task.get("state") == "cancelling":
                        task = self.tasks.finish_cancellation(
                            task_id,
                            audience,
                            expected_revision=task["taskRevision"],
                            operation_id="finish-orphaned-cancel",
                            safe_checkpoint_proven=False,
                        )
                return self._public_discovery_task(task, audience)
            if task.get("intent") == "import_and_verify":
                if self.anki_import_execution is None:
                    raise StudyRuntimeError(
                        "TASK_RUNTIME_UNAVAILABLE",
                        "Anki import task runtime is unavailable",
                    )
                return self.anki_import_execution.cancel_task(task_id, audience)
            if task.get("intent") != "export_apkg":
                raise StudyRuntimeError(
                    "TASK_NOT_CANCELLABLE",
                    "Study task intent is not publicly cancellable",
                )
            if self.package_artifacts is None:
                raise StudyRuntimeError(
                    "TASK_RUNTIME_UNAVAILABLE",
                    "Study task runtime is unavailable",
                )
            return self.package_artifacts.cancel_task(task_id, audience)
        except (
            StudyTaskError,
            PackageArtifactRuntimeError,
            AnkiImportExecutionError,
            ArtifactRegistryError,
            ProjectRegistryError,
        ) as error:
            raise StudyRuntimeError(error.code, error.message) from error
    def plan_cards(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_id: str,
        expected_project_revision: int,
        idempotency_key: str,
        selection_handle: str,
        maximum_plans: int = 1000,
    ) -> dict[str, Any]:
        try:
            return self.card_plans.plan_cards(
                audience=audience,
                project_id=project_id,
                expected_project_revision=expected_project_revision,
                idempotency_key=idempotency_key,
                selection_handle=selection_handle,
                maximum_plans=maximum_plans,
            )
        except (
            CardPlanRuntimeError,
            CandidateSelectionError,
            ArtifactRegistryError,
            ProjectRegistryError,
        ) as error:
            raise StudyRuntimeError(error.code, error.message) from error
