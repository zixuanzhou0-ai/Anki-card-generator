from __future__ import annotations

import ctypes
import hashlib
import os
import stat
import uuid
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


SE_FILE_OBJECT = 1
DACL_SECURITY_INFORMATION = 0x00000004
PROTECTED_DACL_SECURITY_INFORMATION = 0x80000000
SET_ACCESS = 2
TRUSTEE_IS_SID = 0
TRUSTEE_IS_UNKNOWN = 0
OBJECT_INHERIT_ACE = 0x01
CONTAINER_INHERIT_ACE = 0x02
ACCESS_ALLOWED_ACE_TYPE = 0x00
TOKEN_QUERY = 0x0008
TOKEN_USER_INFORMATION_CLASS = 1
ERROR_INSUFFICIENT_BUFFER = 122
FILE_GENERIC_READ_EXECUTE = 0x001200A9
FILE_MODIFY = 0x001301BF
FILE_FULL_CONTROL = 0x001F01FF
SYSTEM_SID = "S-1-5-18"
ADMINISTRATORS_SID = "S-1-5-32-544"
RUNTIME_APPCONTAINER_PREFIX = "AnkiStudy.CardService."
TASK_CAPABILITY_PREFIX = "AnkiStudy.CardService.Task."
HRESULT_ERROR_ALREADY_EXISTS = 0x800700B7


class WindowsSandboxAclError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]


class TOKEN_USER(ctypes.Structure):
    _fields_ = [("User", SID_AND_ATTRIBUTES)]


class TRUSTEE_W(ctypes.Structure):
    _fields_ = [
        ("pMultipleTrustee", ctypes.c_void_p),
        ("MultipleTrusteeOperation", wintypes.DWORD),
        ("TrusteeForm", wintypes.DWORD),
        ("TrusteeType", wintypes.DWORD),
        ("ptstrName", ctypes.c_void_p),
    ]


class EXPLICIT_ACCESS_W(ctypes.Structure):
    _fields_ = [
        ("grfAccessPermissions", wintypes.DWORD),
        ("grfAccessMode", wintypes.DWORD),
        ("grfInheritance", wintypes.DWORD),
        ("Trustee", TRUSTEE_W),
    ]


class ACL_HEADER(ctypes.Structure):
    _fields_ = [
        ("AclRevision", ctypes.c_ubyte),
        ("Sbz1", ctypes.c_ubyte),
        ("AclSize", wintypes.WORD),
        ("AceCount", wintypes.WORD),
        ("Sbz2", wintypes.WORD),
    ]


class ACE_HEADER(ctypes.Structure):
    _fields_ = [
        ("AceType", ctypes.c_ubyte),
        ("AceFlags", ctypes.c_ubyte),
        ("AceSize", wintypes.WORD),
    ]


class ACCESS_ALLOWED_ACE(ctypes.Structure):
    _fields_ = [
        ("Header", ACE_HEADER),
        ("Mask", wintypes.DWORD),
        ("SidStart", wintypes.DWORD),
    ]


@dataclass(frozen=True, order=True)
class DaclEntry:
    sid: str
    access_mask: int
    inheritance_flags: int


def _require_windows() -> None:
    if os.name != "nt":
        raise WindowsSandboxAclError("WINDOWS_ACL_UNAVAILABLE", "Windows sandbox ACLs are unavailable")


def _libraries() -> tuple[ctypes.WinDLL, ctypes.WinDLL]:
    _require_windows()
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    advapi32.ConvertStringSidToSidW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
    advapi32.ConvertStringSidToSidW.restype = wintypes.BOOL
    advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.SetEntriesInAclW.argtypes = [
        wintypes.ULONG,
        ctypes.POINTER(EXPLICIT_ACCESS_W),
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi32.SetEntriesInAclW.restype = wintypes.DWORD
    advapi32.SetNamedSecurityInfoW.argtypes = [
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    advapi32.SetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi32.GetNamedSecurityInfoW.argtypes = [
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi32.GetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi32.GetAce.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
    advapi32.GetAce.restype = wintypes.BOOL
    return kernel32, advapi32


def _stable_existing_path(raw: str | Path) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        raise WindowsSandboxAclError("WINDOWS_ACL_PATH_RELATIVE", "ACL target must be absolute")
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    for part in absolute.parts[1:]:
        current /= part
        attributes = getattr(current.stat(follow_symlinks=False), "st_file_attributes", 0)
        if current.is_symlink() or attributes & reparse_flag:
            raise WindowsSandboxAclError("WINDOWS_ACL_REPARSE_BLOCKED", "ACL target contains a reparse point")
    return absolute.resolve(strict=True)


def _sid_from_text(advapi32: ctypes.WinDLL, value: str) -> ctypes.c_void_p:
    sid = ctypes.c_void_p()
    if not advapi32.ConvertStringSidToSidW(value, ctypes.byref(sid)):
        raise WindowsSandboxAclError("WINDOWS_SID_INVALID", f"Invalid sandbox SID: {ctypes.get_last_error()}")
    return sid


def _sid_to_text(kernel32: ctypes.WinDLL, advapi32: ctypes.WinDLL, sid: ctypes.c_void_p) -> str:
    text = wintypes.LPWSTR()
    if not advapi32.ConvertSidToStringSidW(sid, ctypes.byref(text)):
        raise WindowsSandboxAclError("WINDOWS_SID_INVALID", f"Could not encode SID: {ctypes.get_last_error()}")
    try:
        return str(text.value)
    finally:
        kernel32.LocalFree(text)


def current_user_sid() -> str:
    kernel32, advapi32 = _libraries()
    token = wintypes.HANDLE()
    buffer: ctypes.Array[ctypes.c_char] | None = None
    try:
        if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(token)):
            raise WindowsSandboxAclError("WINDOWS_TOKEN_UNAVAILABLE", f"OpenProcessToken failed: {ctypes.get_last_error()}")
        size = wintypes.DWORD()
        if advapi32.GetTokenInformation(
            token,
            TOKEN_USER_INFORMATION_CLASS,
            None,
            0,
            ctypes.byref(size),
        ) or ctypes.get_last_error() != ERROR_INSUFFICIENT_BUFFER:
            raise WindowsSandboxAclError("WINDOWS_TOKEN_UNAVAILABLE", "Could not size token user information")
        buffer = ctypes.create_string_buffer(size.value)
        if not advapi32.GetTokenInformation(
            token,
            TOKEN_USER_INFORMATION_CLASS,
            buffer,
            size,
            ctypes.byref(size),
        ):
            raise WindowsSandboxAclError("WINDOWS_TOKEN_UNAVAILABLE", f"GetTokenInformation failed: {ctypes.get_last_error()}")
        token_user = ctypes.cast(buffer, ctypes.POINTER(TOKEN_USER)).contents
        return _sid_to_text(kernel32, advapi32, token_user.User.Sid)
    finally:
        if token:
            kernel32.CloseHandle(token)


def _runtime_appcontainer_name(package_id: str) -> str:
    suffix = hashlib.sha256(f"study.runtime-appcontainer.v1:{package_id}".encode("utf-8")).hexdigest()[:32]
    return RUNTIME_APPCONTAINER_PREFIX + suffix


def _ensure_appcontainer_profile(name: str) -> str:
    kernel32, advapi32 = _libraries()
    userenv = ctypes.WinDLL("userenv", use_last_error=True)
    advapi32.FreeSid.argtypes = [ctypes.c_void_p]
    advapi32.FreeSid.restype = ctypes.c_void_p
    userenv.CreateAppContainerProfile.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    userenv.CreateAppContainerProfile.restype = ctypes.c_long
    userenv.DeriveAppContainerSidFromAppContainerName.argtypes = [
        wintypes.LPCWSTR,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    userenv.DeriveAppContainerSidFromAppContainerName.restype = ctypes.c_long
    sid = ctypes.c_void_p()
    try:
        result = userenv.CreateAppContainerProfile(
            name,
            "Anki Study Card Service",
            "Restricted local card-generation runtime",
            None,
            0,
            ctypes.byref(sid),
        )
        unsigned_result = int(result) & 0xFFFFFFFF
        if unsigned_result == HRESULT_ERROR_ALREADY_EXISTS:
            result = userenv.DeriveAppContainerSidFromAppContainerName(name, ctypes.byref(sid))
            unsigned_result = int(result) & 0xFFFFFFFF
        if unsigned_result != 0 or not sid:
            raise WindowsSandboxAclError(
                "WINDOWS_APPCONTAINER_PROFILE_FAILED",
                f"Could not create or derive the AppContainer profile: 0x{unsigned_result:08X}",
            )
        return _sid_to_text(kernel32, advapi32, sid)
    finally:
        if sid:
            advapi32.FreeSid(sid)


def _derive_appcontainer_sid(name: str) -> str:
    kernel32, advapi32 = _libraries()
    userenv = ctypes.WinDLL("userenv", use_last_error=True)
    advapi32.FreeSid.argtypes = [ctypes.c_void_p]
    advapi32.FreeSid.restype = ctypes.c_void_p
    userenv.DeriveAppContainerSidFromAppContainerName.argtypes = [
        wintypes.LPCWSTR,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    userenv.DeriveAppContainerSidFromAppContainerName.restype = ctypes.c_long
    sid = ctypes.c_void_p()
    try:
        result = userenv.DeriveAppContainerSidFromAppContainerName(name, ctypes.byref(sid))
        unsigned_result = int(result) & 0xFFFFFFFF
        if unsigned_result != 0 or not sid:
            raise WindowsSandboxAclError(
                "WINDOWS_APPCONTAINER_SID_FAILED",
                f"Could not derive the AppContainer SID: 0x{unsigned_result:08X}",
            )
        return _sid_to_text(kernel32, advapi32, sid)
    finally:
        if sid:
            advapi32.FreeSid(sid)


def _derive_capability_sid(name: str) -> str:
    kernel32, advapi32 = _libraries()
    kernelbase = ctypes.WinDLL("kernelbase", use_last_error=True)
    sid_array = ctypes.POINTER(ctypes.c_void_p)
    kernelbase.DeriveCapabilitySidsFromName.argtypes = [
        wintypes.LPCWSTR,
        ctypes.POINTER(sid_array),
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(sid_array),
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernelbase.DeriveCapabilitySidsFromName.restype = wintypes.BOOL
    group_sids = sid_array()
    capability_sids = sid_array()
    group_count = wintypes.DWORD()
    capability_count = wintypes.DWORD()
    try:
        if not kernelbase.DeriveCapabilitySidsFromName(
            name,
            ctypes.byref(group_sids),
            ctypes.byref(group_count),
            ctypes.byref(capability_sids),
            ctypes.byref(capability_count),
        ):
            raise WindowsSandboxAclError(
                "WINDOWS_CAPABILITY_SID_FAILED",
                f"Could not derive the task capability SID: {ctypes.get_last_error()}",
            )
        if capability_count.value != 1 or not capability_sids:
            raise WindowsSandboxAclError(
                "WINDOWS_CAPABILITY_SID_FAILED",
                "Task capability derivation did not return exactly one AppAuthority SID",
            )
        return _sid_to_text(kernel32, advapi32, ctypes.c_void_p(capability_sids[0]))
    finally:
        if group_sids:
            for index in range(group_count.value):
                kernel32.LocalFree(ctypes.c_void_p(group_sids[index]))
            kernel32.LocalFree(ctypes.cast(group_sids, ctypes.c_void_p))
        if capability_sids:
            for index in range(capability_count.value):
                kernel32.LocalFree(ctypes.c_void_p(capability_sids[index]))
            kernel32.LocalFree(ctypes.cast(capability_sids, ctypes.c_void_p))


def runtime_sandbox_sid(package_id: str = "anki-study-managed-runtime") -> str:
    return _derive_appcontainer_sid(_runtime_appcontainer_name(package_id))


def ensure_runtime_sandbox_profile(package_id: str = "anki-study-managed-runtime") -> str:
    """Provision the per-user profile; release verification must use runtime_sandbox_sid()."""

    return _ensure_appcontainer_profile(_runtime_appcontainer_name(package_id))


def task_sandbox_sid(task_id: str) -> str:
    try:
        canonical_task_id = str(uuid.UUID(task_id))
    except (ValueError, AttributeError) as error:
        raise WindowsSandboxAclError("WINDOWS_TASK_ID_INVALID", "Task ID must be a canonical UUID") from error
    if canonical_task_id != task_id:
        raise WindowsSandboxAclError("WINDOWS_TASK_ID_INVALID", "Task ID must be a canonical UUID")
    return _derive_capability_sid(TASK_CAPABILITY_PREFIX + canonical_task_id)


def apply_exact_dacl(
    path: str | Path,
    grants: Iterable[tuple[str, int]],
    *,
    inherit_to_children: bool,
) -> tuple[DaclEntry, ...]:
    target = _stable_existing_path(path)
    kernel32, advapi32 = _libraries()
    normalized = sorted({(str(sid), int(mask)) for sid, mask in grants}, key=lambda item: item[0].encode("utf-8"))
    if not normalized:
        raise WindowsSandboxAclError("WINDOWS_ACL_EMPTY", "ACL grants must not be empty")
    sid_allocations: list[ctypes.c_void_p] = []
    new_acl = ctypes.c_void_p()
    try:
        entries = (EXPLICIT_ACCESS_W * len(normalized))()
        inheritance = OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE if inherit_to_children else 0
        for index, (sid_text, access_mask) in enumerate(normalized):
            sid = _sid_from_text(advapi32, sid_text)
            sid_allocations.append(sid)
            entries[index].grfAccessPermissions = access_mask
            entries[index].grfAccessMode = SET_ACCESS
            entries[index].grfInheritance = inheritance
            entries[index].Trustee = TRUSTEE_W(None, 0, TRUSTEE_IS_SID, TRUSTEE_IS_UNKNOWN, sid)
        status = advapi32.SetEntriesInAclW(len(entries), entries, None, ctypes.byref(new_acl))
        if status != 0:
            raise WindowsSandboxAclError("WINDOWS_ACL_BUILD_FAILED", f"SetEntriesInAclW failed: {status}")
        status = advapi32.SetNamedSecurityInfoW(
            str(target),
            SE_FILE_OBJECT,
            DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION,
            None,
            None,
            new_acl,
            None,
        )
        if status != 0:
            raise WindowsSandboxAclError("WINDOWS_ACL_APPLY_FAILED", f"SetNamedSecurityInfoW failed: {status}")
    finally:
        if new_acl:
            kernel32.LocalFree(new_acl)
        for sid in sid_allocations:
            kernel32.LocalFree(sid)
    return read_dacl(target)


def read_dacl(path: str | Path) -> tuple[DaclEntry, ...]:
    target = _stable_existing_path(path)
    kernel32, advapi32 = _libraries()
    dacl = ctypes.c_void_p()
    security_descriptor = ctypes.c_void_p()
    status = advapi32.GetNamedSecurityInfoW(
        str(target),
        SE_FILE_OBJECT,
        DACL_SECURITY_INFORMATION,
        None,
        None,
        ctypes.byref(dacl),
        None,
        ctypes.byref(security_descriptor),
    )
    if status != 0 or not dacl:
        raise WindowsSandboxAclError("WINDOWS_ACL_READ_FAILED", f"GetNamedSecurityInfoW failed: {status}")
    try:
        header = ctypes.cast(dacl, ctypes.POINTER(ACL_HEADER)).contents
        entries: list[DaclEntry] = []
        sid_offset = ACCESS_ALLOWED_ACE.SidStart.offset
        for index in range(header.AceCount):
            ace_pointer = ctypes.c_void_p()
            if not advapi32.GetAce(dacl, index, ctypes.byref(ace_pointer)):
                raise WindowsSandboxAclError("WINDOWS_ACL_READ_FAILED", f"GetAce failed: {ctypes.get_last_error()}")
            ace = ctypes.cast(ace_pointer, ctypes.POINTER(ACCESS_ALLOWED_ACE)).contents
            if ace.Header.AceType != ACCESS_ALLOWED_ACE_TYPE:
                raise WindowsSandboxAclError("WINDOWS_ACL_UNEXPECTED_ACE", "Sandbox DACL contains a non-allow ACE")
            sid_pointer = ctypes.c_void_p(int(ace_pointer.value) + sid_offset)
            entries.append(
                DaclEntry(
                    sid=_sid_to_text(kernel32, advapi32, sid_pointer),
                    access_mask=int(ace.Mask),
                    inheritance_flags=int(ace.Header.AceFlags) & (OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE),
                )
            )
        return tuple(sorted(entries))
    finally:
        kernel32.LocalFree(security_descriptor)


def runtime_tree_grants(sandbox_sid: str, *, user_sid: str | None = None) -> tuple[tuple[str, int], ...]:
    return (
        (user_sid or current_user_sid(), FILE_FULL_CONTROL),
        (SYSTEM_SID, FILE_FULL_CONTROL),
        (ADMINISTRATORS_SID, FILE_FULL_CONTROL),
        (sandbox_sid, FILE_GENERIC_READ_EXECUTE),
    )


def task_workspace_grants(task_sid: str, *, user_sid: str | None = None) -> tuple[tuple[str, int], ...]:
    return (
        (user_sid or current_user_sid(), FILE_FULL_CONTROL),
        (SYSTEM_SID, FILE_FULL_CONTROL),
        (ADMINISTRATORS_SID, FILE_FULL_CONTROL),
        (task_sid, FILE_MODIFY),
    )


def service_root_grants(*, user_sid: str | None = None) -> tuple[tuple[str, int], ...]:
    return (
        (user_sid or current_user_sid(), FILE_FULL_CONTROL),
        (SYSTEM_SID, FILE_FULL_CONTROL),
        (ADMINISTRATORS_SID, FILE_FULL_CONTROL),
    )


def harden_runtime_tree(root: str | Path, sandbox_sid: str) -> None:
    runtime_root = _stable_existing_path(root)
    if not runtime_root.is_dir():
        raise WindowsSandboxAclError("WINDOWS_RUNTIME_ROOT_INVALID", "Runtime ACL root must be a directory")
    grants = runtime_tree_grants(sandbox_sid)
    paths = [runtime_root, *sorted(runtime_root.rglob("*"), key=lambda value: len(value.parts))]
    for path in paths:
        _stable_existing_path(path)
        apply_exact_dacl(path, grants, inherit_to_children=path.is_dir())


def verify_runtime_tree_dacl(root: str | Path, sandbox_sid: str) -> None:
    runtime_root = _stable_existing_path(root)
    grants = runtime_tree_grants(sandbox_sid)
    expected_file = tuple(sorted(DaclEntry(sid, mask, 0) for sid, mask in grants))
    expected_directory = tuple(
        sorted(DaclEntry(sid, mask, OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE) for sid, mask in grants)
    )
    for path in [runtime_root, *runtime_root.rglob("*")]:
        if read_dacl(path) != (expected_directory if path.is_dir() else expected_file):
            raise WindowsSandboxAclError("WINDOWS_RUNTIME_DACL_MISMATCH", "Runtime package DACL is not exact")


def create_task_workspace(root: str | Path, task_id: str) -> tuple[Path, str]:
    workspace_root = Path(root)
    if not workspace_root.is_absolute():
        raise WindowsSandboxAclError("WINDOWS_ACL_PATH_RELATIVE", "Task workspace root must be absolute")
    workspace_root.mkdir(parents=True, exist_ok=True)
    workspace_root = _stable_existing_path(workspace_root)
    apply_exact_dacl(workspace_root, service_root_grants(), inherit_to_children=True)
    task_sid = task_sandbox_sid(task_id)
    workspace = workspace_root / task_id
    workspace.mkdir(exist_ok=False)
    apply_exact_dacl(workspace, task_workspace_grants(task_sid), inherit_to_children=True)
    return workspace, task_sid


def harden_staged_path(path: str | Path, task_sid: str) -> None:
    target = _stable_existing_path(path)
    grants = task_workspace_grants(task_sid)
    paths = [target, *target.rglob("*")] if target.is_dir() else [target]
    for child in paths:
        _stable_existing_path(child)
        apply_exact_dacl(child, grants, inherit_to_children=child.is_dir())
