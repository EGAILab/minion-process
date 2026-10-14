"""Recovery, reconciliation and repair (B-27, B-28, K-12, K-25 to K-40; witnesses W-6, W-19, W-52, W-55 to
W-57, W-59, W-75 to W-80, W-87, W-89 to W-93; controls C-14, C-15, C-16)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from minion_process.hostqueue import client, framing, layout
from minion_process.hostqueue.broker import Broker
from minion_process.hostqueue.framing import decode_single, encode
from minion_process.hostqueue.journal import parse

from .hostqueue_world import SHA, World, make_world, policy_dict

GIB = 1024**3


def journal_file(w: World) -> Path:
    return layout.journal_path(w.queue, w.broker.generation)


def cut_after(
    w: World, kind: str, job_id: int | None = None, damage: str = "length", drop_from: int | None = None
) -> None:
    """Keep the journal up to and including the last `kind` record (for `job_id`), then damage that record:
    `length` enlarges its length prefix (Codex's probe), `marker` removes its commit marker, `checksum`
    flips a payload byte, `none` keeps it intact."""
    path = journal_file(w)
    data = path.read_bytes()
    replay = parse(data)
    index = max(
        i
        for i, r in enumerate(replay.records)
        if r["kind"] == kind and (job_id is None or r.get("job_id") == job_id)
    )
    start = replay.ends[index - 1] if index else 0
    keep = data[: replay.ends[index]]
    record = keep[start:]
    if damage == "length":
        record = record[:5] + b"%08x" % 0x135 + record[13:]
    elif damage == "marker":
        record = record[: -len(framing.COMMIT)]
    elif damage == "checksum":
        record = record[:-8] + (b"X" if record[-8:-7] != b"X" else b"Y") + record[-7:]
    path.write_bytes(keep[:start] + record)


def hold_admission(w: World) -> int:
    w.host.memory = 0
    job_id = int(w.submit()["job_id"])
    w.host.memory = 64 * GIB
    return job_id


def restart(w: World, repair: bool = False) -> Any:
    w.broker.stop()
    w.broker = Broker(w.queue, w.host, w.git, python="python")
    return w.broker.start(repair=repair)


# -- start-up paths ---------------------------------------------------------------------------------------


def test_w6_w59_replay_runs_with_or_without_an_abandonment_signal(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    job_id = w.submit()["job_id"]
    w.host.mutex_abandoned = True
    report = restart(w)
    assert report.abandoned and w.job(job_id).status == "running"
    w.host.mutex_abandoned = False
    report = restart(w)
    assert not report.abandoned and w.job(job_id).status == "running"


# -- launch pairs W-75 to W-77 ----------------------------------------------------------------------------


@pytest.mark.parametrize("damage", ["length", "marker", "checksum"])
def test_w75_never_started_is_relaunched_once(tmp_path: Path, damage: str) -> None:
    """The damaged `launching` record is the tail: replay stops before it, no launch marker exists and
    no workload runs, so the job is still `submitted` and is launched exactly once."""
    w = make_world(tmp_path)
    job_id = hold_admission(w)
    w.broker._record("launching", job_id=job_id)  # crash before the launch marker: nothing started
    cut_after(w, "launching", job_id, damage)
    report = restart(w)
    assert report.mode == "normal", report.recovery
    assert w.job(job_id).status == "submitted"
    w.broker.step()
    assert w.job(job_id).status == "running" and len(w.host.spawned) == 1


def test_w75_intact_launching_without_marker_is_requeued(tmp_path: Path) -> None:
    """The `launching` record survived but the crash came before the launch marker (K-31, first row)."""
    w = make_world(tmp_path)
    job_id = hold_admission(w)
    w.broker._record("launching", job_id=job_id)
    report = restart(w)
    assert report.mode == "normal" and any("never launched" in line for line in report.recovery)
    w.broker.step()
    assert w.job(job_id).status == "running" and len(w.host.spawned) == 1


@pytest.mark.parametrize("damage", ["length", "marker", "checksum"])
def test_w76_still_running_blocks_and_is_not_relaunched(tmp_path: Path, damage: str) -> None:
    w = make_world(tmp_path)
    job_id = w.submit()["job_id"]
    cut_after(w, "launching", job_id, damage)
    report = restart(w)
    assert report.mode == "repair" and any("still running" in line for line in report.recovery)
    w.broker.step()
    assert len(w.host.spawned) == 1


@pytest.mark.parametrize("damage", ["length", "marker", "checksum"])
def test_w77_already_finished_ends_unknown_and_is_not_relaunched(tmp_path: Path, damage: str) -> None:
    w = make_world(tmp_path)
    job_id = w.submit()["job_id"]
    spawned = w.host.spawned[-1]
    w.host.finish(spawned["group"], spawned["runner"])
    cut_after(w, "launching", job_id, damage)
    report = restart(w)
    assert report.mode == "normal", report.recovery
    job = w.job(job_id)
    assert job.status == "ended" and job.outcome == "unknown-outcome" and not job.eligible
    w.broker.step()
    assert len(w.host.spawned) == 1  # launch count 1, not 2
    quarantined = list((w.queue / "quarantine").rglob("*tail"))
    assert quarantined, "the ambiguous bytes are kept"


def test_c15_c16_the_rejected_rules_would_launch_twice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C-15: K-27's rule ("no live workload, therefore submitted") ignores the launch marker; C-16: a marker
    written after the effect gives no exclusivity. Together they make W-77 launch twice."""
    w = make_world(tmp_path)
    job_id = w.submit()["job_id"]
    spawned = w.host.spawned[-1]
    w.host.finish(spawned["group"], spawned["runner"])
    cut_after(w, "launching", job_id, "length")
    real_names = Broker.__dict__["_reconcile_launches"]
    del real_names
    from minion_process.hostqueue import markers as markers_mod

    original_names = markers_mod.Markers.names
    original_publish = markers_mod.Markers.publish

    def names(self: Any, kind: str, *prefix: str) -> list[str]:
        return [] if kind == "launch" else original_names(self, kind, *prefix)

    def publish(
        self: Any, kind: str, identity: tuple[str, ...], payload: dict[str, Any], after_seq: int
    ) -> None:
        if kind == "launch":
            return  # C-16: no write-ahead reservation
        original_publish(self, kind, identity, payload, after_seq)

    monkeypatch.setattr(markers_mod.Markers, "names", names)
    monkeypatch.setattr(markers_mod.Markers, "publish", publish)
    restart(w)
    w.broker.step()
    assert len(w.host.spawned) == 2  # the hazard the agreed rules prevent


def test_c14_discarding_short_tails_would_relaunch_a_live_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = make_world(tmp_path)
    job_id = w.submit()["job_id"]
    cut_after(w, "launching", job_id, "length")
    from minion_process.hostqueue import markers as markers_mod

    original = markers_mod.Markers.names
    monkeypatch.setattr(
        markers_mod.Markers,
        "names",
        lambda self, kind, *p: [] if kind == "launch" else original(self, kind, *p),
    )
    monkeypatch.setattr(markers_mod.Markers, "publish", lambda *a, **k: None)
    w.host.groups[w.job(job_id).spec["group"]] = False  # an inspection that does not see the live work
    restart(w)
    w.broker.step()
    assert len(w.host.spawned) == 2


def test_inspection_failure_during_recovery_blocks(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    job_id = w.submit()["job_id"]
    cut_after(w, "launching", job_id, "length")
    w.host.group_query_error = True
    report = restart(w)
    assert report.mode == "repair" and any("inspection failed" in line for line in report.recovery)


def test_launching_without_marker_and_unknown_workload(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    job_id = hold_admission(w)
    w.broker._record("launching", job_id=job_id)
    w.host.group_query_error = True
    report = restart(w)
    assert report.mode == "repair" and any("cannot be ruled out" in line for line in report.recovery)


# -- accept, render, confirm, policy (W-57, W-78 to W-80, W-87, W-89, W-93) -------------------------------


def test_w57_w93_lost_accept_record_keeps_the_job_id(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    w.host.memory = 0
    request_id = client.put(
        w.queue,
        {
            "type": "submit",
            "class": "build",
            "profile": str(w.profile),
            "launcher": "rust",
            "target": "gate",
            "checkout": str(w.root / "repo"),
            "submitter": {"pane": "w1:p1", "session": "s1"},
        },
    )
    w.broker.step()
    job_id = decode_single((w.queue / "outbox" / f"{request_id}.res").read_bytes())["job_id"]
    cut_after(w, "accept", job_id, "checksum")
    (w.queue / "outbox" / f"{request_id}.res").unlink()  # the response is lost too
    report = restart(w)
    assert report.mode == "normal" and w.job(job_id).request_id == request_id
    again = w.request({"type": "submit", "request_id": request_id, "class": "build"})
    assert again["duplicate"] and again["job_id"] == job_id


def test_accept_marker_out_of_order_or_unreadable(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    w.broker.markers.publish("accept", ("ghost",), {"job_id": 7, "spec": {"class": "build", "leases": []}}, 0)
    report = restart(w)
    assert report.mode == "repair" and any("out of order" in line for line in report.recovery)


def test_w55_unreadable_accept_gets_a_host_blocking_placeholder(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    w.broker.markers.publish("accept", ("lost",), {"job_id": 1, "spec": {}}, 0)
    path = w.queue / "effects" / "accept" / "lost"
    path.write_bytes(path.read_bytes()[:-4])
    report = restart(w)
    assert report.mode == "repair"
    quarantine = w.request({"type": "repair-quarantine"})
    applied = w.confirm(quarantine["code"])
    assert applied["ok"], applied
    placeholder = w.job(1)
    assert placeholder.status == "uncertain" and not placeholder.extent_known
    resume = w.request({"type": "repair-resume"})
    assert w.confirm(resume["code"])["ok"] and w.broker.state.mode == "normal"
    blocked = w.submit()
    assert w.job(blocked["job_id"]).status == "submitted"  # the whole host is blocked
    release = w.request({"type": "release", "job_id": 1})
    assert w.confirm(release["code"])["ok"]
    w.broker.step()
    assert w.job(blocked["job_id"]).status == "running"


def test_unknown_launch_marker_gets_a_placeholder(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    w.broker.markers.publish("launch", ("41",), {"group": "g"}, 0)
    report = restart(w)
    assert report.mode == "repair" and any("unknown job" in line for line in report.recovery)


def test_w78_render_restored_after_a_damaged_tail(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    first = w.request({"type": "render", "text": "hand-off"})
    cut_after(w, "render", None, "marker")
    report = restart(w)
    assert report.mode == "normal" and any("may-have-printed" in line for line in report.recovery)
    assert "already rendered" in w.request({"type": "render", "text": "hand-off"})["error"]
    del first


def test_w87_undelivered_marker_survives_a_damaged_record(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    first = w.request({"type": "render", "text": "hand-off"})
    w.request({"type": "undelivered", "hash": first["hash"], "attempt": 1})
    cut_after(w, "undelivered", None, "length")
    report = restart(w)
    assert report.mode == "normal" and any("retry authorized" in line for line in report.recovery)
    assert w.request({"type": "render", "text": "hand-off"})["attempt"] == 2


def test_w89_unreadable_undelivered_refuses_the_retry(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    first = w.request({"type": "render", "text": "hand-off"})
    w.request({"type": "undelivered", "hash": first["hash"], "attempt": 1})
    cut_after(w, "undelivered", None, "length")
    marker = w.queue / "effects" / "undelivered" / first["hash"] / "1"
    marker.write_bytes(marker.read_bytes()[:-2])
    report = restart(w)
    assert report.mode == "repair" and any("no retry until repaired" in line for line in report.recovery)
    w.confirm(w.request({"type": "repair-quarantine"})["code"])
    w.confirm(w.request({"type": "repair-resume"})["code"])
    assert "already rendered" in w.request({"type": "render", "text": "hand-off"})["error"]


def test_w79_policy_restored_or_unknown(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    w.confirm(w.request({"type": "policy-set", "policy": policy_dict(w.root, version=2, limit=1)})["code"])
    cut_after(w, "policy", None, "checksum")
    report = restart(w)
    assert report.mode == "normal" and w.broker.policy is not None and w.broker.policy.version == 2
    w.confirm(w.request({"type": "policy-set", "policy": policy_dict(w.root, version=3, limit=2)})["code"])
    cut_after(w, "policy", None, "checksum")
    marker = w.queue / "effects" / "policy" / "3"
    marker.write_bytes(marker.read_bytes()[:-2])
    report = restart(w)
    assert report.mode == "repair" and any("policy unknown" in line for line in report.recovery)
    w.confirm(w.request({"type": "repair-quarantine"})["code"])
    w.confirm(w.request({"type": "repair-resume"})["code"])
    assert w.broker.policy is None and "no policy" in w.submit()["error"]  # never the older policy
    assert "must be 4" in w.request({"type": "policy-set", "policy": policy_dict(w.root, version=3)})["error"]
    assert w.confirm(w.request({"type": "policy-set", "policy": policy_dict(w.root, version=4)})["code"])[
        "ok"
    ]


def test_policy_without_a_readable_confirmation_is_unknown(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    w.broker.markers.publish(
        "policy", ("2",), {"policy": policy_dict(w.root, version=2), "challenge": "missing"}, 0
    )
    report = restart(w)
    assert report.mode == "repair" and any("confirmation is not readable" in line for line in report.recovery)


def test_w80_w90_consumed_confirmation_and_unrestored_release(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    job_id = w.submit()["job_id"]
    w.host.group_query_error = True
    w.broker.step()
    challenge = w.request({"type": "release", "job_id": job_id})
    w.host.group_query_error = False
    w.confirm(challenge["code"])
    assert w.job(job_id).outcome == "human-confirmed"
    cut_after(w, "confirmed", None, "length")  # the confirmation record and the release are lost
    report = restart(w)
    assert any("not restored" in line for line in report.recovery)
    assert w.job(job_id).status == "uncertain"  # K-33: the effect is not restored
    assert w.confirm(challenge["code"])["error"] == "challenge already used"


# -- invariants, mid-journal damage, repair (W-19, W-52, W-56, W-91, W-92) ---------------------------------


def test_w52_mid_journal_damage_needs_repair(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    job_id = w.submit()["job_id"]
    path = journal_file(w)
    data = path.read_bytes()
    replay = parse(data)
    accept = next(i for i, r in enumerate(replay.records) if r["kind"] == "accept")
    end = replay.ends[accept]
    path.write_bytes(data[: end - 8] + b"X" + data[end - 7 :])
    report = restart(w)
    assert report.mode == "repair" and "mid-journal" in report.recovery[0]
    assert "repair mode" in w.submit()["error"]
    assert w.request({"type": "status"})["mode"] == "repair"
    assert w.request({"type": "repair-inspect"})["report"]["anomaly"]["position"] == "mid"
    assert "resume needs" in w.request({"type": "repair-resume"})["error"]
    quarantine = w.request({"type": "repair-quarantine"})
    assert quarantine["ok"] and w.confirm(quarantine["code"])["ok"]
    assert list((w.queue / "quarantine").rglob("*full"))
    assert w.broker.state.mode == "repair" and w.broker.generation == 2
    resume = w.request({"type": "repair-resume"})
    assert w.confirm(resume["code"])["ok"] and w.broker.state.mode == "normal"
    w.broker.step()
    del job_id


def test_invariant_failure_keeps_the_prefix(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    w.broker._record("launching", job_id=99) if False else None
    path = journal_file(w)
    last = parse(path.read_bytes()).last_seq
    path.write_bytes(
        path.read_bytes() + encode({"seq": last + 1, "instance": "x", "kind": "launching", "job_id": 99})
    )
    report = restart(w)
    assert report.mode == "repair" and "invariant" in report.recovery[0]
    assert len(w.broker.replay.records) == last  # type: ignore[union-attr]


def test_start_in_repair_mode_and_resume(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    report = restart(w, repair=True)
    assert report.mode == "repair"
    resume = w.request({"type": "repair-resume"})
    assert w.confirm(resume["code"])["ok"] and w.broker.state.mode == "normal"


def test_unknown_generation_needs_the_owner(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    marker = w.queue / "effects" / "generation" / str(w.broker.generation)
    marker.write_bytes(marker.read_bytes()[:-2])
    report = restart(w)
    assert report.mode == "repair" and "unknown" in report.recovery[0]
    assert "needs the Owner" in w.request({"type": "repair-quarantine"})["error"]
    (w.queue / "effects" / "generation" / "odd").write_text("x")
    assert restart(w).mode == "repair"


def test_unsafe_repair_with_inspection_denied(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    job_id = w.submit()["job_id"]
    cut_after(w, "launching", job_id, "length")
    w.host.group_query_error = True
    restart(w)
    w.confirm(w.request({"type": "repair-quarantine"})["code"])
    assert w.job(job_id).status == "uncertain"  # W-56
    resume = w.request({"type": "repair-resume"})
    assert resume["ok"]


def test_marker_folder_unreadable_during_reconciliation(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    (w.queue / "effects" / "render").write_text("not a folder")
    report = restart(w)
    assert report.mode == "repair" and any("inspection failed" in line for line in report.recovery)
    w.confirm(w.request({"type": "repair-quarantine"})["code"])
    assert "nothing unsafe" in w.request({"type": "repair-resume"})["error"]


def test_intact_journal_with_markers_ahead_records_the_recovery(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    w.broker.markers.publish(
        "register", ("loose",), {"path": str(w.root / "exec" / "loose"), "job_id": 1, "manifest": []}, 0
    )
    report = restart(w)
    assert report.mode == "normal" and any("register/loose: restored" in line for line in report.recovery)
    assert "loose" in w.broker.state.copies


def test_unreadable_register_marker(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    w.broker.markers.publish("register", ("bad",), {"path": "x", "job_id": 1, "manifest": []}, 0)
    path = w.queue / "effects" / "register" / "bad"
    path.write_bytes(b"junk")
    report = restart(w)
    assert report.mode == "repair" and any("copy damaged" in line for line in report.recovery)


assert SHA
