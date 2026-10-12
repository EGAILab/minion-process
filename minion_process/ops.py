"""Deterministic workflow operations. Each one either succeeds with its checks recorded, or raises
`CheckFailed` before any dependent action happens."""

from __future__ import annotations

import copy
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .github import REPOS, GitHub, GitHubError, same_text
from .model import NON_ACTIONABLE, BodyFormatError, candidates, render_body, split_body
from .transitions import check_transition
from .validate import errors, validate_workflow

REVIEW_OR_HANDOFF_STATES = frozenset(
    {
        "CONTRACT_REVIEW",
        "IMPLEMENTATION_REVIEW",
        "FINAL_CONTRACT_REVIEW",
        "CLOSURE_REVIEW",
        "CONTRACT_CONVERGENCE",
    }
)


class CheckFailed(RuntimeError):
    pass


@dataclass
class Report:
    ok: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    def check(self, condition: bool, label: str) -> None:
        (self.ok if condition else self.failed).append(label)

    def raise_if_failed(self, verdict: str) -> None:
        if self.failed:
            raise CheckFailed(f"{verdict}: " + "; ".join(self.failed))


def _process_closure(old: dict[str, Any], new: dict[str, Any]) -> str | None:
    """`FINAL_CONTRACT_REVIEW -> CLOSED` is legal only for a process-only work package
    (`coordination-state.md` §10.2): no product requirement, no open finding, and every candidate
    merged (its accepted default-branch milestone recorded, §4.3). The tool checks these mechanical
    facts; the agent still verifies the final review approved that exact candidate."""
    if not (old["status"] == "FINAL_CONTRACT_REVIEW" and new["status"] == "CLOSED"):
        return None
    if old.get("requirements") != [] or new.get("requirements") != []:
        # explicit `[]` in BOTH states: a missing/null scope is not process-only, and the closure
        # patch itself may not reclassify a product WP (PROC-L13-F001 refinement)
        return (
            "FINAL_CONTRACT_REVIEW -> CLOSED is for a process-only WP: requirements must be an explicit "
            "[] before and after the transition (§10.2)"
        )
    if new.get("open_findings"):
        return "cannot close with open findings (§4.3)"
    candidates = new.get("current_candidate") or {}
    if not candidates or not all(isinstance(c, dict) and c.get("merged_sha") for c in candidates.values()):
        return "cannot close before every candidate records its merged_sha (§4.3, §10.2)"
    return None


SCOPING_REVIEW_APPROVED = "APPROVED"
"""The one machine-checkable approval outcome for `scoping_review.outcome` (§10.3)."""


def _scoping_closure(gh: GitHub, old: dict[str, Any], new: dict[str, Any]) -> str | None:
    """`SCOPING -> CLOSED` is legal only for a completed scoping-only work package
    (`coordination-state.md` §10.3). The tool verifies every mechanical fact it can:
    - an explicit `requirements: []` before and after, so the closure claims no product
      certification and may not reclassify a product WP;
    - no open finding;
    - a recorded `scoping_review` whose `outcome` is exactly `APPROVED`, with a non-empty
      `verdict` and `source` (`PROC-L256-R001`: a recorded rejection, block or pending review is
      refused, and no substring of the verdict is ever read as approval);
    - at least one candidate, and every candidate a PR that GitHub reports merged at its recorded
      `merged_sha`, with that merge reachable from the default branch.

    The `APPROVED` marker is necessary, not sufficient. Review semantics stay recorded evidence: the
    agent still verifies that `source` independently approved that exact candidate."""
    if not (old["status"] == "SCOPING" and new["status"] == "CLOSED"):
        return None
    if old.get("requirements") != [] or new.get("requirements") != []:
        return (
            "SCOPING -> CLOSED is for a scoping-only WP: requirements must be an explicit [] before "
            "and after the transition (§10.3)"
        )
    if new.get("open_findings"):
        return "cannot close with open findings (§4.3)"
    review = new.get("scoping_review")
    if not (
        isinstance(review, dict)
        and all(isinstance(review.get(k), str) and review[k].strip() for k in ("verdict", "source"))
    ):
        return (
            "SCOPING -> CLOSED requires a recorded scoping_review with a non-empty verdict and source (§10.3)"
        )
    if review.get("outcome") != SCOPING_REVIEW_APPROVED:
        return (
            f"SCOPING -> CLOSED requires scoping_review.outcome == {SCOPING_REVIEW_APPROVED!r}, "
            f"got {review.get('outcome')!r} (§10.3)"
        )
    present = {side: c for side, c in candidates(new).items() if c is not None}
    if not present:
        return "SCOPING -> CLOSED requires the merged scoping artifact recorded as a candidate (§10.3)"
    for side, candidate in present.items():
        if not (isinstance(candidate, dict) and candidate.get("pr") and candidate.get("merged_sha")):
            return f"cannot close before the {side} candidate records its pr and merged_sha (§4.3, §10.3)"
        repo, merged = REPOS[side], candidate["merged_sha"]
        pr = gh.pr(repo, candidate["pr"])
        if pr.get("state") != "MERGED" or (pr.get("mergeCommit") or {}).get("oid") != merged:
            return f"{side} PR #{candidate['pr']} is not merged at {merged[:12]} (§10.3)"
        if not gh.contains(repo, gh.default_branch(repo), merged):
            return f"{side} merge {merged[:12]} is not on the default branch (§10.3)"
    return None


def commit_state(
    gh: GitHub,
    repo: str,
    number: int,
    mutate: Callable[[dict[str, Any]], str | None],
    allowed: set[str],
    dry_run: bool = False,
) -> tuple[list[str], str]:
    """The coordination-state commit rule (`agent-workflow.md` §11.1.1), steps 1-7.

    `mutate(workflow)` edits a deep copy of the current workflow object in place and may return
    replacement prose. Returns (changed keys, the new body).

    Malformed coordination data is refused with `CheckFailed` / `BodyFormatError` before any write
    (CE-PROC-L13-01 rules 7 and 9): the CURRENT state is validated before it is used -- an invalid
    current state never reaches the transition lookup; restore it with `restore_revision` first.
    Then the patch's keys, the transition, governance-on-resume and the intended state are checked.
    After writing, a remote state that is not valid, semantically equal and byte-equal is a failed
    state commit. Exceptions raised by the caller's own `mutate` and remote `GitHubError`s propagate
    unchanged (rule 9)."""
    current = split_body(gh.issue(repo, number)["body"])
    old = current.workflow
    current_errors = errors(validate_workflow(old))
    if current_errors:
        raise CheckFailed(
            "current state invalid -- restore a valid earlier revision first (`apply --repair --revision`): "
            + "; ".join(map(str, current_errors))
        )
    new_workflow = copy.deepcopy(old)
    prose = mutate(new_workflow)
    if not isinstance(new_workflow, dict):  # pragma: no cover - mutate edits in place; defensive
        raise CheckFailed("intended state invalid: workflow is not a mapping")
    blocking = errors(validate_workflow(new_workflow))
    if blocking:
        raise CheckFailed("intended state invalid: " + "; ".join(map(str, blocking)))
    changed = sorted(k for k in set(old) | set(new_workflow) if old.get(k) != new_workflow.get(k))
    outside = [k for k in changed if k not in allowed]
    if outside:
        raise CheckFailed(f"patch changed keys outside ALLOWED: {outside}")
    reason = (
        check_transition(old["status"], new_workflow["status"])
        or _process_closure(old, new_workflow)
        or _scoping_closure(gh, old, new_workflow)
    )
    if reason:
        raise CheckFailed(reason)
    if old["status"] == "BLOCKED_FOR_OWNER" and new_workflow["status"] != "BLOCKED_FOR_OWNER":
        source = new_workflow.get("governance_source")
        if not source or (isinstance(source, dict) and not any(source.values())):
            raise CheckFailed(
                "resume from BLOCKED_FOR_OWNER requires a recorded governance_source (§11.10); the tool "
                "checks its presence only -- the agent still validates its authority, decision and scope"
            )
    if prose is not None and not isinstance(prose, str):
        raise CheckFailed(f"patch returned non-string prose: {type(prose).__name__}")
    state = dict(current.state)
    state["workflow"] = new_workflow
    body = render_body(state, prose if prose is not None else current.prose)
    try:  # pre-write round trip: a state YAML cannot carry faithfully is refused, never written
        survives = split_body(body).state == state
    except BodyFormatError:  # pragma: no cover - every state value is indented under `workflow:`
        survives = False
    if not survives:
        raise CheckFailed("intended state does not survive YAML serialization unchanged; nothing was written")
    if dry_run:
        return changed, body
    gh.edit_issue_body(repo, number, body)
    _verify_remote(gh, repo, number, state, body)
    return changed, body


def _verify_remote(gh: GitHub, repo: str, number: int, state: dict[str, Any], body: str) -> None:
    remote = gh.issue(repo, number)["body"]
    parsed = split_body(remote)
    remote_errors = errors(validate_workflow(parsed.workflow, len(remote)))
    if remote_errors:
        raise CheckFailed("FAILED STATE COMMIT: remote state invalid: " + "; ".join(map(str, remote_errors)))
    if parsed.state != state:
        raise CheckFailed("FAILED STATE COMMIT: re-fetched state is not semantically equal (§11.1.1)")
    if not same_text(remote, body):
        raise CheckFailed("FAILED STATE COMMIT: re-fetched body differs from the written body")


def restore_revision(gh: GitHub, repo: str, number: int, revision_id: str, dry_run: bool = False) -> str:
    """Repair mode (CE-PROC-L13-01 revision 3): restore the issue body, byte for byte, to an earlier
    revision of THAT issue's body taken from GitHub's own edit history -- never a caller-supplied
    body, never a transition. Refused, with zero writes, unless the current state is invalid and the
    revision exists and validates. Any change after restoration is an ordinary checked `commit_state`.
    Returns the restored body."""
    current_body = gh.issue(repo, number)["body"]
    try:
        current_valid = not errors(validate_workflow(split_body(current_body).workflow))
    except BodyFormatError:
        current_valid = False
    if current_valid:
        raise CheckFailed("current state is valid: use a normal checked apply, not repair")
    try:
        revisions = gh.issue_revisions(repo, number)
    except GitHubError as error:
        raise CheckFailed(f"cannot fetch the issue's edit history: {error}") from error
    matches = [body for rid, body in revisions if rid == revision_id]
    if not matches:
        raise CheckFailed(f"revision {revision_id!r} is not in issue #{number}'s edit history")
    baseline = matches[0]
    try:
        baseline_state = split_body(baseline)
        baseline_errors = errors(validate_workflow(baseline_state.workflow))
    except BodyFormatError as error:
        raise CheckFailed(f"revision {revision_id} does not parse: {error}") from error
    if baseline_errors:
        raise CheckFailed(
            f"revision {revision_id} is not a valid state: " + "; ".join(map(str, baseline_errors))
        )
    if dry_run:
        return baseline
    gh.edit_issue_body(repo, number, baseline)
    _verify_remote(gh, repo, number, baseline_state.state, baseline)
    return baseline


def candidate_report(gh: GitHub, workflow: Any, require_ready: bool) -> Report:
    """Exact-SHA candidate checks for `code`/`docs` (§5, §11.3). Validates first: an invalid state
    is a failed check and its candidates are not consumed (CE-PROC-L13-01 rules 5 and 7)."""
    report = Report()
    invalid = errors(validate_workflow(workflow))
    if invalid:
        report.check(False, "state block valid: " + "; ".join(map(str, invalid)))
        return report
    for side, candidate in candidates(workflow).items():
        if candidate is None:
            continue  # this side has no candidate at all
        if not candidate.get("sha"):
            report.check(False, f"{side} candidate records an exact SHA")
            continue
        repo, sha = REPOS[side], candidate["sha"]
        report.check(gh.commit_exists(repo, sha), f"{side} {sha[:12]} remote-reachable")
        pr_number = candidate.get("pr")
        if pr_number is None:
            continue
        try:
            pr = gh.pr(repo, pr_number)
        except GitHubError as error:  # a well-formed reference to a PR GitHub cannot return
            report.check(False, f"{side} PR #{pr_number} exists: {error}")
            continue
        merged = candidate.get("merged_sha")
        if merged is not None:
            # an accepted baseline: the claim itself is verified, never trusted to switch checks off
            commit = pr.get("mergeCommit") or {}
            report.check(pr["state"] == "MERGED", f"{side} PR #{pr_number} merged")
            report.check(commit.get("oid") == merged, f"{side} PR #{pr_number} merge commit == {merged[:12]}")
            report.check(pr["headRefOid"] == sha, f"{side} PR #{pr_number} merged head == {sha[:12]}")
            report.check(
                gh.contains(repo, gh.default_branch(repo), merged), f"{side} merge on the default branch"
            )
            continue
        report.check(pr["state"] == "OPEN", f"{side} PR #{pr_number} open")
        report.check(pr["headRefOid"] == sha, f"{side} PR #{pr_number} head == {sha[:12]}")
        if require_ready:
            report.check(not pr["isDraft"], f"{side} PR #{pr_number} ready for review")
    return report


def handoff_report(gh: GitHub, repo: str, number: int) -> Report:
    """Handoff validation (`agent-workflow.md` §11.11). Never raises on malformed coordination data:
    it reports HANDOFF_BLOCKED instead (CE-PROC-L13-01 rule 4)."""
    issue = gh.issue(repo, number)
    report = Report()
    report.check(issue["state"] == "OPEN", "coordination issue OPEN")
    try:
        workflow = split_body(issue["body"]).workflow
    except BodyFormatError as error:
        report.check(False, f"state block parses: {error}")
        return report
    invalid = errors(validate_workflow(workflow))
    report.check(
        not invalid, "state block valid" + ("" if not invalid else ": " + "; ".join(map(str, invalid)))
    )
    if invalid:
        return report
    status = workflow["status"]
    report.check(status not in NON_ACTIONABLE | {"BLOCKED_FOR_OWNER"}, f"status {status} permits a handoff")
    report.check(bool(workflow.get("next_owner")), "NEXT_OWNER present")
    report.check(bool(workflow.get("next_action")), "NEXT_ACTION present")
    quarantine = workflow.get("quarantine") or {}
    report.check(
        not quarantine.get("derived_from_quarantined_artifact"),
        "candidate not derived from a quarantined artifact",
    )
    found = candidate_report(gh, workflow, require_ready=status in REVIEW_OR_HANDOFF_STATES)
    report.ok += found.ok
    report.failed += found.failed
    return report


def guarded_merge(
    gh: GitHub, repo: str, number: int, sha: str, wait: Callable[[float], None] = time.sleep
) -> str:
    """Exact-head squash merge plus post-merge containment (§11.3, §11.6, §12). Returns the merge SHA."""
    pr = gh.pr(repo, number)
    for _ in range(5):
        if pr["mergeable"] != "UNKNOWN":
            break
        wait(3)
        pr = gh.pr(repo, number)
    report = Report()
    report.check(pr["state"] == "OPEN", f"PR #{number} open")
    report.check(not pr["isDraft"], f"PR #{number} not draft")
    report.check(pr["headRefOid"] == sha, f"PR #{number} head == approved {sha[:12]} (else STOP)")
    report.check(pr["mergeable"] == "MERGEABLE", f"PR #{number} mergeable")
    report.raise_if_failed("MERGE BLOCKED")
    gh.merge_squash(repo, number, sha)
    post = gh.pr(repo, number)
    if post["state"] != "MERGED" or not post.get("mergeCommit"):
        raise CheckFailed(f"PR #{number} did not merge")
    merge_sha: str = post["mergeCommit"]["oid"]
    branch = gh.default_branch(repo)
    if not gh.contains(repo, branch, merge_sha):
        raise CheckFailed(f"merge {merge_sha[:12]} not reachable from {branch}")
    return merge_sha


def verified_comment(gh: GitHub, repo: str, number: int, body: str, kind: str = "issue") -> str:
    """Post, re-fetch and byte-compare a comment (a history record must survive transport intact)."""
    url = gh.comment(repo, number, body, kind)
    comment_id = url.rsplit("issuecomment-", 1)[-1]
    if not same_text(gh.comment_body(repo, comment_id), body):
        raise CheckFailed(f"comment {url} differs from the posted text")
    return url
