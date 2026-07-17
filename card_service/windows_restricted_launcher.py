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


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


class SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]


def _canonical_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sign(key: bytes, value: dict[str, Any]) -> str:
    unsigned = {name: child for name, child in value.items() if name != "mac"}
    return base64.urlsafe_b64encode(hmac.new(key, _canonical_bytes(unsigned), hashlib.sha256).digest()).decode("ascii").rstrip("=")


def _fail(api: str) -> OSError:
    return OSError(ctypes.get_last_error(), f"{api} failed")


def launch_restricted(*, command: list[str], cwd: str, task_id: str, attestation_key: bytes) -> int:
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
    advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
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
        ctypes.POINTER(STARTUPINFOW),
        ctypes.POINTER(PROCESS_INFORMATION),
    ]
    advapi32.CreateProcessAsUserW.restype = wintypes.BOOL

    source_token = wintypes.HANDLE()
    restricted_token = wintypes.HANDLE()
    source_membership_token = wintypes.HANDLE()
    restricted_membership_token = wintypes.HANDLE()
    process_info = PROCESS_INFORMATION()
    disabled_sid_buffer = ctypes.create_string_buffer(SECURITY_MAX_SID_SIZE)
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
        startup = STARTUPINFOW()
        startup.cb = ctypes.sizeof(STARTUPINFOW)
        startup.dwFlags = STARTF_USESTDHANDLES
        startup.hStdInput = kernel32.GetStdHandle(STD_INPUT_HANDLE)
        startup.hStdOutput = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
        startup.hStdError = kernel32.GetStdHandle(STD_ERROR_HANDLE)
        for handle in (startup.hStdInput, startup.hStdOutput, startup.hStdError):
            if not handle or not kernel32.SetHandleInformation(handle, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT):
                raise _fail("SetHandleInformation")
        command_line = ctypes.create_unicode_buffer(subprocess.list2cmdline(command))
        if not advapi32.CreateProcessAsUserW(
            restricted_token,
            command[0],
            command_line,
            None,
            None,
            True,
            CREATE_SUSPENDED | CREATE_NO_WINDOW,
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
        attestation: dict[str, Any] = {
            "schemaVersion": 1,
            "taskId": task_id,
            "restrictedPrimaryToken": True,
            "maxPrivilegesDisabled": True,
            "authenticatedUsersSidDisabled": True,
            "createdSuspended": True,
            "jobInheritedBeforeResume": True,
            "filesystemRestrictedByDedicatedSidDacl": False,
            "networkRestricted": False,
        }
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
        for handle in (
            process_info.hThread,
            process_info.hProcess,
            restricted_membership_token,
            source_membership_token,
            restricted_token,
            source_token,
        ):
            if handle:
                kernel32.CloseHandle(handle)


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--cwd", required=True)
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
        raise SystemExit(launch_restricted(command=command, cwd=arguments.cwd, task_id=arguments.task_id, attestation_key=key))
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
