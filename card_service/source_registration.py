"""Trusted local InputRef registration into durable SourceAsset artifacts."""

from __future__ import annotations

import hashlib
import base64
import json
import mimetypes
import os
import re
import stat
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Sequence

from .artifact_registry import (
    ArtifactAudienceBinding,
    ArtifactRegistry,
    ArtifactRegistryError,
    canonical_json_bytes,
)
from .project_registry import ProjectRegistry, ProjectRegistryError
from .network_resource_registry import (
    NetworkResourceGrantRegistry,
    NetworkResourceRegistryError,
    PinnedNetworkFetcher,
    ResolvedNetworkResource,
)
from .resource_runtime import ServiceResourceRuntime
from .source_acquisition import SourceAcquisitionError, YouTubeSubtitleAcquirer
from .task_coordinator import StudyTaskCoordinator, StudyTaskError
from .task_manifests import (
    TaskManifestError,
    build_authorization_binding,
    build_capability_binding,
    build_task_input_manifest,
    build_work_reuse_manifest,
)
from .task_source_binding import TaskSourceBindingError, TaskSourceBindingRuntime


WorkspaceFactory = Callable[[str], tuple[Path, str | None]]
WorkspaceReleaser = Callable[[str], None]

_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_RESOURCE_REF_RE = re.compile(r"^resource_[A-Za-z0-9_-]{43}$")
_NETWORK_REF_RE = re.compile(r"^network_[A-Za-z0-9_-]{43}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_INPUTS = 64
_MAX_DIRECTORY_ENTRIES = 100_000
_SOURCE_ADAPTER_SET_DIGEST = hashlib.sha256(
    b"speakright.study.source-registration.adapters.v2"
).hexdigest()
_COMPONENTS = {
    "cardService": "2.0.0",
    "worker": "not-invoked",
    "sourceAdapterSetDigest": _SOURCE_ADAPTER_SET_DIGEST,
    "gateRuleSetVersion": "source-registration-v1",
}
_COMPLETENESS = {
    "state": "complete",
    "omittedLocators": [],
    "reasonCodes": [],
}


class SourceRegistrationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _validate_input_ref(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise SourceRegistrationError(
            "SOURCE_REGISTRATION_INVALID", "InputRef must be an object"
        )
    kind = value.get("kind")
    if kind == "url":
        expected = {
            "schemaVersion",
            "kind",
            "networkResourceRef",
            "displayOrigin",
            "sourceKind",
            "adapter",
            "publicIdentity",
            "queryPresent",
            "sensitiveQuery",
            "resourceRevisionDigest",
            "constraints",
            "expiresAt",
        }
        if set(value) != expected or value.get("schemaVersion") != 1:
            raise SourceRegistrationError(
                "SOURCE_REGISTRATION_INVALID", "Network InputRef fields are invalid"
            )
        if not isinstance(value.get("networkResourceRef"), str) or not _NETWORK_REF_RE.fullmatch(
            str(value["networkResourceRef"])
        ):
            raise SourceRegistrationError(
                "SOURCE_REGISTRATION_INVALID",
                "Network InputRef reference is invalid",
            )
        if value.get("sourceKind") not in {
            "public_video",
            "web",
            "podcast",
            "other",
        } or value.get("adapter") not in {"youtube", "generic_https"}:
            raise SourceRegistrationError(
                "SOURCE_REGISTRATION_INVALID", "Network InputRef adapter is invalid"
            )
        display_origin = value.get("displayOrigin")
        public_identity = value.get("publicIdentity")
        if (
            not isinstance(display_origin, str)
            or not display_origin.startswith("https://")
            or len(display_origin) > 300
            or any(ord(character) < 0x20 for character in display_origin)
            or (
                public_identity is not None
                and (
                    not isinstance(public_identity, str)
                    or not 1 <= len(public_identity) <= 300
                    or any(ord(character) < 0x20 for character in public_identity)
                )
            )
            or not isinstance(value.get("queryPresent"), bool)
            or not isinstance(value.get("sensitiveQuery"), bool)
            or not isinstance(value.get("constraints"), Mapping)
            or not isinstance(value.get("expiresAt"), str)
            or not isinstance(value.get("resourceRevisionDigest"), str)
            or not _SHA256_RE.fullmatch(str(value["resourceRevisionDigest"]))
        ):
            raise SourceRegistrationError(
                "SOURCE_REGISTRATION_INVALID",
                "Network InputRef authorization summary is invalid",
            )
        return _clone(value)
    field = "fileResourceRef" if kind == "file" else "directoryResourceRef"
    expected = {
        "schemaVersion",
        "kind",
        field,
        "displayName",
        "resourceRevisionDigest",
        "constraints",
        "expiresAt",
    }
    if kind not in {"file", "directory"} or set(value) != expected:
        raise SourceRegistrationError(
            "SOURCE_REGISTRATION_INVALID", "InputRef fields are invalid"
        )
    if value.get("schemaVersion") != 1:
        raise SourceRegistrationError(
            "SOURCE_REGISTRATION_INVALID", "InputRef schema version is unsupported"
        )
    if not isinstance(value.get(field), str) or not _RESOURCE_REF_RE.fullmatch(
        str(value[field])
    ):
        raise SourceRegistrationError(
            "SOURCE_REGISTRATION_INVALID", "InputRef resource reference is invalid"
        )
    display_name = value.get("displayName")
    if (
        not isinstance(display_name, str)
        or not display_name
        or len(display_name) > 160
        or any(ord(character) < 0x20 for character in display_name)
    ):
        raise SourceRegistrationError(
            "SOURCE_REGISTRATION_INVALID", "InputRef display name is invalid"
        )
    revision = value.get("resourceRevisionDigest")
    if not isinstance(revision, str) or not _SHA256_RE.fullmatch(revision):
        raise SourceRegistrationError(
            "SOURCE_REGISTRATION_INVALID", "InputRef revision is invalid"
        )
    if not isinstance(value.get("constraints"), Mapping) or not isinstance(
        value.get("expiresAt"), str
    ):
        raise SourceRegistrationError(
            "SOURCE_REGISTRATION_INVALID", "InputRef authorization summary is invalid"
        )
    return _clone(value)


def _source_type(display_name: str, kind: str) -> str:
    if kind == "directory":
        return "directory_manifest"
    extension = Path(display_name).suffix.casefold()
    groups = {
        "video": {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v"},
        "audio": {".mp3", ".m4a", ".wav", ".flac", ".ogg", ".opus", ".aac"},
        "subtitle": {".srt", ".vtt", ".ass", ".ssa"},
        "text": {".txt", ".text"},
        "markdown": {".md", ".markdown", ".mdx"},
        "html": {".html", ".htm"},
        "pdf": {".pdf"},
        "docx": {".docx"},
        "epub": {".epub"},
        "code": {
            ".py",
            ".js",
            ".jsx",
            ".ts",
            ".tsx",
            ".rs",
            ".go",
            ".java",
            ".kt",
            ".swift",
            ".c",
            ".h",
            ".cpp",
            ".hpp",
            ".cs",
            ".rb",
            ".php",
            ".sql",
            ".json",
            ".yaml",
            ".yml",
            ".toml",
        },
        "image": {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff"},
    }
    for name, extensions in groups.items():
        if extension in extensions:
            return name
    return "unknown"


def _media_type(display_name: str) -> str:
    guessed, _ = mimetypes.guess_type(display_name, strict=False)
    if guessed and re.fullmatch(
        r"[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+", guessed
    ):
        return guessed
    return "application/octet-stream"


def _safe_workspace_path(workspace: Path, relative_locator: str) -> Path:
    relative = PurePosixPath(relative_locator)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise SourceRegistrationError(
            "SOURCE_WORKSPACE_INVALID", "Task source locator escaped its workspace"
        )
    root = workspace.resolve(strict=True)
    root_info = root.lstat()
    if (
        not stat.S_ISDIR(root_info.st_mode)
        or stat.S_ISLNK(root_info.st_mode)
        or getattr(root_info, "st_file_attributes", 0) & 0x400
    ):
        raise SourceRegistrationError(
            "SOURCE_WORKSPACE_UNSAFE", "Task workspace is not a private directory"
        )
    unresolved = root
    for part in relative.parts:
        unresolved = unresolved / part
        info = unresolved.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise SourceRegistrationError(
                "SOURCE_WORKSPACE_UNSAFE",
                "Task source locator contains a link or reparse point",
            )
    candidate = unresolved.resolve(strict=True)
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise SourceRegistrationError(
            "SOURCE_WORKSPACE_INVALID", "Task source locator escaped its workspace"
        ) from error
    return candidate


def _directory_files(root: Path) -> list[tuple[str, Path]]:
    root_info = root.lstat()
    if (
        not stat.S_ISDIR(root_info.st_mode)
        or stat.S_ISLNK(root_info.st_mode)
        or getattr(root_info, "st_file_attributes", 0) & 0x400
    ):
        raise SourceRegistrationError(
            "SOURCE_WORKSPACE_UNSAFE", "Staged directory is not a private directory"
        )
    result: list[tuple[str, Path]] = []

    def visit(directory: Path, relative_parent: PurePosixPath) -> None:
        try:
            entries = sorted(
                os.scandir(directory), key=lambda item: item.name.casefold()
            )
        except OSError as error:
            raise SourceRegistrationError(
                "SOURCE_WORKSPACE_UNREADABLE",
                "Staged directory could not be enumerated",
            ) from error
        for entry in entries:
            relative = relative_parent / entry.name
            entry_path = Path(entry.path)
            try:
                # pathlib performs a fresh stat here. CPython's Windows
                # DirEntry cache can transiently report st_nlink=0 for a
                # freshly atomically published nested file.
                info = entry_path.lstat()
            except OSError as error:
                raise SourceRegistrationError(
                    "SOURCE_WORKSPACE_UNREADABLE",
                    "A staged source entry could not be inspected",
                ) from error
            attributes = getattr(info, "st_file_attributes", 0)
            if stat.S_ISLNK(info.st_mode) or attributes & 0x400:
                raise SourceRegistrationError(
                    "SOURCE_WORKSPACE_UNSAFE",
                    "Staged source contains a link or reparse point",
                )
            if stat.S_ISDIR(info.st_mode):
                visit(entry_path, relative)
            elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                result.append((relative.as_posix(), entry_path))
                if len(result) > _MAX_DIRECTORY_ENTRIES:
                    raise SourceRegistrationError(
                        "SOURCE_DIRECTORY_TOO_LARGE",
                        "Staged directory contains too many files",
                    )
            else:
                raise SourceRegistrationError(
                    "SOURCE_WORKSPACE_UNSAFE",
                    "Staged source contains an unsupported entry",
                )

    visit(root, PurePosixPath())
    return result


class SourceRegistrationRuntime:
    """Freeze task-bound local grants and publish authenticated SourceAssets."""

    def __init__(
        self,
        *,
        root: Path,
        service_instance_id: str,
        resources: ServiceResourceRuntime,
        artifacts: ArtifactRegistry,
        projects: ProjectRegistry,
        tasks: StudyTaskCoordinator,
        source_bindings: TaskSourceBindingRuntime,
        network_resources: NetworkResourceGrantRegistry | None = None,
        network_fetcher: PinnedNetworkFetcher | None = None,
        youtube_subtitle_acquirer: YouTubeSubtitleAcquirer | None = None,
        workspace_factory: WorkspaceFactory | None = None,
        workspace_releaser: WorkspaceReleaser | None = None,
    ) -> None:
        self._root = Path(root).absolute()
        self._root.mkdir(parents=True, exist_ok=True)
        self._service_instance_id = service_instance_id
        self._resources = resources
        self._artifacts = artifacts
        self._projects = projects
        self._tasks = tasks
        self._source_bindings = source_bindings
        self._network_resources = network_resources
        self._network_fetcher = network_fetcher or PinnedNetworkFetcher()
        self._youtube_subtitle_acquirer = (
            youtube_subtitle_acquirer or YouTubeSubtitleAcquirer()
        )
        self._workspace_factory = workspace_factory or self._default_workspace
        self._workspace_releaser = workspace_releaser or (lambda _task_id: None)

    @property
    def trusted_network_sources_available(self) -> bool:
        """Whether opaque, consent-bound HTTPS source grants can be resolved."""

        return self._network_resources is not None

    def _default_workspace(self, task_id: str) -> tuple[Path, None]:
        root = (self._root / "workspaces").absolute()
        root.mkdir(parents=True, exist_ok=True)
        workspace = (root / task_id).absolute()
        if workspace.parent != root:
            raise SourceRegistrationError(
                "SOURCE_WORKSPACE_INVALID", "Task workspace escaped its root"
            )
        workspace.mkdir(mode=0o700, exist_ok=True)
        return workspace, None

    @staticmethod
    def _operation_digest(
        project_id: str,
        expected_revision: int,
        input_refs: Sequence[Mapping[str, Any]],
        snapshot_policy: str,
    ) -> str:
        return _sha(
            canonical_json_bytes(
                {
                    "schema": "study.register-inputs.request",
                    "schemaVersion": 1,
                    "projectId": project_id,
                    "expectedProjectRevision": expected_revision,
                    "inputRefs": [dict(value) for value in input_refs],
                    "snapshotPolicy": snapshot_policy,
                }
            )
        )

    def _bundle(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project: Mapping[str, Any],
        input_refs: Sequence[Mapping[str, Any]],
        summaries: Sequence[Mapping[str, Any]],
        operation_digest: str,
        snapshot_policy: str,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], str]:
        source_revisions = [
            str(value["resourceRevisionDigest"]) for value in input_refs
        ]
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
                for value in project.get("latestArtifactRefs", [])
            ],
            "sourceSnapshotDigests": source_revisions,
            "learningContractRevision": project["learningContract"]["contractRevision"],
        }
        work, work_digest = build_work_reuse_manifest(
            action_id="register_inputs",
            subject=subject,
            component_versions=_COMPONENTS,
            service_configurations=[],
            work_partition_policy_digest=_sha(
                canonical_json_bytes(
                    {"snapshotPolicy": snapshot_policy, "inputCount": len(input_refs)}
                )
            ),
        )
        capability, capability_digest = build_capability_binding(
            [
                {
                    "kind": "fixed",
                    "capabilityId": "runtime.card_service",
                    "implementationVersionOrDigest": "2.0.0",
                    "compatibilityContractVersion": "source-registration-v1",
                }
            ]
        )
        authorization_rows = []
        for input_ref, summary in zip(input_refs, summaries, strict=True):
            field = {
                "file": "fileResourceRef",
                "directory": "directoryResourceRef",
                "url": "networkResourceRef",
            }[str(input_ref["kind"])]
            authorization_rows.append(
                {
                    "action": (
                        "access_network"
                        if input_ref["kind"] == "url"
                        else "read_source"
                    ),
                    "authorizationRecordDigest": _sha(
                        canonical_json_bytes(
                            {
                                "resourceRef": input_ref[field],
                                "resourceRevisionDigest": input_ref[
                                    "resourceRevisionDigest"
                                ],
                            }
                        )
                    ),
                    "constraintsDigest": _sha(
                        canonical_json_bytes(input_ref["constraints"])
                    ),
                    "exactScopeDigest": _sha(
                        canonical_json_bytes(
                            {
                                "kind": input_ref["kind"],
                                "resourceRef": input_ref[field],
                                "resourceRevisionDigest": input_ref[
                                    "resourceRevisionDigest"
                                ],
                                "constraints": input_ref["constraints"],
                            }
                        )
                    ),
                    "expectedRevocationEpoch": int(summary["revocationEpoch"]),
                }
            )
        authorization, authorization_digest = build_authorization_binding(
            audience=audience,
            service_instance_id=self._service_instance_id,
            bindings=authorization_rows,
        )
        task_input, input_fingerprint = build_task_input_manifest(
            action_id="register_inputs",
            work_reuse_manifest=work,
            work_reuse_digest=work_digest,
            subject=subject,
            authorization_binding_digest=authorization_digest,
            capability_binding_digest=capability_digest,
            component_versions=_COMPONENTS,
            service_bindings=[],
            operation_intent_digest=operation_digest,
            batch_policy_digest=_sha(b"study.register-inputs.batch.v1"),
        )
        return work, task_input, capability, authorization, input_fingerprint

    def _freeze(
        self,
        *,
        input_ref: Mapping[str, Any],
        staged_path: Path,
    ) -> tuple[dict[str, Any], str]:
        if input_ref["kind"] == "file":
            blob = self._artifacts.put_blob_path(
                staged_path,
                media_type=_media_type(str(input_ref["displayName"])),
            )
            representation = {
                "representationId": "representation-original",
                "kind": "original_bytes",
                "blobRef": blob,
                "extractor": {
                    "component": "source-registration",
                    "version": "1.0.0",
                },
                "confidence": None,
                "completeness": _clone(_COMPLETENESS),
            }
            return representation, str(blob["sha256"])
        entries = []
        for relative_locator, file_path in _directory_files(staged_path):
            blob = self._artifacts.put_blob_path(
                file_path,
                media_type=_media_type(relative_locator),
            )
            entries.append({"relativeLocator": relative_locator, "blobRef": blob})
        manifest = {
            "schema": "study.directory-snapshot",
            "schemaVersion": 1,
            "entries": entries,
        }
        blob = self._artifacts.put_blob(
            canonical_json_bytes(manifest),
            media_type="application/vnd.speakright.directory+json",
        )
        representation = {
            "representationId": "representation-directory-manifest",
            "kind": "structured_document",
            "blobRef": blob,
            "extractor": {
                "component": "source-registration",
                "version": "1.0.0",
            },
            "confidence": None,
            "completeness": _clone(_COMPLETENESS),
        }
        return representation, str(blob["sha256"])

    @staticmethod
    def _network_source_type(media_type: str) -> str:
        base = media_type.split(";", 1)[0].strip().casefold()
        if base in {
            "text/html",
            "application/xhtml+xml",
            "application/rss+xml",
            "application/atom+xml",
            "application/xml",
            "text/xml",
        }:
            return "html"
        if base == "text/markdown":
            return "markdown"
        if base.startswith("text/"):
            return "text"
        if base == "application/pdf":
            return "pdf"
        if base.startswith("audio/"):
            return "audio"
        if base.startswith("video/"):
            return "video"
        return "unknown"

    def _fetch_generic_network(
        self,
        resource: ResolvedNetworkResource,
        *,
        audience: ArtifactAudienceBinding,
    ) -> tuple[bytes, str]:
        if resource.source_kind not in {"web", "podcast"}:
            raise SourceRegistrationError(
                "SOURCE_NETWORK_ADAPTER_NOT_AVAILABLE",
                "This network source type does not yet have a snapshot adapter",
            )
        current = resource
        while True:
            response = self._network_resources.fetch(  # type: ignore[union-attr]
                current,
                audience,
                maximum_bytes=min(
                    int(current.constraints["maxResponseBytes"]),
                    32 * 1024 * 1024,
                ),
                timeout_seconds=min(
                    int(current.constraints["timeoutSeconds"]), 60
                ),
                fetcher=self._network_fetcher,
            )
            if 300 <= response.status < 400:
                if not response.redirect_location:
                    raise SourceRegistrationError(
                        "SOURCE_NETWORK_REDIRECT_INVALID",
                        "Network source redirect did not provide a location",
                    )
                current = self._network_resources.authorize_redirect(  # type: ignore[union-attr]
                    current,
                    audience,
                    location=response.redirect_location,
                    redirect_index=current.redirect_count + 1,
                )
                continue
            if not 200 <= response.status < 300:
                raise SourceRegistrationError(
                    "SOURCE_NETWORK_FETCH_FAILED",
                    "Network source returned an unsuccessful response",
                )
            content_encoding = str(
                response.headers.get("content-encoding") or "identity"
            ).strip().casefold()
            if content_encoding not in {"", "identity"}:
                raise SourceRegistrationError(
                    "SOURCE_NETWORK_ENCODING_BLOCKED",
                    "Compressed network source responses are not accepted",
                )
            media_type = str(
                response.headers.get("content-type") or "application/octet-stream"
            ).strip()[:200]
            if not re.fullmatch(
                r"[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+(?:\s*;[^\r\n]{0,160})?",
                media_type,
            ):
                media_type = "application/octet-stream"
            return response.body, media_type.split(";", 1)[0].strip().casefold()

    def _freeze_network(
        self,
        *,
        audience: ArtifactAudienceBinding,
        input_ref: Mapping[str, Any],
        summary: Mapping[str, Any],
        operation_digest: str,
        index: int,
        prompt_language: str,
    ) -> tuple[dict[str, Any], str, str, str, dict[str, Any]]:
        if self._network_resources is None:
            raise SourceRegistrationError(
                "SOURCE_NETWORK_RUNTIME_UNAVAILABLE",
                "Trusted network source registration is unavailable",
            )
        try:
            resource = self._network_resources.consume(
                str(input_ref["networkResourceRef"]),
                audience,
                use_id=f"register-{operation_digest[:48]}-{index}",
                expected_resource_revision_digest=str(
                    input_ref["resourceRevisionDigest"]
                ),
                expected_revocation_epoch=int(summary["revocationEpoch"]),
                requested_constraints=input_ref["constraints"],
            )
            if resource.adapter == "youtube" and resource.source_kind == "public_video":
                language = (
                    prompt_language
                    if prompt_language and prompt_language.casefold() != "auto"
                    else "English"
                )
                acquired, _transferred = self._youtube_subtitle_acquirer.acquire(
                    resource.canonical_url, language
                )
                body = base64.b64decode(
                    str(acquired["contentBase64"]), validate=True
                )
                if (
                    len(body) != int(acquired["byteLength"])
                    or hashlib.sha256(body).hexdigest() != acquired["sha256"]
                ):
                    raise SourceRegistrationError(
                        "SOURCE_NETWORK_SNAPSHOT_INVALID",
                        "YouTube subtitle snapshot failed integrity validation",
                    )
                media_type = "text/vtt"
                source_type = "subtitle"
                display_name = (
                    str(acquired.get("title") or "YouTube subtitles")[:120]
                    + ".vtt"
                )
                adapter_metadata = {
                    "adapter": "youtube_subtitles",
                    "publicIdentity": str(acquired["videoId"]),
                    "languageCode": str(acquired["languageCode"]),
                    "captionKind": str(acquired["captionKind"]),
                }
            else:
                body, media_type = self._fetch_generic_network(
                    resource, audience=audience
                )
                source_type = self._network_source_type(media_type)
                display_name = (
                    str(summary["displayOrigin"])[:140]
                    + {
                        "html": " · webpage.html",
                        "text": " · document.txt",
                        "markdown": " · document.md",
                        "pdf": " · document.pdf",
                        "audio": " · podcast-audio.bin",
                        "video": " · podcast-video.bin",
                    }.get(source_type, " · network-resource.bin")
                )[:160]
                adapter_metadata = {
                    "adapter": (
                        "podcast_https_snapshot"
                        if resource.source_kind == "podcast"
                        else str(summary["adapter"])
                    ),
                    "publicIdentity": summary.get("publicIdentity"),
                }
        except (NetworkResourceRegistryError, SourceAcquisitionError) as error:
            raise SourceRegistrationError(
                getattr(error, "code", "SOURCE_NETWORK_FETCH_FAILED"),
                getattr(error, "message", str(error)),
            ) from error
        blob = self._artifacts.put_blob(body, media_type=media_type)
        representation = {
            "representationId": "representation-network-snapshot",
            "kind": "original_bytes",
            "blobRef": blob,
            "extractor": {
                "component": "source-registration-network",
                "version": "1.0.0",
            },
            "confidence": None,
            "completeness": _clone(_COMPLETENESS),
        }
        return (
            representation,
            str(blob["sha256"]),
            source_type,
            display_name,
            adapter_metadata,
        )

    @staticmethod
    def _public_result(
        committed: Mapping[str, Any],
        publications: Sequence[tuple[Mapping[str, Any], str, Mapping[str, Any]]],
        task_id: str,
    ) -> dict[str, Any]:
        sources = []
        for envelope, handle, input_ref in publications:
            payload = envelope["payload"]
            sources.append(
                {
                    "sourceHandle": handle,
                    "sourceId": payload["sourceId"],
                    "displayName": payload["displayName"],
                    "inputKind": payload["inputRefKind"],
                    "sourceType": payload["sourceType"],
                    "sourceRevision": payload["sourceRevision"],
                    "contentSha256": payload["contentSha256"],
                    "supportTier": payload["supportTier"],
                    "status": payload["status"],
                }
            )
        return {
            "schemaVersion": 1,
            "projectId": committed["projectId"],
            "projectRevision": committed["projectRevision"],
            "artifactStage": committed["artifactStage"],
            "taskId": task_id,
            "sources": sources,
            "completeness": {
                "state": "complete",
                "registeredSources": len(sources),
                "omittedSources": 0,
            },
        }

    def register_inputs(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_id: str,
        expected_project_revision: int,
        idempotency_key: str,
        input_refs: Sequence[Mapping[str, Any]],
        snapshot_policy: str = "require_stable",
    ) -> dict[str, Any]:
        if not isinstance(idempotency_key, str) or not _IDEMPOTENCY_RE.fullmatch(
            idempotency_key
        ):
            raise SourceRegistrationError(
                "SOURCE_REGISTRATION_INVALID", "idempotencyKey is invalid"
            )
        if (
            isinstance(expected_project_revision, bool)
            or not isinstance(expected_project_revision, int)
            or expected_project_revision < 1
        ):
            raise SourceRegistrationError(
                "SOURCE_REGISTRATION_INVALID", "expectedProjectRevision is invalid"
            )
        if snapshot_policy not in {
            "require_stable",
            "allow_conditional",
            "draft_only",
        }:
            raise SourceRegistrationError(
                "SOURCE_REGISTRATION_INVALID", "snapshotPolicy is invalid"
            )
        if (
            not isinstance(input_refs, Sequence)
            or isinstance(input_refs, (str, bytes))
            or not 1 <= len(input_refs) <= _MAX_INPUTS
        ):
            raise SourceRegistrationError(
                "SOURCE_REGISTRATION_INVALID", "inputRefs count is invalid"
            )
        normalized = [_validate_input_ref(value) for value in input_refs]
        revisions = [value["resourceRevisionDigest"] for value in normalized]
        if len(revisions) != len(set(revisions)):
            raise SourceRegistrationError(
                "SOURCE_REGISTRATION_DUPLICATE",
                "inputRefs contain a duplicate snapshot",
            )
        operation_digest = self._operation_digest(
            project_id,
            expected_project_revision,
            normalized,
            snapshot_policy,
        )
        operation_id = "register:" + idempotency_key
        prior = self._projects.get_operation_result(
            audience=audience,
            project_id=project_id,
            operation_id=operation_id,
            operation_digest=operation_digest,
        )
        if prior is not None:
            publications = []
            for ref in prior["artifactRefs"]:
                envelope = self._artifacts.verify_ref(ref, audience)
                publications.append(
                    (
                        envelope,
                        self._artifacts.issue_handle(ref, audience),
                        {"kind": envelope["payload"]["inputRefKind"]},
                    )
                )
            return self._public_result(prior, publications, str(prior["taskId"]))

        project = self._projects.get_project(project_id, audience)
        if project["projectRevision"] != expected_project_revision:
            raise SourceRegistrationError(
                "PROJECT_REVISION_CONFLICT",
                "Project revision changed before input registration",
            )
        summaries = []
        for input_ref in normalized:
            field = {
                "file": "fileResourceRef",
                "directory": "directoryResourceRef",
                "url": "networkResourceRef",
            }[str(input_ref["kind"])]
            if input_ref["kind"] == "url" and self._network_resources is None:
                raise SourceRegistrationError(
                    "SOURCE_NETWORK_RUNTIME_UNAVAILABLE",
                    "Trusted network source registration is unavailable",
                )
            try:
                summary = (
                    self._network_resources.inspect(str(input_ref[field]), audience)
                    if input_ref["kind"] == "url"
                    and self._network_resources is not None
                    else self._resources.local_registry.inspect(
                        str(input_ref[field]), audience
                    )
                )
            except Exception as error:
                raise SourceRegistrationError(
                    getattr(error, "code", "SOURCE_GRANT_INVALID"),
                    getattr(error, "message", "Source grant is unavailable"),
                ) from error
            expected = (
                {
                    "sourceKind": input_ref["sourceKind"],
                    "adapter": input_ref["adapter"],
                    "displayOrigin": input_ref["displayOrigin"],
                    "publicIdentity": input_ref["publicIdentity"],
                    "queryPresent": input_ref["queryPresent"],
                    "sensitiveQuery": input_ref["sensitiveQuery"],
                    "resourceRevisionDigest": input_ref[
                        "resourceRevisionDigest"
                    ],
                    "constraints": input_ref["constraints"],
                    "expiresAt": input_ref["expiresAt"],
                }
                if input_ref["kind"] == "url"
                else {
                    "kind": input_ref["kind"],
                    "displayName": input_ref["displayName"],
                    "resourceRevisionDigest": input_ref[
                        "resourceRevisionDigest"
                    ],
                    "constraints": input_ref["constraints"],
                    "expiresAt": input_ref["expiresAt"],
                }
            )
            if any(summary.get(name) != value for name, value in expected.items()):
                raise SourceRegistrationError(
                    "SOURCE_INPUT_REF_MISMATCH",
                    "InputRef does not match the service-owned source grant",
                )
            if summary.get("state") not in {"active", "exhausted"}:
                raise SourceRegistrationError(
                    "SOURCE_GRANT_UNAVAILABLE", "Source grant is no longer available"
                )
            summaries.append(summary)

        work, task_input, capability, authorization, input_fingerprint = self._bundle(
            audience=audience,
            project=project,
            input_refs=normalized,
            summaries=summaries,
            operation_digest=operation_digest,
            snapshot_policy=snapshot_policy,
        )
        task_id = "task_register_" + operation_digest[:40]
        work_units = [
            {"workUnitId": f"source-{index:04d}", "phase": "source_registration"}
            for index in range(len(normalized))
        ]
        try:
            task = self._tasks.create_task(
                audience=audience,
                work_reuse_manifest=work,
                task_input_manifest=task_input,
                capability_binding=capability,
                authorization_binding=authorization,
                work_units=work_units,
                _task_id=task_id,
            )
        except StudyTaskError as error:
            if error.code != "TASK_ALREADY_EXISTS":
                raise SourceRegistrationError(error.code, error.message) from error
            task = self._tasks.get_task(task_id, audience)
            if task.get("inputFingerprint") != input_fingerprint:
                raise SourceRegistrationError(
                    "TASK_INPUT_MISMATCH", "Recoverable registration task input changed"
                )

        if task["state"] not in {"queued", "running", "succeeded"}:
            raise SourceRegistrationError(
                "TASK_RECOVERY_REQUIRED",
                "Input registration task requires explicit recovery",
            )
        if task["state"] == "succeeded":
            final_handles = list(task["resultHandles"])
        else:
            workspace, sandbox_id = self._workspace_factory(task_id)
            try:
                bindings = []
                for index, input_ref in enumerate(normalized):
                    bindings.append(
                        None
                        if input_ref["kind"] == "url"
                        else self._source_bindings.bind_local_input(
                            audience=audience,
                            task_id=task_id,
                            task_input_fingerprint=input_fingerprint,
                            task_workspace=workspace,
                            task_sandbox_id=sandbox_id,
                            input_ref=input_ref,
                            registration_id=(
                                "binding-"
                                + _sha(f"{operation_digest}:{index}".encode("ascii"))[
                                    :40
                                ]
                            ),
                        )
                    )
                task = self._tasks.get_task(task_id, audience)
                if task["state"] == "queued":
                    task = self._tasks.start_task(
                        task_id,
                        audience,
                        expected_revision=task["taskRevision"],
                        operation_id="start-" + operation_digest[:40],
                    )
                for index, (input_ref, binding) in enumerate(
                    zip(normalized, bindings, strict=True)
                ):
                    unit_id = f"source-{index:04d}"
                    task = self._tasks.get_task(task_id, audience)
                    unit = next(
                        item
                        for item in task["workUnits"]
                        if item["workUnitId"] == unit_id
                    )
                    if unit["state"] == "completed":
                        continue
                    if unit["state"] in {"pending", "failed"}:
                        task = self._tasks.begin_work_unit(
                            task_id,
                            audience,
                            expected_revision=task["taskRevision"],
                            operation_id=f"begin-{operation_digest[:32]}-{index}",
                            work_unit_id=unit_id,
                        )
                    elif unit["state"] != "active":
                        raise SourceRegistrationError(
                            "TASK_RECOVERY_REQUIRED",
                            "Source registration work unit is not recoverable",
                        )
                    if input_ref["kind"] == "url":
                        (
                            representation,
                            content_sha,
                            source_type,
                            display_name,
                            adapter_metadata,
                        ) = self._freeze_network(
                            audience=audience,
                            input_ref=input_ref,
                            summary=summaries[index],
                            operation_digest=operation_digest,
                            index=index,
                            prompt_language=str(
                                project["learningContract"].get(
                                    "promptLanguage", "auto"
                                )
                            ),
                        )
                        observed_at = str(
                            task.get("createdAt") or project["updatedAt"]
                        )
                        identity_method = "verified_network_snapshot"
                        provenance_kind = "network_snapshot"
                        provenance_method = "trusted_network_resource_snapshot"
                    else:
                        if not isinstance(binding, Mapping):
                            raise SourceRegistrationError(
                                "SOURCE_BINDING_INVALID",
                                "Local source binding is unavailable",
                            )
                        worker_input = self._source_bindings.worker_input(
                            str(binding["sourceBindingRef"]),
                            audience=audience,
                            task_id=task_id,
                            task_input_fingerprint=input_fingerprint,
                            task_workspace=workspace,
                        )
                        staged_path = _safe_workspace_path(
                            workspace,
                            str(worker_input["locator"]["workspaceRelativePath"]),
                        )
                        representation, content_sha = self._freeze(
                            input_ref=input_ref, staged_path=staged_path
                        )
                        source_type = _source_type(
                            str(input_ref["displayName"]), str(input_ref["kind"])
                        )
                        display_name = str(input_ref["displayName"])
                        adapter_metadata = {}
                        observed_at = str(binding["createdAt"])
                        identity_method = "verified_snapshot"
                        provenance_kind = "deterministic_extractor"
                        provenance_method = "trusted_task_staging_snapshot"
                    source_id = (
                        "source_"
                        + _sha(f"{operation_digest}:{index}".encode("ascii"))[:40]
                    )
                    support_tier = "C" if source_type == "unknown" else "B"
                    payload = {
                        "sourceId": source_id,
                        "inputRefKind": input_ref["kind"],
                        "displayName": display_name,
                        "sourceType": source_type,
                        "sourceRevision": 1,
                        "contentSha256": content_sha,
                        "sourceIdentity": {
                            "stable": True,
                            "identityMethod": identity_method,
                            "observedAt": observed_at,
                        },
                        "representations": [representation],
                        "provenance": {
                            "sourceKind": provenance_kind,
                            "producer": {
                                "component": "source-registration",
                                "version": "1.0.0",
                            },
                            "parentRefs": [],
                            "method": provenance_method,
                            "observedAt": observed_at,
                            "snapshotPolicy": snapshot_policy,
                            **adapter_metadata,
                        },
                        "supportTier": support_tier,
                        "status": "conditional",
                        "issueRefs": [],
                    }
                    publication = self._artifacts.publish_idempotent(
                        audience=audience,
                        project_id=project_id,
                        project_revision=expected_project_revision,
                        artifact_id=source_id,
                        artifact_revision=1,
                        payload_schema="study.source-asset",
                        payload_schema_version=1,
                        payload=payload,
                        producer={
                            "component": "source-registration",
                            "version": "1.0.0",
                        },
                        parents=[],
                        input_fingerprint=input_fingerprint,
                        completeness=_clone(_COMPLETENESS),
                        issue_refs=[],
                    )
                    task = self._tasks.get_task(task_id, audience)
                    self._tasks.complete_work_unit(
                        task_id,
                        audience,
                        expected_revision=task["taskRevision"],
                        operation_id=f"complete-{operation_digest[:29]}-{index}",
                        work_unit_id=unit_id,
                        result_handles=[publication.handle],
                    )
                task = self._tasks.get_task(task_id, audience)
                if task["state"] == "running":
                    task = self._tasks.succeed_task(
                        task_id,
                        audience,
                        expected_revision=task["taskRevision"],
                        operation_id="succeed-" + operation_digest[:38],
                    )
                final_handles = list(task["resultHandles"])
            finally:
                self._workspace_releaser(task_id)

        artifact_refs = []
        publications = []
        by_source = {
            "source_" + _sha(f"{operation_digest}:{index}".encode("ascii"))[:40]: value
            for index, value in enumerate(normalized)
        }
        for handle in final_handles:
            artifact_ref, envelope = self._artifacts.resolve_with_ref(handle, audience)
            artifact_refs.append(artifact_ref)
            publications.append(
                (envelope, handle, by_source[artifact_ref["artifactId"]])
            )
        committed = self._projects.commit_artifact_stage(
            audience=audience,
            project_id=project_id,
            expected_project_revision=expected_project_revision,
            operation_id=operation_id,
            operation_digest=operation_digest,
            task_id=task_id,
            artifact_stage="sources_ready",
            artifact_refs=artifact_refs,
            artifact_handles=final_handles,
        )
        publications.sort(key=lambda item: item[0]["artifactId"])
        return self._public_result(committed, publications, task_id)


__all__ = [
    "SourceRegistrationError",
    "SourceRegistrationRuntime",
    "WorkspaceFactory",
    "WorkspaceReleaser",
]
