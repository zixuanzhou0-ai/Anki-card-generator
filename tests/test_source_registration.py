from __future__ import annotations

import hashlib
import base64
import json
import socket
from pathlib import Path

import pytest

from card_service.artifact_registry import ArtifactAudienceBinding
from card_service.credentials import CredentialStore, InMemoryCredentialBackend
from card_service.project_registry import ProjectRegistryError
from card_service.network_resource_registry import (
    NetworkFetchResponse,
    NetworkResourceGrantRegistry,
    PinnedNetworkFetcher,
)
from card_service.resource_runtime import ServiceResourceRuntime
from card_service.service import CardService
from card_service.study_runtime import StudyRuntime, StudyRuntimeError


OWNER = hashlib.sha256(b"source-registration-owner").hexdigest()


def audience(**changes: str) -> ArtifactAudienceBinding:
    values = {
        "owner_digest": OWNER,
        "host_id": "codex-desktop",
        "plugin_id": "speakright.study",
        "session_id": "session-1",
    }
    values.update(changes)
    return ArtifactAudienceBinding(**values)


def environment(tmp_path: Path):
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
    )
    project = runtime.create_project(
        audience=audience(),
        idempotency_key="project-1",
        learning_contract={
            "purpose": "Remember useful material",
            "targetBehavior": "Recall it without seeing the answer",
        },
        title="Trusted sources",
    )
    return resources, runtime, project


def public_resolver(_host: str, _port: int, **_kwargs: object):
    return [
        (
            socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            ("93.184.216.34", 443),
        )
    ]


class StaticPinnedFetcher(PinnedNetworkFetcher):
    def __init__(
        self,
        body: bytes,
        media_type: str = "text/html; charset=utf-8",
        *,
        content_encoding: str = "identity",
    ) -> None:
        self.body = body
        self.media_type = media_type
        self.content_encoding = content_encoding
        self.calls = 0

    def fetch(self, _resource, *, maximum_bytes=None, timeout_seconds=None):
        self.calls += 1
        assert maximum_bytes is not None and maximum_bytes >= len(self.body)
        assert timeout_seconds is not None and timeout_seconds <= 60
        return NetworkFetchResponse(
            status=200,
            headers={
                "content-type": self.media_type,
                "content-encoding": self.content_encoding,
            },
            body=self.body,
            peer_ip="93.184.216.34",
            redirect_location=None,
        )


class StaticYouTubeAcquirer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def acquire(self, source_url: str, language: str):
        self.calls.append((source_url, language))
        body = b"WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nSpacing improves recall.\n"
        return (
            {
                "schemaVersion": 1,
                "sourceKind": "youtube_subtitles",
                "videoId": "dQw4w9WgXcQ",
                "title": "Memory lesson",
                "languageCode": "en",
                "captionKind": "manual",
                "mimeType": "text/vtt",
                "contentBase64": base64.b64encode(body).decode("ascii"),
                "byteLength": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
            },
            len(body),
        )


def network_environment(tmp_path: Path, body: bytes):
    backend = InMemoryCredentialBackend()
    credentials = (tmp_path / "credentials").resolve()
    credential_store = CredentialStore(state_dir=credentials, backend=backend)
    resources = ServiceResourceRuntime(
        state_dir=(tmp_path / "resources").resolve(),
        credential_store=credential_store,
        gesture_verifier=lambda *_args: True,
        harden_callback=None,
        require_hardening=False,
    )
    network = NetworkResourceGrantRegistry(
        (tmp_path / "network").resolve(),
        authentication_key=b"source-registration-network-key-32",
        service_instance_id=resources.service_instance_id,
        gesture_verifier=lambda *_args: True,
        resolver=public_resolver,
    )
    fetcher = StaticPinnedFetcher(body)
    runtime = StudyRuntime(
        state_dir=(tmp_path / "study").resolve(),
        credential_store=credential_store,
        resource_runtime=resources,
        network_resource_registry=network,
        network_fetcher=fetcher,
    )
    project = runtime.create_project(
        audience=audience(),
        idempotency_key="network-project-1",
        learning_contract={
            "purpose": "Learn the document",
            "targetBehavior": "Recall its key ideas",
        },
        title="Trusted web source",
    )
    grant = network.issue_grant(
        audience=audience(),
        grant_request_id="web-source-1",
        raw_url="https://example.com/private/article?sig=network-canary",
        source_kind="web",
        attestation_ref="trusted-network-gesture",
        max_uses=8,
    )
    ref = {
        "schemaVersion": 1,
        "kind": "url",
        "networkResourceRef": grant["networkResourceRef"],
        "displayOrigin": grant["displayOrigin"],
        "sourceKind": grant["sourceKind"],
        "adapter": grant["adapter"],
        "publicIdentity": grant["publicIdentity"],
        "queryPresent": grant["queryPresent"],
        "sensitiveQuery": grant["sensitiveQuery"],
        "resourceRevisionDigest": grant["resourceRevisionDigest"],
        "constraints": grant["constraints"],
        "expiresAt": grant["expiresAt"],
    }
    return network, runtime, project, ref, fetcher


def input_ref(
    resources: ServiceResourceRuntime,
    path: Path,
    *,
    request_id: str,
) -> dict:
    kind = "directory" if path.is_dir() else "file"
    constraints = (
        {
            "actions": ["enumerate", "read"],
            "maxDepth": 8,
            "maxEntries": 64,
            "maxTotalBytes": 1024 * 1024,
        }
        if kind == "directory"
        else {"actions": ["read"], "maxBytes": max(1, path.stat().st_size)}
    )
    grant = resources.issue_local_grant(
        audience=audience(),
        grant_request_id=request_id,
        raw_path=path.resolve(),
        kind=kind,
        constraints=constraints,
        attestation_ref="gesture-" + request_id,
    )
    field = "directoryResourceRef" if kind == "directory" else "fileResourceRef"
    return {
        "schemaVersion": 1,
        "kind": kind,
        field: grant["resourceRef"],
        "displayName": grant["displayName"],
        "resourceRevisionDigest": grant["resourceRevisionDigest"],
        "constraints": grant["constraints"],
        "expiresAt": grant["expiresAt"],
    }


def register(
    runtime: StudyRuntime, project: dict, ref: dict, *, key: str = "register-1"
):
    return runtime.register_inputs(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=project["projectRevision"],
        idempotency_key=key,
        input_refs=[ref],
    )


def test_register_file_freezes_source_without_disclosing_local_path(
    tmp_path: Path,
) -> None:
    resources, runtime, project = environment(tmp_path)
    source = (tmp_path / "lesson.txt").resolve()
    source.write_text("reliable source evidence", encoding="utf-8")
    ref = input_ref(resources, source, request_id="file-1")

    result = register(runtime, project, ref)
    encoded = json.dumps(result, ensure_ascii=False, sort_keys=True)
    assert result["projectRevision"] == 2
    assert result["artifactStage"] == "sources_ready"
    assert result["completeness"] == {
        "state": "complete",
        "registeredSources": 1,
        "omittedSources": 0,
    }
    assert result["sources"][0]["sourceType"] == "text"
    assert result["sources"][0]["status"] == "conditional"
    assert str(source) not in encoded
    assert ref["fileResourceRef"] not in encoded
    for forbidden in ("workspaceRelativePath", "stagingRef", "registryAuthRef"):
        assert forbidden not in encoded

    public_project = runtime.get_public_project(
        project_id=project["projectId"], audience=audience(session_id="session-2")
    )
    assert public_project["workflow"]["operationState"] == "succeeded"
    assert public_project["currentTask"]["taskId"] == result["taskId"]
    assert public_project["currentTask"]["state"] == "succeeded"
    assert public_project["currentTask"]["recoverable"] is False
    assert len(public_project["latestArtifacts"]) == 1
    public_artifact = public_project["latestArtifacts"][0]
    assert public_artifact["payloadSchema"] == "study.source-asset"
    assert runtime.artifacts.resolve(
        public_artifact["artifactHandle"], audience(session_id="session-2")
    )["payloadSchema"] == "study.source-asset"
    public_page = runtime.list_public_projects(
        audience=audience(session_id="session-2"), limit=1
    )
    assert public_page["items"][0]["latestTask"]["state"] == "succeeded"
    assert public_page["items"][0]["artifactStage"] == "sources_ready"
    public_encoded = json.dumps(public_project, ensure_ascii=False, sort_keys=True)
    for forbidden in ("registryAuthRef", "blobRef", "workspace", str(source)):
        assert forbidden not in public_encoded

    envelope = runtime.artifacts.resolve(
        result["sources"][0]["sourceHandle"], audience()
    )
    payload = envelope["payload"]
    assert payload["inputRefKind"] == "file"
    assert payload["sourceIdentity"]["stable"] is True
    assert (
        runtime.artifacts.read_blob(payload["representations"][0]["blobRef"])
        == source.read_bytes()
    )
    persisted = b"\n".join(
        path.read_bytes() for path in (tmp_path / "study").rglob("*") if path.is_file()
    )
    assert str(source).encode("utf-8") not in persisted


def test_register_and_inspect_web_source_without_disclosing_complete_url(
    tmp_path: Path,
) -> None:
    body = (
        b"<html><body><h1>Spacing effect</h1><p>Retrieval strengthens memory.</p>"
        b"<script>secret()</script></body></html>"
    )
    _network, runtime, project, ref, fetcher = network_environment(tmp_path, body)
    registered = register(runtime, project, ref, key="register-web-1")
    assert fetcher.calls == 1
    source = registered["sources"][0]
    assert source["inputKind"] == "url"
    assert source["sourceType"] == "html"
    assert source["displayName"].startswith("https://example.com")
    serialized = json.dumps(registered, ensure_ascii=False, sort_keys=True)
    assert "/private/article" not in serialized
    assert "network-canary" not in serialized
    assert ref["networkResourceRef"] not in serialized
    envelope = runtime.artifacts.resolve(source["sourceHandle"], audience())
    assert runtime.artifacts.read_blob(
        envelope["payload"]["representations"][0]["blobRef"]
    ) == body

    inspected = runtime.start_source_inspection(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=registered["projectRevision"],
        idempotency_key="inspect-web-1",
        source_handles=[source["sourceHandle"]],
    )
    assert inspected["sources"][0]["sourceType"] == "html"
    assert inspected["sources"][0]["supportTier"] == "B"
    persisted = b"\n".join(
        path.read_bytes()
        for root in (tmp_path / "study", tmp_path / "network")
        for path in root.rglob("*")
        if path.is_file()
    )
    assert b"/private/article" not in persisted
    assert b"network-canary" not in persisted


def test_network_registration_rejects_cross_session_input_ref(tmp_path: Path) -> None:
    _network, runtime, project, ref, fetcher = network_environment(
        tmp_path, b"<html><body>session scoped</body></html>"
    )
    with pytest.raises(StudyRuntimeError) as mismatch:
        runtime.register_inputs(
            audience=audience(session_id="different-session"),
            project_id=project["projectId"],
            expected_project_revision=project["projectRevision"],
            idempotency_key="register-cross-session",
            input_refs=[ref],
        )
    assert mismatch.value.code in {"PROJECT_AUDIENCE_MISMATCH", "NETWORK_AUDIENCE_MISMATCH"}
    assert fetcher.calls == 0


def test_network_registration_rejects_compressed_response(tmp_path: Path) -> None:
    _network, runtime, project, ref, fetcher = network_environment(
        tmp_path, b"compressed-response"
    )
    fetcher.content_encoding = "gzip"
    with pytest.raises(StudyRuntimeError) as blocked:
        register(runtime, project, ref, key="register-compressed")
    assert blocked.value.code == "SOURCE_NETWORK_ENCODING_BLOCKED"
    assert fetcher.calls == 1


@pytest.mark.parametrize("source_kind", ["podcast", "other"])
def test_unimplemented_network_adapters_fail_before_fetch(
    tmp_path: Path, source_kind: str
) -> None:
    network, runtime, project, ref, fetcher = network_environment(
        tmp_path, b"unsupported"
    )
    grant = network.issue_grant(
        audience=audience(),
        grant_request_id=f"{source_kind}-source",
        raw_url="https://media.example/lesson",
        source_kind=source_kind,
        attestation_ref=f"{source_kind}-gesture",
        max_uses=8,
    )
    unsupported_ref = {
        **ref,
        "networkResourceRef": grant["networkResourceRef"],
        "displayOrigin": grant["displayOrigin"],
        "sourceKind": grant["sourceKind"],
        "adapter": grant["adapter"],
        "publicIdentity": grant["publicIdentity"],
        "queryPresent": grant["queryPresent"],
        "sensitiveQuery": grant["sensitiveQuery"],
        "resourceRevisionDigest": grant["resourceRevisionDigest"],
        "constraints": grant["constraints"],
        "expiresAt": grant["expiresAt"],
    }
    with pytest.raises(StudyRuntimeError) as unavailable:
        register(
            runtime,
            project,
            unsupported_ref,
            key=f"register-{source_kind}",
        )
    assert unavailable.value.code == "SOURCE_NETWORK_ADAPTER_NOT_AVAILABLE"
    assert fetcher.calls == 0


def test_register_youtube_grant_uses_only_canonical_video_identity(
    tmp_path: Path,
) -> None:
    backend = InMemoryCredentialBackend()
    credentials = (tmp_path / "credentials").resolve()
    credential_store = CredentialStore(state_dir=credentials, backend=backend)
    resources = ServiceResourceRuntime(
        state_dir=(tmp_path / "resources").resolve(),
        credential_store=credential_store,
        gesture_verifier=lambda *_args: True,
        harden_callback=None,
        require_hardening=False,
    )
    network = NetworkResourceGrantRegistry(
        (tmp_path / "network").resolve(),
        authentication_key=b"youtube-registration-network-key",
        service_instance_id=resources.service_instance_id,
        gesture_verifier=lambda *_args: True,
        resolver=public_resolver,
    )
    acquirer = StaticYouTubeAcquirer()
    runtime = StudyRuntime(
        state_dir=(tmp_path / "study").resolve(),
        credential_store=credential_store,
        resource_runtime=resources,
        network_resource_registry=network,
        youtube_subtitle_acquirer=acquirer,  # type: ignore[arg-type]
    )
    project = runtime.create_project(
        audience=audience(),
        idempotency_key="youtube-project",
        learning_contract={
            "purpose": "Learn spoken English",
            "targetBehavior": "Recall useful expressions",
            "promptLanguage": "English",
        },
        title="YouTube lesson",
    )
    grant = network.issue_grant(
        audience=audience(),
        grant_request_id="youtube-source",
        raw_url="https://youtu.be/dQw4w9WgXcQ?si=youtube-tracking-canary",
        source_kind="public_video",
        attestation_ref="youtube-gesture",
        max_uses=8,
    )
    ref = {
        "schemaVersion": 1,
        "kind": "url",
        "networkResourceRef": grant["networkResourceRef"],
        "displayOrigin": grant["displayOrigin"],
        "sourceKind": grant["sourceKind"],
        "adapter": grant["adapter"],
        "publicIdentity": grant["publicIdentity"],
        "queryPresent": grant["queryPresent"],
        "sensitiveQuery": grant["sensitiveQuery"],
        "resourceRevisionDigest": grant["resourceRevisionDigest"],
        "constraints": grant["constraints"],
        "expiresAt": grant["expiresAt"],
    }
    registered = register(runtime, project, ref, key="register-youtube")
    assert acquirer.calls == [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "English")
    ]
    assert registered["sources"][0]["sourceType"] == "subtitle"
    assert "youtube-tracking-canary" not in json.dumps(registered)
    envelope = runtime.artifacts.resolve(
        registered["sources"][0]["sourceHandle"], audience()
    )
    assert envelope["payload"]["provenance"]["adapter"] == "youtube_subtitles"
    assert envelope["payload"]["provenance"]["publicIdentity"] == "dQw4w9WgXcQ"


def test_register_directory_publishes_content_addressed_manifest(
    tmp_path: Path,
) -> None:
    resources, runtime, project = environment(tmp_path)
    source = (tmp_path / "course").resolve()
    source.mkdir()
    (source / "part-1.md").write_text("first", encoding="utf-8")
    nested = source / "nested"
    nested.mkdir()
    (nested / "part-2.txt").write_text("second", encoding="utf-8")
    ref = input_ref(resources, source, request_id="directory-1")

    result = register(runtime, project, ref)
    envelope = runtime.artifacts.resolve(
        result["sources"][0]["sourceHandle"], audience()
    )
    payload = envelope["payload"]
    assert payload["sourceType"] == "directory_manifest"
    manifest = json.loads(
        runtime.artifacts.read_blob(payload["representations"][0]["blobRef"])
    )
    assert [entry["relativeLocator"] for entry in manifest["entries"]] == [
        "nested/part-2.txt",
        "part-1.md",
    ]
    assert all(
        not Path(entry["relativeLocator"]).is_absolute()
        for entry in manifest["entries"]
    )


def test_completed_registration_is_idempotent_and_reissues_session_handle(
    tmp_path: Path,
) -> None:
    resources, runtime, project = environment(tmp_path)
    source = (tmp_path / "lesson.md").resolve()
    source.write_text("stable", encoding="utf-8")
    ref = input_ref(resources, source, request_id="file-idempotent")

    first = register(runtime, project, ref)
    second = register(runtime, project, ref)
    assert second["projectRevision"] == first["projectRevision"] == 2
    assert second["taskId"] == first["taskId"]
    assert second["sources"][0]["sourceId"] == first["sources"][0]["sourceId"]
    assert second["sources"][0]["sourceHandle"] != first["sources"][0]["sourceHandle"]
    first_envelope = runtime.artifacts.resolve(
        first["sources"][0]["sourceHandle"], audience()
    )
    second_envelope = runtime.artifacts.resolve(
        second["sources"][0]["sourceHandle"], audience()
    )
    assert second_envelope == first_envelope


def test_retry_after_task_success_commits_project_without_rereading_source(
    tmp_path: Path, monkeypatch
) -> None:
    resources, runtime, project = environment(tmp_path)
    source = (tmp_path / "lesson.txt").resolve()
    source.write_text("recoverable", encoding="utf-8")
    ref = input_ref(resources, source, request_id="file-recovery")
    original_commit = runtime.projects.commit_artifact_stage
    calls = 0

    def interrupt_once(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ProjectRegistryError(
                "PROJECT_COMMIT_INTERRUPTED", "simulated interruption"
            )
        return original_commit(**kwargs)

    monkeypatch.setattr(runtime.projects, "commit_artifact_stage", interrupt_once)
    with pytest.raises(StudyRuntimeError) as interrupted:
        register(runtime, project, ref, key="register-recovery")
    assert interrupted.value.code == "PROJECT_COMMIT_INTERRUPTED"
    source.unlink()

    recovered = register(runtime, project, ref, key="register-recovery")
    assert recovered["projectRevision"] == 2
    assert recovered["completeness"]["registeredSources"] == 1


def test_registration_rejects_changed_source_and_cross_session_ref(
    tmp_path: Path,
) -> None:
    resources, runtime, project = environment(tmp_path)
    source = (tmp_path / "lesson.txt").resolve()
    source.write_text("before", encoding="utf-8")
    ref = input_ref(resources, source, request_id="file-change")
    source.write_text("after", encoding="utf-8")
    with pytest.raises(StudyRuntimeError) as changed:
        register(runtime, project, ref, key="changed")
    assert changed.value.code == "RESOURCE_CHANGED"

    with pytest.raises(StudyRuntimeError) as wrong_session:
        runtime.register_inputs(
            audience=audience(session_id="session-2"),
            project_id=project["projectId"],
            expected_project_revision=1,
            idempotency_key="wrong-session",
            input_refs=[ref],
        )
    assert wrong_session.value.code in {
        "PROJECT_SCOPE_MISMATCH",
        "RESOURCE_SCOPE_MISMATCH",
        "RESOURCE_AUDIENCE_MISMATCH",
    }


def test_card_service_uses_managed_workspace_and_releases_capacity_reservation(
    tmp_path: Path,
) -> None:
    service = CardService(
        state_dir=(tmp_path / "service").resolve(),
        credential_backend=InMemoryCredentialBackend(),
        resource_gesture_verifier=lambda *_args: True,
        use_restricted_launcher=False,
    )
    resources = service._ensure_resource_runtime()
    source = (tmp_path / "service-lesson.txt").resolve()
    source.write_text("managed workspace", encoding="utf-8")
    ref = input_ref(resources, source, request_id="service-file")
    project = service.create_study_project(
        audience=audience(),
        idempotency_key="service-project",
        learning_contract={
            "purpose": "Remember managed input",
            "targetBehavior": "Recall it later",
        },
    )

    result = service.register_study_inputs(
        audience=audience(),
        project_id=project["projectId"],
        expected_project_revision=1,
        idempotency_key="service-register",
        input_refs=[ref],
    )

    assert result["artifactStage"] == "sources_ready"
    assert result["taskId"] not in service._workspace_reservations
    workspace = service.store.root / "sandboxes" / result["taskId"]
    assert workspace.is_dir()
