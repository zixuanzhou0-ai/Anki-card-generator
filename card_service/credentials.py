from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import threading
import time
from ctypes import wintypes
from pathlib import Path
from typing import Protocol

from .storage import AtomicJsonStore


PROFILE_REF_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


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
    """Credential Manager facade with crash-safe, strictly monotonic revisions."""

    def __init__(self, *, state_dir: str | Path, backend: CredentialBackend | None = None, target_prefix: str = "CodexStudy") -> None:
        root = Path(state_dir).expanduser()
        if not root.is_absolute():
            raise CredentialStoreError("Credential metadata directory must be absolute")
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.backend = backend or WindowsCredentialBackend()
        self.target_prefix = target_prefix.rstrip("/")
        self._lock = threading.RLock()
        self._reconcile_pending_updates()

    @staticmethod
    def _validate(profile_ref: str) -> str:
        if not PROFILE_REF_PATTERN.fullmatch(profile_ref):
            raise CredentialStoreError("Invalid credential profile reference")
        return profile_ref

    def _target(self, profile_ref: str) -> str:
        return f"{self.target_prefix}/{self._validate(profile_ref)}"

    def _path(self, profile_ref: str) -> Path:
        return self.root / f"{hashlib.sha256(profile_ref.encode('utf-8')).hexdigest()}.json"

    def _read(self, profile_ref: str) -> dict[str, object]:
        path = self._path(profile_ref)
        if not path.is_file():
            return {"schemaVersion": 1, "profileRef": profile_ref, "credentialRevision": 0, "exists": False, "state": "committed", "updatedAt": 0}
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        if not isinstance(value, dict) or value.get("profileRef") != profile_ref:
            raise CredentialStoreError("Credential metadata is invalid")
        return value

    def _write(self, profile_ref: str, value: dict[str, object]) -> None:
        AtomicJsonStore._write_atomic(self._path(profile_ref), value)

    def _reconcile_pending_updates(self) -> None:
        for path in self.root.glob("*.json"):
            try:
                with path.open("r", encoding="utf-8") as handle:
                    value = json.load(handle)
                profile_ref = str(value.get("profileRef") or "")
                if value.get("state") != "pending" or not PROFILE_REF_PATTERN.fullmatch(profile_ref):
                    continue
                value.update(state="committed", exists=self.backend.exists(self._target(profile_ref)), updatedAt=int(time.time() * 1000))
                AtomicJsonStore._write_atomic(path, value)
            except (OSError, ValueError, CredentialStoreError):
                continue

    def metadata(self, profile_ref: str) -> dict[str, object]:
        with self._lock:
            profile_ref = self._validate(profile_ref)
            value = self._read(profile_ref)
            return {"profileRef": profile_ref, "credentialRevision": int(value.get("credentialRevision") or 0), "exists": self.backend.exists(self._target(profile_ref)), "updatedAt": int(value.get("updatedAt") or 0)}

    def _begin(self, profile_ref: str) -> dict[str, object]:
        current = self._read(profile_ref)
        pending = {"schemaVersion": 1, "profileRef": profile_ref, "credentialRevision": int(current.get("credentialRevision") or 0) + 1, "exists": bool(current.get("exists")), "state": "pending", "updatedAt": int(time.time() * 1000)}
        self._write(profile_ref, pending)
        return pending

    def _commit(self, profile_ref: str, pending: dict[str, object]) -> dict[str, object]:
        committed = {**pending, "exists": self.backend.exists(self._target(profile_ref)), "state": "committed", "updatedAt": int(time.time() * 1000)}
        self._write(profile_ref, committed)
        return {key: committed[key] for key in ("profileRef", "credentialRevision", "exists", "updatedAt")}

    def set_secret(self, profile_ref: str, secret: str) -> dict[str, object]:
        profile_ref = self._validate(profile_ref)
        if not secret:
            raise CredentialStoreError("Credential secret cannot be empty")
        with self._lock:
            pending = self._begin(profile_ref)
            try:
                self.backend.write(self._target(profile_ref), secret)
            finally:
                secret = ""
            return self._commit(profile_ref, pending)

    def delete_secret(self, profile_ref: str) -> dict[str, object]:
        profile_ref = self._validate(profile_ref)
        with self._lock:
            pending = self._begin(profile_ref)
            self.backend.delete(self._target(profile_ref))
            return self._commit(profile_ref, pending)

    def resolve_secret(self, profile_ref: str, *, expected_revision: int) -> str:
        with self._lock:
            profile_ref = self._validate(profile_ref)
            value = self._read(profile_ref)
            if value.get("state") != "committed" or int(value.get("credentialRevision") or 0) != expected_revision:
                raise CredentialStoreError("Credential revision is stale")
            secret = self.backend.read(self._target(profile_ref))
            if secret is None:
                raise CredentialStoreError("Credential does not exist")
            return secret
