"""The broker end to end on the fake host: start, jobs, frozen inputs, end proof, overrides, render
(B-1 to B-21, K-3, K-9 to K-12a, K-21 to K-24, K-32; witnesses W-5, W-7 to W-16, W-17, W-18, W-39,
W-41, W-45, W-51, W-66, W-67, W-85, W-86, W-88; controls C-1, C-2, C-4, C-13, C-17)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
import yaml

from minion_process.hostqueue import client, confirm
from minion_process.hostqueue.broker import Broker, BrokerRefused
from minion_process.hostqueue.framing import decode_single, encode
from minion_process.hostqueue.jobspec import SpecError, build_spec, drift

from .hostqueue_fake import FakeGit, FakeHost, pane_info
from .hostqueue_world import SHA, SHA2, World, make_world, policy_dict


def result(w: World, job_id: int, exit_code: int = 0, gate_end: int | None = 0) -> None:
    (w.queue / "jobs" / str(job_id) / "result").write_bytes(encode({"exit": exit_code, "gate_end": gate_end}))


def finish(w: World, job_id: int) -> None:
    spawned = next(s for s in w.host.spawned if s["group"] == w.job(job_id).spec["group"])
    w.host.finish(spawned["group"], spawned["runner"])
    w.broker.step()


# -- start and the single instance ----------------------------------------------------------------------


def test_w5_c1_one_broker_per_host(tmp_path: Path) -> None:
    host = FakeHost()
    first = Broker(tmp_path / "q1", host, FakeGit())
    first.start()
    with pytest.raises(BrokerRefused, match="another broker"):
        Broker(tmp_path / "q2", host, FakeGit()).start()  # a different folder changes nothing
    # C-1: without the single-instance check a second broker would run; the mutex refusal is the witness
    host.mutex_error = "access denied"
    with pytest.raises(BrokerRefused, match="mutex unavailable"):
        Broker(tmp_path / "q3", host, FakeGit()).start()


def test_queue_must_be_on_a_local_fixed_volume(tmp_path: Path) -> None:
    host = FakeHost(local_volume=None)
    with pytest.raises(BrokerRefused, match="local fixed volume"):
        Broker(tmp_path / "q", host, FakeGit()).start()
    assert not host.mutex_owned


def test_previous_broker_temporaries_only(tmp_path: Path) -> None:
    w = make_world(tmp_path, with_policy=False)
    (w.queue / "inbox" / ".tmp-client-1-abc").write_text("in progress")  # W-65: a client's temporary
    (w.queue / "effects" / ".tmp-broker-broker-old-1").write_text("old broker")
    w.restart()
    assert (w.queue / "inbox" / ".tmp-client-1-abc").exists()
    assert not (w.queue / "effects" / ".tmp-broker-broker-old-1").exists()


# -- policy ----------------------------------------------------------------------------------------------


def test_policy_needs_a_confirmed_challenge(tmp_path: Path) -> None:
    w = make_world(tmp_path, with_policy=False)
    assert w.submit()["error"] == "no policy in force"
    bad = w.request({"type": "policy-set", "policy": {"policy_id": "x"}})
    assert not bad["ok"] and "invalid policy" in bad["error"]
    wrong = w.request({"type": "policy-set", "policy": policy_dict(w.root, version=2)})
    assert not wrong["ok"] and "must be 1" in wrong["error"]
    challenge = w.request({"type": "policy-set", "policy": policy_dict(w.root), "decision": "link"})
    assert challenge["confirm_with"] == f"CONFIRM QUEUE {challenge['code']}"
    assert w.broker.policy is None  # nothing changes until the Owner confirms (W-67 first half)
    applied = w.confirm(challenge["code"])
    assert applied["ok"] and w.broker.policy is not None and w.broker.state.policy_version == 1


def test_w66_w67_c13_confirmation_channel(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    challenge = w.request({"type": "policy-set", "policy": policy_dict(w.root, version=2, limit=1)})
    code = challenge["code"]
    for prompt in (
        f"Codex w1:p2: CONFIRM QUEUE {code}",
        f"CONFIRM QUEUE {code} please",
        f"CONFIRM QUEUE {code[:7]}",
        "hello",
    ):
        assert confirm.handle({"hook_event_name": "UserPromptSubmit", "prompt": prompt}, w.queue) is None
    assert (
        confirm.handle({"hook_event_name": "PreToolUse", "prompt": f"CONFIRM QUEUE {code}"}, w.queue) is None
    )
    # C-13: a client verb cannot produce a hook confirmation, and the broker refuses any other origin
    with pytest.raises(ValueError, match="cannot send"):
        client.put(w.queue, {"type": "hook-confirm", "code": code})
    forged = client.put(w.queue, {"type": "hook-confirm", "code": code, "origin": "agent"}, _type_check=False)
    w.broker.step()
    assert (
        "only from the Owner's chat hook"
        in decode_single((w.queue / "outbox" / f"{forged}.res").read_bytes())["error"]
    )
    assert w.broker.policy is not None and w.broker.policy.limit == 2  # unchanged
    assert w.confirm("0" * 8)["error"] == "no challenge for that code"
    assert w.confirm(code)["ok"] and w.broker.policy.limit == 1  # W-66: exactly the bound effect
    assert w.confirm(code)["error"] == "challenge already used"


def test_expired_and_stale_generation_challenges(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    challenge = w.request({"type": "policy-set", "policy": policy_dict(w.root, version=2)})
    w.host.clock += 16 * 60
    assert w.confirm(challenge["code"])["error"] == "challenge expired"
    fresh = w.request({"type": "policy-set", "policy": policy_dict(w.root, version=2)})
    w.broker.generation += 1  # as if repair had written a new generation
    assert "another journal generation" in w.confirm(fresh["code"])["error"]


# -- submit, frozen inputs and refusals ------------------------------------------------------------------


def test_jobspec_refusals(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    full = {
        "profile": str(w.profile),
        "launcher": "rust",
        "target": "gate",
        "checkout": str(w.root / "repo"),
        "submitter": {"pane": "w1:p1", "session": "s1"},
    }
    assert "unknown class" in w.request({"type": "submit", "class": "weird", **full})["error"]
    assert (
        "profile unreadable"
        in w.request(
            {"type": "submit", "class": "build", **{**full, "profile": str(tmp_path / "none.yaml")}}
        )["error"]
    )
    assert "target 'missing'" in w.submit(target="missing")["error"]
    assert "controls-kind target" in w.submit("control", "gate", sha=SHA)["error"]
    assert (
        "controls-kind target" in w.submit("control", "reviewer", sha=SHA)["error"]
    )  # R003: no reviewer gate cache
    assert "never use a controls target" in w.submit("build", "controls")["error"]
    assert (
        "belongs to claude, not codex" in w.submit("build", "reviewer", session="s2", pane="w1:p2")["error"]
    )  # W-16
    assert "need --sha" in w.submit("evidence", "gate")["error"]
    assert "does not match its pane" in w.submit(session="forged")["error"]
    assert "cannot be read" in w.submit(pane="w9:p9")["error"]
    assert (
        "are required"
        in w.request(
            {
                "type": "submit",
                "class": "build",
                "profile": str(w.profile),
                "launcher": "rust",
                "target": "gate",
                "checkout": str(w.root / "repo"),
                "submitter": {},
            }
        )["error"]
    )
    outside = w.submit(checkout=str(tmp_path / "elsewhere"))
    assert "not contained" in outside["error"]  # W-24
    client.put(w.queue, {"type": "submit", "class": "weird", "request_id": "fixed", **full})
    w.broker.step()
    again = w.request({"type": "submit", "class": "weird", "request_id": "fixed", **full})
    assert again["duplicate"] and "unknown class" in again["error"]


def _edit_profile(w: World, edit: Any) -> None:
    data = yaml.safe_load(w.profile.read_text(encoding="utf-8"))
    edit(data)
    w.profile.write_text(yaml.safe_dump(data), encoding="utf-8")


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (lambda d: d.pop("build_queue"), "no build_queue"),
        (lambda d: d["build_queue"].update(policy_id="other"), "expects policy"),
        (lambda d: d["build_queue"].update(project="ghost"), "allow-list"),
        (lambda d: d["gates"]["rust"].pop("queue"), "no queue definition"),
        (lambda d: d["gates"]["rust"]["queue"].update(argv=[]), "non-empty list"),
        (lambda d: d["build_queue"]["targets"]["gate"].update(kind="odd"), "target kind"),
        (lambda d: d["gates"]["rust"]["queue"].update(source_globs=[]), "source_globs"),
        (lambda d: d["gates"]["rust"]["queue"].update(argv=["x", "--out=C:\\Windows\\x"]), "K-42"),
    ],
)
def test_profile_refusals(tmp_path: Path, edit: Any, message: str) -> None:
    w = make_world(tmp_path)
    _edit_profile(w, edit)
    assert message in w.submit()["error"]


def test_profile_must_be_a_mapping_of_yaml(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    w.profile.write_text("[1, 2", encoding="utf-8")
    assert "not YAML" in w.submit()["error"]
    w.profile.write_text("- 1\n", encoding="utf-8")
    assert "not a mapping" in w.submit()["error"]


def test_w13_c4_input_drift_refuses_at_launch(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    w.host.memory = 0  # hold admission so the job stays submitted
    job_id = w.submit()["job_id"]
    _edit_profile(w, lambda d: d["gates"]["rust"]["queue"].update(argv=["cargo", "build"]))
    w.host.memory = 64 * 1024**3
    w.broker.step()
    job = w.job(job_id)
    assert job.status == "refused" and "input drift" in str(job.reason) and "argv" in str(job.reason)
    assert not w.host.spawned  # C-4: with the freeze disabled the drifted launcher would have run
    assert drift({"a": 1}, {"a": 2, "b": 3}) == ["a", "b"]


def test_submitter_session_rechecked_at_launch(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    w.host.memory = 0
    job_id = w.submit()["job_id"]
    w.host.panes["w1:p1"] = pane_info("replaced")
    w.host.memory = 64 * 1024**3
    w.broker.step()
    assert w.job(job_id).status == "refused" and "refused at launch" in str(w.job(job_id).reason)


def test_build_spec_paths_and_mount_forms(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    assert w.broker.policy is not None
    _edit_profile(
        w,
        lambda d: d["gates"]["rust"]["queue"].update(
            argv=[
                "docker",
                "-v",
                {"slot": "{target}:/t", "access": "write"},
                {"slot": "--env={log}", "access": "write"},
            ],
            env={"A": {"slot": "{workdir}", "access": "write"}},
            container={"paths": ["/t"]},
        ),
    )
    request = {
        "class": "evidence",
        "profile": str(w.profile),
        "launcher": "rust",
        "target": "gate",
        "checkout": str(w.root / "repo"),
        "sha": SHA,
        "submitter": {"pane": "w1:p1", "session": "s1"},
    }
    spec = build_spec(request, w.broker.policy, "q", 5, pane_info("s1"))
    assert spec["argv"][2].endswith(":/t") and spec["env"]["A"].endswith("q-job-5")
    assert spec["argv"][3] == "--env=" + spec["log"]
    _edit_profile(w, lambda d: d["gates"]["rust"]["queue"].update(argv=["docker", "-v", "C:\\Windows:/w"]))
    with pytest.raises(SpecError, match="K-42"):
        build_spec(request, w.broker.policy, "q", 5, pane_info("s1"))
    with pytest.raises(SpecError, match="cannot be read"):
        build_spec(request, w.broker.policy, "q", 5, None)


# -- lifecycle and the end proof -------------------------------------------------------------------------


def test_w12_build_freshness_then_shared_lease(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    lib = w.root / "repo" / "src" / "lib.rs"
    readme = w.root / "repo" / "README.md"
    os.utime(lib, (1_000_000, 1_000_000))
    os.utime(readme, (1_000_000, 1_000_000))
    job_id = w.submit()["job_id"]
    assert lib.stat().st_mtime > 1_000_000 and readme.stat().st_mtime == 1_000_000  # W-51: only sources
    held = dict(w.broker.state.held_leases())
    assert held[str(w.job(job_id).spec["checkout"])] == "shared"  # K-12a: exclusive, touch, then shared
    second = w.submit(target="gate2")
    # The second build's preparation needs the checkout exclusively, so it waits for the first (K-12a).
    assert w.job(second["job_id"]).status == "submitted"
    status = w.request({"type": "status", "job_id": second["job_id"]})
    assert status["jobs"][0]["waits"].startswith("resource held")
    result(w, job_id)
    finish(w, job_id)
    assert w.job(second["job_id"]).status == "running"


def test_w9_w15_natural_end_and_never_evidence(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    job_id = w.submit()["job_id"]
    result(w, job_id, 0, 0)
    finish(w, job_id)
    job = w.job(job_id)
    assert (
        job.status == "ended"
        and job.outcome == "passed"
        and not job.eligible
        and "never evidence" in str(job.reason)
    )


def test_exit_and_gate_end_must_agree(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    job_id = w.submit("evidence", sha=SHA)["job_id"]
    result(w, job_id, 0, None)
    finish(w, job_id)
    assert w.job(job_id).outcome == "failed" and not w.job(job_id).eligible


def test_w14_evidence_copy_must_match_sha_and_stay_clean(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    job_id = w.submit("evidence", sha=SHA)["job_id"]
    w.git.clean_state[str(w.job(job_id).spec["workdir"])] = False
    result(w, job_id)
    finish(w, job_id)
    job = w.job(job_id)
    assert job.outcome == "passed" and not job.eligible and "post-run copy check" in str(job.reason)


def test_evidence_preparation_failures_refuse_before_any_workload(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    from minion_process.hostqueue.resources import canonical

    w.git.heads[canonical(w.root / "exec" / "host-test-job-1")] = (
        SHA2  # the fresh copy is at the wrong commit
    )
    job_id = w.submit("evidence", sha=SHA)["job_id"]
    assert w.job(job_id).status == "refused" and "fresh copy" in str(w.job(job_id).reason)
    w.git.add_error = OSError("worktree add failed")
    job_id = w.submit("evidence", sha=SHA)["job_id"]
    assert w.job(job_id).status == "refused" and not w.host.spawned
    w.git.add_error = None
    (w.root / "exec" / "host-test-job-3").mkdir()
    job_id = w.submit("evidence", sha=SHA)["job_id"]
    assert "already exists" in str(w.job(job_id).reason)


def test_w12_controls_use_their_own_copies(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    a = w.submit("control", "controls", sha=SHA)["job_id"]
    w.host.memory = 64 * 1024**3
    assert w.job(a).spec["run_dir"] != str(w.root / "repo")
    assert w.job(a).spec["env"]["CARGO_TARGET_DIR"].endswith("controls")


def test_w8_c2_runner_dead_while_workload_lives(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    job_id = w.submit()["job_id"]
    spawned = w.host.spawned[-1]
    w.host.processes[(spawned["runner"].pid, spawned["runner"].start)] = (
        False  # runner gone, group still active
    )
    w.broker.step()
    job = w.job(job_id)
    assert job.status == "uncertain"  # C-2: a runner-alive check alone would have released the resources
    ev = w.submit("evidence", "gate2", sha=SHA)
    assert w.job(ev["job_id"]).status == "submitted"
    w.host.finish(spawned["group"])
    w.broker.step()
    assert job.status == "ended" and job.outcome == "unknown-outcome"
    assert w.job(ev["job_id"]).status == "running"


def test_containers_count_as_workload(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    job_id = w.submit()["job_id"]
    spawned = w.host.spawned[-1]
    w.host.containers[w.job(job_id).spec["job_label"]] = True
    w.host.finish(spawned["group"], None)
    w.broker.step()
    assert w.job(job_id).status == "running"
    w.host.containers[w.job(job_id).spec["job_label"]] = False
    w.host.processes[(spawned["runner"].pid, spawned["runner"].start)] = False
    w.broker.step()
    assert w.job(job_id).status == "ended"


def test_inspection_failure_makes_a_running_job_uncertain(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    job_id = w.submit()["job_id"]
    w.host.group_query_error = True
    w.broker.step()
    assert w.job(job_id).status == "uncertain"
    w.broker.step()  # still unknown: stays uncertain
    assert w.job(job_id).status == "uncertain"
    result(w, job_id)  # a result without a verified drain proves nothing (R002)
    w.broker.step()
    assert w.job(job_id).status == "uncertain"
    (w.queue / "jobs" / str(job_id) / "result").write_bytes(
        encode({"exit": 0, "gate_end": 0, "drained": True})
    )
    w.broker.step()
    assert w.job(job_id).status == "uncertain"  # the runner process itself is still alive
    runner = w.host.spawned[-1]["runner"]
    w.host.processes[(runner.pid, runner.start)] = False
    w.broker.step()
    assert w.job(job_id).status == "ended"


def test_spawn_failures(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    w.host.spawn_error = OSError("assign failed")
    job_id = w.submit()["job_id"]
    assert w.job(job_id).status == "uncertain"  # the group existed: cannot prove nothing started
    w.host.spawn_error = OSError("create failed")
    w.host.spawn_creates_group = False
    other = w.submit(target="gate2")["job_id"]
    assert w.job(other).status in ("refused", "submitted")


def test_w84_launch_marker_collision_never_launches_twice(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    w.broker.markers.publish("launch", ("1",), {"group": "x"}, 0)
    job_id = w.submit()["job_id"]
    assert w.job(job_id).status == "uncertain" and not w.host.spawned


# -- release and status ----------------------------------------------------------------------------------


def test_w45_release_is_human_confirmed_and_ineligible(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    job_id = w.submit()["job_id"]
    assert "only to an uncertain job" in w.request({"type": "release", "job_id": job_id})["error"]
    w.host.group_query_error = True
    w.broker.step()
    challenge = w.request({"type": "release", "job_id": job_id})
    w.host.group_query_error = False
    w.host.groups[w.job(job_id).spec["group"]] = True
    applied = w.confirm(challenge["code"])
    assert applied["ok"]
    job = w.job(job_id)
    assert job.status == "ended" and job.outcome == "human-confirmed" and not job.eligible


def test_stale_release_challenge(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    job_id = w.submit()["job_id"]
    w.host.group_query_error = True
    w.broker.step()
    challenge = w.request({"type": "release", "job_id": job_id})
    w.host.group_query_error = False
    result(w, job_id)
    spawned = w.host.spawned[-1]
    w.host.finish(spawned["group"], spawned["runner"])
    w.broker.step()  # proven ended meanwhile
    assert "stale" in w.confirm(challenge["code"])["error"]


def test_status_cancel_unretain(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    w.host.memory = 0
    job_id = w.submit()["job_id"]
    status = w.request({"type": "status", "job_id": job_id})
    assert status["jobs"][0]["waits"].startswith("memory")
    assert (
        "submitting session"
        in w.request({"type": "cancel", "job_id": job_id, "submitter": {"session": "other"}})["error"]
    )
    assert w.request({"type": "cancel", "job_id": job_id, "submitter": {"session": "s1"}})["ok"]
    assert (
        "only a submitted"
        in w.request({"type": "cancel", "job_id": job_id, "submitter": {"session": "s1"}})["error"]
    )
    assert "not retained" in w.request({"type": "unretain", "job_id": job_id})["error"]
    w.host.memory = 64 * 1024**3
    ev = w.submit("evidence", sha=SHA)["job_id"]
    result(w, ev)
    finish(w, ev)
    assert w.request({"type": "unretain", "job_id": ev})["ok"]
    odd = client.put(w.queue, {"type": "nonsense"}, _type_check=False)
    w.broker.step()
    assert decode_single((w.queue / "outbox" / f"{odd}.res").read_bytes())["error"].startswith(
        "unknown request type"
    )


def test_w20_malformed_requests_are_rejected_alone(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    (w.queue / "inbox" / "bad.req").write_bytes(b"garbage")
    (w.queue / "inbox" / "mismatch.req").write_bytes(encode({"request_id": "other", "type": "status"}))
    (w.queue / "inbox" / "note.txt").write_text("ignored")
    good = w.submit()
    assert good["ok"]
    assert (w.queue / "rejected" / "bad.req").exists() and "unreadable" in (
        w.queue / "rejected" / "bad.reason"
    ).read_text()
    assert "does not match" in (w.queue / "rejected" / "mismatch.reason").read_text()


# -- render / undelivered (K-3, K-32) --------------------------------------------------------------------


def test_w41_w85_w86_render_attempts(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    assert "needs the hand-off text" in w.request({"type": "render", "text": ""})["error"]
    first = w.request({"type": "render", "text": "hand-off", "pane": "w1:p2", "session": "s"})
    assert first["attempt"] == 1 and "may-have-printed" in first["delivery"]
    assert "already rendered" in w.request({"type": "render", "text": "hand-off"})["error"]
    w.restart()
    assert (
        "already rendered" in w.request({"type": "render", "text": "hand-off"})["error"]
    )  # W-41 across restart
    assert (
        "latest attempt" in w.request({"type": "undelivered", "hash": first["hash"], "attempt": 2})["error"]
    )
    assert w.request({"type": "undelivered", "hash": first["hash"], "attempt": 1})["ok"]
    assert w.request({"type": "undelivered", "hash": first["hash"], "attempt": 1})["duplicate"]
    second = w.request({"type": "render", "text": "hand-off"})
    assert second["attempt"] == 2  # W-85: the authorized retry
    assert "already rendered" in w.request({"type": "render", "text": "hand-off"})["error"]  # W-86


def test_c17_one_marker_per_handoff_would_block_the_retry(tmp_path: Path) -> None:
    """C-17: with the revision-6 key (hash only), the authorized retry collides at exclusive create."""
    from minion_process.hostqueue.markers import MarkerExists, Markers

    m = Markers(tmp_path, FakeHost(), "x")
    m.publish("render", ("h",), {}, 0)
    with pytest.raises(MarkerExists):
        m.publish("render", ("h",), {}, 0)
    m.publish("render", ("h2", "1"), {}, 0)
    m.publish("render", ("h2", "2"), {}, 0)  # the per-attempt key admits the authorized retry


def test_repair_requests_outside_repair_mode(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    assert "not in repair mode" in w.request({"type": "repair-quarantine"})["error"]
    assert "resume needs repair mode" in w.request({"type": "repair-resume"})["error"]
    report = w.request({"type": "repair-inspect"})["report"]
    assert report["mode"] == "normal" and report["anomaly"] is None
