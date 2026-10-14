"""Edge paths of the host queue: each test names the rule whose refusal or fallback it pins."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from minion_process.github import GitHub
from minion_process.hostqueue import broker as broker_mod
from minion_process.hostqueue import client, commands, contain, runner
from minion_process.hostqueue.broker import BrokerRefused
from minion_process.hostqueue.framing import decode_single, encode
from minion_process.hostqueue.gitops import RealGit

from .hostqueue_world import SHA, make_world


def test_record_without_a_journal_refuses(tmp_path: Path) -> None:
    w = make_world(tmp_path, with_policy=False)
    w.broker.journal = None
    with pytest.raises(BrokerRefused, match="no writable journal"):
        w.broker._record("mode", mode="normal")


def test_unreadable_policy_marker_at_start_means_repair(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    marker = w.queue / "effects" / "policy" / "1"
    marker.write_bytes(marker.read_bytes()[:-3])
    report = w.restart()
    assert report.mode == "repair" and w.broker.policy is None


def test_removed_copies_are_skipped_in_recovery(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    job_id = int(w.submit("evidence", sha=SHA)["job_id"])
    (w.queue / "jobs" / str(job_id) / "result").write_bytes(encode({"exit": 1, "gate_end": 1}))
    w.host.finish(w.job(job_id).spec["group"])
    w.broker.step()
    copy_id = str(w.job(job_id).spec["job_label"])
    w.request(
        {
            "type": "submit",
            "class": "cleanup",
            "apply": True,
            "profile": str(w.profile),
            "copies": [copy_id],
            "submitter": {"pane": "w1:p1", "session": "s1"},
        }
    )
    w.broker.step()
    assert w.broker.state.copies[copy_id]["state"] == "removed"
    assert w.restart().mode == "normal"


def test_spawn_failure_before_any_group_is_refused(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    w.host.spawn_creates_group = False
    w.host.spawn_error = OSError("CreateJobObjectW failed")
    job_id = w.submit()["job_id"]
    assert w.job(job_id).status == "refused" and "before any workload" in str(w.job(job_id).reason)


def test_git_metadata_is_never_touched_by_the_freshness_step(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    git_dir = w.root / "repo" / ".git"
    git_dir.mkdir()
    (git_dir / "x.rs").write_text("not a source")
    import os

    os.utime(git_dir / "x.rs", (1_000_000, 1_000_000))
    w.submit()
    assert (git_dir / "x.rs").stat().st_mtime == 1_000_000


def test_retain_rechecked_at_the_cleanup_boundary(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    job_id = int(w.submit("evidence", sha=SHA)["job_id"])
    (w.queue / "jobs" / str(job_id) / "result").write_bytes(encode({"exit": 1, "gate_end": 1}))
    w.host.finish(w.job(job_id).spec["group"])
    w.broker.step()
    copy_id = str(w.job(job_id).spec["job_label"])
    w.host.memory = 0
    cleanup = w.request(
        {
            "type": "submit",
            "class": "cleanup",
            "apply": True,
            "profile": str(w.profile),
            "copies": [copy_id],
            "submitter": {"pane": "w1:p1", "session": "s1"},
        }
    )
    w.job(job_id).retain = True  # a retained state appearing between submit and the boundary
    w.host.memory = 64 * 1024**3
    w.broker.step()
    w.broker.step()
    assert "retained" in str(w.job(cleanup["job_id"]).reason)


def test_uncertain_record_can_name_the_group(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    job_id = w.submit()["job_id"]
    w.broker._record("uncertain", job_id=job_id, reason="test", extent_known=True, group="named-group")
    assert w.job(job_id).group == "named-group"


def test_client_call_round_trip(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    response = client.call(w.queue, {"type": "status"}, 5.0, sleep=lambda s: w.broker.step())
    assert response["ok"] and response["mode"] == "normal"


def test_session_failure_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    profile = tmp_path / "p.yaml"
    profile.write_text("repos:\n  code: {path: ., default_branch: main}\n", encoding="utf-8")

    def broken_run(*a: Any, **k: Any) -> Any:
        raise OSError("no git")

    monkeypatch.setattr(commands.subprocess, "run", broken_run)

    def no_disk(path: Any) -> Any:
        raise OSError("no disk")

    monkeypatch.setattr(commands.shutil, "disk_usage", no_disk)
    report = commands.session_start(profile, "claude")
    assert any("free space unknown" in f for f in report["failed"]) and any(
        "fetch failed" in f for f in report["failed"]
    )


def test_queue_summary_unknowns(tmp_path: Path) -> None:
    queue = tmp_path / "q"
    (queue / "effects" / "generation").mkdir(parents=True)
    (queue / "effects" / "generation" / "odd").write_text("x")
    with pytest.raises(ValueError, match="unexpected"):
        commands._queue_summary(queue)
    (queue / "effects" / "generation" / "odd").unlink()
    w = make_world(tmp_path / "w")
    (w.queue / "journal" / f"gen-{w.broker.generation}.log").unlink()
    with pytest.raises(ValueError, match="missing"):
        commands._queue_summary(w.queue)


def test_containment_empty_form() -> None:
    assert contain._form_ok("") == "empty path"


def test_runner_main_and_bad_gate_end(tmp_path: Path) -> None:
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    (job_dir / "input").write_bytes(
        encode(
            {
                "argv": [sys.executable, "-c", "print('GATE-END x')"],
                "cwd": str(tmp_path),
                "log": str(tmp_path / "logs" / "l.log"),
                "roots": [str(tmp_path)],
            }
        )
    )
    assert runner.main([str(job_dir)]) == 0
    log = tmp_path / "bad.log"
    log.write_text("GATE-END x\n")
    assert runner._gate_end(log) is None
    assert decode_single((job_dir / "result").read_bytes())["gate_end"] == 0


def test_real_git_operations(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "f.txt").write_text("x")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "c"],
        check=True,
    )
    sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    git = RealGit()
    copy = tmp_path / "copy"
    git.add_worktree(repo, copy, sha)
    assert git.head(copy) == sha and git.clean(copy) is True
    assert git.unpushed(copy) == [sha]  # no remote at all: the commit is reachable from no remote ref
    (copy / "new.txt").write_text("y")
    assert git.clean(copy) is False
    with pytest.raises(OSError, match="worktree add failed"):
        git.add_worktree(repo, tmp_path / "copy2", "0" * 40)
    missing = tmp_path / "not-a-repo"
    missing.mkdir()
    assert git.head(missing) is None and git.clean(missing) is None and git.unpushed(missing) is None
    git.prune(repo)


def test_github_open_issues() -> None:
    seen: list[list[str]] = []

    def run(args: list[str], stdin: str | None) -> str:
        seen.append(args)
        return json.dumps([{"number": 1, "title": "t", "body": "b"}])

    assert GitHub(run).open_issues("o/r") == [{"number": 1, "title": "t", "body": "b"}]
    assert "--state" in seen[0] and "open" in seen[0]


assert broker_mod.CLEANUP_BATCH
