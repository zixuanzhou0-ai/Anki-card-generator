from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from card_service.credentials import CredentialStore, InMemoryCredentialBackend
from card_service.service_profile_registry import (
    ServiceProfileRegistry,
    ServiceProfileRegistryError,
    profile_configuration_fingerprint,
)
from card_service.service_profiles import ServiceProfileVerificationRegistry


AUTH_KEY = b"service-profile-registry-test-key-32-bytes"
VERIFY_KEY = b"service-profile-verifier-test-key-32-bytes"


def model_config(**overrides):
    value = {
        "profileRef": "model.primary",
        "capability": "model",
        "provider": "openai",
        "baseUrl": "https://api.openai.com/v1/",
        "model": "gpt-5.6",
        "voice": "",
        "timeoutSeconds": 120,
        "maximumResponseBytes": 512 * 1024,
        "authMode": "bearer",
    }
    value.update(overrides)
    return value


def hermes_config(**overrides):
    value = model_config(
        profileRef="model.hermes",
        provider="hermes",
        baseUrl="http://127.0.0.1:8317/v1/",
        model="grok-4.5",
        authMode="none",
    )
    value.update(overrides)
    return value


def tts_config(**overrides):
    value = {
        "profileRef": "tts.primary",
        "capability": "tts",
        "provider": "openai",
        "baseUrl": "https://api.openai.com/v1",
        "model": "gpt-4o-mini-tts",
        "voice": "alloy",
        "timeoutSeconds": 120,
        "maximumResponseBytes": 600 * 1024,
        "authMode": "bearer",
    }
    value.update(overrides)
    return value


def anki_config(**overrides):
    value = {
        "profileRef": "anki.local",
        "capability": "anki_connect",
        "provider": "anki_connect",
        "baseUrl": "http://127.0.0.1:8765/",
        "apiVersion": 6,
        "timeoutSeconds": 10,
        "maximumResponseBytes": 1024 * 1024,
        "authMode": "none",
    }
    value.update(overrides)
    return value


def make_registry(tmp_path: Path, backend=None):
    backend = backend or InMemoryCredentialBackend()
    credentials = CredentialStore(
        state_dir=(tmp_path / "credentials").resolve(),
        backend=backend,
    )
    registry = ServiceProfileRegistry(
        (tmp_path / "profiles").resolve(),
        authentication_key=AUTH_KEY,
        credential_store=credentials,
    )
    return registry, credentials, backend


def test_remote_profile_can_be_saved_before_secret_and_reports_actionable_binding(tmp_path: Path) -> None:
    registry, _, _ = make_registry(tmp_path)
    saved = registry.save_profile(model_config(), expected_revision=0, operation_id="save-1")
    assert saved["profileRevision"] == 1
    assert saved["configuration"]["baseUrl"] == "https://api.openai.com/v1"
    assert saved["credentialRevision"] == 0
    assert saved["credentialState"] == "missing"
    assert saved["secretRequired"] is True
    assert saved["secretExists"] is False


def test_secret_add_replace_delete_immediately_changes_resolved_binding(tmp_path: Path) -> None:
    registry, credentials, _ = make_registry(tmp_path)
    registry.save_profile(model_config(), expected_revision=0, operation_id="save-1")
    first = credentials.set_secret("model.primary", "first")
    binding = registry.resolve_binding("model", "model.primary")
    assert binding["credentialRevision"] == first["credentialRevision"]
    assert binding["credentialState"] == "committed"
    second = credentials.set_secret("model.primary", "second", expected_revision=1)
    assert registry.resolve_binding("model", "model.primary")["credentialRevision"] == 2
    credentials.delete_secret("model.primary", expected_revision=2)
    missing = registry.resolve_binding("model", "model.primary")
    assert missing["credentialRevision"] == 3
    assert missing["credentialState"] == "missing"
    assert second["secretRef"] == first["secretRef"]


def test_credential_change_invalidates_profile_verification_without_resaving_profile(tmp_path: Path) -> None:
    registry, credentials, _ = make_registry(tmp_path)
    credentials.set_secret("model.primary", "first")
    saved = registry.save_profile(model_config(), expected_revision=0, operation_id="save-1")
    verifier = ServiceProfileVerificationRegistry(
        (tmp_path / "verifications").resolve(),
        authentication_key=VERIFY_KEY,
        binding_resolver=registry.resolve_binding,
    )
    verifier.record_result(
        operation_id="verify-1",
        capability="model",
        profile_ref="model.primary",
        configuration_fingerprint=saved["configurationFingerprint"],
        credential_revision=1,
        status="passed",
    )
    assert verifier.profile_snapshot("model", "model.primary")["state"] == "ready"
    credentials.set_secret("model.primary", "second", expected_revision=1)
    assert verifier.profile_snapshot("model", "model.primary")["state"] == "stale"


def test_hermes_profile_keeps_credential_backend_empty_and_revision_zero(tmp_path: Path) -> None:
    registry, _, backend = make_registry(tmp_path)
    saved = registry.save_profile(hermes_config(), expected_revision=0, operation_id="save-hermes")
    assert saved["credentialRevision"] == 0
    assert saved["secretRequired"] is False
    assert backend.values == {}
    assert registry.resolve_binding("model", "model.hermes")["credentialRevision"] == 0


def test_anki_loopback_profile_supports_optional_or_required_secret(tmp_path: Path) -> None:
    registry, credentials, _ = make_registry(tmp_path)
    local = registry.save_profile(anki_config(), expected_revision=0, operation_id="save-anki")
    assert local["configuration"]["baseUrl"] == "http://127.0.0.1:8765"
    assert local["secretRequired"] is False
    credentials.set_secret("anki.secure", "anki-key")
    secured = registry.save_profile(
        anki_config(profileRef="anki.secure", authMode="bearer"),
        expected_revision=0,
        operation_id="save-anki-secure",
    )
    assert secured["credentialRevision"] == 1
    assert secured["secretExists"] is True


@pytest.mark.parametrize(
    "configuration",
    [
        model_config(api_key="forbidden"),
        model_config(baseUrl="https://user:pass@api.openai.com/v1"),
        model_config(baseUrl="https://api.openai.com/v1?token=secret"),
        model_config(provider="openai-compatible", baseUrl="https://example.invalid/v1"),
        hermes_config(authMode="bearer"),
        anki_config(baseUrl="http://localhost:8765"),
        anki_config(baseUrl="http://127.0.0.1:8765/path"),
        model_config(model={"not": "text"}),
        tts_config(voice=["not", "text"]),
    ],
)
def test_unknown_secret_bearing_or_unapproved_configuration_is_rejected(tmp_path: Path, configuration) -> None:
    registry, _, _ = make_registry(tmp_path)
    with pytest.raises(ServiceProfileRegistryError):
        registry.save_profile(configuration, expected_revision=0, operation_id="save-invalid")


def test_configuration_fingerprint_is_plain_deterministic_sha256(tmp_path: Path) -> None:
    registry, _, _ = make_registry(tmp_path)
    first = registry.save_profile(model_config(), expected_revision=0, operation_id="save-1")
    expected = profile_configuration_fingerprint(model_config(baseUrl="https://api.openai.com/v1"))
    assert first["configurationFingerprint"] == expected
    assert len(expected) == 64 and set(expected) <= set("0123456789abcdef")


def test_profile_revision_cas_and_noop_semantics(tmp_path: Path) -> None:
    registry, _, _ = make_registry(tmp_path)
    first = registry.save_profile(model_config(), expected_revision=0, operation_id="save-1")
    repeated = registry.save_profile(model_config(), expected_revision=1, operation_id="save-noop")
    assert repeated["profileRevision"] == first["profileRevision"] == 1
    changed = registry.save_profile(
        model_config(model="gpt-5.6-mini"), expected_revision=1, operation_id="save-2"
    )
    assert changed["profileRevision"] == 2
    assert changed["configurationFingerprint"] != first["configurationFingerprint"]
    with pytest.raises(ServiceProfileRegistryError) as stale:
        registry.save_profile(model_config(), expected_revision=1, operation_id="save-stale")
    assert stale.value.code == "SERVICE_PROFILE_REVISION_CONFLICT"


def test_operation_id_is_idempotent_but_not_reusable_for_another_payload(tmp_path: Path) -> None:
    registry, _, _ = make_registry(tmp_path)
    first = registry.save_profile(model_config(), expected_revision=0, operation_id="save-1")
    replay = registry.save_profile(model_config(), expected_revision=0, operation_id="save-1")
    assert replay == first
    with pytest.raises(ServiceProfileRegistryError) as conflict:
        registry.save_profile(
            model_config(model="another-model"), expected_revision=0, operation_id="save-1"
        )
    assert conflict.value.code == "SERVICE_PROFILE_IDEMPOTENCY_CONFLICT"


def test_concurrent_create_has_one_winner(tmp_path: Path) -> None:
    backend = InMemoryCredentialBackend()
    first, credentials, _ = make_registry(tmp_path, backend)
    second = ServiceProfileRegistry(
        (tmp_path / "profiles").resolve(),
        authentication_key=AUTH_KEY,
        credential_store=credentials,
    )
    barrier = threading.Barrier(2)
    results: list[str] = []

    def create(registry: ServiceProfileRegistry, operation_id: str) -> None:
        barrier.wait()
        try:
            registry.save_profile(model_config(), expected_revision=0, operation_id=operation_id)
        except ServiceProfileRegistryError as error:
            results.append(error.code)
        else:
            results.append("created")

    threads = [
        threading.Thread(target=create, args=(first, "create-1")),
        threading.Thread(target=create, args=(second, "create-2")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(results) == ["SERVICE_PROFILE_REVISION_CONFLICT", "created"]


def test_delete_is_revisioned_idempotent_and_removes_binding(tmp_path: Path) -> None:
    registry, _, _ = make_registry(tmp_path)
    registry.save_profile(hermes_config(), expected_revision=0, operation_id="save-1")
    deleted = registry.delete_profile("model.hermes", expected_revision=1, operation_id="delete-1")
    assert deleted["active"] is False
    assert deleted["profileRevision"] == 2
    assert registry.resolve_binding("model", "model.hermes") is None
    replay = registry.delete_profile("model.hermes", expected_revision=1, operation_id="delete-1")
    assert replay == deleted


def test_list_profiles_is_sorted_and_hides_inactive_by_default(tmp_path: Path) -> None:
    registry, _, _ = make_registry(tmp_path)
    registry.save_profile(tts_config(), expected_revision=0, operation_id="save-tts")
    registry.save_profile(hermes_config(), expected_revision=0, operation_id="save-model")
    registry.delete_profile("model.hermes", expected_revision=1, operation_id="delete-model")
    assert [item["profileRef"] for item in registry.list_profiles()] == ["tts.primary"]
    assert [item["profileRef"] for item in registry.list_profiles(include_inactive=True)] == [
        "model.hermes", "tts.primary"
    ]


def test_public_profiles_never_return_secret_ref_operation_ids_or_secret(tmp_path: Path) -> None:
    registry, credentials, _ = make_registry(tmp_path)
    credentials.set_secret("model.primary", "credential-canary-value")
    saved = registry.save_profile(model_config(), expected_revision=0, operation_id="opaque-operation-canary")
    serialized = json.dumps(saved, ensure_ascii=False)
    assert "secretRef" not in serialized
    assert "credential-canary-value" not in serialized
    assert "opaque-operation-canary" not in serialized
    persisted = "".join(path.read_text(encoding="utf-8") for path in registry._root.rglob("*.json"))
    assert "credential-canary-value" not in persisted
    assert "opaque-operation-canary" not in persisted


def test_credential_revision_outside_json_safe_range_fails_closed(
    tmp_path: Path, monkeypatch
) -> None:
    registry, credentials, _ = make_registry(tmp_path)
    monkeypatch.setattr(credentials, "metadata", lambda _profile_ref: {
        "secretRef": f'secret_{"0" * 48}',
        "credentialRevision": 9_007_199_254_740_992,
        "exists": True,
        "state": "committed",
    })
    with pytest.raises(ServiceProfileRegistryError) as unavailable:
        registry.save_profile(model_config(), expected_revision=0, operation_id="save-1")
    assert unavailable.value.code == "SERVICE_PROFILE_CREDENTIAL_UNAVAILABLE"



def test_external_credential_replacement_propagates_uncertain_state(tmp_path: Path) -> None:
    registry, credentials, backend = make_registry(tmp_path)
    credentials.set_secret("model.primary", "first")
    registry.save_profile(model_config(), expected_revision=0, operation_id="save-1")
    backend.write("CodexStudy/model.primary", "external")
    binding = registry.resolve_binding("model", "model.primary")
    assert binding["credentialRevision"] == 2
    assert binding["credentialState"] == "uncertain"


def test_external_credential_deletion_stays_uncertain_instead_of_looking_merely_missing(
    tmp_path: Path,
) -> None:
    registry, credentials, backend = make_registry(tmp_path)
    credentials.set_secret("model.primary", "first")
    registry.save_profile(model_config(), expected_revision=0, operation_id="save-1")
    backend.delete("CodexStudy/model.primary")
    binding = registry.resolve_binding("model", "model.primary")
    assert binding["credentialRevision"] == 2
    assert binding["credentialState"] == "uncertain"
    assert binding["secretExists"] is False


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update(extra="unexpected"),
        lambda value: value["profile"].update(extra="unexpected"),
        lambda value: value["profile"]["configuration"].update(
            baseUrl="http://127.0.0.1:8317/v1/"
        ),
        lambda value: value["profile"]["credentialBindingAtSave"].update(
            credentialRevision=1
        ),
        lambda value: value["operations"].update({"not-a-digest": {
            "payloadDigest": "0" * 64, "resultRevision": 1,
        }}),
    ],
)
def test_authenticated_but_noncanonical_or_open_ended_records_are_rejected(
    tmp_path: Path, mutate
) -> None:
    registry, _, _ = make_registry(tmp_path)
    registry.save_profile(hermes_config(), expected_revision=0, operation_id="save-1")
    path = registry._path("model.hermes")
    value = json.loads(path.read_text(encoding="utf-8"))
    value.pop("authTag")
    value.pop("authKeyId")
    mutate(value)
    path.write_bytes(json.dumps(
        registry._authenticate(value), sort_keys=True, separators=(",", ":")
    ).encode("utf-8"))
    with pytest.raises(ServiceProfileRegistryError) as invalid:
        registry.get_profile("model.hermes")
    assert invalid.value.code in {
        "SERVICE_PROFILE_RECORD_INVALID", "SERVICE_PROFILE_RECORD_CORRUPT",
    }



def test_replay_after_a_later_revision_fails_instead_of_returning_the_wrong_result(
    tmp_path: Path,
) -> None:
    registry, _, _ = make_registry(tmp_path)
    registry.save_profile(hermes_config(), expected_revision=0, operation_id="save-1")
    registry.save_profile(
        hermes_config(model="grok-4.5-fast"), expected_revision=1, operation_id="save-2"
    )
    with pytest.raises(ServiceProfileRegistryError) as superseded:
        registry.save_profile(hermes_config(), expected_revision=0, operation_id="save-1")
    assert superseded.value.code == "SERVICE_PROFILE_IDEMPOTENCY_RESULT_SUPERSEDED"


def test_revision_exhaustion_blocks_update_and_delete(tmp_path: Path) -> None:
    registry, _, _ = make_registry(tmp_path)
    registry.save_profile(hermes_config(), expected_revision=0, operation_id="save-1")
    path = registry._path("model.hermes")
    value = json.loads(path.read_text(encoding="utf-8"))
    value.pop("authTag")
    value.pop("authKeyId")
    value["profile"]["profileRevision"] = 9_007_199_254_740_991
    path.write_bytes(json.dumps(
        registry._authenticate(value), sort_keys=True, separators=(",", ":")
    ).encode("utf-8"))
    with pytest.raises(ServiceProfileRegistryError) as update_exhausted:
        registry.save_profile(
            hermes_config(model="grok-4.5-fast"),
            expected_revision=9_007_199_254_740_991,
            operation_id="save-exhausted",
        )
    assert update_exhausted.value.code == "SERVICE_PROFILE_REVISION_EXHAUSTED"
    with pytest.raises(ServiceProfileRegistryError) as delete_exhausted:
        registry.delete_profile(
            "model.hermes",
            expected_revision=9_007_199_254_740_991,
            operation_id="delete-exhausted",
        )
    assert delete_exhausted.value.code == "SERVICE_PROFILE_REVISION_EXHAUSTED"


def test_list_rejects_an_authenticated_record_transplanted_to_another_identity(
    tmp_path: Path,
) -> None:
    registry, _, _ = make_registry(tmp_path)
    registry.save_profile(hermes_config(), expected_revision=0, operation_id="save-1")
    raw = registry._path("model.hermes").read_bytes()
    transplanted = registry._profiles_root / "ff" / f'{"0" * 64}.json'
    transplanted.parent.mkdir()
    transplanted.write_bytes(raw)
    with pytest.raises(ServiceProfileRegistryError) as corrupted:
        registry.list_profiles()
    assert corrupted.value.code == "SERVICE_PROFILE_RECORD_CORRUPT"



def test_record_tampering_fails_and_does_not_fall_back_to_backup(tmp_path: Path) -> None:
    registry, _, _ = make_registry(tmp_path)
    registry.save_profile(hermes_config(), expected_revision=0, operation_id="save-1")
    registry.save_profile(
        hermes_config(model="grok-4.5-fast"), expected_revision=1, operation_id="save-2"
    )
    path = registry._path("model.hermes")
    value = json.loads(path.read_text(encoding="utf-8"))
    value["profile"]["configuration"]["model"] = "tampered"
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    with pytest.raises(ServiceProfileRegistryError) as corrupted:
        registry.get_profile("model.hermes")
    assert corrupted.value.code in {"SERVICE_PROFILE_RECORD_CORRUPT", "SERVICE_PROFILE_RECORD_INVALID"}
    assert path.with_suffix(path.suffix + ".bak").is_file()


def test_registry_reloads_authenticated_profile(tmp_path: Path) -> None:
    registry, credentials, _ = make_registry(tmp_path)
    expected = registry.save_profile(hermes_config(), expected_revision=0, operation_id="save-1")
    reloaded = ServiceProfileRegistry(
        (tmp_path / "profiles").resolve(),
        authentication_key=AUTH_KEY,
        credential_store=credentials,
    )
    assert reloaded.get_profile("model.hermes") == expected
