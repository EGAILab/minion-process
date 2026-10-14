"""Witnesses and executed negative controls for Codex's implementation review round 7 (PROC-KIT-P3B-R002,
R003, R005, R006, R008, R009, R010), and real substitutions for the controls C-1, C-2, C-4 and C-9.

A "control" test here swaps the agreed rule for the wrong one and asserts that the hazard appears. Its
paired witness asserts the hazard does not appear with the real code."""

from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import Any

import pytest
import yaml

from minion_process.hostqueue import broker as broker_mod
from minion_process.hostqueue import client, contain, fsops, jobspec, requests
from minion_process.hostqueue import state as state_mod
from minion_process.hostqueue.broker import Broker, BrokerRefused
from minion_process.hostqueue.framing import decode_single, encode
from minion_process.hostqueue.hostos import ProcessIdentity, SpawnFailed

from .hostqueue_fake import FakeGit, FakeHost
from .hostqueue_world import SHA, World, make_world

PACKAGE = Path(__file__).resolve().parent.parent / "minion_process" / "hostqueue"


def edit_profile(w: World, change: Any) -> None:
    data = yaml.safe_load(w.profile.read_text(encoding="utf-8"))
    change(data)
    w.profile.write_text(yaml.safe_dump(data), encoding="utf-8")


def finish_result(w: World, job_id: int, drained: bool) -> None:
    (w.queue / "jobs" / str(job_id) / "result").write_bytes(
        encode({"exit": 0, "gate_end": 0, "drained": drained})
    )


# == R002: drain provenance and stray processes ==========================================================


def test_r002_result_without_verified_drain_is_not_proof(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    job_id = w.submit()["job_id"]
    runner = w.host.spawned[-1]["runner"]
    w.host.processes[(runner.pid, runner.start)] = False
    w.host.group_query_error = True
    w.broker.step()
    finish_result(w, job_id, drained=False)
    w.broker.step()
    assert w.job(job_id).status == "uncertain"


def test_r002_control_accepting_any_result_releases_unproven_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = make_world(tmp_path)
    job_id = w.submit()["job_id"]
    runner = w.host.spawned[-1]["runner"]
    w.host.processes[(runner.pid, runner.start)] = False
    w.host.group_query_error = True
    w.broker.step()
    finish_result(w, job_id, drained=False)
    real = Broker._read_result
    monkeypatch.setattr(Broker, "_read_result", lambda self, j: {**(real(self, j) or {}), "drained": True})
    w.broker.step()
    assert w.job(job_id).status == "ended"  # the hazard: an unverified result released the resources


def test_r002_stray_process_from_a_failed_spawn_stays_uncertain(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    stray = ProcessIdentity(9001, 5)
    w.host.processes[(stray.pid, stray.start)] = True
    w.host.spawn_error = SpawnFailed("AssignProcessToJobObject failed", stray)
    job_id = w.submit()["job_id"]
    job = w.job(job_id)
    assert job.status == "uncertain" and job.runner == {"pid": 9001, "start": 5}
    w.host.groups[job.spec["group"]] = False
    w.broker.step()
    assert job.status == "uncertain"  # the stray process outside the job is alive
    w.host.processes[(stray.pid, stray.start)] = None
    w.broker.step()
    assert job.status == "uncertain"  # unknown is never ended
    w.host.processes[(stray.pid, stray.start)] = False
    w.broker.step()
    assert job.status == "ended" and job.outcome == "unknown-outcome"


def test_r002_control_losing_the_stray_identity_ends_live_work(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    stray = ProcessIdentity(9002, 5)
    w.host.processes[(stray.pid, stray.start)] = True
    w.host.spawn_error = OSError("AssignProcessToJobObject failed")  # the identity is lost
    job_id = w.submit()["job_id"]
    w.host.groups[w.job(job_id).spec["group"]] = False
    w.broker.step()
    assert w.job(job_id).status == "ended"  # the hazard: ended while process 9002 still runs


# == R003: environment and resource binding ===============================================================


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda q: q.update(env={"CARGO_TARGET_DIR": "C:\\elsewhere"}), "bound variable"),
        (lambda q: q.update(env={"OUT": "C:\\elsewhere"}), "not contained"),
        (lambda q: q.update(env={"OUT": "{target}\\..\\gate2"}), "not contained"),
        (lambda q: q.update(env={"TMP": "{workdir}"}), "bound variable"),
        (lambda q: q.update(cache_env={"CARGO_HOME": "undeclared"}), "does not declare"),
        (lambda q: q.update(argv=["cargo", "--out", "{target}"]), None),
    ],
)
def test_r003_environment_binding(tmp_path: Path, change: Any, message: str | None) -> None:
    w = make_world(tmp_path)
    edit_profile(w, lambda d: change(d["gates"]["rust"]["queue"]))
    response = w.submit()
    if message is None:
        assert response["ok"], response
    else:
        assert message in response["error"]


def test_r003_unleased_contained_paths_are_refused(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    other = str(w.root / "targets" / "gate2")
    edit_profile(w, lambda d: d["gates"]["rust"]["queue"].update(env={"OUT": other}))
    assert "not a leased resource" in w.submit()["error"]
    edit_profile(
        w, lambda d: d["gates"]["rust"]["queue"].update(env={}, argv=["docker", "-v", f"{other}:/x"])
    )
    assert "not a leased resource" in w.submit()["error"]


def test_r003_caches_are_declared_and_leased_shared(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    cache = w.root / "cache" / "cargo-home"
    cache.mkdir(parents=True)
    edit_profile(
        w,
        lambda d: (
            d["build_queue"].update(caches={"cargo-home": str(cache)}),
            d["gates"]["rust"]["queue"].update(cache_env={"CARGO_HOME": "cargo-home"}),
        ),
    )
    job = w.job(w.submit()["job_id"])
    env = w.host.spawned[-1]["env"]
    assert env["CARGO_HOME"].lower() == str(cache).lower()
    assert [str(cache).lower(), "shared"] in [[p.lower(), m] for p, m in job.spec["leases"]]
    assert env["TMP"] == env["TEMP"] == job.spec["tmp"] and Path(job.spec["tmp"]).is_dir()


def test_r003_effective_environment_is_frozen_and_nothing_else_is_inherited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MINION_TEST_SECRET", "leak")
    w = make_world(tmp_path)
    w.submit()
    env = w.host.spawned[-1]["env"]
    assert "MINION_TEST_SECRET" not in env and "PATH" in env


def test_r003_inherited_environment_drift_refuses_at_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = make_world(tmp_path)
    w.host.memory = 0
    job_id = w.submit()["job_id"]
    monkeypatch.setenv("PATH", os.environ.get("PATH", "") + os.pathsep + "E:\\drifted")
    w.host.memory = 64 * 1024**3
    w.broker.step()
    assert w.job(job_id).status == "refused" and "env" in str(w.job(job_id).reason)


def test_r003_inherit_env_may_not_name_a_bound_variable(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    edit_profile(w, lambda d: d["build_queue"].update(inherit_env=["PATH", "TMP"]))
    assert "bound variable TMP" in w.submit()["error"]
    edit_profile(w, lambda d: d["build_queue"].update(inherit_env="PATH"))
    assert "list of variable names" in w.submit()["error"]
    edit_profile(w, lambda d: d["build_queue"].update(inherit_env=["PATH"], caches=[1]))
    assert "caches must be a mapping" in w.submit()["error"]
    edit_profile(
        w, lambda d: (d["build_queue"].update(caches={}), d["gates"]["rust"]["queue"].update(cache_env=[1]))
    )
    assert "cache_env must be a mapping" in w.submit()["error"]


def test_r003_reviewer_owned_controls_target(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    own = w.root / "targets" / "claude-controls"
    own.mkdir()
    edit_profile(
        w,
        lambda d: d["build_queue"]["targets"].update(
            {"claude-controls": {"path": str(own), "kind": "controls", "owner_agent": "claude"}}
        ),
    )
    assert w.submit("control", "claude-controls", sha=SHA)["ok"]
    assert (
        "belongs to claude"
        in w.submit("control", "claude-controls", sha=SHA, session="s2", pane="w1:p2")["error"]
    )


def test_c4_control_freeze_disabled_runs_the_drifted_launcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = make_world(tmp_path)
    w.host.memory = 0
    w.submit()
    edit_profile(w, lambda d: d["gates"]["rust"]["queue"].update(argv=["cargo", "build", "--drifted"]))
    monkeypatch.setattr(broker_mod, "drift", lambda original, rebuilt: [])
    w.host.memory = 64 * 1024**3
    w.broker.step()
    assert w.host.spawned  # the hazard: launched although its inputs drifted (W-13 refuses it)


# == R005: retry authorization reconciled positively ======================================================


def _render_with_grant(w: World) -> str:
    first = w.request({"type": "render", "text": "hand-off"})
    assert w.request({"type": "undelivered", "hash": first["hash"], "attempt": 1})["ok"]
    return str(first["hash"])


def test_r005_intact_journal_grant_with_unreadable_marker_is_revoked(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    handoff = _render_with_grant(w)
    marker = w.queue / "effects" / "undelivered" / handoff / "1"
    marker.write_bytes(marker.read_bytes()[:-2])
    report = w.restart()
    assert report.mode == "repair" and any("authorization not readable" in line for line in report.recovery)
    w.confirm(w.request({"type": "repair-quarantine"})["code"])
    w.confirm(w.request({"type": "repair-resume"})["code"])
    assert "already rendered" in w.request({"type": "render", "text": "hand-off"})["error"]


def test_r005_intact_journal_grant_with_missing_marker_is_revoked(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    handoff = _render_with_grant(w)
    (w.queue / "effects" / "undelivered" / handoff / "1").unlink()  # outside the fault model; fail closed
    report = w.restart()
    assert report.mode == "repair"
    w.confirm(w.request({"type": "repair-quarantine"})["code"])
    w.confirm(w.request({"type": "repair-resume"})["code"])
    assert "already rendered" in w.request({"type": "render", "text": "hand-off"})["error"]


def test_r005_control_keeping_journal_grants_reauthorizes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = make_world(tmp_path)
    handoff = _render_with_grant(w)
    marker = w.queue / "effects" / "undelivered" / handoff / "1"
    marker.write_bytes(marker.read_bytes()[:-2])
    monkeypatch.setattr(Broker, "_reconcile_renders", lambda self, outcomes, add, unsafe: None)
    assert w.restart().mode == "normal"
    assert w.request({"type": "render", "text": "hand-off"})["attempt"] == 2  # the hazard


def test_r005_a_consumed_grant_is_never_reauthorized(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    _render_with_grant(w)
    assert w.request({"type": "render", "text": "hand-off"})["attempt"] == 2
    report = w.restart()
    assert report.mode == "normal"
    assert "already rendered" in w.request({"type": "render", "text": "hand-off"})["error"]


def test_r005_restored_retry_needs_its_earlier_grant(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    handoff = _render_with_grant(w)
    w.request({"type": "render", "text": "hand-off"})
    w.broker.markers.publish("render", (handoff, "3"), {}, 0)  # a published attempt 3 with no grant for 2
    report = w.restart()
    assert report.mode == "repair" and any("without a readable grant" in line for line in report.recovery)


def test_r005_lost_grant_and_retry_records_are_restored_from_markers(tmp_path: Path) -> None:
    from .test_hostqueue_recovery import cut_after

    w = make_world(tmp_path)
    _render_with_grant(w)
    assert w.request({"type": "render", "text": "hand-off"})["attempt"] == 2
    cut_after(w, "render", None, "none")  # keep through the last render record, then cut it as a tail
    path = w.queue / "journal" / f"gen-{w.broker.generation}.log"
    from minion_process.hostqueue.journal import parse

    replay = parse(path.read_bytes())
    first_render = next(i for i, r in enumerate(replay.records) if r["kind"] == "render")
    path.write_bytes(path.read_bytes()[: replay.ends[first_render]] + b"MPQ1 torn")
    report = w.restart()
    assert report.mode == "normal", report.recovery
    assert w.broker.state.renders[next(iter(w.broker.state.renders))] == 2
    assert "already rendered" in w.request({"type": "render", "text": "hand-off"})["error"]


def test_r005_empty_render_folder_is_ignored(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    (w.queue / "effects" / "render" / ("f" * 64)).mkdir(parents=True)
    assert w.restart().mode == "normal"


# == R006: cleanup contract ================================================================================


def _copy(w: World) -> tuple[str, Path]:
    job_id = int(w.submit("evidence", sha=SHA)["job_id"])
    job = w.job(job_id)
    (w.queue / "jobs" / str(job_id) / "result").write_bytes(encode({"exit": 1, "gate_end": 1}))
    w.host.finish(job.spec["group"], w.host.spawned[-1]["runner"])
    w.broker.step()
    return str(job.spec["job_label"]), Path(str(job.spec["workdir"]))


def _cleanup(w: World, copy_id: str, apply: bool | None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "type": "submit",
        "class": "cleanup",
        "profile": str(w.profile),
        "copies": [copy_id],
        "submitter": {"pane": "w1:p1", "session": "s1"},
    }
    if apply is not None:
        body["apply"] = apply
    return w.request(body)


def test_r006_cleanup_is_a_dry_run_unless_applied(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    copy_id, workdir = _copy(w)
    job = w.job(_cleanup(w, copy_id, None)["job_id"])
    w.broker.step()
    assert job.outcome == "dry-run" and workdir.exists()
    report = (w.queue / "jobs" / str(job.job_id) / "report").read_text()
    assert "would remove" in report and str(workdir).lower() in report.lower()
    assert w.broker.state.copies[copy_id]["state"] == "registered"
    applied = w.job(_cleanup(w, copy_id, True)["job_id"])
    w.broker.step()
    assert applied.outcome == "passed" and not workdir.exists()


def test_r006_late_submission_naming_an_actively_cleaned_copy_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(broker_mod, "CLEANUP_BATCH", 1)
    w = make_world(tmp_path)
    copy_id, workdir = _copy(w)
    job = w.job(_cleanup(w, copy_id, True)["job_id"])
    w.broker.step()
    assert job.status == "running"
    late = w.submit("build", "gate2", checkout=str(workdir))
    assert "leased by cleanup job" in late["error"]


def test_r006_late_reference_stops_the_next_batch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(broker_mod, "CLEANUP_BATCH", 1)
    w = make_world(tmp_path)
    copy_id, workdir = _copy(w)
    job = w.job(_cleanup(w, copy_id, True)["job_id"])
    w.broker.step()
    (w.root / "incidents" / "new.md").write_text(f"keep {workdir}\n", encoding="utf-8")
    w.broker.step()
    assert job.outcome == "failed" and "referenced in" in str(job.reason) and workdir.exists()


@pytest.mark.parametrize(
    ("setup", "message"),
    [
        (lambda w, p: w.git.clean_state.__setitem__(str(p), False), "not a clean worktree"),
        (lambda w, p: w.git.unpushed_commits.__setitem__(str(p), ["c1"]), "not reachable from a remote"),
        (lambda w, p: w.git.unpushed_commits.__setitem__(str(p), None), "reachability unknown"),
    ],
)
def test_r006_git_predicates(tmp_path: Path, setup: Any, message: str) -> None:
    w = make_world(tmp_path)
    copy_id, workdir = _copy(w)
    from minion_process.hostqueue.resources import canonical

    setup(w, canonical(workdir))
    job = w.job(_cleanup(w, copy_id, True)["job_id"])
    w.broker.step()
    assert message in str(job.reason) and workdir.exists()


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda q: q.pop("cleanup_references"), "must declare"),
        (lambda q: q["cleanup_references"].update(work_packages="cmd"), "must be a command"),
        (lambda q: q["cleanup_references"].update(work_packages=["no-such-command-xyz"]), "unreadable"),
        (
            lambda q: q["cleanup_references"].update(work_packages=["python", "-c", "raise SystemExit(3)"]),
            "exit 3",
        ),
        (lambda q: q["cleanup_references"].update(authority_cache=[]), "at least one path"),
    ],
)
def test_r006_reference_set_must_be_complete_and_readable(tmp_path: Path, change: Any, message: str) -> None:
    w = make_world(tmp_path)
    copy_id, workdir = _copy(w)
    edit_profile(w, lambda d: change(d["build_queue"]))
    job = w.job(_cleanup(w, copy_id, True)["job_id"])
    w.broker.step()
    assert message in str(job.reason) and workdir.exists()


def test_r006_work_package_states_mention_the_copy(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    copy_id, workdir = _copy(w)
    edit_profile(
        w,
        lambda d: d["build_queue"]["cleanup_references"].update(
            work_packages=["python", "-c", f"print({str(workdir)!r})"]
        ),
    )
    job = w.job(_cleanup(w, copy_id, True)["job_id"])
    w.broker.step()
    assert "open work packages" in str(job.reason)


def test_r006_protected_store_overlap(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    copy_id, workdir = _copy(w)
    edit_profile(
        w,
        lambda d: d["build_queue"]["targets"].update(
            {"overlap": {"path": str(workdir / "sub"), "kind": "gate"}}
        ),
    )
    job = w.job(_cleanup(w, copy_id, True)["job_id"])
    w.broker.step()
    assert "protected store" in str(job.reason) and workdir.exists()


def test_r006_control_without_the_predicates_removes_a_referenced_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = make_world(tmp_path)
    copy_id, workdir = _copy(w)
    (w.root / "incidents" / "keep.md").write_text(f"keep {workdir}\n", encoding="utf-8")
    monkeypatch.setattr(Broker, "_cleanup_predicates", lambda self, job: None)
    w.job(_cleanup(w, copy_id, True)["job_id"])
    w.broker.step()
    assert not workdir.exists()  # the hazard


# == R008: challenge expiry bound to a boot ===============================================================


def test_r008_a_challenge_from_an_earlier_boot_is_refused(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    challenge = w.request({"type": "policy-set", "policy": {**_policy(w, 2)}})
    w.host.boot = "boot-2"
    w.host.clock = 10.0  # a new boot's monotonic clock starts low: the old deadline looks far away
    w.restart()
    assert w.confirm(challenge["code"])["error"] == "challenge expired"
    w.host.boot = None
    fresh = w.request({"type": "policy-set", "policy": {**_policy(w, 2)}})
    assert w.confirm(fresh["code"])["error"] == "challenge expired"  # boot unknown: conservatively expired


def test_r008_control_without_the_boot_binding_revives_the_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = make_world(tmp_path)
    challenge = w.request({"type": "policy-set", "policy": {**_policy(w, 2)}})
    w.host.boot = "boot-2"
    w.host.clock = 10.0
    w.restart()
    monkeypatch.setattr(FakeHost, "boot_id", lambda self: "boot-1")  # the old rule: no boot comparison
    assert w.confirm(challenge["code"])["ok"]  # the hazard


def _policy(w: World, version: int) -> dict[str, Any]:
    from .hostqueue_world import policy_dict

    return policy_dict(w.root, version=version)


# == R009: containment proof covers the root and every mutation ============================================


def test_r009_root_and_ancestors_are_proved(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link-root"
    from .test_hostqueue_storage import _make_dir_link

    _make_dir_link(link, real)
    with pytest.raises(contain.Contained, match="link or reparse"):
        contain.assert_inside([link], link / "x")  # the root itself is a reparse point
    deep = tmp_path / "a" / "b"
    deep.mkdir(parents=True)
    with pytest.raises(contain.Contained, match="link or reparse"):
        contain.assert_inside([link / "inner"], link / "inner" / "x")  # an ancestor of the root


def test_r009_root_inspection_failure_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "root"
    root.mkdir()
    real_lstat = os.lstat

    def denied(path: Any) -> Any:
        if str(path) == str(root):
            raise PermissionError("denied")
        return real_lstat(path)

    monkeypatch.setattr(contain.os, "lstat", denied)
    with pytest.raises(contain.Contained, match="cannot inspect"):
        contain.assert_inside([root], root / "x")


MUTATIONS = ("mkdir", "open", "replace", "rename", "unlink", "rmdir", "utime", "write")


def _intercept(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    for name in MUTATIONS:
        monkeypatch.setattr(fsops.os, name, lambda *a, _n=name, **k: calls.append(_n))

    def denied(path: Any) -> Any:
        raise PermissionError("denied")

    monkeypatch.setattr(contain.os, "lstat", denied)
    return calls


def test_r009_no_mutation_runs_without_a_proof(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "q"
    calls = _intercept(monkeypatch)
    operations = [
        lambda: fsops.mkdir([root], root / "a"),
        lambda: fsops.write_new([root], root / "f", b"x"),
        lambda: fsops.append([root], root / "j", b"x"),
        lambda: fsops.replace([root], root / "s", root / "d"),
        lambda: fsops.publish([root], root / "s", root / "d", lambda s, d: calls.append("publish")),
        lambda: fsops.unlink([root], root / "f"),
        lambda: fsops.rmdir([root], root / "d"),
        lambda: fsops.utime([root], root / "f"),
        lambda: fsops.open_append([root], root / "log"),
    ]
    for operation in operations:
        with pytest.raises(contain.Contained):
            operation()
    assert calls == []


def test_r009_control_without_the_proof_mutates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "q"
    calls = _intercept(monkeypatch)
    monkeypatch.setattr(fsops, "assert_inside", lambda roots, target, final_entry=False: target)
    fsops.unlink([root], root / "f")
    assert calls == ["unlink"]  # the hazard


def test_r009_broker_and_markers_write_nothing_when_inspection_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = make_world(tmp_path)
    calls = _intercept(monkeypatch)
    with pytest.raises(contain.Contained):
        w.broker.markers.publish("launch", ("77",), {}, 0)
    with pytest.raises(contain.Contained):
        w.broker._record("mode", mode="normal")
    with pytest.raises(contain.Contained):
        client.put(w.queue, {"type": "status"})
    assert calls == []


def test_r009_static_no_direct_mutation_outside_fsops() -> None:
    forbidden_os = {
        "open",
        "replace",
        "rename",
        "unlink",
        "remove",
        "rmdir",
        "mkdir",
        "makedirs",
        "utime",
        "removedirs",
    }
    forbidden_methods = {
        "write_bytes",
        "write_text",
        "mkdir",
        "unlink",
        "rmdir",
        "touch",
        "rename",
        "replace",
    }
    offences: list[str] = []
    for path in PACKAGE.glob("*.py"):
        if path.name == "fsops.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute):
                owner = func.value.id if isinstance(func.value, ast.Name) else ""
                if owner == "os" and func.attr in forbidden_os:
                    offences.append(f"{path.name}: os.{func.attr}")
                elif (
                    owner not in ("fsops", "os", "self", "k32", "subprocess")
                    and func.attr in forbidden_methods
                    # str.replace takes two arguments; a path rename or replace takes exactly one
                    and (func.attr not in ("replace", "rename") or len(node.args) == 1)
                ):
                    offences.append(f"{path.name}: .{func.attr}")
            if isinstance(func, ast.Name) and func.id == "open":
                offences.append(f"{path.name}: open")
    assert offences == []


# == R010: malformed requests are rejected alone ===========================================================


MALFORMED = [
    {"type": "cancel", "job_id": []},
    {"type": "cancel", "job_id": 1, "submitter": []},
    {"type": "submit", "class": "build", "profile": "p", "submitter": ["x"]},
    {"type": "submit", "class": "build", "profile": "p", "submitter": {}, "launcher": ["x"]},
    {"type": "submit", "class": "cleanup", "profile": "p", "submitter": {}, "copies": "x"},
    {"type": "submit", "class": "cleanup", "profile": "p", "submitter": {}, "copies": ["x"], "apply": "yes"},
    {
        "type": "submit",
        "class": "build",
        "profile": "p",
        "submitter": {},
        "launcher": "l",
        "target": "t",
        "checkout": "c",
        "sha": 5,
    },
    {"type": "submit", "class": 3},
    {"type": "submit", "class": "build", "profile": ""},
    {"type": "submit", "class": "build", "profile": "p", "submitter": {"pane": 3}},
    {"type": "undelivered", "hash": "h", "attempt": "1"},
    {"type": "undelivered", "hash": "", "attempt": 1},
    {"type": "undelivered", "hash": "h", "attempt": 1, "session": 3},
    {"type": "status", "job_id": "1"},
    {"type": "release", "job_id": True},
    {"type": "policy-set", "policy": []},
    {"type": "policy-set", "policy": {}, "decision": 3},
    {"type": "render", "text": 5},
    {"type": "render", "text": "t", "pane": 3},
    {"type": "hook-confirm", "code": 5},
    {"type": "hook-confirm", "code": "c", "session": 3},
]


@pytest.mark.parametrize("bad", MALFORMED, ids=lambda b: f"{b['type']}-{sorted(b)}")
def test_r010_malformed_request_is_rejected_alone_and_service_continues(
    tmp_path: Path, bad: dict[str, Any]
) -> None:
    w = make_world(tmp_path)
    bad_id = client.put(w.queue, bad, _type_check=False)
    good = w.request({"type": "status"})
    assert good["ok"]
    reason = (w.queue / "rejected" / f"{bad_id}.reason").read_text(encoding="utf-8")
    assert reason.startswith("malformed request:")
    assert not (w.queue / "outbox" / f"{bad_id}.res").exists() and not w.host.spawned


def test_r010_control_without_shape_checks_wedges_the_broker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = make_world(tmp_path)
    client.put(w.queue, {"type": "cancel", "job_id": []}, _type_check=False)
    monkeypatch.setattr(broker_mod, "malformed", lambda request: None)
    with pytest.raises(TypeError):
        w.broker.step()  # the hazard: the request stays in the inbox and raises on every pass


def test_r010_unknown_type_is_an_ordinary_refusal() -> None:
    assert requests.malformed({"type": "nonsense"}) is None


# == real substitutions for C-1, C-2, C-9 ==================================================================


def test_c1_control_without_single_instance_runs_two_brokers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = FakeHost()
    Broker(tmp_path / "q1", host, FakeGit()).start()
    with pytest.raises(BrokerRefused):
        Broker(tmp_path / "q2", host, FakeGit()).start()
    from minion_process.hostqueue.hostos import MutexResult

    monkeypatch.setattr(FakeHost, "acquire_broker_mutex", lambda self: MutexResult(True, False))
    Broker(tmp_path / "q2", host, FakeGit()).start()  # the hazard: a second writer


def test_c2_control_runner_alive_check_only_releases_live_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = make_world(tmp_path)
    job_id = w.submit()["job_id"]
    runner = w.host.spawned[-1]["runner"]
    w.host.processes[(runner.pid, runner.start)] = False  # the runner died; its group still has work
    monkeypatch.setattr(Broker, "_workload", lambda self, spec, runner=None: False)
    w.broker.step()
    assert w.job(job_id).status == "ended"  # the hazard W-8 prevents


def test_c9_control_running_only_count_admits_beside_launching(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = make_world(tmp_path)
    w.host.memory = 0
    first = w.submit()["job_id"]
    w.broker._record("launching", job_id=first)
    ev = w.submit("evidence", "gate2", sha=SHA)["job_id"]
    w.host.memory = 64 * 1024**3
    monkeypatch.setattr(state_mod, "ACTIVE", ("running",))
    monkeypatch.setattr(broker_mod.Broker, "_check_active", lambda self: None)
    w.broker.step()
    assert w.job(ev).status != "submitted"  # the hazard: evidence admitted beside a launching job


assert decode_single
assert jobspec
