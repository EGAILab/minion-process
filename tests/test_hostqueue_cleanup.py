"""Leased cleanup of registered copies (K-17 to K-20, K-39, Part C; witnesses W-27 to W-32, W-61 to W-64,
W-81, W-82; control C-12)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from minion_process.hostqueue import broker as broker_mod
from minion_process.hostqueue.framing import encode

from .hostqueue_world import SHA, World, make_world


def evidence_copy(w: World, retain: bool = False) -> tuple[int, str, Path]:
    job_id = int(w.submit("evidence", sha=SHA)["job_id"])
    job = w.job(job_id)
    code = (0, 0) if retain else (1, 1)
    (w.queue / "jobs" / str(job_id) / "result").write_bytes(encode({"exit": code[0], "gate_end": code[1]}))
    w.host.finish(job.spec["group"])
    w.broker.step()
    copy_id = str(job.spec["job_label"])
    return job_id, copy_id, Path(str(job.spec["workdir"]))


def cleanup(w: World, *copies: str, apply: bool = True) -> dict[str, Any]:
    return w.request(
        {
            "type": "submit",
            "class": "cleanup",
            "profile": str(w.profile),
            "copies": list(copies),
            "apply": apply,
            "submitter": {"pane": "w1:p1", "session": "s1"},
        }
    )


def test_w61_owned_copy_is_removed_through_submit_and_admission(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    _, copy_id, workdir = evidence_copy(w)
    assert workdir.exists()
    response = cleanup(w, copy_id)
    assert response["ok"], response
    w.broker.step()
    job = w.job(response["job_id"])
    assert job.status == "ended" and job.outcome == "passed" and not job.eligible
    assert not workdir.exists() and w.broker.state.copies[copy_id]["state"] == "removed"
    assert w.git.pruned  # the source repository's worktree registry is pruned


def test_cleanup_runs_in_batches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(broker_mod, "CLEANUP_BATCH", 1)
    w = make_world(tmp_path)
    _, copy_id, workdir = evidence_copy(w)
    response = cleanup(w, copy_id)
    job = w.job(response["job_id"])
    assert job.status == "running" and workdir.exists()
    for _ in range(10):
        w.broker.step()
    assert job.status == "ended" and not workdir.exists()


def test_w64_retained_evidence_copy_is_refused(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    _, copy_id, _ = evidence_copy(w, retain=True)
    assert "retained" in cleanup(w, copy_id)["error"]


def test_cleanup_refusals_at_submit(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    assert "not a registered copy" in cleanup(w, "ghost")["error"]
    assert (
        "list of registered copy ids"
        in w.request(
            {
                "type": "submit",
                "class": "cleanup",
                "profile": str(w.profile),
                "copies": [],
                "submitter": {"pane": "w1:p1", "session": "s1"},
            }
        )["error"]
    )
    job_id = int(w.submit("evidence", sha=SHA)["job_id"])  # still running
    copy_id = str(w.job(job_id).spec["job_label"])
    assert "which is running" in cleanup(w, copy_id)["error"]


def waiting_user(w: World, workdir: Path) -> int:
    """A build that names the copy as its checkout and waits behind a running job holding its target."""
    holder = w.submit("build", "gate2")
    assert w.job(holder["job_id"]).status == "running"
    user = w.submit("build", "gate2", checkout=str(workdir))
    assert w.job(user["job_id"]).status == "submitted", w.request({"type": "status"})
    return int(user["job_id"])


def test_w62_reference_by_a_waiting_job_refuses_at_the_boundary(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    _, copy_id, workdir = evidence_copy(w)
    waiting_user(w, workdir)
    job = w.job(cleanup(w, copy_id)["job_id"])
    w.broker.step()
    assert job.outcome == "failed" and "referenced by job" in str(job.reason)
    assert workdir.exists()


def test_c12_empty_reference_set_removes_a_live_reference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C-12: with the reference set emptied, the copy a waiting job names is removed."""
    w = make_world(tmp_path)
    _, copy_id, workdir = evidence_copy(w)
    waiting_user(w, workdir)
    monkeypatch.setattr(broker_mod.Broker, "_cleanup_predicates", lambda self, job: None)
    cleanup(w, copy_id)
    for _ in range(3):
        w.broker.step()
    assert not workdir.exists()


def test_w63_reference_sources_and_unreadable_sources(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    _, copy_id, workdir = evidence_copy(w)
    (w.root / "incidents" / "i1.md").write_text(f"evidence kept at {workdir}\n", encoding="utf-8")
    job = w.job(cleanup(w, copy_id)["job_id"])
    w.broker.step()
    assert job.outcome == "failed" and "referenced in" in str(job.reason) and workdir.exists()
    data = yaml.safe_load(w.profile.read_text(encoding="utf-8"))
    data["build_queue"]["cleanup_references"]["incidents"] = [str(w.root / "missing-folder" / "x.md")]
    w.profile.write_text(yaml.safe_dump(data), encoding="utf-8")
    job = w.job(cleanup(w, copy_id)["job_id"])
    w.broker.step()
    assert "unreadable" in str(job.reason) and workdir.exists()
    data["build_queue"]["cleanup_references"]["incidents"] = [str(w.root / "incidents")]
    (w.root / "incidents" / "i1.md").write_text("nothing here\n", encoding="utf-8")
    w.profile.write_text(yaml.safe_dump(data), encoding="utf-8")
    job = w.job(cleanup(w, copy_id)["job_id"])
    w.broker.step()
    assert job.outcome == "passed" and not workdir.exists()


def test_cleanup_profile_unreadable_at_the_boundary(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    _, copy_id, workdir = evidence_copy(w)
    w.host.memory = 0
    response = cleanup(w, copy_id)
    w.profile.write_text("[broken", encoding="utf-8")
    w.host.memory = 64 * 1024**3
    w.broker.step()
    w.broker.step()
    assert "profile unreadable at the boundary" in str(w.job(response["job_id"]).reason) and workdir.exists()


def test_w81_w82_recovered_cleanup_extent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(broker_mod, "CLEANUP_BATCH", 1)
    w = make_world(tmp_path)
    _, copy_id, workdir = evidence_copy(w)
    job_id = int(cleanup(w, copy_id)["job_id"])
    w.broker.step()  # the cleanup job deletes one entry per step at this batch size
    assert w.broker.copy_extent(copy_id, job_id) == "cleaning"  # one entry deleted, with its marker
    report = w.restart()
    assert any(f"copy {copy_id}: cleaning" in line for line in report.recovery)
    extent = w.broker.copy_extent(copy_id, job_id)
    assert extent == "cleaning"  # W-81: reconciled exactly
    survivors = [p for p in workdir.rglob("*") if p.is_file()]
    survivors[0].unlink()  # an entry vanished without a marker
    assert w.broker.copy_extent(copy_id, job_id) == "damaged"  # W-82
    report = w.restart()
    assert report.mode == "repair" and any("damaged" in line for line in report.recovery)


def test_copy_extent_with_unreadable_markers(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    _, copy_id, _ = evidence_copy(w)
    assert w.broker.copy_extent(copy_id, 99) == "registered"
    w.broker.markers.publish("cleanup", ("99", "00000001"), {"copy_id": copy_id, "path": "x"}, 0)
    marker = w.queue / "effects" / "cleanup" / "99" / "00000001"
    marker.write_bytes(b"junk")
    assert w.broker.copy_extent(copy_id, 99) == "damaged"
    register = w.queue / "effects" / "register" / copy_id
    register.write_bytes(b"junk")
    assert w.broker.copy_extent(copy_id, 99) == "damaged"
