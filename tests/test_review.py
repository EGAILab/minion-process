"""Structured review headers (kit 0.3.0, schema version 2): every shape rule of `validate_review`, with
one mutation per rule; the counters over a prepared selection; the metrics; the offline `review-check`.
Discovery, identity and chronology are covered by `tests/test_p3a_convergence.py`."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from minion_process.cli import main
from minion_process.review import (
    Claim,
    Copy,
    counters,
    metrics,
    select_reviews,
    trigger_statement,
    validate_review,
)

from .test_minion_process import SHA_A, SHA_B, workflow

GOOD: dict[str, Any] = {
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


def render(record: dict[str, Any], prose: str = "Prose below.\n") -> str:
    return "# Review\n\n```yaml\n" + yaml.safe_dump(record, sort_keys=False) + "```\n\n" + prose


def selection(*headers: dict[str, Any]) -> Any:
    """A selection built from valid records published one minute apart."""
    copies = [
        Copy(f"2026-10-12T00:{i:02d}:00Z", i + 1, Claim(0, record, None)) for i, record in enumerate(headers)
    ]
    return select_reviews(copies, "WP-X")


def test_good_record_validates() -> None:
    assert validate_review(good()) == []


@pytest.mark.parametrize(
    ("record", "path"),
    [
        ([], "review"),
        ({"review": 1}, "review"),
        ({"review": GOOD["review"], "extra": 1}, "review"),
        (good(schema_version=1), "review.schema_version"),
        (good(schema_version=True), "review.schema_version"),
        (good(schema_version=2.0), "review.schema_version"),
        (good(surprise=1), "review"),
        (good(wp=""), "review.wp"),
        (good(type="FULL"), "review.type"),
        (good(round=0), "review.round"),
        (good(round=True), "review.round"),
        (good(round="1"), "review.round"),
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
            good(class_confirmation={"kind": "p", "class": "g", "rule": "r", "outcome": "CONFIRMED", 3: 1}),
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
            good(findings=[{"id": "WPX-R001", "class": "CONTRACT_ASSURANCE_DEFECT", "blocking": True, 2: 0}]),
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
        (good(closed=[{"id": "WPX-R000", "negative_control": "m", None: 1}]), "review.closed[0]"),
        ({"review": {**GOOD["review"], 7: "x", "unknown": 1}}, "review"),
    ],
)
def test_one_mutation_per_rule(record: Any, path: str) -> None:
    found = [p.path for p in validate_review(record)]  # must not raise for any YAML key type
    assert path in found, found


def test_missing_required_keys_are_each_reported() -> None:
    found = [p.path for p in validate_review({"review": {"schema_version": 2}})]
    for key in (
        "wp",
        "type",
        "round",
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
    assert validate_review(record) == []
    assert validate_review(good(verdict="HANDOFF_BLOCKED", findings=[])) == []


# --- counters over a prepared selection -------------------------------------------------------------------


def finding(fid: str, surface: str | None = None, blocking: bool = True) -> dict[str, Any]:
    f: dict[str, Any] = {"id": fid, "class": "CONTRACT_ASSURANCE_DEFECT", "blocking": blocking}
    if surface:
        f["surface"] = surface
    return f


def test_counters_and_triggers() -> None:
    s = selection(
        good(round=1, findings=[finding("WPX-R001", "s1")]),
        good(
            round=2,
            complete=False,
            type="TARGETED_CLOSURE",
            findings=[finding("WPX-R001", "s1")],
            new_evidence=False,
        ),
        good(round=3, findings=[finding("WPX-R002", "s1")], new_evidence=False),
        good(round=4, verdict="HANDOFF_BLOCKED", findings=[]),
        good(round=5, verdict="APPROVED", findings=[], new_evidence=True),
    )
    k = counters(s)
    assert k.reviews == 5
    assert k.survived == {"WPX-R001": 2, "WPX-R002": 1} and k.a_fired == ["WPX-R001"]
    assert k.successors == {"s1": ["WPX-R001", "WPX-R002"]} and k.b_fired == ["s1"]
    assert k.rejected_complete == 2 and not k.c_fired
    assert k.rounds_without_new_evidence == 2 and k.consecutive_without_new_evidence == 2
    text = trigger_statement(k)
    assert "Trigger A HAS FIRED: WPX-R001" in text and "Trigger B HAS FIRED" in text
    assert "Trigger C has not fired: 2" in text and "CONVERGENCE TRIGGER FIRED" in text


def test_no_trigger_statement_and_c_trigger() -> None:
    quiet = counters(selection(good(findings=[finding("WPX-R001")])))
    text = trigger_statement(quiet)
    assert "Trigger A has not fired" in text and "(max 1)" in text and "No trigger fired" in text
    three = counters(selection(*(good(round=i + 1, findings=[finding(f"WPX-R00{i}")]) for i in range(3))))
    assert three.c_fired and "Trigger C HAS FIRED: 3" in trigger_statement(three)
    assert trigger_statement(counters(selection())).startswith("0 distinct review event(s) read")


def test_metrics_from_state_and_selection() -> None:
    w = workflow(
        schema_version=2,
        kind="process",
        consequence={"class": "governing", "rule": "CP-3"},
        requirements=[],
        history={
            "routes": [{"rule": "RT-2", "at": "d", "reason": "r"}, {"rule": "RT-6", "at": "d", "reason": "r"}]
        },
    )
    s = selection(
        good(),
        good(
            round=2,
            verdict="APPROVED",
            complete=False,
            type="TARGETED_CLOSURE",
            gate_tier_verified="G1",
            findings=[],
            closed=[{"id": "WPX-R001", "negative_control": "NOT_APPLICABLE", "reason": "documentary"}],
        ),
    )
    m = metrics(w, s)
    assert m["work_package"] == "WP-X" and m["kind"] == "process" and m["class"] == "governing"
    assert m["review_events"] == 2 and m["complete_reviews"] == 1 and m["targeted_reviews"] == 1
    assert m["approvals"] == 1 and m["rejected_complete_reviews"] == 1 and m["handoff_blocked"] == 0
    assert m["findings_recorded"] == 2
    assert m["findings_by_class"] == {"CONTRACT_ASSURANCE_DEFECT": 1, "PI_PARITY_DEFECT": 1}
    assert m["closed_with_negative_control"] == 1 and m["closed_documentary"] == 1
    assert m["gate_tiers_verified"] == {"G1": 1, "G3": 1}
    assert m["routes_taken"] == [("RT-2", 1), ("RT-6", 1)] and m["owner_questions_routed"] == 1
    assert m["triggers"] == {"A": [], "B": [], "C": False}
    bare = metrics(workflow(), selection())
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
