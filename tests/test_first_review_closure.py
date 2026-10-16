"""Guarded `IMPLEMENTATION_REVIEW -> CLOSED` for a clean process or status work package
(`coordination-state.md` §10.2a; `minion-process#12`, Owner decision `minion-agent#222`
issuecomment-6209854474). One refusal witness per guard clause; every refusal makes zero writes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from minion_process.cli import main
from minion_process.composite import close as composite_close
from minion_process.github import GitHub
from minion_process.model import render_body, split_body
from minion_process.ops import CheckFailed, commit_state
from minion_process.transitions import check_transition

from .test_minion_process import CODE, DOCS, SHA_A, SHA_B, FakeGitHub, workflow

MERGED = "d" * 40
OTHER = "e" * 40
DROP = object()
SEMANTIC = {
    "kind": "semantic",
    "consequence": {"class": "governing", "rule": "CP-3", "confirmed_by": "Codex"},
    "requirements": ["HAR-001"],
}
LEGACY_UNCLASSIFIED = {"schema_version": 1, "kind": DROP, "consequence": DROP}


def _wp(**changes: Any) -> dict[str, Any]:
    state = workflow(
        schema_version=2,
        kind="process",
        consequence={"class": "mechanical", "rule": "CP-0"},
        requirements=[],
        open_findings=[],
        code=None,
        docs={"pr": 312, "sha": SHA_B, "base": "master", "merged_sha": MERGED},
        next_owner="Claude",
        next_action="close the WP",
    )
    state.update(changes)
    return {k: v for k, v in state.items() if v is not DROP}


def _header(**changes: Any) -> dict[str, Any]:
    review: dict[str, Any] = {
        "schema_version": 2,
        "wp": "WP-X",
        "type": "IMPLEMENTATION_REVIEW",
        "round": 1,
        "complete": True,
        "reviewer": "Codex",
        "author": "Claude",
        "candidate": {"docs": SHA_B},
        "verdict": "APPROVED",
        "new_evidence": False,
        "findings": [],
        "closed": [],
    }
    review.update(changes)
    return review


def _comment(review: dict[str, Any], cid: int, at: str | None = "2026-10-16T01:00:00Z") -> dict[str, Any]:
    body = "```yaml\n" + yaml.safe_dump({"review": review}, sort_keys=False) + "```\nprose\n"
    entry: dict[str, Any] = {"id": cid, "body": body}
    if at is not None:
        entry["created_at"] = at
    return entry


def _fake(
    state: dict[str, Any],
    reviews: list[dict[str, Any]] | None = None,
    pr: dict[str, Any] | None = None,
    on_default: bool = True,
) -> FakeGitHub:
    fake = FakeGitHub()
    fake.issues[(CODE, 10)] = {"body": render_body({"workflow": state}, ""), "state": "OPEN", "title": "x"}
    fake.issue_comments[(CODE, 10)] = reviews if reviews is not None else [_comment(_header(), 1)]
    fake.prs[(DOCS, 312)] = {
        "state": "MERGED",
        "mergeCommit": {"oid": MERGED},
        "headRefOid": SHA_B,
        "isDraft": False,
        **(pr or {}),
    }
    if on_default:
        fake.on_default.add(MERGED)
    return fake


ALLOWED = {
    "status",
    "next_owner",
    "next_action",
    "requirements",
    "open_findings",
    "provisionally_closed",
    "convergence",
    "kind",
    "work_package",
    "docs",
    "code",
}


def _close(fake: FakeGitHub, extra: dict[str, Any] | None = None) -> None:
    def mutate(w: dict[str, Any]) -> None:
        w["status"] = "CLOSED"
        w["next_owner"] = None
        w["next_action"] = None
        w.update(extra or {})

    commit_state(GitHub(fake.run), CODE, 10, mutate, ALLOWED)


def test_the_route_is_in_the_transition_table() -> None:
    assert check_transition("IMPLEMENTATION_REVIEW", "CLOSED") is None


@pytest.mark.parametrize("kind", ["process", "status"])
def test_a_clean_first_review_closes_and_the_remote_state_round_trips(kind: str) -> None:
    fake = _fake(_wp(kind=kind))
    _close(fake)
    assert fake.edits == 1
    assert split_body(fake.issues[(CODE, 10)]["body"]).workflow["status"] == "CLOSED"


def test_the_approval_may_be_published_on_the_candidate_pr() -> None:
    fake = _fake(_wp(), reviews=[])
    fake.issue_comments[(DOCS, 312)] = [_comment(_header(), 7)]
    _close(fake)
    assert fake.edits == 1


def test_a_process_review_type_and_a_two_sided_candidate_close() -> None:
    code = {"pr": 9, "sha": SHA_A, "base": "main", "merged_sha": OTHER}
    fake = _fake(
        _wp(code=code),
        reviews=[_comment(_header(type="PROCESS_REVIEW", candidate={"code": SHA_A, "docs": SHA_B}), 1)],
    )
    fake.prs[(CODE, 9)] = {"state": "MERGED", "mergeCommit": {"oid": OTHER}, "headRefOid": SHA_A}
    fake.on_default.add(OTHER)
    _close(fake)
    assert fake.edits == 1


def test_composite_close_uses_the_route_and_records_the_merge() -> None:
    state = _wp(docs={"pr": 312, "sha": SHA_B, "base": "master"})  # close records merged_sha itself
    fake = _fake(state)
    changed, merged = composite_close(GitHub(fake.run), CODE, 10, "closed: clean first review")
    assert merged == {"docs": MERGED} and "status" in changed
    assert fake.closed and fake.edits == 1


def test_composite_close_dry_run_refuses_an_unapproved_wp_without_writing() -> None:
    state = _wp(docs={"pr": 312, "sha": SHA_B, "base": "master"})
    fake = _fake(state, reviews=[_comment(_header(verdict="CHANGES_REQUESTED", findings=[]), 1)])
    with pytest.raises(CheckFailed, match="not a complete APPROVED"):
        composite_close(GitHub(fake.run), CODE, 10, "closed", dry_run=True)
    assert fake.edits == 0 and not fake.closed


LATER = "2026-10-16T02:00:00Z"
BLOCKING = [{"id": "WP-X-R001", "class": "CONTRACT_ASSURANCE_DEFECT", "blocking": True}]


@pytest.mark.parametrize(
    ("state", "reviews", "patch", "fake_kwargs", "message"),
    [
        # 1. kind
        (SEMANTIC, None, None, {}, "clean process or status WP"),
        ({**SEMANTIC, "kind": "delta"}, None, None, {}, "clean process or status WP"),
        (LEGACY_UNCLASSIFIED, None, None, {}, "clean process or status WP"),
        # 2. requirements (the validator already refuses a process WP that owns a requirement)
        ({"requirements": ["HAR-001"]}, None, None, {}, "requirements"),
        ({}, None, {"requirements": ["HAR-001"]}, {}, "requirements"),
        ({"requirements": None}, None, None, {}, "explicit \\[\\]"),
        ({}, None, {"requirements": None}, {}, "explicit \\[\\]"),
        # 3. open findings
        ({"open_findings": ["WP-X-R001"]}, None, None, {}, "open findings"),
        ({"open_findings": ["WP-X-R001"]}, None, {"open_findings": []}, {}, "cannot clear"),
        # candidates
        ({"docs": None}, None, None, {}, "at least one recorded candidate"),
        ({"docs": {"pr": 312, "sha": SHA_B, "base": "master"}}, None, None, {}, "merged_sha"),
        # 4. a complete, independent, published APPROVED review
        ({}, [], None, {}, "none found"),
        ({}, [_comment(_header(wp="WP-OTHER"), 1)], None, {}, "none found"),
        ({}, [_comment(_header(verdict="CHANGES_REQUESTED"), 1)], None, {}, "not a complete APPROVED"),
        ({}, [_comment(_header(complete=False), 1)], None, {}, "not a complete APPROVED"),
        ({}, [_comment(_header(type="CHECKPOINT"), 1)], None, {}, "is not one of"),
        ({}, [_comment(_header(reviewer="Claude"), 1)], None, {}, "1 invalid header"),
        ({}, [_comment(_header(findings=BLOCKING), 1)], None, {}, "1 invalid header"),
        (
            {},
            [_comment(_header(), 1), _comment(_header(verdict="CHANGES_REQUESTED", round=2), 2, LATER)],
            None,
            {},
            "not a complete APPROVED",
        ),
        (
            {},
            [_comment(_header(), 1), _comment(_header(new_evidence=True), 2, LATER)],
            None,
            {},
            "1 conflict",
        ),
        ({}, [_comment(_header(), 1, at=None)], None, {}, "1 unorderable"),
        # 5. no candidate change since the approval
        ({}, [_comment(_header(candidate={"docs": OTHER}), 1)], None, {}, "not the exact final candidate"),
        (
            {},
            [_comment(_header(candidate={"docs": SHA_B, "code": SHA_A}), 1)],
            None,
            {},
            "not the exact final candidate",
        ),
        (
            {},
            None,
            {"docs": {"pr": 312, "sha": OTHER, "base": "master", "merged_sha": MERGED}},
            {},
            "changed the candidate",
        ),
        # 6. merged at the recorded SHA
        ({}, None, None, {"pr": {"state": "OPEN", "mergeCommit": None}}, "not merged"),
        ({}, None, None, {"pr": {"mergeCommit": {"oid": OTHER}}}, "not merged"),
        ({}, None, None, {"pr": {"headRefOid": OTHER}}, "not the approved"),
        # 7. reachable from the default branch
        ({}, None, None, {"on_default": False}, "default branch"),
    ],
    ids=[
        "kind-semantic",
        "kind-delta",
        "kind-missing",
        "product-requirement",
        "closure-adds-requirement",
        "requirements-null",
        "closure-nulls-requirements",
        "open-finding",
        "closure-clears-finding",
        "no-candidate",
        "candidate-without-merged-sha",
        "no-published-review",
        "other-wp-review-not-credited",
        "latest-rejected",
        "incomplete-review",
        "wrong-review-type",
        "self-review",
        "approved-with-blocking-finding",
        "later-rejection-supersedes-approval",
        "conflicting-copies",
        "unorderable-copy",
        "stale-approval-other-sha",
        "approval-of-a-different-candidate-map",
        "closure-changes-candidate",
        "pr-not-merged",
        "merge-commit-mismatch",
        "merged-head-not-approved",
        "merge-off-default-branch",
    ],
)
def test_the_route_is_refused_with_zero_writes_unless_every_clause_holds(
    state: dict[str, Any],
    reviews: list[dict[str, Any]] | None,
    patch: dict[str, Any] | None,
    fake_kwargs: dict[str, Any],
    message: str,
) -> None:
    fake = _fake(_wp(**state), reviews, **fake_kwargs)
    with pytest.raises(CheckFailed, match=message):
        _close(fake, patch)
    assert fake.edits == 0


def test_the_other_closure_routes_are_not_widened() -> None:
    for state in (
        "CONTRACT_DRAFT",
        "CONTRACT_REVIEW",
        "PYTHON_IMPLEMENTATION",
        "REMEDIATION",
        "RUST_IMPLEMENTATION",
    ):
        assert check_transition(state, "CLOSED") is not None
    assert check_transition("BLOCKED_FOR_OWNER", "CLOSED") is not None
    assert check_transition("FINAL_CONTRACT_REVIEW", "CLOSED") is None
    assert check_transition("CLOSURE_REVIEW", "CLOSED") is None


# --- KIT-032-R001: the approval source is bound to the current identity and the issue's history ---------


def _merged_pr(head: str, merge: str) -> dict[str, Any]:
    return {"state": "MERGED", "mergeCommit": {"oid": merge}, "headRefOid": head, "isDraft": False}


def _apply(fake: FakeGitHub, tmp_path: Path, patch: str) -> int:
    path = tmp_path / "close.py"
    body = f"ALLOWED = {sorted(ALLOWED)!r}\ndef apply(w):\n    w['status'] = 'CLOSED'\n{patch}"
    path.write_text(body, encoding="utf-8")
    return main(["apply", "10", str(path)], gh=GitHub(fake.run))


def test_r001_a_closing_patch_cannot_borrow_another_wps_approval(tmp_path: Path) -> None:
    foreign = [_comment(_header(wp="WP-Y"), 1)]
    fake = _fake(_wp(), reviews=foreign)
    with pytest.raises(CheckFailed, match="none found"):  # control: the unchanged context refuses
        _close(fake)
    with pytest.raises(CheckFailed, match="may not change work_package"):
        _close(fake, {"work_package": "WP-Y"})
    assert _apply(fake, tmp_path, "    w['work_package'] = 'WP-Y'\n") == 1
    assert fake.edits == 0


def test_r001_a_closing_patch_cannot_repoint_the_pr_to_hide_a_later_rejection(tmp_path: Path) -> None:
    fake = _fake(_wp())
    fake.issue_comments[(DOCS, 312)] = [_comment(_header(verdict="CHANGES_REQUESTED", round=2), 9, LATER)]
    fake.prs[(DOCS, 313)] = _merged_pr(SHA_B, MERGED)
    with pytest.raises(CheckFailed, match="not a complete APPROVED"):  # control
        _close(fake)
    repoint = {"docs": {"pr": 313, "sha": SHA_B, "base": "master", "merged_sha": MERGED}}
    with pytest.raises(CheckFailed, match="changed the candidate"):
        _close(fake, repoint)
    assert _apply(fake, tmp_path, "    w['docs']['pr'] = 313\n") == 1
    assert fake.edits == 0


def _revision(state: dict[str, Any]) -> str:
    return render_body({"workflow": state}, "")


def test_r001_an_earlier_ordinary_repoint_does_not_hide_the_earlier_prs_rejection() -> None:
    """Two-step variant: the PR was re-pointed by an earlier ordinary patch; the edit history still names
    PR #312, so its later rejection is read."""
    current = _wp(docs={"pr": 313, "sha": SHA_B, "base": "master", "merged_sha": MERGED})
    fake = _fake(current)
    fake.prs[(DOCS, 313)] = _merged_pr(SHA_B, MERGED)
    fake.issue_comments[(DOCS, 312)] = [_comment(_header(verdict="CHANGES_REQUESTED", round=2), 9, LATER)]
    fake.revisions[(CODE, 10)] = [("r2", _revision(current)), ("r1", _revision(_wp()))]
    with pytest.raises(CheckFailed, match="not a complete APPROVED"):
        _close(fake)
    assert fake.edits == 0
    fake.revisions[(CODE, 10)] = [("r2", _revision(current))]  # control: no history of #312
    _close(fake)
    assert fake.edits == 1


def test_r001_an_earlier_identity_change_cannot_borrow_an_approval() -> None:
    fake = _fake(_wp(), reviews=[_comment(_header(), 1)])
    fake.revisions[(CODE, 10)] = [("r1", _revision(_wp(work_package="WP-Y")))]
    with pytest.raises(CheckFailed, match="identity change cannot borrow"):
        _close(fake)
    assert fake.edits == 0


def test_r001_an_unreadable_history_or_historical_candidate_refuses() -> None:
    fake = _fake(_wp())
    fake.history_fails = True
    with pytest.raises(CheckFailed, match="edit history"):
        _close(fake)
    fake = _fake(_wp())
    fake.revisions[(CODE, 10)] = [("r1", _revision(_wp(docs={"pr": "abc", "sha": SHA_B})))]
    with pytest.raises(CheckFailed, match="cannot read"):
        _close(fake)
    assert fake.edits == 0


def _repointed() -> FakeGitHub:
    """Review 2's fixture: the current candidate is merged PR #313 at the approved SHA; earlier PR #312
    carries a later rejection for this WP."""
    fake = _fake(_wp(docs={"pr": 313, "sha": SHA_B, "base": "master", "merged_sha": MERGED}))
    fake.prs[(DOCS, 313)] = _merged_pr(SHA_B, MERGED)
    fake.issue_comments[(DOCS, 312)] = [_comment(_header(verdict="CHANGES_REQUESTED", round=2), 9, LATER)]
    return fake


@pytest.mark.parametrize(
    ("history", "message"),
    [
        ([("r1", _revision(_wp()))], "not a complete APPROVED"),  # control: readable history names #312
        ([("r1", _revision(_wp()).replace("\n```", "\n"))], "does not parse"),  # fence never closed
        ([("r1", None)], "unreadable"),  # GitHub returned no body for this edit
        ([("r1", "  " + _revision(_wp()))], "does not parse"),  # a state block not at the start
        ([("r1", "notes\nworkflow: {work_package: WP-X}\n")], "does not parse"),  # a bare state key
    ],
    ids=["readable-history", "unterminated-state", "null-body", "indented-state", "bare-workflow-key"],
)
def test_r001_unreadable_history_refuses_instead_of_hiding_a_source(
    history: list[tuple[str, str | None]], message: str
) -> None:
    fake = _repointed()
    fake.revisions[(CODE, 10)] = history
    with pytest.raises(CheckFailed, match=message):
        _close(fake)
    assert fake.edits == 0


def test_r001_null_history_bodies_survive_the_real_adapter() -> None:
    """The real `GitHub.issue_revisions` keeps a node whose `diff` is null as `None` (it used to drop it),
    and the closure refuses on it."""
    fake = _repointed()
    fake.revisions[(CODE, 10)] = [("unreadable-old", None)]
    assert GitHub(fake.run).issue_revisions(CODE, 10) == [("unreadable-old", None)]
    with pytest.raises(CheckFailed, match="unreadable"):
        _close(fake)
    assert fake.edits == 0


def test_r001_without_any_history_of_312_the_repointed_wp_closes() -> None:
    """The paired green control for the two tests above."""
    fake = _repointed()
    _close(fake)
    assert fake.edits == 1


def test_r001_a_history_with_the_same_identity_and_prose_only_revisions_still_closes() -> None:
    fake = _fake(_wp())
    fake.revisions[(CODE, 10)] = [("r2", _revision(_wp())), ("r1", "prose before the state block\n")]
    _close(fake)
    assert fake.edits == 1


@pytest.mark.parametrize(
    "patch",
    [
        {"code": {"pr": 9, "sha": SHA_A, "base": "main", "merged_sha": OTHER}},
        {"docs": {"pr": 312, "sha": SHA_B, "base": "main", "merged_sha": MERGED}},
        {"docs": {"pr": 312, "sha": SHA_B, "base": "master", "merged_sha": OTHER}},
    ],
    ids=["adds-a-side", "changes-base", "changes-recorded-merged-sha"],
)
def test_r001_the_closing_patch_keeps_every_candidate_field_but_merged_sha(patch: dict[str, Any]) -> None:
    fake = _fake(_wp())
    with pytest.raises(CheckFailed, match="changed the candidate"):
        _close(fake, patch)
    assert fake.edits == 0


# --- KIT-032-R002: findings in every admitted location -------------------------------------------------


@pytest.mark.parametrize(
    ("state", "patch"),
    [
        ({"convergence": {"open_findings": ["WP-X-R001"]}}, None),
        ({"convergence": {"open_findings": ["WP-X-R001"]}}, {"convergence": {"open_findings": []}}),
        ({}, {"convergence": {"open_findings": ["WP-X-R001"]}}),
        ({"provisionally_closed": ["WP-X-R001"]}, None),
        ({"convergence": {"provisionally_closed": ["WP-X-R001"]}}, None),
    ],
    ids=["conv-retained", "conv-cleared", "conv-added", "provisional", "conv-provisional"],
)
def test_r002_findings_in_any_location_refuse(state: dict[str, Any], patch: dict[str, Any] | None) -> None:
    fake = _fake(_wp(**state))
    with pytest.raises(CheckFailed, match="open findings"):
        _close(fake, patch)
    assert fake.edits == 0


def test_r002_an_empty_convergence_record_still_closes() -> None:
    fake = _fake(_wp(convergence={"open_findings": [], "provisionally_closed": []}))
    _close(fake)
    assert fake.edits == 1
