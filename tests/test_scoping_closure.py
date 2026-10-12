"""Guarded `SCOPING -> CLOSED` for a completed scoping-only work package (`coordination-state.md`
§10.3; Owner decision, `minion-agent#157` issuecomment-6051471806)."""

from __future__ import annotations

from typing import Any

import pytest

from minion_process.github import GitHub
from minion_process.model import render_body, split_body
from minion_process.ops import CheckFailed, commit_state
from minion_process.transitions import check_transition

from .test_minion_process import CODE, DOCS, SHA_B, FakeGitHub, workflow

MERGED = "d" * 40


def _scoping_wp(**changes: Any) -> dict[str, Any]:
    state = workflow(
        status="SCOPING",
        requirements=[],
        open_findings=[],
        code=None,
        docs={"pr": 253, "sha": SHA_B, "base": "master", "merged_sha": MERGED},
        scoping_review={
            "outcome": "APPROVED",
            "verdict": "LAYER 14 SCOPE APPROVED",
            "source": "minion-agent-docs#253 issuecomment-1",
        },
        next_owner="Claude",
        next_action="close the scoping WP",
    )
    state.update(changes)
    return state


def _fake(state: dict[str, Any], merged: bool = True, on_default: bool = True) -> FakeGitHub:
    fake = FakeGitHub()
    fake.issues[(CODE, 10)] = {"body": render_body({"workflow": state}, ""), "state": "OPEN", "title": "x"}
    fake.prs[(DOCS, 253)] = {
        "state": "MERGED" if merged else "OPEN",
        "mergeCommit": {"oid": MERGED} if merged else None,
        "headRefOid": SHA_B,
        "isDraft": False,
    }
    if on_default:
        fake.on_default.add(MERGED)
    return fake


def _close(fake: FakeGitHub, extra: dict[str, Any] | None = None) -> None:
    def mutate(w: dict[str, Any]) -> None:
        w["status"] = "CLOSED"
        w["next_owner"] = None
        w["next_action"] = None
        w.update(extra or {})

    allowed = {
        "status",
        "next_owner",
        "next_action",
        "requirements",
        "open_findings",
        "scoping_review",
        "docs",
    }
    commit_state(GitHub(fake.run), CODE, 10, mutate, allowed)


def test_scoping_to_closed_is_in_the_transition_table() -> None:
    assert check_transition("SCOPING", "CLOSED") is None


def test_a_completed_scoping_only_wp_closes_and_the_remote_state_round_trips() -> None:
    fake = _fake(_scoping_wp())
    _close(fake)
    assert fake.edits == 1
    assert split_body(fake.issues[(CODE, 10)]["body"]).workflow["status"] == "CLOSED"


@pytest.mark.parametrize(
    ("state_changes", "patch", "fake_kwargs", "message"),
    [
        ({"requirements": ["HAR-001"]}, None, {}, "scoping-only"),
        ({}, {"requirements": ["HAR-001"]}, {}, "scoping-only"),
        ({"requirements": None}, None, {}, "scoping-only"),
        ({"open_findings": ["L14-SCOPE-R001"]}, None, {}, "open findings"),
        ({"scoping_review": None}, None, {}, "scoping_review"),
        ({"scoping_review": {"verdict": "  ", "source": "x"}}, None, {}, "scoping_review"),
        ({"scoping_review": {"verdict": "APPROVED"}}, None, {}, "scoping_review"),
        ({"docs": None}, None, {}, "merged scoping artifact"),
        ({"docs": {"pr": 253, "sha": SHA_B, "base": "master"}}, None, {}, "merged_sha"),
        ({}, None, {"merged": False}, "not merged"),
        (
            {"docs": {"pr": 253, "sha": SHA_B, "base": "master", "merged_sha": "e" * 40}},
            None,
            {},
            "not merged",
        ),
        ({}, None, {"on_default": False}, "default branch"),
    ],
    ids=[
        "product-requirement",
        "closure-adds-requirement",
        "requirements-null",
        "open-finding",
        "no-review-record",
        "blank-verdict",
        "review-without-source",
        "no-candidate",
        "candidate-unmerged-record",
        "pr-not-merged",
        "merge-commit-mismatch",
        "merge-off-default-branch",
    ],
)
def test_scoping_closure_is_refused_with_zero_writes_unless_mechanically_complete(
    state_changes: dict[str, Any], patch: dict[str, Any] | None, fake_kwargs: dict[str, bool], message: str
) -> None:
    fake = _fake(_scoping_wp(**state_changes), **fake_kwargs)
    with pytest.raises(CheckFailed, match=message):
        _close(fake, patch)
    assert fake.edits == 0


def test_blocked_for_owner_still_cannot_close_directly() -> None:
    """The Owner decision keeps the state machine clean: no BLOCKED_FOR_OWNER -> CLOSED shortcut."""
    assert check_transition("BLOCKED_FOR_OWNER", "CLOSED") is not None
    assert check_transition("BLOCKED_FOR_OWNER", "SCOPING") is None


def test_other_states_are_not_widened() -> None:
    for state in ("CONTRACT_DRAFT", "CONTRACT_REVIEW", "PYTHON_IMPLEMENTATION", "WAITING_FOR_TRIGGER"):
        assert check_transition(state, "CLOSED") is not None


def _review(outcome: object, verdict: str = "LAYER 14 SCOPE APPROVED") -> dict[str, Any]:
    review: dict[str, Any] = {"verdict": verdict, "source": "minion-agent-docs#253 issuecomment-1"}
    if outcome is not _MISSING:
        review["outcome"] = outcome
    return review


_MISSING = object()


@pytest.mark.parametrize(
    "review",
    [
        _review("CHANGES REQUESTED", "LAYER 14 SCOPE CHANGES REQUESTED"),
        _review("CHANGES_REQUESTED"),
        _review("BLOCKED"),
        _review("PENDING"),
        _review("approved"),
        _review("NOT APPROVED"),
        _review("APPROVED WITH CHANGES"),
        _review(None),
        _review(True),
        _review(_MISSING),
    ],
    ids=[
        "rejected",
        "rejected-token",
        "blocked",
        "pending",
        "lowercase",
        "not-approved",
        "approved-prefix",
        "null",
        "boolean",
        "missing",
    ],
)
def test_only_an_explicit_approved_outcome_closes(review: dict[str, Any]) -> None:
    """PROC-L256-R001: a recorded rejection, block, pending or unrecognized outcome is refused with
    zero writes; only the exact `APPROVED` token passes, and no verdict substring is ever read."""
    fake = _fake(_scoping_wp(scoping_review=review))
    with pytest.raises(CheckFailed, match="outcome"):
        _close(fake)
    assert fake.edits == 0


def test_an_approved_outcome_with_a_rejecting_verdict_text_is_not_reinterpreted() -> None:
    """The tool reads the outcome token, never the verdict prose: an APPROVED outcome closes even
    though the prose would not, which is why the agent must still verify the source (§10.3)."""
    fake = _fake(_scoping_wp(scoping_review=_review("APPROVED", "free text, not parsed")))
    _close(fake)
    assert fake.edits == 1
