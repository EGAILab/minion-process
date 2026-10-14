"""Admission, occupancy and resources (B-9, K-9 to K-11, K-17, B-11, B-5; witnesses W-1 to W-4, W-11,
W-25, W-46 to W-48, W-50, controls C-3 and C-9)."""

from __future__ import annotations

import os
from typing import Any

import pytest

from minion_process.hostqueue import policy as policy_mod
from minion_process.hostqueue import resources
from minion_process.hostqueue import state as state_mod
from minion_process.hostqueue.state import InvariantError, QueueState, decide

GIB = 1024**3


def policy(**over: Any) -> policy_mod.Policy:
    return policy_mod.parse(
        {"policy_id": "p", "version": 1, **policy_mod.OWNER_DEFAULTS, "projects": {"proj": ["E:\\x"]}, **over}
    )


class Q:
    """A queue state built from records, the way the broker builds it."""

    def __init__(self) -> None:
        self.state = QueueState()
        self.seq = 0

    def rec(self, kind: str, now: float = 0.0, **fields: Any) -> None:
        self.seq += 1
        self.state.apply({"seq": self.seq, "kind": kind, **fields}, now)

    def job(self, klass: str, leases: list[list[str]] | None = None) -> int:
        job_id = self.state.next_job_id
        spec = {
            "class": klass,
            "leases": leases if leases is not None else [[f"T{job_id}", "exclusive"]],
            "submitter": {},
        }
        self.rec("accept", request_id=f"r{job_id}", job_id=job_id, spec=spec)
        return job_id

    def run(self, job_id: int, now: float = 0.0) -> None:
        self.rec("launching", now, job_id=job_id)
        self.rec("running", now, job_id=job_id, runner={"pid": 1, "start": 1}, group="g")


# -- the policy ------------------------------------------------------------------------------------------


def test_owner_defaults_are_the_decided_values() -> None:
    assert policy_mod.OWNER_DEFAULTS == {
        "limit": 2,
        "floor_bytes": 16 * GIB,
        "reservation_seconds": 180,
        "bypass_limit": 3,
    }
    p = policy()
    assert p.as_dict()["projects"] == {"proj": ["E:\\x"]}


@pytest.mark.parametrize(
    "bad",
    [
        None,
        {"policy_id": "p"},
        {"policy_id": "p", "version": True, **policy_mod.OWNER_DEFAULTS, "projects": {"a": ["r"]}},
        {"policy_id": "p", "version": 0, **policy_mod.OWNER_DEFAULTS, "projects": {"a": ["r"]}},
        {"policy_id": "", "version": 1, **policy_mod.OWNER_DEFAULTS, "projects": {"a": ["r"]}},
        {"policy_id": "p", "version": 1, **policy_mod.OWNER_DEFAULTS, "projects": {}},
        {"policy_id": "p", "version": 1, **policy_mod.OWNER_DEFAULTS, "projects": {"a": []}},
        {"policy_id": "p", "version": 1, **policy_mod.OWNER_DEFAULTS, "projects": {"a": [""]}},
        {"policy_id": "p", "version": 1, **policy_mod.OWNER_DEFAULTS, "projects": {"a": ["r"]}, "extra": 1},
    ],
)
def test_policy_rejects_bad_shapes(bad: Any) -> None:
    with pytest.raises(policy_mod.PolicyError):
        policy_mod.parse(bad)


# -- resources -------------------------------------------------------------------------------------------


def test_resources_overlap_by_canonical_path(tmp_path: Any) -> None:
    a = resources.canonical(tmp_path / "t")
    nested = resources.canonical(tmp_path / "t" / "inner")
    assert resources.overlaps(a, a) and resources.overlaps(a, nested) and resources.overlaps(nested, a)
    assert not resources.overlaps(
        a, resources.canonical(tmp_path / "t2")
    )  # a prefix of the name is not a parent
    assert resources.conflicts([(a, "shared")], [(nested, "shared")]) == []
    assert resources.conflicts([(a, "shared")], [(nested, "exclusive")]) == [(a, nested)]
    alias = resources.canonical(str(tmp_path / "t") + os.sep)  # W-11: two spellings of one directory
    assert alias == a


# -- decide ----------------------------------------------------------------------------------------------


def test_w1_evidence_waits_for_the_drain_and_blocks_later_jobs() -> None:
    q = Q()
    b1, b2 = q.job("build"), q.job("build")
    q.run(b1)
    q.run(b2)
    ev, b3 = q.job("evidence"), q.job("build")
    d = decide(q.state, policy(limit=3), 64 * GIB, 0.0)
    assert d.admit is None and "drain" in d.waits[ev] and d.waits[b3] == "behind an earlier job"
    q.rec("ended", job_id=b1, outcome="passed", eligible=False)
    q.rec("ended", job_id=b2, outcome="passed", eligible=False)
    assert decide(q.state, policy(limit=3), 64 * GIB, 0.0).admit == ev
    q.run(ev)
    d = decide(q.state, policy(limit=3), 64 * GIB, 0.0)  # W-2: nothing admitted while evidence runs
    assert d.admit is None and "evidence" in d.waits[b3]
    q.rec("ended", job_id=ev, outcome="passed", eligible=True)
    assert decide(q.state, policy(limit=3), 64 * GIB, 0.0).admit == b3


def test_c3_admission_without_evidence_exclusivity_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    """C-3 negative control: with the host-blocked check removed, W-2's build is admitted beside evidence."""
    q = Q()
    ev, b = q.job("evidence"), q.job("build")
    q.run(ev)
    monkeypatch.setattr(QueueState, "host_blocked", lambda self: False)
    assert decide(q.state, policy(), 64 * GIB, 0.0).admit == b


def test_w3_w4_memory_floor_in_exact_bytes_with_reservations() -> None:
    q = Q()
    b1, b2 = q.job("build"), q.job("build")
    p = policy()
    assert decide(q.state, p, 16 * GIB, 0.0).admit == b1  # exactly the floor: admitted
    assert decide(q.state, p, 16 * GIB - 1, 0.0).admit is None  # one byte below: waits
    q.run(b1, now=0.0)
    d = decide(q.state, p, 20 * GIB, 10.0)  # b1 still in its start-up window: 20 - 16 < 16
    assert d.admit is None and "memory" in d.waits[b2]
    assert decide(q.state, p, 20 * GIB, 181.0).admit == b2  # window over
    assert decide(q.state, p, None, 181.0).admit is None


def test_limit_counts_every_active_job() -> None:
    q = Q()
    jobs = [q.job("build") for _ in range(3)]
    q.run(jobs[0])
    q.run(jobs[1])
    d = decide(q.state, policy(), 64 * GIB, 1000.0)
    assert d.admit is None and "limit" in d.waits[jobs[2]]


def test_w25_bounded_bypass() -> None:
    q = Q()
    holder = q.job("build", [["T", "exclusive"]])
    q.run(holder)
    blocked = q.job("build", [["T", "exclusive"]])
    later = q.job("build", [["U", "exclusive"]])
    d = decide(q.state, policy(limit=5), 64 * GIB, 1000.0)
    assert d.admit == later and d.bypassed == (blocked,)
    q.rec("bypass", job_id=blocked, count=3)
    d = decide(q.state, policy(limit=5), 64 * GIB, 1000.0)
    assert d.admit is None and "resource held" in d.waits[blocked]  # the bound is reached: it blocks


def test_w46_w48_c9_launching_and_uncertain_occupy_the_host() -> None:
    q = Q()
    ctl = q.job("control", [["C", "exclusive"]])
    q.rec("launching", job_id=ctl)
    ev = q.job("evidence", [["E", "exclusive"]])
    assert decide(q.state, policy(), 64 * GIB, 1000.0).admit is None  # W-48: launching is active
    q.rec("uncertain", job_id=ctl, reason="runner gone", extent_known=True)
    assert decide(q.state, policy(), 64 * GIB, 1000.0).admit is None  # W-46: uncertain on unrelated paths
    # W-47: an uncertain job keeps its reservation even past the window
    assert q.state.reserved_bytes(10_000.0, policy()) == 16 * GIB
    running_only = [j for j in q.state.active() if j.status == "running"]
    assert running_only == []  # C-9: a running-only count would have admitted the evidence job
    del ev


def test_w50_unknown_extent_blocks_every_class() -> None:
    q = Q()
    ghost = q.job("build", [])
    q.rec("launching", job_id=ghost)
    q.rec("uncertain", job_id=ghost, reason="footprint unknown", extent_known=False)
    b = q.job("build", [["Z", "exclusive"]])
    d = decide(q.state, policy(), 64 * GIB, 1000.0)
    assert d.admit is None and "blocked" in d.waits[b]


def test_cleanup_counts_and_never_runs_with_evidence() -> None:
    q = Q()
    c = q.job("cleanup", [["X", "exclusive"]])
    ev = q.job("evidence", [["Y", "exclusive"]])
    q.run(c)
    assert decide(q.state, policy(), 64 * GIB, 1000.0).admit is None
    del ev


def test_modes_and_missing_policy_stop_admission() -> None:
    q = Q()
    b = q.job("build")
    assert "no policy" in decide(q.state, None, 64 * GIB, 0.0).waits[b]
    q.rec("mode", mode="repair")
    assert "repair" in decide(q.state, policy(), 64 * GIB, 0.0).waits[b]


# -- state invariants ------------------------------------------------------------------------------------


def test_invariants_refuse_contradictions() -> None:
    q = Q()
    with pytest.raises(InvariantError, match="unknown kind"):
        q.rec("nonsense")
    j = q.job("build")
    with pytest.raises(InvariantError, match="accepted twice"):
        q.rec("accept", request_id=f"r{j}", job_id=2, spec={"class": "build", "leases": []})
    with pytest.raises(InvariantError, match="expected"):
        q.rec("accept", request_id="new", job_id=9, spec={"class": "build", "leases": []})
    with pytest.raises(InvariantError, match="unknown job"):
        q.rec("launching", job_id=99)
    with pytest.raises(InvariantError, match="not"):
        q.rec("running", job_id=j, runner={}, group="g")
    q.rec("reject", request_id="bad", reason="x")
    with pytest.raises(InvariantError, match="decided twice"):
        q.rec("reject", request_id="bad", reason="x")
    with pytest.raises(InvariantError, match="unknown copy"):
        q.rec("copy-state", copy_id="c", state="removed")
    with pytest.raises(InvariantError, match="closed or unknown challenge"):
        q.rec("confirmed", challenge_id="nope")
    with pytest.raises(InvariantError, match="render attempt"):
        q.rec("render", hash="h", attempt=2)
    q.rec("render", hash="h", attempt=1)
    with pytest.raises(InvariantError, match="without an undelivered"):
        q.rec("render", hash="h", attempt=2)
    with pytest.raises(InvariantError, match="policy version"):
        q.rec("policy", version=3, challenge="c")


def test_state_transitions_cover_every_record_kind() -> None:
    q = Q()
    j = q.job("build")
    q.rec("bypass", job_id=j, count=1)
    q.rec("launching", job_id=j)
    q.rec("requeue", job_id=j)
    assert q.state.jobs[j].status == "submitted"
    q.rec("cancelled", job_id=j)
    k = q.job("evidence")
    q.run(k)
    q.rec("ended", job_id=k, outcome="passed", eligible=True, retain=True)
    q.rec("unretain", job_id=k)
    assert not q.state.jobs[k].retain
    r = q.job("build")
    q.rec("launching", job_id=r)
    q.rec("refused", job_id=r, reason="drift")
    q.rec("broker-start", pid=1, start=1)
    q.rec(
        "challenge",
        challenge_id="c1",
        code_sha256="x",
        action="release",
        scope={},
        effect="e",
        expires_mono=1.0,
    )
    q.rec("confirmed", challenge_id="c1")
    q.rec("challenge-consumed", challenge_id="c2")
    q.rec("policy", version=1, challenge="c1")
    q.rec("policy-unknown", highest=4)
    assert q.state.policy_version is None and q.state.policy_floor == 4
    q.rec("policy", version=5, challenge="c3")
    q.rec("register", copy_id="cp", path="P", job_id=k)
    q.rec("lease-transfer", copy_id="cp", to_job=r)
    q.rec("copy-state", copy_id="cp", state="removed")
    q.rec("undelivered", hash="h", attempt=1)
    q.rec("recovery", outcomes=[])
    assert q.state.copies["cp"]["creator"] == k


def test_restart_holds_reservations_for_a_full_window() -> None:
    q = Q()
    j = q.job("build")
    q.run(j, now=0.0)
    q.rec("broker-start", 500.0, pid=1, start=1)
    job = q.state.jobs[j]
    assert job.reserved_since == 500.0 and job.reservation_restored
    assert q.state.reserved_bytes(600.0, policy()) == 16 * GIB


def test_build_lease_drops_to_shared_after_preparation() -> None:
    q = Q()
    j = q.state.next_job_id
    spec = {
        "class": "build",
        "leases": [["CHK", "exclusive"], ["T", "exclusive"]],
        "downgrade_after_prepare": "CHK",
        "submitter": {},
    }
    q.rec("accept", request_id="r", job_id=j, spec=spec)
    q.rec("launching", job_id=j)
    assert ("CHK", "exclusive") in q.state.held_leases()
    q.rec("running", job_id=j, runner={"pid": 1, "start": 1}, group="g")
    assert ("CHK", "shared") in q.state.held_leases() and ("T", "exclusive") in q.state.held_leases()


assert state_mod.CLASSES == ("evidence", "build", "control", "cleanup")
