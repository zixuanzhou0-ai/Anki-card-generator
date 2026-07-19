"""Service-owned composition root for Study project, artifact, task, and source state."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping

from .artifact_registry import (
    ArtifactAudienceBinding,
    ArtifactRegistry,
    ArtifactRegistryError,
)
from .credentials import CredentialStore, CredentialStoreError
from .project_registry import ProjectRegistry, ProjectRegistryError
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
        except (
            CredentialStoreError,
            ArtifactRegistryError,
            ProjectRegistryError,
            StudyTaskError,
            TaskSourceBindingError,
            SourceRegistrationError,
            SourceInspectionError,
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
