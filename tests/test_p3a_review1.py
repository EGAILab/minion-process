"""Witnesses for Codex review 1 of kit 0.3.0 (`PROC-KIT-P3-R001`..`R003`): transport copies of one review
event count once; a hand-off on a closed issue or into a non-handoff status is refused before any write;
every review-bearing fence is accounted for and malformed headers never raise."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from minion_process.cli import main
from minion_process.composite import handoff
from minion_process.github import GitHub
from minion_process.model import render_body
from minion_process.ops import CheckFailed
from minion_process.review import (
    counters,
    parse_review_records,
    select_reviews,
    trigger_statement,
    validate_review,
)
from minion_process.validate import errors

from .test_minion_process import CODE, DOCS, FakeGitHub, workflow
from .test_review import GOOD, good, render


def run(fake: FakeGitHub, *argv: str) -> int:
    return main(list(argv), gh=GitHub(fake.run))


# --- R001: one event, several transport copies -------------------------------------------------------


def test_identical_headers_are_one_event() -> None:
    mirror = [good(), good(), good()]  # the same verdict published on the issue and both PRs
    reviews, invalid, duplicates = select_reviews(mirror, "WP-X")
    assert len(reviews) == 1 and invalid == 0 and duplicates == 2
    k = counters(reviews, invalid, duplicates)
    assert k.survived == {"WPX-R001": 1} and k.a_fired == [] and k.rejected_complete == 1 and not k.c_fired
    text = trigger_statement(k)
    assert "1 distinct review event(s) read; 2 transport copies of the same event ignored" in text
    assert "Trigger A has not fired" in text and "Trigger C has not fired: 1" in text
    # a header that differs in any field is a second event
    second = good(type="TARGETED_CLOSURE", complete=False)
    reviews, _, duplicates = select_reviews([good(), good(), second], "WP-X")
    assert len(reviews) == 2 and duplicates == 1
    assert counters(reviews).a_fired == ["WPX-R001"]
    assert "1 transport copy of the same event ignored" in trigger_statement(counters(reviews, 0, 1))


def test_counters_cli_ignores_mirrors_and_counts_distinct_events(
    fake: FakeGitHub, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    header = render(GOOD)
    fake.issue_comments[(CODE, 10)] = [header]
    fake.issue_comments[(CODE, 1)] = [header]  # mirror on the code PR
    fake.issue_comments[(DOCS, 2)] = [header]  # mirror on the docs PR
    assert run(fake, "convergence", "counters", "10") == 0
    out = capsys.readouterr().out
    assert "1 distinct review event(s) read; 2 transport copies" in out
    assert "Trigger A has not fired" in out and "No trigger fired" in out
    fake.issue_comments[(DOCS, 2)].append(render(good(type="TARGETED_CLOSURE", complete=False)))
    assert run(fake, "convergence", "counters", "10") == 0
    assert "Trigger A HAS FIRED: WPX-R001" in capsys.readouterr().out
    target = tmp_path / "m.yaml"
    assert run(fake, "metrics", "10", "--out", str(target)) == 0
    m = yaml.safe_load(target.read_text(encoding="utf-8"))
    assert m["review_events"] == 2 and m["transport_copies_ignored"] == 2 and m["invalid_review_headers"] == 0


# --- R002: pre-write hand-off prerequisites -------------------------------------------------------------


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


# --- R003: every review-bearing fence is accounted for; malformed headers never raise --------------------


@pytest.mark.parametrize(
    "block",
    [
        "```yaml\nreview: null\n```",
        "```yaml\nreview: {wp: WP-X}\n```",
        "```yaml\nreview:\n  wp: WP-X\n```",
        "```yml\nreview : [1, 2]\n```",
    ],
)
def test_every_review_bearing_fence_is_parsed_and_reported_invalid(block: str) -> None:
    records = parse_review_records("prose\n" + block + "\nmore prose\n")
    assert len(records) == 1
    assert errors(validate_review(records[0]))
    reviews, invalid, duplicates = select_reviews(records, "WP-X")
    assert reviews == [] and invalid == 1 and duplicates == 0


def test_non_review_fences_are_not_counted_as_invalid() -> None:
    text = "```yaml\nworkflow:\n  status: SCOPING\n```\n\n```yaml\nexample:\n  review: not-a-header\n```\n"
    assert parse_review_records(text) == []


@pytest.mark.parametrize(
    ("mutation", "path"),
    [
        ({7: "x", "unknown": 1}, "review"),
        ({"schema_version": True}, "review.schema_version"),
        ({"schema_version": 1.0}, "review.schema_version"),
        (
            {"class_confirmation": {"kind": "p", "class": "g", "rule": "r", "outcome": "CONFIRMED", 3: 1}},
            "review.class_confirmation",
        ),
        (
            {"findings": [{"id": "WPX-R001", "class": "CONTRACT_ASSURANCE_DEFECT", "blocking": True, 2: 0}]},
            "review.findings[0]",
        ),
        ({"closed": [{"id": "WPX-R000", "negative_control": "m", None: 1}]}, "review.closed[0]"),
    ],
)
def test_arbitrary_yaml_key_types_and_version_shapes_are_diagnostics(
    mutation: dict[Any, Any], path: str
) -> None:
    record = good()
    record["review"].update(mutation)
    found = [p.path for p in validate_review(record)]  # must not raise
    assert path in found, found


def test_review_check_cli_reports_malformed_headers_without_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "r.md"
    path.write_text("```yaml\nreview: {wp: WP-X, 7: x}\n```\n", encoding="utf-8")
    assert main(["review-check", str(path)]) == 1
    out = capsys.readouterr().out
    assert "ERROR: review" in out and out.strip().endswith("INVALID")
