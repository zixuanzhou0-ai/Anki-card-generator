"""Service-owned composition root for Study project, artifact, task, and source state."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping, Sequence

from .anki_import_preparation import (
    AnkiImportPreparationError,
    AnkiImportPreparationRuntime,
)
from .anki_target_probe import AnkiTargetInspector
from .artifact_registry import (
    ArtifactAudienceBinding,
    ArtifactRegistry,
    ArtifactRegistryError,
)
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
from .source_inspection import SourceInspectionError, SourceInspectionRuntime
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
        workspace_factory: WorkspaceFactory | None = None,
        workspace_releaser: WorkspaceReleaser | None = None,
        candidate_discovery_model: CandidateDiscoveryModel | None = None,
        candidate_discovery_model_provider: (
            CandidateDiscoveryModelProvider | None
        ) = None,
        package_export_executor: PackageExportExecutor | None = None,
        anki_target_inspector: AnkiTargetInspector | None = None,
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
            self.artifacts = ArtifactRegistry(
                self.root / "artifacts",
                authentication_key=artifact_key,
                service_instance_id=self.service_instance_id,
            )
            self.projects = ProjectRegistry(
                self.root / "projects",
                authentication_key=project_key,
                service_instance_id=self.service_instance_id,
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
                workspace_factory=workspace_factory,
                workspace_releaser=workspace_releaser,
            )
            self.source_inspection = SourceInspectionRuntime(
                service_instance_id=self.service_instance_id,
                artifacts=self.artifacts,
                projects=self.projects,
                tasks=self.tasks,
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
            "studyTaskCoordinator": True,
            "taskSourceBinding": True,
            "sourceAssetPublication": True,
            "sourceInspection": True,
            "candidateDiscoveryRuntime": self.candidate_discovery is not None,
            "publicCandidateDiscovery": False,
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
            "publicAnkiWrite": False,
            "publicProjectTools": True,
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
            return self.anki_import_preparation.prepare(
                audience=audience,
                project_id=project_id,
                expected_project_revision=expected_project_revision,
                idempotency_key=idempotency_key,
                package_artifact_handle=package_artifact_handle,
            )
        except AnkiImportPreparationError as error:
            raise StudyRuntimeError(error.code, error.message) from error

    def get_study_task(
        self, *, audience: ArtifactAudienceBinding, task_id: str
    ) -> dict[str, Any]:
        if self.package_artifacts is None:
            raise StudyRuntimeError(
                "TASK_RUNTIME_UNAVAILABLE", "Study task runtime is unavailable"
            )
        try:
            return self.package_artifacts.get_task(task_id, audience)
        except PackageArtifactRuntimeError as error:
            raise StudyRuntimeError(error.code, error.message) from error

    def cancel_study_task(
        self, *, audience: ArtifactAudienceBinding, task_id: str
    ) -> dict[str, Any]:
        if self.package_artifacts is None:
            raise StudyRuntimeError(
                "TASK_RUNTIME_UNAVAILABLE", "Study task runtime is unavailable"
            )
        try:
            return self.package_artifacts.cancel_task(task_id, audience)
        except PackageArtifactRuntimeError as error:
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
