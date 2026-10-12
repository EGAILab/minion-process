"""Kinds, consequence classes, stage skips and delegated routes (`coordination-state.md` §14, kit 0.2.0):
validator shape rules and the `apply` guard. Owner decisions 2 and 3 (minion-agent#205) and `#75`
Amendment 2."""

from __future__ import annotations

from typing import Any

import pytest

from minion_process.github import GitHub
from minion_process.model import render_body
from minion_process.ops import CheckFailed, classification_guard, commit_state
from minion_process.validate import errors, validate_workflow

from .test_minion_process import CODE, SHA_A, FakeGitHub, workflow

CLASSIFIED: dict[str, Any] = {
    "schema_version": 2,
    "kind": "process",
    "consequence": {"class": "governing", "rule": "CP-3", "confirmed_by": "Codex"},
    "requirements": [],
}


def wf(**overrides: Any) -> dict[str, Any]:
    return workflow(**{**CLASSIFIED, **overrides})


def paths(w: dict[str, Any]) -> list[str]:
    return [p.path for p in errors(validate_workflow(w))]


def test_a_classified_process_wp_is_valid_and_an_unclassified_v2_wp_only_warns() -> None:
    assert errors(validate_workflow(wf())) == []
    problems = validate_workflow(workflow(schema_version=2))
    assert errors(problems) == []
    assert any(p.path == "kind" and p.level == "warning" for p in problems)
    assert not any(p.path == "kind" for p in validate_workflow(workflow()))  # v1: no warning


@pytest.mark.parametrize(
    ("overrides", "path"),
    [
        ({"kind": "magic"}, "kind"),
        ({"kind": ["process"]}, "kind"),
        ({"consequence": "governing"}, "consequence"),
        ({"consequence": {"class": "big", "rule": "CP-1"}}, "consequence.class"),
        ({"consequence": {"class": "governing", "rule": "CP 9"}}, "consequence.rule"),
        ({"consequence": {"class": "governing", "rule": "cp-1"}}, "consequence.rule"),
        ({"consequence": {"class": "governing", "rule": ["CP-1"]}}, "consequence.rule"),
        ({"consequence": {"class": "governing", "rule": "CP-0"}}, "consequence.rule"),
        ({"consequence": {"class": "mechanical", "rule": "CP-2"}}, "consequence.rule"),
        ({"consequence": {"class": "mechanical", "rule": "L13-X-R1"}}, "consequence.rule"),
        (
            {"consequence": {"class": "governing", "rule": "CP-1", "confirmed_by": ""}},
            "consequence.confirmed_by",
        ),
        (
            {"consequence": {"class": "governing", "rule": "CP-1", "upgraded_by": "L13-X-R1"}},
            "consequence.upgraded_by",
        ),
        (
            {"consequence": {"class": "governing", "rule": "CP-1", "downgrade": "yes"}},
            "consequence.downgrade",
        ),
        (
            {"consequence": {"class": "mechanical", "rule": "CP-0", "downgrade": {"owner_decision": "x"}}},
            "consequence.downgrade.reviewer",
        ),
        ({"consequence": {"class": "governing", "rule": "CP-1", "extra": 1}}, "consequence"),
        (
            {
                "kind": "semantic",
                "requirements": ["TOOL-1"],
                "consequence": {"class": "mechanical", "rule": "CP-0"},
            },
            "consequence.class",
        ),
        ({"kind": "delta", "requirements": []}, "requirements"),
        ({"kind": "process", "requirements": ["TOOL-1"]}, "requirements"),
        ({"kind": "status", "requirements": ["TOOL-1"]}, "requirements"),
        ({"kind": "scoping", "status": "CONTRACT_DRAFT"}, "status"),
        (
            {
                "status": "CONTRACT_CONVERGENCE",
                "convergence": {"episode": "CE-1", "open_findings": ["L13-X-R1"]},
                "consequence": {"class": "mechanical", "rule": "CP-0"},
            },
            "consequence.class",
        ),
        ({"skipped": "none"}, "skipped"),
        (
            {"skipped": [{"stage": "x", "rule": "SK-1", "measured_rows": ["r"], "reviewer": "Codex"}]},
            "skipped",
        ),
        ({"consequence": {"class": "mechanical", "rule": "CP-0"}, "skipped": ["x"]}, "skipped[0]"),
        (
            {
                "consequence": {"class": "mechanical", "rule": "CP-0"},
                "skipped": [
                    {
                        "stage": "FINAL_CONTRACT_REVIEW",
                        "rule": "SK-1",
                        "measured_rows": ["r"],
                        "reviewer": "Codex",
                    }
                ],
            },
            "skipped[0].stage",
        ),
        (
            {
                "consequence": {"class": "mechanical", "rule": "CP-0"},
                "skipped": [{"stage": "", "rule": "skip", "measured_rows": [], "reviewer": None}],
            },
            "skipped[0].rule",
        ),
        ({"history": {"routes": "RT-1"}}, "history.routes"),
        ({"history": {"routes": ["RT-1"]}}, "history.routes[0]"),
        (
            {"history": {"routes": [{"rule": "RT-9", "at": "2026-10-12", "reason": "x"}]}},
            "history.routes[0].rule",
        ),
        ({"history": {"routes": [{"rule": "RT-1", "at": "", "reason": "x"}]}}, "history.routes[0].at"),
    ],
)
def test_classification_shape_errors(overrides: dict[str, Any], path: str) -> None:
    found = paths(wf(**overrides))
    assert path in found, found


def test_valid_skip_and_route_records() -> None:
    w = wf(
        consequence={"class": "mechanical", "rule": "CP-0"},
        skipped=[
            {
                "stage": "IMPLEMENTATION_REVIEW",
                "rule": "SK-1",
                "measured_rows": ["F1.-0", "F1.inf"],
                "reviewer": "Codex",
            }
        ],
        history={
            "assurance_index": "x.md",
            "routes": [{"rule": "RT-2", "at": "2026-10-12", "reason": "WP-B idle"}],
        },
    )
    assert errors(validate_workflow(w)) == []
    upgraded = wf(consequence={"class": "governing", "rule": "L13-X-R1", "upgraded_by": ["L13-X-R1"]})
    assert errors(validate_workflow(upgraded)) == []
    assert errors(validate_workflow(wf(kind="semantic", requirements=["TOOL-1"]))) == []
    assert errors(validate_workflow(wf(kind="scoping", status="SCOPING"))) == []


# --- the apply guard ----------------------------------------------------------------------------


def test_guard_requires_classification_at_intake() -> None:
    old = workflow(schema_version=2, status="SCOPING")
    new = {**old, "status": "CONTRACT_DRAFT"}
    assert "intake requires classification" in str(classification_guard(old, new))
    legacy = workflow(status="SCOPING")  # schema v1: pre-kit WPs are not re-classified mid-flight
    assert classification_guard(legacy, {**legacy, "status": "CONTRACT_DRAFT"}) is None
    assert classification_guard(old, {**old, "status": "BLOCKED_FOR_OWNER"}) is None
    assert classification_guard(old, {**old, "status": "WAITING_FOR_TRIGGER"}) is None
    assert classification_guard(old, {**new, **CLASSIFIED}) is None


def test_guard_fixes_the_kind_after_intake_and_allows_change_during_scoping() -> None:
    old = wf(status="CONTRACT_DRAFT")
    assert "kind is fixed after intake" in str(classification_guard(old, {**old, "kind": "status"}))
    scoping = wf(status="SCOPING")
    assert classification_guard(scoping, {**scoping, "kind": "status"}) is None


def test_guard_makes_downgrade_owner_only_and_upgrade_free() -> None:
    old = wf()
    mechanical = {**old, "consequence": {"class": "mechanical", "rule": "CP-0"}}
    assert "Owner-only" in str(classification_guard(old, mechanical))
    with_downgrade = {
        **old,
        "consequence": {
            "class": "mechanical",
            "rule": "CP-0",
            "downgrade": {"owner_decision": "#205 ...", "reviewer": "Codex"},
        },
    }
    assert "governance_source" in str(classification_guard(old, with_downgrade))
    assert classification_guard(old, {**with_downgrade, "governance_source": {"artifact": "x"}}) is None
    assert classification_guard(old, {**with_downgrade, "governance_source": {"artifact": None}}) is not None
    up_from = {**old, "consequence": {"class": "mechanical", "rule": "CP-0"}}
    upgraded = {**old, "consequence": {"class": "governing", "rule": "L13-X-R1"}}
    assert classification_guard(up_from, upgraded) is None


def test_guard_routes_closure_by_kind() -> None:
    final = wf(status="FINAL_CONTRACT_REVIEW")
    assert classification_guard(final, {**final, "status": "CLOSED"}) is None
    semantic = wf(status="FINAL_CONTRACT_REVIEW", kind="semantic", requirements=["TOOL-1"])
    assert "CLOSURE_REVIEW" in str(classification_guard(semantic, {**semantic, "status": "CLOSED"}))
    scoping = wf(status="SCOPING", kind="scoping")
    assert classification_guard(scoping, {**scoping, "status": "CLOSED"}) is None
    process_in_scoping = wf(status="SCOPING")
    assert "scoping-only route" in str(
        classification_guard(process_in_scoping, {**process_in_scoping, "status": "CLOSED"})
    )
    unclassified = workflow(status="FINAL_CONTRACT_REVIEW")
    assert classification_guard(unclassified, {**unclassified, "status": "CLOSED"}) is None


def test_commit_state_runs_the_guard(fake: FakeGitHub) -> None:
    gh = GitHub(fake.run)
    fake.issues[(CODE, 10)]["body"] = render_body(
        {"workflow": workflow(schema_version=2, status="SCOPING", code=None, docs=None)}, "p\n"
    )

    def leave_scoping(w: dict[str, Any]) -> None:
        w["status"] = "CONTRACT_DRAFT"

    with pytest.raises(CheckFailed, match="intake requires classification"):
        commit_state(gh, CODE, 10, leave_scoping, {"status"})

    def classify_and_leave(w: dict[str, Any]) -> None:
        w["status"] = "CONTRACT_DRAFT"
        w["kind"] = "process"
        w["consequence"] = {"class": "mechanical", "rule": "CP-0"}

    changed, _ = commit_state(gh, CODE, 10, classify_and_leave, {"status", "kind", "consequence"})
    assert changed == ["consequence", "kind", "status"]
    assert SHA_A  # fixture import used
