"""Keep Windows GUI interpreter descendants owned by their simulator session."""
import ctypes
import os
from ctypes import wintypes
from typing import Optional
from uuid import uuid4


class _BasicLimits(ctypes.Structure):
    _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                ("flags", wintypes.DWORD), ("min_working", ctypes.c_size_t),
                ("max_working", ctypes.c_size_t), ("active_limit", wintypes.DWORD),
                ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
                ("scheduling", wintypes.DWORD)]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [("basic", _BasicLimits), ("io", ctypes.c_uint64 * 6),
                ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]


def _kernel():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.OpenJobObjectW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.OpenJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                              ctypes.c_void_p, wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    return kernel


class SessionProcesses:
    """A parent-held job handle closes every joined GUI process on parent exit."""

    def __init__(self) -> None:
        self.name: Optional[str] = None
        self.handle = None
        if os.name == "nt":
            self.name = "Local\\KneeSpaSimulator-" + str(uuid4())
            kernel = _kernel()
            self.handle = kernel.CreateJobObjectW(None, self.name)
            if not self.handle:
                raise ctypes.WinError(ctypes.get_last_error())
            limits = _ExtendedLimits()
            limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits),
                                                  ctypes.sizeof(limits)):
                self.close()
                raise ctypes.WinError(ctypes.get_last_error())

    def environment(self) -> dict:
        env = dict(os.environ, PYTHONUNBUFFERED="1")
        if self.name:
            env["KNEESPA_SIM_JOB"] = self.name
        return env

    def close(self) -> None:
        if self.handle:
            _kernel().CloseHandle(self.handle)
            self.handle = None


def join_session_job() -> None:
    """Join from the actual Python process, including when a venv shim launched it."""
    name = os.environ.pop("KNEESPA_SIM_JOB", None)
    if os.name != "nt" or not name:
        return
    kernel = _kernel()
    handle = kernel.OpenJobObjectW(0x0001, False, name)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if not kernel.AssignProcessToJobObject(handle, kernel.GetCurrentProcess()):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel.CloseHandle(handle)
