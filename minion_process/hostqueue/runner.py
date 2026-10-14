"""The per-job runner: `python -m minion_process.hostqueue.runner <job-dir>`.

The broker starts the runner inside the job's tracking group. The runner reads `<job-dir>/input`, a framed
record with `argv`, `cwd` and `log`, and runs the launcher with the environment it inherited from the
broker. The launcher's standard output and standard error go to the log. When the launcher exits, the
runner appends the last line `GATE-END <exit code>`, then writes `<job-dir>/result` atomically. The runner
never signals, stops or kills anything (B-13). Whatever the runner reports, the broker still proves the
workload ended (B-18).
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from . import fsops
from .framing import decode_single, encode


def _hold_and_drain() -> bool:
    """On Windows, hold a handle to this process's own job object, then wait until this runner is the only
    live process left in it. Returns True only when a successful accounting query observed that state. A
    missing job, a failed open or a failed query returns False, and the result then claims no drain
    (PROC-KIT-P3B-R002). The broker accepts the result-file shortcut only with `drained: true`."""
    if sys.platform != "win32":  # pragma: no cover - other platforms have no job objects
        return False
    import ctypes
    from ctypes import wintypes

    from .winos import _ACCOUNTING

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.QueryInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_void_p,
    ]
    k32.OpenJobObjectW.restype = wintypes.HANDLE
    k32.OpenJobObjectW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    group = os.environ.get("MINION_JOB_GROUP", "")
    if not group:
        return False
    handle = k32.OpenJobObjectW(0x0004, False, f"Local\\{group}")
    if not handle:
        return False
    _hold_and_drain.handle = handle  # type: ignore[attr-defined]  # kept open until the process exits
    info = _ACCOUNTING()
    while True:
        if not k32.QueryInformationJobObject(handle, 1, ctypes.byref(info), ctypes.sizeof(info), None):
            return False
        if info.ActiveProcesses <= 1:
            return True
        time.sleep(1.0)


def run(job_dir: Path) -> int:
    spec = decode_single((job_dir / "input").read_bytes())
    log = Path(spec["log"])
    roots = [Path(r) for r in spec["roots"]]
    fsops.mkdir(roots, log.parent)
    with fsops.open_append(roots, log) as out:  # type: ignore[attr-defined]
        try:
            code = subprocess.run(
                spec["argv"], cwd=spec["cwd"], stdout=out, stderr=subprocess.STDOUT, check=False
            ).returncode
        except OSError as exc:
            out.write(f"launcher failed to start: {exc}\n".encode())
            code = 127
        out.flush()
        drained = _hold_and_drain()
        out.write(f"GATE-END {code}\n".encode())
        out.flush()
        os.fsync(out.fileno())
    temp = job_dir / f".tmp-runner-{os.getpid()}"
    fsops.write_replace(
        [job_dir.parent],
        temp,
        job_dir / "result",
        encode({"exit": code, "gate_end": _gate_end(log), "drained": drained}),
    )
    return code


def _gate_end(log: Path) -> int | None:
    """The code on the log's last `GATE-END` line, so the broker checks the log and the exit agree."""
    try:
        lines = log.read_bytes().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        if line.startswith("GATE-END "):
            try:
                return int(line.split()[1])
            except (IndexError, ValueError):
                return None
    return None


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: python -m minion_process.hostqueue.runner <job-dir>", file=sys.stderr)
        return 64
    return run(Path(argv[0]))


if __name__ == "__main__":  # pragma: no cover - entry point; `main` is tested directly
    raise SystemExit(main(sys.argv[1:]))
