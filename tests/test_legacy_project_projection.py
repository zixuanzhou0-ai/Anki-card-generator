from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import pytest

from card_service.artifact_registry import ArtifactAudienceBinding, ArtifactRegistry, canonical_json_bytes
from card_service.legacy_project_projection import (
    LEGACY_PROJECT_PROJECTION_SCHEMA_SHA256,
    LegacyProjectProjectionError,
    LegacyProjectProjectionPublisher,
    LegacyResourceBinding,
    sanitize_legacy_project,
)


AUTH_KEY = bytes(range(32))
OWNER = hashlib.sha256(b"legacy-owner").hexdigest()
INPUT_FINGERPRINT = hashlib.sha256(b"legacy-input").hexdigest()
RAW_URL = "https://reader:private@example.com/watch?v=abc&signature=SECRET-CANARY"
VIDEO_PATH = r"E:\private\cache\source.mp4"
SUBTITLE_PATH = r"E:\private\cache\source.en.srt"
SEGMENT_PATH = r"E:\private\cache\segment-001.mp4"


def audience() -> ArtifactAudienceBinding:
    return ArtifactAudienceBinding(
        owner_digest=OWNER,
        host_id="codex-desktop",
        plugin_id="speakright.study",
        session_id="session-legacy",
    )


def make_registry(root: Path) -> ArtifactRegistry:
    return ArtifactRegistry(root, authentication_key=AUTH_KEY, service_instance_id="legacy-service")


def publish_support(
    registry: ArtifactRegistry,
    *,
    artifact_id: str,
    schema: str,
    project_id: str = "project-legacy",
) -> dict[str, Any]:
    publication = registry.publish(
        audience=audience(),
        project_id=project_id,
        project_revision=1,
        artifact_id=artifact_id,
        artifact_revision=1,
        payload_schema=schema,
        payload_schema_version=1,
        payload={"kind": artifact_id, "digest": hashlib.sha256(artifact_id.encode()).hexdigest()},
        producer={"component": "test-suite", "version": "1.0.0"},
        parents=[],
        input_fingerprint=INPUT_FINGERPRINT,
        completeness={"state": "complete", "omittedLocators": [], "reasonCodes": []},
        issue_refs=[],
    )
    return dict(publication.artifact_ref)


def support_refs(registry: ArtifactRegistry, *, project_id: str = "project-legacy") -> dict[str, Any]:
    return {
        "source_asset_refs": [
            publish_support(registry, artifact_id="source-1", schema="study.source-asset", project_id=project_id)
        ],
        "media_ledger_ref": publish_support(
            registry, artifact_id="media-1", schema="study.media-ledger", project_id=project_id
        ),
        "reliability_manifest_ref": publish_support(
            registry, artifact_id="reliability-1", schema="study.reliability-manifest", project_id=project_id
        ),
        "learning_point_inventory_ref": publish_support(
            registry, artifact_id="inventory-1", schema="study.learning-point-inventory", project_id=project_id
        ),
        "generation_diagnostics_ref": publish_support(
            registry, artifact_id="diagnostics-1", schema="study.generation-diagnostics", project_id=project_id
        ),
    }


def project() -> dict[str, Any]:
    return {
        "schema_version": 12,
        "id": "legacy-project-1",
        "title": "Reliable phrases",
        "source_mode": "url",
        "source_url": RAW_URL,
        "source_info": {
            "title": "Source title",
            "webpage_url": RAW_URL,
            "Authorization": "Bearer hidden-auth-token-value-1234567890",
        },
        "video_path": VIDEO_PATH,
        "subtitle_path": SUBTITLE_PATH,
        "language": "en",
        "level": "B1",
        "template_id": "video_v12",
        "content_toggles": {"video": True, "tts": True},
        "card_types": ["review"],
        "card_generation_diagnostics": {"generated_card_count": 1, "items": []},
        "reliability_manifest": {
            "schema_version": 1,
            "decision": "pass",
            "model_provider": "must-be-removed-only-when-config-field",
        },
        "learning_point_inventory": [{"id": "lp-1", "exact_span": "in good shape"}],
        "segments": [
            {
                "id": "segment-1",
                "english": "They are in good shape.",
                "video_path": SEGMENT_PATH,
                "media": {"video": "segment-001.mp4", "audio": "segment-001.mp3"},
                "enabled": True,
            }
        ],
        "warnings": [],
        "created_at": 1_750_000_000,
        "api_config": {"provider": "xai", "api_key": "SECRET-CANARY"},
        "tts_config": {"voice": "private", "access_token": "SECRET-CANARY"},
        "ai_model_provider": "xai",
        "ai_model_name": "grok-private",
    }


def binding(pointer: str, raw: str, kind: str, number: int) -> LegacyResourceBinding:
    common = {
        "slot_id": f"slot-{number}",
        "json_pointer": pointer,
        "kind": kind,
        "internal_resource_binding_id": f"resource-binding-{number}",
        "resource_revision_digest": hashlib.sha256(f"revision-{number}".encode()).hexdigest(),
        "resource_value_digest": hashlib.sha256(raw.encode()).hexdigest(),
    }
    if kind == "source_network":
        return LegacyResourceBinding(
            **common,
            canonical_request_digest=hashlib.sha256(b"GET example.com/watch redacted").hexdigest(),
            display_origin="https://example.com",
            query_redaction_digest=hashlib.sha256(b"v,signature").hexdigest(),
        )
    return LegacyResourceBinding(**common)


def bindings() -> list[LegacyResourceBinding]:
    return [
        binding("#/source_url", RAW_URL, "source_network", 1),
        binding("#/source_info/webpage_url", RAW_URL, "source_network", 2),
        binding("#/video_path", VIDEO_PATH, "source_file", 3),
        binding("#/subtitle_path", SUBTITLE_PATH, "source_file", 4),
        binding("#/segments/0/video_path", SEGMENT_PATH, "media_file", 5),
    ]


def publish_projection(registry: ArtifactRegistry, **changes: Any):
    options: dict[str, Any] = {
        "audience": audience(),
        "project_id": "project-legacy",
        "project_revision": 1,
        "artifact_id": "legacy-projection",
        "artifact_revision": 1,
        "legacy_project": project(),
        "resource_bindings": bindings(),
        "service_bindings": [
            {
                "capability": "model",
                "profileRef": "model.hermes-grok-4.5",
                "configurationFingerprint": hashlib.sha256(b"model-profile").hexdigest(),
            },
            {
                "capability": "tts",
                "profileRef": "tts.gemini",
                "configurationFingerprint": hashlib.sha256(b"tts-profile").hexdigest(),
            },
        ],
        "input_fingerprint": INPUT_FINGERPRINT,
        "forbidden_canaries": ["SECRET-CANARY"],
        **support_refs(registry),
    }
    options.update(changes)
    return LegacyProjectProjectionPublisher(registry).publish(**options)


def persisted_bytes(root: Path) -> bytes:
    return b"\n".join(path.read_bytes() for path in root.rglob("*") if path.is_file())


def assert_error(code: str, action) -> None:
    with pytest.raises(LegacyProjectProjectionError) as captured:
        action()
    assert captured.value.code == code


def test_publish_preserves_export_data_but_never_persists_raw_resources_or_secrets(tmp_path: Path) -> None:
    registry = make_registry(tmp_path / "registry")
    publication = publish_projection(registry)
    bridge = LegacyProjectProjectionPublisher(registry)
    internal = bridge.resolve_internal(publication.handle, audience())
    projection = internal["projection"]
    projected = projection["project"]

    assert projected["segments"][0]["english"] == "They are in good shape."
    assert projected["segments"][0]["enabled"] is True
    assert projected["segments"][0]["media"]["video"] == "segment-001.mp4"
    assert projected["reliability_manifest"]["decision"] == "pass"
    assert projected["learning_point_inventory"][0]["id"] == "lp-1"
    assert projected["source_url"] == {"$resourceSlot": "slot-1"}
    assert projected["segments"][0]["video_path"] == {"$resourceSlot": "slot-5"}
    assert "api_config" not in projected
    assert "tts_config" not in projected
    assert "ai_model_provider" not in projected
    assert "Authorization" not in projected["source_info"]
    assert internal["record"]["payload"]["projectionSchemaSha256"] == LEGACY_PROJECT_PROJECTION_SCHEMA_SHA256

    raw = persisted_bytes(tmp_path / "registry")
    for forbidden in (RAW_URL, VIDEO_PATH, SUBTITLE_PATH, SEGMENT_PATH, "SECRET-CANARY", "grok-private"):
        assert forbidden.encode() not in raw


def test_public_summary_hides_blob_refs_internal_bindings_profile_refs_and_project(tmp_path: Path) -> None:
    registry = make_registry(tmp_path / "registry")
    publication = publish_projection(registry)
    summary = LegacyProjectProjectionPublisher(registry).public_summary(publication.handle, audience())
    encoded = json.dumps(summary, sort_keys=True)
    assert summary["resourceSlotCount"] == 5
    assert summary["serviceCapabilities"] == ["model", "tts"]
    for forbidden in (
        "projectProjection", "internalResourceBindingId", "profileRef", "configurationFingerprint",
        "resource-binding", "segments", RAW_URL,
    ):
        assert forbidden not in encoded


@pytest.mark.parametrize(
    "mutate,code",
    [
        (lambda values: values[1:], "LEGACY_RESOURCE_BINDING_MISSING"),
        (
            lambda values: [
                *values,
                binding("#/document_path", r"E:\unused\document.pdf", "source_file", 99),
            ],
            "LEGACY_RESOURCE_BINDING_UNUSED",
        ),
        (
            lambda values: [
                *values[:2],
                binding("#/video_path", "different value", "source_file", 3),
                *values[3:],
            ],
            "LEGACY_RESOURCE_BINDING_MISMATCH",
        ),
        (
            lambda values: [
                *values[:2],
                binding("#/video_path", VIDEO_PATH, "source_network", 3),
                *values[3:],
            ],
            "LEGACY_RESOURCE_BINDING_MISMATCH",
        ),
    ],
)
def test_missing_unused_or_mismatched_resource_binding_fails_before_blob_write(
    tmp_path: Path, mutate, code: str
) -> None:
    registry = make_registry(tmp_path / "registry")
    refs = support_refs(registry)
    bridge = LegacyProjectProjectionPublisher(registry)
    assert_error(
        code,
        lambda: bridge.publish(
            audience=audience(), project_id="project-legacy", project_revision=1,
            artifact_id="legacy-projection", artifact_revision=1, legacy_project=project(),
            resource_bindings=mutate(bindings()), input_fingerprint=INPUT_FINGERPRINT, **refs,
        ),
    )
    assert not any((tmp_path / "registry" / "blobs").rglob("*"))


def test_secret_canary_under_innocent_field_fails_before_persistence(tmp_path: Path) -> None:
    registry = make_registry(tmp_path / "registry")
    raw_project = project()
    raw_project["warning"] = "sk-abcdefghijklmnopqrstuvwxyz1234567890"
    assert_error(
        "LEGACY_SECRET_CANARY_DETECTED",
        lambda: sanitize_legacy_project(raw_project, resource_bindings=bindings()),
    )
    assert not any((tmp_path / "registry" / "blobs").rglob("*"))


@pytest.mark.parametrize(
    "change,code",
    [
        ({"unexpected_runtime_field": True}, "LEGACY_PROJECTION_SCHEMA_INVALID"),
        ({"warning": {"$resourceSlot": "slot-1"}}, "LEGACY_RESOURCE_MARKER_FORGED"),
        ({"warning": "open https://example.net/private now"}, "LEGACY_RESOURCE_VALUE_FORBIDDEN"),
        ({"warning": "ftp://example.net/private"}, "LEGACY_RESOURCE_VALUE_FORBIDDEN"),
    ],
)
def test_closed_schema_marker_forgery_and_embedded_locator_are_rejected(
    change: Mapping[str, Any], code: str
) -> None:
    raw_project = project()
    raw_project.update(change)
    assert_error(code, lambda: sanitize_legacy_project(raw_project, resource_bindings=bindings()))



def test_normal_colon_text_is_preserved_but_traversal_path_requires_a_binding() -> None:
    safe = project()
    safe["warning"] = "Note:example remains ordinary learning content"
    projection, _, _ = sanitize_legacy_project(safe, resource_bindings=bindings())
    assert projection["project"]["warning"] == "Note:example remains ordinary learning content"

    unsafe = project()
    unsafe["warning"] = "../private/result.json"
    assert_error(
        "LEGACY_RESOURCE_BINDING_MISSING",
        lambda: sanitize_legacy_project(unsafe, resource_bindings=bindings()),
    )


def test_network_display_origin_is_strictly_redacted_and_well_formed() -> None:
    for invalid in (
        "https://reader@example.com",
        "https://example.com?signature=secret",
        "https://example.com:invalid",
        "https://exa mple.com",
    ):
        resources = bindings()
        resources[0] = replace(resources[0], display_origin=invalid)
        assert_error(
            "LEGACY_RESOURCE_BINDING_INVALID",
            lambda resources=resources: sanitize_legacy_project(project(), resource_bindings=resources),
        )


def test_secret_and_configuration_fields_are_removed_recursively_with_audit_paths() -> None:
    raw_project = project()
    raw_project["segments"][0]["metadata"] = {
        "access_token": "SECRET-CANARY",
        "safe": "kept",
        "oauth_state": "SECRET-CANARY",
        "token": "SECRET-CANARY",
    }
    projection, removed, _ = sanitize_legacy_project(
        raw_project, resource_bindings=bindings(), forbidden_canaries=["SECRET-CANARY"]
    )
    assert projection["project"]["segments"][0]["metadata"] == {"safe": "kept"}
    assert "#/api_config" in removed
    assert "#/segments/0/metadata/access_token" in removed
    assert "#/segments/0/metadata/oauth_state" in removed
    assert "#/segments/0/metadata/token" in removed


def test_wrong_schema_cross_project_revoked_and_missing_optional_support_fail_before_blob(tmp_path: Path) -> None:
    for case in ("wrong-schema", "cross-project", "revoked", "missing-optional"):
        root = tmp_path / case
        registry = make_registry(root / "registry")
        refs = support_refs(registry)
        if case == "wrong-schema":
            refs["media_ledger_ref"] = publish_support(
                registry, artifact_id="wrong-media", schema="study.source-asset"
            )
        elif case == "cross-project":
            refs["media_ledger_ref"] = publish_support(
                registry, artifact_id="foreign-media", schema="study.media-ledger", project_id="other-project"
            )
        elif case == "revoked":
            registry.revoke(refs["media_ledger_ref"], audience(), reason_code="test_revocation")
        else:
            refs["reliability_manifest_ref"] = None
        assert_error(
            "LEGACY_SUPPORT_ARTIFACT_INVALID",
            lambda refs=refs: LegacyProjectProjectionPublisher(registry).publish(
                audience=audience(), project_id="project-legacy", project_revision=1,
                artifact_id="legacy-projection", artifact_revision=1, legacy_project=project(),
                resource_bindings=bindings(), input_fingerprint=INPUT_FINGERPRINT, **refs,
            ),
        )
        assert not any((root / "registry" / "blobs").rglob("*"))


def test_service_binding_is_closed_unique_and_contains_no_secret(tmp_path: Path) -> None:
    fingerprint = hashlib.sha256(b"profile").hexdigest()
    bad_values = [
        [{"capability": "model", "profileRef": "model.one", "configurationFingerprint": fingerprint, "apiKey": "x"}],
        [
            {"capability": "model", "profileRef": "model.one", "configurationFingerprint": fingerprint},
            {"capability": "model", "profileRef": "model.two", "configurationFingerprint": fingerprint},
        ],
    ]
    for index, value in enumerate(bad_values):
        registry = make_registry(tmp_path / f"registry-{index}")
        refs = support_refs(registry)
        assert_error(
            "LEGACY_PROJECTION_SCHEMA_INVALID",
            lambda value=value: LegacyProjectProjectionPublisher(registry).publish(
                audience=audience(), project_id="project-legacy", project_revision=1,
                artifact_id="legacy-projection", artifact_revision=1, legacy_project=project(),
                resource_bindings=bindings(), service_bindings=value,
                input_fingerprint=INPUT_FINGERPRINT, **refs,
            ),
        )


def test_tampered_projection_blob_is_rejected(tmp_path: Path) -> None:
    registry = make_registry(tmp_path / "registry")
    publication = publish_projection(registry)
    envelope = registry.resolve(publication.handle, audience())
    blob_ref = envelope["payload"]["payload"]["projectProjection"]
    blob_path = registry._blob_path(blob_ref["sha256"])
    raw = bytearray(blob_path.read_bytes())
    raw[-2] = ord(" ") if raw[-2] != ord(" ") else ord("x")
    blob_path.write_bytes(bytes(raw))
    assert_error(
        "LEGACY_PROJECTION_BLOB_INVALID",
        lambda: LegacyProjectProjectionPublisher(registry).resolve_internal(publication.handle, audience()),
    )


def test_depth_and_non_json_values_fail_closed() -> None:
    too_deep: dict[str, Any] = project()
    cursor: dict[str, Any] = {}
    too_deep["material_context"] = cursor
    for _ in range(70):
        child: dict[str, Any] = {}
        cursor["nested"] = child
        cursor = child
    assert_error(
        "LEGACY_PROJECTION_LIMIT_EXCEEDED",
        lambda: sanitize_legacy_project(too_deep, resource_bindings=bindings()),
    )
    invalid = project()
    invalid["warning"] = object()
    assert_error(
        "LEGACY_PROJECTION_SCHEMA_INVALID",
        lambda: sanitize_legacy_project(invalid, resource_bindings=bindings()),
    )
from dataclasses import replace
