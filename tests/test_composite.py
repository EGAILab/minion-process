"""Composite verbs `handoff` and `close`, and the remote-reading verbs `convergence counters` and
`metrics` (kit 0.3.0), through the real `commit_state` and the fake remote."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from minion_process.cli import main
from minion_process.composite import close, handoff
from minion_process.github import GitHub
from minion_process.model import render_body, split_body
from minion_process.ops import CheckFailed

from .test_minion_process import CODE, DOCS, SHA_A, SHA_B, FakeGitHub, workflow


def run(fake: FakeGitHub, *argv: str) -> int:
    return main(list(argv), gh=GitHub(fake.run))


def state(fake: FakeGitHub) -> dict[str, Any]:
    return split_body(fake.issues[(CODE, 10)]["body"]).workflow


def v2_workflow(**overrides: Any) -> dict[str, Any]:
    """A schema-v2 state: the v1 `code`/`docs` keys are absent, not null."""
    w = workflow(schema_version=2, **overrides)
    for side in ("code", "docs"):
        if side not in overrides:
            del w[side]
    return w


# --- handoff ---------------------------------------------------------------------------------------


def test_handoff_records_owner_action_and_heads_in_one_checked_commit(fake: FakeGitHub) -> None:
    gh = GitHub(fake.run)
    new_sha = "c" * 40
    fake.prs[(CODE, 1)]["headRefOid"] = new_sha
    fake.commits.add(new_sha)
    changed, report = handoff(gh, CODE, 10, "Claude", "remediate R001", "REMEDIATION", {"code": new_sha})
    assert changed == ["code", "next_action", "next_owner", "status", "updated_reason"]
    assert not report.failed and fake.edits == 1
    w = state(fake)
    assert w["status"] == "REMEDIATION" and w["next_owner"] == "Claude" and w["code"]["sha"] == new_sha


def test_handoff_refuses_with_zero_writes_when_the_candidate_would_block(fake: FakeGitHub) -> None:
    gh = GitHub(fake.run)
    with pytest.raises(CheckFailed, match="HANDOFF_BLOCKED \\(intended candidate\\)"):
        handoff(gh, CODE, 10, "Codex", "review", None, {"code": "d" * 40})  # not the PR head, not reachable
    assert fake.edits == 0
    with pytest.raises(CheckFailed, match="unknown candidate side"):
        handoff(gh, CODE, 10, "Codex", "review", None, {"kit": SHA_A})
    with pytest.raises(CheckFailed, match="40-hex"):
        handoff(gh, CODE, 10, "Codex", "review", None, {"code": "abc"})
    with pytest.raises(CheckFailed, match="non-empty next_action"):
        handoff(gh, CODE, 10, "Codex", "  ")
    with pytest.raises(CheckFailed, match="illegal transition"):
        handoff(gh, CODE, 10, "Codex", "review", "PYTHON_IMPLEMENTATION")  # table-illegal from review
    assert fake.edits == 0


def test_handoff_dry_run_and_v2_candidate_and_post_commit_block(fake: FakeGitHub) -> None:
    gh = GitHub(fake.run)
    changed, report = handoff(gh, CODE, 10, "Codex", "re-review", dry_run=True)
    assert changed == ["next_action", "updated_reason"] and report.ok == [] and fake.edits == 0
    # a null side means "no candidate yet": the hand-off creates the mapping
    fake.issues[(CODE, 10)]["body"] = render_body({"workflow": workflow(docs=None)}, "p\n")
    changed, _ = handoff(gh, CODE, 10, "Codex", "review", None, {"docs": SHA_B})
    assert "docs" in changed and state(fake)["docs"] == {"sha": SHA_B}
    v2 = v2_workflow(current_candidate={"code": {"pr": 1, "sha": SHA_A, "base": "main"}})
    fake.issues[(CODE, 10)]["body"] = render_body({"workflow": v2}, "p\n")
    changed, _ = handoff(gh, CODE, 10, "Codex", "review", None, {"docs": SHA_B})
    assert "current_candidate" in changed and state(fake)["current_candidate"]["docs"]["sha"] == SHA_B
    broken = v2_workflow(current_candidate={"code": "nope"})
    fake.issues[(CODE, 10)]["body"] = render_body({"workflow": broken}, "p\n")
    with pytest.raises(CheckFailed):  # the current state is invalid; refused before any write
        handoff(gh, CODE, 10, "Codex", "review", None, {"code": SHA_A})
    # the issue closes between the pre-check and the post-commit check: reported, not hidden
    fake.issues[(CODE, 10)]["body"] = render_body({"workflow": workflow()}, "p\n")
    original = fake.run

    def closing_run(args: list[str], stdin: str | None) -> str:
        out = original(args, stdin)
        if args[0] == "issue" and args[1] == "edit":
            fake.issues[(CODE, 10)]["state"] = "CLOSED"
        return out

    with pytest.raises(CheckFailed, match="after commit"):
        handoff(GitHub(closing_run), CODE, 10, "Codex", "review")


def test_handoff_cli(fake: FakeGitHub, capsys: pytest.CaptureFixture[str]) -> None:
    assert (
        run(
            fake,
            "handoff",
            "10",
            "--to",
            "Claude",
            "--action",
            "fix",
            "--status",
            "REMEDIATION",
            "--sha",
            f"code={SHA_A}",
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "HANDED OFF #10 -> Claude" in out and "ok" in out
    assert run(fake, "handoff", "10", "--to", "Codex", "--action", "x", "--status", "CLOSED") == 1
    assert "illegal transition" in capsys.readouterr().err


# --- close -------------------------------------------------------------------------------------------


def merged_fixture(fake: FakeGitHub) -> None:
    for (repo, number), sha in (((CODE, 1), SHA_A), ((DOCS, 2), SHA_B)):
        merge = f"{'e' if repo == CODE else 'f'}" * 40
        fake.prs[(repo, number)].update(state="MERGED", headRefOid=sha, mergeCommit={"oid": merge})
        fake.on_default.add(merge)


def test_close_verifies_every_merge_records_it_and_closes_the_issue(fake: FakeGitHub) -> None:
    gh = GitHub(fake.run)
    fake.issues[(CODE, 10)]["body"] = render_body(
        {"workflow": workflow(status="CLOSURE_REVIEW", next_owner="Claude", requirements=["TOOL-1"])}, "p\n"
    )
    merged_fixture(fake)
    changed, merged = close(gh, CODE, 10, "closed per section 4.3")
    assert merged == {"code": "e" * 40, "docs": "f" * 40}
    assert changed == ["code", "docs", "next_action", "next_owner", "status", "updated_reason"]
    w = state(fake)
    assert w["status"] == "CLOSED" and w["code"]["merged_sha"] == "e" * 40 and w["next_owner"] is None
    assert (
        fake.closed == [(CODE, 10, "closed per section 4.3")] and fake.issues[(CODE, 10)]["state"] == "CLOSED"
    )


def test_close_refusals_leave_zero_writes(fake: FakeGitHub) -> None:
    gh = GitHub(fake.run)
    body = render_body(
        {"workflow": workflow(status="CLOSURE_REVIEW", next_owner="Claude", requirements=["TOOL-1"])}, "p\n"
    )
    fake.issues[(CODE, 10)]["body"] = body
    with pytest.raises(CheckFailed, match="not MERGED"):
        close(gh, CODE, 10, "c")
    merged_fixture(fake)
    fake.prs[(CODE, 1)]["headRefOid"] = "9" * 40
    with pytest.raises(CheckFailed, match="merged head"):
        close(gh, CODE, 10, "c")
    fake.prs[(CODE, 1)]["headRefOid"] = SHA_A
    fake.prs[(CODE, 1)]["mergeCommit"] = None
    with pytest.raises(CheckFailed, match="no merge commit"):
        close(gh, CODE, 10, "c")
    fake.prs[(CODE, 1)]["mergeCommit"] = {"oid": "e" * 40}
    fake.on_default.discard("e" * 40)
    with pytest.raises(CheckFailed, match="not on the default branch"):
        close(gh, CODE, 10, "c")
    fake.on_default.add("e" * 40)
    stale = workflow(status="CLOSURE_REVIEW", next_owner="Claude", requirements=["TOOL-1"])
    stale["code"]["merged_sha"] = "1" * 40
    fake.issues[(CODE, 10)]["body"] = render_body({"workflow": stale}, "p\n")
    with pytest.raises(CheckFailed, match="recorded merged_sha"):
        close(gh, CODE, 10, "c")
    fake.issues[(CODE, 10)]["body"] = body
    del fake.prs[(DOCS, 2)]
    with pytest.raises(CheckFailed, match="cannot be read"):
        close(gh, CODE, 10, "c")
    with pytest.raises(CheckFailed, match="non-empty closure comment"):
        close(gh, CODE, 10, "   ")
    no_candidate = workflow(
        status="CLOSURE_REVIEW", next_owner="Claude", requirements=["TOOL-1"], code=None, docs=None
    )
    fake.issues[(CODE, 10)]["body"] = render_body({"workflow": no_candidate}, "p\n")
    with pytest.raises(CheckFailed, match="at least one recorded candidate"):
        close(gh, CODE, 10, "c")
    partial = workflow(status="CLOSURE_REVIEW", next_owner="Claude", requirements=["TOOL-1"], docs=None)
    partial["code"] = {"base": "main"}
    fake.issues[(CODE, 10)]["body"] = render_body({"workflow": partial}, "p\n")
    with pytest.raises(CheckFailed, match="needs pr and sha"):
        close(gh, CODE, 10, "c")
    assert fake.edits == 0 and fake.closed == []


def test_close_runs_the_closure_guards_and_the_cli(
    fake: FakeGitHub, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    gh = GitHub(fake.run)
    merged_fixture(fake)
    # a process-only WP closing from FINAL_CONTRACT_REVIEW takes the 10.2 guard: requirements must be []
    both = {
        "code": {"pr": 1, "sha": SHA_A, "base": "main"},
        "docs": {"pr": 2, "sha": SHA_B, "base": "master"},
    }
    fake.issues[(CODE, 10)]["body"] = render_body(
        {
            "workflow": v2_workflow(
                status="FINAL_CONTRACT_REVIEW",
                next_owner="Claude",
                requirements=["TOOL-1"],
                current_candidate=both,
            )
        },
        "p\n",
    )
    with pytest.raises(CheckFailed, match="process-only"):
        close(gh, CODE, 10, "c")
    assert fake.edits == 0
    fake.issues[(CODE, 10)]["body"] = render_body(
        {
            "workflow": v2_workflow(
                status="FINAL_CONTRACT_REVIEW", next_owner="Claude", requirements=[], current_candidate=both
            )
        },
        "p\n",
    )
    changed, merged = close(gh, CODE, 10, "c", dry_run=True)
    assert "status" in changed and merged and fake.edits == 0 and fake.closed == []
    note = tmp_path / "close.md"
    note.write_text("PROC CLOSED\n", encoding="utf-8")
    assert run(fake, "close", "10", "--comment-file", str(note)) == 0
    out = capsys.readouterr().out
    assert "CLOSED #10" in out and "code merged" in out and fake.closed[0][2] == "PROC CLOSED\n"
