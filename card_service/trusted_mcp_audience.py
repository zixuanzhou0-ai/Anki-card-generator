from __future__ import annotations

import ctypes
import hashlib
import os
import re
import secrets
from dataclasses import dataclass
from pathlib import Path

from .artifact_registry import ArtifactAudienceBinding


LAUNCHER_PID_ENV = "ANKI_STUDY_MCP_LAUNCHER_PID"
SESSION_NONCE_ENV = "ANKI_STUDY_MCP_SESSION_NONCE"
PLUGIN_ID = "anki-study-agent-plugin"
_NONCE_RE = re.compile(r"^[0-9a-f]{64}$")


class TrustedMcpAudienceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class TrustedMcpAudienceSession:
    audience: ArtifactAudienceBinding
    mode: str

    def public_summary(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "available": True,
            "mode": self.mode,
            "identifiersDisclosed": False,
            "toolArgumentsCanDeclareAudience": False,
        }


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _windows_user_sid() -> str:
    from ctypes import wintypes

    token_query = 0x0008
    token_user_class = 1
    token = wintypes.HANDLE()
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32.GetCurrentProcess.argtypes = []
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.ConvertSidToStringSidW.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.LPWSTR),
    ]
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(), token_query, ctypes.byref(token)
    ):
        raise OSError(ctypes.get_last_error(), "OpenProcessToken failed")
    try:
        required = wintypes.DWORD()
        advapi32.GetTokenInformation(
            token, token_user_class, None, 0, ctypes.byref(required)
        )
        if required.value <= 0 or required.value > 64 * 1024:
            raise OSError("TokenUser size is invalid")
        buffer = ctypes.create_string_buffer(required.value)
        if not advapi32.GetTokenInformation(
            token,
            token_user_class,
            buffer,
            required.value,
            ctypes.byref(required),
        ):
            raise OSError(ctypes.get_last_error(), "GetTokenInformation failed")

        class SidAndAttributes(ctypes.Structure):
            _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]

        class TokenUser(ctypes.Structure):
            _fields_ = [("User", SidAndAttributes)]

        user = ctypes.cast(buffer, ctypes.POINTER(TokenUser)).contents
        sid_text = ctypes.c_wchar_p()
        if not advapi32.ConvertSidToStringSidW(user.User.Sid, ctypes.byref(sid_text)):
            raise OSError(ctypes.get_last_error(), "ConvertSidToStringSidW failed")
        try:
            value = str(sid_text.value or "")
        finally:
            kernel32.LocalFree(ctypes.cast(sid_text, ctypes.c_void_p))
        if not re.fullmatch(r"S-1-(?:[0-9]+-)+[0-9]+", value):
            raise OSError("Current Windows SID is invalid")
        return value
    finally:
        kernel32.CloseHandle(token)


def _current_owner_identity() -> str:
    if os.name == "nt":
        return "windows-sid:" + _windows_user_sid()
    if not hasattr(os, "getuid"):
        raise TrustedMcpAudienceError(
            "MCP_OWNER_IDENTITY_UNAVAILABLE", "Current OS owner identity is unavailable"
        )
    return f"posix-uid:{os.getuid()}"


def current_owner_digest() -> str:
    try:
        identity = _current_owner_identity()
    except (OSError, ValueError) as error:
        raise TrustedMcpAudienceError(
            "MCP_OWNER_IDENTITY_UNAVAILABLE", "Current OS owner identity is unavailable"
        ) from error
    return _sha(b"study.mcp-owner-identity.v1\x00" + identity.encode("utf-8"))


def _process_executable(process_id: int) -> Path:
    if process_id <= 0:
        raise TrustedMcpAudienceError(
            "MCP_LAUNCH_ATTESTATION_INVALID", "Launcher process identity is invalid"
        )
    if os.name != "nt":
        try:
            return Path(f"/proc/{process_id}/exe").resolve(strict=True)
        except OSError as error:
            raise TrustedMcpAudienceError(
                "MCP_LAUNCH_ATTESTATION_INVALID", "Launcher process is unavailable"
            ) from error

    from ctypes import wintypes

    process_query_limited_information = 0x1000
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(
        process_query_limited_information, False, wintypes.DWORD(process_id)
    )
    if not handle:
        raise TrustedMcpAudienceError(
            "MCP_LAUNCH_ATTESTATION_INVALID", "Launcher process is unavailable"
        )
    try:
        size = wintypes.DWORD(32_768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(
            handle, 0, buffer, ctypes.byref(size)
        ):
            raise TrustedMcpAudienceError(
                "MCP_LAUNCH_ATTESTATION_INVALID", "Launcher executable is unavailable"
            )
        return Path(buffer.value).resolve(strict=True)
    finally:
        kernel32.CloseHandle(handle)


def _derive_session(
    *,
    owner_digest: str,
    launcher: Path,
    nonce: str,
    mode: str,
    stable_host_identity: str | None = None,
) -> TrustedMcpAudienceSession:
    if not re.fullmatch(r"[0-9a-f]{64}", owner_digest) or not _NONCE_RE.fullmatch(
        nonce
    ):
        raise TrustedMcpAudienceError(
            "MCP_LAUNCH_ATTESTATION_INVALID", "MCP launch identity is invalid"
        )
    launcher_digest = _sha(
        (
            "stable-install:" + stable_host_identity
            if stable_host_identity is not None
            else os.path.normcase(str(launcher.absolute()))
        ).encode("utf-8", "strict")
    )
    nonce_bytes = bytes.fromhex(nonce)
    host_digest = _sha(
        b"study.mcp-host-instance.v2\x00"
        + owner_digest.encode("ascii")
        + b"\x00"
        + launcher_digest.encode("ascii")
        + b"\x00"
        + PLUGIN_ID.encode("utf-8", "strict")
    )
    host_id = "stdio-host-" + host_digest[:48]
    session_id = (
        "mcp-session-"
        + _sha(
            b"study.mcp-session.v2\x00"
            + host_digest.encode("ascii")
            + b"\x00"
            + nonce_bytes
        )[:48]
    )
    return TrustedMcpAudienceSession(
        audience=ArtifactAudienceBinding(
            owner_digest=owner_digest,
            host_id=host_id,
            plugin_id=PLUGIN_ID,
            session_id=session_id,
        ),
        mode=mode,
    )


def create_packaged_mcp_audience(runtime_root: str | Path) -> TrustedMcpAudienceSession:
    launcher_pid_text = os.environ.pop(LAUNCHER_PID_ENV, "")
    nonce = os.environ.pop(SESSION_NONCE_ENV, "")
    if not launcher_pid_text.isdigit() or not _NONCE_RE.fullmatch(nonce):
        raise TrustedMcpAudienceError(
            "MCP_LAUNCH_ATTESTATION_REQUIRED",
            "The signed native launcher did not provide a valid MCP session proof",
        )
    launcher_pid = int(launcher_pid_text)
    if launcher_pid != os.getppid():
        raise TrustedMcpAudienceError(
            "MCP_LAUNCH_ATTESTATION_INVALID", "MCP launcher parent binding is invalid"
        )
    root = Path(runtime_root).resolve(strict=True)
    executable_name = "anki-study-agent.exe" if os.name == "nt" else "anki-study-agent"
    expected_launcher = (root.parent / "launcher" / executable_name).resolve(
        strict=True
    )
    actual_launcher = _process_executable(launcher_pid)
    try:
        same_launcher = os.path.samefile(actual_launcher, expected_launcher)
    except OSError as error:
        raise TrustedMcpAudienceError(
            "MCP_LAUNCH_ATTESTATION_INVALID", "MCP launcher identity is unavailable"
        ) from error
    if not same_launcher:
        raise TrustedMcpAudienceError(
            "MCP_LAUNCH_ATTESTATION_INVALID",
            "MCP launcher executable binding is invalid",
        )
    return _derive_session(
        owner_digest=current_owner_digest(),
        launcher=actual_launcher,
        nonce=nonce,
        mode="packaged_launcher",
    )


def create_development_mcp_audience(
    *, installation_identity: str | None = None
) -> TrustedMcpAudienceSession:
    if installation_identity is None:
        launcher = Path(__file__).resolve()
    else:
        if not _NONCE_RE.fullmatch(installation_identity):
            raise TrustedMcpAudienceError(
                "MCP_INSTALL_IDENTITY_INVALID",
                "Development MCP installation identity is invalid",
            )
        # A stable, opaque identity keeps project scope intact when a content-
        # addressed development snapshot is upgraded. It is stored beneath the
        # same exact-DACL state root as the Card Service, never in the snapshot.
        launcher = Path(__file__).resolve()
    return _derive_session(
        owner_digest=current_owner_digest(),
        launcher=launcher,
        nonce=secrets.token_hex(32),
        mode="development_explicit",
        stable_host_identity=installation_identity,
    )
