"""Authenticated, audience-bound, single-use approval for persistent Anki writes."""

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
from typing import Any, Callable, Iterator, Mapping

from .artifact_registry import (
    ArtifactAudienceBinding,
    ArtifactRegistryError,
    canonical_json_bytes,
    validate_persistable_json,
)


MAX_RECORD_BYTES = 1024 * 1024
MAX_INTENT_LIFETIME = timedelta(minutes=30)
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class AnkiImportApprovalError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise AnkiImportApprovalError(
            "IMPORT_APPROVAL_RECORD_INVALID", "Import approval timestamp is invalid"
        )
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise AnkiImportApprovalError(
            "IMPORT_APPROVAL_RECORD_INVALID", "Import approval timestamp is invalid"
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise AnkiImportApprovalError(
            "IMPORT_APPROVAL_RECORD_INVALID", "Import approval timestamp is invalid"
        )
    return parsed.astimezone(timezone.utc)


def _identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise AnkiImportApprovalError(
            "IMPORT_APPROVAL_REQUEST_INVALID", f"{label} is invalid"
        )
    return value


def _digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise AnkiImportApprovalError(
            "IMPORT_APPROVAL_REQUEST_INVALID", f"{label} is invalid"
        )
    return value


def _directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    info = path.lstat()
    attributes = getattr(info, "st_file_attributes", 0)
    if (
        not stat.S_ISDIR(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or attributes & 0x400
    ):
        raise AnkiImportApprovalError(
            "IMPORT_APPROVAL_STORAGE_UNSAFE",
            "Import approval storage contains a link or reparse directory",
        )
    return path


def _temporary(path: Path, data: bytes) -> Path:
    temporary = path.parent / f".{path.name}.{secrets.token_hex(12)}.partial"
    with temporary.open("xb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())
    return temporary


class AnkiImportApprovalLedger:
    """Persist and atomically consume ImportApproval without exposing a bearer."""

    def __init__(
        self,
        root: Path,
        *,
        authentication_key: bytes,
        service_instance_id: str,
        gesture_attestation_verifier: (
            Callable[[str, str, str, str], bool] | None
        ) = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(authentication_key, bytes) or len(authentication_key) < 32:
            raise AnkiImportApprovalError(
                "IMPORT_APPROVAL_KEY_INVALID",
                "Import approval authentication key must contain at least 256 bits",
            )
        self._authentication_key = bytes(authentication_key)
        self._service_instance_id = _identifier(
            service_instance_id, "serviceInstanceId"
        )
        self._gesture_attestation_verifier = gesture_attestation_verifier
        self._clock = clock or _utc_now
        self._root = _directory(Path(root).absolute())
        self._intents_root = _directory(self._root / "intents")
        self._lock_path = self._root / "import-approval-ledger.lock"
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
            raise AnkiImportApprovalError(
                "IMPORT_APPROVAL_CLOCK_INVALID",
                "Import approval clock must return an aware datetime",
            )
        return value.astimezone(timezone.utc)

    def _audience_digest(self, audience: ArtifactAudienceBinding) -> str:
        if not isinstance(audience, ArtifactAudienceBinding):
            raise AnkiImportApprovalError(
                "IMPORT_APPROVAL_AUDIENCE_INVALID", "Import audience is invalid"
            )
        return _sha(canonical_json_bytes(audience.audience(self._service_instance_id)))

    def audience_digest(self, audience: ArtifactAudienceBinding) -> str:
        return self._audience_digest(audience)

    def _ensure_parent(self, path: Path) -> None:
        absolute = path.absolute()
        try:
            relative = absolute.relative_to(self._root)
        except ValueError as error:
            raise AnkiImportApprovalError(
                "IMPORT_APPROVAL_STORAGE_UNSAFE",
                "Import approval path escapes its root",
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
                raise AnkiImportApprovalError(
                    "IMPORT_APPROVAL_STORAGE_UNSAFE",
                    "Import approval lock is not a private regular file",
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

    def _mac(self, value: Mapping[str, Any]) -> str:
        return hmac.new(
            self._authentication_key,
            b"study.anki.import-approval-record.v1\x00"
            + canonical_json_bytes(dict(value)),
            hashlib.sha256,
        ).hexdigest()

    def _authenticate(self, value: Mapping[str, Any]) -> dict[str, Any]:
        unsigned = {**dict(value), "authKeyId": "study-anki-import-approval-v1"}
        return {**unsigned, "authTag": self._mac(unsigned)}

    def _intent_path(self, import_intent_id: str) -> Path:
        identity = _sha(_identifier(import_intent_id, "importIntentId").encode())
        return self._intents_root / identity[:2] / f"{identity}.json"

    def _safe_read(self, path: Path) -> bytes:
        self._ensure_parent(path.parent)
        try:
            before = path.lstat()
        except FileNotFoundError as error:
            raise AnkiImportApprovalError(
                "IMPORT_INTENT_NOT_FOUND", "Import intent was not found"
            ) from error
        attributes = getattr(before, "st_file_attributes", 0)
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_ISLNK(before.st_mode)
            or attributes & 0x400
            or before.st_nlink != 1
            or before.st_size > MAX_RECORD_BYTES
        ):
            raise AnkiImportApprovalError(
                "IMPORT_APPROVAL_STORAGE_UNSAFE", "Import intent record is unsafe"
            )
        raw = path.read_bytes()
        after = path.lstat()
        if len(raw) != before.st_size or (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise AnkiImportApprovalError(
                "IMPORT_APPROVAL_RECORD_CHANGED",
                "Import intent record changed while being read",
            )
        return raw

    def _decode(self, raw: bytes) -> dict[str, Any]:
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise AnkiImportApprovalError(
                "IMPORT_APPROVAL_RECORD_INVALID", "Import intent record is invalid"
            ) from error
        if not isinstance(value, dict) or canonical_json_bytes(value) != raw:
            raise AnkiImportApprovalError(
                "IMPORT_APPROVAL_RECORD_INVALID",
                "Import intent record is not canonical JSON",
            )
        tag = value.get("authTag")
        unsigned = dict(value)
        unsigned.pop("authTag", None)
        if (
            value.get("schema") != "study.anki.import-approval-record"
            or value.get("schemaVersion") != 1
            or value.get("authKeyId") != "study-anki-import-approval-v1"
            or not isinstance(tag, str)
            or not hmac.compare_digest(tag, self._mac(unsigned))
        ):
            raise AnkiImportApprovalError(
                "IMPORT_APPROVAL_RECORD_CORRUPT",
                "Import intent authentication failed",
            )
        return value

    def _load(self, import_intent_id: str) -> tuple[dict[str, Any], bytes]:
        raw = self._safe_read(self._intent_path(import_intent_id))
        return self._decode(raw), raw

    def _publish(self, path: Path, raw: bytes) -> None:
        if len(raw) > MAX_RECORD_BYTES:
            raise AnkiImportApprovalError(
                "IMPORT_APPROVAL_RECORD_TOO_LARGE", "Import intent record is too large"
            )
        self._ensure_parent(path.parent)
        temporary = _temporary(path, raw)
        try:
            try:
                os.link(temporary, path)
            except FileExistsError as error:
                raise AnkiImportApprovalError(
                    "IMPORT_INTENT_ALREADY_EXISTS", "Import intent already exists"
                ) from error
        finally:
            temporary.unlink(missing_ok=True)

    def _replace(self, path: Path, raw: bytes, previous_raw: bytes) -> None:
        if len(raw) > MAX_RECORD_BYTES:
            raise AnkiImportApprovalError(
                "IMPORT_APPROVAL_RECORD_TOO_LARGE", "Import intent record is too large"
            )
        self._ensure_parent(path.parent)
        backup = path.with_suffix(".json.bak")
        backup_temp = _temporary(backup, previous_raw)
        current_temp = _temporary(path, raw)
        try:
            os.replace(backup_temp, backup)
            os.replace(current_temp, path)
        finally:
            backup_temp.unlink(missing_ok=True)
            current_temp.unlink(missing_ok=True)

    def _intent_id(self, audience_digest: str, plan_digest: str) -> str:
        return (
            "anki_intent_"
            + hmac.new(
                self._authentication_key,
                b"study.anki.import-intent-id.v1\x00"
                + audience_digest.encode("ascii")
                + b"\x00"
                + plan_digest.encode("ascii"),
                hashlib.sha256,
            ).hexdigest()[:48]
        )

    @staticmethod
    def _public(record: Mapping[str, Any], now: datetime) -> dict[str, Any]:
        state = "pending"
        approval = record.get("approval")
        if isinstance(approval, Mapping):
            state = str(approval.get("state") or "pending")
        if now >= _parse_timestamp(record["intent"]["expiresAt"]) and state in {
            "pending",
            "approved",
        }:
            state = "expired"
        return {
            "schemaVersion": 1,
            "importIntentId": record["intent"]["importIntentId"],
            "approvalState": state,
            "expiresAt": record["intent"]["expiresAt"],
        }

    def create_intent(
        self,
        *,
        audience: ArtifactAudienceBinding,
        project_id: str,
        project_revision: int,
        import_plan_ref: Mapping[str, Any],
        import_plan_digest: str,
        target_digest: str,
        apkg_sha256: str,
    ) -> dict[str, Any]:
        project_id = _identifier(project_id, "projectId")
        if (
            isinstance(project_revision, bool)
            or not isinstance(project_revision, int)
            or project_revision < 1
        ):
            raise AnkiImportApprovalError(
                "IMPORT_APPROVAL_REQUEST_INVALID", "projectRevision is invalid"
            )
        plan_digest = _digest(import_plan_digest, "importPlanDigest")
        target_digest = _digest(target_digest, "targetDigest")
        apkg_sha256 = _digest(apkg_sha256, "apkgSha256")
        audience_digest = self._audience_digest(audience)
        intent_id = self._intent_id(audience_digest, plan_digest)
        try:
            ref = json.loads(json.dumps(dict(import_plan_ref), allow_nan=False))
            validate_persistable_json(ref)
        except (TypeError, ValueError, ArtifactRegistryError) as error:
            raise AnkiImportApprovalError(
                "IMPORT_APPROVAL_REQUEST_INVALID", "ImportPlan reference is invalid"
            ) from error
        now = self._now()
        expires_at = now + MAX_INTENT_LIFETIME
        creation = {
            "projectId": project_id,
            "projectRevision": project_revision,
            "importPlanRef": ref,
            "importPlanDigest": plan_digest,
            "targetDigest": target_digest,
            "apkgSha256": apkg_sha256,
        }
        creation_digest = _sha(canonical_json_bytes(creation))
        record = self._authenticate(
            {
                "schema": "study.anki.import-approval-record",
                "schemaVersion": 1,
                "audienceDigest": audience_digest,
                "creationDigest": creation_digest,
                "intent": {
                    "importIntentId": intent_id,
                    **creation,
                    "expiresAt": _timestamp(expires_at),
                },
                "approval": None,
                "consumption": None,
                "createdAt": _timestamp(now),
                "updatedAt": _timestamp(now),
            }
        )
        raw = canonical_json_bytes(record)
        path = self._intent_path(intent_id)
        with self._transaction():
            try:
                self._publish(path, raw)
                return self._public(record, now)
            except AnkiImportApprovalError as error:
                if error.code != "IMPORT_INTENT_ALREADY_EXISTS":
                    raise
                existing, _ = self._load(intent_id)
                if existing.get("audienceDigest") != audience_digest:
                    raise AnkiImportApprovalError(
                        "IMPORT_APPROVAL_AUDIENCE_MISMATCH",
                        "Import intent belongs to another trusted audience",
                    ) from error
                if existing.get("creationDigest") != creation_digest:
                    raise AnkiImportApprovalError(
                        "IMPORT_INTENT_CONFLICT",
                        "Import intent identity conflicts with another plan",
                    ) from error
                return self._public(existing, now)

    def get_intent(
        self, *, audience: ArtifactAudienceBinding, import_intent_id: str
    ) -> dict[str, Any]:
        now = self._now()
        with self._transaction():
            record, _ = self._load(import_intent_id)
            if record.get("audienceDigest") != self._audience_digest(audience):
                raise AnkiImportApprovalError(
                    "IMPORT_APPROVAL_AUDIENCE_MISMATCH",
                    "Import intent belongs to another trusted audience",
                )
            return self._public(record, now)

    def get_binding(
        self, *, audience: ArtifactAudienceBinding, import_intent_id: str
    ) -> dict[str, Any]:
        with self._transaction():
            record, _ = self._load(import_intent_id)
            if record.get("audienceDigest") != self._audience_digest(audience):
                raise AnkiImportApprovalError(
                    "IMPORT_APPROVAL_AUDIENCE_MISMATCH",
                    "Import intent belongs to another trusted audience",
                )
            return json.loads(json.dumps(record["intent"], ensure_ascii=False))

    def record_decision(
        self,
        *,
        audience: ArtifactAudienceBinding,
        import_intent_id: str,
        decision: str,
        gesture_attestation_ref: str,
    ) -> dict[str, Any]:
        if decision not in {"approved", "declined"}:
            raise AnkiImportApprovalError(
                "IMPORT_APPROVAL_DECISION_INVALID", "Import decision is invalid"
            )
        if not isinstance(gesture_attestation_ref, str) or not gesture_attestation_ref:
            raise AnkiImportApprovalError(
                "TRUSTED_GESTURE_INVALID", "Trusted gesture is unavailable"
            )
        now = self._now()
        audience_digest = self._audience_digest(audience)
        with self._transaction():
            record, previous = self._load(import_intent_id)
            if record.get("audienceDigest") != audience_digest:
                raise AnkiImportApprovalError(
                    "IMPORT_APPROVAL_AUDIENCE_MISMATCH",
                    "Import intent belongs to another trusted audience",
                )
            existing = record.get("approval")
            gesture_digest = _sha(gesture_attestation_ref.encode("utf-8"))
            if isinstance(existing, Mapping):
                if (
                    existing.get("state") == decision
                    and existing.get("userGestureRef") == gesture_digest
                ):
                    return self._public(record, now)
                raise AnkiImportApprovalError(
                    "IMPORT_APPROVAL_TERMINAL",
                    "Import intent already has a terminal decision",
                )
            if now >= _parse_timestamp(record["intent"]["expiresAt"]):
                raise AnkiImportApprovalError(
                    "IMPORT_INTENT_EXPIRED", "Import intent has expired"
                )
            if self._gesture_attestation_verifier is None:
                raise AnkiImportApprovalError(
                    "TRUSTED_GESTURE_VERIFIER_UNAVAILABLE",
                    "Trusted gesture verification is unavailable",
                )
            try:
                verified = self._gesture_attestation_verifier(
                    gesture_attestation_ref,
                    audience_digest,
                    import_intent_id,
                    f"decide:{decision}",
                )
            except Exception as error:
                raise AnkiImportApprovalError(
                    "TRUSTED_GESTURE_INVALID",
                    "Trusted import gesture could not be verified",
                ) from error
            if verified is not True:
                raise AnkiImportApprovalError(
                    "TRUSTED_GESTURE_INVALID", "Trusted import gesture is invalid"
                )
            unsigned = dict(record)
            unsigned.pop("authKeyId", None)
            unsigned.pop("authTag", None)
            timestamp = _timestamp(now)
            unsigned["approval"] = {
                "importIntentId": import_intent_id,
                "audienceDigest": audience_digest,
                "importPlanDigest": record["intent"]["importPlanDigest"],
                "userGestureRef": gesture_digest,
                "state": decision,
                ("approvedAt" if decision == "approved" else "declinedAt"): timestamp,
            }
            unsigned["updatedAt"] = timestamp
            updated = self._authenticate(unsigned)
            self._replace(
                self._intent_path(import_intent_id),
                canonical_json_bytes(updated),
                previous,
            )
            return self._public(updated, now)

    def consume(
        self,
        *,
        audience: ArtifactAudienceBinding,
        import_intent_id: str,
        execution_id: str,
        expected_import_plan_digest: str,
        current_target_digest: str,
    ) -> dict[str, Any]:
        execution_id = _identifier(execution_id, "executionId")
        plan_digest = _digest(expected_import_plan_digest, "importPlanDigest")
        target_digest = _digest(current_target_digest, "targetDigest")
        audience_digest = self._audience_digest(audience)
        consumption_digest = _sha(
            canonical_json_bytes(
                {
                    "executionIdDigest": _sha(execution_id.encode("utf-8")),
                    "importPlanDigest": plan_digest,
                    "targetDigest": target_digest,
                }
            )
        )
        now = self._now()
        with self._transaction():
            record, previous = self._load(import_intent_id)
            if record.get("audienceDigest") != audience_digest:
                raise AnkiImportApprovalError(
                    "IMPORT_APPROVAL_AUDIENCE_MISMATCH",
                    "Import intent belongs to another trusted audience",
                )
            prior = record.get("consumption")
            if isinstance(prior, Mapping):
                if prior.get("consumptionDigest") == consumption_digest:
                    return json.loads(json.dumps(prior["result"], ensure_ascii=False))
                raise AnkiImportApprovalError(
                    "IMPORT_APPROVAL_CONSUMED",
                    "Import approval was already consumed by another execution",
                )
            intent = record["intent"]
            if intent["importPlanDigest"] != plan_digest:
                raise AnkiImportApprovalError(
                    "IMPORT_PLAN_STALE", "ImportPlan digest changed before execution"
                )
            if intent["targetDigest"] != target_digest:
                raise AnkiImportApprovalError(
                    "ANKI_TARGET_CHANGED", "Anki target changed after confirmation"
                )
            approval = record.get("approval")
            if not isinstance(approval, Mapping) or approval.get("state") != "approved":
                raise AnkiImportApprovalError(
                    "IMPORT_APPROVAL_REQUIRED",
                    "Import intent has no approved trusted decision",
                )
            if now >= _parse_timestamp(intent["expiresAt"]):
                raise AnkiImportApprovalError(
                    "IMPORT_INTENT_EXPIRED", "Import intent has expired"
                )
            result = {
                "importIntentId": import_intent_id,
                "executionId": execution_id,
                "projectId": intent["projectId"],
                "projectRevision": intent["projectRevision"],
                "importPlanRef": intent["importPlanRef"],
                "importPlanDigest": intent["importPlanDigest"],
                "targetDigest": intent["targetDigest"],
                "apkgSha256": intent["apkgSha256"],
                "consumedAt": _timestamp(now),
            }
            unsigned = dict(record)
            unsigned.pop("authKeyId", None)
            unsigned.pop("authTag", None)
            unsigned["approval"] = {
                **dict(approval),
                "state": "consumed",
                "consumedAt": result["consumedAt"],
            }
            unsigned["consumption"] = {
                "consumptionDigest": consumption_digest,
                "result": result,
            }
            unsigned["updatedAt"] = result["consumedAt"]
            updated = self._authenticate(unsigned)
            self._replace(
                self._intent_path(import_intent_id),
                canonical_json_bytes(updated),
                previous,
            )
            return json.loads(json.dumps(result, ensure_ascii=False))


__all__ = [
    "AnkiImportApprovalError",
    "AnkiImportApprovalLedger",
    "MAX_INTENT_LIFETIME",
]
