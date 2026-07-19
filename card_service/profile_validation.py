"""Exact, authorization-bound service profile validation helpers."""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit

from .artifact_registry import ArtifactAudienceBinding, canonical_json_bytes
from .authorization_ledger import AuthorizationLedger
from .broker import BrokerBudget, BrokerReservationLedger, ModelTtsBroker
from .broker_configuration import operation_for_profile
from .broker_runtime import (
    AuthorizedProviderCall,
    TaskBrokerAuthorization,
    make_task_broker_handler,
)
from .credentials import CredentialBackend, CredentialStore
from .provider_egress import ProviderProfile, ProviderTransport


PROFILE_VALIDATION_LIFETIME_MINUTES = 10
PROFILE_VALIDATION_REQUEST_BYTES = 64 * 1024
PROFILE_VALIDATION_RESPONSE_BYTES = 2 * 1024 * 1024
PROFILE_VALIDATION_TTS_CHARACTERS = 128
PROFILE_VALIDATION_TTS_SECONDS = 30


@dataclass(frozen=True)
class ProfileValidationPlan:
    capability: str
    profile_ref: str
    configuration_fingerprint: str
    credential_revision: int
    provider_profile: ProviderProfile
    current_service_binding: Mapping[str, Any]
    operation_request_manifest: Mapping[str, Any]
    disclosure_manifest: Mapping[str, Any]
    cost_budget: Mapping[str, Any]
    worker_method: str
    worker_request: Mapping[str, Any]
    consent_summary: str


def _sha(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _normalized_endpoint(base_url: str) -> dict[str, Any]:
    parsed = urlsplit(base_url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return {
        "scheme": parsed.scheme,
        "asciiHost": str(parsed.hostname or "").encode("idna").decode("ascii").casefold(),
        "port": port,
        "pathPrefix": parsed.path or "/",
        "queryPolicy": "none",
    }


def _provider_profile(configuration: Mapping[str, Any]) -> ProviderProfile:
    return ProviderProfile(
        profile_ref=str(configuration["profileRef"]),
        capability=str(configuration["capability"]),
        provider=str(configuration["provider"]),
        base_url=str(configuration["baseUrl"]),
        model=str(configuration.get("model") or ""),
        voice=str(configuration.get("voice") or ""),
        timeout_seconds=int(configuration["timeoutSeconds"]),
        maximum_response_bytes=int(configuration["maximumResponseBytes"]),
    )


def build_profile_validation_plan(
    profile: Mapping[str, Any],
    *,
    now: datetime | None = None,
    configuration_session_ref: str | None = None,
) -> ProfileValidationPlan:
    capability = str(profile["capability"])
    if capability not in {"model", "tts"}:
        raise ValueError("remote profile validation only supports model or TTS")
    configuration = profile["configuration"]
    provider_profile = _provider_profile(configuration)
    endpoint = _normalized_endpoint(provider_profile.base_url)
    egress_manifest = {
        "schema": "study.egress.manifest",
        "schemaVersion": 1,
        "capability": capability,
        "profileRef": provider_profile.profile_ref,
        "normalizedTarget": endpoint,
        "allowedMethods": ["POST"],
        "allowedContentTypes": ["application/json"],
        "redirectPolicy": "none",
        "proxyPolicy": "card_service_broker_only",
        "dnsPolicy": "public_ip_only_recheck_on_connect",
        "maximumResponseBytes": provider_profile.maximum_response_bytes,
    }
    egress_digest = _sha(egress_manifest)
    origin = {
        "scheme": endpoint["scheme"],
        "asciiHost": endpoint["asciiHost"],
        "port": endpoint["port"],
    }
    binding = {
        "capability": capability,
        "profileRef": provider_profile.profile_ref,
        "configurationFingerprint": str(profile["configurationFingerprint"]),
        "credentialRevision": int(profile["credentialRevision"]),
        "egressManifestDigest": egress_digest,
    }
    model_or_voice = (
        provider_profile.voice if capability == "tts" else provider_profile.model
    )
    model_or_voice_ref = f"sha256:{_sha({'value': model_or_voice})}"
    if capability == "model":
        max_input_tokens = 2_048
        max_output_tokens = 2_048
        max_tts_characters = 0
        max_tts_seconds = 0
        max_media_items = 0
        worker_method = "runtime.test_model"
        worker_request: Mapping[str, Any] = {
            "api_config": {
                "provider": provider_profile.provider,
                "model": provider_profile.model,
            }
        }
    else:
        max_input_tokens = 0
        max_output_tokens = 0
        max_tts_characters = PROFILE_VALIDATION_TTS_CHARACTERS
        max_tts_seconds = PROFILE_VALIDATION_TTS_SECONDS
        max_media_items = 1
        worker_method = "runtime.test_tts"
        worker_request = {
            "language": "English",
            "api_config": {
                "tts_config": {
                    "enabled": True,
                    "provider": provider_profile.provider,
                    "language": "auto",
                    "sample_rate": 24_000,
                    "bit_rate": 128_000,
                }
            },
        }
    disclosure = {
        "schema": "study.disclosure.manifest",
        "schemaVersion": 1,
        "entries": [
            {
                "disclosureEntryId": "profile-validation-diagnostic",
                "target": {
                    "capability": capability,
                    "profileRef": provider_profile.profile_ref,
                    "providerOriginDigest": _sha(origin),
                    "modelOrVoiceRef": model_or_voice_ref,
                },
                "dataCategory": "diagnostic_summary",
                "sourceSlices": [],
                "maxRequestBytes": PROFILE_VALIDATION_REQUEST_BYTES,
                "maxInputTokens": max_input_tokens,
                "maxOutputTokens": max_output_tokens,
                "maxTtsCharacters": max_tts_characters,
                "maxTtsAudioSeconds": max_tts_seconds,
            }
        ],
        "globalCaps": {
            "maxTotalRequestBytes": PROFILE_VALIDATION_REQUEST_BYTES,
            "maxInputTokens": max_input_tokens,
            "maxOutputTokens": max_output_tokens,
            "maxTtsCharacters": max_tts_characters,
            "maxTtsAudioSeconds": max_tts_seconds,
        },
    }
    cost = {
        "priceKnown": False,
        "currency": None,
        "maxMinorUnits": None,
        "pricingSnapshotRef": None,
        "pricingSnapshotVersion": None,
        "maxRemoteCalls": 1,
        "maxCards": 0,
        "maxMediaItems": max_media_items,
        "unknownPricePolicy": "explicit_unknown_cost_with_hard_resource_caps",
    }
    subject: dict[str, Any] = {
        "kind": "profile_validation",
        "profileRef": provider_profile.profile_ref,
        "configurationFingerprint": str(profile["configurationFingerprint"]),
        "credentialRevision": int(profile["credentialRevision"]),
    }
    if configuration_session_ref is not None:
        subject["configurationSessionRef"] = configuration_session_ref
    created = now or datetime.now(timezone.utc)
    batch_policy = {
        "schema": "study.profile-validation.batch",
        "schemaVersion": 1,
        "maxAttempts": 1,
    }
    operation_request = {
        "schema": "study.operation.request",
        "schemaVersion": 1,
        "actionId": "validate_profile",
        "subject": subject,
        "serviceBindings": [binding],
        "disclosureManifestDigest": _sha(disclosure),
        "costBudgetDigest": _sha(cost),
        "batchPolicyDigest": _sha(batch_policy),
        "expiresAt": _timestamp(
            created + timedelta(minutes=PROFILE_VALIDATION_LIFETIME_MINUTES)
        ),
    }
    endpoint_origin = f"{endpoint['scheme']}://{endpoint['asciiHost']}:{endpoint['port']}"
    target_label = provider_profile.voice if capability == "tts" else provider_profile.model
    consent_summary = "\n".join(
        [
            f"操作：验证 {capability} 配置",
            f"配置：{provider_profile.profile_ref}",
            f"服务：{provider_profile.provider} / {target_label}",
            f"目标：{endpoint_origin}",
            "发送内容：仅固定的连接诊断文本，不包含你的学习素材、卡片或本地文件。",
            "硬上限：1 次远程调用；请求不超过 64 KiB；不会生成学习卡片。",
            "价格：当前未知；本次只允许上述一次诊断调用。",
        ]
    )
    return ProfileValidationPlan(
        capability=capability,
        profile_ref=provider_profile.profile_ref,
        configuration_fingerprint=str(profile["configurationFingerprint"]),
        credential_revision=int(profile["credentialRevision"]),
        provider_profile=provider_profile,
        current_service_binding=binding,
        operation_request_manifest=operation_request,
        disclosure_manifest=disclosure,
        cost_budget=cost,
        worker_method=worker_method,
        worker_request=worker_request,
        consent_summary=consent_summary,
    )


def make_profile_validation_broker_factory(
    *,
    state_dir: Path,
    credential_backend: CredentialBackend | None,
    authorization_ledger: AuthorizationLedger,
    audience: ArtifactAudienceBinding,
    operation_intent_id: str,
    authorization_expires_at: str,
    plan: ProfileValidationPlan,
    approval_consumption: Mapping[str, Any],
    transport: ProviderTransport | None = None,
) -> Callable[[str, str, dict[str, Any]], Callable[[str, dict[str, Any]], Any]]:
    credentials = CredentialStore(
        state_dir=(state_dir / "trusted-surfaces" / "credentials").resolve(),
        backend=credential_backend,
    )
    reservations = BrokerReservationLedger(
        (state_dir / "broker" / "profile-validation-reservations-v1.json").resolve()
    )
    broker = ModelTtsBroker(credential_store=credentials, ledger=reservations)
    operation = operation_for_profile(plan.provider_profile)
    expected_action = "call_tts" if plan.capability == "tts" else "call_model"
    grants = {
        str(item["action"]): item
        for item in approval_consumption["internalAuthorizationGrants"]
    }
    bindings = {
        str(item["action"]): item
        for item in approval_consumption["authorizationBindings"]
    }
    grant = grants[expected_action]
    authorization_binding = bindings[expected_action]

    def factory(
        task_id: str, method: str, _request: dict[str, Any]
    ) -> Callable[[str, dict[str, Any]], Any]:
        if method != plan.worker_method or task_id != approval_consumption["taskId"]:
            raise RuntimeError("profile validation task authorization mismatch")
        authorization = TaskBrokerAuthorization(
            operation_intent_ref=operation_intent_id,
            budget=BrokerBudget(
                max_remote_calls=1,
                max_request_bytes=PROFILE_VALIDATION_REQUEST_BYTES,
                max_response_bytes=min(
                    PROFILE_VALIDATION_RESPONSE_BYTES,
                    plan.provider_profile.maximum_response_bytes,
                ),
                max_cost_minor_units=None,
            ),
            operations={
                operation: AuthorizedProviderCall(
                    profile=plan.provider_profile,
                    credential_revision=plan.credential_revision,
                    reserved_cost_minor_units=None,
                    transport=transport,
                )
            },
            expires_at_unix_ms=int(
                datetime.fromisoformat(
                    str(authorization_expires_at).replace("Z", "+00:00")
                ).timestamp()
                * 1000
            ),
        )
        broker_handler = make_task_broker_handler(
            task_id=task_id, authorization=authorization, broker=broker
        )

        def handle(provider_operation: str, payload: dict[str, Any]) -> Any:
            if provider_operation != operation:
                raise RuntimeError("profile validation broker operation mismatch")
            work_unit_id = str(payload.get("workUnitId") or "")
            use_id = "profile-validation-" + hashlib.sha256(
                canonical_json_bytes(
                    {
                        "taskId": task_id,
                        "workUnitId": work_unit_id,
                        "operation": provider_operation,
                    }
                )
            ).hexdigest()
            authorization_ledger.consume_authorization(
                operation_intent_id=operation_intent_id,
                authorization_id=str(grant["authorizationId"]),
                audience=audience,
                task_id=task_id,
                action=expected_action,
                use_id=use_id,
                expected_authorization_record_digest=str(
                    authorization_binding["authorizationRecordDigest"]
                ),
                expected_exact_scope_digest=str(
                    authorization_binding["exactScopeDigest"]
                ),
                expected_revocation_epoch=int(
                    authorization_binding["expectedRevocationEpoch"]
                ),
                current_service_binding=plan.current_service_binding,
            )
            return broker_handler(provider_operation, payload)

        return handle

    return factory


def validate_anki_connect_profile(
    profile: Mapping[str, Any],
    *,
    credential_store: CredentialStore,
) -> dict[str, Any]:
    configuration = profile["configuration"]
    credential_revision = int(profile["credentialRevision"])
    key: str | None = None
    if bool(profile["secretRequired"]):
        key = credential_store.resolve_secret(
            str(profile["profileRef"]), expected_revision=credential_revision
        )
    payload: dict[str, Any] = {
        "action": "version",
        "version": int(configuration["apiVersion"]),
        "params": {},
    }
    if key is not None:
        payload["key"] = key
    request = urllib.request.Request(
        str(configuration["baseUrl"]),
        data=canonical_json_bytes(payload),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    started = time.monotonic()
    try:
        with opener.open(
            request, timeout=float(configuration["timeoutSeconds"])
        ) as response:
            if response.status != 200:
                raise RuntimeError("ANKI_CONNECT_HTTP_STATUS")
            raw = response.read(int(configuration["maximumResponseBytes"]) + 1)
    except (OSError, TimeoutError, urllib.error.URLError) as error:
        raise RuntimeError("ANKI_OFFLINE") from error
    if len(raw) > int(configuration["maximumResponseBytes"]):
        raise RuntimeError("ANKI_CONNECT_RESPONSE_TOO_LARGE")
    try:
        result = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("ANKI_CONNECT_INVALID_RESPONSE") from error
    if (
        not isinstance(result, dict)
        or set(result) != {"result", "error"}
        or result["error"] is not None
        or isinstance(result["result"], bool)
        or not isinstance(result["result"], int)
        or not 5 <= result["result"] <= 6
    ):
        raise RuntimeError("ANKI_CONNECT_INVALID_RESPONSE")
    return {
        "ok": True,
        "latencyMs": max(0, int((time.monotonic() - started) * 1000)),
        "apiVersion": int(result["result"]),
    }


__all__ = [
    "ProfileValidationPlan",
    "build_profile_validation_plan",
    "make_profile_validation_broker_factory",
    "validate_anki_connect_profile",
]
