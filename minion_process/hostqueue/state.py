"""Queue state, replayed from the journal, and the admission rule (B-9, K-9 to K-11, K-17).

`QueueState.apply(record)` is the only way state changes, so replay and live operation agree.
`decide(...)` is a pure function of the state, the policy, free memory and the clock. The broker journals
whatever it returns before acting on it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .policy import Policy

CLASSES = ("evidence", "build", "control", "cleanup")
ACTIVE = ("launching", "running", "uncertain")
TERMINAL = ("ended", "refused", "cancelled")


class InvariantError(ValueError):
    """A record contradicts the replayed state (B-27): the broker refuses to start."""


@dataclass
class Job:
    job_id: int
    request_id: str
    spec: dict[str, Any]
    status: str = "submitted"
    bypasses: int = 0
    reserved_since: float | None = None  # monotonic time of this broker instance
    reservation_restored: bool = False
    runner: dict[str, Any] | None = None
    group: str | None = None
    outcome: str | None = None
    eligible: bool = False
    reason: str | None = None
    extent_known: bool = True
    retain: bool = False

    @property
    def klass(self) -> str:
        return str(self.spec["class"])

    def leases(self) -> list[tuple[str, str]]:
        return [(str(p), str(m)) for p, m in self.spec["leases"]]

    def run_leases(self) -> list[tuple[str, str]]:
        """Leases held while running: a build job's checkout drops to shared after preparation (K-12a)."""
        if self.status == "running" and self.spec.get("downgrade_after_prepare"):
            downgrade = str(self.spec["downgrade_after_prepare"])
            return [(p, "shared" if p == downgrade else m) for p, m in self.leases()]
        return self.leases()


@dataclass
class QueueState:
    jobs: dict[int, Job] = field(default_factory=dict)
    requests: dict[str, int | str] = field(default_factory=dict)  # request id -> job id, or "rejected:<why>"
    mode: str = "normal"
    policy_version: int | None = None
    policy_floor: int = 0  # highest policy marker version seen when the policy became unknown
    challenges: dict[str, dict[str, Any]] = field(default_factory=dict)
    renders: dict[str, int] = field(default_factory=dict)  # handoff hash -> highest attempt
    undelivered: dict[str, set[int]] = field(default_factory=dict)
    copies: dict[str, dict[str, Any]] = field(default_factory=dict)  # registered copies
    next_job_id: int = 1

    # -- replay ------------------------------------------------------------------------------------------

    def apply(self, rec: dict[str, Any], now: float) -> None:
        kind = rec["kind"]
        handler = getattr(self, "_on_" + kind.replace("-", "_"), None)
        if handler is None:
            raise InvariantError(f"record {rec['seq']}: unknown kind {kind!r}")
        handler(rec, now)

    def _job(self, rec: dict[str, Any], *allowed: str) -> Job:
        job = self.jobs.get(rec["job_id"])
        if job is None:
            raise InvariantError(f"record {rec['seq']}: unknown job {rec['job_id']}")
        if allowed and job.status not in allowed:
            raise InvariantError(f"record {rec['seq']}: job {job.job_id} is {job.status}, not {allowed}")
        return job

    def _on_broker_start(self, rec: dict[str, Any], now: float) -> None:
        # B-6: reservations of the previous instance cannot be timed; hold each for a full window again.
        for job in self.jobs.values():
            if job.status in ACTIVE:
                job.reserved_since = now
                job.reservation_restored = True

    def _on_mode(self, rec: dict[str, Any], now: float) -> None:
        self.mode = rec["mode"]

    def _on_policy(self, rec: dict[str, Any], now: float) -> None:
        expected = max(self.policy_version or 0, self.policy_floor) + 1
        if rec["version"] != expected:
            raise InvariantError(f"record {rec['seq']}: policy version {rec['version']}, expected {expected}")
        self.policy_version = rec["version"]

    def _on_policy_unknown(self, rec: dict[str, Any], now: float) -> None:
        """Recovery: the policy in force cannot be established; admission stops until the Owner confirms a
        new version above every published one (K-37)."""
        self.policy_version = None
        self.policy_floor = int(rec["highest"])

    def _on_accept(self, rec: dict[str, Any], now: float) -> None:
        if rec["request_id"] in self.requests:
            raise InvariantError(f"record {rec['seq']}: request {rec['request_id']} accepted twice")
        if rec["job_id"] != self.next_job_id:
            raise InvariantError(f"record {rec['seq']}: job id {rec['job_id']}, expected {self.next_job_id}")
        self.jobs[rec["job_id"]] = Job(rec["job_id"], rec["request_id"], rec["spec"])
        self.requests[rec["request_id"]] = rec["job_id"]
        self.next_job_id += 1

    def _on_reject(self, rec: dict[str, Any], now: float) -> None:
        if rec["request_id"] in self.requests:
            raise InvariantError(f"record {rec['seq']}: request {rec['request_id']} decided twice")
        self.requests[rec["request_id"]] = "rejected:" + rec["reason"]

    def _on_bypass(self, rec: dict[str, Any], now: float) -> None:
        self._job(rec, "submitted").bypasses = rec["count"]

    def _on_launching(self, rec: dict[str, Any], now: float) -> None:
        job = self._job(rec, "submitted")
        job.status = "launching"
        job.reserved_since = now

    def _on_running(self, rec: dict[str, Any], now: float) -> None:
        job = self._job(rec, "launching")
        job.status = "running"
        job.runner = rec["runner"]
        job.group = rec["group"]

    def _on_uncertain(self, rec: dict[str, Any], now: float) -> None:
        job = self._job(rec, "launching", "running", "uncertain")
        job.status = "uncertain"
        job.reason = rec["reason"]
        job.extent_known = bool(rec.get("extent_known", True))
        if rec.get("group"):
            job.group = rec["group"]
        if rec.get("runner"):
            job.runner = rec["runner"]

    def _on_ended(self, rec: dict[str, Any], now: float) -> None:
        job = self._job(rec, "launching", "running", "uncertain")
        job.status = "ended"
        job.outcome = rec["outcome"]
        job.eligible = bool(rec["eligible"])
        job.reason = rec.get("reason")
        job.retain = bool(rec.get("retain", False))
        job.reserved_since = None

    def _on_refused(self, rec: dict[str, Any], now: float) -> None:
        job = self._job(rec, "submitted", "launching")
        job.status = "refused"
        job.reason = rec["reason"]
        job.reserved_since = None

    def _on_cancelled(self, rec: dict[str, Any], now: float) -> None:
        self._job(rec, "submitted").status = "cancelled"

    def _on_requeue(self, rec: dict[str, Any], now: float) -> None:
        """Recovery only: a `launching` job with no launch marker and proven no workload never started
        (K-31, first row)."""
        job = self._job(rec, "launching")
        job.status = "submitted"
        job.reserved_since = None

    def _on_challenge_consumed(self, rec: dict[str, Any], now: float) -> None:
        """Recovery only: `confirm/<id>` exists, so the challenge can never be used again (K-31, K-33)."""
        challenge = self.challenges.setdefault(rec["challenge_id"], {"challenge_id": rec["challenge_id"]})
        challenge["state"] = "consumed"

    def _on_unretain(self, rec: dict[str, Any], now: float) -> None:
        self._job(rec, "ended").retain = False

    def _on_challenge(self, rec: dict[str, Any], now: float) -> None:
        self.challenges[rec["challenge_id"]] = {**rec, "state": "open"}

    def _on_confirmed(self, rec: dict[str, Any], now: float) -> None:
        challenge = self.challenges.get(rec["challenge_id"])
        if challenge is None or challenge["state"] != "open":
            raise InvariantError(f"record {rec['seq']}: confirmation of a closed or unknown challenge")
        challenge["state"] = "consumed"

    def _on_render(self, rec: dict[str, Any], now: float) -> None:
        previous = self.renders.get(rec["hash"], 0)
        if rec["attempt"] != previous + 1:
            raise InvariantError(f"record {rec['seq']}: render attempt {rec['attempt']} after {previous}")
        if previous and previous not in self.undelivered.get(rec["hash"], set()):
            raise InvariantError(f"record {rec['seq']}: render retry without an undelivered attempt")
        self.undelivered.get(rec["hash"], set()).discard(previous)  # one grant authorizes one retry
        self.renders[rec["hash"]] = rec["attempt"]

    def _on_undelivered(self, rec: dict[str, Any], now: float) -> None:
        self.undelivered.setdefault(rec["hash"], set()).add(rec["attempt"])

    def _on_undelivered_revoked(self, rec: dict[str, Any], now: float) -> None:
        """Recovery: a journal grant whose published marker cannot be read is withdrawn (R005)."""
        self.undelivered.get(rec["hash"], set()).discard(rec["attempt"])

    def _on_register(self, rec: dict[str, Any], now: float) -> None:
        self.copies[rec["copy_id"]] = {
            "path": rec["path"],
            "job_id": rec["job_id"],
            "creator": rec["job_id"],
            "state": "registered",
        }

    def _copy(self, rec: dict[str, Any]) -> dict[str, Any]:
        copy = self.copies.get(rec["copy_id"])
        if copy is None:
            raise InvariantError(f"record {rec['seq']}: unknown copy {rec['copy_id']}")
        return copy

    def _on_lease_transfer(self, rec: dict[str, Any], now: float) -> None:
        self._copy(rec)["job_id"] = rec["to_job"]

    def _on_copy_state(self, rec: dict[str, Any], now: float) -> None:
        self._copy(rec)["state"] = rec["state"]

    def _on_recovery(self, rec: dict[str, Any], now: float) -> None:
        pass  # informational: the outcomes it reports are applied by their own records

    # -- queries -----------------------------------------------------------------------------------------

    def active(self) -> list[Job]:
        return [j for j in self.jobs.values() if j.status in ACTIVE]

    def waiting(self) -> list[Job]:
        return sorted((j for j in self.jobs.values() if j.status == "submitted"), key=lambda j: j.job_id)

    def held_leases(self) -> list[tuple[str, str]]:
        held: list[tuple[str, str]] = []
        for job in self.active():
            held += job.run_leases()
        return held

    def host_blocked(self) -> bool:
        """Evidence running, or uncertain work of unknown extent, blocks every admission (K-9a, K-10)."""
        return any(
            j.klass == "evidence" or (j.status == "uncertain" and not j.extent_known) for j in self.active()
        )

    def reserved_bytes(self, now: float, policy: Policy) -> int:
        total = 0
        for job in self.active():
            in_window = (
                job.reserved_since is not None and now - job.reserved_since < policy.reservation_seconds
            )
            if job.status in ("launching", "uncertain") or in_window:
                total += policy.floor_bytes
        return total


@dataclass(frozen=True)
class Decision:
    admit: int | None
    bypassed: tuple[int, ...]  # earlier jobs passed over by this admission (B-9 bounded bypass)
    waits: dict[int, str]  # job id -> what it waits on (B-9: status names it)


def decide(state: QueueState, policy: Policy | None, free_bytes: int | None, now: float) -> Decision:
    from .resources import conflicts

    waits: dict[int, str] = {}
    queue = state.waiting()
    if state.mode != "normal":
        return Decision(None, (), {j.job_id: f"broker in {state.mode} mode" for j in queue})
    if policy is None:
        return Decision(None, (), {j.job_id: "no policy in force" for j in queue})
    if state.host_blocked():
        return Decision(None, (), {j.job_id: "host blocked by evidence or uncertain work" for j in queue})
    active = state.active()
    bypassed: list[int] = []
    for job in queue:
        if job.klass == "evidence":
            if active:
                waits[job.job_id] = "evidence waits for the host to drain"
                break  # nothing behind an evidence job is admitted (drain)
            return Decision(job.job_id, tuple(bypassed), waits)
        if len(active) >= policy.limit:
            waits[job.job_id] = f"host limit {policy.limit} reached"
            break
        if free_bytes is None:
            waits[job.job_id] = "free memory unknown"
            break
        available = free_bytes - state.reserved_bytes(now, policy)
        if available < policy.floor_bytes:
            waits[job.job_id] = (
                f"memory: {available} bytes available after reservations, floor {policy.floor_bytes}"
            )
            break  # memory is host-wide: never bypassed
        clash = conflicts(state.held_leases(), job.leases())
        if clash:
            waits[job.job_id] = f"resource held: {clash[0][0]}"
            if job.bypasses >= policy.bypass_limit:
                break  # bypass bound reached: it now blocks everything behind it
            bypassed.append(job.job_id)
            continue
        return Decision(job.job_id, tuple(bypassed), waits)
    for job in queue:
        waits.setdefault(job.job_id, "behind an earlier job")
    return Decision(None, (), waits)
