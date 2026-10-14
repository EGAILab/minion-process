"""The real `HostOS` for a Windows host (ctypes, standard library only).

- **Mutex:** the named mutex `Global\\MinionProcessHostQueue` (B-1, K-16). One broker thread owns it for the
  broker's life. Access denied or a type conflict refuses; there is never a fallback to `Local\\`.
- **Process identity:** a process id plus its creation time from `GetProcessTimes`, so a reused id is not
  the same process (B-18, W-10).
- **Job objects:**
  - each workload is created suspended, assigned to a new named job object, then resumed with
    `NtResumeProcess`;
  - breakaway is not permitted, and no kill-on-close or other kill limit is ever set (K-16);
  - the job object's active-process count decides whether the workload ended (B-18).

  A named job object loses its name when its last handle closes, even while processes remain in it.
  Therefore the broker keeps a handle to every job object it creates. The runner also holds a handle to
  its own job and exits only after every other process in the job has exited, so the name stays valid
  while any work remains. After a broker restart, a job object that cannot be opened is **unknown**, never
  ended. The broker treats it as ended only when the runner's result file shows the runner drained the job
  (`broker._workload`).
- **Containers:** `docker ps --filter label=minion.job=<label>`. Any docker failure is unknown.
- **Memory:** `GlobalMemoryStatusEx` available physical memory, in exact bytes.
- **Publication:** `MoveFileExW` with `MOVEFILE_WRITE_THROUGH` and without `MOVEFILE_REPLACE_EXISTING`.
- **Volume:** `GetDriveTypeW` must be `DRIVE_FIXED`.
"""

from __future__ import annotations

import ctypes
import json
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

from .hostos import MutexResult, ProcessIdentity, Spawned, SpawnFailed

MUTEX_NAME = "Global\\MinionProcessHostQueue"
WAIT_OBJECT_0 = 0x00000000
WAIT_ABANDONED = 0x00000080
WAIT_TIMEOUT = 0x00000102
ERROR_ACCESS_DENIED = 5
ERROR_INVALID_HANDLE = 6
ERROR_FILE_EXISTS = 80
ERROR_ALREADY_EXISTS = 183
ERROR_FILE_NOT_FOUND = 2
STILL_ACTIVE = 259
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_SET_QUOTA = 0x0100
PROCESS_TERMINATE_NOT_USED = 0  # the broker never requests terminate rights
JOB_OBJECT_QUERY = 0x0004
JOB_OBJECT_ASSIGN_PROCESS = 0x0001
JOB_OBJECT_ALL_ACCESS = 0x1F001F
JOBOBJECT_BASIC_ACCOUNTING_INFORMATION_CLASS = 1
CREATE_SUSPENDED = 0x00000004
CREATE_NEW_PROCESS_GROUP = 0x00000200
MOVEFILE_WRITE_THROUGH = 0x8
DRIVE_FIXED = 3


class _FILETIME(ctypes.Structure):
    _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]


class _ACCOUNTING(ctypes.Structure):
    _fields_ = [
        ("TotalUserTime", ctypes.c_longlong),
        ("TotalKernelTime", ctypes.c_longlong),
        ("ThisPeriodTotalUserTime", ctypes.c_longlong),
        ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
        ("TotalPageFaultCount", wintypes.DWORD),
        ("TotalProcesses", wintypes.DWORD),
        ("ActiveProcesses", wintypes.DWORD),
        ("TotalTerminatedProcesses", wintypes.DWORD),
    ]


class _TIMEOFDAY(ctypes.Structure):
    _fields_ = [
        ("BootTime", ctypes.c_longlong),
        ("CurrentTime", ctypes.c_longlong),
        ("TimeZoneBias", ctypes.c_longlong),
        ("TimeZoneId", ctypes.c_ulong),
        ("Reserved", ctypes.c_ulong),
        ("BootTimeBias", ctypes.c_ulonglong),
        ("SleepTimeBias", ctypes.c_ulonglong),
    ]


class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _k32() -> ctypes.WinDLL:
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = wintypes.HANDLE
    k32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k32.WaitForSingleObject.restype = wintypes.DWORD
    k32.ReleaseMutex.argtypes = [wintypes.HANDLE]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(_FILETIME)] * 4
    k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    k32.OpenJobObjectW.restype = wintypes.HANDLE
    k32.OpenJobObjectW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    k32.QueryInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_void_p,
    ]
    k32.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(_MEMORYSTATUSEX)]
    k32.MoveFileExW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
    k32.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
    k32.GetDriveTypeW.restype = wintypes.UINT
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    return k32


def _filetime(ft: _FILETIME) -> int:
    return int((ft.high << 32) | ft.low)


class WindowsHostOS:
    def __init__(self, docker: str = "docker", herdr: str = "herdr", mutex_name: str = MUTEX_NAME) -> None:
        if sys.platform != "win32":  # pragma: no cover - other platforms
            raise OSError("WindowsHostOS needs Windows")
        self.mutex_name = mutex_name
        self.k32 = _k32()
        self.ntdll = ctypes.WinDLL("ntdll")
        self.docker = docker
        self.herdr = herdr
        self.mutex: int | None = None
        self.jobs: dict[str, int] = {}  # job-object name -> handle kept open by this broker

    # -- mutex ------------------------------------------------------------------------------------------
    def acquire_broker_mutex(self) -> MutexResult:
        handle = self.k32.CreateMutexW(None, False, self.mutex_name)
        if not handle:
            error = ctypes.get_last_error()
            return MutexResult(False, False, f"CreateMutexW failed with error {error}")
        result = self.k32.WaitForSingleObject(handle, 0)
        if result in (WAIT_OBJECT_0, WAIT_ABANDONED):
            self.mutex = handle
            return MutexResult(True, result == WAIT_ABANDONED)
        self.k32.CloseHandle(handle)
        if result == WAIT_TIMEOUT:
            return MutexResult(False, False)
        return MutexResult(False, False, f"WaitForSingleObject returned {result}")

    def release_broker_mutex(self) -> None:
        if self.mutex:
            self.k32.ReleaseMutex(self.mutex)
            self.k32.CloseHandle(self.mutex)
            self.mutex = None

    # -- processes --------------------------------------------------------------------------------------
    def _times(self, handle: int) -> int | None:
        created, exited, kernel, user = _FILETIME(), _FILETIME(), _FILETIME(), _FILETIME()
        if not self.k32.GetProcessTimes(
            handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel), ctypes.byref(user)
        ):
            return None
        return _filetime(created)

    def self_identity(self) -> ProcessIdentity:
        import os

        start = self._times(self.k32.GetCurrentProcess())
        return ProcessIdentity(os.getpid(), start or 0)

    def process_alive(self, ident: ProcessIdentity) -> bool | None:
        handle = self.k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, ident.pid)
        if not handle:
            error = ctypes.get_last_error()
            return False if error == 87 else None  # ERROR_INVALID_PARAMETER: no such process id
        try:
            start = self._times(handle)
            if start is None:
                return None
            if start != ident.start:
                return False  # the id was reused by another process
            code = wintypes.DWORD()
            if not self.k32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return None
            return code.value == STILL_ACTIVE
        finally:
            self.k32.CloseHandle(handle)

    def spawn(self, argv: list[str], env: dict[str, str], cwd: Path, log: Path, group: str) -> Spawned:
        job = self.k32.CreateJobObjectW(None, f"Local\\{group}")
        if not job:
            raise OSError(f"CreateJobObjectW failed: {ctypes.get_last_error()}")
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            self.k32.CloseHandle(job)
            raise OSError(f"job object {group} already exists")
        self.jobs[group] = job  # no limits set: no kill-on-close, no breakaway permission (K-16)
        process = subprocess.Popen(
            argv,
            cwd=str(cwd),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_SUSPENDED | CREATE_NEW_PROCESS_GROUP,
        )
        handle = int(process._handle)  # type: ignore[attr-defined]
        ident = ProcessIdentity(process.pid, self._times(handle) or 0)
        if not self.k32.AssignProcessToJobObject(job, handle):
            raise SpawnFailed(f"AssignProcessToJobObject failed: {ctypes.get_last_error()}", ident)
        status = self.ntdll.NtResumeProcess(handle)
        if status != 0:
            raise SpawnFailed(f"NtResumeProcess failed: {status:#x}", ident)
        return Spawned(ident, group)

    def _job(self, group: str) -> int | None:
        if group in self.jobs:
            return self.jobs[group]
        handle = self.k32.OpenJobObjectW(JOB_OBJECT_QUERY, False, f"Local\\{group}")
        if handle:
            self.jobs[group] = int(handle)
            return int(handle)
        return None

    def group_active(self, group: str) -> bool | None:
        if not group:
            return None
        handle = self._job(group)
        if handle is None:
            return None  # not openable: its name may have gone while processes remain; unknown, never ended
        info = _ACCOUNTING()
        if not self.k32.QueryInformationJobObject(
            handle,
            JOBOBJECT_BASIC_ACCOUNTING_INFORMATION_CLASS,
            ctypes.byref(info),
            ctypes.sizeof(info),
            None,
        ):
            return None
        return bool(info.ActiveProcesses > 0)

    def group_exists(self, group: str) -> bool | None:
        if not group:
            return None
        if group in self.jobs:
            return True
        handle = self.k32.OpenJobObjectW(JOB_OBJECT_QUERY, False, f"Local\\{group}")
        if handle:
            self.jobs[group] = handle
            return True
        return False if ctypes.get_last_error() == ERROR_FILE_NOT_FOUND else None

    def containers_running(self, label: str) -> bool | None:
        if not label:
            return None
        try:
            result = subprocess.run(
                [self.docker, "ps", "--quiet", "--filter", f"label=minion.job={label}"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            return None
        return bool(result.stdout.strip())

    # -- memory, clock, volume --------------------------------------------------------------------------
    def free_memory_bytes(self) -> int | None:
        status = _MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(status)
        if not self.k32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
        return int(status.ullAvailPhys)

    def monotonic(self) -> float:
        return time.monotonic()

    def boot_id(self) -> str | None:
        """The system boot time from `NtQuerySystemInformation(SystemTimeOfDayInformation)`, exact and
        stable for the whole boot."""
        info = _TIMEOFDAY()
        status = self.ntdll.NtQuerySystemInformation(3, ctypes.byref(info), ctypes.sizeof(info), None)
        if status != 0:
            return None
        return str(info.BootTime)

    def wall_time(self) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def is_local_fixed_volume(self, path: Path) -> bool | None:
        anchor = Path(path).anchor
        if not anchor:
            return None
        return bool(self.k32.GetDriveTypeW(anchor) == DRIVE_FIXED)

    # -- publication ------------------------------------------------------------------------------------
    def publish(self, temp: Path, final: Path) -> None:
        if not self.k32.MoveFileExW(str(temp), str(final), MOVEFILE_WRITE_THROUGH):
            error = ctypes.get_last_error()
            if error in (ERROR_FILE_EXISTS, ERROR_ALREADY_EXISTS):
                raise FileExistsError(str(final))
            raise OSError(f"MoveFileExW failed with error {error}")

    # -- herdr ------------------------------------------------------------------------------------------
    def pane(self, pane: str) -> dict[str, object] | None:
        try:
            result = subprocess.run(
                [self.herdr, "agent", "get", pane], capture_output=True, text=True, timeout=15, check=False
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            return None
        try:
            agent = json.loads(result.stdout)["result"]["agent"]
        except (ValueError, KeyError, TypeError):
            return None
        return agent if isinstance(agent, dict) else None
