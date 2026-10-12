"""CE-PROC-P3A-01 acceptance witnesses M1-M10 (minion-agent#213, checkpoint revision 4, AGREED FOR
IMPLEMENTATION): identity (wp, reviewer, round), mirrors by parsed value, conflicts reported and excluded,
chronology from publication metadata with the fence ordinal, scanner-token discovery with one
disposition per claim, plus the reviewer's disclosed scanner boundary."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from minion_process.cli import main
from minion_process.github import GitHub
from minion_process.review import (
    INVALID_SHAPE,
    UNPARSABLE,
    UNSUPPORTED,
    Claim,
    Copy,
    counters,
    discover,
    metrics,
    parse_review_records,
    select_reviews,
    trigger_statement,
    validate_review,
)

from .test_minion_process import CODE, DOCS, SHA_A, SHA_B, FakeGitHub, workflow

HEADER: dict[str, Any] = {
    "review": {
        "schema_version": 2,
        "wp": "WP-X",
        "type": "IMPLEMENTATION_REVIEW",
        "round": 1,
        "complete": True,
        "reviewer": "Codex",
        "author": "Claude",
        "candidate": {"code": SHA_A, "docs": SHA_B},
        "gate_tier_verified": "G3",
        "verdict": "CHANGES_REQUESTED",
        "new_evidence": True,
        "findings": [
            {"id": "WPX-R001", "class": "CONTRACT_ASSURANCE_DEFECT", "blocking": True, "surface": "s1"}
        ],
        "closed": [],
    }
}


def header(**over: Any) -> dict[str, Any]:
    record = copy.deepcopy(HEADER)
    record["review"].update(over)
    return record


def fence(record: dict[str, Any], crlf: bool = False, comment: bool = False, quoted_key: bool = False) -> str:
    text = yaml.safe_dump(record, sort_keys=False)
    if quoted_key:
        text = text.replace("review:", '"review":', 1)
    if comment:
        text = "# published copy\n" + text
    block = "```yaml\n" + text + "```\n"
    return block.replace("\n", "\r\n") if crlf else block


def claim(record: dict[str, Any]) -> Claim:
    return Claim(0, record, None)


def cp(created: str, cid: int, record: dict[str, Any], ordinal: int = 0) -> Copy:
    return Copy(created, cid, Claim(ordinal, record, None))


def run(fake: FakeGitHub, *argv: str) -> int:
    return main(list(argv), gh=GitHub(fake.run))


# --- M1-M3: identity, mirrors, conflicts --------------------------------------------------------------


def test_m1_transport_copies_are_one_event_even_when_bytes_differ() -> None:
    body_issue = fence(header())
    body_code = fence(header(), crlf=True, comment=True, quoted_key=True)
    body_docs = fence(header())
    copies = [
        Copy("2026-10-12T01:00:00Z", 1, parse_review_records(body_issue)[0]),
        Copy("2026-10-12T01:00:05Z", 2, parse_review_records(body_code)[0]),
        Copy("2026-10-12T01:00:09Z", 3, parse_review_records(body_docs)[0]),
    ]
    s = select_reviews(copies, "WP-X")
    assert len(s.events) == 1 and s.mirrors == 2 and s.conflicts == [] and s.invalid_total == 0
    k = counters(s)
    assert k.survived == {"WPX-R001": 1} and k.a_fired == [] and k.rejected_complete == 1
    assert "2 transport copies of the same event ignored" in trigger_statement(k)


def test_m2_separately_issued_rounds_with_equal_fields_are_two_events() -> None:
    copies = [cp("2026-10-12T01:00:00Z", 1, header(round=1)), cp("2026-10-12T02:00:00Z", 2, header(round=2))]
    s = select_reviews(copies, "WP-X")
    assert len(s.events) == 2 and s.mirrors == 0
    assert counters(s).a_fired == ["WPX-R001"]


def test_m3_same_identity_different_values_is_a_reported_conflict_and_presentation_is_a_mirror() -> None:
    conflict = [
        cp("2026-10-12T01:00:00Z", 1, header(round=3)),
        cp("2026-10-12T01:00:05Z", 2, header(round=3, verdict="APPROVED", findings=[])),
    ]
    s = select_reviews(conflict, "WP-X")
    assert s.events == [] and s.mirrors == 0
    assert s.conflicts == [
        {"identity": "(wp=WP-X, reviewer=Codex, round=3)", "fields": ["findings", "verdict"]}
    ]
    text = trigger_statement(counters(s))
    assert "EXCLUDED: 1 conflicting identity" in text and "round=3" in text
    assert "remains mandatory" in text  # no trigger, but never a clean negative
    reordered = header(round=3)
    reordered["review"] = dict(reversed(list(reordered["review"].items())))
    quoted = parse_review_records(fence(header(round=3), quoted_key=True))[0]
    mirror = [cp("2026-10-12T01:00:00Z", 1, reordered), Copy("2026-10-12T01:00:05Z", 2, quoted)]
    s = select_reviews(mirror, "WP-X")
    assert len(s.events) == 1 and s.mirrors == 1 and s.conflicts == []


# --- M4-M5: chronology ------------------------------------------------------------------------------------


def test_m4_events_are_ordered_by_publication_time_across_threads() -> None:
    early = cp("2026-10-12T01:00:00Z", 10, header(round=1, new_evidence=False))
    late = cp("2026-10-12T03:00:00Z", 11, header(round=3, new_evidence=False))
    middle = cp("2026-10-12T02:00:00Z", 1, header(round=2, new_evidence=True))
    s = select_reviews(
        [early, late, middle], "WP-X"
    )  # issue comments first, then the code PR: the old collection order
    assert [e["round"] for e in s.events] == [1, 2, 3]
    k = counters(s)
    assert k.rounds_without_new_evidence == 2 and k.consecutive_without_new_evidence == 1


def test_m5_same_timestamp_round_and_comment_order_by_fence_ordinal() -> None:
    prior = cp("2026-10-12T00:00:00Z", 1, header(round=2, new_evidence=False))
    a = header(round=3, reviewer="A", new_evidence=False)
    b = header(round=3, reviewer="B", new_evidence=True)
    a_first = [
        prior,
        cp("2026-10-12T01:00:00Z", 100, a, ordinal=0),
        cp("2026-10-12T01:00:00Z", 100, b, ordinal=1),
    ]
    b_first = [
        prior,
        cp("2026-10-12T01:00:00Z", 100, b, ordinal=0),
        cp("2026-10-12T01:00:00Z", 100, a, ordinal=1),
    ]
    sa, sb = select_reviews(a_first, "WP-X"), select_reviews(b_first, "WP-X")
    assert counters(sa).consecutive_without_new_evidence == 2
    assert counters(sb).consecutive_without_new_evidence == 1
    assert sa.multi_header_comments == 1 and sb.multi_header_comments == 1
    assert "1 comment(s) carry more than one header" in trigger_statement(counters(sa))


# --- M6-M8: discovery and disposition ----------------------------------------------------------------------

SUPPORTED_INVALID_SHAPE = [
    "# c\nreview: null",
    '"review": null',
    "{review: null}",
    "---\nreview: {wp: WP-X}",
    "%YAML 1.2\n---\nreview: null",
    "﻿review: null",
]
UNSUPPORTED_COMPLETED = [
    "&h\nreview: null",
    "!!map\nreview: null",
    "? review\n: null",
    "? &key review\n: null",
    "? !!str review\n: null",
    "{&key review: null}",
    "{? !!str review: null}",
    "?\n  review\n: null",
    "&h # root anchor\nreview: null",
]
ORDINARY = [
    "example:\n  review: x",
    "workflow:\n  status: SCOPING",
    "data: null",
    "review",
    '"review"',
    "&h review",
    "!!str review",
    "---\nreview",
    "- review",
    "text: |\n  review: null",
    "data: [unclosed",
    "---\ndata: [unclosed",
    "&o\ndata: [unclosed",
    "!!map\ndata: [unclosed",
    "? data\n: [unclosed",
    '"review: [unclosed',  # the scanner fails before any key: no recognizable first entry
    'review: "\x00"',  # the reader rejects the stream before StreamStart (reviewer's disclosed boundary)
    "[review]",
    "? [review]\n: null",  # a collection key is not the scalar key review
    "*alias",
    "{}",  # a mapping with no first entry
    "",  # an empty fence
]
UNPARSABLE_SUPPORTED = [
    "review: [unclosed",
    "---\nreview: [unclosed",
    '%YAML 1.2\n---\n"review": [unclosed',
    "# c\n{review: [unclosed",
    'review: "unterminated',
]
UNSUPPORTED_MALFORMED = [
    "&h\nreview: [unclosed",
    "!!map\nreview: [unclosed",
    "? review\n: [unclosed",
    "? &key review\n: [unclosed",
    "? !!str review\n: [unclosed",
    "{&key review: [unclosed",
    "{? !!str review: [unclosed",
    "?\n  review\n: [unclosed",
    "&h # root anchor\nreview: [unclosed",
]


def fenced(block: str) -> str:
    return "prose\n```yaml\n" + block + "\n```\nmore prose\n"


@pytest.mark.parametrize("block", SUPPORTED_INVALID_SHAPE)
def test_m6a_supported_claims_with_bad_shape_are_invalid_shape(block: str) -> None:
    claims = parse_review_records(fenced(block))
    assert len(claims) == 1 and claims[0].reason is None
    s = select_reviews([Copy("t", 1, claims[0])], "WP-X")
    assert s.events == [] and s.invalid == {UNSUPPORTED: 0, UNPARSABLE: 0, INVALID_SHAPE: 1}


@pytest.mark.parametrize("block", UNSUPPORTED_COMPLETED + UNSUPPORTED_MALFORMED)
def test_m6b_m8b_properties_and_explicit_keys_are_unsupported_whether_or_not_they_parse(block: str) -> None:
    assert discover(block) == (True, True)
    claims = parse_review_records(fenced(block))
    assert [c.reason for c in claims] == [UNSUPPORTED]
    s = select_reviews([Copy("t", 1, claims[0])], "WP-X")
    assert s.invalid[UNSUPPORTED] == 1 and s.invalid_total == 1


@pytest.mark.parametrize("block", ORDINARY)
def test_m7_m8c_ordinary_fences_are_not_claims(block: str) -> None:
    assert discover(block) == (False, False)
    assert parse_review_records(fenced(block)) == []


@pytest.mark.parametrize("block", UNPARSABLE_SUPPORTED)
def test_m8a_supported_claims_that_fail_to_parse_are_unparsable(block: str) -> None:
    assert discover(block) == (True, False)
    claims = parse_review_records(fenced(block))
    assert [c.reason for c in claims] == [UNPARSABLE]


def test_m8_completed_and_malformed_pairs_share_their_discovery() -> None:
    for completed, malformed in zip(UNSUPPORTED_COMPLETED, UNSUPPORTED_MALFORMED, strict=True):
        assert discover(completed) == discover(malformed) == (True, True)
    assert discover("review: null") == discover("review: [unclosed") == (True, False)


def test_fence_ordinal_counts_all_yaml_fences_in_the_comment() -> None:
    text = "```yaml\nworkflow: 1\n```\n\n```yaml\nreview: null\n```\n\n```yml\nreview: [x\n```\n"
    claims = parse_review_records(text)
    assert [(c.ordinal, c.reason) for c in claims] == [(1, None), (2, UNPARSABLE)]


def test_m9_schema_version_1_headers_are_invalid_shape() -> None:
    v1 = header()
    v1["review"]["schema_version"] = 1
    del v1["review"]["round"]
    found = [p.path for p in validate_review(v1)]
    assert "review.schema_version" in found and "review.round" in found
    for bad in (0, -1, True, "1", 1.0):
        assert "review.round" in [p.path for p in validate_review(header(round=bad))], bad
    assert validate_review(header()) == []


# --- end to end through the CLI ---------------------------------------------------------------------------


def test_counters_and_metrics_cli_over_mirrors_rounds_and_junk(
    fake: FakeGitHub, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    r1, r2 = fence(header(round=1)), fence(header(round=2), crlf=True)
    fake.issue_comments[(CODE, 10)] = [
        "plain comment",
        r1,
        {"id": 999, "created_at": "2026-10-13T00:00:00Z", "body": r2},
    ]
    fake.issue_comments[(CODE, 1)] = [
        r1,
        fenced("&h\nreview: null"),
    ]  # mirror of round 1 + an unsupported claim
    fake.issue_comments[(DOCS, 2)] = [fenced("review: [unclosed") + fenced("example:\n  review: x")]
    assert run(fake, "convergence", "counters", "10") == 0
    out = capsys.readouterr().out
    assert "2 distinct review event(s) read" in out
    assert "1 transport copy of the same event ignored" in out
    assert "EXCLUDED: 2 invalid review header(s): 1 unsupported publication form, 1 unparsable" in out
    assert "Trigger A HAS FIRED: WPX-R001" in out
    target = tmp_path / "m.yaml"
    assert run(fake, "metrics", "10", "--out", str(target)) == 0
    m = yaml.safe_load(target.read_text(encoding="utf-8"))
    assert m["review_events"] == 2 and m["transport_copies_ignored"] == 1
    assert m["invalid_review_headers"] == {UNSUPPORTED: 1, UNPARSABLE: 1, INVALID_SHAPE: 0}
    assert m["conflicting_identities"] == [] and m["comments_with_multiple_headers"] == 0
    assert run(fake, "metrics", "10") == 0
    assert "review_events: 2" in capsys.readouterr().out


def test_review_check_cli_reports_every_disposition(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ok = tmp_path / "ok.md"
    ok.write_text(fence(header()), encoding="utf-8")
    assert main(["review-check", str(ok)]) == 0
    assert capsys.readouterr().out.strip() == "VALID"
    for name, block, expected in (
        ("u.md", "&h\nreview: null", UNSUPPORTED),
        ("p.md", "review: [unclosed", UNPARSABLE),
        ("s.md", "review: null", "review: must be a mapping"),
    ):
        path = tmp_path / name
        path.write_text(fenced(block), encoding="utf-8")
        assert main(["review-check", str(path)]) == 1
        out = capsys.readouterr().out
        assert expected in out and out.strip().endswith("INVALID")
    none = tmp_path / "none.md"
    none.write_text(fenced("data: 1"), encoding="utf-8")
    assert main(["review-check", str(none)]) == 1
    assert "found 0" in capsys.readouterr().out


def test_collector_refuses_an_invalid_current_state(
    fake: FakeGitHub, capsys: pytest.CaptureFixture[str]
) -> None:
    from minion_process.model import render_body

    fake.issues[(CODE, 10)]["body"] = render_body({"workflow": workflow(status="BLOCKED")}, "p\n")
    assert run(fake, "metrics", "10") == 1
    assert "current state invalid" in capsys.readouterr().err


def test_metrics_without_events_and_a_handoff_blocked_event() -> None:
    s = select_reviews([], "WP-X")
    m = metrics(workflow(), s)
    assert m["review_events"] == 0 and m["triggers"] == {"A": [], "B": [], "C": False}
    blocked = header(round=5, verdict="HANDOFF_BLOCKED", findings=[], complete=True)
    s = select_reviews([cp("t", 1, blocked), cp("u", 2, header(round=6, wp="OTHER"))], "WP-X")
    assert len(s.events) == 1 and counters(s).rejected_complete == 0
    assert metrics(workflow(), s)["handoff_blocked"] == 1
