"""First end-to-end pass through the broker on the fake host: policy, submit, admit, launch, end."""

from __future__ import annotations

from pathlib import Path

from .hostqueue_world import SHA, make_world


def test_build_job_lifecycle(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    assert w.broker.policy is not None and w.broker.policy.limit == 2
    response = w.submit("build", "gate")
    assert response["ok"], response
    job = w.job(response["job_id"])
    assert job.status == "running"
    spawned = w.host.spawned[-1]
    assert spawned["env"]["CARGO_TARGET_DIR"].endswith("gate")
    w.host.finish(spawned["group"], spawned["runner"])
    w.broker.step()
    assert job.status == "ended" and job.outcome == "unknown-outcome"


def test_evidence_job_eligible(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    response = w.submit("evidence", "gate", sha=SHA)
    assert response["ok"], response
    job = w.job(response["job_id"])
    assert job.status == "running", job.reason
    from minion_process.hostqueue.framing import encode

    (w.queue / "jobs" / str(job.job_id) / "result").write_bytes(encode({"exit": 0, "gate_end": 0}))
    spawned = w.host.spawned[-1]
    w.host.finish(spawned["group"], spawned["runner"])
    w.broker.step()
    assert job.status == "ended" and job.outcome == "passed" and job.eligible and job.retain
