from __future__ import annotations

import json
import socket
import sys
import time
from pathlib import Path

import pytest

from card_service.artifact_registry import ArtifactAudienceBinding
from card_service.credentials import InMemoryCredentialBackend
from card_service.service import CardService, CardServiceError


ROOT = Path(__file__).resolve().parents[1]
FAKE_SURFACE = ROOT / "tests" / "fixtures" / "card_service" / "fake_surface.py"
OWNER = "a" * 64


def audience() -> ArtifactAudienceBinding:
    return ArtifactAudienceBinding(
        owner_digest=OWNER,
        host_id="codex-desktop",
        plugin_id="speakright.study",
        session_id="trusted-picker-session",
    )


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


def test_card_service_turns_trusted_picker_result_into_opaque_grant(
    tmp_path: Path,
) -> None:
    state_dir = (tmp_path / "service-state").resolve()
    service = CardService(
        state_dir=state_dir,
        python_path=Path(sys.executable).resolve(),
        trusted_surface_path=FAKE_SURFACE.resolve(),
        credential_backend=InMemoryCredentialBackend(),
        use_restricted_launcher=False,
    )
    opened = service.open_local_resource_picker(
        audience=audience(),
        grant_request_id="trusted-picker-grant",
        kind="file",
        constraints={"actions": ["read"], "maxBytes": 1024},
    )
    session_ref = str(opened["sessionRef"])
    request_path = service.trusted_surfaces.sessions_dir / f"{session_ref}.json"
    selected_path = (
        request_path.parents[3] / f"trusted-picker-{session_ref}.txt"
    ).resolve()
    selected_path.write_text("trusted adapter content", encoding="utf-8")
    request_text = request_path.read_text(encoding="utf-8")
    assert str(selected_path) not in request_text
    assert "selectedPath" not in request_text

    deadline = time.monotonic() + 5
    result: dict[str, object] = {}
    while time.monotonic() < deadline:
        result = service.complete_local_resource_picker(session_ref)
        if result.get("state") not in {"created", "open"}:
            break
        time.sleep(0.02)
    assert result["state"] == "selected"
    assert result["resourceSelection"] == {
        "kind": "file",
        "displayName": "Selected file",
        "pathDisclosure": False,
    }
    grant = result["resourceGrant"]
    assert isinstance(grant, dict)
    assert grant["kind"] == "file"
    assert str(grant["resourceRef"]).startswith("resource_")
    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)
    assert str(selected_path) not in serialized
    assert "privatePayload" not in serialized
    assert "attestation" not in serialized.lower()
    assert service.trusted_surfaces.selected_local_resource(session_ref) is None
    assert service.complete_local_resource_picker(session_ref) == result
    assert "system.request_source_grant" in service.capabilities()["systemMethods"]

    runtime = service._ensure_resource_runtime()
    resolved = runtime.consume_local_grant(
        resource_ref=str(grant["resourceRef"]),
        audience=audience(),
        use_id="trusted-picker-use",
        action="read",
        expected_resource_revision_digest=str(grant["resourceRevisionDigest"]),
        expected_revocation_epoch=int(grant["revocationEpoch"]),
        requested_constraints={"actions": ["read"], "maxBytes": 1024},
    )
    assert resolved.path == selected_path



def test_card_service_rejects_non_json_picker_constraints_before_launch(
    tmp_path: Path,
) -> None:
    service = CardService(
        state_dir=(tmp_path / "service-state").resolve(),
        python_path=Path(sys.executable).resolve(),
        trusted_surface_path=FAKE_SURFACE.resolve(),
        credential_backend=InMemoryCredentialBackend(),
        use_restricted_launcher=False,
    )

    for invalid_constraints in (
        {"actions": ["read"], "maxBytes": float("nan")},
        {"actions": ["read"], "opaque": object()},
    ):
        with pytest.raises(CardServiceError) as failure:
            service.open_local_resource_picker(
                audience=audience(),
                grant_request_id="invalid-picker-constraints",
                kind="file",
                constraints=invalid_constraints,
            )
        assert failure.value.code == "RESOURCE_CONSTRAINT_INVALID"

    assert not list(service.trusted_surfaces.sessions_dir.glob("*.json"))


def test_card_service_turns_trusted_url_input_into_opaque_network_grant(
    tmp_path: Path,
) -> None:
    service = CardService(
        state_dir=(tmp_path / "service-state").resolve(),
        python_path=Path(sys.executable).resolve(),
        trusted_surface_path=FAKE_SURFACE.resolve(),
        credential_backend=InMemoryCredentialBackend(),
        use_restricted_launcher=False,
        network_resource_resolver=public_resolver,
    )
    opened = service.request_network_resource_grant(
        audience=audience(),
        grant_request_id="trusted-network-1",
        source_kind="web",
    )
    assert opened["state"] == "open"
    deadline = time.monotonic() + 5
    result: dict[str, object] = {}
    while time.monotonic() < deadline:
        result = service.request_network_resource_grant(
            audience=audience(),
            grant_request_id="trusted-network-1",
            source_kind="web",
        )
        if result.get("state") not in {"created", "open"}:
            break
        time.sleep(0.02)
    assert result["state"] == "selected"
    grant = result["networkGrant"]
    assert isinstance(grant, dict)
    assert str(grant["networkResourceRef"]).startswith("network_")
    assert grant["displayOrigin"] == "https://example.com"
    assert grant["sourceKind"] == "web"
    assert grant["sensitiveQuery"] is True
    assert grant["remainingUses"] == 8
    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)
    assert "surface-canary" not in serialized
    assert "/study" not in serialized
    assert "privatePayload" not in serialized
    persisted = "\n".join(
        path.read_text(encoding="utf-8")
        for path in service.store.root.rglob("*.json")
    )
    assert "surface-canary" not in persisted
    assert "/study" not in persisted
    assert service.trusted_surfaces.selected_network_resource(
        str(opened["sessionRef"])
    ) is None
    assert "system.request_network_grant" in service.capabilities()["systemMethods"]
    assert service.request_network_resource_grant(
        audience=audience(),
        grant_request_id="trusted-network-1",
        source_kind="web",
    ) == result
    with pytest.raises(CardServiceError) as conflict:
        service.request_network_resource_grant(
            audience=audience(),
            grant_request_id="trusted-network-1",
            source_kind="podcast",
        )
    assert conflict.value.code == "NETWORK_GRANT_REQUEST_CONFLICT"


def test_network_grant_is_revocable_through_the_trusted_manager(
    tmp_path: Path,
) -> None:
    service = CardService(
        state_dir=(tmp_path / "service-state").resolve(),
        python_path=Path(sys.executable).resolve(),
        trusted_surface_path=FAKE_SURFACE.resolve(),
        credential_backend=InMemoryCredentialBackend(),
        use_restricted_launcher=False,
        network_resource_resolver=public_resolver,
    )
    opened = service.request_network_resource_grant(
        audience=audience(),
        grant_request_id="network-revoke-source",
        source_kind="web",
    )
    deadline = time.monotonic() + 5
    grant_result: dict[str, object] = {}
    while time.monotonic() < deadline:
        grant_result = service.request_network_resource_grant(
            audience=audience(),
            grant_request_id="network-revoke-source",
            source_kind="web",
        )
        if grant_result.get("state") not in {"created", "open"}:
            break
        time.sleep(0.02)
    grant = grant_result["networkGrant"]
    assert isinstance(grant, dict)

    manager = service.request_authorization_revocation(audience=audience())
    session_ref = str(manager["authorizationSessionRef"])
    manager_request = (
        service.trusted_surfaces.sessions_dir / f"{session_ref}.json"
    ).read_text(encoding="utf-8")
    assert str(grant["networkResourceRef"]) not in manager_request
    assert "surface-canary" not in manager_request
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        manager = service.request_authorization_revocation(
            audience=audience(), authorization_session_ref=session_ref
        )
        if manager.get("state") not in {"open", "created", "processing"}:
            break
        time.sleep(0.02)
    assert manager["state"] == "completed"
    assert manager["revokedCount"] == 1
    assert manager["results"] == [
        {"kind": "network_resource", "disposition": "revoked"}
    ]
    inspected = service._ensure_network_resource_registry().inspect(
        str(grant["networkResourceRef"]), audience()
    )
    assert inspected["state"] == "revoked"
    assert str(grant["networkResourceRef"]) not in json.dumps(manager)


def test_public_resource_request_is_idempotent_and_scope_is_service_owned(
    tmp_path: Path,
) -> None:
    state_dir = (tmp_path / "service-state").resolve()
    service = CardService(
        state_dir=state_dir,
        python_path=Path(sys.executable).resolve(),
        trusted_surface_path=FAKE_SURFACE.resolve(),
        credential_backend=InMemoryCredentialBackend(),
        use_restricted_launcher=False,
    )
    first = service.request_local_resource_picker(
        audience=audience(), grant_request_id="public-source-1", kind="file"
    )
    session_ref = str(first["sessionRef"])
    request_path = service.trusted_surfaces.sessions_dir / f"{session_ref}.json"
    selected_path = (
        request_path.parents[3] / f"trusted-picker-{session_ref}.txt"
    ).resolve()
    selected_path.write_text("public adapter content", encoding="utf-8")

    deadline = time.monotonic() + 5
    result: dict[str, object] = {}
    while time.monotonic() < deadline:
        result = service.request_local_resource_picker(
            audience=audience(), grant_request_id="public-source-1", kind="file"
        )
        if result.get("state") not in {"created", "open"}:
            break
        time.sleep(0.02)
    assert result["state"] == "selected"
    assert service.request_local_resource_picker(
        audience=audience(), grant_request_id="public-source-1", kind="file"
    ) == result
    grant = result["resourceGrant"]
    assert isinstance(grant, dict)
    assert grant["constraints"] == {
        "actions": ["read"], "maxBytes": 32 * 1024 * 1024 * 1024
    }
    assert grant["remainingUses"] == 8

    with pytest.raises(CardServiceError) as conflict:
        service.request_local_resource_picker(
            audience=audience(), grant_request_id="public-source-1", kind="directory"
        )
    assert conflict.value.code == "RESOURCE_GRANT_REQUEST_CONFLICT"

    with pytest.raises(CardServiceError) as invalid:
        service.request_local_resource_picker(
            audience=audience(), grant_request_id="../invalid", kind="file"
        )
    assert invalid.value.code == "RESOURCE_GRANT_REQUEST_INVALID"
