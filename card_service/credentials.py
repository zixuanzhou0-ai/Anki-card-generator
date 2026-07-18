from __future__ import annotations

import ctypes
import hashlib
import hmac
import json
import os
import re
import secrets
import stat
import threading
import time
from ctypes import wintypes
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Protocol

from .artifact_registry import canonical_json_bytes
from .storage import AtomicJsonStore


PROFILE_REF_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
MAX_CREDENTIAL_RECORD_BYTES = 64 * 1024
SERVICE_KEY_PURPOSE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


class CredentialStoreError(RuntimeError):
    pass


class CredentialBackend(Protocol):
    def write(self, target: str, secret: str) -> None: ...
    def read(self, target: str) -> str | None: ...
    def delete(self, target: str) -> None: ...
    def exists(self, target: str) -> bool: ...


class InMemoryCredentialBackend:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def write(self, target: str, secret: str) -> None:
        self.values[target] = secret

    def read(self, target: str) -> str | None:
        return self.values.get(target)

    def delete(self, target: str) -> None:
        self.values.pop(target, None)

    def exists(self, target: str) -> bool:
        return target in self.values


class _FileTime(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]


class _Credential(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR), ("LastWritten", _FileTime),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p), ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


class WindowsCredentialBackend:
    CREDENTIAL_TYPE_GENERIC = 1
    CREDENTIAL_PERSIST_LOCAL_MACHINE = 2
    ERROR_NOT_FOUND = 1168

    def __init__(self) -> None:
        if os.name != "nt":
            raise CredentialStoreError("Windows Credential Manager is only available on Windows")
        self.api = ctypes.WinDLL("Advapi32", use_last_error=True)
        self.api.CredWriteW.argtypes = [ctypes.POINTER(_Credential), wintypes.DWORD]
        self.api.CredWriteW.restype = wintypes.BOOL
        self.api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(_Credential))]
        self.api.CredReadW.restype = wintypes.BOOL
        self.api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        self.api.CredDeleteW.restype = wintypes.BOOL
        self.api.CredFree.argtypes = [ctypes.c_void_p]

    def write(self, target: str, secret: str) -> None:
        encoded = secret.encode("utf-16-le")
        if not encoded or len(encoded) > 2_560:
            raise CredentialStoreError("Credential must contain 1 to 1280 UTF-16 code units")
        blob = (ctypes.c_ubyte * len(encoded)).from_buffer_copy(encoded)
        credential = _Credential(Type=self.CREDENTIAL_TYPE_GENERIC, TargetName=target)
        credential.CredentialBlobSize = len(encoded)
        credential.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte))
        credential.Persist = self.CREDENTIAL_PERSIST_LOCAL_MACHINE
        credential.UserName = "Codex Study local profile"
        try:
            if not self.api.CredWriteW(ctypes.byref(credential), 0):
                raise CredentialStoreError(f"CredWriteW failed: {ctypes.get_last_error()}")
        finally:
            ctypes.memset(blob, 0, len(encoded))

    def read(self, target: str) -> str | None:
        pointer = ctypes.POINTER(_Credential)()
        if not self.api.CredReadW(target, self.CREDENTIAL_TYPE_GENERIC, 0, ctypes.byref(pointer)):
            error = ctypes.get_last_error()
            if error == self.ERROR_NOT_FOUND:
                return None
            raise CredentialStoreError(f"CredReadW failed: {error}")
        try:
            item = pointer.contents
            return ctypes.string_at(item.CredentialBlob, item.CredentialBlobSize).decode("utf-16-le")
        finally:
            self.api.CredFree(pointer)

    def delete(self, target: str) -> None:
        if self.api.CredDeleteW(target, self.CREDENTIAL_TYPE_GENERIC, 0):
            return
        error = ctypes.get_last_error()
        if error != self.ERROR_NOT_FOUND:
            raise CredentialStoreError(f"CredDeleteW failed: {error}")

    def exists(self, target: str) -> bool:
        return self.read(target) is not None


class CredentialStore:
    """Authenticated OS-credential facade with monotonic, crash-safe revisions.

    Secret material never enters the metadata files.  Those files contain an
    opaque SecretRef and keyed material digests so recovery can distinguish the
    intended secret, the previous secret and an ambiguous external mutation.
    """

    RECORD_SCHEMA = "study.credential.record"
    RECORD_VERSION = 2
    AUTH_KEY_ID = "study-credential-metadata-v1"

    def __init__(
        self,
        *,
        state_dir: str | Path,
        backend: CredentialBackend | None = None,
        target_prefix: str = "CodexStudy",
    ) -> None:
        root = Path(state_dir).expanduser()
        if not root.is_absolute():
            raise CredentialStoreError("Credential metadata directory must be absolute")
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.backend = backend or WindowsCredentialBackend()
        self.target_prefix = target_prefix.rstrip("/")
        if not self.target_prefix:
            raise CredentialStoreError("Credential target prefix cannot be empty")
        self._lock = threading.RLock()
        self._lock_path = self.root / "credential-store.lock"
        try:
            with self._lock_path.open("xb") as output:
                output.write(b"\x00")
                output.flush()
                os.fsync(output.fileno())
        except FileExistsError:
            pass
        self._authentication_key: bytes | None = None
        with self._transaction():
            self._authentication_key = self._load_authentication_key(create=False)
        self._reconcile_pending_updates()

    @staticmethod
    def _validate(profile_ref: str) -> str:
        if not PROFILE_REF_PATTERN.fullmatch(profile_ref):
            raise CredentialStoreError("Invalid credential profile reference")
        return profile_ref

    def _target(self, profile_ref: str) -> str:
        return f"{self.target_prefix}/{self._validate(profile_ref)}"

    def _authentication_target(self) -> str:
        return f"{self.target_prefix}/__service_metadata_auth_v1"

    def _path(self, profile_ref: str) -> Path:
        identity = hashlib.sha256(profile_ref.encode("utf-8")).hexdigest()
        return self.root / f"{identity}.json"

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        with self._lock:
            info = self._lock_path.lstat()
            attributes = getattr(info, "st_file_attributes", 0)
            if (
                not stat.S_ISREG(info.st_mode)
                or stat.S_ISLNK(info.st_mode)
                or attributes & 0x400
                or info.st_nlink != 1
            ):
                raise CredentialStoreError("Credential store lock is not a private regular file")
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

    def _load_authentication_key(self, *, create: bool) -> bytes | None:
        target = self._authentication_target()
        encoded = self.backend.read(target)
        if encoded is None:
            if not create:
                return None
            encoded = secrets.token_hex(48)
            self.backend.write(target, encoded)
            confirmed = self.backend.read(target)
            if confirmed is None or not hmac.compare_digest(confirmed, encoded):
                raise CredentialStoreError("Credential metadata authentication key could not be committed")
        if not re.fullmatch(r"[0-9a-f]{96}", encoded):
            raise CredentialStoreError("Credential metadata authentication key is invalid")
        return bytes.fromhex(encoded)

    def _key(self) -> bytes:
        if self._authentication_key is None:
            self._authentication_key = self._load_authentication_key(create=True)

        if self._authentication_key is None:
            raise CredentialStoreError("Credential metadata authentication key is unavailable")
        return self._authentication_key
    def derive_service_key(self, purpose: str, *, context: bytes = b"") -> bytes:
        """Derive a domain-separated internal key without exposing the root key.

        The caller must use a non-secret, stable context. Only the OS-backed root
        key is persisted; derived keys remain in the owning service process.
        """

        if not isinstance(purpose, str) or not SERVICE_KEY_PURPOSE_PATTERN.fullmatch(purpose):
            raise CredentialStoreError("Invalid service key derivation purpose")
        if not isinstance(context, bytes) or len(context) > 1024:
            raise CredentialStoreError("Invalid service key derivation context")
        with self._transaction():
            root_key = self._key()
            return hmac.new(
                root_key,
                b"study.service-key-derivation.v1\x00"
                + purpose.encode("ascii")
                + b"\x00"
                + len(context).to_bytes(2, "big")
                + context,
                hashlib.sha256,
            ).digest()


    def _mac(self, domain: str, value: dict[str, Any]) -> str:
        payload = domain.encode("ascii") + b"\x00" + canonical_json_bytes(value)
        return hmac.new(self._key(), payload, hashlib.sha256).hexdigest()

    def _secret_ref(self, profile_ref: str) -> str:
        digest = hmac.new(
            self._key(),
            b"study.secret-ref.v1\x00" + profile_ref.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"secret_{digest[:48]}"

    def _material_mac(self, secret: str) -> str:
        return hmac.new(
            self._key(),
            b"study.secret-material.v1\x00" + secret.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _authenticate(self, value: dict[str, Any]) -> dict[str, Any]:
        unsigned = {**value, "authKeyId": self.AUTH_KEY_ID}
        return {**unsigned, "authTag": self._mac("study.credential.record.v2", unsigned)}

    def _empty(self, profile_ref: str) -> dict[str, Any]:
        return {
            "schema": self.RECORD_SCHEMA,
            "schemaVersion": self.RECORD_VERSION,
            "profileRef": profile_ref,
            "secretRef": self._secret_ref(profile_ref),
            "credentialRevision": 0,
            "highWaterRevision": 0,
            "exists": False,
            "state": "committed",
            "secretMaterialMac": None,
            "updatedAt": 0,
        }

    def _decode(self, profile_ref: str, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict) or value.get("profileRef") != profile_ref:
            raise CredentialStoreError("Credential metadata is invalid")
        if value.get("schemaVersion") == 1 and "schema" not in value:
            revision = int(value.get("credentialRevision") or 0)
            if revision < 0:
                raise CredentialStoreError("Credential metadata revision is invalid")
            secret = self.backend.read(self._target(profile_ref))
            return {
                **self._empty(profile_ref),
                "credentialRevision": revision,
                "highWaterRevision": revision,
                "exists": secret is not None,
                "state": "legacy_pending" if value.get("state") == "pending" else "committed",
                "secretMaterialMac": self._material_mac(secret) if secret is not None else None,
                "updatedAt": int(value.get("updatedAt") or 0),
            }
        if value.get("schema") != self.RECORD_SCHEMA or value.get("schemaVersion") != self.RECORD_VERSION:
            raise CredentialStoreError("Credential metadata schema is invalid")
        tag = value.get("authTag")
        unsigned = dict(value)
        unsigned.pop("authTag", None)
        if value.get("authKeyId") != self.AUTH_KEY_ID or not isinstance(tag, str):
            raise CredentialStoreError("Credential metadata authentication is unavailable")
        if not hmac.compare_digest(tag, self._mac("study.credential.record.v2", unsigned)):
            raise CredentialStoreError("Credential metadata authentication failed")
        revision = value.get("credentialRevision")
        high_water = value.get("highWaterRevision")
        if (
            isinstance(revision, bool)
            or not isinstance(revision, int)
            or isinstance(high_water, bool)
            or not isinstance(high_water, int)
            or revision < 0
            or high_water < revision
        ):
            raise CredentialStoreError("Credential metadata revision is invalid")
        if value.get("secretRef") != self._secret_ref(profile_ref):
            raise CredentialStoreError("Credential SecretRef binding is invalid")
        if value.get("state") not in {"committed", "pending", "uncertain"}:
            raise CredentialStoreError("Credential metadata state is invalid")
        return dict(value)

    def _read(self, profile_ref: str) -> dict[str, Any]:
        path = self._path(profile_ref)
        try:
            info = path.lstat()
        except FileNotFoundError:
            return self._empty(profile_ref)
        attributes = getattr(info, "st_file_attributes", 0)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or attributes & 0x400
            or info.st_nlink != 1
        ):
            raise CredentialStoreError("Credential metadata is not a private regular file")
        if info.st_size > MAX_CREDENTIAL_RECORD_BYTES:
            raise CredentialStoreError("Credential metadata exceeds its size limit")
        raw = path.read_bytes()
        after = path.lstat()
        if (
            len(raw) != info.st_size
            or (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        ):
            raise CredentialStoreError("Credential metadata changed while being read")
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CredentialStoreError("Credential metadata is invalid JSON") from error
        return self._decode(profile_ref, value)

    def _write(self, profile_ref: str, value: dict[str, Any]) -> dict[str, Any]:
        unsigned = {key: item for key, item in value.items() if key not in {"authKeyId", "authTag"}}
        authenticated = self._authenticate(unsigned)
        AtomicJsonStore._write_atomic(self._path(profile_ref), authenticated)
        return authenticated

    def _same_material(self, secret: str | None, expected_mac: Any) -> bool:
        if secret is None:
            return expected_mac is None
        return isinstance(expected_mac, str) and hmac.compare_digest(self._material_mac(secret), expected_mac)

    def _reconcile_record(self, profile_ref: str, value: dict[str, Any]) -> dict[str, Any]:
        if value.get("state") == "legacy_pending":
            return self._write(profile_ref, {**value, "state": "committed"})
        if value.get("state") != "pending":
            return value
        current = self.backend.read(self._target(profile_ref))
        operation = value.get("pendingOperation")
        intended_matches = (
            operation in {"set", "rollback", "oauth_material_change"}
            and self._same_material(current, value.get("pendingMaterialMac"))
        ) or (operation == "delete" and current is None)
        previous_matches = self._same_material(current, value.get("previousSecretMaterialMac"))
        cleaned = {
            key: item
            for key, item in value.items()
            if key not in {
                "authKeyId", "authTag", "pendingOperation", "pendingMaterialMac",
                "previousCredentialRevision", "previousExists", "previousSecretMaterialMac",
            }
        }
        if intended_matches:
            cleaned.update(
                state="committed",
                exists=current is not None,
                secretMaterialMac=self._material_mac(current) if current is not None else None,
                updatedAt=int(time.time() * 1000),
            )
        elif previous_matches:
            cleaned.update(
                credentialRevision=int(value.get("previousCredentialRevision") or 0),
                state="committed",
                exists=current is not None,
                secretMaterialMac=self._material_mac(current) if current is not None else None,
                updatedAt=int(time.time() * 1000),
            )
        else:
            cleaned.update(
                state="uncertain",
                exists=current is not None,
                secretMaterialMac=self._material_mac(current) if current is not None else None,
                updatedAt=int(time.time() * 1000),
            )
        return self._write(profile_ref, cleaned)

    def _reconcile_pending_updates(self) -> None:
        with self._transaction():
            for path in self.root.glob("*.json"):
                try:
                    info = path.lstat()
                    attributes = getattr(info, "st_file_attributes", 0)
                    if (
                        not stat.S_ISREG(info.st_mode)
                        or stat.S_ISLNK(info.st_mode)
                        or attributes & 0x400
                        or info.st_nlink != 1
                        or info.st_size > MAX_CREDENTIAL_RECORD_BYTES
                    ):
                        continue
                    with path.open("r", encoding="utf-8") as handle:
                        raw = json.load(handle)
                    profile_ref = str(raw.get("profileRef") or "") if isinstance(raw, dict) else ""
                    if not PROFILE_REF_PATTERN.fullmatch(profile_ref):
                        continue
                    value = self._decode(profile_ref, raw)
                    if value.get("state") in {"pending", "legacy_pending"}:
                        self._reconcile_record(profile_ref, value)
                    elif raw.get("schemaVersion") == 1:
                        self._write(profile_ref, value)
                except (OSError, ValueError, CredentialStoreError):
                    continue

    def _observe_current(self, profile_ref: str, value: dict[str, Any]) -> dict[str, Any]:
        if value.get("state") == "pending":
            value = self._reconcile_record(profile_ref, value)
        current = self.backend.read(self._target(profile_ref))
        if value.get("state") == "uncertain" or self._same_material(current, value.get("secretMaterialMac")):
            return value
        revision = int(value.get("highWaterRevision") or 0) + 1
        uncertain = {
            **{key: item for key, item in value.items() if key not in {"authKeyId", "authTag"}},
            "credentialRevision": revision,
            "highWaterRevision": revision,
            "exists": current is not None,
            "state": "uncertain",
            "secretMaterialMac": self._material_mac(current) if current is not None else None,
            "updatedAt": int(time.time() * 1000),
        }
        return self._write(profile_ref, uncertain)

    def metadata(self, profile_ref: str) -> dict[str, object]:
        with self._transaction():
            profile_ref = self._validate(profile_ref)
            value = self._observe_current(profile_ref, self._read(profile_ref))
            return {
                "profileRef": profile_ref,
                "secretRef": value["secretRef"],
                "credentialRevision": int(value.get("credentialRevision") or 0),
                "exists": bool(value.get("exists")),
                "state": value.get("state"),
                "updatedAt": int(value.get("updatedAt") or 0),
            }

    def secret_exists(self, profile_ref: str, *, expected_revision: int | None = None) -> bool:
        metadata = self.metadata(profile_ref)
        if expected_revision is not None and metadata["credentialRevision"] != expected_revision:
            raise CredentialStoreError("Credential revision is stale")
        return bool(metadata["exists"] and metadata["state"] == "committed")

    def _begin(
        self,
        profile_ref: str,
        *,
        operation: str,
        intended_material_mac: str | None,
        expected_revision: int | None,
    ) -> dict[str, Any]:
        current = self._observe_current(profile_ref, self._read(profile_ref))
        current_revision = int(current.get("credentialRevision") or 0)
        if expected_revision is not None and current_revision != expected_revision:
            raise CredentialStoreError("Credential revision is stale")
        next_revision = int(current.get("highWaterRevision") or 0) + 1
        pending = {
            **{key: item for key, item in current.items() if key not in {"authKeyId", "authTag"}},
            "credentialRevision": next_revision,
            "highWaterRevision": next_revision,
            "state": "pending",
            "pendingOperation": operation,
            "pendingMaterialMac": intended_material_mac,
            "previousCredentialRevision": current_revision,
            "previousExists": bool(current.get("exists")),
            "previousSecretMaterialMac": current.get("secretMaterialMac"),
            "updatedAt": int(time.time() * 1000),
        }
        return self._write(profile_ref, pending)

    @staticmethod
    def _public(value: dict[str, Any]) -> dict[str, object]:
        return {
            key: value[key]
            for key in ("profileRef", "secretRef", "credentialRevision", "exists", "state", "updatedAt")
        }

    def _mutate(
        self,
        profile_ref: str,
        *,
        operation: str,
        secret: str | None,
        expected_revision: int | None,
    ) -> dict[str, object]:
        profile_ref = self._validate(profile_ref)
        if operation != "delete" and (not isinstance(secret, str) or not secret):
            raise CredentialStoreError("Credential secret cannot be empty")
        intended_mac = self._material_mac(secret) if secret is not None else None
        with self._transaction():
            pending = self._begin(
                profile_ref,
                operation=operation,
                intended_material_mac=intended_mac,
                expected_revision=expected_revision,
            )
            try:
                if operation == "delete":
                    self.backend.delete(self._target(profile_ref))
                else:
                    assert secret is not None
                    self.backend.write(self._target(profile_ref), secret)
            except Exception:
                self._reconcile_record(profile_ref, pending)
                raise
            finally:
                secret = None
            committed = self._reconcile_record(profile_ref, pending)
            if committed.get("state") != "committed" or committed.get("credentialRevision") != pending.get("credentialRevision"):
                raise CredentialStoreError("Credential mutation could not be verified")
            return self._public(committed)

    def set_secret(
        self,
        profile_ref: str,
        secret: str,
        *,
        expected_revision: int | None = None,
    ) -> dict[str, object]:
        return self._mutate(
            profile_ref,
            operation="set",
            secret=secret,
            expected_revision=expected_revision,
        )

    def delete_secret(
        self,
        profile_ref: str,
        *,
        expected_revision: int | None = None,
    ) -> dict[str, object]:
        return self._mutate(
            profile_ref,
            operation="delete",
            secret=None,
            expected_revision=expected_revision,
        )

    def rollback_secret(
        self,
        profile_ref: str,
        restored_secret: str,
        *,
        expected_revision: int,
    ) -> dict[str, object]:
        return self._mutate(
            profile_ref,
            operation="rollback",
            secret=restored_secret,
            expected_revision=expected_revision,
        )

    def set_oauth_material(
        self,
        profile_ref: str,
        oauth_material: str,
        *,
        expected_revision: int | None = None,
    ) -> dict[str, object]:
        return self._mutate(
            profile_ref,
            operation="oauth_material_change",
            secret=oauth_material,
            expected_revision=expected_revision,
        )

    def resolve_secret(self, profile_ref: str, *, expected_revision: int) -> str:
        with self._transaction():
            profile_ref = self._validate(profile_ref)
            value = self._observe_current(profile_ref, self._read(profile_ref))
            if value.get("state") != "committed" or value.get("credentialRevision") != expected_revision:
                raise CredentialStoreError("Credential revision is stale")
            secret = self.backend.read(self._target(profile_ref))
            if secret is None:
                raise CredentialStoreError("Credential does not exist")
            if not self._same_material(secret, value.get("secretMaterialMac")):
                raise CredentialStoreError("Credential material is not authenticated")
            return secret
