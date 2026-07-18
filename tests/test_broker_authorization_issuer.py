from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from card_service.broker_authorization_issuer import (
    BrokerAuthorizationIssuer,
    BrokerAuthorizationIssuerError,
)
from card_service.broker_configuration import BrokerAuthorizationConfiguration
from card_service.credentials import InMemoryCredentialBackend
from card_service.service import CardService, CardServiceError, MethodPolicy
from card_service.trusted_surfaces import TrustedSurfaceManager


ROOT = Path(__file__).resolve().parents[1]
FAKE_WORKER = ROOT / "tests" / "fixtures" / "card_service" / "fake_worker.py"
FAKE_SURFACE = ROOT / "tests" / "fixtures" / "card_service" / "fake_surface.py"


def _draft(*, hermes: bool = True) -> dict[str, object]:
    profile = {
        "profileRef": "model.primary",
        "capability": "model",
        "provider": "hermes" if hermes else "openai",
        "baseUrl": "http://127.0.0.1:8317/v1" if hermes else "https://api.openai.com/v1",
        "model": "grok-4.5" if hermes else "gpt-5.6",
        "voice": "",
        "timeoutSeconds": 120,
        "maximumResponseBytes": 4096,
        "reservedCostMinorUnits": 5,
    }
    return {
        "lifetimeSeconds": 600,
        "budget": {
            "maxRemoteCalls": 8,
            "maxRequestBytes": 500_000,
            "maxResponseBytes": 8 * 1024 * 1024,
            "maxCostMinorUnits": 100,
        },
        "profiles": [profile],
        "methodBindings": {
            "runtime.extract_learning_points": {
                "model": "model.primary",
                "source": "source.youtube_subtitles",
            }
        },
        "sourceAcquisition": {
            "youtubeSubtitles": {"enabled": True, "timeoutSeconds": 30}
        },
    }


def _wait(surfaces: TrustedSurfaceManager, session_ref: str) -> dict[str, object]:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = surfaces.get_session(session_ref)
        if result["state"] not in {"created", "open"}:
            return result
        time.sleep(0.02)
    raise AssertionError("trusted broker authorization did not finish")


def test_issuer_freezes_exact_profile_budget_and_source_without_path_or_secret(tmp_path: Path) -> None:
    backend = InMemoryCredentialBackend()
    issuer = BrokerAuthorizationIssuer(
        state_dir=(tmp_path / "trusted-surfaces").resolve(),
        credential_backend=backend,
    )
    prepared = issuer.prepare(_draft())
    assert "grok-4.5" in prepared.summary
    assert "本授权合计预算" in prepared.summary
    assert "model=model.primary" in prepared.summary
    assert "source=source.youtube_subtitles" in prepared.summary
    assert "单次预留成本=5" in prepared.summary
    assert "source.youtube_subtitles" in json.dumps(prepared.value, ensure_ascii=False)

    issued = issuer.issue(session_ref="trusted-session-1", prepared=prepared.value)
    repeated = issuer.issue(session_ref="trusted-session-1", prepared=prepared.value)
    assert repeated.manifest_path == issued.manifest_path
    assert set(issued.public_summary) == {
        "schemaVersion",
        "authorizationDigest",
        "expiresAtUnixMs",
        "profileCount",
        "methodCount",
        "youtubeSubtitleAcquisition",
    }
    assert str(issued.manifest_path) not in json.dumps(issued.public_summary)

    source = issued.manifest_path.read_text(encoding="utf-8")
    assert "secret" not in source.casefold()
    configuration = BrokerAuthorizationConfiguration.load(issued.manifest_path)
    assert configuration.profiles["model.primary"].credential_revision == 0
    assert configuration.youtube_subtitles_enabled is True
    assert configuration.method_bindings["runtime.extract_learning_points"] == {
        "model": "model.primary",
        "source": "source.youtube_subtitles",
    }


def test_remote_credential_revision_is_service_resolved_and_change_invalidates_approval(tmp_path: Path) -> None:
    backend = InMemoryCredentialBackend()
    issuer = BrokerAuthorizationIssuer(
        state_dir=(tmp_path / "trusted-surfaces").resolve(),
        credential_backend=backend,
    )
    with pytest.raises(BrokerAuthorizationIssuerError) as missing:
        issuer.prepare(_draft(hermes=False))
    assert missing.value.code == "BROKER_CREDENTIAL_REQUIRED"

    first = issuer.credentials.set_secret("model.primary", "first-secret")
    prepared = issuer.prepare(_draft(hermes=False))
    assert prepared.value["profiles"][0]["credentialRevision"] == first["credentialRevision"]
    issuer.credentials.set_secret("model.primary", "second-secret")
    with pytest.raises(BrokerAuthorizationIssuerError) as changed:
        issuer.issue(session_ref="trusted-session-2", prepared=prepared.value)
    assert changed.value.code == "BROKER_CREDENTIAL_CHANGED"
    assert list(issuer.authorization_dir.glob("*.json")) == []


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update(apiKey="secret-canary"),
        lambda value: value["budget"].update(maxRemoteCalls=513),
        lambda value: value["methodBindings"]["runtime.extract_learning_points"].update(
            source="source.attacker"
        ),
        lambda value: value["sourceAcquisition"]["youtubeSubtitles"].update(enabled="yes"),
        lambda value: value["profiles"][0].update(model="grok-4.5\u202etxt.exe"),
        lambda value: value["profiles"].append(
            {
                **value["profiles"][0],
                "profileRef": "model.unused",
            }
        ),
        lambda value: value["methodBindings"]["runtime.extract_learning_points"].pop("source"),
    ],
)
def test_issuer_rejects_unknown_secret_budget_and_binding_mutations(tmp_path: Path, mutate) -> None:
    issuer = BrokerAuthorizationIssuer(
        state_dir=(tmp_path / "trusted-surfaces").resolve(),
        credential_backend=InMemoryCredentialBackend(),
    )
    draft = _draft()
    mutate(draft)
    with pytest.raises(BrokerAuthorizationIssuerError):
        issuer.prepare(draft)


def test_authenticated_surface_issues_manifest_once_and_discloses_only_summary(tmp_path: Path) -> None:
    surfaces = TrustedSurfaceManager(
        state_dir=(tmp_path / "trusted-surfaces").resolve(),
        python_path=Path(sys.executable).resolve(),
        surface_path=FAKE_SURFACE.resolve(),
        credential_backend=InMemoryCredentialBackend(),
    )
    session = surfaces.create_broker_authorization_session(_draft())
    surfaces.launch(str(session["sessionRef"]))
    result = _wait(surfaces, str(session["sessionRef"]))
    assert result["state"] == "approved"
    assert result["userGestureRecorded"] is True
    assert result["authorization"]["methodCount"] == 1
    assert str(tmp_path) not in json.dumps(result, ensure_ascii=False)
    issued = surfaces.issued_authorization(str(session["sessionRef"]))
    assert issued is not None
    manifest_path = issued.manifest_path
    assert manifest_path.is_file()
    assert len(list(manifest_path.parent.glob("*.json"))) == 1
    assert surfaces.get_session(str(session["sessionRef"])) == result


def test_card_service_hot_loads_only_the_authenticated_issued_authorization(tmp_path: Path) -> None:
    service = CardService(
        state_dir=(tmp_path / "state").resolve(),
        worker_path=FAKE_WORKER.resolve(),
        python_path=Path(sys.executable).resolve(),
        method_policies={
            "runtime.extract_learning_points": MethodPolicy(
                "extract_learning_points", 4.0, requires_broker=True
            )
        },
        credential_backend=InMemoryCredentialBackend(),
        trusted_surface_path=FAKE_SURFACE.resolve(),
        use_restricted_launcher=False,
    )
    before = service.capabilities()
    assert before["methodAvailability"]["runtime.extract_learning_points"] == {
        "available": False,
        "blocker": "model_tts_broker_not_ready",
    }
    opened = service.dispatch("system.open_broker_authorization", _draft())
    session_ref = str(opened["sessionRef"])
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = service.dispatch("system.get_trusted_surface", {"sessionRef": session_ref})
        if result["state"] not in {"created", "open"}:
            break
        time.sleep(0.02)
    else:
        raise AssertionError("Card Service did not activate the trusted authorization")
    assert result["state"] == "approved"
    assert str(tmp_path) not in json.dumps(result, ensure_ascii=False)
    after = service.capabilities()
    assert after["methodAvailability"]["runtime.extract_learning_points"] == {
        "available": True,
        "blocker": None,
    }
    assert after["modelTtsBroker"]["serviceOwnedAuthorizationResolver"] is True
    assert after["modelTtsBroker"]["pathDisclosure"] is False


def test_card_service_rejects_same_directory_manifest_replacement_before_activation(tmp_path: Path) -> None:
    backend = InMemoryCredentialBackend()
    issuer = BrokerAuthorizationIssuer(
        state_dir=(tmp_path / "state" / "trusted-surfaces").resolve(),
        credential_backend=backend,
    )
    prepared = issuer.prepare(_draft())
    issued = issuer.issue(session_ref="trusted-session-tamper", prepared=prepared.value)
    replacement = json.loads(issued.manifest_path.read_text(encoding="utf-8"))
    replacement["budget"]["maxRemoteCalls"] = 9
    from card_service.storage import AtomicJsonStore

    AtomicJsonStore._write_atomic(issued.manifest_path, replacement)
    service = CardService(
        state_dir=(tmp_path / "state").resolve(),
        worker_path=FAKE_WORKER.resolve(),
        python_path=Path(sys.executable).resolve(),
        method_policies={},
        credential_backend=backend,
        use_restricted_launcher=False,
    )
    with pytest.raises(CardServiceError) as caught:
        service._activate_broker_authorization(
            issued.manifest_path,
            expected_digest=str(issued.public_summary["authorizationDigest"]),
        )
    assert getattr(caught.value, "code", "") == "BROKER_MANIFEST_DIGEST_MISMATCH"


def test_task_keeps_the_broker_factory_captured_at_task_creation(tmp_path: Path) -> None:
    first_factory = lambda _task, _method, _request: lambda _operation, _payload: {"first": True}
    second_factory = lambda _task, _method, _request: lambda _operation, _payload: {"second": True}
    service = CardService(
        state_dir=(tmp_path / "state").resolve(),
        worker_path=FAKE_WORKER.resolve(),
        python_path=Path(sys.executable).resolve(),
        method_policies={
            "runtime.extract_learning_points": MethodPolicy(
                "extract_learning_points", 4.0, requires_broker=True
            )
        },
        broker_handler_factory=first_factory,
        broker_method_blocker=lambda _method: None,
        use_restricted_launcher=False,
    )

    class DeferredThread:
        def __init__(self, *args, **kwargs) -> None:
            self.target = kwargs.get("target")
            self.args = kwargs.get("args")

        def start(self) -> None:
            return None

    with patch("card_service.service.threading.Thread", DeferredThread):
        started = service.start_task("runtime.extract_learning_points", {"mode": "broker_typed"})
    runtime = service._tasks[str(started["id"])]
    service.broker_handler_factory = second_factory
    assert runtime.broker_handler_factory is first_factory
