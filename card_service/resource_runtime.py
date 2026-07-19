from __future__ import annotations

import hashlib
import os
import re
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .artifact_registry import ArtifactAudienceBinding
from .credentials import CredentialStore, CredentialStoreError
from .local_resource_registry import (
    LocalResourceGrantRegistry,
    LocalResourceRegistryError,
    ResolvedLocalResource,
)
from .resource_staging import ResourceStagingError, StagedResource, TaskResourceStager


_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,160}$")
GestureVerifier = Callable[[str, str, str, str], bool]
StagingHardener = Callable[[Path, str], None]


class ServiceResourceRuntimeError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _require_request_id(value: str, label: str) -> str:
    if not isinstance(value, str) or not _REQUEST_ID_RE.fullmatch(value):
        raise ServiceResourceRuntimeError(
            "RESOURCE_RUNTIME_REQUEST_INVALID", f"{label} is invalid"
        )
    return value


def _path_is_within(candidate: Path, root: Path) -> bool:
    try:
        common = os.path.commonpath(
            [os.path.normcase(str(candidate.absolute())), os.path.normcase(str(root.absolute()))]
        )
    except ValueError:
        return False
    return os.path.normcase(common) == os.path.normcase(str(root.absolute()))


def _state_context(root: Path) -> bytes:
    normalized = os.path.normcase(str(root.absolute())).encode("utf-8")
    return hashlib.sha256(
        b"study.service-resource-runtime.state-context.v1\x00" + normalized
    ).digest()


class ServiceResourceRuntime:
    """Card Service-owned local resource registry and task staging composition.

    This object is deliberately not an MCP adapter. Raw paths can enter only the
    trusted issuance call, and Worker-facing values are task-relative locators.
    """

    def __init__(
        self,
        *,
        state_dir: str | Path,
        credential_store: CredentialStore,
        gesture_verifier: GestureVerifier | None,
        harden_callback: StagingHardener | None,
        forbidden_roots: Sequence[str | Path] = (),
        require_hardening: bool,
    ) -> None:
        root = Path(state_dir).expanduser()
        if not root.is_absolute():
            raise ServiceResourceRuntimeError(
                "RESOURCE_RUNTIME_STATE_INVALID",
                "resource runtime state directory must be absolute",
            )
        self.root = root.absolute()
        normalized_forbidden: list[Path] = [self.root]
        for value in forbidden_roots:
            candidate = Path(value).expanduser()
            if not candidate.is_absolute():
                raise ServiceResourceRuntimeError(
                    "RESOURCE_RUNTIME_STATE_INVALID",
                    "forbidden resource roots must be absolute",
                )
            candidate = candidate.absolute()
            if candidate not in normalized_forbidden:
                normalized_forbidden.append(candidate)
        self._forbidden_roots = tuple(normalized_forbidden)
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            context = _state_context(self.root)
            local_key = credential_store.derive_service_key(
                "local-resource-registry-v1", context=context
            )
            staging_key = credential_store.derive_service_key(
                "resource-staging-v1", context=context
            )
        except (CredentialStoreError, OSError) as error:
            raise ServiceResourceRuntimeError(
                "RESOURCE_RUNTIME_KEY_UNAVAILABLE",
                "resource runtime authentication material is unavailable",
            ) from error
        self.service_instance_id = "service-" + secrets.token_urlsafe(24)
        try:
            self.local_registry = LocalResourceGrantRegistry(
                self.root / "local-resources",
                authentication_key=local_key,
                service_instance_id=self.service_instance_id,
                gesture_verifier=gesture_verifier,
            )
            self.stager = TaskResourceStager(
                self.root / "staging",
                authentication_key=staging_key,
                service_instance_id=self.service_instance_id,
                harden_callback=harden_callback,
                require_hardening=require_hardening,
            )
        except (LocalResourceRegistryError, ResourceStagingError, OSError) as error:
            raise ServiceResourceRuntimeError(
                getattr(error, "code", "RESOURCE_RUNTIME_INITIALIZATION_FAILED"),
                "resource runtime could not be initialized safely",
            ) from error
        self._gesture_verifier = gesture_verifier
        self._hardening_available = harden_callback is not None
        self._hardening_required = require_hardening is True

    def capabilities(self) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "serviceInstanceBound": True,
            "authenticationKeyPersistedInFiles": False,
            "serviceStateSelectionBlocked": True,
            "trustedGrantIssuance": self._gesture_verifier is not None,
            "taskStaging": True,
            "productionHardeningRequired": self._hardening_required,
            "productionHardeningAvailable": self._hardening_available,
            "workerLocatorRelativeOnly": True,
            "sourcePathDisclosure": False,
            "complete": False,
        }

    def issue_local_grant(
        self,
        *,
        audience: ArtifactAudienceBinding,
        grant_request_id: str,
        raw_path: str | os.PathLike[str],
        kind: str,
        constraints: Mapping[str, Any],
        attestation_ref: str,
        max_uses: int = 1,
        expires_at: datetime | str | None = None,
    ) -> dict[str, Any]:
        selected_path = Path(raw_path).expanduser()
        if not selected_path.is_absolute() or any(
            _path_is_within(selected_path, root) for root in self._forbidden_roots
        ):
            raise ServiceResourceRuntimeError(
                "RESOURCE_RUNTIME_PATH_FORBIDDEN",
                "Card Service state cannot be selected as a task resource",
            )
        _require_request_id(grant_request_id, "grantRequestId")
        try:
            return self.local_registry.issue_grant(
                audience=audience,
                grant_request_id=grant_request_id,
                raw_path=raw_path,
                kind=kind,
                constraints=constraints,
                attestation_ref=attestation_ref,
                max_uses=max_uses,
                expires_at=expires_at,
            )
        except LocalResourceRegistryError as error:
            raise ServiceResourceRuntimeError(error.code, error.message) from error

    def consume_local_grant(
        self,
        *,
        resource_ref: str,
        audience: ArtifactAudienceBinding,
        use_id: str,
        action: str,
        expected_resource_revision_digest: str,
        expected_revocation_epoch: int,
        requested_constraints: Mapping[str, Any] | None = None,
    ) -> ResolvedLocalResource:
        _require_request_id(use_id, "useId")
        try:
            return self.local_registry.consume(
                resource_ref,
                audience,
                use_id=use_id,
                action=action,
                expected_resource_revision_digest=expected_resource_revision_digest,
                expected_revocation_epoch=expected_revocation_epoch,
                requested_constraints=requested_constraints,
            )
        except LocalResourceRegistryError as error:
            raise ServiceResourceRuntimeError(error.code, error.message) from error

    def list_local_grants(
        self,
        *,
        audience: ArtifactAudienceBinding,
        include_terminal: bool = False,
        maximum: int = 256,
    ) -> list[dict[str, Any]]:
        try:
            return self.local_registry.list_grants(
                audience,
                include_terminal=include_terminal,
                maximum=maximum,
            )
        except LocalResourceRegistryError as error:
            raise ServiceResourceRuntimeError(error.code, error.message) from error

    def revoke_local_grant(
        self,
        *,
        resource_ref: str,
        audience: ArtifactAudienceBinding,
        revocation_id: str,
        expected_revocation_epoch: int,
        attestation_ref: str,
    ) -> dict[str, Any]:
        _require_request_id(revocation_id, "revocationId")
        try:
            return self.local_registry.revoke(
                resource_ref,
                audience,
                revocation_id=revocation_id,
                expected_revocation_epoch=expected_revocation_epoch,
                attestation_ref=attestation_ref,
            )
        except LocalResourceRegistryError as error:
            raise ServiceResourceRuntimeError(error.code, error.message) from error

    def stage_local_resource(
        self,
        resource: ResolvedLocalResource,
        *,
        audience: ArtifactAudienceBinding,
        task_id: str,
        task_workspace: str | Path,
        staging_request_id: str,
        task_sandbox_id: str | None,
    ) -> StagedResource:
        _require_request_id(staging_request_id, "stagingRequestId")
        try:
            return self.stager.stage(
                resource,
                registry=self.local_registry,
                audience=audience,
                task_id=task_id,
                task_workspace=Path(task_workspace),
                staging_request_id=staging_request_id,
                task_sandbox_id=task_sandbox_id,
            )
        except ResourceStagingError as error:
            raise ServiceResourceRuntimeError(error.code, error.message) from error
