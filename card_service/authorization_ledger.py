from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import stat
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence

from .artifact_registry import (
    ArtifactAudienceBinding,
    ArtifactRegistryError,
    canonical_json_bytes,
    validate_persistable_json,
)
from .task_manifests import AUTHORIZATION_ACTIONS, WORKFLOW_ACTIONS


MAX_RECORD_BYTES = 4 * 1024 * 1024
MAX_INTENT_LIFETIME = timedelta(hours=24)
MAX_SERVICE_BINDINGS = 16
MAX_DISCLOSURE_ENTRIES = 256
MAX_SOURCE_SLICES = 512
MAX_REMOTE_CALLS = 2_048
MAX_SAFE_INTEGER = 9_007_199_254_740_991
ID_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-"
)
SERVICE_CAPABILITIES = frozenset({"model", "tts"})
DISCLOSURE_CATEGORIES = frozenset(
    {
        "source_excerpt",
        "subtitle",
        "learning_objective",
        "card_plan",
        "tts_text",
        "diagnostic_summary",
    }
)
REMOTE_OPERATION_ACTIONS = frozenset(
    {
        "validate_profile",
        "inspect_source",
        "discover_candidates",
        "plan_cards",
        "validate_card_plans",
        "generate_cards",
        "resume_task",
        "retry",
    }
)
SECRET_VALUE_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~-]{20,}\b", re.IGNORECASE),
)


class AuthorizationLedgerError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime) -> str:
    normalized = value.astimezone(timezone.utc)
    return normalized.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse_timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise AuthorizationLedgerError(
            "AUTHORIZATION_SCHEMA_INVALID", f"{label} must be a UTC timestamp"
        )
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise AuthorizationLedgerError(
            "AUTHORIZATION_SCHEMA_INVALID", f"{label} is invalid"
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise AuthorizationLedgerError(
            "AUTHORIZATION_SCHEMA_INVALID", f"{label} must be UTC"
        )
    return parsed.astimezone(timezone.utc)


def _id(value: Any, label: str, *, maximum: int = 256) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or any(character not in ID_CHARS for character in value)
    ):
        raise AuthorizationLedgerError(
            "AUTHORIZATION_SCHEMA_INVALID", f"{label} is invalid"
        )
    if any(pattern.search(value) for pattern in SECRET_VALUE_PATTERNS):
        raise AuthorizationLedgerError(
            "AUTHORIZATION_SECRET_FORBIDDEN",
            f"{label} appears to contain a credential",
        )
    return value


def _digest(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise AuthorizationLedgerError(
            "AUTHORIZATION_SCHEMA_INVALID", f"{label} must be a SHA-256 digest"
        )
    return value


def _integer(
    value: Any,
    label: str,
    *,
    minimum: int = 0,
    maximum: int = MAX_SAFE_INTEGER,
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < minimum
        or value > maximum
    ):
        raise AuthorizationLedgerError(
            "AUTHORIZATION_SCHEMA_INVALID", f"{label} is outside its allowed range"
        )
    return value


def _exact(
    value: Any, required: set[str], optional: set[str], label: str
) -> Mapping[str, Any]:
    if (
        not isinstance(value, Mapping)
        or not required.issubset(value)
        or not set(value).issubset(required | optional)
    ):
        raise AuthorizationLedgerError(
            "AUTHORIZATION_SCHEMA_INVALID", f"{label} fields are invalid"
        )
    return value


def _sorted_digests(values: Any, label: str) -> list[str]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise AuthorizationLedgerError(
            "AUTHORIZATION_SCHEMA_INVALID", f"{label} must be a list"
        )
    normalized = sorted(
        (_digest(value, label) for value in values), key=lambda item: item.encode("utf-8")
    )
    if len(normalized) != len(set(normalized)):
        raise AuthorizationLedgerError(
            "AUTHORIZATION_DUPLICATE", f"{label} contains a duplicate"
        )
    return normalized


def _persistable(value: Mapping[str, Any]) -> None:
    try:
        validate_persistable_json(dict(value))
    except ArtifactRegistryError as error:
        raise AuthorizationLedgerError(
            "AUTHORIZATION_FORBIDDEN_DATA", error.message
        ) from error


def _temporary(path: Path, data: bytes) -> Path:
    temporary = path.parent / f".{path.name}.{secrets.token_hex(12)}.partial"
    with temporary.open("xb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())
    return temporary


def _directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    info = path.lstat()
    attributes = getattr(info, "st_file_attributes", 0)
    if (
        not stat.S_ISDIR(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or attributes & 0x400
    ):
        raise AuthorizationLedgerError(
            "AUTHORIZATION_STORAGE_UNSAFE",
            "Authorization storage contains a link or reparse directory",
        )
    return path


def _normalize_subject(value: Any) -> dict[str, Any]:
    subject = _exact(value, {"kind"}, {
        "projectId", "projectRevision", "learningContractRevision",
        "inputArtifactDigests", "sourceRevisionDigests", "configurationSessionRef",
        "profileRef", "configurationFingerprint", "credentialRevision",
    }, "operation subject")
    kind = subject["kind"]
    if kind == "project_task":
        _exact(
            subject,
            {
                "kind", "projectId", "projectRevision", "learningContractRevision",
                "inputArtifactDigests", "sourceRevisionDigests",
            },
            set(),
            "project task subject",
        )
        return {
            "kind": kind,
            "projectId": _id(subject["projectId"], "projectId"),
            "projectRevision": _integer(
                subject["projectRevision"], "projectRevision", minimum=1
            ),
            "learningContractRevision": _integer(
                subject["learningContractRevision"],
                "learningContractRevision",
                minimum=1,
            ),
            "inputArtifactDigests": _sorted_digests(
                subject["inputArtifactDigests"], "inputArtifactDigest"
            ),
            "sourceRevisionDigests": _sorted_digests(
                subject["sourceRevisionDigests"], "sourceRevisionDigest"
            ),
        }
    if kind == "profile_validation":
        _exact(
            subject,
            {"kind", "profileRef", "configurationFingerprint", "credentialRevision"},
            {"configurationSessionRef"},
            "profile validation subject",
        )
        normalized = {
            "kind": kind,
            "profileRef": _id(subject["profileRef"], "profileRef"),
            "configurationFingerprint": _digest(
                subject["configurationFingerprint"], "configurationFingerprint"
            ),
            "credentialRevision": _integer(
                subject["credentialRevision"], "credentialRevision"
            ),
        }
        if "configurationSessionRef" in subject:
            normalized["configurationSessionRef"] = _id(
                subject["configurationSessionRef"], "configurationSessionRef"
            )
        return normalized
    raise AuthorizationLedgerError(
        "AUTHORIZATION_SCHEMA_INVALID", "operation subject kind is invalid"
    )


def _normalize_service_bindings(values: Any) -> list[dict[str, Any]]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise AuthorizationLedgerError(
            "AUTHORIZATION_SCHEMA_INVALID", "serviceBindings must be a list"
        )
    if not 1 <= len(values) <= MAX_SERVICE_BINDINGS:
        raise AuthorizationLedgerError(
            "AUTHORIZATION_SCHEMA_INVALID", "serviceBindings count is invalid"
        )
    normalized: list[dict[str, Any]] = []
    for value in values:
        item = _exact(
            value,
            {
                "capability", "profileRef", "configurationFingerprint",
                "credentialRevision", "egressManifestDigest",
            },
            set(),
            "service binding",
        )
        if item["capability"] not in SERVICE_CAPABILITIES:
            raise AuthorizationLedgerError(
                "AUTHORIZATION_SCHEMA_INVALID", "service capability is invalid"
            )
        normalized.append(
            {
                "capability": item["capability"],
                "profileRef": _id(item["profileRef"], "profileRef"),
                "configurationFingerprint": _digest(
                    item["configurationFingerprint"], "configurationFingerprint"
                ),
                "credentialRevision": _integer(
                    item["credentialRevision"], "credentialRevision"
                ),
                "egressManifestDigest": _digest(
                    item["egressManifestDigest"], "egressManifestDigest"
                ),
            }
        )
    normalized.sort(
        key=lambda item: (
            item["capability"].encode("utf-8"),
            item["profileRef"].encode("utf-8"),
        )
    )
    keys = [(item["capability"], item["profileRef"]) for item in normalized]
    if len(keys) != len(set(keys)):
        raise AuthorizationLedgerError(
            "AUTHORIZATION_DUPLICATE",
            "serviceBindings contains a duplicate capability/profile",
        )
    return normalized


def _normalize_disclosure_manifest(value: Any) -> dict[str, Any]:
    manifest = _exact(
        value,
        {"schema", "schemaVersion", "entries", "globalCaps"},
        set(),
        "disclosure manifest",
    )
    if (
        manifest["schema"] != "study.disclosure.manifest"
        or manifest["schemaVersion"] != 1
    ):
        raise AuthorizationLedgerError(
            "AUTHORIZATION_SCHEMA_INVALID", "disclosure manifest schema is invalid"
        )
    values = manifest["entries"]
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise AuthorizationLedgerError(
            "AUTHORIZATION_SCHEMA_INVALID", "disclosure entries must be a list"
        )
    if not 1 <= len(values) <= MAX_DISCLOSURE_ENTRIES:
        raise AuthorizationLedgerError(
            "AUTHORIZATION_SCHEMA_INVALID", "disclosure entry count is invalid"
        )
    entries: list[dict[str, Any]] = []
    for value in values:
        item = _exact(
            value,
            {
                "disclosureEntryId", "target", "dataCategory", "sourceSlices",
                "maxRequestBytes", "maxInputTokens", "maxOutputTokens",
                "maxTtsCharacters", "maxTtsAudioSeconds",
            },
            set(),
            "disclosure entry",
        )
        target = _exact(
            item["target"],
            {
                "capability", "profileRef", "providerOriginDigest",
                "modelOrVoiceRef",
            },
            set(),
            "disclosure target",
        )
        if target["capability"] not in SERVICE_CAPABILITIES:
            raise AuthorizationLedgerError(
                "AUTHORIZATION_SCHEMA_INVALID", "disclosure capability is invalid"
            )
        if item["dataCategory"] not in DISCLOSURE_CATEGORIES:
            raise AuthorizationLedgerError(
                "AUTHORIZATION_SCHEMA_INVALID", "disclosure category is invalid"
            )
        source_values = item["sourceSlices"]
        if not isinstance(source_values, Sequence) or isinstance(
            source_values, (str, bytes)
        ):
            raise AuthorizationLedgerError(
                "AUTHORIZATION_SCHEMA_INVALID", "sourceSlices must be a list"
            )
        if len(source_values) > MAX_SOURCE_SLICES:
            raise AuthorizationLedgerError(
                "AUTHORIZATION_SCHEMA_INVALID", "sourceSlices count is invalid"
            )
        slices: list[dict[str, Any]] = []
        for source_value in source_values:
            source = _exact(
                source_value,
                {
                    "sourceArtifactDigest", "sourceRevisionDigest",
                    "locatorSetDigest", "maxBytes",
                },
                set(),
                "disclosure source slice",
            )
            slices.append(
                {
                    "sourceArtifactDigest": _digest(
                        source["sourceArtifactDigest"], "sourceArtifactDigest"
                    ),
                    "sourceRevisionDigest": _digest(
                        source["sourceRevisionDigest"], "sourceRevisionDigest"
                    ),
                    "locatorSetDigest": _digest(
                        source["locatorSetDigest"], "locatorSetDigest"
                    ),
                    "maxBytes": _integer(source["maxBytes"], "maxBytes"),
                }
            )
        slices.sort(key=canonical_json_bytes)
        encoded_slices = [canonical_json_bytes(item) for item in slices]
        if len(encoded_slices) != len(set(encoded_slices)):
            raise AuthorizationLedgerError(
                "AUTHORIZATION_DUPLICATE", "sourceSlices contains a duplicate"
            )
        entries.append(
            {
                "disclosureEntryId": _id(
                    item["disclosureEntryId"], "disclosureEntryId"
                ),
                "target": {
                    "capability": target["capability"],
                    "profileRef": _id(target["profileRef"], "profileRef"),
                    "providerOriginDigest": _digest(
                        target["providerOriginDigest"], "providerOriginDigest"
                    ),
                    "modelOrVoiceRef": _id(
                        target["modelOrVoiceRef"], "modelOrVoiceRef"
                    ),
                },
                "dataCategory": item["dataCategory"],
                "sourceSlices": slices,
                "maxRequestBytes": _integer(
                    item["maxRequestBytes"], "maxRequestBytes"
                ),
                "maxInputTokens": _integer(
                    item["maxInputTokens"], "maxInputTokens"
                ),
                "maxOutputTokens": _integer(
                    item["maxOutputTokens"], "maxOutputTokens"
                ),
                "maxTtsCharacters": _integer(
                    item["maxTtsCharacters"], "maxTtsCharacters"
                ),
                "maxTtsAudioSeconds": _integer(
                    item["maxTtsAudioSeconds"], "maxTtsAudioSeconds"
                ),
            }
        )
    entries.sort(key=lambda item: item["disclosureEntryId"].encode("utf-8"))
    entry_ids = [item["disclosureEntryId"] for item in entries]
    if len(entry_ids) != len(set(entry_ids)):
        raise AuthorizationLedgerError(
            "AUTHORIZATION_DUPLICATE", "disclosureEntryId is duplicated"
        )
    caps = _exact(
        manifest["globalCaps"],
        {
            "maxTotalRequestBytes", "maxInputTokens", "maxOutputTokens",
            "maxTtsCharacters", "maxTtsAudioSeconds",
        },
        set(),
        "disclosure global caps",
    )
    normalized_caps = {
        name: _integer(caps[name], name)
        for name in (
            "maxTotalRequestBytes", "maxInputTokens", "maxOutputTokens",
            "maxTtsCharacters", "maxTtsAudioSeconds",
        )
    }
    for entry in entries:
        if entry["maxRequestBytes"] > normalized_caps["maxTotalRequestBytes"]:
            raise AuthorizationLedgerError(
                "AUTHORIZATION_BUDGET_INVALID",
                "a disclosure entry exceeds its global request-byte cap",
            )
        for name in (
            "maxInputTokens", "maxOutputTokens", "maxTtsCharacters",
            "maxTtsAudioSeconds",
        ):
            if entry[name] > normalized_caps[name]:
                raise AuthorizationLedgerError(
                    "AUTHORIZATION_BUDGET_INVALID",
                    f"a disclosure entry exceeds global {name}",
                )
    normalized = {
        "schema": "study.disclosure.manifest",
        "schemaVersion": 1,
        "entries": entries,
        "globalCaps": normalized_caps,
    }
    _persistable(normalized)
    return normalized


def _normalize_cost_budget(value: Any) -> dict[str, Any]:
    budget = _exact(
        value,
        {"priceKnown", "currency", "maxMinorUnits", "pricingSnapshotRef",
         "pricingSnapshotVersion", "maxRemoteCalls", "maxCards", "maxMediaItems"},
        {"unknownPricePolicy"},
        "cost budget",
    )
    known = budget["priceKnown"]
    if not isinstance(known, bool):
        raise AuthorizationLedgerError(
            "AUTHORIZATION_SCHEMA_INVALID", "priceKnown must be boolean"
        )
    normalized: dict[str, Any] = {
        "priceKnown": known,
        "maxRemoteCalls": _integer(
            budget["maxRemoteCalls"],
            "maxRemoteCalls",
            minimum=1,
            maximum=MAX_REMOTE_CALLS,
        ),
        "maxCards": _integer(budget["maxCards"], "maxCards"),
        "maxMediaItems": _integer(budget["maxMediaItems"], "maxMediaItems"),
    }
    if known:
        if "unknownPricePolicy" in budget:
            raise AuthorizationLedgerError(
                "AUTHORIZATION_SCHEMA_INVALID",
                "known-price budget cannot contain unknownPricePolicy",
            )
        currency = budget["currency"]
        if (
            not isinstance(currency, str)
            or len(currency) != 3
            or not currency.isascii()
            or not currency.isupper()
            or not currency.isalpha()
        ):
            raise AuthorizationLedgerError(
                "AUTHORIZATION_SCHEMA_INVALID", "currency is invalid"
            )
        normalized.update(
            {
                "currency": currency,
                "maxMinorUnits": _integer(
                    budget["maxMinorUnits"], "maxMinorUnits"
                ),
                "pricingSnapshotRef": _id(
                    budget["pricingSnapshotRef"], "pricingSnapshotRef"
                ),
                "pricingSnapshotVersion": _id(
                    budget["pricingSnapshotVersion"], "pricingSnapshotVersion"
                ),
            }
        )
    else:
        if any(
            budget[name] is not None
            for name in (
                "currency", "maxMinorUnits", "pricingSnapshotRef",
                "pricingSnapshotVersion",
            )
        ):
            raise AuthorizationLedgerError(
                "AUTHORIZATION_SCHEMA_INVALID",
                "unknown-price budget fields must be null",
            )
        policy = budget.get("unknownPricePolicy")
        if policy not in {
            "block", "explicit_unknown_cost_with_hard_resource_caps"
        }:
            raise AuthorizationLedgerError(
                "AUTHORIZATION_SCHEMA_INVALID", "unknownPricePolicy is invalid"
            )
        if policy == "block":
            raise AuthorizationLedgerError(
                "AUTHORIZATION_COST_BLOCKED", "unknown-price policy blocks this operation"
            )
        normalized.update(
            {
                "currency": None,
                "maxMinorUnits": None,
                "pricingSnapshotRef": None,
                "pricingSnapshotVersion": None,
                "unknownPricePolicy": policy,
            }
        )
    _persistable(normalized)
    return normalized


def _normalize_operation_request(value: Any) -> dict[str, Any]:
    request = _exact(
        value,
        {
            "schema", "schemaVersion", "actionId", "subject", "serviceBindings",
            "disclosureManifestDigest", "costBudgetDigest", "batchPolicyDigest",
            "expiresAt",
        },
        set(),
        "operation request manifest",
    )
    if request["schema"] != "study.operation.request" or request["schemaVersion"] != 1:
        raise AuthorizationLedgerError(
            "AUTHORIZATION_SCHEMA_INVALID", "operation request schema is invalid"
        )
    if request["actionId"] not in WORKFLOW_ACTIONS:
        raise AuthorizationLedgerError(
            "AUTHORIZATION_SCHEMA_INVALID", "workflow action is invalid"
        )
    if request["actionId"] not in REMOTE_OPERATION_ACTIONS:
        raise AuthorizationLedgerError(
            "AUTHORIZATION_SCHEMA_INVALID",
            "workflow action cannot request model or TTS authorization",
        )
    normalized = {
        "schema": "study.operation.request",
        "schemaVersion": 1,
        "actionId": request["actionId"],
        "subject": _normalize_subject(request["subject"]),
        "serviceBindings": _normalize_service_bindings(request["serviceBindings"]),
        "disclosureManifestDigest": _digest(
            request["disclosureManifestDigest"], "disclosureManifestDigest"
        ),
        "costBudgetDigest": _digest(request["costBudgetDigest"], "costBudgetDigest"),
        "batchPolicyDigest": _digest(
            request["batchPolicyDigest"], "batchPolicyDigest"
        ),
        "expiresAt": request["expiresAt"],
    }
    _parse_timestamp(normalized["expiresAt"], "expiresAt")
    _persistable(normalized)
    return normalized


def _audience_manifest(
    audience: ArtifactAudienceBinding, service_instance_id: str
) -> dict[str, Any]:
    return {
        "schema": "study.authorization.audience",
        "schemaVersion": 1,
        "osUserSidDigest": _digest(audience.owner_digest, "osUserSidDigest"),
        "hostInstanceId": _id(audience.host_id, "hostInstanceId"),
        "pluginInstanceId": _id(audience.plugin_id, "pluginInstanceId"),
        "serviceInstanceId": _id(service_instance_id, "serviceInstanceId"),
        "sessionId": _id(audience.session_id, "sessionId"),
    }


class AuthorizationLedger:
    def __init__(
        self,
        root: Path,
        *,
        authentication_key: bytes,
        service_instance_id: str,
        key_id: str = "study-authorization-ledger-v1",
        clock: Callable[[], datetime] | None = None,
        gesture_attestation_verifier: (
            Callable[[str, str, str, str], bool] | None
        ) = None,
    ) -> None:
        if not isinstance(authentication_key, bytes) or len(authentication_key) < 32:
            raise AuthorizationLedgerError(
                "AUTHORIZATION_KEY_INVALID",
                "Authorization authentication key must contain at least 256 bits",
            )
        self._authentication_key = bytes(authentication_key)
        self._service_instance_id = _id(service_instance_id, "serviceInstanceId")
        self._key_id = _id(key_id, "keyId")
        self._clock = clock or _utc_now
        self._gesture_attestation_verifier = gesture_attestation_verifier
        self._root = _directory(Path(root).absolute())
        self._intents_root = _directory(self._root / "operation-intents")
        self._lock_path = self._root / "authorization-ledger.lock"
        try:
            with self._lock_path.open("xb") as output:
                output.write(b"\x00")
                output.flush()
                os.fsync(output.fileno())
        except FileExistsError:
            pass
        self._thread_lock = threading.RLock()

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise AuthorizationLedgerError(
                "AUTHORIZATION_CLOCK_INVALID", "Authorization clock must return UTC time"
            )
        return value.astimezone(timezone.utc)

    def _ensure_parent(self, path: Path) -> None:
        absolute = path.absolute()
        try:
            relative = absolute.relative_to(self._root)
        except ValueError as error:
            raise AuthorizationLedgerError(
                "AUTHORIZATION_STORAGE_UNSAFE",
                "Authorization storage path escapes its root",
            ) from error
        current = _directory(self._root)
        for part in relative.parts:
            current = _directory(current / part)

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        with self._thread_lock:
            info = self._lock_path.lstat()
            attributes = getattr(info, "st_file_attributes", 0)
            if (
                not stat.S_ISREG(info.st_mode)
                or stat.S_ISLNK(info.st_mode)
                or attributes & 0x400
                or info.st_nlink != 1
            ):
                raise AuthorizationLedgerError(
                    "AUTHORIZATION_STORAGE_UNSAFE",
                    "Authorization ledger lock is not a private regular file",
                )
            with self._lock_path.open("r+b") as lock_file:
                lock_file.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
                    try:
                        yield
                    finally:
                        lock_file.seek(0)
                        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                    try:
                        yield
                    finally:
                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _mac(self, domain: str, value: Mapping[str, Any]) -> str:
        message = domain.encode("ascii") + b"\x00" + canonical_json_bytes(dict(value))
        return hmac.new(self._authentication_key, message, hashlib.sha256).hexdigest()

    def _authenticate(self, value: Mapping[str, Any]) -> dict[str, Any]:
        unsigned = {**dict(value), "authKeyId": self._key_id}
        return {
            **unsigned,
            "authTag": self._mac("study.authorization.intent-record.v1", unsigned),
        }

    def _intent_path(self, operation_intent_id: str) -> Path:
        identity = _sha(_id(operation_intent_id, "operationIntentId").encode("utf-8"))
        return self._intents_root / identity[:2] / f"{identity}.json"

    def _safe_read(self, path: Path) -> bytes:
        self._ensure_parent(path.parent)
        try:
            info = path.lstat()
        except FileNotFoundError as error:
            raise AuthorizationLedgerError(
                "OPERATION_INTENT_NOT_FOUND", "Operation intent was not found"
            ) from error
        attributes = getattr(info, "st_file_attributes", 0)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or attributes & 0x400
            or info.st_nlink != 1
        ):
            raise AuthorizationLedgerError(
                "AUTHORIZATION_STORAGE_UNSAFE",
                "Operation intent record is not a private regular file",
            )
        if info.st_size > MAX_RECORD_BYTES:
            raise AuthorizationLedgerError(
                "AUTHORIZATION_RECORD_TOO_LARGE",
                "Operation intent record exceeds its size limit",
            )
        raw = path.read_bytes()
        after = path.lstat()
        before_identity = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
        after_identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        if len(raw) != info.st_size or before_identity != after_identity:
            raise AuthorizationLedgerError(
                "AUTHORIZATION_RECORD_CHANGED",
                "Operation intent record changed while being read",
            )
        return raw

    def _decode(self, raw: bytes) -> dict[str, Any]:
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise AuthorizationLedgerError(
                "AUTHORIZATION_RECORD_INVALID",
                "Operation intent record is not valid JSON",
            ) from error
        if not isinstance(value, dict) or canonical_json_bytes(value) != raw:
            raise AuthorizationLedgerError(
                "AUTHORIZATION_RECORD_INVALID",
                "Operation intent record is not canonical JSON",
            )
        if (
            value.get("schema") != "study.authorization.operation-intent-record"
            or value.get("schemaVersion") != 1
        ):
            raise AuthorizationLedgerError(
                "AUTHORIZATION_RECORD_INVALID",
                "Operation intent record schema is invalid",
            )
        tag = value.get("authTag")
        unsigned = dict(value)
        unsigned.pop("authTag", None)
        if value.get("authKeyId") != self._key_id or not isinstance(tag, str):
            raise AuthorizationLedgerError(
                "AUTHORIZATION_RECORD_CORRUPT",
                "Operation intent authentication key is unavailable",
            )
        if not hmac.compare_digest(
            tag, self._mac("study.authorization.intent-record.v1", unsigned)
        ):
            raise AuthorizationLedgerError(
                "AUTHORIZATION_RECORD_CORRUPT",
                "Operation intent authentication failed",
            )
        return value

    def _load(self, operation_intent_id: str) -> tuple[dict[str, Any], bytes]:
        raw = self._safe_read(self._intent_path(operation_intent_id))
        return self._decode(raw), raw

    def _publish(self, path: Path, raw: bytes) -> None:
        if len(raw) > MAX_RECORD_BYTES:
            raise AuthorizationLedgerError(
                "AUTHORIZATION_RECORD_TOO_LARGE",
                "Operation intent record exceeds its size limit",
            )
        self._ensure_parent(path.parent)
        temporary = _temporary(path, raw)
        try:
            try:
                os.link(temporary, path)
            except FileExistsError as error:
                raise AuthorizationLedgerError(
                    "OPERATION_INTENT_ALREADY_EXISTS", "Operation intent already exists"
                ) from error
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def _replace(self, path: Path, raw: bytes, previous_raw: bytes) -> None:
        if len(raw) > MAX_RECORD_BYTES:
            raise AuthorizationLedgerError(
                "AUTHORIZATION_RECORD_TOO_LARGE",
                "Operation intent record exceeds its size limit",
            )
        self._ensure_parent(path.parent)
        backup = path.with_suffix(path.suffix + ".bak")
        backup_temp = _temporary(backup, previous_raw)
        current_temp = _temporary(path, raw)
        try:
            os.replace(backup_temp, backup)
            os.replace(current_temp, path)
        finally:
            for temporary in (backup_temp, current_temp):
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass

    def _audience_digest(self, audience: ArtifactAudienceBinding) -> str:
        return _sha(
            canonical_json_bytes(
                _audience_manifest(audience, self._service_instance_id)
            )
        )

    def _verify_gesture(
        self,
        *,
        gesture_digest: str,
        audience_digest: str,
        target_id: str,
        action: str,
    ) -> None:
        if self._gesture_attestation_verifier is None:
            raise AuthorizationLedgerError(
                "TRUSTED_GESTURE_VERIFIER_UNAVAILABLE",
                "trusted gesture verification is unavailable",
            )
        try:
            verified = self._gesture_attestation_verifier(
                gesture_digest, audience_digest, target_id, action
            )
        except Exception as error:
            raise AuthorizationLedgerError(
                "TRUSTED_GESTURE_INVALID",
                "trusted gesture attestation could not be verified",
            ) from error
        if verified is not True:
            raise AuthorizationLedgerError(
                "TRUSTED_GESTURE_INVALID",
                "trusted gesture attestation is invalid",
            )

    def _authorize(
        self, record: Mapping[str, Any], audience: ArtifactAudienceBinding
    ) -> None:
        if record.get("audienceDigest") != self._audience_digest(audience):
            raise AuthorizationLedgerError(
                "AUTHORIZATION_AUDIENCE_MISMATCH",
                "Operation intent belongs to another trusted audience",
            )

    def _derive_intent_id(
        self, audience_digest: str, idempotency_key: str
    ) -> str:
        if (
            not isinstance(idempotency_key, str)
            or not 1 <= len(idempotency_key) <= 512
            or any(ord(character) < 0x20 for character in idempotency_key)
        ):
            raise AuthorizationLedgerError(
                "AUTHORIZATION_IDEMPOTENCY_INVALID", "idempotencyKey is invalid"
            )
        message = (
            b"study.operation-intent-id.v1\x00"
            + audience_digest.encode("ascii")
            + b"\x00"
            + idempotency_key.encode("utf-8")
        )
        return "intent_" + hmac.new(
            self._authentication_key, message, hashlib.sha256
        ).hexdigest()[:48]

    @staticmethod
    def _public(record: Mapping[str, Any], now: datetime) -> dict[str, Any]:
        intent = record["intent"]
        approval = record.get("approval")
        expires_at = _parse_timestamp(intent["expiresAt"], "expiresAt")
        state = "pending"
        if isinstance(approval, Mapping):
            state = approval["state"]
        if now >= expires_at and state in {"pending", "approved"}:
            state = "expired"
        return {
            "operationIntentId": intent["operationIntentId"],
            "operationRequestManifestDigest": intent[
                "operationRequestManifestDigest"
            ],
            "intentDigest": intent["intentDigest"],
            "actionId": record["operationRequestManifest"]["actionId"],
            "state": state,
            "expiresAt": intent["expiresAt"],
            "serviceBindingCount": len(
                record["operationRequestManifest"]["serviceBindings"]
            ),
            "authorizationCount": len(record.get("authorizations", [])),
        }

    def create_operation_intent(
        self,
        *,
        audience: ArtifactAudienceBinding,
        idempotency_key: str,
        operation_request_manifest: Mapping[str, Any],
        disclosure_manifest: Mapping[str, Any],
        cost_budget: Mapping[str, Any],
    ) -> dict[str, Any]:
        request = _normalize_operation_request(operation_request_manifest)
        disclosure = _normalize_disclosure_manifest(disclosure_manifest)
        budget = _normalize_cost_budget(cost_budget)
        disclosure_digest = _sha(canonical_json_bytes(disclosure))
        cost_digest = _sha(canonical_json_bytes(budget))
        if request["disclosureManifestDigest"] != disclosure_digest:
            raise AuthorizationLedgerError(
                "AUTHORIZATION_MANIFEST_MISMATCH",
                "disclosure manifest digest does not match the operation request",
            )
        if request["costBudgetDigest"] != cost_digest:
            raise AuthorizationLedgerError(
                "AUTHORIZATION_MANIFEST_MISMATCH",
                "cost budget digest does not match the operation request",
            )
        binding_keys = {
            (item["capability"], item["profileRef"])
            for item in request["serviceBindings"]
        }
        disclosure_keys = {
            (item["target"]["capability"], item["target"]["profileRef"])
            for item in disclosure["entries"]
        }
        if not disclosure_keys or not binding_keys.issubset(disclosure_keys):
            raise AuthorizationLedgerError(
                "AUTHORIZATION_DISCLOSURE_INCOMPLETE",
                "every service binding must have a disclosure entry",
            )
        if not disclosure_keys.issubset(binding_keys):
            raise AuthorizationLedgerError(
                "AUTHORIZATION_DISCLOSURE_SCOPE_MISMATCH",
                "disclosure targets must match the operation service bindings",
            )
        subject = request["subject"]
        if subject["kind"] == "profile_validation":
            matching = [
                item
                for item in request["serviceBindings"]
                if item["profileRef"] == subject["profileRef"]
                and item["configurationFingerprint"]
                == subject["configurationFingerprint"]
                and item["credentialRevision"] == subject["credentialRevision"]
            ]
            if len(matching) != 1 or len(request["serviceBindings"]) != 1:
                raise AuthorizationLedgerError(
                    "AUTHORIZATION_SUBJECT_MISMATCH",
                    "profile validation must bind exactly its validated profile",
                )
        now = self._now()
        expires_at = _parse_timestamp(request["expiresAt"], "expiresAt")
        if expires_at <= now or expires_at - now > MAX_INTENT_LIFETIME:
            raise AuthorizationLedgerError(
                "AUTHORIZATION_EXPIRY_INVALID",
                "operation intent expiry is outside the allowed window",
            )
        audience_digest = self._audience_digest(audience)
        operation_intent_id = self._derive_intent_id(
            audience_digest, idempotency_key
        )
        request_digest = _sha(canonical_json_bytes(request))
        intent_preimage = {
            "schemaVersion": 1,
            "operationIntentId": operation_intent_id,
            "audienceDigest": audience_digest,
            "operationRequestManifestDigest": request_digest,
            "disclosureManifestDigest": disclosure_digest,
            "costBudgetDigest": cost_digest,
            "expiresAt": request["expiresAt"],
        }
        intent = {
            **intent_preimage,
            "intentDigest": _sha(canonical_json_bytes(intent_preimage)),
        }
        creation_digest = _sha(
            canonical_json_bytes(
                {
                    "operationRequestManifest": request,
                    "disclosureManifest": disclosure,
                    "costBudget": budget,
                }
            )
        )
        record = self._authenticate(
            {
                "schema": "study.authorization.operation-intent-record",
                "schemaVersion": 1,
                "audienceDigest": audience_digest,
                "creationRequestDigest": creation_digest,
                "operationRequestManifest": request,
                "disclosureManifest": disclosure,
                "costBudget": budget,
                "intent": intent,
                "approval": None,
                "operationConsumption": None,
                "authorizations": [],
                "globalUsage": {
                    "maxRemoteCalls": budget["maxRemoteCalls"],
                    "consumedRemoteCalls": 0,
                },
                "createdAt": _timestamp(now),
                "updatedAt": _timestamp(now),
            }
        )
        _persistable(record)
        raw = canonical_json_bytes(record)
        path = self._intent_path(operation_intent_id)
        with self._transaction():
            try:
                self._publish(path, raw)
                return self._public(record, now)
            except AuthorizationLedgerError as error:
                if error.code != "OPERATION_INTENT_ALREADY_EXISTS":
                    raise
                existing, _ = self._load(operation_intent_id)
                self._authorize(existing, audience)
                if existing.get("creationRequestDigest") != creation_digest:
                    raise AuthorizationLedgerError(
                        "AUTHORIZATION_IDEMPOTENCY_CONFLICT",
                        "idempotencyKey was already used with different intent input",
                    ) from error
                return self._public(existing, now)

    def get_operation_intent(
        self, operation_intent_id: str, audience: ArtifactAudienceBinding
    ) -> dict[str, Any]:
        now = self._now()
        with self._transaction():
            record, _ = self._load(operation_intent_id)
            self._authorize(record, audience)
            return self._public(record, now)

    def record_operation_decision(
        self,
        *,
        operation_intent_id: str,
        audience: ArtifactAudienceBinding,
        decision: str,
        gesture_attestation_digest: str,
    ) -> dict[str, Any]:
        if decision not in {"approved", "declined"}:
            raise AuthorizationLedgerError(
                "AUTHORIZATION_DECISION_INVALID", "decision is invalid"
            )
        gesture_digest = _digest(
            gesture_attestation_digest, "gestureAttestationDigest"
        )
        now = self._now()
        with self._transaction():
            record, previous_raw = self._load(operation_intent_id)
            self._authorize(record, audience)
            existing = record.get("approval")
            if isinstance(existing, Mapping):
                if (
                    existing.get("state") == decision
                    and existing.get("userGestureRef") == gesture_digest
                ):
                    return self._public(record, now)
                raise AuthorizationLedgerError(
                    "OPERATION_APPROVAL_TERMINAL",
                    "operation intent already has a terminal decision",
                )
            expires_at = _parse_timestamp(record["intent"]["expiresAt"], "expiresAt")
            if now >= expires_at:
                raise AuthorizationLedgerError(
                    "OPERATION_INTENT_EXPIRED", "operation intent has expired"
                )
            self._verify_gesture(
                gesture_digest=gesture_digest,
                audience_digest=record["audienceDigest"],
                target_id=operation_intent_id,
                action=f"decide:{decision}",
            )
            unsigned = dict(record)
            unsigned.pop("authKeyId", None)
            unsigned.pop("authTag", None)
            timestamp = _timestamp(now)
            unsigned["approval"] = {
                "operationIntentId": record["intent"]["operationIntentId"],
                "audienceDigest": record["audienceDigest"],
                "userGestureRef": gesture_digest,
                "state": decision,
                ("approvedAt" if decision == "approved" else "declinedAt"): timestamp,
            }
            unsigned["updatedAt"] = timestamp
            updated = self._authenticate(unsigned)
            self._replace(
                self._intent_path(operation_intent_id),
                canonical_json_bytes(updated),
                previous_raw,
            )
            return self._public(updated, now)

    def _sign_authorization(self, value: Mapping[str, Any]) -> dict[str, Any]:
        unsigned = {**dict(value), "keyId": self._key_id}
        return {
            **unsigned,
            "signature": self._mac(
                "study.internal-authorization-record.v1", unsigned
            ),
        }

    def _verify_authorization(self, value: Mapping[str, Any]) -> None:
        signature = value.get("signature")
        unsigned = dict(value)
        unsigned.pop("signature", None)
        if value.get("keyId") != self._key_id or not isinstance(signature, str):
            raise AuthorizationLedgerError(
                "AUTHORIZATION_RECORD_CORRUPT",
                "internal authorization signing key is unavailable",
            )
        if not hmac.compare_digest(
            signature,
            self._mac("study.internal-authorization-record.v1", unsigned),
        ):
            raise AuthorizationLedgerError(
                "AUTHORIZATION_RECORD_CORRUPT",
                "internal authorization signature is invalid",
            )

    @staticmethod
    def _resource_bindings(
        request: Mapping[str, Any], operation_request_digest: str
    ) -> dict[str, Any]:
        subject = request["subject"]
        exact_refs: list[str] = []
        if subject["kind"] == "project_task":
            exact_refs = sorted(
                [
                    *(
                        f"artifact-digest:{value}"
                        for value in subject["inputArtifactDigests"]
                    ),
                    *(
                        f"source-revision-digest:{value}"
                        for value in subject["sourceRevisionDigests"]
                    ),
                ],
                key=lambda item: item.encode("utf-8"),
            )
            if len(exact_refs) != len(set(exact_refs)):
                raise AuthorizationLedgerError(
                    "AUTHORIZATION_DUPLICATE",
                    "resource binding digests overlap",
                )
        return {
            "exactResourceRefs": exact_refs,
            "resourceRevisionDigest": _sha(canonical_json_bytes(exact_refs)),
            "canonicalRequestDigest": operation_request_digest,
        }

    def _authorization_id(
        self,
        *,
        operation_intent_id: str,
        task_id: str,
        capability: str,
        profile_ref: str,
    ) -> str:
        preimage = canonical_json_bytes(
            {
                "operationIntentId": operation_intent_id,
                "taskId": task_id,
                "capability": capability,
                "profileRef": profile_ref,
            }
        )
        return "authorization_" + hmac.new(
            self._authentication_key,
            b"study.authorization-id.v1\x00" + preimage,
            hashlib.sha256,
        ).hexdigest()[:48]

    @staticmethod
    def _authorization_result(
        operation_intent_id: str,
        task_id: str,
        authorizations: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        bindings: list[dict[str, Any]] = []
        grants: list[dict[str, Any]] = []
        for entry in authorizations:
            record = entry["record"]
            unsigned_record = dict(record)
            unsigned_record.pop("signature", None)
            exact_scope = {
                "subject": record["subject"],
                "action": record["action"],
                "intentId": record["intentId"],
                "taskId": record.get("taskId"),
                "resourceBindings": record["resourceBindings"],
                "serviceBindings": record.get("serviceBindings"),
            }
            record_digest = _sha(canonical_json_bytes(unsigned_record))
            bindings.append(
                {
                    "action": record["action"],
                    "authorizationRecordDigest": record_digest,
                    "constraintsDigest": record["constraintsDigest"],
                    "exactScopeDigest": _sha(canonical_json_bytes(exact_scope)),
                    "expectedRevocationEpoch": entry["ledger"][
                        "currentRevocationEpoch"
                    ],
                }
            )
            grants.append(
                {
                    "authorizationId": record["authorizationId"],
                    "action": record["action"],
                    "authorizationRecordDigest": record_digest,
                }
            )
        bindings.sort(
            key=lambda item: (
                item["action"].encode("utf-8"),
                item["authorizationRecordDigest"],
                item["exactScopeDigest"],
            )
        )
        return {
            "operationIntentId": operation_intent_id,
            "taskId": task_id,
            "authorizationBindings": bindings,
            "internalAuthorizationGrants": grants,
        }

    def consume_operation_approval(
        self,
        *,
        operation_intent_id: str,
        audience: ArtifactAudienceBinding,
        task_id: str,
        consumption_id: str,
        expected_intent_digest: str,
        expected_operation_request_digest: str,
        current_service_bindings: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        task_id = _id(task_id, "taskId")
        consumption_id = _id(consumption_id, "consumptionId")
        expected_intent_digest = _digest(
            expected_intent_digest, "expectedIntentDigest"
        )
        expected_operation_request_digest = _digest(
            expected_operation_request_digest,
            "expectedOperationRequestManifestDigest",
        )
        current_bindings = _normalize_service_bindings(current_service_bindings)
        consumption_digest = _sha(
            canonical_json_bytes(
                {
                    "consumptionIdDigest": _sha(consumption_id.encode("utf-8")),
                    "taskId": task_id,
                    "intentDigest": expected_intent_digest,
                    "operationRequestManifestDigest": expected_operation_request_digest,
                    "serviceBindings": current_bindings,
                }
            )
        )
        now = self._now()
        with self._transaction():
            record, previous_raw = self._load(operation_intent_id)
            self._authorize(record, audience)
            previous_consumption = record.get("operationConsumption")
            if isinstance(previous_consumption, Mapping):
                if previous_consumption.get("consumptionDigest") == consumption_digest:
                    return json.loads(
                        json.dumps(previous_consumption["result"], ensure_ascii=False)
                    )
                raise AuthorizationLedgerError(
                    "OPERATION_APPROVAL_CONSUMED",
                    "operation approval was already consumed for another task",
                )
            intent = record["intent"]
            if intent["intentDigest"] != expected_intent_digest:
                raise AuthorizationLedgerError(
                    "OPERATION_INTENT_MISMATCH", "operation intent digest changed"
                )
            if (
                intent["operationRequestManifestDigest"]
                != expected_operation_request_digest
            ):
                raise AuthorizationLedgerError(
                    "OPERATION_INTENT_MISMATCH",
                    "operation request manifest digest changed",
                )
            request = record["operationRequestManifest"]
            if current_bindings != request["serviceBindings"]:
                raise AuthorizationLedgerError(
                    "AUTHORIZATION_SERVICE_BINDING_STALE",
                    "service profile configuration or credential revision changed",
                )
            approval = record.get("approval")
            if not isinstance(approval, Mapping) or approval.get("state") != "approved":
                raise AuthorizationLedgerError(
                    "OPERATION_APPROVAL_REQUIRED",
                    "operation does not have an approved trusted decision",
                )
            if now >= _parse_timestamp(intent["expiresAt"], "expiresAt"):
                raise AuthorizationLedgerError(
                    "OPERATION_INTENT_EXPIRED", "operation intent has expired"
                )
            resources = self._resource_bindings(
                request, intent["operationRequestManifestDigest"]
            )
            authorizations: list[dict[str, Any]] = []
            for binding in request["serviceBindings"]:
                action = "call_model" if binding["capability"] == "model" else "call_tts"
                if action not in AUTHORIZATION_ACTIONS:
                    raise AuthorizationLedgerError(
                        "AUTHORIZATION_SCHEMA_INVALID", "authorization action is invalid"
                    )
                authorization_id = self._authorization_id(
                    operation_intent_id=operation_intent_id,
                    task_id=task_id,
                    capability=binding["capability"],
                    profile_ref=binding["profileRef"],
                )
                constraints_digest = _sha(
                    canonical_json_bytes(
                        {
                            "operationRequestManifestDigest": intent[
                                "operationRequestManifestDigest"
                            ],
                            "disclosureManifestDigest": intent[
                                "disclosureManifestDigest"
                            ],
                            "costBudgetDigest": intent["costBudgetDigest"],
                            "batchPolicyDigest": request["batchPolicyDigest"],
                            "action": action,
                            "serviceBinding": binding,
                            "maxUses": record["globalUsage"]["maxRemoteCalls"],
                        }
                    )
                )
                authorization = self._sign_authorization(
                    {
                        "schemaVersion": 1,
                        "authorizationId": authorization_id,
                        "issuerServiceInstanceId": self._service_instance_id,
                        "audienceDigest": record["audienceDigest"],
                        "intentId": operation_intent_id,
                        "taskId": task_id,
                        "subject": request["subject"],
                        "action": action,
                        "resourceBindings": resources,
                        "serviceBindings": binding,
                        "constraintsDigest": constraints_digest,
                        "notBefore": _timestamp(now),
                        "expiresAt": intent["expiresAt"],
                        "maxUses": record["globalUsage"]["maxRemoteCalls"],
                        "revocationEpoch": 0,
                        "nonce": secrets.token_hex(32),
                    }
                )
                authorizations.append(
                    {
                        "record": authorization,
                        "ledger": {
                            "authorizationId": authorization_id,
                            "state": "active",
                            "consumedUses": 0,
                            "currentRevocationEpoch": 0,
                            "uses": [],
                        },
                    }
                )
            result = self._authorization_result(
                operation_intent_id, task_id, authorizations
            )
            timestamp = _timestamp(now)
            unsigned = dict(record)
            unsigned.pop("authKeyId", None)
            unsigned.pop("authTag", None)
            unsigned["authorizations"] = authorizations
            unsigned["approval"] = {
                **dict(approval),
                "state": "consumed",
                "consumedAt": timestamp,
            }
            unsigned["operationConsumption"] = {
                "consumptionDigest": consumption_digest,
                "consumedAt": timestamp,
                "result": result,
            }
            unsigned["updatedAt"] = timestamp
            _persistable(unsigned)
            updated = self._authenticate(unsigned)
            self._replace(
                self._intent_path(operation_intent_id),
                canonical_json_bytes(updated),
                previous_raw,
            )
            return json.loads(json.dumps(result, ensure_ascii=False))

    @staticmethod
    def _find_authorization(
        record: Mapping[str, Any], authorization_id: str
    ) -> tuple[int, Mapping[str, Any]]:
        for index, entry in enumerate(record.get("authorizations", [])):
            if entry.get("record", {}).get("authorizationId") == authorization_id:
                return index, entry
        raise AuthorizationLedgerError(
            "AUTHORIZATION_NOT_FOUND", "internal authorization was not found"
        )

    def consume_authorization(
        self,
        *,
        operation_intent_id: str,
        authorization_id: str,
        audience: ArtifactAudienceBinding,
        task_id: str,
        action: str,
        use_id: str,
        expected_authorization_record_digest: str,
        expected_exact_scope_digest: str,
        expected_revocation_epoch: int,
        current_service_binding: Mapping[str, Any],
    ) -> dict[str, Any]:
        authorization_id = _id(authorization_id, "authorizationId")
        task_id = _id(task_id, "taskId")
        use_id = _id(use_id, "useId")
        if action not in AUTHORIZATION_ACTIONS:
            raise AuthorizationLedgerError(
                "AUTHORIZATION_SCHEMA_INVALID", "action is invalid"
            )
        expected_record_digest = _digest(
            expected_authorization_record_digest,
            "expectedAuthorizationRecordDigest",
        )
        expected_scope_digest = _digest(
            expected_exact_scope_digest, "expectedExactScopeDigest"
        )
        expected_epoch = _integer(
            expected_revocation_epoch, "expectedRevocationEpoch"
        )
        normalized_binding = _normalize_service_bindings([current_service_binding])[0]
        use_digest = _sha(
            canonical_json_bytes(
                {
                    "useIdDigest": _sha(use_id.encode("utf-8")),
                    "authorizationId": authorization_id,
                    "taskId": task_id,
                    "action": action,
                    "serviceBinding": normalized_binding,
                    "expectedAuthorizationRecordDigest": expected_record_digest,
                    "expectedExactScopeDigest": expected_scope_digest,
                    "expectedRevocationEpoch": expected_epoch,
                }
            )
        )
        now = self._now()
        with self._transaction():
            record, previous_raw = self._load(operation_intent_id)
            self._authorize(record, audience)
            index, entry = self._find_authorization(record, authorization_id)
            authorization = entry["record"]
            self._verify_authorization(authorization)
            ledger = entry["ledger"]
            for previous_use in ledger.get("uses", []):
                if previous_use.get("useDigest") == use_digest:
                    return json.loads(
                        json.dumps(previous_use["result"], ensure_ascii=False)
                    )
            if authorization.get("taskId") != task_id or authorization.get("action") != action:
                raise AuthorizationLedgerError(
                    "AUTHORIZATION_SCOPE_MISMATCH",
                    "authorization task or action does not match",
                )
            if authorization.get("serviceBindings") != normalized_binding:
                raise AuthorizationLedgerError(
                    "AUTHORIZATION_SERVICE_BINDING_STALE",
                    "service profile configuration or credential revision changed",
                )
            unsigned_authorization = dict(authorization)
            unsigned_authorization.pop("signature", None)
            actual_record_digest = _sha(canonical_json_bytes(unsigned_authorization))
            scope = {
                "subject": authorization["subject"],
                "action": authorization["action"],
                "intentId": authorization["intentId"],
                "taskId": authorization.get("taskId"),
                "resourceBindings": authorization["resourceBindings"],
                "serviceBindings": authorization.get("serviceBindings"),
            }
            actual_scope_digest = _sha(canonical_json_bytes(scope))
            if (
                actual_record_digest != expected_record_digest
                or actual_scope_digest != expected_scope_digest
            ):
                raise AuthorizationLedgerError(
                    "AUTHORIZATION_BINDING_MISMATCH",
                    "authorization record or exact scope digest changed",
                )
            if ledger["currentRevocationEpoch"] != expected_epoch:
                raise AuthorizationLedgerError(
                    "AUTHORIZATION_REVOKED",
                    "authorization revocation epoch changed",
                )
            if ledger["state"] != "active":
                raise AuthorizationLedgerError(
                    "AUTHORIZATION_NOT_ACTIVE",
                    f"authorization is {ledger['state']}",
                )
            if now < _parse_timestamp(authorization["notBefore"], "notBefore"):
                raise AuthorizationLedgerError(
                    "AUTHORIZATION_NOT_ACTIVE", "authorization is not active yet"
                )
            if now >= _parse_timestamp(authorization["expiresAt"], "expiresAt"):
                raise AuthorizationLedgerError(
                    "AUTHORIZATION_EXPIRED", "authorization has expired"
                )
            if record["globalUsage"]["consumedRemoteCalls"] >= record[
                "globalUsage"
            ]["maxRemoteCalls"]:
                raise AuthorizationLedgerError(
                    "OPERATION_BUDGET_CONSUMED",
                    "operation remote-call budget is exhausted",
                )
            if ledger["consumedUses"] >= authorization["maxUses"]:
                raise AuthorizationLedgerError(
                    "AUTHORIZATION_NOT_ACTIVE", "authorization is consumed"
                )
            unsigned = json.loads(json.dumps(record, ensure_ascii=False))
            unsigned.pop("authKeyId", None)
            unsigned.pop("authTag", None)
            mutable_entry = unsigned["authorizations"][index]
            mutable_ledger = mutable_entry["ledger"]
            mutable_ledger["consumedUses"] += 1
            unsigned["globalUsage"]["consumedRemoteCalls"] += 1
            if mutable_ledger["consumedUses"] >= authorization["maxUses"]:
                mutable_ledger["state"] = "consumed"
            timestamp = _timestamp(now)
            result = {
                "authorizationId": authorization_id,
                "state": mutable_ledger["state"],
                "consumedUses": mutable_ledger["consumedUses"],
                "maxUses": authorization["maxUses"],
                "operationConsumedRemoteCalls": unsigned["globalUsage"]
                ["consumedRemoteCalls"],
                "operationMaxRemoteCalls": unsigned["globalUsage"]["maxRemoteCalls"],
                "consumedAt": timestamp,
            }
            mutable_ledger["uses"].append(
                {"useDigest": use_digest, "consumedAt": timestamp, "result": result}
            )
            mutable_ledger["lastConsumedAt"] = timestamp
            unsigned["updatedAt"] = timestamp
            _persistable(unsigned)
            updated = self._authenticate(unsigned)
            self._replace(
                self._intent_path(operation_intent_id),
                canonical_json_bytes(updated),
                previous_raw,
            )
            return json.loads(json.dumps(result, ensure_ascii=False))

    def get_authorization_state(
        self,
        *,
        operation_intent_id: str,
        authorization_id: str,
        audience: ArtifactAudienceBinding,
    ) -> dict[str, Any]:
        authorization_id = _id(authorization_id, "authorizationId")
        now = self._now()
        with self._transaction():
            record, _ = self._load(operation_intent_id)
            self._authorize(record, audience)
            _, entry = self._find_authorization(record, authorization_id)
            authorization = entry["record"]
            self._verify_authorization(authorization)
            ledger = entry["ledger"]
            state = ledger["state"]
            if (
                state == "active"
                and now >= _parse_timestamp(authorization["expiresAt"], "expiresAt")
            ):
                state = "expired"
            return {
                "authorizationId": authorization_id,
                "action": authorization["action"],
                "state": state,
                "consumedUses": ledger["consumedUses"],
                "maxUses": authorization["maxUses"],
                "currentRevocationEpoch": ledger["currentRevocationEpoch"],
                "expiresAt": authorization["expiresAt"],
            }

    def revoke_operation_approval(
        self,
        *,
        operation_intent_id: str,
        audience: ArtifactAudienceBinding,
        revocation_attestation_digest: str,
    ) -> dict[str, Any]:
        attestation = _digest(
            revocation_attestation_digest, "revocationAttestationDigest"
        )
        now = self._now()
        with self._transaction():
            record, previous_raw = self._load(operation_intent_id)
            self._authorize(record, audience)
            approval = record.get("approval")
            if isinstance(approval, Mapping) and approval.get("state") == "revoked":
                if approval.get("revocationAttestationDigest") == attestation:
                    return self._public(record, now)
                raise AuthorizationLedgerError(
                    "OPERATION_APPROVAL_TERMINAL", "operation approval is revoked"
                )
            if isinstance(approval, Mapping) and approval.get("state") in {
                "declined", "consumed", "expired"
            }:
                raise AuthorizationLedgerError(
                    "OPERATION_APPROVAL_TERMINAL",
                    f"operation approval is {approval['state']}",
                )
            if now >= _parse_timestamp(record["intent"]["expiresAt"], "expiresAt"):
                raise AuthorizationLedgerError(
                    "OPERATION_INTENT_EXPIRED", "operation intent has expired"
                )
            self._verify_gesture(
                gesture_digest=attestation,
                audience_digest=record["audienceDigest"],
                target_id=operation_intent_id,
                action="revoke_operation",
            )
            timestamp = _timestamp(now)
            unsigned = json.loads(json.dumps(record, ensure_ascii=False))
            unsigned.pop("authKeyId", None)
            unsigned.pop("authTag", None)
            base = dict(approval) if isinstance(approval, Mapping) else {
                "operationIntentId": record["intent"]["operationIntentId"],
                "audienceDigest": record["audienceDigest"],
                "userGestureRef": attestation,
            }
            unsigned["approval"] = {
                **base,
                "state": "revoked",
                "revokedAt": timestamp,
                "revocationAttestationDigest": attestation,
            }
            unsigned["updatedAt"] = timestamp
            updated = self._authenticate(unsigned)
            self._replace(
                self._intent_path(operation_intent_id),
                canonical_json_bytes(updated),
                previous_raw,
            )
            return self._public(updated, now)

    def revoke_authorization(
        self,
        *,
        operation_intent_id: str,
        authorization_id: str,
        audience: ArtifactAudienceBinding,
        expected_revocation_epoch: int,
        revocation_attestation_digest: str,
    ) -> dict[str, Any]:
        authorization_id = _id(authorization_id, "authorizationId")
        expected_epoch = _integer(
            expected_revocation_epoch, "expectedRevocationEpoch"
        )
        attestation = _digest(
            revocation_attestation_digest, "revocationAttestationDigest"
        )
        now = self._now()
        with self._transaction():
            record, previous_raw = self._load(operation_intent_id)
            self._authorize(record, audience)
            index, entry = self._find_authorization(record, authorization_id)
            self._verify_authorization(entry["record"])
            ledger = entry["ledger"]
            if ledger["state"] == "revoked":
                if (
                    ledger.get("revocationAttestationDigest") == attestation
                    and ledger["currentRevocationEpoch"] == expected_epoch + 1
                ):
                    return {
                        "authorizationId": authorization_id,
                        "action": entry["record"]["action"],
                        "state": "revoked",
                        "consumedUses": ledger["consumedUses"],
                        "maxUses": entry["record"]["maxUses"],
                        "currentRevocationEpoch": ledger[
                            "currentRevocationEpoch"
                        ],
                        "expiresAt": entry["record"]["expiresAt"],
                    }
                raise AuthorizationLedgerError(
                    "AUTHORIZATION_REVOKED", "authorization is already revoked"
                )
            if ledger["state"] != "active":
                raise AuthorizationLedgerError(
                    "AUTHORIZATION_NOT_ACTIVE",
                    f"authorization is {ledger['state']}",
                )
            if ledger["currentRevocationEpoch"] != expected_epoch:
                raise AuthorizationLedgerError(
                    "AUTHORIZATION_REVOKED",
                    "authorization revocation epoch changed",
                )
            self._verify_gesture(
                gesture_digest=attestation,
                audience_digest=record["audienceDigest"],
                target_id=authorization_id,
                action="revoke_authorization",
            )
            timestamp = _timestamp(now)
            unsigned = json.loads(json.dumps(record, ensure_ascii=False))
            unsigned.pop("authKeyId", None)
            unsigned.pop("authTag", None)
            mutable_ledger = unsigned["authorizations"][index]["ledger"]
            mutable_ledger["currentRevocationEpoch"] += 1
            mutable_ledger["state"] = "revoked"
            mutable_ledger["revokedAt"] = timestamp
            mutable_ledger["revocationAttestationDigest"] = attestation
            unsigned["updatedAt"] = timestamp
            updated = self._authenticate(unsigned)
            self._replace(
                self._intent_path(operation_intent_id),
                canonical_json_bytes(updated),
                previous_raw,
            )
            return {
                "authorizationId": authorization_id,
                "action": entry["record"]["action"],
                "state": "revoked",
                "consumedUses": mutable_ledger["consumedUses"],
                "maxUses": entry["record"]["maxUses"],
                "currentRevocationEpoch": mutable_ledger[
                    "currentRevocationEpoch"
                ],
                "expiresAt": entry["record"]["expiresAt"],
            }
