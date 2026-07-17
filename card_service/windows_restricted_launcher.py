from __future__ import annotations

import argparse
import base64
import ctypes
import hashlib
import hmac
import json
import os
import subprocess
import sys
from ctypes import wintypes
from typing import Any


SANDBOX_ATTESTATION_PREFIX = "__ANKI_CARD_SANDBOX_ATTESTATION__"
ERROR_PREFIX = "__ANKI_CARD_ERROR__"
RESTRICTED_CHILD_EXIT_PREFIX = "__ANKI_CARD_RESTRICTED_CHILD_EXIT__"
DISABLE_MAX_PRIVILEGE = 0x1
TOKEN_ASSIGN_PRIMARY = 0x0001
TOKEN_DUPLICATE = 0x0002
TOKEN_QUERY = 0x0008
CREATE_SUSPENDED = 0x00000004
CREATE_NO_WINDOW = 0x08000000
EXTENDED_STARTUPINFO_PRESENT = 0x00080000
STARTF_USESTDHANDLES = 0x00000100
STD_INPUT_HANDLE = -10
STD_OUTPUT_HANDLE = -11
STD_ERROR_HANDLE = -12
HANDLE_FLAG_INHERIT = 0x00000001
WAIT_OBJECT_0 = 0
INFINITE = 0xFFFFFFFF
SECURITY_MAX_SID_SIZE = 68
WIN_AUTHENTICATED_USER_SID = 17
SECURITY_IDENTIFICATION = 1
ERROR_INSUFFICIENT_BUFFER = 122
TOKEN_IS_APPCONTAINER = 29
TOKEN_CAPABILITIES = 30
TOKEN_APPCONTAINER_SID = 31
SE_GROUP_ENABLED = 0x00000004
PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020009


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(ctypes.c_ubyte)),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [
        ("StartupInfo", STARTUPINFOW),
        ("lpAttributeList", ctypes.c_void_p),
    ]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


class SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]


class SECURITY_CAPABILITIES(ctypes.Structure):
    _fields_ = [
        ("AppContainerSid", ctypes.c_void_p),
        ("Capabilities", ctypes.POINTER(SID_AND_ATTRIBUTES)),
        ("CapabilityCount", wintypes.DWORD),
        ("Reserved", wintypes.DWORD),
    ]


class TOKEN_APPCONTAINER_INFORMATION(ctypes.Structure):
    _fields_ = [("TokenAppContainer", ctypes.c_void_p)]


def _canonical_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sign(key: bytes, value: dict[str, Any]) -> str:
    unsigned = {name: child for name, child in value.items() if name != "mac"}
    return base64.urlsafe_b64encode(hmac.new(key, _canonical_bytes(unsigned), hashlib.sha256).digest()).decode("ascii").rstrip("=")


def _fail(api: str) -> OSError:
    return OSError(ctypes.get_last_error(), f"{api} failed")


def _sid_binding_digest(domain: str, sid: str) -> str:
    return hashlib.sha256(domain.encode("ascii") + b"\x00" + sid.encode("ascii")).hexdigest()


def launch_restricted(
    *,
    command: list[str],
    cwd: str,
    task_id: str,
    attestation_key: bytes,
    runtime_sid: str | None = None,
    task_sid: str | None = None,
) -> int:
    if os.name != "nt":
        raise RuntimeError("restricted launcher is only available on Windows")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.GetStdHandle.argtypes = [wintypes.DWORD]
    kernel32.GetStdHandle.restype = wintypes.HANDLE
    kernel32.SetHandleInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD]
    kernel32.SetHandleInformation.restype = wintypes.BOOL
    kernel32.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
    kernel32.IsProcessInJob.restype = wintypes.BOOL
    kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
    kernel32.ResumeThread.restype = wintypes.DWORD
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    kernel32.InitializeProcThreadAttributeList.argtypes = [
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    kernel32.InitializeProcThreadAttributeList.restype = wintypes.BOOL
    kernel32.UpdateProcThreadAttribute.argtypes = [
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    kernel32.UpdateProcThreadAttribute.restype = wintypes.BOOL
    kernel32.DeleteProcThreadAttributeList.argtypes = [ctypes.c_void_p]
    kernel32.DeleteProcThreadAttributeList.restype = None
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
    advapi32.CreateRestrictedToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.CreateRestrictedToken.restype = wintypes.BOOL
    advapi32.CreateWellKnownSid.argtypes = [
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.CreateWellKnownSid.restype = wintypes.BOOL
    advapi32.ConvertStringSidToSidW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
    advapi32.ConvertStringSidToSidW.restype = wintypes.BOOL
    advapi32.EqualSid.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    advapi32.EqualSid.restype = wintypes.BOOL
    advapi32.CheckTokenMembership.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL)]
    advapi32.CheckTokenMembership.restype = wintypes.BOOL
    advapi32.DuplicateToken.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.POINTER(wintypes.HANDLE)]
    advapi32.DuplicateToken.restype = wintypes.BOOL
    advapi32.CreateProcessAsUserW.argtypes = [
        wintypes.HANDLE,
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.BOOL,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.LPCWSTR,
        ctypes.c_void_p,
        ctypes.POINTER(PROCESS_INFORMATION),
    ]
    advapi32.CreateProcessAsUserW.restype = wintypes.BOOL

    source_token = wintypes.HANDLE()
    restricted_token = wintypes.HANDLE()
    source_membership_token = wintypes.HANDLE()
    restricted_membership_token = wintypes.HANDLE()
    process_info = PROCESS_INFORMATION()
    disabled_sid_buffer = ctypes.create_string_buffer(SECURITY_MAX_SID_SIZE)
    sandbox_sid_allocations: list[ctypes.c_void_p] = []
    attribute_list_buffer: ctypes.Array[ctypes.c_char] | None = None
    attribute_list_initialized = False
    child_token = wintypes.HANDLE()
    filesystem_restricted = runtime_sid is not None or task_sid is not None
    if filesystem_restricted and (runtime_sid is None or task_sid is None):
        raise RuntimeError("runtime and task restricting SIDs must be supplied together")
    try:
        access = TOKEN_ASSIGN_PRIMARY | TOKEN_DUPLICATE | TOKEN_QUERY
        if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), access, ctypes.byref(source_token)):
            raise _fail("OpenProcessToken")
        disabled_sid_size = wintypes.DWORD(SECURITY_MAX_SID_SIZE)
        if not advapi32.CreateWellKnownSid(
            WIN_AUTHENTICATED_USER_SID,
            None,
            disabled_sid_buffer,
            ctypes.byref(disabled_sid_size),
        ):
            raise _fail("CreateWellKnownSid")
        disabled_sids = (SID_AND_ATTRIBUTES * 1)(
            SID_AND_ATTRIBUTES(ctypes.cast(disabled_sid_buffer, ctypes.c_void_p).value, 0)
        )
        if not advapi32.DuplicateToken(
            source_token,
            SECURITY_IDENTIFICATION,
            ctypes.byref(source_membership_token),
        ):
            raise _fail("DuplicateToken(source)")
        source_membership = wintypes.BOOL()
        if not advapi32.CheckTokenMembership(
            source_membership_token,
            ctypes.cast(disabled_sid_buffer, ctypes.c_void_p),
            ctypes.byref(source_membership),
        ):
            raise _fail("CheckTokenMembership(source)")
        if not source_membership.value:
            raise RuntimeError("source token is missing the compatibility SID selected for disabling")
        appcontainer_sid = ctypes.c_void_p()
        task_capability_sid = ctypes.c_void_p()
        if filesystem_restricted:
            assert runtime_sid is not None and task_sid is not None
            if not advapi32.ConvertStringSidToSidW(runtime_sid, ctypes.byref(appcontainer_sid)):
                raise _fail("ConvertStringSidToSidW(AppContainer)")
            sandbox_sid_allocations.append(appcontainer_sid)
            if not advapi32.ConvertStringSidToSidW(task_sid, ctypes.byref(task_capability_sid)):
                raise _fail("ConvertStringSidToSidW(task capability)")
            sandbox_sid_allocations.append(task_capability_sid)
        if not advapi32.CreateRestrictedToken(
            source_token,
            DISABLE_MAX_PRIVILEGE,
            1,
            ctypes.byref(disabled_sids),
            0,
            None,
            0,
            None,
            ctypes.byref(restricted_token),
        ):
            raise _fail("CreateRestrictedToken")
        if not advapi32.DuplicateToken(
            restricted_token,
            SECURITY_IDENTIFICATION,
            ctypes.byref(restricted_membership_token),
        ):
            raise _fail("DuplicateToken(restricted)")
        restricted_membership = wintypes.BOOL()
        if not advapi32.CheckTokenMembership(
            restricted_membership_token,
            ctypes.cast(disabled_sid_buffer, ctypes.c_void_p),
            ctypes.byref(restricted_membership),
        ):
            raise _fail("CheckTokenMembership(restricted)")
        if restricted_membership.value:
            raise RuntimeError("CreateRestrictedToken did not disable the compatibility SID")
        startup = STARTUPINFOEXW()
        startup.StartupInfo.cb = ctypes.sizeof(STARTUPINFOEXW) if filesystem_restricted else ctypes.sizeof(STARTUPINFOW)
        startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES
        startup.StartupInfo.hStdInput = kernel32.GetStdHandle(STD_INPUT_HANDLE)
        startup.StartupInfo.hStdOutput = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
        startup.StartupInfo.hStdError = kernel32.GetStdHandle(STD_ERROR_HANDLE)
        for handle in (
            startup.StartupInfo.hStdInput,
            startup.StartupInfo.hStdOutput,
            startup.StartupInfo.hStdError,
        ):
            if not handle or not kernel32.SetHandleInformation(handle, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT):
                raise _fail("SetHandleInformation")
        creation_flags = CREATE_SUSPENDED | CREATE_NO_WINDOW
        capabilities: ctypes.Array[SID_AND_ATTRIBUTES] | None = None
        security_capabilities: SECURITY_CAPABILITIES | None = None
        if filesystem_restricted:
            capabilities = (SID_AND_ATTRIBUTES * 1)(
                SID_AND_ATTRIBUTES(task_capability_sid.value, SE_GROUP_ENABLED)
            )
            security_capabilities = SECURITY_CAPABILITIES(
                appcontainer_sid.value,
                ctypes.cast(capabilities, ctypes.POINTER(SID_AND_ATTRIBUTES)),
                1,
                0,
            )
            attribute_list_size = ctypes.c_size_t()
            ctypes.set_last_error(0)
            if kernel32.InitializeProcThreadAttributeList(
                None,
                1,
                0,
                ctypes.byref(attribute_list_size),
            ) or ctypes.get_last_error() != ERROR_INSUFFICIENT_BUFFER:
                raise _fail("InitializeProcThreadAttributeList(size)")
            attribute_list_buffer = ctypes.create_string_buffer(attribute_list_size.value)
            startup.lpAttributeList = ctypes.cast(attribute_list_buffer, ctypes.c_void_p)
            if not kernel32.InitializeProcThreadAttributeList(
                startup.lpAttributeList,
                1,
                0,
                ctypes.byref(attribute_list_size),
            ):
                raise _fail("InitializeProcThreadAttributeList")
            attribute_list_initialized = True
            if not kernel32.UpdateProcThreadAttribute(
                startup.lpAttributeList,
                0,
                PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES,
                ctypes.byref(security_capabilities),
                ctypes.sizeof(security_capabilities),
                None,
                None,
            ):
                raise _fail("UpdateProcThreadAttribute")
            creation_flags |= EXTENDED_STARTUPINFO_PRESENT
        command_line = ctypes.create_unicode_buffer(subprocess.list2cmdline(command))
        if not advapi32.CreateProcessAsUserW(
            restricted_token,
            command[0],
            command_line,
            None,
            None,
            True,
            creation_flags,
            None,
            cwd,
            ctypes.byref(startup),
            ctypes.byref(process_info),
        ):
            raise _fail("CreateProcessAsUserW")
        in_job = wintypes.BOOL()
        if not kernel32.IsProcessInJob(process_info.hProcess, None, ctypes.byref(in_job)) or not in_job.value:
            kernel32.TerminateProcess(process_info.hProcess, 70)
            raise RuntimeError("restricted child did not inherit the task Job Object")
        if filesystem_restricted:
            if not advapi32.OpenProcessToken(process_info.hProcess, TOKEN_QUERY, ctypes.byref(child_token)):
                kernel32.TerminateProcess(process_info.hProcess, 70)
                raise _fail("OpenProcessToken(AppContainer child)")
            is_appcontainer = wintypes.DWORD()
            token_information_size = wintypes.DWORD()
            if not advapi32.GetTokenInformation(
                child_token,
                TOKEN_IS_APPCONTAINER,
                ctypes.byref(is_appcontainer),
                ctypes.sizeof(is_appcontainer),
                ctypes.byref(token_information_size),
            ) or is_appcontainer.value != 1:
                kernel32.TerminateProcess(process_info.hProcess, 70)
                raise RuntimeError("restricted child token is not an AppContainer")
            appcontainer_information_size = wintypes.DWORD()
            ctypes.set_last_error(0)
            if advapi32.GetTokenInformation(
                child_token,
                TOKEN_APPCONTAINER_SID,
                None,
                0,
                ctypes.byref(appcontainer_information_size),
            ) or ctypes.get_last_error() != ERROR_INSUFFICIENT_BUFFER:
                kernel32.TerminateProcess(process_info.hProcess, 70)
                raise _fail("GetTokenInformation(AppContainer SID size)")
            appcontainer_information_buffer = ctypes.create_string_buffer(appcontainer_information_size.value)
            if not advapi32.GetTokenInformation(
                child_token,
                TOKEN_APPCONTAINER_SID,
                appcontainer_information_buffer,
                appcontainer_information_size,
                ctypes.byref(appcontainer_information_size),
            ):
                kernel32.TerminateProcess(process_info.hProcess, 70)
                raise _fail("GetTokenInformation(AppContainer SID)")
            appcontainer_information = ctypes.cast(
                appcontainer_information_buffer,
                ctypes.POINTER(TOKEN_APPCONTAINER_INFORMATION),
            ).contents
            if not advapi32.EqualSid(appcontainer_information.TokenAppContainer, appcontainer_sid):
                kernel32.TerminateProcess(process_info.hProcess, 70)
                raise RuntimeError("restricted child AppContainer SID does not match the runtime boundary")
            capability_information_size = wintypes.DWORD()
            ctypes.set_last_error(0)
            if advapi32.GetTokenInformation(
                child_token,
                TOKEN_CAPABILITIES,
                None,
                0,
                ctypes.byref(capability_information_size),
            ) or ctypes.get_last_error() != ERROR_INSUFFICIENT_BUFFER:
                kernel32.TerminateProcess(process_info.hProcess, 70)
                raise _fail("GetTokenInformation(capabilities size)")
            capability_information = ctypes.create_string_buffer(capability_information_size.value)
            if not advapi32.GetTokenInformation(
                child_token,
                TOKEN_CAPABILITIES,
                capability_information,
                capability_information_size,
                ctypes.byref(capability_information_size),
            ):
                kernel32.TerminateProcess(process_info.hProcess, 70)
                raise _fail("GetTokenInformation(capabilities)")
            capability_count = ctypes.cast(
                capability_information,
                ctypes.POINTER(wintypes.DWORD),
            ).contents.value
            groups_offset = ctypes.sizeof(ctypes.c_void_p)
            task_capability_present = False
            for index in range(capability_count):
                capability = SID_AND_ATTRIBUTES.from_buffer(
                    capability_information,
                    groups_offset + index * ctypes.sizeof(SID_AND_ATTRIBUTES),
                )
                if (
                    capability.Attributes & SE_GROUP_ENABLED
                    and advapi32.EqualSid(capability.Sid, task_capability_sid)
                ):
                    task_capability_present = True
                    break
            if not task_capability_present:
                kernel32.TerminateProcess(process_info.hProcess, 70)
                raise RuntimeError("restricted child token is missing the task capability")
        attestation: dict[str, Any] = {
            "schemaVersion": 1,
            "taskId": task_id,
            "restrictedPrimaryToken": True,
            "maxPrivilegesDisabled": True,
            "authenticatedUsersSidDisabled": True,
            "createdSuspended": True,
            "jobInheritedBeforeResume": True,
            "filesystemRestrictedByDedicatedSidDacl": filesystem_restricted,
            "networkRestricted": filesystem_restricted,
        }
        if filesystem_restricted:
            assert runtime_sid is not None and task_sid is not None
            attestation["runtimeAppContainerSidDigest"] = _sid_binding_digest(
                "study.runtime-appcontainer-sid.v1",
                runtime_sid,
            )
            attestation["taskCapabilitySidDigest"] = _sid_binding_digest(
                "study.task-capability-sid.v1",
                task_sid,
            )
            attestation["appContainerToken"] = True
            attestation["taskCapabilityPresent"] = True
        attestation["mac"] = _sign(attestation_key, attestation)
        print(SANDBOX_ATTESTATION_PREFIX + json.dumps(attestation, sort_keys=True, separators=(",", ":")), file=sys.stderr, flush=True)
        if kernel32.ResumeThread(process_info.hThread) == 0xFFFFFFFF:
            kernel32.TerminateProcess(process_info.hProcess, 71)
            raise _fail("ResumeThread")
        if kernel32.WaitForSingleObject(process_info.hProcess, INFINITE) != WAIT_OBJECT_0:
            raise _fail("WaitForSingleObject")
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(process_info.hProcess, ctypes.byref(exit_code)):
            raise _fail("GetExitCodeProcess")
        if exit_code.value != 0:
            print(
                RESTRICTED_CHILD_EXIT_PREFIX
                + json.dumps(
                    {
                        "error_code": "RESTRICTED_CHILD_FAILED",
                        "message": f"Restricted worker exited with code {int(exit_code.value)}",
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                file=sys.stderr,
                flush=True,
            )
        return int(exit_code.value)
    finally:
        if attribute_list_initialized and attribute_list_buffer is not None:
            kernel32.DeleteProcThreadAttributeList(ctypes.cast(attribute_list_buffer, ctypes.c_void_p))
        for handle in (
            process_info.hThread,
            process_info.hProcess,
            child_token,
            restricted_membership_token,
            source_membership_token,
            restricted_token,
            source_token,
        ):
            if handle:
                kernel32.CloseHandle(handle)
        for sid in sandbox_sid_allocations:
            kernel32.LocalFree(sid)


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--cwd", required=True)
    parser.add_argument("--runtime-sid")
    parser.add_argument("--task-sid")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    arguments = parser.parse_args()
    command = list(arguments.command)
    if command and command[0] == "--":
        command = command[1:]
    start_line = sys.stdin.readline(512)
    if not start_line.startswith("START ") or not start_line.endswith("\n"):
        raise SystemExit("restricted launcher start handshake is invalid")
    try:
        key_text = start_line[6:].strip()
        key = base64.b64decode(key_text + "=" * (-len(key_text) % 4), altchars=b"-_", validate=True)
        if len(key) != 32 or not command or not os.path.isabs(command[0]) or not os.path.isabs(arguments.cwd):
            raise ValueError("invalid restricted launcher input")
        raise SystemExit(
            launch_restricted(
                command=command,
                cwd=arguments.cwd,
                task_id=arguments.task_id,
                attestation_key=key,
                runtime_sid=arguments.runtime_sid,
                task_sid=arguments.task_sid,
            )
        )
    except SystemExit:
        raise
    except Exception as error:
        print(
            ERROR_PREFIX + json.dumps(
                {"error_code": "WINDOWS_SANDBOX_LAUNCH_FAILED", "message": str(error)},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(72)


if __name__ == "__main__":
    main()
