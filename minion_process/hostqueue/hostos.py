"""The operating-system seam of the host queue.

Everything the broker and the runner need from the host goes through `HostOS`, so the scheduling, recovery
and reconciliation rules are tested against a deterministic fake (`tests/hostqueue_fake.py`). The real
implementation for the Owner's host is `winos.WindowsHostOS`.

Every inspection returns `True`, `False` or `None`. `None` means the inspection itself failed (access
denied, a tool error, an unreadable answer), and callers treat it as unknown. Unknown is never absence
(K-36).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class ProcessIdentity:
    """A process is its id plus its start time, so a reused id is never mistaken for it (B-18, W-10)."""

    pid: int
    start: int  # OS start time in the OS's own unit (100-ns ticks on Windows)


@dataclass(frozen=True)
class MutexResult:
    acquired: bool
    abandoned: bool  # the previous holder ended without releasing; replay runs either way (K-16)
    error: str | None = None  # access denied or a type conflict: refuse, never fall back to Local\ (K-16)


class SpawnFailed(OSError):
    """`spawn` failed. `stray` is the identity of a process it created before failing (for example, one
    left suspended outside its job object after a failed assignment), so the broker keeps it uncertain
    and never assumes it ended. The broker never kills it."""

    def __init__(self, message: str, stray: ProcessIdentity | None = None) -> None:
        super().__init__(message)
        self.stray = stray


@dataclass(frozen=True)
class Spawned:
    """A workload started by `HostOS.spawn`: the runner process and the OS group that tracks it."""

    runner: ProcessIdentity
    group: str  # the job-object name (Windows) that holds the runner and every descendant


class HostOS(Protocol):
    def acquire_broker_mutex(self) -> MutexResult: ...

    def release_broker_mutex(self) -> None: ...

    def self_identity(self) -> ProcessIdentity: ...

    def process_alive(self, ident: ProcessIdentity) -> bool | None: ...

    def spawn(self, argv: list[str], env: dict[str, str], cwd: Path, log: Path, group: str) -> Spawned:
        """Create the process suspended, assign it to a new tracking group named `group` with no kill
        limit and no breakaway, then resume it (K-16). Raises `OSError` when any step fails; the caller
        treats a failure after group creation as uncertain (K-11)."""
        ...

    def group_active(self, group: str) -> bool | None:
        """Does the tracking group still contain a live process?"""
        ...

    def group_exists(self, group: str) -> bool | None: ...

    def containers_running(self, label: str) -> bool | None:
        """Is any container with label `minion.job=<label>` running?"""
        ...

    def free_memory_bytes(self) -> int | None: ...

    def monotonic(self) -> float: ...

    def boot_id(self) -> str | None:
        """An identifier of the current boot, so a monotonic deadline is compared only within its own
        boot (R008). None when the boot cannot be identified; callers then treat deadlines as expired."""
        ...

    def wall_time(self) -> str: ...

    def is_local_fixed_volume(self, path: Path) -> bool | None: ...

    def publish(self, temp: Path, final: Path) -> None:
        """Rename `temp` to `final` without replacing an existing `final`, with write-through. Raises
        `FileExistsError` if `final` exists (K-35). A rename may publish before the call returns (N001);
        callers observe the final name, never infer from the return alone."""
        ...

    def pane(self, pane: str) -> dict[str, object] | None:
        """`herdr agent get <pane>`'s agent object, or None if it cannot be read."""
        ...
