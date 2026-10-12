"""Structured review headers (kit 0.3.0): parsing, every shape rule, the §11.8 counters, the trigger
statement and the §14.6 metrics; and the offline `review-check` verb."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from minion_process.cli import main
from minion_process.review import (
    counters,
    metrics,
    parse_review_records,
    select_reviews,
    trigger_statement,
    validate_review,
)

from .test_minion_process import SHA_A, SHA_B, workflow

GOOD: dict[str, Any] = {
    "review": {
        "schema_version": 1,
        "wp": "WP-X",
        "type": "IMPLEMENTATION_REVIEW",
        "complete": True,
        "reviewer": "Codex",
        "author": "Claude",
        "candidate": {"code": SHA_A, "docs": SHA_B},
        "gate_tier_verified": "G3",
        "class_confirmation": {
            "kind": "process",
            "class": "governing",
            "rule": "CP-3",
            "outcome": "CONFIRMED",
        },
        "verdict": "CHANGES_REQUESTED",
        "new_evidence": True,
        "findings": [
            {"id": "WPX-R001", "class": "CONTRACT_ASSURANCE_DEFECT", "blocking": True, "surface": "intake"},
            {"id": "WPX-Q001", "class": "PI_PARITY_DEFECT", "blocking": False},
        ],
        "closed": [{"id": "WPX-R000", "negative_control": "revert fix in worktree; witness FAILS"}],
    }
}


def good(**over: Any) -> dict[str, Any]:
    record = copy.deepcopy(GOOD)
    record["review"].update(over)
    return record


def problems(record: Any) -> list[str]:
    return [str(p) for p in validate_review(record)]


def render(record: dict[str, Any], prose: str = "Prose below.\n") -> str:
    return "# Review\n\n```yaml\n" + yaml.safe_dump(record, sort_keys=False) + "```\n\n" + prose


def test_good_record_validates_and_round_trips_through_the_fence() -> None:
    assert problems(good()) == []
    records = parse_review_records(render(good()))
    assert records == [good()]
    assert parse_review_records("no header here") == []
    assert parse_review_records("```yaml\nreview:\n  - [unclosed\n```") == ["<unparsable>"]
    assert parse_review_records("```yaml\nworkflow:\n  a: 1\n```") == []  # a state block is not a review


@pytest.mark.parametrize(
    ("record", "path"),
    [
        ([], "review"),
        ({"review": 1}, "review"),
        ({"review": GOOD["review"], "extra": 1}, "review"),
        (good(schema_version=2), "review.schema_version"),
        (good(surprise=1), "review"),
        (good(wp=""), "review.wp"),
        (good(type="FULL"), "review.type"),
        (good(complete="yes"), "review.complete"),
        (good(new_evidence=None), "review.new_evidence"),
        (good(reviewer=" "), "review.reviewer"),
        (good(author=None), "review.author"),
        (good(reviewer="claude"), "review.reviewer"),  # same as author, case-insensitive
        (good(candidate={}), "review.candidate"),
        (good(candidate=[SHA_A]), "review.candidate"),
        (good(candidate={"code": "abc"}), "review.candidate.code"),
        (good(candidate={"": SHA_A}), "review.candidate"),
        (good(gate_tier_verified="G9"), "review.gate_tier_verified"),
        (good(class_confirmation="ok"), "review.class_confirmation"),
        (
            good(
                class_confirmation={"kind": "process", "class": "governing", "rule": "CP-3", "outcome": "YES"}
            ),
            "review.class_confirmation.outcome",
        ),
        (
            good(
                class_confirmation={"kind": "", "class": "governing", "rule": "CP-3", "outcome": "CONFIRMED"}
            ),
            "review.class_confirmation.kind",
        ),
        (
            good(class_confirmation={"kind": "p", "class": "g", "rule": "r", "outcome": "CONFIRMED", "x": 1}),
            "review.class_confirmation",
        ),
        (good(verdict="LGTM"), "review.verdict"),
        (good(verdict="APPROVED"), "review.verdict"),  # with a blocking finding
        (good(verdict="HANDOFF_BLOCKED"), "review.findings"),
        (good(findings={}), "review.findings"),
        (good(findings=["WPX-R001"]), "review.findings[0]"),
        (
            good(findings=[{"id": "bad id", "class": "CONTRACT_ASSURANCE_DEFECT", "blocking": True}]),
            "review.findings[0].id",
        ),
        (good(findings=[{"id": "WPX-R001", "class": "weird", "blocking": True}]), "review.findings[0].class"),
        (
            good(findings=[{"id": "WPX-R001", "class": "CONTRACT_ASSURANCE_DEFECT", "blocking": "yes"}]),
            "review.findings[0].blocking",
        ),
        (
            good(
                findings=[
                    {"id": "WPX-R001", "class": "CONTRACT_ASSURANCE_DEFECT", "blocking": True, "surface": ""}
                ]
            ),
            "review.findings[0].surface",
        ),
        (
            good(
                findings=[{"id": "WPX-R001", "class": "CONTRACT_ASSURANCE_DEFECT", "blocking": True, "x": 1}]
            ),
            "review.findings[0]",
        ),
        (
            good(findings=[GOOD["review"]["findings"][0], GOOD["review"]["findings"][0]]),
            "review.findings[1].id",
        ),
        (good(closed="none"), "review.closed"),
        (good(closed=["WPX-R000"]), "review.closed[0]"),
        (good(closed=[{"id": "x", "negative_control": "m"}]), "review.closed[0].id"),
        (good(closed=[{"id": "WPX-R000"}]), "review.closed[0].negative_control"),
        (good(closed=[{"id": "WPX-R000", "negative_control": "NOT_APPLICABLE"}]), "review.closed[0].reason"),
        (good(closed=[{"id": "WPX-R000", "negative_control": "m", "x": 1}]), "review.closed[0]"),
    ],
)
def test_one_mutation_per_rule(record: Any, path: str) -> None:
    found = [p.path for p in validate_review(record)]
    assert path in found, found


def test_missing_required_keys_are_each_reported() -> None:
    record = {"review": {"schema_version": 1}}
    found = [p.path for p in validate_review(record)]
    for key in (
        "wp",
        "type",
        "complete",
        "reviewer",
        "author",
        "candidate",
        "verdict",
        "new_evidence",
        "findings",
        "closed",
    ):
        assert f"review.{key}" in found


def test_documentary_closure_and_approval_without_blockers_are_valid() -> None:
    record = good(
        verdict="APPROVED",
        findings=[{"id": "WPX-Q001", "class": "PI_PARITY_DEFECT", "blocking": False}],
        closed=[
            {
                "id": "WPX-R000",
                "negative_control": "NOT_APPLICABLE",
                "reason": "documentary/traceability-only",
            }
        ],
    )
    assert problems(record) == []
    assert problems(good(verdict="HANDOFF_BLOCKED", findings=[])) == []


# --- counters -------------------------------------------------------------------------------------


def review(**over: Any) -> dict[str, Any]:
    return good(**over)["review"]


def finding(fid: str, surface: str | None = None, blocking: bool = True) -> dict[str, Any]:
    f: dict[str, Any] = {"id": fid, "class": "CONTRACT_ASSURANCE_DEFECT", "blocking": blocking}
    if surface:
        f["surface"] = surface
    return f


def test_select_reviews_filters_by_wp_and_counts_invalid_headers() -> None:
    records = [good(), good(wp="WP-OTHER"), {"review": 1}, "<unparsable>"]
    reviews, invalid = select_reviews(records, "WP-X")
    assert len(reviews) == 1 and invalid == 2


def test_counters_and_triggers() -> None:
    reviews = [
        review(findings=[finding("WPX-R001", "s1")]),
        review(
            complete=False, type="TARGETED_CLOSURE", findings=[finding("WPX-R001", "s1")], new_evidence=False
        ),
        review(findings=[finding("WPX-R002", "s1")], new_evidence=False),
        review(verdict="HANDOFF_BLOCKED", findings=[]),
        review(verdict="APPROVED", findings=[], new_evidence=True),
    ]
    k = counters(reviews, invalid=1)
    assert k.reviews == 5 and k.invalid == 1
    assert k.survived == {"WPX-R001": 2, "WPX-R002": 1}
    assert k.a_fired == ["WPX-R001"]
    assert k.successors == {"s1": ["WPX-R001", "WPX-R002"]} and k.b_fired == ["s1"]
    assert k.rejected_complete == 2 and not k.c_fired
    assert k.rounds_without_new_evidence == 2 and k.consecutive_without_new_evidence == 2
    text = trigger_statement(k)
    assert "Trigger A HAS FIRED: WPX-R001" in text
    assert "Trigger B HAS FIRED" in text and "Trigger C has not fired: 2" in text
    assert "1 invalid header(s) ignored" in text and "CONVERGENCE TRIGGER FIRED" in text


def test_no_trigger_statement_and_c_trigger() -> None:
    quiet = counters([review(findings=[finding("WPX-R001")])])
    text = trigger_statement(quiet)
    assert "Trigger A has not fired" in text and "(max 1)" in text and "No trigger fired" in text
    three = counters([review(findings=[finding(f"WPX-R00{i}")]) for i in range(3)])
    assert three.c_fired and "Trigger C HAS FIRED: 3" in trigger_statement(three)
    assert trigger_statement(counters([])).startswith("0 review record(s) read")


def test_metrics_from_state_and_reviews() -> None:
    w = workflow(
        schema_version=2,
        kind="process",
        consequence={"class": "governing", "rule": "CP-3"},
        requirements=[],
        history={
            "routes": [{"rule": "RT-2", "at": "d", "reason": "r"}, {"rule": "RT-6", "at": "d", "reason": "r"}]
        },
    )
    reviews = [
        review(),
        review(
            verdict="APPROVED",
            complete=False,
            type="TARGETED_CLOSURE",
            gate_tier_verified="G1",
            findings=[],
            closed=[{"id": "WPX-R001", "negative_control": "NOT_APPLICABLE", "reason": "documentary"}],
        ),
    ]
    m = metrics(w, reviews, invalid=1)
    assert m["work_package"] == "WP-X" and m["kind"] == "process" and m["class"] == "governing"
    assert m["review_events"] == 2 and m["complete_reviews"] == 1 and m["targeted_reviews"] == 1
    assert m["approvals"] == 1 and m["rejected_complete_reviews"] == 1 and m["handoff_blocked"] == 0
    assert m["findings_recorded"] == 2
    assert m["findings_by_class"] == {"CONTRACT_ASSURANCE_DEFECT": 1, "PI_PARITY_DEFECT": 1}
    assert m["closed_with_negative_control"] == 1 and m["closed_documentary"] == 1
    assert m["gate_tiers_verified"] == {"G1": 1, "G3": 1}
    assert m["routes_taken"] == [("RT-2", 1), ("RT-6", 1)] and m["owner_questions_routed"] == 1
    assert m["triggers"] == {"A": [], "B": [], "C": False} and m["invalid_review_headers"] == 1
    bare = metrics(workflow(), [])
    assert bare["kind"] is None and bare["class"] is None and bare["routes_taken"] == []


# --- the offline verb ---------------------------------------------------------------------------------


def test_review_check_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ok = tmp_path / "ok.md"
    ok.write_text(render(good()), encoding="utf-8")
    assert main(["review-check", str(ok)]) == 0
    assert capsys.readouterr().out.strip() == "VALID"
    bad = tmp_path / "bad.md"
    bad.write_text(render(good(reviewer="Claude")), encoding="utf-8")
    assert main(["review-check", str(bad)]) == 1
    out = capsys.readouterr().out
    assert "review.reviewer" in out and out.strip().endswith("INVALID")
    none = tmp_path / "none.md"
    none.write_text("just prose\n", encoding="utf-8")
    assert main(["review-check", str(none)]) == 1
    assert "expected exactly one `review:` header, found 0" in capsys.readouterr().out
