from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from card_service.credentials import CredentialStore, CredentialStoreError, InMemoryCredentialBackend
from card_service.service_profiles import (
    ServiceProfileVerificationError,
    ServiceProfileVerificationRegistry,
)


FINGERPRINT_A = "a" * 64
FINGERPRINT_B = "b" * 64
AUTH_KEY = b"profile-verification-test-key-32-bytes-minimum"


class MutableBindings:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], dict[str, object]] = {}
        self.lock = threading.Lock()

    def set(
        self,
        capability: str = "model",
        profile_ref: str = "model.primary",
        *,
        fingerprint: str = FINGERPRINT_A,
        revision: int = 1,
        credential_state: str = "committed",
        secret_required: bool = True,
        secret_exists: bool = True,
    ) -> None:
        with self.lock:
            self.values[(capability, profile_ref)] = {
                "capability": capability,
                "profileRef": profile_ref,
                "configurationFingerprint": fingerprint,
                "credentialRevision": revision,
                "credentialState": credential_state,
                "secretRequired": secret_required,
                "secretExists": secret_exists,
            }

    def resolve(self, capability: str, profile_ref: str):
        with self.lock:
            value = self.values.get((capability, profile_ref))
            return dict(value) if value is not None else None


class Clock:
    def __init__(self, value: float = 1_000.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def make_registry(tmp_path: Path, bindings: MutableBindings, *, clock=None):
    return ServiceProfileVerificationRegistry(
        (tmp_path / "verifications").resolve(),
        authentication_key=AUTH_KEY,
        binding_resolver=bindings.resolve,
        clock=clock or Clock(),
    )


def record_pass(registry, operation: str = "verify-1", **overrides):
    values = {
        "operation_id": operation,
        "capability": "model",
        "profile_ref": "model.primary",
        "configuration_fingerprint": FINGERPRINT_A,
        "credential_revision": 1,
        "status": "passed",
        "latency_ms": 42,
    }
    values.update(overrides)
    return registry.record_result(**values)


def record_failure(registry, operation: str = "verify-failed", **overrides):
    values = {
        "operation_id": operation,
        "capability": "model",
        "profile_ref": "model.primary",
        "configuration_fingerprint": FINGERPRINT_A,
        "credential_revision": 1,
        "status": "failed",
        "error_code": "MODEL_UNREACHABLE",
        "retryable": True,
    }
    values.update(overrides)
    return registry.record_result(**values)


def test_unconfigured_profile_is_unknown(tmp_path: Path) -> None:
    registry = make_registry(tmp_path, MutableBindings())
    snapshot = registry.profile_snapshot("model", "model.primary")
    assert snapshot["state"] == "unknown"
    assert snapshot["reasonCode"] == "PROFILE_NOT_CONFIGURED"


def test_missing_or_uncertain_credentials_fail_closed(tmp_path: Path) -> None:
    bindings = MutableBindings()
    bindings.set(secret_exists=False)
    registry = make_registry(tmp_path, bindings)
    assert registry.profile_snapshot("model", "model.primary")["state"] == "action_required"
    bindings.set(credential_state="uncertain")
    snapshot = registry.profile_snapshot("model", "model.primary")
    assert snapshot["state"] == "blocked"
    assert snapshot["reasonCode"] == "CREDENTIAL_STATE_UNCERTAIN"


def test_registry_normalized_missing_credential_is_actionable_not_uncertain(
    tmp_path: Path,
) -> None:
    bindings = MutableBindings()
    bindings.set(credential_state="missing", secret_exists=False)
    registry = make_registry(tmp_path, bindings)
    snapshot = registry.profile_snapshot("model", "model.primary")
    assert snapshot["state"] == "action_required"
    assert snapshot["reasonCode"] == "CREDENTIAL_REQUIRED"


def test_exact_pass_is_ready_and_public_record_has_no_operation_id(tmp_path: Path) -> None:
    bindings = MutableBindings()
    bindings.set()
    registry = make_registry(tmp_path, bindings)
    result = record_pass(registry)
    snapshot = registry.profile_snapshot("model", "model.primary")
    assert snapshot["state"] == "ready"
    assert snapshot["latestVerification"]["recordId"] == result["recordId"]
    assert "operationId" not in json.dumps(result)


def test_latest_failure_overrides_older_success(tmp_path: Path) -> None:
    bindings = MutableBindings()
    bindings.set()
    registry = make_registry(tmp_path, bindings)
    first = record_pass(registry)
    second = record_failure(registry)
    snapshot = registry.profile_snapshot("model", "model.primary")
    assert second["sequence"] > first["sequence"]
    assert snapshot["state"] == "action_required"
    assert snapshot["latestVerification"]["status"] == "failed"


def test_nonretryable_failure_is_blocked(tmp_path: Path) -> None:
    bindings = MutableBindings()
    bindings.set()
    registry = make_registry(tmp_path, bindings)
    record_failure(registry, retryable=False, error_code="PROFILE_POLICY_REJECTED")
    assert registry.profile_snapshot("model", "model.primary")["state"] == "blocked"


def test_configuration_or_credential_change_makes_old_result_stale(tmp_path: Path) -> None:
    bindings = MutableBindings()
    bindings.set()
    registry = make_registry(tmp_path, bindings)
    record_pass(registry)
    bindings.set(fingerprint=FINGERPRINT_B)
    assert registry.profile_snapshot("model", "model.primary")["state"] == "stale"
    bindings.set(fingerprint=FINGERPRINT_A, revision=2)
    assert registry.profile_snapshot("model", "model.primary")["state"] == "stale"


def test_result_completed_after_binding_change_is_audit_only(tmp_path: Path) -> None:
    bindings = MutableBindings()
    bindings.set()
    registry = make_registry(tmp_path, bindings)
    bindings.set(fingerprint=FINGERPRINT_B, revision=2)
    result = record_pass(registry)
    assert result["publishState"] == "stale_at_publish"
    assert registry.profile_snapshot("model", "model.primary")["state"] == "stale"


def test_expired_success_is_stale(tmp_path: Path) -> None:
    bindings = MutableBindings()
    bindings.set()
    clock = Clock()
    registry = make_registry(tmp_path, bindings, clock=clock)
    record_pass(registry)
    clock.value += 8 * 24 * 60 * 60
    snapshot = registry.profile_snapshot("model", "model.primary")
    assert snapshot["state"] == "stale"
    assert snapshot["reasonCode"] == "VERIFICATION_EXPIRED"


def test_record_result_is_idempotent_and_conflicts_on_payload_change(tmp_path: Path) -> None:
    bindings = MutableBindings()
    bindings.set()
    registry = make_registry(tmp_path, bindings)
    first = record_pass(registry)
    repeated = record_pass(registry)
    assert repeated == first
    with pytest.raises(ServiceProfileVerificationError) as conflict:
        record_failure(registry, operation="verify-1")
    assert conflict.value.code == "PROFILE_VERIFICATION_IDEMPOTENCY_CONFLICT"


def test_concurrent_results_get_unique_monotonic_sequences(tmp_path: Path) -> None:
    bindings = MutableBindings()
    bindings.set()
    registry = make_registry(tmp_path, bindings)
    sequences: list[int] = []

    def publish(index: int) -> None:
        result = record_pass(registry, operation=f"verify-{index}", latency_ms=index)
        sequences.append(result["sequence"])

    threads = [threading.Thread(target=publish, args=(index,)) for index in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(sequences) == list(range(1, 13))


def test_authenticated_backup_is_audit_only_and_cannot_restore_old_success(tmp_path: Path) -> None:
    bindings = MutableBindings()
    bindings.set()
    registry = make_registry(tmp_path, bindings)
    record_pass(registry, operation="verify-1")
    record_failure(registry, operation="verify-2")
    path = registry._path
    value = json.loads(path.read_text(encoding="utf-8"))
    value["records"][-1]["status"] = "passed"
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    with pytest.raises(ServiceProfileVerificationError) as recovery:
        registry.profile_snapshot("model", "model.primary")
    assert recovery.value.code == "PROFILE_VERIFICATION_LEDGER_RECOVERY_REQUIRED"
    assert registry._backup_path.is_file()


def test_tampering_without_backup_fails_closed(tmp_path: Path) -> None:
    bindings = MutableBindings()
    bindings.set()
    registry = make_registry(tmp_path, bindings)
    record_pass(registry)
    registry._backup_path.unlink(missing_ok=True)
    value = json.loads(registry._path.read_text(encoding="utf-8"))
    value["sequence"] = 99
    registry._path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    with pytest.raises(ServiceProfileVerificationError) as corrupted:
        registry.profile_snapshot("model", "model.primary")
    assert corrupted.value.code == "PROFILE_VERIFICATION_LEDGER_CORRUPT"


def test_system_aggregate_is_display_only_and_preserves_each_profile(tmp_path: Path) -> None:
    bindings = MutableBindings()
    bindings.set("model", "model.primary")
    bindings.set("model", "model.secondary", fingerprint=FINGERPRINT_B, revision=4)
    registry = make_registry(tmp_path, bindings)
    record_pass(registry)
    snapshot = registry.system_snapshot([("model", "model.primary"), ("model", "model.secondary")])
    assert [item["state"] for item in snapshot["serviceProfiles"]] == ["ready", "unknown"]
    assert snapshot["serviceAggregates"]["model"] == {"total": 2, "ready": 1, "notReady": 1}


def test_secret_ref_is_stable_and_disk_metadata_has_no_secret(tmp_path: Path) -> None:
    backend = InMemoryCredentialBackend()
    store = CredentialStore(state_dir=(tmp_path / "credentials").resolve(), backend=backend)
    first = store.set_secret("model.primary", "provider-secret-canary")
    second = store.set_secret("model.primary", "replacement-secret-canary", expected_revision=1)
    assert first["secretRef"] == second["secretRef"]
    persisted = "".join(path.read_text(encoding="utf-8") for path in store.root.glob("*.json"))
    assert "provider-secret-canary" not in persisted
    assert "replacement-secret-canary" not in persisted
    assert store.secret_exists("model.primary", expected_revision=2)


def test_rollback_oauth_delete_and_replace_are_strictly_monotonic(tmp_path: Path) -> None:
    store = CredentialStore(
        state_dir=(tmp_path / "credentials").resolve(), backend=InMemoryCredentialBackend()
    )
    one = store.set_secret("model.primary", "first")
    two = store.set_oauth_material("model.primary", "oauth-token-bundle", expected_revision=1)
    three = store.rollback_secret("model.primary", "first", expected_revision=2)
    four = store.delete_secret("model.primary", expected_revision=3)
    assert [item["credentialRevision"] for item in (one, two, three, four)] == [1, 2, 3, 4]
    assert four["exists"] is False


def test_stale_expected_revision_cannot_mutate_backend(tmp_path: Path) -> None:
    backend = InMemoryCredentialBackend()
    store = CredentialStore(state_dir=(tmp_path / "credentials").resolve(), backend=backend)
    store.set_secret("model.primary", "first")
    with pytest.raises(CredentialStoreError, match="stale"):
        store.set_secret("model.primary", "should-not-be-written", expected_revision=0)
    assert backend.read("CodexStudy/model.primary") == "first"


def test_failed_mutation_burns_attempt_sequence_without_reusing_it(tmp_path: Path) -> None:
    class FailingBackend(InMemoryCredentialBackend):
        fail = False

        def write(self, target: str, secret: str) -> None:
            if self.fail and not target.endswith("__service_metadata_auth_v1"):
                raise CredentialStoreError("simulated backend failure")
            super().write(target, secret)

    backend = FailingBackend()
    store = CredentialStore(state_dir=(tmp_path / "credentials").resolve(), backend=backend)
    store.set_secret("model.primary", "first")
    backend.fail = True
    with pytest.raises(CredentialStoreError, match="simulated"):
        store.set_secret("model.primary", "second", expected_revision=1)
    assert store.metadata("model.primary")["credentialRevision"] == 1
    backend.fail = False
    result = store.set_secret("model.primary", "third", expected_revision=1)
    assert result["credentialRevision"] == 3


def test_external_secret_replacement_marks_revision_uncertain_and_blocks_resolution(tmp_path: Path) -> None:
    backend = InMemoryCredentialBackend()
    store = CredentialStore(state_dir=(tmp_path / "credentials").resolve(), backend=backend)
    store.set_secret("model.primary", "first")
    backend.write("CodexStudy/model.primary", "external-replacement")
    metadata = store.metadata("model.primary")
    assert metadata["credentialRevision"] == 2
    assert metadata["state"] == "uncertain"
    with pytest.raises(CredentialStoreError, match="stale"):
        store.resolve_secret("model.primary", expected_revision=2)
    repaired = store.set_secret("model.primary", "trusted-replacement", expected_revision=2)
    assert repaired["credentialRevision"] == 3
    assert repaired["state"] == "committed"
def test_two_store_instances_serialize_revisions_through_file_lock(tmp_path: Path) -> None:
    backend = InMemoryCredentialBackend()
    root = (tmp_path / "credentials").resolve()
    first = CredentialStore(state_dir=root, backend=backend)
    second = CredentialStore(state_dir=root, backend=backend)
    revisions: list[int] = []

    def update(store: CredentialStore, index: int) -> None:
        revisions.append(int(store.set_secret("model.shared", f"secret-{index}")["credentialRevision"]))

    threads = [
        threading.Thread(target=update, args=(first if index % 2 == 0 else second, index))
        for index in range(10)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(revisions) == list(range(1, 11))


def test_credential_metadata_tampering_fails_authentication(tmp_path: Path) -> None:
    store = CredentialStore(
        state_dir=(tmp_path / "credentials").resolve(), backend=InMemoryCredentialBackend()
    )
    store.set_secret("model.primary", "credential-canary")
    path = next(store.root.glob("*.json"))
    value = json.loads(path.read_text(encoding="utf-8"))
    value["credentialRevision"] = 99
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    with pytest.raises(CredentialStoreError, match="authentication failed"):
        store.metadata("model.primary")


def test_ambiguous_crash_recovery_never_authenticates_unknown_material(tmp_path: Path) -> None:
    backend = InMemoryCredentialBackend()
    root = (tmp_path / "credentials").resolve()
    store = CredentialStore(state_dir=root, backend=backend)
    store.set_secret("model.primary", "first")
    with store._transaction():
        store._begin(
            "model.primary",
            operation="set",
            intended_material_mac=store._material_mac("second"),
            expected_revision=1,
        )
    backend.write("CodexStudy/model.primary", "unknown-third-value")
    recovered = CredentialStore(state_dir=root, backend=backend)
    metadata = recovered.metadata("model.primary")
    assert metadata["credentialRevision"] == 2
    assert metadata["state"] == "uncertain"
    with pytest.raises(CredentialStoreError, match="stale"):
        recovered.resolve_secret("model.primary", expected_revision=2)
