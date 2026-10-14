"""A deterministic `HostOS` and `GitOps` for the host-queue tests: process table, tracking groups,
containers, memory, clock, the broker mutex and herdr panes are all plain data the test controls."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from minion_process.hostqueue.hostos import MutexResult, ProcessIdentity, Spawned


@dataclass
class FakeHost:
    mutex_held_by_other: bool = False
    mutex_abandoned: bool = False
    mutex_error: str | None = None
    mutex_owned: bool = False
    local_volume: bool | None = True
    memory: int | None = 64 * 1024**3
    clock: float = 1000.0
    processes: dict[tuple[int, int], bool | None] = field(default_factory=dict)
    groups: dict[str, bool | None] = field(default_factory=dict)  # group -> active
    containers: dict[str, bool | None] = field(default_factory=dict)  # label -> running
    panes: dict[str, dict[str, Any] | None] = field(default_factory=dict)
    spawned: list[dict[str, Any]] = field(default_factory=list)
    spawn_error: OSError | None = None
    spawn_creates_group: bool = True
    spawn_birth_unknown: bool = False  # the birth query failed at spawn (K-41)
    next_pid: int = 5000
    publish_calls: list[Path] = field(default_factory=list)
    group_query_error: bool = False
    boot: str | None = "boot-1"

    # -- mutex ------------------------------------------------------------------------------------------
    def acquire_broker_mutex(self) -> MutexResult:
        if self.mutex_error:
            return MutexResult(False, False, self.mutex_error)
        if self.mutex_held_by_other or self.mutex_owned:
            return MutexResult(False, False)
        self.mutex_owned = True
        return MutexResult(True, self.mutex_abandoned)

    def release_broker_mutex(self) -> None:
        self.mutex_owned = False

    # -- processes --------------------------------------------------------------------------------------
    def self_identity(self) -> ProcessIdentity:
        return ProcessIdentity(4242, 1)

    def process_alive(self, ident: ProcessIdentity) -> bool | None:
        """`processes` maps (pid, birth) to alive (True), exited (False) or unknown (None). An identity
        recorded with an unknown birth is alive-or-unknown while any process with that id has not exited
        (K-41); a known birth is looked up exactly, so a different birth is a reused id."""
        if ident.start is None:
            present = [alive for (pid, _birth), alive in self.processes.items() if pid == ident.pid]
            return None if any(alive is not False for alive in present) else False
        return self.processes.get((ident.pid, ident.start), False)

    def spawn(self, argv: list[str], env: dict[str, str], cwd: Path, log: Path, group: str) -> Spawned:
        if self.spawn_creates_group:
            self.groups[group] = True
        if self.spawn_error is not None:
            raise self.spawn_error
        self.next_pid += 1
        ident = ProcessIdentity(self.next_pid, None if self.spawn_birth_unknown else 77)
        self.processes[(ident.pid, ident.start)] = True
        self.spawned.append(
            {"argv": argv, "env": env, "cwd": cwd, "log": log, "group": group, "runner": ident}
        )
        return Spawned(ident, group)

    def group_active(self, group: str) -> bool | None:
        if self.group_query_error:
            return None
        return self.groups.get(group, False)

    def group_exists(self, group: str) -> bool | None:
        if self.group_query_error:
            return None
        return group in self.groups

    def containers_running(self, label: str) -> bool | None:
        return self.containers.get(label, False)

    def finish(self, group: str, runner: ProcessIdentity | None = None) -> None:
        """The workload ends: the group empties, and the runner it spawned (or the one named) exits."""
        self.groups[group] = False
        ended = [s["runner"] for s in self.spawned if s["group"] == group]
        for ident in [*ended, *([runner] if runner is not None else [])]:
            self.processes[(ident.pid, ident.start)] = False

    # -- memory, clock, volume --------------------------------------------------------------------------
    def free_memory_bytes(self) -> int | None:
        return self.memory

    def monotonic(self) -> float:
        return self.clock

    def boot_id(self) -> str | None:
        return self.boot

    def wall_time(self) -> str:
        return "2026-10-13T20:00:00Z"

    def is_local_fixed_volume(self, path: Path) -> bool | None:
        return self.local_volume

    # -- publication ------------------------------------------------------------------------------------
    def publish(self, temp: Path, final: Path) -> None:
        self.publish_calls.append(final)
        if os.path.lexists(final):
            raise FileExistsError(str(final))
        os.rename(temp, final)

    # -- herdr ------------------------------------------------------------------------------------------
    def pane(self, pane: str) -> dict[str, Any] | None:
        return self.panes.get(pane)


@dataclass
class FakeGit:
    heads: dict[str, str | None] = field(default_factory=dict)
    clean_state: dict[str, bool | None] = field(default_factory=dict)
    add_error: OSError | None = None
    files: tuple[str, ...] = ("src/lib.rs", "Cargo.toml")
    plant: Any = None  # called with the new worktree, e.g. to check out a committed link (W-99d)

    def add_worktree(self, source: Path, workdir: Path, sha: str) -> None:
        if self.add_error is not None:
            raise self.add_error
        for name in self.files:
            path = workdir / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"{sha}\n", encoding="utf-8")
        if self.plant is not None:
            self.plant(workdir)
        self.heads.setdefault(str(workdir), sha)
        self.clean_state.setdefault(str(workdir), True)

    def head(self, workdir: Path) -> str | None:
        return self.heads.get(str(workdir))

    def clean(self, workdir: Path) -> bool | None:
        return self.clean_state.get(str(workdir))


def pane_info(session: str, agent: str = "claude") -> dict[str, Any]:
    return {"agent": agent, "agent_session": {"kind": "id", "value": session}, "agent_status": "idle"}
