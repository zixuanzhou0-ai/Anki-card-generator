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
        except (
            CredentialStoreError,
            ArtifactRegistryError,
            ProjectRegistryError,
            StudyTaskError,
            TaskSourceBindingError,
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
            "sourceAssetPublication": False,
            "publicProjectTools": True,
            "publicInputRegistration": False,
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
