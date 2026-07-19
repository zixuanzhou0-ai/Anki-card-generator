from __future__ import annotations

import threading
import time
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from card_service.artifact_registry import ArtifactAudienceBinding
from card_service.credentials import InMemoryCredentialBackend
from card_service.service import CardService, CardServiceError


ROOT = Path(__file__).resolve().parents[1]
FAKE_SURFACE = ROOT / "tests" / "fixtures" / "card_service" / "fake_surface.py"


class _Ledger:
    def __init__(self) -> None:
        self.calls: list[set[str]] = []

    def revoke_profiles(self, profile_refs: set[str]) -> int:
        self.calls.append(set(profile_refs))
        return len(profile_refs)


def test_active_broker_authorization_summary_and_revoke_are_bounded() -> None:
    ledger = _Ledger()
    runtime = SimpleNamespace(
        configuration=SimpleNamespace(
            manifest_digest="sha256:" + "a" * 64,
            method_bindings={
                "generate": {"model": "model.primary", "tts": "tts.primary"},
                "discover": {"source": "source.youtube", "model": "model.primary"},
            },
            expires_at_unix_ms=int(time.time() * 1000) + 60_000,
        ),
        ledger=ledger,
    )
    service = object.__new__(CardService)
    service._broker_runtime_lock = threading.RLock()
    service._active_broker_runtime = runtime
    service.broker_handler_factory = object()
    service.broker_method_blocker = object()
    service.broker_runtime_capabilities = {
        "authorizationManifestDigest": runtime.configuration.manifest_digest
    }

    summary = service._active_broker_authorization_summary()
    assert summary == {
        "schemaVersion": 1,
        "kind": "broker_authorization",
        "authorizationDigest": runtime.configuration.manifest_digest,
        "capabilities": ["model", "source", "tts"],
        "profileCount": 3,
        "expiresAtUnixMs": runtime.configuration.expires_at_unix_ms,
        "state": "active",
    }

    revoked = service._revoke_active_broker_authorization()
    assert revoked == {
        "schemaVersion": 1,
        "kind": "broker_authorization",
        "state": "revoked",
        "revokedProfileCount": 3,
        "newlyRevokedProfileCount": 3,
    }
    assert ledger.calls == [{"model.primary", "tts.primary", "source.youtube"}]
    assert service._active_broker_runtime is None
    assert service.broker_handler_factory is None
    assert service.broker_method_blocker is None
    assert service.broker_runtime_capabilities == {}
    assert service._active_broker_authorization_summary() is None
    assert service._revoke_active_broker_authorization()["state"] == "not_found"


def test_stale_broker_revocation_cannot_revoke_new_authorization() -> None:
    ledger = _Ledger()
    runtime = SimpleNamespace(
        configuration=SimpleNamespace(
            manifest_digest="sha256:" + "b" * 64,
            method_bindings={"generate": {"model": "model.new"}},
            expires_at_unix_ms=int(time.time() * 1000) + 60_000,
        ),
        ledger=ledger,
    )
    service = object.__new__(CardService)
    service._broker_runtime_lock = threading.RLock()
    service._active_broker_runtime = runtime
    service.broker_handler_factory = object()
    service.broker_method_blocker = object()
    service.broker_runtime_capabilities = {
        "authorizationManifestDigest": runtime.configuration.manifest_digest
    }
    prior_handler = service.broker_handler_factory
    prior_blocker = service.broker_method_blocker
    prior_capabilities = service.broker_runtime_capabilities

    result = service._revoke_active_broker_authorization(
        expected_authorization_digest="sha256:" + "a" * 64
    )

    assert result["state"] == "stale"
    assert ledger.calls == []
    assert service._active_broker_runtime is runtime
    assert service.broker_handler_factory is prior_handler
    assert service.broker_method_blocker is prior_blocker
    assert service.broker_runtime_capabilities is prior_capabilities


def test_trusted_authorization_manager_revokes_selected_resource_without_disclosing_ref(
    tmp_path: Path,
) -> None:
    service = CardService(
        state_dir=(tmp_path / "state").resolve(),
        python_path=Path(sys.executable).resolve(),
        method_policies={},
        credential_backend=InMemoryCredentialBackend(),
        trusted_surface_path=FAKE_SURFACE.resolve(),
        use_restricted_launcher=False,
    )
    audience = ArtifactAudienceBinding(
        owner_digest="a" * 64,
        host_id="codex-desktop",
        plugin_id="anki-study-agent-plugin",
        session_id="authorization-manager-session",
    )
    opened_picker = service.open_local_resource_picker(
        audience=audience,
        grant_request_id="authorization-manager-resource",
        kind="file",
        constraints={"actions": ["read"], "maxBytes": 1024},
    )
    picker_ref = str(opened_picker["sessionRef"])
    picker_request = service.trusted_surfaces.sessions_dir / f"{picker_ref}.json"
    selected_path = (
        picker_request.parents[3] / f"trusted-picker-{picker_ref}.txt"
    ).resolve()
    selected_path.write_text("authorization manager", encoding="utf-8")
    deadline = time.monotonic() + 5
    while True:
        grant_result = service.complete_local_resource_picker(picker_ref)
        if grant_result.get("state") not in {"created", "open"}:
            break
        if time.monotonic() >= deadline:
            raise AssertionError("trusted resource fixture did not finish")
        time.sleep(0.02)
    resource_ref = str(grant_result["resourceGrant"]["resourceRef"])

    opened = service.request_authorization_revocation(audience=audience)
    authorization_ref = str(opened["authorizationSessionRef"])
    request_text = (
        service.trusted_surfaces.sessions_dir / f"{authorization_ref}.json"
    ).read_text(encoding="utf-8")
    assert resource_ref not in request_text
    assert "locator" not in request_text

    other_audience = ArtifactAudienceBinding(
        owner_digest="b" * 64,
        host_id=audience.host_id,
        plugin_id=audience.plugin_id,
        session_id=audience.session_id,
    )
    with pytest.raises(CardServiceError) as cross_audience:
        service.request_authorization_revocation(
            audience=other_audience,
            authorization_session_ref=authorization_ref,
        )
    assert cross_audience.value.code == "AUTHORIZATION_SESSION_NOT_FOUND"

    deadline = time.monotonic() + 5
    while True:
        completed = service.request_authorization_revocation(
            audience=audience,
            authorization_session_ref=authorization_ref,
        )
        if completed["state"] not in {"created", "open"}:
            break
        if time.monotonic() >= deadline:
            raise AssertionError("authorization manager fixture did not finish")
        time.sleep(0.02)
    assert completed == {
        "schemaVersion": 1,
        "authorizationSessionRef": authorization_ref,
        "state": "completed",
        "availableCount": 1,
        "selectedCount": 1,
        "revokedCount": 1,
        "alreadyConsumedCount": 0,
        "alreadyRevokedCount": 0,
        "notFoundCount": 0,
        "failedCount": 0,
        "results": [
            {"kind": "local_resource", "disposition": "revoked"}
        ],
    }
    assert resource_ref not in json.dumps(completed, sort_keys=True)
    listed = service._ensure_resource_runtime().list_local_grants(
        audience=audience,
        include_terminal=True,
        maximum=10,
    )
    assert listed[0]["state"] == "revoked"
    assert service.request_authorization_revocation(
        audience=audience,
        authorization_session_ref=authorization_ref,
    ) == completed
