"""Client, confirm hook, runner, `build`/`session`/`faults`/`dispatch` verbs and the no-keystroke and
no-kill guarantees (B-3, K-1 to K-3, K-21, Parts B, E, F; witnesses W-26, W-38, W-39, W-40, W-42 to W-44;
control C-7)."""

from __future__ import annotations

import argparse
import ast
import io
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from minion_process import faults
from minion_process.cli import main
from minion_process.hostqueue import client, commands, confirm, runner
from minion_process.hostqueue.framing import decode_single, encode

from .hostqueue_fake import FakeGit, FakeHost, pane_info
from .hostqueue_world import make_world

PACKAGE = Path(__file__).resolve().parent.parent / "minion_process"

# -- W-40 / C-7: no kit code path sends keys or signals a process ----------------------------------------

FORBIDDEN_CALLS = {
    "kill",
    "killpg",
    "terminate",
    "send_signal",
    "TerminateProcess",
    "TerminateJobObject",
    "GenerateConsoleCtrlEvent",
}


def offences(source: str) -> list[str]:
    """Calls that signal or kill a process, and any argument list that drives herdr's `prompt` or
    `send-keys` (the only ways the kit could put keystrokes into a pane)."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            func = node.func
            name = (
                func.attr
                if isinstance(func, ast.Attribute)
                else func.id
                if isinstance(func, ast.Name)
                else ""
            )
            if name in FORBIDDEN_CALLS:
                found.append(name)
        if isinstance(node, (ast.List, ast.Tuple)):
            words = {e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)}
            if "send-keys" in words or ({"prompt"} <= words and {"agent", "herdr"} & words):
                found.append("pane keystrokes")
        if isinstance(node, ast.Constant) and node.value == "send-keys":
            found.append("send-keys")
    return found


def test_w40_no_keystrokes_and_no_kill_anywhere_in_the_package() -> None:
    hits = {path.name: offences(path.read_text(encoding="utf-8")) for path in PACKAGE.rglob("*.py")}
    assert {name: found for name, found in hits.items() if found} == {}


def test_c7_an_injected_prompt_call_is_caught() -> None:
    injected = 'import subprocess\nsubprocess.run(["herdr", "agent", "prompt", "w1:p2", "x"])\nproc.kill()\n'
    assert set(offences(injected)) == {"kill", "pane keystrokes"}
    assert offences('event.get("prompt", "")') == []  # reading a hook event's prompt is not sending one


# -- client ----------------------------------------------------------------------------------------------


def test_client_put_get_and_timeouts(tmp_path: Path) -> None:
    queue = tmp_path / "q"
    for folder in ("inbox", "outbox"):
        (queue / folder).mkdir(parents=True)
    request_id = client.put(queue, {"type": "status"})
    assert decode_single((queue / "inbox" / f"{request_id}.req").read_bytes())["type"] == "status"
    with pytest.raises(ValueError):
        client.put(queue, {"type": "hook-confirm"})
    clock = iter([0.0, 0.1, 10.0])
    with pytest.raises(client.Unavailable, match="no response"):
        client.get(queue, "missing", 1.0, sleep=lambda s: None, clock=lambda: next(clock))
    (queue / "outbox" / "bad.res").write_bytes(b"junk")
    with pytest.raises(client.Unavailable, match="unreadable"):
        client.get(queue, "bad", 1.0, sleep=lambda s: None)
    (queue / "outbox" / "ok.res").write_bytes(encode({"request_id": "ok", "ok": True}))
    assert client.get(queue, "ok", 1.0)["ok"]


@pytest.mark.parametrize(
    ("job", "code"),
    [
        ({"status": "ended", "outcome": "passed"}, 0),
        ({"status": "ended", "outcome": "failed"}, 1),
        ({"status": "refused"}, 2),
        ({"status": "cancelled"}, 2),
        ({"status": "uncertain"}, 3),
    ],
)
def test_w39_wait_outcomes(job: dict[str, Any], code: int) -> None:
    assert client.wait_job(Path("."), 1, 5.0, poll=lambda: {"jobs": [job]})[0] == code


def test_w39_wait_timeout() -> None:
    clock = iter([0.0, 1.0, 9.0])
    code, job = client.wait_job(
        Path("."),
        1,
        5.0,
        poll=lambda: {"jobs": [{"status": "running"}]},
        sleep=lambda s: None,
        clock=lambda: next(clock),
    )
    assert code == 4 and job["status"] == "running"
    clock = iter([0.0, 9.0])
    assert (
        client.wait_job(
            Path("."), 1, 5.0, poll=lambda: {"jobs": []}, sleep=lambda s: None, clock=lambda: next(clock)
        )[0]
        == 4
    )


# -- confirm hook ----------------------------------------------------------------------------------------


def test_confirm_grammar() -> None:
    assert confirm.parse("  CONFIRM QUEUE 0123abcd \n") == "0123abcd"
    for bad in (
        "CONFIRM QUEUE 0123ABCD",
        "confirm queue 0123abcd",
        "CONFIRM QUEUE 0123abc",
        "x CONFIRM QUEUE 0123abcd",
    ):
        assert confirm.parse(bad) is None


def test_confirm_main(tmp_path: Path) -> None:
    queue = tmp_path / "q"
    (queue / "inbox").mkdir(parents=True)
    assert confirm.main(["--queue"]) == 64
    assert confirm.main(["--queue", str(queue)], io.StringIO("not json")) == 0
    assert confirm.main(["--queue", str(queue)], io.StringIO("[1]")) == 0
    event = {"hook_event_name": "UserPromptSubmit", "prompt": "CONFIRM QUEUE 0123abcd", "session_id": "o"}
    assert confirm.main(["--queue", str(queue)], io.StringIO(json.dumps(event))) == 0
    written = [p for p in (queue / "inbox").iterdir() if p.suffix == ".req"]
    assert len(written) == 1 and decode_single(written[0].read_bytes())["origin"] == "user-prompt-hook"


# -- runner ----------------------------------------------------------------------------------------------


def _runner_job(tmp_path: Path, argv: list[str]) -> Path:
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    (job_dir / "input").write_bytes(
        encode(
            {
                "argv": argv,
                "cwd": str(tmp_path),
                "log": str(tmp_path / "logs" / "j.log"),
                "roots": [str(tmp_path)],
            }
        )
    )
    return job_dir


def test_runner_records_exit_and_gate_end(tmp_path: Path) -> None:
    job_dir = _runner_job(tmp_path, [sys.executable, "-c", "print('hello'); raise SystemExit(3)"])
    assert runner.run(job_dir) == 3
    result = decode_single((job_dir / "result").read_bytes())
    assert result == {"exit": 3, "gate_end": 3, "drained": False}
    log = (tmp_path / "logs" / "j.log").read_text()
    assert "hello" in log and log.rstrip().endswith("GATE-END 3")


def test_runner_setup_failure_is_never_a_pass(tmp_path: Path) -> None:
    job_dir = _runner_job(tmp_path, [str(tmp_path / "no-such-launcher.exe")])
    assert runner.run(job_dir) == 127
    result = decode_single((job_dir / "result").read_bytes())
    assert result["exit"] == 127 and result["drained"] is False  # outside a job object: no drain claimed


def test_runner_gate_end_parsing(tmp_path: Path) -> None:
    log = tmp_path / "l.log"
    log.write_text("x\nGATE-END\n")
    assert runner._gate_end(log) is None
    log.write_text("x\nnothing\n")
    assert runner._gate_end(log) is None
    assert runner._gate_end(tmp_path / "missing.log") is None
    assert runner.main([]) == 64


@pytest.mark.skipif(sys.platform != "win32", reason="job objects are Windows only")
def test_runner_drain_without_a_group_or_job(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MINION_JOB_GROUP", raising=False)
    runner._hold_and_drain()
    monkeypatch.setenv("MINION_JOB_GROUP", "minion-test-no-such-group")
    runner._hold_and_drain()


# -- faults (Part F, W-38) -------------------------------------------------------------------------------


def cell(value: str, **over: Any) -> dict[str, Any]:
    return {"fault": "f", "platform": "windows", "binding": "rust", "value": value, **over}


def test_w38_fault_accounting() -> None:
    good = {
        "rows": [
            {
                "id": "r1",
                "credited": True,
                "cells": [cell("fired"), cell("not-applicable", reason="authority never calls it")],
            }
        ]
    }
    assert faults.check(good) == []
    unfired = {"rows": [{"id": "r", "credited": True, "cells": [cell("unfired")]}]}
    assert "credited, but" in faults.check(unfired)[0].message
    mixed = {"rows": [{"id": "r", "credited": True, "cells": [cell("fired"), cell("setup-failure")]}]}
    assert faults.check(mixed)
    forged = {"rows": [{"id": "r", "credited": True, "cells": [cell("not-applicable")]}]}
    assert any("declared reason" in p.message for p in faults.check(forged))
    honest = {"rows": [{"id": "r", "credited": False, "cells": [cell("unfired")]}]}
    assert faults.check(honest) == []


@pytest.mark.parametrize(
    "bad",
    [
        None,
        {"rows": []},
        {"rows": [1]},
        {"rows": [{"id": "r", "credited": "yes", "cells": [cell("fired")]}]},
        {"rows": [{"id": "r", "credited": True, "cells": []}]},
        {"rows": [{"id": "r", "credited": True, "cells": [1]}]},
        {"rows": [{"id": "r", "credited": True, "cells": [{"value": "fired"}]}]},
        {"rows": [{"id": "r", "credited": True, "cells": [cell("maybe")]}]},
    ],
)
def test_fault_matrix_shape(bad: Any) -> None:
    assert faults.check(bad)


def test_faults_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "m.yaml"
    path.write_text(yaml.safe_dump({"rows": [{"id": "r", "credited": True, "cells": [cell("fired")]}]}))
    assert main(["faults", "check", str(path)]) == 0
    path.write_text(yaml.safe_dump({"rows": [{"id": "r", "credited": True, "cells": [cell("unfired")]}]}))
    assert main(["faults", "check", str(path)]) == 1
    assert main(["faults", "check", str(tmp_path / "missing.yaml")]) == 1
    assert "INVALID" in capsys.readouterr().out


# -- build verbs through the CLI -------------------------------------------------------------------------


def test_build_broker_verb(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    host = FakeHost()
    args = argparse.Namespace(verb="broker", queue=str(tmp_path / "q"), repair=False, serve=False)
    assert commands.run_build(args, host_factory=lambda: host, git_factory=FakeGit) == 0
    assert '"mode": "normal"' in capsys.readouterr().out
    host.mutex_held_by_other = True
    assert commands.run_build(args, host_factory=lambda: host, git_factory=FakeGit) == 1


def test_build_client_verbs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    w = make_world(tmp_path)
    w.host.memory = 0
    sent: list[dict[str, Any]] = []

    def fake_call(queue: Path, request: dict[str, Any], timeout: float = 30.0, **kw: Any) -> dict[str, Any]:
        sent.append(request)
        request_id = client.put(queue, request)
        w.broker.step()
        return decode_single((queue / "outbox" / f"{request_id}.res").read_bytes())

    monkeypatch.setattr(client, "call", fake_call)
    base = ["build"]
    assert (
        main(
            [
                *base,
                "submit",
                "--profile",
                str(w.profile),
                "--class",
                "build",
                "--launcher",
                "rust",
                "--target",
                "gate",
                "--checkout",
                str(w.root / "repo"),
                "--pane",
                "w1:p1",
                "--session",
                "s1",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                *base,
                "submit",
                "--profile",
                str(w.profile),
                "--class",
                "evidence",
                "--launcher",
                "rust",
                "--target",
                "gate",
                "--checkout",
                str(w.root / "repo"),
                "--pane",
                "w1:p1",
                "--session",
                "s1",
                "--sha",
                "a" * 40,
            ]
        )
        == 0
    )
    assert main([*base, "status", "--queue", str(w.queue)]) == 0
    assert main([*base, "status", "--queue", str(w.queue), "--job", "1"]) == 0
    assert (
        main([*base, "cancel", "--queue", str(w.queue), "--job", "1", "--pane", "w1:p1", "--session", "s1"])
        == 0
    )
    assert (
        main([*base, "unretain", "--queue", str(w.queue), "--job", "1", "--pane", "w1:p1", "--session", "s1"])
        == 1
    )
    assert main([*base, "release", "--queue", str(w.queue), "--job", "2"]) == 1
    policy = tmp_path / "policy.yaml"
    policy.write_text(
        yaml.safe_dump(
            {
                "policy_id": "host-test",
                "version": 2,
                "limit": 1,
                "floor_bytes": 1,
                "reservation_seconds": 1,
                "bypass_limit": 1,
                "projects": {"proj": [str(w.root)]},
            }
        )
    )
    assert main([*base, "policy", "--queue", str(w.queue), "--file", str(policy), "--decision", "link"]) == 0
    assert main([*base, "repair", "--queue", str(w.queue), "inspect"]) == 0
    assert (
        main(
            [
                *base,
                "cleanup",
                "--profile",
                str(w.profile),
                "--copies",
                "x",
                "--pane",
                "w1:p1",
                "--session",
                "s1",
                "--apply",
            ]
        )
        == 1
    )
    monkeypatch.setattr(client, "wait_job", lambda queue, job, timeout: (3, {"status": "uncertain"}))
    assert main([*base, "wait", "--queue", str(w.queue), "--job", "1"]) == 3
    assert [r["type"] for r in sent][:3] == ["submit", "submit", "status"]
    assert next(r for r in sent if r.get("class") == "cleanup")["apply"] is True

    def unavailable(*a: Any, **k: Any) -> dict[str, Any]:
        raise client.Unavailable("down")

    monkeypatch.setattr(client, "call", unavailable)
    assert main([*base, "status", "--queue", str(w.queue)]) == 3
    assert "UNAVAILABLE" in capsys.readouterr().out


# -- session start (Part B, W-26) ------------------------------------------------------------------------


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_w26_session_start_reports_and_writes_only_its_report(tmp_path: Path) -> None:
    origin = tmp_path / "origin.git"
    _git(["init", "--bare", "-b", "main", str(origin)], tmp_path)
    repo = tmp_path / "repo"
    _git(["clone", str(origin), str(repo)], tmp_path)
    _git(["-c", "user.email=t@t", "-c", "user.name=t", "commit", "--allow-empty", "-m", "c"], repo)
    _git(["push", "origin", "HEAD:main"], repo)
    (repo / "dirty.txt").write_text("x")
    other = tmp_path / "plain"
    other.mkdir()
    w = make_world(tmp_path / "w")
    profile = repo / "profile.yaml"
    profile.write_text(
        yaml.safe_dump(
            {
                "repos": {
                    "code": {"path": ".", "default_branch": "main"},
                    "broken": {"path": "../plain", "default_branch": "main"},
                },
                "environment": "env.ps1",
                "build_queue": {"state": str(w.queue)},
            }
        )
    )
    before = sorted(p.name for p in repo.iterdir())
    report = commands.session_start(
        profile, "claude", lambda: [{"next_owner": "claude", "issue": 1}, {"next_owner": "codex", "issue": 2}]
    )
    assert sorted(p.name for p in repo.iterdir()) == before  # no working file touched
    assert report["repos"]["code"]["dirty"] is True and report["repos"]["code"]["behind"] == 0
    assert report["partial"] and any("broken" in f for f in report["failed"])  # partial is never green
    assert any("environment file missing" in f for f in report["failed"])
    assert report["work_packages"] == [{"next_owner": "claude", "issue": 1}]
    assert report["queue"] == {"running": [], "waiting": [], "uncertain": []}

    def broken() -> list[dict[str, Any]]:
        raise RuntimeError("gh down")

    assert any(
        "work packages unknown" in f for f in commands.session_start(profile, "claude", broken)["failed"]
    )


def test_session_queue_summary_and_candidates(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    evidence = w.submit("evidence", sha="a" * 40)["job_id"]
    (w.queue / "jobs" / str(evidence) / "result").write_bytes(encode({"exit": 1, "gate_end": 1}))
    w.host.finish(w.job(evidence).spec["group"])
    w.broker.step()
    w.host.memory = 0
    w.submit()
    summary, candidates = commands._queue_summary(w.queue)
    assert summary["waiting"] and candidates == [str(w.job(evidence).spec["job_label"])]
    assert commands._queue_summary(tmp_path / "empty") == (
        {"running": [], "waiting": [], "uncertain": []},
        [],
    )
    path = w.queue / "journal" / f"gen-{w.broker.generation}.log"
    path.write_bytes(path.read_bytes()[:-3])
    with pytest.raises(ValueError, match="anomaly"):
        commands._queue_summary(w.queue)


def test_session_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    profile = tmp_path / "p.yaml"
    profile.write_text(yaml.safe_dump({"repos": {}}))
    out = tmp_path / "report.yaml"
    args = argparse.Namespace(profile=str(profile), agent="claude", out=str(out))
    assert commands.run_session(args) == 0 and "COMPLETE" in capsys.readouterr().out and out.exists()
    profile.write_text(yaml.safe_dump({"repos": {}, "build_queue": {"state": str(tmp_path / "q")}}))
    (tmp_path / "q" / "effects" / "generation").mkdir(parents=True)
    (tmp_path / "q" / "effects" / "generation" / "1").write_text("x")
    assert commands.run_session(args) == 1


# -- dispatch --print (Part D) ---------------------------------------------------------------------------


def test_render_and_dispatch_helpers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    text = commands.render_handoff(
        {
            "work_package": "WP",
            "title": "T",
            "status": "CONTRACT_REVIEW",
            "current_candidate": {"docs": {"pr": 5, "sha": "s"}},
            "next_owner": "Codex",
            "next_action": "review",
        },
        "w1:p8",
    )
    assert "docs PR #5 at s" in text and "w1:p8" in text
    assert "candidate: none" in commands.render_handoff({"work_package": "WP", "status": "S"}, "p")
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        client, "call", lambda queue, request, timeout=30.0: calls.append(request) or {"ok": True}
    )
    commands.dispatch_print(tmp_path, "t", "p", "s")
    commands.mark_undelivered(tmp_path, "h", 1, "s")
    assert [c["type"] for c in calls] == ["render", "undelivered"]


def test_dispatch_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from minion_process import cli as cli_mod
    from minion_process.ops import Report

    body = (
        "```yaml\nworkflow:\n  work_package: WP\n  status: CONTRACT_REVIEW\n"
        "  next_owner: Codex\n  next_action: review\n```\n"
    )

    class GH:
        def issue(self, repo: str, number: int) -> dict[str, Any]:
            return {"body": body, "state": "OPEN"}

        def open_issues(self, repo: str) -> list[dict[str, Any]]:
            return [{"number": 1, "body": body}, {"number": 2, "body": "no state"}]

    ok = Report()
    monkeypatch.setattr(cli_mod, "handoff_report", lambda gh, repo, number: ok)
    monkeypatch.setattr(
        client,
        "call",
        lambda queue, request, timeout=30.0: {"ok": True, "text": request["text"], "hash": "h", "attempt": 1},
    )
    argv = ["dispatch", "1", "--queue", str(tmp_path), "--pane", "w1:p2", "--session", "s"]
    assert main(argv, gh=GH()) == 0  # type: ignore[arg-type]
    assert "may-have-printed" in capsys.readouterr().out
    monkeypatch.setattr(client, "call", lambda queue, request, timeout=30.0: {"ok": True})
    assert main([*argv, "--mark-undelivered", "h:1"], gh=GH()) == 0  # type: ignore[arg-type]
    monkeypatch.setattr(client, "call", lambda queue, request, timeout=30.0: {"ok": False, "error": "x"})
    assert main(argv, gh=GH()) == 1  # type: ignore[arg-type]

    def down(*a: Any, **k: Any) -> dict[str, Any]:
        raise client.Unavailable("down")

    monkeypatch.setattr(client, "call", down)
    assert main(argv, gh=GH()) == 3  # type: ignore[arg-type]
    blocked = Report()
    blocked.check(False, "status permits a handoff")
    monkeypatch.setattr(cli_mod, "handoff_report", lambda gh, repo, number: blocked)
    assert main(argv, gh=GH()) == 1  # type: ignore[arg-type]
    assert "HANDOFF_BLOCKED" in capsys.readouterr().out
    profile = tmp_path / "p.yaml"
    profile.write_text(yaml.safe_dump({"repos": {}}))
    assert main(["session", "start", "--profile", str(profile), "--agent", "Codex"], gh=GH()) == 0  # type: ignore[arg-type]
    assert "WP" in capsys.readouterr().out


assert pane_info("s")
