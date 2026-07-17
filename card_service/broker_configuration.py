from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .broker import BrokerBudget, BrokerReservationLedger, ModelTtsBroker
from .broker_runtime import (
    AuthorizedProviderCall,
    TaskBrokerAuthorization,
    make_task_broker_handler,
)
from .credentials import CredentialBackend, CredentialStore, CredentialStoreError
from .provider_egress import ProviderProfile, ProviderTransport
from .runtime_manifest import assert_stable_path, canonical_bytes


AUTHORIZATION_SCHEMA = "study.card-service.broker-authorization"
MAX_AUTHORIZATION_MANIFEST_BYTES = 256 * 1024
MAX_AUTHORIZATION_LIFETIME_MS = 24 * 60 * 60 * 1000
METHOD_CAPABILITIES = {
    "runtime.test_model": frozenset({"model"}),
    "runtime.test_tts": frozenset({"tts"}),
    "runtime.extract_learning_points": frozenset({"model"}),
    "runtime.generate_cards": frozenset({"model"}),
    "runtime.generate_legacy_project": frozenset({"model"}),
    "runtime.export_apkg": frozenset({"tts"}),
}


class BrokerConfigurationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _exact_keys(value: Any, expected: set[str], *, code: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise BrokerConfigurationError(code, "Broker authorization manifest shape is invalid")
    return value


def _bounded_int(value: Any, *, minimum: int, maximum: int, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise BrokerConfigurationError(code, "Broker authorization integer is outside the allowed range")
    return value


def operation_for_profile(profile: ProviderProfile) -> str:
    if profile.capability == "tts":
        return "tts.synthesize"
    if profile.provider in {"openai", "openai-compatible", "xai", "hermes"}:
        return "model.openai_chat"
    if profile.provider == "anthropic":
        return "model.anthropic_messages"
    if profile.provider == "gemini":
        return "model.gemini_content"
    raise BrokerConfigurationError("BROKER_PROFILE_INVALID", "Provider profile has no managed operation")


def profile_configuration_fingerprint(profile: ProviderProfile) -> str:
    value = {
        "schema": "study.card-service.provider-profile",
        "schemaVersion": 1,
        "profileRef": profile.profile_ref,
        "capability": profile.capability,
        "provider": profile.provider,
        "baseUrl": profile.base_url,
        "model": profile.model,
        "voice": profile.voice,
        "timeoutSeconds": profile.timeout_seconds,
        "maximumResponseBytes": profile.maximum_response_bytes,
        "operation": operation_for_profile(profile),
        "providerEgressPolicyVersion": 1,
    }
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


@dataclass(frozen=True)
class ConfiguredProviderBinding:
    profile: ProviderProfile
    configuration_fingerprint: str
    credential_revision: int
    reserved_cost_minor_units: int

    @property
    def operation(self) -> str:
        return operation_for_profile(self.profile)


@dataclass(frozen=True)
class BrokerAuthorizationConfiguration:
    manifest_digest: str
    operation_intent_ref: str
    expires_at_unix_ms: int
    budget: BrokerBudget
    profiles: Mapping[str, ConfiguredProviderBinding]
    method_bindings: Mapping[str, Mapping[str, str]]

    @classmethod
    def load(cls, path: str | Path, *, now_unix_ms: int | None = None) -> "BrokerAuthorizationConfiguration":
        candidate = Path(path)
        if not candidate.is_absolute():
            raise BrokerConfigurationError("BROKER_MANIFEST_PATH_RELATIVE", "Broker manifest path must be absolute")
        try:
            resolved = assert_stable_path(candidate)
            source = resolved.read_bytes()
        except (OSError, RuntimeError) as error:
            raise BrokerConfigurationError("BROKER_MANIFEST_UNAVAILABLE", "Broker manifest is unavailable") from error
        if not source or len(source) > MAX_AUTHORIZATION_MANIFEST_BYTES:
            raise BrokerConfigurationError("BROKER_MANIFEST_INVALID", "Broker manifest is empty or too large")
        try:
            value = json.loads(source)
        except ValueError as error:
            raise BrokerConfigurationError("BROKER_MANIFEST_INVALID", "Broker manifest is invalid JSON") from error
        if not isinstance(value, dict) or canonical_bytes(value) != source:
            raise BrokerConfigurationError("BROKER_MANIFEST_NONCANONICAL", "Broker manifest must use canonical JSON")
        _exact_keys(
            value,
            {
                "schema",
                "schemaVersion",
                "operationIntentRef",
                "expiresAtUnixMs",
                "budget",
                "profiles",
                "methodBindings",
            },
            code="BROKER_MANIFEST_INVALID",
        )
        if value["schema"] != AUTHORIZATION_SCHEMA or value["schemaVersion"] != 1:
            raise BrokerConfigurationError("BROKER_MANIFEST_VERSION", "Broker manifest version is unsupported")
        now = int(time.time() * 1000) if now_unix_ms is None else int(now_unix_ms)
        expires = _bounded_int(
            value["expiresAtUnixMs"],
            minimum=1,
            maximum=2**63 - 1,
            code="BROKER_AUTHORIZATION_INVALID",
        )
        if expires <= now:
            raise BrokerConfigurationError("BROKER_AUTHORIZATION_EXPIRED", "Broker authorization has expired")
        if expires > now + MAX_AUTHORIZATION_LIFETIME_MS:
            raise BrokerConfigurationError(
                "BROKER_AUTHORIZATION_INVALID",
                "Broker authorization lifetime exceeds the allowed maximum",
            )
        operation_intent_ref = str(value["operationIntentRef"])
        from .broker_runtime import INTENT_REF_PATTERN

        if INTENT_REF_PATTERN.fullmatch(operation_intent_ref) is None:
            raise BrokerConfigurationError("BROKER_INTENT_INVALID", "Broker operation intent reference is invalid")
        budget_value = _exact_keys(
            value["budget"],
            {"maxRemoteCalls", "maxRequestBytes", "maxResponseBytes", "maxCostMinorUnits"},
            code="BROKER_BUDGET_INVALID",
        )
        budget = BrokerBudget(
            _bounded_int(budget_value["maxRemoteCalls"], minimum=1, maximum=4096, code="BROKER_BUDGET_INVALID"),
            _bounded_int(
                budget_value["maxRequestBytes"], minimum=1, maximum=64 * 1024 * 1024, code="BROKER_BUDGET_INVALID"
            ),
            _bounded_int(
                budget_value["maxResponseBytes"], minimum=1, maximum=2 * 1024 * 1024 * 1024, code="BROKER_BUDGET_INVALID"
            ),
            _bounded_int(budget_value["maxCostMinorUnits"], minimum=0, maximum=1_000_000_000, code="BROKER_BUDGET_INVALID"),
        )
        profile_values = value["profiles"]
        if not isinstance(profile_values, list) or not 1 <= len(profile_values) <= 16:
            raise BrokerConfigurationError("BROKER_PROFILE_INVALID", "Broker profiles are invalid")
        profiles: dict[str, ConfiguredProviderBinding] = {}
        for raw in profile_values:
            item = _exact_keys(
                raw,
                {
                    "profileRef",
                    "capability",
                    "provider",
                    "baseUrl",
                    "model",
                    "voice",
                    "timeoutSeconds",
                    "maximumResponseBytes",
                    "configurationFingerprint",
                    "credentialRevision",
                    "reservedCostMinorUnits",
                },
                code="BROKER_PROFILE_INVALID",
            )
            try:
                profile = ProviderProfile(
                    profile_ref=str(item["profileRef"]),
                    capability=str(item["capability"]),
                    provider=str(item["provider"]),
                    base_url=str(item["baseUrl"]),
                    model=str(item["model"]),
                    voice=str(item["voice"]),
                    timeout_seconds=item["timeoutSeconds"],
                    maximum_response_bytes=item["maximumResponseBytes"],
                )
            except RuntimeError as error:
                raise BrokerConfigurationError("BROKER_PROFILE_INVALID", "Broker provider profile is invalid") from error
            if profile.profile_ref in profiles:
                raise BrokerConfigurationError("BROKER_PROFILE_DUPLICATE", "Broker profile reference is duplicated")
            fingerprint = str(item["configurationFingerprint"])
            if fingerprint != profile_configuration_fingerprint(profile):
                raise BrokerConfigurationError("BROKER_PROFILE_FINGERPRINT_MISMATCH", "Broker profile fingerprint is invalid")
            revision = _bounded_int(
                item["credentialRevision"], minimum=0, maximum=2**63 - 1, code="BROKER_PROFILE_INVALID"
            )
            if (profile.provider == "hermes" and revision != 0) or (profile.provider != "hermes" and revision == 0):
                raise BrokerConfigurationError("BROKER_PROFILE_INVALID", "Broker credential revision is invalid")
            profiles[profile.profile_ref] = ConfiguredProviderBinding(
                profile=profile,
                configuration_fingerprint=fingerprint,
                credential_revision=revision,
                reserved_cost_minor_units=_bounded_int(
                    item["reservedCostMinorUnits"],
                    minimum=0,
                    maximum=1_000_000_000,
                    code="BROKER_PROFILE_INVALID",
                ),
            )
        method_values = value["methodBindings"]
        if not isinstance(method_values, dict):
            raise BrokerConfigurationError("BROKER_METHOD_BINDING_INVALID", "Broker method bindings are invalid")
        method_bindings: dict[str, Mapping[str, str]] = {}
        for method, raw_bindings in method_values.items():
            allowed = METHOD_CAPABILITIES.get(str(method))
            if allowed is None or not isinstance(raw_bindings, dict) or set(raw_bindings) != set(allowed):
                raise BrokerConfigurationError("BROKER_METHOD_BINDING_INVALID", "Broker method binding is invalid")
            resolved_bindings: dict[str, str] = {}
            for capability, raw_profile_ref in raw_bindings.items():
                profile_ref = str(raw_profile_ref)
                binding = profiles.get(profile_ref)
                if binding is None or binding.profile.capability != capability:
                    raise BrokerConfigurationError("BROKER_METHOD_BINDING_INVALID", "Broker method profile is invalid")
                resolved_bindings[capability] = profile_ref
            method_bindings[str(method)] = resolved_bindings
        return cls(
            manifest_digest="sha256:" + hashlib.sha256(source).hexdigest(),
            operation_intent_ref=operation_intent_ref,
            expires_at_unix_ms=expires,
            budget=budget,
            profiles=profiles,
            method_bindings=method_bindings,
        )


class ServiceBrokerRuntime:
    def __init__(
        self,
        *,
        configuration: BrokerAuthorizationConfiguration,
        credential_store: CredentialStore,
        ledger: BrokerReservationLedger,
        transport_overrides: Mapping[str, ProviderTransport] | None = None,
    ) -> None:
        overrides = dict(transport_overrides or {})
        if set(overrides) - set(configuration.profiles):
            raise BrokerConfigurationError("BROKER_TRANSPORT_INVALID", "Broker transport override has no profile")
        self.configuration = configuration
        self.credential_store = credential_store
        self.ledger = ledger
        self.broker = ModelTtsBroker(credential_store=credential_store, ledger=ledger)
        self.transport_overrides = overrides

    @classmethod
    def from_manifest(
        cls,
        manifest_path: str | Path,
        *,
        state_dir: str | Path,
        credential_backend: CredentialBackend | None = None,
        transport_overrides: Mapping[str, ProviderTransport] | None = None,
        now_unix_ms: int | None = None,
    ) -> "ServiceBrokerRuntime":
        root = Path(state_dir)
        if not root.is_absolute():
            raise BrokerConfigurationError("BROKER_STATE_PATH_RELATIVE", "Broker state directory must be absolute")
        resolved = root.resolve()
        authorization_root = (resolved / "trusted-surfaces" / "authorizations").resolve()
        candidate = Path(manifest_path)
        if not candidate.is_absolute():
            raise BrokerConfigurationError("BROKER_MANIFEST_PATH_RELATIVE", "Broker manifest path must be absolute")
        try:
            resolved_manifest = candidate.resolve(strict=True)
        except OSError as error:
            raise BrokerConfigurationError("BROKER_MANIFEST_UNAVAILABLE", "Broker manifest is unavailable") from error
        if resolved_manifest.parent != authorization_root:
            raise BrokerConfigurationError(
                "BROKER_MANIFEST_OUTSIDE_TRUSTED_SURFACE",
                "Broker manifest must come from the trusted authorization directory",
            )
        configuration = BrokerAuthorizationConfiguration.load(resolved_manifest, now_unix_ms=now_unix_ms)
        credentials = CredentialStore(
            state_dir=(resolved / "trusted-surfaces" / "credentials").resolve(),
            backend=credential_backend,
        )
        ledger = BrokerReservationLedger((resolved / "broker" / "reservation-ledger-v1.json").resolve())
        return cls(
            configuration=configuration,
            credential_store=credentials,
            ledger=ledger,
            transport_overrides=transport_overrides,
        )

    def method_blocker(self, method: str) -> str | None:
        if int(time.time() * 1000) >= self.configuration.expires_at_unix_ms:
            return "broker_authorization_expired"
        bindings = self.configuration.method_bindings.get(method)
        if bindings is None:
            return "broker_authorization_missing"
        for profile_ref in bindings.values():
            binding = self.configuration.profiles[profile_ref]
            if binding.profile.provider == "hermes":
                continue
            try:
                metadata = self.credential_store.metadata(profile_ref)
            except CredentialStoreError:
                return "broker_profile_unavailable"
            if (
                metadata.get("exists") is not True
                or int(metadata.get("credentialRevision") or 0) != binding.credential_revision
            ):
                return "broker_profile_unavailable"
        return None

    def handler_factory(self, task_id: str, method: str, _request: dict[str, Any]):
        blocker = self.method_blocker(method)
        if blocker is not None:
            raise BrokerConfigurationError("BROKER_AUTHORIZATION_UNAVAILABLE", blocker)
        method_profiles = self.configuration.method_bindings[method]
        operations: dict[str, AuthorizedProviderCall] = {}
        for profile_ref in method_profiles.values():
            binding = self.configuration.profiles[profile_ref]
            operations[binding.operation] = AuthorizedProviderCall(
                profile=binding.profile,
                credential_revision=binding.credential_revision,
                reserved_cost_minor_units=binding.reserved_cost_minor_units,
                transport=self.transport_overrides.get(profile_ref),
            )
        authorization = TaskBrokerAuthorization(
            operation_intent_ref=self.configuration.operation_intent_ref,
            budget=self.configuration.budget,
            operations=operations,
            expires_at_unix_ms=self.configuration.expires_at_unix_ms,
        )
        return make_task_broker_handler(task_id=task_id, authorization=authorization, broker=self.broker)

    def capabilities(self) -> dict[str, Any]:
        return {
            "serviceOwnedAuthorizationResolver": True,
            "authorizationManifestDigest": self.configuration.manifest_digest,
            "authorizationExpiresAtUnixMs": self.configuration.expires_at_unix_ms,
            "configuredProfileCount": len(self.configuration.profiles),
            "configuredMethodCount": len(self.configuration.method_bindings),
            "pathDisclosure": False,
            "complete": False,
        }
