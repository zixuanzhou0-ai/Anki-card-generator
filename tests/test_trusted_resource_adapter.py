from __future__ import annotations

import json
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
