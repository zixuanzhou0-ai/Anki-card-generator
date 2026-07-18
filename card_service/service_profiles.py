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
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence

from .artifact_registry import canonical_json_bytes


CAPABILITIES = frozenset({"model", "tts", "anki_connect"})
RESULT_STATUSES = frozenset({"passed", "failed"})
PROFILE_REF_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,256}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
MAX_SAFE_INTEGER = 9_007_199_254_740_991
MAX_RECORDS = 4_096
MAX_LEDGER_BYTES = 8 * 1024 * 1024
DEFAULT_VERIFICATION_MAX_AGE_SECONDS = 7 * 24 * 60 * 60


class ServiceProfileVerificationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


BindingResolver = Callable[[str, str], Mapping[str, Any] | None]


def _require_id(value: Any, label: str, pattern: re.Pattern[str] = ID_PATTERN) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ServiceProfileVerificationError("PROFILE_VERIFICATION_SCHEMA_INVALID", f"{label} is invalid")
    return value


def _require_fingerprint(value: Any) -> str:
    if not isinstance(value, str) or not SHA256_PATTERN.fullmatch(value):
        raise ServiceProfileVerificationError(
            "PROFILE_VERIFICATION_SCHEMA_INVALID",
            "configurationFingerprint must be a lowercase SHA-256 digest",
        )
    return value


def _require_revision(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > MAX_SAFE_INTEGER:
        raise ServiceProfileVerificationError(
            "PROFILE_VERIFICATION_SCHEMA_INVALID",
            "credentialRevision must be a non-negative safe integer",
        )
    return value


def _temporary_file(path: Path, data: bytes) -> Path:
    temporary = path.parent / f".{path.name}.{secrets.token_hex(12)}.partial"
    with temporary.open("xb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())
    return temporary


class ServiceProfileVerificationRegistry:
    """Authenticated latest-result ledger for model, TTS and AnkiConnect profiles.

    The registry never owns a profile configuration.  A trusted resolver supplies
    the current non-secret binding, so a result completed after configuration or
    credential changes is retained as stale audit evidence and cannot unlock the
    new binding.
    """

    def __init__(
        self,
        root: Path,
        *,
        authentication_key: bytes,
        binding_resolver: BindingResolver,
        key_id: str = "study-profile-verification-v1",
        verification_max_age_seconds: int = DEFAULT_VERIFICATION_MAX_AGE_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not isinstance(authentication_key, bytes) or len(authentication_key) < 32:
            raise ServiceProfileVerificationError(
                "PROFILE_VERIFICATION_AUTH_KEY_INVALID",
                "Verification authentication key must contain at least 256 bits",
            )
        if not callable(binding_resolver):
            raise ServiceProfileVerificationError(
                "PROFILE_VERIFICATION_RESOLVER_INVALID", "A trusted profile binding resolver is required"
            )
        if (
            isinstance(verification_max_age_seconds, bool)
            or not isinstance(verification_max_age_seconds, int)
            or not 60 <= verification_max_age_seconds <= 90 * 24 * 60 * 60
        ):
            raise ServiceProfileVerificationError(
                "PROFILE_VERIFICATION_TTL_INVALID", "Verification maximum age is invalid"
            )
        self._authentication_key = bytes(authentication_key)
        self._binding_resolver = binding_resolver
        self._key_id = _require_id(key_id, "keyId")
        self._clock = clock
        self._max_age_ms = verification_max_age_seconds * 1000
        self._root = Path(root).absolute()
        self._root.mkdir(parents=True, exist_ok=True)
        self._path = self._root / "service-profile-verifications.json"
        self._backup_path = self._path.with_suffix(self._path.suffix + ".bak")
        self._lock_path = self._root / "service-profile-verifications.lock"
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
                raise ServiceProfileVerificationError(
                    "PROFILE_VERIFICATION_STORAGE_UNSAFE",
                    "Verification registry lock is not a private regular file",
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
        return {**unsigned, "authTag": self._mac("study.profile-verification.ledger.v1", unsigned)}

    @staticmethod
    def _empty() -> dict[str, Any]:
        return {
            "schema": "study.profile-verification.ledger",
            "schemaVersion": 1,
            "sequence": 0,
            "records": [],
            "idempotency": {},
            "updatedAt": 0,
        }

    def _decode(self, raw: bytes) -> dict[str, Any]:
        if len(raw) > MAX_LEDGER_BYTES:
            raise ServiceProfileVerificationError(
                "PROFILE_VERIFICATION_LEDGER_TOO_LARGE", "Verification registry exceeds its size limit"
            )
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ServiceProfileVerificationError(
                "PROFILE_VERIFICATION_LEDGER_INVALID", "Verification registry is not valid JSON"
            ) from error
        if not isinstance(value, dict) or canonical_json_bytes(value) != raw:
            raise ServiceProfileVerificationError(
                "PROFILE_VERIFICATION_LEDGER_INVALID", "Verification registry is not canonical JSON"
            )
        if value.get("schema") != "study.profile-verification.ledger" or value.get("schemaVersion") != 1:
            raise ServiceProfileVerificationError(
                "PROFILE_VERIFICATION_LEDGER_INVALID", "Verification registry schema is invalid"
            )
        tag = value.get("authTag")
        unsigned = dict(value)
        unsigned.pop("authTag", None)
        if value.get("authKeyId") != self._key_id or not isinstance(tag, str):
            raise ServiceProfileVerificationError(
                "PROFILE_VERIFICATION_LEDGER_CORRUPT", "Verification registry authentication is unavailable"
            )
        if not hmac.compare_digest(tag, self._mac("study.profile-verification.ledger.v1", unsigned)):
            raise ServiceProfileVerificationError(
                "PROFILE_VERIFICATION_LEDGER_CORRUPT", "Verification registry authentication failed"
            )
        sequence = value.get("sequence")
        records = value.get("records")
        idempotency = value.get("idempotency")
        if (
            isinstance(sequence, bool)
            or not isinstance(sequence, int)
            or sequence < 0
            or sequence > MAX_SAFE_INTEGER
            or not isinstance(records, list)
            or len(records) > MAX_RECORDS
            or not isinstance(idempotency, dict)
        ):
            raise ServiceProfileVerificationError(
                "PROFILE_VERIFICATION_LEDGER_INVALID", "Verification registry structure is invalid"
            )
        return value

    def _read_path(self, path: Path) -> dict[str, Any]:
        info = path.lstat()
        attributes = getattr(info, "st_file_attributes", 0)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or attributes & 0x400
            or info.st_nlink != 1
        ):
            raise ServiceProfileVerificationError(
                "PROFILE_VERIFICATION_STORAGE_UNSAFE", "Verification registry is not a private regular file"
            )
        raw = path.read_bytes()
        after = path.lstat()
        if (
            len(raw) != info.st_size
            or (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        ):
            raise ServiceProfileVerificationError(
                "PROFILE_VERIFICATION_LEDGER_CHANGED", "Verification registry changed while being read"
            )
        return self._decode(raw)

    def _load(self) -> dict[str, Any]:
        if not self._path.is_file():
            if self._backup_path.is_file():
                raise ServiceProfileVerificationError(
                    "PROFILE_VERIFICATION_LEDGER_RECOVERY_REQUIRED",
                    "Current verification registry is missing; the backup is audit-only until revalidated",
                )
            return self._empty()
        try:
            return self._read_path(self._path)
        except ServiceProfileVerificationError as error:
            if self._backup_path.is_file():
                raise ServiceProfileVerificationError(
                    "PROFILE_VERIFICATION_LEDGER_RECOVERY_REQUIRED",
                    "Current verification registry failed authentication; old success cannot be restored",
                ) from error
            raise error

    def _write(self, value: Mapping[str, Any]) -> None:
        authenticated = self._authenticate(value)
        raw = canonical_json_bytes(authenticated)
        if len(raw) > MAX_LEDGER_BYTES:
            raise ServiceProfileVerificationError(
                "PROFILE_VERIFICATION_LEDGER_TOO_LARGE", "Verification registry exceeds its size limit"
            )
        previous = self._path.read_bytes() if self._path.is_file() else None
        backup_temp = _temporary_file(self._backup_path, previous) if previous is not None else None
        current_temp = _temporary_file(self._path, raw)
        try:
            if backup_temp is not None:
                os.replace(backup_temp, self._backup_path)
            os.replace(current_temp, self._path)
        finally:
            for temporary in (backup_temp, current_temp):
                if temporary is not None:
                    try:
                        temporary.unlink()
                    except FileNotFoundError:
                        pass

    def _resolve_binding(self, capability: str, profile_ref: str) -> dict[str, Any] | None:
        if capability not in CAPABILITIES:
            raise ServiceProfileVerificationError(
                "PROFILE_VERIFICATION_SCHEMA_INVALID", "capability is unsupported"
            )
        profile_ref = _require_id(profile_ref, "profileRef", PROFILE_REF_PATTERN)
        raw = self._binding_resolver(capability, profile_ref)
        if raw is None:
            return None
        if not isinstance(raw, Mapping):
            raise ServiceProfileVerificationError(
                "PROFILE_BINDING_INVALID", "Trusted profile binding resolver returned an invalid value"
            )
        expected = {
            "capability", "profileRef", "configurationFingerprint", "credentialRevision",
            "credentialState", "secretRequired", "secretExists",
        }
        if set(raw) != expected or raw.get("capability") != capability or raw.get("profileRef") != profile_ref:
            raise ServiceProfileVerificationError(
                "PROFILE_BINDING_INVALID", "Trusted profile binding does not match the requested profile"
            )
        fingerprint = _require_fingerprint(raw.get("configurationFingerprint"))
        revision = _require_revision(raw.get("credentialRevision"))
        credential_state = raw.get("credentialState")
        if credential_state not in {"committed", "uncertain", "missing"}:
            raise ServiceProfileVerificationError(
                "PROFILE_BINDING_INVALID", "Trusted profile credential state is invalid"
            )
        if not isinstance(raw.get("secretRequired"), bool) or not isinstance(raw.get("secretExists"), bool):
            raise ServiceProfileVerificationError(
                "PROFILE_BINDING_INVALID", "Trusted profile secret state is invalid"
            )
        return {
            "capability": capability,
            "profileRef": profile_ref,
            "configurationFingerprint": fingerprint,
            "credentialRevision": revision,
            "credentialState": credential_state,
            "secretRequired": raw["secretRequired"],
            "secretExists": raw["secretExists"],
        }

    def _operation_digest(self, operation_id: str) -> str:
        operation_id = _require_id(operation_id, "operationId")
        return hmac.new(
            self._authentication_key,
            b"study.profile-verification.operation.v1\x00" + operation_id.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def _record_payload(
        *,
        capability: str,
        profile_ref: str,
        configuration_fingerprint: str,
        credential_revision: int,
        status: str,
        error_code: str | None,
        retryable: bool | None,
        latency_ms: int | None,
    ) -> dict[str, Any]:
        return {
            "capability": capability,
            "profileRef": profile_ref,
            "configurationFingerprint": configuration_fingerprint,
            "credentialRevision": credential_revision,
            "status": status,
            "errorCode": error_code,
            "retryable": retryable,
            "latencyMs": latency_ms,
        }

    def record_result(
        self,
        *,
        operation_id: str,
        capability: str,
        profile_ref: str,
        configuration_fingerprint: str,
        credential_revision: int,
        status: str,
        error_code: str | None = None,
        retryable: bool | None = None,
        latency_ms: int | None = None,
    ) -> dict[str, Any]:
        if capability not in CAPABILITIES:
            raise ServiceProfileVerificationError(
                "PROFILE_VERIFICATION_SCHEMA_INVALID", "capability is unsupported"
            )
        profile_ref = _require_id(profile_ref, "profileRef", PROFILE_REF_PATTERN)
        configuration_fingerprint = _require_fingerprint(configuration_fingerprint)
        credential_revision = _require_revision(credential_revision)
        if status not in RESULT_STATUSES:
            raise ServiceProfileVerificationError(
                "PROFILE_VERIFICATION_SCHEMA_INVALID", "verification status is invalid"
            )
        if status == "passed":
            if error_code is not None or retryable is not None:
                raise ServiceProfileVerificationError(
                    "PROFILE_VERIFICATION_SCHEMA_INVALID", "passed verification cannot contain an error"
                )
        else:
            error_code = _require_id(error_code, "errorCode")
            if not isinstance(retryable, bool):
                raise ServiceProfileVerificationError(
                    "PROFILE_VERIFICATION_SCHEMA_INVALID", "failed verification must declare retryability"
                )
        if latency_ms is not None and (
            isinstance(latency_ms, bool) or not isinstance(latency_ms, int) or not 0 <= latency_ms <= 600_000
        ):
            raise ServiceProfileVerificationError(
                "PROFILE_VERIFICATION_SCHEMA_INVALID", "latencyMs is invalid"
            )
        payload = self._record_payload(
            capability=capability,
            profile_ref=profile_ref,
            configuration_fingerprint=configuration_fingerprint,
            credential_revision=credential_revision,
            status=status,
            error_code=error_code,
            retryable=retryable,
            latency_ms=latency_ms,
        )
        payload_digest = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        operation_digest = self._operation_digest(operation_id)
        with self._transaction():
            ledger = self._load()
            existing = ledger["idempotency"].get(operation_digest)
            if existing is not None:
                if existing.get("payloadDigest") != payload_digest:
                    raise ServiceProfileVerificationError(
                        "PROFILE_VERIFICATION_IDEMPOTENCY_CONFLICT",
                        "operationId was already used for another verification result",
                    )
                record_id = existing.get("recordId")
                for record in ledger["records"]:
                    if record.get("recordId") == record_id:
                        return self._public_record(record)
                raise ServiceProfileVerificationError(
                    "PROFILE_VERIFICATION_LEDGER_INVALID", "Idempotency record target is missing"
                )
            if len(ledger["records"]) >= MAX_RECORDS:
                raise ServiceProfileVerificationError(
                    "PROFILE_VERIFICATION_LEDGER_FULL", "Verification registry reached its record limit"
                )
            current = self._resolve_binding(capability, profile_ref)
            binding_current = bool(
                current
                and current["configurationFingerprint"] == configuration_fingerprint
                and current["credentialRevision"] == credential_revision
            )
            sequence = int(ledger["sequence"]) + 1
            now_ms = int(self._clock() * 1000)
            record_id = "verification_" + hmac.new(
                self._authentication_key,
                b"study.profile-verification.record.v1\x00" + sequence.to_bytes(8, "big")
                + canonical_json_bytes(payload),
                hashlib.sha256,
            ).hexdigest()[:48]
            record = {
                "schema": "study.profile-verification.record",
                "schemaVersion": 1,
                "recordId": record_id,
                "sequence": sequence,
                **payload,
                "publishState": "current" if binding_current else "stale_at_publish",
                "checkedAt": now_ms,
            }
            updated = {
                **{key: item for key, item in ledger.items() if key not in {"authKeyId", "authTag"}},
                "sequence": sequence,
                "records": [*ledger["records"], record],
                "idempotency": {
                    **ledger["idempotency"],
                    operation_digest: {"payloadDigest": payload_digest, "recordId": record_id},
                },
                "updatedAt": now_ms,
            }
            self._write(updated)
            return self._public_record(record)

    @staticmethod
    def _public_record(record: Mapping[str, Any]) -> dict[str, Any]:
        return {
            key: record[key]
            for key in (
                "recordId", "sequence", "capability", "profileRef", "configurationFingerprint",
                "credentialRevision", "status", "errorCode", "retryable", "latencyMs",
                "publishState", "checkedAt",
            )
        }

    def profile_snapshot(self, capability: str, profile_ref: str) -> dict[str, Any]:
        with self._transaction():
            current = self._resolve_binding(capability, profile_ref)
            ledger = self._load()
            records = [
                record
                for record in ledger["records"]
                if record.get("capability") == capability and record.get("profileRef") == profile_ref
            ]
            if current is None:
                return {
                    "capability": capability,
                    "profileRef": profile_ref,
                    "state": "unknown",
                    "latestVerification": None,
                    "reasonCode": "PROFILE_NOT_CONFIGURED",
                }
            exact = [
                record
                for record in records
                if record.get("configurationFingerprint") == current["configurationFingerprint"]
                and record.get("credentialRevision") == current["credentialRevision"]
                and record.get("publishState") == "current"
            ]
            latest = max(exact, key=lambda item: int(item["sequence"])) if exact else None
            if current["credentialState"] != "committed":
                state, reason = "blocked", "CREDENTIAL_STATE_UNCERTAIN"
            elif current["secretRequired"] and not current["secretExists"]:
                state, reason = "action_required", "CREDENTIAL_REQUIRED"
            elif latest is None:
                state = "stale" if records else "unknown"
                reason = "VERIFICATION_BINDING_CHANGED" if records else "VERIFICATION_REQUIRED"
            elif latest["status"] == "failed":
                state = "action_required" if latest["retryable"] else "blocked"
                reason = latest["errorCode"]
            elif int(self._clock() * 1000) - int(latest["checkedAt"]) > self._max_age_ms:
                state, reason = "stale", "VERIFICATION_EXPIRED"
            else:
                state, reason = "ready", None
            return {
                **current,
                "state": state,
                "latestVerification": self._public_record(latest) if latest is not None else None,
                "reasonCode": reason,
            }

    def system_snapshot(self, profiles: Sequence[tuple[str, str]]) -> dict[str, Any]:
        if not isinstance(profiles, Sequence) or isinstance(profiles, (str, bytes)):
            raise ServiceProfileVerificationError(
                "PROFILE_VERIFICATION_SCHEMA_INVALID", "profiles must be a sequence"
            )
        normalized: list[tuple[str, str]] = []
        for capability, profile_ref in profiles:
            if capability not in CAPABILITIES:
                raise ServiceProfileVerificationError(
                    "PROFILE_VERIFICATION_SCHEMA_INVALID", "capability is unsupported"
                )
            normalized.append((capability, _require_id(profile_ref, "profileRef", PROFILE_REF_PATTERN)))
        if len(normalized) != len(set(normalized)):
            raise ServiceProfileVerificationError(
                "PROFILE_VERIFICATION_SCHEMA_INVALID", "profiles contain a duplicate"
            )
        snapshots = [self.profile_snapshot(capability, profile_ref) for capability, profile_ref in normalized]
        aggregates: dict[str, dict[str, int]] = {}
        for capability in sorted(CAPABILITIES):
            relevant = [item for item in snapshots if item["capability"] == capability]
            aggregates[capability] = {
                "total": len(relevant),
                "ready": sum(item["state"] == "ready" for item in relevant),
                "notReady": sum(item["state"] != "ready" for item in relevant),
            }
        return {"serviceProfiles": snapshots, "serviceAggregates": aggregates}
