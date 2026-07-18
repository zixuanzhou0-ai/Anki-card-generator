from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .broker_configuration import (
    AUTHORIZATION_SCHEMA,
    METHOD_REQUIRED_CAPABILITIES,
    SOURCE_CAPABLE_METHODS,
    BrokerAuthorizationConfiguration,
    BrokerConfigurationError,
    profile_configuration_fingerprint,
)
from .credentials import CredentialBackend, CredentialStore, CredentialStoreError
from .provider_egress import ProviderEgressError, ProviderProfile
from .source_acquisition import SOURCE_PROFILE_REF
from .storage import AtomicJsonStore


MAX_ISSUED_AUTHORIZATION_LIFETIME_SECONDS = 60 * 60
MAX_ISSUED_REMOTE_CALLS = 512
MAX_ISSUED_REQUEST_BYTES = 16 * 1024 * 1024
MAX_ISSUED_RESPONSE_BYTES = 512 * 1024 * 1024
MAX_ISSUED_COST_MINOR_UNITS = 100_000


class BrokerAuthorizationIssuerError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _exact_mapping(value: Any, keys: set[str], *, code: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise BrokerAuthorizationIssuerError(code, "Broker authorization request shape is invalid")
    return dict(value)


def _bounded_int(value: Any, *, minimum: int, maximum: int, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise BrokerAuthorizationIssuerError(code, "Broker authorization value is outside the allowed range")
    return value


@dataclass(frozen=True)
class PreparedBrokerAuthorization:
    value: Mapping[str, Any]
    title: str
    summary: str


@dataclass(frozen=True)
class IssuedBrokerAuthorization:
    manifest_path: Path
    public_summary: Mapping[str, Any]


class BrokerAuthorizationIssuer:
    """Creates a short-lived broker manifest only after a trusted local approval."""

    def __init__(
        self,
        *,
        state_dir: str | Path,
        credential_backend: CredentialBackend | None = None,
    ) -> None:
        root = Path(state_dir).expanduser()
        if not root.is_absolute():
            raise BrokerAuthorizationIssuerError(
                "BROKER_AUTHORIZATION_STATE_RELATIVE",
                "Broker authorization state directory must be absolute",
            )
        self.root = root.resolve()
        self.authorization_dir = (self.root / "authorizations").resolve()
        self.authorization_dir.mkdir(parents=True, exist_ok=True)
        self.credentials = CredentialStore(
            state_dir=(self.root / "credentials").resolve(),
            backend=credential_backend,
        )
        self._issued: dict[str, IssuedBrokerAuthorization] = {}
        self._lock = threading.RLock()

    def prepare(self, draft: Any) -> PreparedBrokerAuthorization:
        source = _exact_mapping(
            draft,
            {"lifetimeSeconds", "budget", "profiles", "methodBindings", "sourceAcquisition"},
            code="BROKER_AUTHORIZATION_REQUEST_INVALID",
        )
        lifetime_seconds = _bounded_int(
            source["lifetimeSeconds"],
            minimum=60,
            maximum=MAX_ISSUED_AUTHORIZATION_LIFETIME_SECONDS,
            code="BROKER_AUTHORIZATION_LIFETIME_INVALID",
        )
        raw_budget = _exact_mapping(
            source["budget"],
            {"maxRemoteCalls", "maxRequestBytes", "maxResponseBytes", "maxCostMinorUnits"},
            code="BROKER_AUTHORIZATION_BUDGET_INVALID",
        )
        budget = {
            "maxRemoteCalls": _bounded_int(
                raw_budget["maxRemoteCalls"],
                minimum=1,
                maximum=MAX_ISSUED_REMOTE_CALLS,
                code="BROKER_AUTHORIZATION_BUDGET_INVALID",
            ),
            "maxRequestBytes": _bounded_int(
                raw_budget["maxRequestBytes"],
                minimum=1,
                maximum=MAX_ISSUED_REQUEST_BYTES,
                code="BROKER_AUTHORIZATION_BUDGET_INVALID",
            ),
            "maxResponseBytes": _bounded_int(
                raw_budget["maxResponseBytes"],
                minimum=1,
                maximum=MAX_ISSUED_RESPONSE_BYTES,
                code="BROKER_AUTHORIZATION_BUDGET_INVALID",
            ),
            "maxCostMinorUnits": _bounded_int(
                raw_budget["maxCostMinorUnits"],
                minimum=0,
                maximum=MAX_ISSUED_COST_MINOR_UNITS,
                code="BROKER_AUTHORIZATION_BUDGET_INVALID",
            ),
        }
        raw_profiles = source["profiles"]
        if not isinstance(raw_profiles, list) or not 1 <= len(raw_profiles) <= 16:
            raise BrokerAuthorizationIssuerError(
                "BROKER_AUTHORIZATION_PROFILES_INVALID",
                "Broker authorization must contain between one and sixteen profiles",
            )
        profiles: list[dict[str, Any]] = []
        profiles_by_ref: dict[str, ProviderProfile] = {}
        for raw_profile in raw_profiles:
            item = _exact_mapping(
                raw_profile,
                {
                    "profileRef",
                    "capability",
                    "provider",
                    "baseUrl",
                    "model",
                    "voice",
                    "timeoutSeconds",
                    "maximumResponseBytes",
                    "reservedCostMinorUnits",
                },
                code="BROKER_AUTHORIZATION_PROFILE_INVALID",
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
            except (TypeError, ValueError, ProviderEgressError) as error:
                raise BrokerAuthorizationIssuerError(
                    "BROKER_AUTHORIZATION_PROFILE_INVALID",
                    "Broker authorization provider profile is invalid",
                ) from error
            if profile.profile_ref in profiles_by_ref:
                raise BrokerAuthorizationIssuerError(
                    "BROKER_AUTHORIZATION_PROFILE_DUPLICATE",
                    "Broker authorization profile reference is duplicated",
                )
            reserved_cost = _bounded_int(
                item["reservedCostMinorUnits"],
                minimum=0,
                maximum=budget["maxCostMinorUnits"],
                code="BROKER_AUTHORIZATION_PROFILE_INVALID",
            )
            if profile.provider == "hermes":
                credential_revision = 0
            else:
                try:
                    metadata = self.credentials.metadata(profile.profile_ref)
                except CredentialStoreError as error:
                    raise BrokerAuthorizationIssuerError(
                        "BROKER_CREDENTIAL_UNAVAILABLE",
                        "Broker credential metadata is unavailable",
                    ) from error
                if not metadata["exists"] or int(metadata["credentialRevision"]) <= 0:
                    raise BrokerAuthorizationIssuerError(
                        "BROKER_CREDENTIAL_REQUIRED",
                        f"A local credential is required for {profile.profile_ref}",
                    )
                credential_revision = int(metadata["credentialRevision"])
            profiles_by_ref[profile.profile_ref] = profile
            profiles.append(
                {
                    "profileRef": profile.profile_ref,
                    "capability": profile.capability,
                    "provider": profile.provider,
                    "baseUrl": profile.base_url,
                    "model": profile.model,
                    "voice": profile.voice,
                    "timeoutSeconds": profile.timeout_seconds,
                    "maximumResponseBytes": profile.maximum_response_bytes,
                    "configurationFingerprint": profile_configuration_fingerprint(profile),
                    "credentialRevision": credential_revision,
                    "reservedCostMinorUnits": reserved_cost,
                }
            )
        raw_source_policy = _exact_mapping(
            source["sourceAcquisition"],
            {"youtubeSubtitles"},
            code="BROKER_AUTHORIZATION_SOURCE_INVALID",
        )
        raw_youtube = _exact_mapping(
            raw_source_policy["youtubeSubtitles"],
            {"enabled", "timeoutSeconds"},
            code="BROKER_AUTHORIZATION_SOURCE_INVALID",
        )
        if not isinstance(raw_youtube["enabled"], bool):
            raise BrokerAuthorizationIssuerError(
                "BROKER_AUTHORIZATION_SOURCE_INVALID",
                "YouTube subtitle authorization flag must be a boolean",
            )
        youtube = {
            "enabled": raw_youtube["enabled"],
            "timeoutSeconds": _bounded_int(
                raw_youtube["timeoutSeconds"],
                minimum=1,
                maximum=60,
                code="BROKER_AUTHORIZATION_SOURCE_INVALID",
            ),
        }
        raw_methods = source["methodBindings"]
        if not isinstance(raw_methods, dict) or not raw_methods:
            raise BrokerAuthorizationIssuerError(
                "BROKER_AUTHORIZATION_METHOD_INVALID",
                "Broker authorization method bindings are required",
            )
        methods: dict[str, dict[str, str]] = {}
        referenced_profiles: set[str] = set()
        source_binding_present = False
        for raw_method, raw_bindings in raw_methods.items():
            method = str(raw_method)
            required = METHOD_REQUIRED_CAPABILITIES.get(method)
            allowed = set(required or ())
            if method in SOURCE_CAPABLE_METHODS and youtube["enabled"]:
                allowed.add("source")
            if (
                required is None
                or not isinstance(raw_bindings, dict)
                or not set(required) <= set(raw_bindings) <= allowed
            ):
                raise BrokerAuthorizationIssuerError(
                    "BROKER_AUTHORIZATION_METHOD_INVALID",
                    "Broker authorization method binding is invalid",
                )
            bindings: dict[str, str] = {}
            for capability, raw_ref in raw_bindings.items():
                profile_ref = str(raw_ref)
                if capability == "source":
                    if profile_ref != SOURCE_PROFILE_REF:
                        raise BrokerAuthorizationIssuerError(
                            "BROKER_AUTHORIZATION_METHOD_INVALID",
                            "Broker source binding is invalid",
                        )
                    source_binding_present = True
                else:
                    profile = profiles_by_ref.get(profile_ref)
                    if profile is None or profile.capability != capability:
                        raise BrokerAuthorizationIssuerError(
                            "BROKER_AUTHORIZATION_METHOD_INVALID",
                            "Broker method binding does not match a prepared profile",
                        )
                    referenced_profiles.add(profile_ref)
                bindings[capability] = profile_ref
            methods[method] = bindings
        if referenced_profiles != set(profiles_by_ref):
            raise BrokerAuthorizationIssuerError(
                "BROKER_AUTHORIZATION_PROFILE_UNUSED",
                "Every broker profile must be bound to at least one authorized method",
            )
        if youtube["enabled"] != source_binding_present:
            raise BrokerAuthorizationIssuerError(
                "BROKER_AUTHORIZATION_SOURCE_INVALID",
                "YouTube subtitle acquisition must exactly match an authorized source binding",
            )
        profiles.sort(key=lambda item: str(item["profileRef"]).encode("utf-8"))
        methods = {method: methods[method] for method in sorted(methods)}
        prepared = {
            "schemaVersion": 1,
            "lifetimeSeconds": lifetime_seconds,
            "budget": budget,
            "profiles": profiles,
            "methodBindings": methods,
            "sourceAcquisition": {"youtubeSubtitles": youtube},
        }
        profile_lines = [
            f"{item['profileRef']}：{item['provider']} / {item['model']} / {item['baseUrl']}"
            + (f" / voice={item['voice']}" if item["voice"] else "")
            + (
                f" / 超时={item['timeoutSeconds']:g}秒"
                f" / 单次响应上限={item['maximumResponseBytes']}字节"
                f" / 单次预留成本={item['reservedCostMinorUnits']}"
            )
            for item in profiles
        ]
        method_lines = [
            method
            + " ["
            + ", ".join(f"{capability}={profile_ref}" for capability, profile_ref in sorted(bindings.items()))
            + "]"
            for method, bindings in methods.items()
        ]
        summary = "\n".join(
            [
                f"有效期：{lifetime_seconds // 60} 分钟",
                (
                    f"本授权合计预算：最多 {budget['maxRemoteCalls']} 次远程调用；"
                    f"请求 {budget['maxRequestBytes']} 字节；响应 {budget['maxResponseBytes']} 字节；"
                    f"成本上限 {budget['maxCostMinorUnits']} 最小货币单位"
                ),
                "方法与能力绑定：\n" + "\n".join(method_lines),
                "配置：\n" + "\n".join(profile_lines),
                "YouTube 字幕读取："
                + (f"允许（超时 {youtube['timeoutSeconds']} 秒）" if youtube["enabled"] else "不允许"),
            ]
        )
        return PreparedBrokerAuthorization(
            value=prepared,
            title="授权 Codex Study 使用本地生成服务",
            summary=summary,
        )

    def issue(
        self,
        *,
        session_ref: str,
        prepared: Mapping[str, Any],
        now_unix_ms: int | None = None,
    ) -> IssuedBrokerAuthorization:
        with self._lock:
            existing = self._issued.get(session_ref)
            if existing is not None:
                return existing
            try:
                prepared_value = _exact_mapping(
                    prepared,
                    {
                        "schemaVersion",
                        "lifetimeSeconds",
                        "budget",
                        "profiles",
                        "methodBindings",
                        "sourceAcquisition",
                    },
                    code="BROKER_AUTHORIZATION_PREPARED_INVALID",
                )
                if prepared_value["schemaVersion"] != 1:
                    raise BrokerAuthorizationIssuerError(
                        "BROKER_AUTHORIZATION_PREPARED_INVALID",
                        "Prepared broker authorization version is invalid",
                    )
                lifetime_seconds = _bounded_int(
                    prepared_value["lifetimeSeconds"],
                    minimum=60,
                    maximum=MAX_ISSUED_AUTHORIZATION_LIFETIME_SECONDS,
                    code="BROKER_AUTHORIZATION_LIFETIME_INVALID",
                )
                profiles = list(prepared_value["profiles"])
                budget = dict(prepared_value["budget"])
                method_bindings = dict(prepared_value["methodBindings"])
                source_acquisition = dict(prepared_value["sourceAcquisition"])
            except (KeyError, TypeError, ValueError, BrokerAuthorizationIssuerError) as error:
                if isinstance(error, BrokerAuthorizationIssuerError):
                    raise
                raise BrokerAuthorizationIssuerError(
                    "BROKER_AUTHORIZATION_PREPARED_INVALID",
                    "Prepared broker authorization is invalid",
                ) from error
            for profile in profiles:
                if not isinstance(profile, dict):
                    raise BrokerAuthorizationIssuerError(
                        "BROKER_AUTHORIZATION_PREPARED_INVALID",
                        "Prepared broker profile is invalid",
                    )
                provider = str(profile.get("provider") or "")
                if provider == "hermes":
                    continue
                try:
                    metadata = self.credentials.metadata(str(profile["profileRef"]))
                except (KeyError, CredentialStoreError) as error:
                    raise BrokerAuthorizationIssuerError(
                        "BROKER_CREDENTIAL_UNAVAILABLE",
                        "Broker credential metadata is unavailable",
                    ) from error
                if (
                    not metadata["exists"]
                    or int(metadata["credentialRevision"]) != int(profile["credentialRevision"])
                ):
                    raise BrokerAuthorizationIssuerError(
                        "BROKER_CREDENTIAL_CHANGED",
                        "A broker credential changed after the trusted confirmation opened",
                    )
            now = int(time.time() * 1000) if now_unix_ms is None else int(now_unix_ms)
            operation_intent_ref = f"intent:startup:{session_ref}"
            manifest = {
                "schema": AUTHORIZATION_SCHEMA,
                "schemaVersion": 1,
                "operationIntentRef": operation_intent_ref,
                "expiresAtUnixMs": now + lifetime_seconds * 1000,
                "budget": budget,
                "profiles": profiles,
                "methodBindings": method_bindings,
                "sourceAcquisition": source_acquisition,
            }
            manifest_path = (self.authorization_dir / f"broker-{uuid.uuid4()}.json").resolve()
            if manifest_path.parent != self.authorization_dir or manifest_path.exists():
                raise BrokerAuthorizationIssuerError(
                    "BROKER_AUTHORIZATION_PATH_INVALID",
                    "Broker authorization output path is invalid",
                )
            AtomicJsonStore._write_atomic(manifest_path, manifest)
            try:
                configuration = BrokerAuthorizationConfiguration.load(manifest_path, now_unix_ms=now)
            except BrokerConfigurationError as error:
                try:
                    manifest_path.unlink(missing_ok=True)
                except OSError:
                    pass
                raise BrokerAuthorizationIssuerError(error.code, str(error)) from error
            public_summary = {
                "schemaVersion": 1,
                "authorizationDigest": configuration.manifest_digest,
                "expiresAtUnixMs": configuration.expires_at_unix_ms,
                "profileCount": len(configuration.profiles),
                "methodCount": len(configuration.method_bindings),
                "youtubeSubtitleAcquisition": configuration.youtube_subtitles_enabled,
            }
            issued = IssuedBrokerAuthorization(manifest_path=manifest_path, public_summary=public_summary)
            self._issued[session_ref] = issued
            return issued
