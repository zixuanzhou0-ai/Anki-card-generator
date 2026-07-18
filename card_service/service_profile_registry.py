from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import stat
import threading
import time
import urllib.parse
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping

from .artifact_registry import canonical_json_bytes, validate_persistable_json
from .credentials import CredentialStore, CredentialStoreError, PROFILE_REF_PATTERN
from .provider_egress import ProviderEgressError, ProviderProfile


MAX_PROFILE_RECORD_BYTES = 512 * 1024
MAX_PROFILE_OPERATIONS = 512
MAX_SAFE_INTEGER = 9_007_199_254_740_991
ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,256}$")


class ServiceProfileRegistryError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _require_id(value: Any, label: str, pattern: re.Pattern[str] = ID_PATTERN) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ServiceProfileRegistryError("SERVICE_PROFILE_SCHEMA_INVALID", f"{label} is invalid")
    return value


def _require_exact(value: Any, required: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != required:
        raise ServiceProfileRegistryError(
            "SERVICE_PROFILE_SCHEMA_INVALID", f"{label} fields are invalid"
        )
    return dict(value)


def _integer(value: Any, label: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ServiceProfileRegistryError(
            "SERVICE_PROFILE_SCHEMA_INVALID", f"{label} is outside its allowed range"
        )
    return value


def _temporary_file(path: Path, data: bytes) -> Path:
    temporary = path.parent / f".{path.name}.{secrets.token_hex(12)}.partial"
    with temporary.open("xb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())
    return temporary


def _ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    info = path.lstat()
    attributes = getattr(info, "st_file_attributes", 0)
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or attributes & 0x400:
        raise ServiceProfileRegistryError(
            "SERVICE_PROFILE_STORAGE_UNSAFE", "Service profile storage contains a link or reparse directory"
        )
    return path


def _normalize_anki_url(value: Any) -> str:
    if not isinstance(value, str):
        raise ServiceProfileRegistryError("SERVICE_PROFILE_SCHEMA_INVALID", "AnkiConnect baseUrl is invalid")
    try:
        parsed = urllib.parse.urlsplit(value.strip())
        port = parsed.port
    except ValueError as error:
        raise ServiceProfileRegistryError(
            "SERVICE_PROFILE_SCHEMA_INVALID", "AnkiConnect baseUrl is invalid"
        ) from error
    host = (parsed.hostname or "").casefold()
    if (
        parsed.scheme != "http"
        or host not in {"127.0.0.1", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ServiceProfileRegistryError(
            "SERVICE_PROFILE_SCHEMA_INVALID", "AnkiConnect must use a literal loopback HTTP endpoint"
        )
    if port is None:
        port = 8765
    if not 1 <= port <= 65535:
        raise ServiceProfileRegistryError(
            "SERVICE_PROFILE_SCHEMA_INVALID", "AnkiConnect port is invalid"
        )
    netloc = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
    return urllib.parse.urlunsplit(("http", netloc, "", "", ""))


def normalize_profile_configuration(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ServiceProfileRegistryError(
            "SERVICE_PROFILE_SCHEMA_INVALID", "Service profile configuration must be an object"
        )
    draft = dict(value)
    if "schema" in draft or "schemaVersion" in draft:
        if (
            draft.get("schema") != "study.service-profile.configuration"
            or draft.get("schemaVersion") != 1
        ):
            raise ServiceProfileRegistryError(
                "SERVICE_PROFILE_SCHEMA_INVALID", "Service profile configuration schema is invalid"
            )
        draft.pop("schema")
        draft.pop("schemaVersion")
    capability = draft.get("capability")
    if capability in {"model", "tts"}:
        source = _require_exact(
            draft,
            {
                "profileRef", "capability", "provider", "baseUrl", "model", "voice",
                "timeoutSeconds", "maximumResponseBytes", "authMode",
            },
            "provider profile",
        )
        if any(
            not isinstance(source[field], str)
            for field in ("provider", "baseUrl", "model", "voice", "authMode")
        ):
            raise ServiceProfileRegistryError(
                "SERVICE_PROFILE_SCHEMA_INVALID", "Provider profile text fields are invalid"
            )
        profile_ref = _require_id(source["profileRef"], "profileRef", PROFILE_REF_PATTERN)
        timeout_seconds = _integer(source["timeoutSeconds"], "timeoutSeconds", minimum=1, maximum=180)
        maximum_response_bytes = _integer(
            source["maximumResponseBytes"], "maximumResponseBytes", minimum=1, maximum=1024 * 1024
        )
        try:
            profile = ProviderProfile(
                profile_ref=profile_ref,
                capability=capability,
                provider=source["provider"],
                base_url=source["baseUrl"],
                model=source["model"],
                voice=source["voice"],
                timeout_seconds=timeout_seconds,
                maximum_response_bytes=maximum_response_bytes,
            )
        except (ProviderEgressError, ValueError, TypeError) as error:
            raise ServiceProfileRegistryError(
                "SERVICE_PROFILE_SCHEMA_INVALID", "Provider profile configuration is invalid"
            ) from error
        auth_mode = source["authMode"]
        expected_auth = "none" if profile.provider == "hermes" else "bearer"
        if auth_mode != expected_auth:
            raise ServiceProfileRegistryError(
                "SERVICE_PROFILE_SCHEMA_INVALID", "Provider profile authentication mode is invalid"
            )
        if capability == "model" and profile.voice:
            raise ServiceProfileRegistryError(
                "SERVICE_PROFILE_SCHEMA_INVALID", "Model profile cannot declare a voice"
            )
        normalized = {
            "schema": "study.service-profile.configuration",
            "schemaVersion": 1,
            "profileRef": profile.profile_ref,
            "capability": profile.capability,
            "provider": profile.provider,
            "baseUrl": profile.base_url,
            "model": profile.model,
            "voice": profile.voice,
            "timeoutSeconds": int(profile.timeout_seconds),
            "maximumResponseBytes": profile.maximum_response_bytes,
            "authMode": auth_mode,
        }
    elif capability == "anki_connect":
        source = _require_exact(
            draft,
            {
                "profileRef", "capability", "provider", "baseUrl", "apiVersion",
                "timeoutSeconds", "maximumResponseBytes", "authMode",
            },
            "AnkiConnect profile",
        )
        profile_ref = _require_id(source["profileRef"], "profileRef", PROFILE_REF_PATTERN)
        if source["provider"] != "anki_connect" or source["authMode"] not in {"none", "bearer"}:
            raise ServiceProfileRegistryError(
                "SERVICE_PROFILE_SCHEMA_INVALID", "AnkiConnect profile identity is invalid"
            )
        normalized = {
            "schema": "study.service-profile.configuration",
            "schemaVersion": 1,
            "profileRef": profile_ref,
            "capability": "anki_connect",
            "provider": "anki_connect",
            "baseUrl": _normalize_anki_url(source["baseUrl"]),
            "apiVersion": _integer(source["apiVersion"], "apiVersion", minimum=5, maximum=6),
            "timeoutSeconds": _integer(source["timeoutSeconds"], "timeoutSeconds", minimum=1, maximum=30),
            "maximumResponseBytes": _integer(
                source["maximumResponseBytes"], "maximumResponseBytes", minimum=1, maximum=16 * 1024 * 1024
            ),
            "authMode": source["authMode"],
        }
    else:
        raise ServiceProfileRegistryError(
            "SERVICE_PROFILE_SCHEMA_INVALID", "Service profile capability is unsupported"
        )
    try:
        validate_persistable_json(normalized)
    except RuntimeError as error:
        raise ServiceProfileRegistryError(
            "SERVICE_PROFILE_FORBIDDEN_DATA", "Service profile contains forbidden data"
        ) from error
    return normalized


def profile_configuration_fingerprint(configuration: Mapping[str, Any]) -> str:
    normalized = normalize_profile_configuration(configuration)
    return hashlib.sha256(canonical_json_bytes(normalized)).hexdigest()


class ServiceProfileRegistry:
    """Authenticated non-secret profile registry backed by current CredentialStore state."""

    def __init__(
        self,
        root: Path,
        *,
        authentication_key: bytes,
        credential_store: CredentialStore,
        key_id: str = "study-service-profile-v1",
    ) -> None:
        if not isinstance(authentication_key, bytes) or len(authentication_key) < 32:
            raise ServiceProfileRegistryError(
                "SERVICE_PROFILE_AUTH_KEY_INVALID", "Profile authentication key must contain at least 256 bits"
            )
        if not isinstance(credential_store, CredentialStore):
            raise ServiceProfileRegistryError(
                "SERVICE_PROFILE_CREDENTIAL_STORE_INVALID", "A trusted CredentialStore is required"
            )
        self._authentication_key = bytes(authentication_key)
        self._credential_store = credential_store
        self._key_id = _require_id(key_id, "keyId")
        self._root = _ensure_directory(Path(root).absolute())
        self._profiles_root = _ensure_directory(self._root / "profiles")
        self._lock_path = self._root / "service-profiles.lock"
        try:
            with self._lock_path.open("xb") as output:
                output.write(b"\x00")
                output.flush()
                os.fsync(output.fileno())
        except FileExistsError:
            pass
        self._thread_lock = threading.RLock()

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
                raise ServiceProfileRegistryError(
                    "SERVICE_PROFILE_STORAGE_UNSAFE", "Service profile lock is not a private regular file"
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
        return {**unsigned, "authTag": self._mac("study.service-profile.record.v1", unsigned)}

    def _path(self, profile_ref: str) -> Path:
        profile_ref = _require_id(profile_ref, "profileRef", PROFILE_REF_PATTERN)
        identity = hashlib.sha256(profile_ref.encode("utf-8")).hexdigest()
        return self._profiles_root / identity[:2] / f"{identity}.json"

    def _ensure_parent(self, path: Path) -> None:
        current = _ensure_directory(self._root)
        try:
            relative = path.absolute().relative_to(self._root)
        except ValueError as error:
            raise ServiceProfileRegistryError(
                "SERVICE_PROFILE_STORAGE_UNSAFE", "Service profile path escapes its root"
            ) from error
        for part in relative.parts:
            current = _ensure_directory(current / part)

    def _safe_read(self, path: Path) -> bytes:
        self._ensure_parent(path.parent)
        try:
            info = path.lstat()
        except FileNotFoundError as error:
            raise ServiceProfileRegistryError(
                "SERVICE_PROFILE_NOT_FOUND", "Service profile was not found"
            ) from error
        attributes = getattr(info, "st_file_attributes", 0)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or attributes & 0x400
            or info.st_nlink != 1
            or info.st_size > MAX_PROFILE_RECORD_BYTES
        ):
            raise ServiceProfileRegistryError(
                "SERVICE_PROFILE_STORAGE_UNSAFE", "Service profile record is unsafe or too large"
            )
        raw = path.read_bytes()
        after = path.lstat()
        if (
            len(raw) != info.st_size
            or (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        ):
            raise ServiceProfileRegistryError(
                "SERVICE_PROFILE_RECORD_CHANGED", "Service profile changed while being read"
            )
        return raw

    def _decode(self, raw: bytes) -> dict[str, Any]:
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ServiceProfileRegistryError(
                "SERVICE_PROFILE_RECORD_INVALID", "Service profile record is not valid JSON"
            ) from error
        if not isinstance(value, dict) or canonical_json_bytes(value) != raw:
            raise ServiceProfileRegistryError(
                "SERVICE_PROFILE_RECORD_INVALID", "Service profile record is not canonical JSON"
            )
        if set(value) != {
            "schema", "schemaVersion", "profile", "operations", "updatedAt", "authKeyId", "authTag",
        } or value.get("schema") != "study.service-profile.record" or value.get("schemaVersion") != 1:
            raise ServiceProfileRegistryError(
                "SERVICE_PROFILE_RECORD_INVALID", "Service profile record schema is invalid"
            )
        tag = value.get("authTag")
        unsigned = dict(value)
        unsigned.pop("authTag", None)
        if (
            value.get("authKeyId") != self._key_id
            or not isinstance(tag, str)
            or re.fullmatch(r"[0-9a-f]{64}", tag) is None
        ):
            raise ServiceProfileRegistryError(
                "SERVICE_PROFILE_RECORD_CORRUPT", "Service profile authentication is unavailable"
            )
        if not hmac.compare_digest(tag, self._mac("study.service-profile.record.v1", unsigned)):
            raise ServiceProfileRegistryError(
                "SERVICE_PROFILE_RECORD_CORRUPT", "Service profile authentication failed"
            )
        self._validate_decoded_record(value)
        return value

    def _validate_decoded_record(self, value: Mapping[str, Any]) -> None:
        try:
            record_updated_at = _integer(
                value.get("updatedAt"), "updatedAt", minimum=0, maximum=MAX_SAFE_INTEGER
            )
            profile = _require_exact(
                value.get("profile"),
                {
                    "profileRef", "capability", "profileRevision", "active",
                    "configurationFingerprint", "configuration", "credentialBindingAtSave",
                    "updatedAt",
                },
                "profile record",
            )
        except ServiceProfileRegistryError as error:
            raise ServiceProfileRegistryError(
                "SERVICE_PROFILE_RECORD_INVALID", "Service profile record structure is invalid"
            ) from error
        operations = value.get("operations")
        if not isinstance(operations, dict) or not 1 <= len(operations) <= MAX_PROFILE_OPERATIONS:
            raise ServiceProfileRegistryError(
                "SERVICE_PROFILE_RECORD_INVALID", "Service profile operation ledger is invalid"
            )
        try:
            revision = _integer(
                profile.get("profileRevision"),
                "profileRevision",
                minimum=1,
                maximum=MAX_SAFE_INTEGER,
            )
            profile_updated_at = _integer(
                profile.get("updatedAt"), "profile.updatedAt", minimum=0, maximum=MAX_SAFE_INTEGER
            )
        except ServiceProfileRegistryError as error:
            raise ServiceProfileRegistryError(
                "SERVICE_PROFILE_RECORD_INVALID", "Service profile revision is invalid"
            ) from error
        if record_updated_at < profile_updated_at:
            raise ServiceProfileRegistryError(
                "SERVICE_PROFILE_RECORD_INVALID", "Service profile timestamps are inconsistent"
            )
        try:
            configuration = normalize_profile_configuration(profile.get("configuration"))
        except ServiceProfileRegistryError as error:
            raise ServiceProfileRegistryError(
                "SERVICE_PROFILE_RECORD_INVALID", "Service profile configuration is invalid"
            ) from error
        if configuration != profile.get("configuration"):
            raise ServiceProfileRegistryError(
                "SERVICE_PROFILE_RECORD_INVALID", "Service profile configuration is not normalized"
            )
        fingerprint = profile.get("configurationFingerprint")
        if (
            not isinstance(fingerprint, str)
            or re.fullmatch(r"[0-9a-f]{64}", fingerprint) is None
            or fingerprint != hashlib.sha256(canonical_json_bytes(configuration)).hexdigest()
        ):
            raise ServiceProfileRegistryError(
                "SERVICE_PROFILE_RECORD_CORRUPT", "Service profile fingerprint is invalid"
            )
        if (
            profile.get("profileRef") != configuration["profileRef"]
            or profile.get("capability") != configuration["capability"]
        ):
            raise ServiceProfileRegistryError(
                "SERVICE_PROFILE_RECORD_CORRUPT", "Service profile identity is invalid"
            )
        if not isinstance(profile.get("active"), bool):
            raise ServiceProfileRegistryError(
                "SERVICE_PROFILE_RECORD_INVALID", "Service profile active state is invalid"
            )
        try:
            binding = _require_exact(
                profile.get("credentialBindingAtSave"),
                {
                    "secretRef", "credentialRevision", "credentialState",
                    "secretRequired", "secretExists",
                },
                "credential binding",
            )
            credential_revision = _integer(
                binding["credentialRevision"],
                "credentialRevision",
                minimum=0,
                maximum=MAX_SAFE_INTEGER,
            )
        except ServiceProfileRegistryError as error:
            raise ServiceProfileRegistryError(
                "SERVICE_PROFILE_RECORD_INVALID", "Saved credential binding is invalid"
            ) from error
        secret_required = configuration["authMode"] != "none"
        if (
            not isinstance(binding["secretRequired"], bool)
            or not isinstance(binding["secretExists"], bool)
            or binding["secretRequired"] != secret_required
        ):
            raise ServiceProfileRegistryError(
                "SERVICE_PROFILE_RECORD_INVALID", "Saved credential binding is inconsistent"
            )
        if not secret_required:
            if binding != {
                "secretRef": None,
                "credentialRevision": 0,
                "credentialState": "committed",
                "secretRequired": False,
                "secretExists": False,
            }:
                raise ServiceProfileRegistryError(
                    "SERVICE_PROFILE_RECORD_INVALID", "Secret-free profile has a credential binding"
                )
        elif (
            not isinstance(binding["secretRef"], str)
            or re.fullmatch(r"secret_[0-9a-f]{48}", binding["secretRef"]) is None
            or binding["credentialState"] not in {"committed", "missing", "pending", "uncertain"}
            or (binding["credentialState"] == "committed" and not binding["secretExists"])
            or (binding["credentialState"] == "missing" and binding["secretExists"])
            or (credential_revision == 0 and binding["secretExists"])
        ):
            raise ServiceProfileRegistryError(
                "SERVICE_PROFILE_RECORD_INVALID", "Saved credential binding is invalid"
            )
        for operation_digest, operation in operations.items():
            if (
                not isinstance(operation_digest, str)
                or re.fullmatch(r"[0-9a-f]{64}", operation_digest) is None
            ):
                raise ServiceProfileRegistryError(
                    "SERVICE_PROFILE_RECORD_INVALID", "Service profile operation identity is invalid"
                )
            try:
                operation_value = _require_exact(
                    operation, {"payloadDigest", "resultRevision"}, "profile operation"
                )
                _integer(
                    operation_value["resultRevision"],
                    "resultRevision",
                    minimum=1,
                    maximum=revision,
                )
            except ServiceProfileRegistryError as error:
                raise ServiceProfileRegistryError(
                    "SERVICE_PROFILE_RECORD_INVALID", "Service profile operation is invalid"
                ) from error
            payload_digest = operation_value["payloadDigest"]
            if (
                not isinstance(payload_digest, str)
                or re.fullmatch(r"[0-9a-f]{64}", payload_digest) is None
            ):
                raise ServiceProfileRegistryError(
                    "SERVICE_PROFILE_RECORD_INVALID", "Service profile operation digest is invalid"
                )

    def _load(self, profile_ref: str) -> tuple[dict[str, Any], bytes]:
        raw = self._safe_read(self._path(profile_ref))
        value = self._decode(raw)
        if value["profile"].get("profileRef") != profile_ref:
            raise ServiceProfileRegistryError(
                "SERVICE_PROFILE_RECORD_CORRUPT", "Service profile path binding is invalid"
            )
        return value, raw

    def _operation_digest(self, operation_id: str) -> str:
        operation_id = _require_id(operation_id, "operationId")
        return hmac.new(
            self._authentication_key,
            b"study.service-profile.operation.v1\x00" + operation_id.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _credential_binding(self, configuration: Mapping[str, Any]) -> dict[str, Any]:
        secret_required = configuration["authMode"] != "none"
        if not secret_required:
            return {
                "secretRef": None,
                "credentialRevision": 0,
                "credentialState": "committed",
                "secretRequired": False,
                "secretExists": False,
            }
        try:
            metadata = self._credential_store.metadata(str(configuration["profileRef"]))
            credential_revision = _integer(
                metadata["credentialRevision"],
                "credentialRevision",
                minimum=0,
                maximum=MAX_SAFE_INTEGER,
            )
            credential_state = metadata["state"]
            secret_exists = metadata["exists"]
            secret_ref = metadata["secretRef"]
            if (
                credential_state not in {"committed", "uncertain"}
                or not isinstance(secret_exists, bool)
                or not isinstance(secret_ref, str)
                or re.fullmatch(r"secret_[0-9a-f]{48}", secret_ref) is None
                or (credential_revision == 0 and secret_exists)
            ):
                raise ServiceProfileRegistryError(
                    "SERVICE_PROFILE_SCHEMA_INVALID", "Credential metadata is invalid"
                )
        except (CredentialStoreError, KeyError, ServiceProfileRegistryError) as error:
            raise ServiceProfileRegistryError(
                "SERVICE_PROFILE_CREDENTIAL_UNAVAILABLE", "Credential binding could not be resolved"
            ) from error
        if credential_state == "committed" and not secret_exists:
            credential_state = "missing"
        return {
            "secretRef": secret_ref,
            "credentialRevision": credential_revision,
            "credentialState": credential_state,
            "secretRequired": True,
            "secretExists": secret_exists,
        }

    @staticmethod
    def _public(profile: Mapping[str, Any], current_credential: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "profileRef": profile["profileRef"],
            "capability": profile["capability"],
            "profileRevision": profile["profileRevision"],
            "active": profile["active"],
            "configurationFingerprint": profile["configurationFingerprint"],
            "configuration": json.loads(json.dumps(profile["configuration"])),
            "credentialRevision": current_credential["credentialRevision"],
            "credentialState": current_credential["credentialState"],
            "secretRequired": current_credential["secretRequired"],
            "secretExists": current_credential["secretExists"],
            "updatedAt": profile["updatedAt"],
        }

    def save_profile(
        self,
        configuration: Mapping[str, Any],
        *,
        expected_revision: int,
        operation_id: str,
    ) -> dict[str, Any]:
        normalized = normalize_profile_configuration(configuration)
        expected_revision = _integer(
            expected_revision, "expectedRevision", minimum=0, maximum=MAX_SAFE_INTEGER
        )
        fingerprint = hashlib.sha256(canonical_json_bytes(normalized)).hexdigest()
        operation_digest = self._operation_digest(operation_id)
        payload_digest = hashlib.sha256(canonical_json_bytes({
            "action": "save",
            "expectedRevision": expected_revision,
            "configuration": normalized,
        })).hexdigest()
        path = self._path(str(normalized["profileRef"]))
        with self._transaction():
            exists = path.is_file()
            if exists:
                record, previous_raw = self._load(str(normalized["profileRef"]))
                replay = record["operations"].get(operation_digest)
                if replay is not None:
                    if replay.get("payloadDigest") != payload_digest:
                        raise ServiceProfileRegistryError(
                            "SERVICE_PROFILE_IDEMPOTENCY_CONFLICT", "operationId was reused for another change"
                        )
                    if replay["resultRevision"] != record["profile"]["profileRevision"]:
                        raise ServiceProfileRegistryError(
                            "SERVICE_PROFILE_IDEMPOTENCY_RESULT_SUPERSEDED",
                            "The original service profile result has been superseded",
                        )
                    return self._public(record["profile"], self._credential_binding(record["profile"]["configuration"]))
                current_revision = int(record["profile"]["profileRevision"])
            else:
                record = None
                previous_raw = None
                current_revision = 0
            if current_revision != expected_revision:
                raise ServiceProfileRegistryError(
                    "SERVICE_PROFILE_REVISION_CONFLICT", "Service profile revision is stale"
                )
            current_credential = self._credential_binding(normalized)
            no_change = bool(
                record
                and record["profile"]["active"]
                and record["profile"]["configuration"] == normalized
            )
            if not no_change and current_revision == MAX_SAFE_INTEGER:
                raise ServiceProfileRegistryError(
                    "SERVICE_PROFILE_REVISION_EXHAUSTED", "Service profile revision is exhausted"
                )
            next_revision = current_revision if no_change else current_revision + 1
            if next_revision == 0:
                next_revision = 1
            now_ms = int(time.time() * 1000)
            profile = {
                "profileRef": normalized["profileRef"],
                "capability": normalized["capability"],
                "profileRevision": next_revision,
                "active": True,
                "configurationFingerprint": fingerprint,
                "configuration": normalized,
                "credentialBindingAtSave": (
                    record["profile"]["credentialBindingAtSave"] if no_change else current_credential
                ),
                "updatedAt": record["profile"]["updatedAt"] if no_change else now_ms,
            }
            operations = dict(record["operations"]) if record else {}
            if len(operations) >= MAX_PROFILE_OPERATIONS:
                raise ServiceProfileRegistryError(
                    "SERVICE_PROFILE_OPERATION_LEDGER_FULL", "Service profile operation ledger is full"
                )
            operations[operation_digest] = {
                "payloadDigest": payload_digest,
                "resultRevision": next_revision,
            }
            unsigned = {
                "schema": "study.service-profile.record",
                "schemaVersion": 1,
                "profile": profile,
                "operations": operations,
                "updatedAt": now_ms,
            }
            raw = canonical_json_bytes(self._authenticate(unsigned))
            if len(raw) > MAX_PROFILE_RECORD_BYTES:
                raise ServiceProfileRegistryError(
                    "SERVICE_PROFILE_RECORD_TOO_LARGE", "Service profile record exceeds its size limit"
                )
            self._ensure_parent(path.parent)
            temporary = _temporary_file(path, raw)
            try:
                if previous_raw is None:
                    try:
                        os.link(temporary, path)
                    except FileExistsError as error:
                        raise ServiceProfileRegistryError(
                            "SERVICE_PROFILE_REVISION_CONFLICT", "Service profile was created concurrently"
                        ) from error
                else:
                    backup = path.with_suffix(path.suffix + ".bak")
                    backup_temp = _temporary_file(backup, previous_raw)
                    try:
                        os.replace(backup_temp, backup)
                        os.replace(temporary, path)
                    finally:
                        try:
                            backup_temp.unlink()
                        except FileNotFoundError:
                            pass
            finally:
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass
            return self._public(profile, current_credential)

    def delete_profile(
        self,
        profile_ref: str,
        *,
        expected_revision: int,
        operation_id: str,
    ) -> dict[str, Any]:
        profile_ref = _require_id(profile_ref, "profileRef", PROFILE_REF_PATTERN)
        expected_revision = _integer(
            expected_revision, "expectedRevision", minimum=1, maximum=MAX_SAFE_INTEGER
        )
        operation_digest = self._operation_digest(operation_id)
        payload_digest = hashlib.sha256(canonical_json_bytes({
            "action": "delete", "profileRef": profile_ref, "expectedRevision": expected_revision,
        })).hexdigest()
        with self._transaction():
            record, previous_raw = self._load(profile_ref)
            replay = record["operations"].get(operation_digest)
            if replay is not None:
                if replay.get("payloadDigest") != payload_digest:
                    raise ServiceProfileRegistryError(
                        "SERVICE_PROFILE_IDEMPOTENCY_CONFLICT", "operationId was reused for another change"
                    )
                if replay["resultRevision"] != record["profile"]["profileRevision"]:
                    raise ServiceProfileRegistryError(
                        "SERVICE_PROFILE_IDEMPOTENCY_RESULT_SUPERSEDED",
                        "The original service profile result has been superseded",
                    )
                return self._public(record["profile"], self._credential_binding(record["profile"]["configuration"]))
            profile = dict(record["profile"])
            if int(profile["profileRevision"]) != expected_revision:
                raise ServiceProfileRegistryError(
                    "SERVICE_PROFILE_REVISION_CONFLICT", "Service profile revision is stale"
                )
            if profile["active"]:
                if expected_revision == MAX_SAFE_INTEGER:
                    raise ServiceProfileRegistryError(
                        "SERVICE_PROFILE_REVISION_EXHAUSTED", "Service profile revision is exhausted"
                    )
                profile.update(
                    active=False,
                    profileRevision=expected_revision + 1,
                    updatedAt=int(time.time() * 1000),
                )
            operations = dict(record["operations"])
            if len(operations) >= MAX_PROFILE_OPERATIONS:
                raise ServiceProfileRegistryError(
                    "SERVICE_PROFILE_OPERATION_LEDGER_FULL", "Service profile operation ledger is full"
                )
            operations[operation_digest] = {
                "payloadDigest": payload_digest,
                "resultRevision": profile["profileRevision"],
            }
            unsigned = {
                "schema": "study.service-profile.record",
                "schemaVersion": 1,
                "profile": profile,
                "operations": operations,
                "updatedAt": int(time.time() * 1000),
            }
            path = self._path(profile_ref)
            raw = canonical_json_bytes(self._authenticate(unsigned))
            backup = path.with_suffix(path.suffix + ".bak")
            backup_temp = _temporary_file(backup, previous_raw)
            current_temp = _temporary_file(path, raw)
            try:
                os.replace(backup_temp, backup)
                os.replace(current_temp, path)
            finally:
                for temporary in (backup_temp, current_temp):
                    try:
                        temporary.unlink()
                    except FileNotFoundError:
                        pass
            return self._public(profile, self._credential_binding(profile["configuration"]))

    def get_profile(self, profile_ref: str) -> dict[str, Any]:
        with self._transaction():
            record, _ = self._load(_require_id(profile_ref, "profileRef", PROFILE_REF_PATTERN))
            return self._public(record["profile"], self._credential_binding(record["profile"]["configuration"]))

    def resolve_binding(self, capability: str, profile_ref: str) -> dict[str, Any] | None:
        with self._transaction():
            try:
                record, _ = self._load(_require_id(profile_ref, "profileRef", PROFILE_REF_PATTERN))
            except ServiceProfileRegistryError as error:
                if error.code == "SERVICE_PROFILE_NOT_FOUND":
                    return None
                raise
            profile = record["profile"]
            if not profile["active"] or profile["capability"] != capability:
                return None
            credential = self._credential_binding(profile["configuration"])
            return {
                "capability": profile["capability"],
                "profileRef": profile["profileRef"],
                "configurationFingerprint": profile["configurationFingerprint"],
                "credentialRevision": credential["credentialRevision"],
                "credentialState": credential["credentialState"],
                "secretRequired": credential["secretRequired"],
                "secretExists": credential["secretExists"],
            }

    def list_profiles(self, *, include_inactive: bool = False) -> list[dict[str, Any]]:
        profiles: list[dict[str, Any]] = []
        with self._transaction():
            for path in sorted(self._profiles_root.glob("*/*.json")):
                raw = self._safe_read(path)
                record = self._decode(raw)
                profile = record["profile"]
                if path != self._path(str(profile["profileRef"])):
                    raise ServiceProfileRegistryError(
                        "SERVICE_PROFILE_RECORD_CORRUPT",
                        "Service profile record is stored under the wrong identity",
                    )
                if include_inactive or profile["active"]:
                    profiles.append(
                        self._public(profile, self._credential_binding(profile["configuration"]))
                    )
        profiles.sort(key=lambda item: (item["capability"].encode("utf-8"), item["profileRef"].encode("utf-8")))
        return profiles
