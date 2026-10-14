"""The real Windows adapter, exercised on the Windows host (K-16, B-1, B-18, K-35; witnesses W-5, W-6, W-10,
W-59, W-60). Skipped on other platforms. Every child process these tests start exits on its own; nothing
is killed, signalled or stopped."""

from __future__ import annotations

import ctypes
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows host adapter")

if sys.platform == "win32":
    from minion_process.hostqueue import runner, winos
    from minion_process.hostqueue.hostos import ProcessIdentity


def name(prefix: str = "Local") -> str:
    return f"{prefix}\\MinionProcessTest-{secrets.token_hex(6)}"


def host(**kw: Any) -> Any:
    return winos.WindowsHostOS(mutex_name=kw.pop("mutex_name", name()), **kw)


def hold_mutex_in_child(mutex: str, seconds: float, release: bool) -> subprocess.Popen[bytes]:
    code = (
        "import ctypes,sys,time\n"
        "k=ctypes.WinDLL('kernel32')\n"
        "k.CreateMutexW.restype=ctypes.c_void_p\n"
        f"h=ctypes.c_void_p(k.CreateMutexW(None,False,{mutex!r}))\n"
        "k.WaitForSingleObject(h,0xFFFFFFFF)\n"
        "print('held',flush=True)\n"
        f"time.sleep({seconds})\n" + ("k.ReleaseMutex(h)\n" if release else "")
    )
    child = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE)
    assert child.stdout is not None and child.stdout.readline().strip() == b"held"
    return child


# -- mutex -----------------------------------------------------------------------------------------------


def test_w5_mutex_single_instance_across_processes() -> None:
    mutex = name()
    child = hold_mutex_in_child(mutex, 1.5, release=True)
    h = host(mutex_name=mutex)
    result = h.acquire_broker_mutex()
    assert not result.acquired and result.error is None
    child.wait()
    result = h.acquire_broker_mutex()
    assert result.acquired and not result.abandoned
    h.release_broker_mutex()
    h.release_broker_mutex()  # releasing twice is harmless


def test_w6_w59_abandonment_signal_only_while_a_handle_survives() -> None:
    mutex = name()
    k32 = ctypes.WinDLL("kernel32")
    k32.CreateMutexW.restype = ctypes.c_void_p
    keep = k32.CreateMutexW(None, False, mutex)  # this test keeps a handle open, so the object survives
    hold_mutex_in_child(mutex, 0.1, release=False).wait()
    h = host(mutex_name=mutex)
    result = h.acquire_broker_mutex()
    assert result.acquired and result.abandoned  # W-6
    h.release_broker_mutex()
    k32.CloseHandle(ctypes.c_void_p(keep))
    other = name()
    hold_mutex_in_child(other, 0.1, release=False).wait()  # no surviving handle: the object is destroyed
    h2 = host(mutex_name=other)
    result = h2.acquire_broker_mutex()
    assert result.acquired and not result.abandoned  # W-59: no signal, replay runs anyway
    h2.release_broker_mutex()


def test_w60_type_conflict_refuses_without_fallback() -> None:
    clash = name()
    k32 = ctypes.WinDLL("kernel32")
    k32.CreateEventW.restype = ctypes.c_void_p
    event = k32.CreateEventW(None, True, False, clash)
    try:
        result = host(mutex_name=clash).acquire_broker_mutex()
        assert not result.acquired and result.error and "CreateMutexW failed" in result.error
    finally:
        k32.CloseHandle(ctypes.c_void_p(event))


def test_unexpected_wait_result_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    h = host()
    monkeypatch.setattr(h.k32, "WaitForSingleObject", lambda handle, ms: 0xFFFFFFFF)
    result = h.acquire_broker_mutex()
    assert not result.acquired and "WaitForSingleObject returned" in str(result.error)


# -- processes -------------------------------------------------------------------------------------------


def test_w10_process_identity() -> None:
    h = host()
    me = h.self_identity()
    assert me.pid == os.getpid() and me.start > 0
    assert h.process_alive(me) is True
    assert h.process_alive(ProcessIdentity(me.pid, me.start + 1)) is False  # a reused id is not this process
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    assert h.process_alive(ProcessIdentity(child.pid, 1)) in (False, None)
    assert h.process_alive(ProcessIdentity(0x7FFFFFF0, 1)) is False  # no such process id


def test_process_times_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    h = host()
    monkeypatch.setattr(h.k32, "GetProcessTimes", lambda *a: 0)
    assert h._times(h.k32.GetCurrentProcess()) is None


def test_process_alive_unknown_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    h = host()
    me = h.self_identity()
    monkeypatch.setattr(h.k32, "GetExitCodeProcess", lambda handle, code: 0)
    assert h.process_alive(me) is None
    monkeypatch.setattr(h, "_times", lambda handle: None)
    assert h.process_alive(me) is None
    monkeypatch.setattr(h.k32, "OpenProcess", lambda access, inherit, pid: 0)
    monkeypatch.setattr(winos.ctypes, "get_last_error", lambda: winos.ERROR_ACCESS_DENIED)
    assert h.process_alive(me) is None


# -- job objects -----------------------------------------------------------------------------------------


def test_spawn_tracks_the_workload_and_its_children(tmp_path: Path) -> None:
    h = host()
    group = f"MinionProcessTest-{secrets.token_hex(6)}"
    script = (
        "import subprocess,sys,time; "
        "subprocess.Popen([sys.executable,'-c','import time; time.sleep(2)']); time.sleep(0.5)"
    )
    spawned = h.spawn([sys.executable, "-c", script], dict(os.environ), tmp_path, tmp_path / "log", group)
    assert spawned.group == group and h.group_exists(group) is True
    assert h.group_active(group) is True
    deadline = time.monotonic() + 10
    while h.group_active(group) and time.monotonic() < deadline:
        time.sleep(0.2)
    assert h.group_active(group) is False  # the grandchild outlived the runner and was still tracked
    other = host()
    assert other.group_active(group) is False  # opened by name, then queried
    third = host()
    assert third.group_exists(group) is True


def test_runner_holds_its_job_and_drains(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    h = host()
    group = f"MinionProcessTest-{secrets.token_hex(6)}"
    script = (
        "import subprocess,sys,time; "
        "subprocess.Popen([sys.executable,'-c','import time; time.sleep(1.5)']); time.sleep(1.5)"
    )
    h.spawn([sys.executable, "-c", script], dict(os.environ), tmp_path, tmp_path / "log", group)
    time.sleep(0.3)  # both processes are in the job: the drain must wait for one of them to exit
    monkeypatch.setenv("MINION_JOB_GROUP", group)
    started = time.monotonic()
    assert runner._hold_and_drain() is True  # this test process is outside the job: the count reaches 0
    assert time.monotonic() - started >= 0.5


def test_job_object_failures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    h = host()
    assert h.group_active("") is None and h.group_exists("") is None
    missing = f"MinionProcessTest-{secrets.token_hex(6)}"
    assert h.group_active(missing) is None  # unknown, never ended
    assert h.group_exists(missing) is False
    group = f"MinionProcessTest-{secrets.token_hex(6)}"
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateJobObjectW.restype = ctypes.c_void_p
    existing = k32.CreateJobObjectW(None, f"Local\\{group}")
    with pytest.raises(OSError, match="already exists"):
        h.spawn([sys.executable, "-c", "pass"], dict(os.environ), tmp_path, tmp_path / "log", group)
    k32.CloseHandle(ctypes.c_void_p(existing))

    class FakeProcess:
        pid = os.getpid()
        _handle = int(ctypes.WinDLL("kernel32").GetCurrentProcess())

    monkeypatch.setattr(winos.subprocess, "Popen", lambda *a, **k: FakeProcess())
    monkeypatch.setattr(h.k32, "AssignProcessToJobObject", lambda job, process: 0)
    with pytest.raises(OSError, match="AssignProcessToJobObject") as failed:
        h.spawn(["x"], {}, tmp_path, tmp_path / "log", f"MinionProcessTest-{secrets.token_hex(6)}")
    assert failed.value.stray is not None and failed.value.stray.pid == os.getpid()  # R002: identity kept
    monkeypatch.setattr(
        h.k32, "AssignProcessToJobObject", lambda job, process: 1
    )  # pretend; never assigns this process
    monkeypatch.setattr(h.ntdll, "NtResumeProcess", lambda process: 0xC0000001)
    with pytest.raises(OSError, match="NtResumeProcess"):
        h.spawn(["x"], {}, tmp_path, tmp_path / "log", f"MinionProcessTest-{secrets.token_hex(6)}")
    monkeypatch.setattr(h.k32, "CreateJobObjectW", lambda attrs, job_name: 0)
    with pytest.raises(OSError, match="CreateJobObjectW"):
        h.spawn(["x"], {}, tmp_path, tmp_path / "log", "any")


def test_group_queries_unknown(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    h = host()
    group = f"MinionProcessTest-{secrets.token_hex(6)}"
    h.spawn([sys.executable, "-c", "pass"], dict(os.environ), tmp_path, tmp_path / "log", group)
    monkeypatch.setattr(h.k32, "QueryInformationJobObject", lambda *a: 0)
    assert h.group_active(group) is None
    other = host()
    monkeypatch.setattr(other.k32, "OpenJobObjectW", lambda access, inherit, job_name: 0)
    monkeypatch.setattr(winos.ctypes, "get_last_error", lambda: winos.ERROR_ACCESS_DENIED)
    assert other.group_exists(group) is None


# -- containers, herdr, memory, volume, publication ------------------------------------------------------


def _shim(tmp_path: Path, name_: str, output: str, code: int = 0) -> str:
    path = tmp_path / f"{name_}.cmd"
    lines = ["@echo off"] + ([f"echo {output}"] if output else []) + [f"exit /b {code}"]
    path.write_text("\r\n".join(lines) + "\r\n", encoding="ascii")
    return str(path)


def test_containers(tmp_path: Path) -> None:
    assert host(docker=_shim(tmp_path, "d1", "abc123")).containers_running("lbl") is True
    assert host(docker=_shim(tmp_path, "d2", "")).containers_running("lbl") is False
    assert host(docker=_shim(tmp_path, "d3", "", 1)).containers_running("lbl") is None
    assert host(docker=str(tmp_path / "no-docker.exe")).containers_running("lbl") is None
    assert host().containers_running("") is None


def test_herdr_pane(tmp_path: Path) -> None:
    payload = '{"result":{"agent":{"agent":"claude","agent_session":{"value":"s"}}}}'
    shim = tmp_path / "h.cmd"
    shim.write_text("@echo off\r\necho " + payload.replace('"', '"') + "\r\n", encoding="ascii")
    assert host(herdr=str(shim)).pane("w1:p1") == {"agent": "claude", "agent_session": {"value": "s"}}
    assert host(herdr=_shim(tmp_path, "h2", "not-json")).pane("w1:p1") is None
    assert host(herdr=_shim(tmp_path, "h3", "", 1)).pane("w1:p1") is None
    assert host(herdr=str(tmp_path / "no-herdr.exe")).pane("w1:p1") is None
    assert host(herdr=_shim(tmp_path, "h4", '{"result":{"agent":[1]}}')).pane("w1:p1") is None


def test_r008_boot_id(monkeypatch: pytest.MonkeyPatch) -> None:
    h = host()
    first = h.boot_id()
    assert first is not None and first == h.boot_id()  # stable within one boot
    monkeypatch.setattr(h.ntdll, "NtQuerySystemInformation", lambda *a: 0xC0000001)
    assert h.boot_id() is None


class _FakeK32:
    """Stands in for kernel32 inside the runner's drain, so a failed open or query is observable."""

    def __init__(self, open_handle: int, query_ok: bool) -> None:
        self.open_handle = open_handle
        self.query_ok = query_ok

        class _F:
            def __init__(self, fn: Any) -> None:
                self.fn = fn
                self.argtypes: Any = None
                self.restype: Any = None

            def __call__(self, *a: Any) -> Any:
                return self.fn(*a)

        self.OpenJobObjectW = _F(lambda *a: self.open_handle)
        self.QueryInformationJobObject = _F(lambda *a: 1 if self.query_ok else 0)


@pytest.mark.parametrize(("open_handle", "query_ok"), [(0, True), (7, False)])
def test_r002_runner_claims_no_drain_on_failed_open_or_query(
    monkeypatch: pytest.MonkeyPatch, open_handle: int, query_ok: bool
) -> None:
    monkeypatch.setenv("MINION_JOB_GROUP", "any-group")
    monkeypatch.setattr(ctypes, "WinDLL", lambda *a, **k: _FakeK32(open_handle, query_ok))
    assert runner._hold_and_drain() is False


def test_memory_clock_volume(monkeypatch: pytest.MonkeyPatch) -> None:
    h = host()
    assert (h.free_memory_bytes() or 0) > 0
    assert h.monotonic() > 0 and h.wall_time().endswith("Z")
    assert h.is_local_fixed_volume(Path(os.getcwd())) is True
    assert h.is_local_fixed_volume(Path("relative")) is None
    monkeypatch.setattr(h.k32, "GlobalMemoryStatusEx", lambda status: 0)
    assert h.free_memory_bytes() is None


def test_k35_publication_without_replace(tmp_path: Path) -> None:
    h = host()
    (tmp_path / "t1").write_text("one")
    h.publish(tmp_path / "t1", tmp_path / "final")
    (tmp_path / "t2").write_text("two")
    with pytest.raises(FileExistsError):
        h.publish(tmp_path / "t2", tmp_path / "final")
    assert (tmp_path / "final").read_text() == "one"
    with pytest.raises(OSError, match="MoveFileExW failed"):
        h.publish(tmp_path / "missing", tmp_path / "other")
