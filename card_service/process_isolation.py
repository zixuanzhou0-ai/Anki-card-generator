from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from typing import Any


JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION = 0x00000400
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
JOB_OBJECT_BASIC_UI_RESTRICTIONS = 4
JOB_OBJECT_UILIMIT_SAFE_HEADLESS = 0x000000FF


class ProcessIsolationError(RuntimeError):
    pass


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class _BasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _ExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _BasicUiRestrictions(ctypes.Structure):
    _fields_ = [("UIRestrictionsClass", wintypes.DWORD)]


class TaskOwnedProcessGroup:
    """Owns a Windows Job Object; closing it terminates all task descendants."""

    def __init__(self, *, memory_limit_bytes: int, active_process_limit: int) -> None:
        self._handle: int | None = None
        self.memory_limit_bytes = max(64 * 1024 * 1024, int(memory_limit_bytes))
        self.active_process_limit = max(1, int(active_process_limit))
        if os.name != "nt":
            return
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise ProcessIsolationError(f"CreateJobObjectW failed: {ctypes.get_last_error()}")
        information = _ExtendedLimitInformation()
        information.BasicLimitInformation.LimitFlags = (
            JOB_OBJECT_LIMIT_ACTIVE_PROCESS
            | JOB_OBJECT_LIMIT_JOB_MEMORY
            | JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            | JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION
        )
        information.BasicLimitInformation.ActiveProcessLimit = self.active_process_limit
        information.JobMemoryLimit = self.memory_limit_bytes
        if not kernel32.SetInformationJobObject(
            handle,
            JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(information),
            ctypes.sizeof(information),
        ):
            error = ctypes.get_last_error()
            kernel32.CloseHandle(handle)
            raise ProcessIsolationError(f"SetInformationJobObject failed: {error}")
        ui_restrictions = _BasicUiRestrictions(JOB_OBJECT_UILIMIT_SAFE_HEADLESS)
        if not kernel32.SetInformationJobObject(
            handle,
            JOB_OBJECT_BASIC_UI_RESTRICTIONS,
            ctypes.byref(ui_restrictions),
            ctypes.sizeof(ui_restrictions),
        ):
            error = ctypes.get_last_error()
            kernel32.CloseHandle(handle)
            raise ProcessIsolationError(f"SetInformationJobObject UI restrictions failed: {error}")
        self._handle = int(handle)

    @property
    def enabled(self) -> bool:
        return self._handle is not None

    def assign(self, process: Any) -> None:
        if os.name != "nt":
            return
        if self._handle is None:
            raise ProcessIsolationError("Task Job Object is unavailable")
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        process_handle = int(getattr(process, "_handle", 0))
        if not process_handle or not kernel32.AssignProcessToJobObject(self._handle, process_handle):
            raise ProcessIsolationError(f"AssignProcessToJobObject failed: {ctypes.get_last_error()}")

    def close(self) -> None:
        if self._handle is None:
            return
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle, self._handle = self._handle, None
        if not kernel32.CloseHandle(handle):
            raise ProcessIsolationError(f"CloseHandle failed: {ctypes.get_last_error()}")

    def __enter__(self) -> "TaskOwnedProcessGroup":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
