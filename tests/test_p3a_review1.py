"""Witnesses for Codex review 1 of kit 0.3.0 that remain in force after the convergence episode
`CE-PROC-P3A-01` superseded the R001/R003 accounting rules (those live in `test_p3a_convergence.py`):
`PROC-KIT-P3-R002`, the composite hand-off refuses a closed issue or a non-hand-off status before any
write."""

from __future__ import annotations

import pytest

from minion_process.composite import handoff
from minion_process.github import GitHub
from minion_process.model import render_body
from minion_process.ops import CheckFailed

from .test_minion_process import CODE, FakeGitHub, workflow


def test_handoff_on_a_closed_issue_is_refused_before_any_write(fake: FakeGitHub) -> None:
    fake.issues[(CODE, 10)]["state"] = "CLOSED"
    gh = GitHub(fake.run)
    with pytest.raises(CheckFailed, match=r"pre-write.*not OPEN"):
        handoff(gh, CODE, 10, "Claude", "review next")
    with pytest.raises(CheckFailed, match=r"pre-write.*not OPEN"):
        handoff(gh, CODE, 10, "Claude", "review next", dry_run=True)
    assert fake.edits == 0
    fake.issues[(CODE, 10)]["state"] = "OPEN"  # positive control
    changed, report = handoff(gh, CODE, 10, "Claude", "review next")
    assert fake.edits == 1 and not report.failed and "next_owner" in changed


def test_handoff_into_a_non_handoff_status_is_refused_before_any_write(fake: FakeGitHub) -> None:
    gh = GitHub(fake.run)
    with pytest.raises(CheckFailed, match=r"pre-write.*does not permit a hand-off"):
        handoff(gh, CODE, 10, "Owner", "decide", "BLOCKED_FOR_OWNER")
    assert fake.edits == 0
    blocked = workflow(status="BLOCKED_FOR_OWNER", next_owner="Owner")
    fake.issues[(CODE, 10)]["body"] = render_body({"workflow": blocked}, "p\n")
    with pytest.raises(CheckFailed, match=r"pre-write.*does not permit a hand-off"):
        handoff(gh, CODE, 10, "Codex", "review")  # status unchanged and non-handoff
    assert fake.edits == 0
