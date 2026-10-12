"""Witnesses for Codex's first targeted closure review of CE-PROC-P3A-01 (kit 0.3.0): conflicts report the
differing fields (R001 refinement); loader failures of a recognized claim are `unparsable` and Markdown
example text is not a published fence (R003 refinement); comments without publication metadata are an
explicit, incomplete-making exclusion (PROC-KIT-P3-R004)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from minion_process.cli import main
from minion_process.github import GitHub
from minion_process.review import (
    UNPARSABLE,
    Claim,
    Copy,
    counters,
    metrics,
    parse_review_records,
    select_reviews,
    trigger_statement,
    yaml_fences,
)

from .test_minion_process import CODE, FakeGitHub, workflow
from .test_p3a_convergence import cp, fence, header


def run(fake: FakeGitHub, *argv: str) -> int:
    return main(list(argv), gh=GitHub(fake.run))


# --- R001 refinement: conflicts name the differing fields -------------------------------------------------


def test_conflicts_report_identity_and_differing_fields() -> None:
    s = select_reviews(
        [cp("t1", 1, header(round=1)), cp("t2", 2, header(round=1, verdict="APPROVED", findings=[]))], "WP-X"
    )
    assert s.events == []
    assert s.conflicts == [
        {"identity": "(wp=WP-X, reviewer=Codex, round=1)", "fields": ["findings", "verdict"]}
    ]
    text = trigger_statement(counters(s))
    assert "(wp=WP-X, reviewer=Codex, round=1) differing in findings, verdict" in text
    m = metrics(workflow(), s)
    assert m["conflicting_identities"][0]["fields"] == ["findings", "verdict"]
    # presentation-only differences stay a mirror
    s = select_reviews(
        [
            cp("t1", 1, header(round=1)),
            Copy("t2", 2, parse_review_records(fence(header(round=1), quoted_key=True, crlf=True))[0]),
        ],
        "WP-X",
    )
    assert len(s.events) == 1 and s.mirrors == 1 and s.conflicts == []


# --- R003 refinement: loader failures and Markdown framing -------------------------------------------------


@pytest.mark.parametrize(
    "block",
    [
        "review: " + "[" * 1200 + "0" + "]" * 1200,  # RecursionError in the loader
        "review:\n  round: " + "9" * 5000,  # ValueError: integer string too long
        'review: "unterminated',
    ],
)
def test_recognized_claims_whose_loading_fails_are_unparsable_and_do_not_stop_collection(
    block: str, fake: FakeGitHub, capsys: pytest.CaptureFixture[str]
) -> None:
    claims = parse_review_records("```yaml\n" + block + "\n```\n")
    assert [c.reason for c in claims] == [UNPARSABLE]
    fake.issue_comments[(CODE, 10)] = ["```yaml\n" + block + "\n```\n", fence(header())]
    assert run(fake, "convergence", "counters", "10") == 0
    out = capsys.readouterr().out
    assert "1 distinct review event(s) read" in out and "1 unparsable" in out


def test_markdown_example_text_is_not_a_published_fence() -> None:
    inner = fence(header())
    assert len(parse_review_records(inner)) == 1  # the real thing
    wrapped = "````markdown\n" + inner + "````\n"  # the template's own display of an example
    assert yaml_fences(wrapped) == [] and parse_review_records(wrapped) == []
    tilde_wrapped = "~~~~\n" + inner + "~~~~\n"
    assert parse_review_records(tilde_wrapped) == []
    not_an_opener = "Example " + inner  # an opener is a line-level marker
    assert parse_review_records(not_an_opener) == []
    indented = "   " + inner  # up to three spaces of indentation is still a fence
    assert len(parse_review_records(indented)) == 1
    unclosed = "```yaml\nreview: null\n"
    assert parse_review_records(unclosed) == []  # never closed: not a published block
    two = inner + "\nprose\n" + fence(header(round=2)) + "```text\nreview: null\n```\n"
    assert [c.ordinal for c in parse_review_records(two)] == [0, 1]  # the text fence is not YAML
    assert yaml_fences("```yaml extra info\nreview: null\n```\n") == ["review: null"]
    assert yaml_fences("```yaml\n a\n````\nmore\n```\n") == [" a"]  # a longer run of the same char closes
    assert yaml_fences("~~~yaml\n a\n```\n b\n~~~\n") == [" a\n```\n b"]  # a different char does not close
    assert (
        yaml_fences("``` yaml` x\nreview: null\n```\n") == []
    )  # a backtick in the info string is not a fence


# --- R004: publication metadata completeness ---------------------------------------------------------------


def test_comments_without_publication_metadata_are_excluded_visibly_and_make_the_result_incomplete(
    fake: FakeGitHub, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.issue_comments[(CODE, 10)] = [{"body": fence(header())}]  # the API response lacks id and created_at
    assert run(fake, "convergence", "counters", "10") == 0
    out = capsys.readouterr().out
    assert "EXCLUDED: 1 review claim(s) in comment(s) without publication metadata" in out
    assert "THIS STATEMENT IS INCOMPLETE" in out and "RESULT INCOMPLETE" in out
    assert "No trigger fired" not in out
    target = tmp_path / "m.yaml"
    assert run(fake, "metrics", "10", "--out", str(target)) == 0
    m = yaml.safe_load(target.read_text(encoding="utf-8"))
    assert (
        m["review_events"] == 0 and m["claims_without_publication_metadata"] == 1 and m["complete"] is False
    )
    fake.issue_comments[(CODE, 10)] = [
        {"id": 5, "created_at": "2026-10-12T00:00:05Z", "body": fence(header())}
    ]
    assert run(fake, "convergence", "counters", "10") == 0
    out = capsys.readouterr().out
    assert "1 distinct review event(s) read" in out and "INCOMPLETE" not in out
    partial = [
        {"id": 7, "body": fence(header(round=2))},
        {"created_at": "2026-10-12T00:00:01Z", "body": fence(header(round=3))},
    ]
    fake.issue_comments[(CODE, 10)] = partial
    assert run(fake, "convergence", "counters", "10") == 0
    assert "EXCLUDED: 2 review claim(s)" in capsys.readouterr().out


def test_a_body_less_comment_carries_nothing_and_metadata_is_never_manufactured(fake: FakeGitHub) -> None:
    fake.issue_comments[(CODE, 10)] = [{"id": 1, "created_at": "t"}]  # no body at all
    gh = GitHub(fake.run)
    assert gh.issue_comments(CODE, 10) == []
    fake.issue_comments[(CODE, 10)] = [{"id": "not-an-int", "created_at": 12, "body": "x"}]
    assert gh.issue_comments(CODE, 10) == [{"id": None, "created_at": None, "body": "x"}]
    unorderable = Copy(None, None, Claim(0, header(), None))
    assert not unorderable.orderable
    s = select_reviews([unorderable], "WP-X")
    assert s.unorderable == 1 and not s.complete and s.events == []
