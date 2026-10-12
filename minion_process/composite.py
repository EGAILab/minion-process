"""Composite verbs (record §6.6, kit 0.3.0): one checked transition each, built only from the existing
primitives. `handoff` records the next owner/action (and new candidate heads) and refuses when the
hand-off would be blocked; `close` records every candidate's verified merge and closes the work
package. Both run the full `commit_state` rule, so every guard (transition legality, classification,
process-only and scoping-only closure, round-trip) applies, and a refusal happens before any write."""

from __future__ import annotations

import re
from typing import Any

from .github import REPOS, GitHub, GitHubError
from .model import candidates
from .ops import REVIEW_OR_HANDOFF_STATES, CheckFailed, Report, candidate_report, commit_state, handoff_report

SHA = re.compile(r"^[0-9a-f]{40}$")


def _set_candidate(w: dict[str, Any], side: str, key: str, value: str) -> None:
    """Writes into the v2 `current_candidate` or the v1 top-level side, whichever the state uses."""
    container = w.get("current_candidate", w)  # the v2 mapping, or the v1 top level
    if not isinstance(container, dict):  # pragma: no cover  (the validator refuses this before mutate)
        raise CheckFailed("current_candidate is not a mapping")
    entry = container.get(side)
    if entry is None:  # a null side means "no candidate yet": the hand-off creates it
        entry = container[side] = {}
    if not isinstance(entry, dict):  # pragma: no cover  (the validator refuses this before mutate)
        raise CheckFailed(f"{side} candidate is not a mapping")
    entry[key] = value


def handoff(
    gh: GitHub,
    repo: str,
    number: int,
    to: str,
    action: str,
    status: str | None = None,
    shas: dict[str, str] | None = None,
    dry_run: bool = False,
) -> tuple[list[str], Report]:
    """`minion-process handoff`: set `next_owner`/`next_action` (optionally `status` and new candidate
    heads) in one checked commit, refusing with zero writes when the resulting hand-off would be
    `HANDOFF_BLOCKED` (§11.11). Returns the changed keys and the post-commit hand-off report."""
    if not action.strip():
        raise CheckFailed("handoff needs a non-empty next_action")
    for side, sha in (shas or {}).items():
        if side not in REPOS:
            raise CheckFailed(f"unknown candidate side {side!r} (allowed: {', '.join(REPOS)})")
        if not SHA.match(sha):
            raise CheckFailed(f"{side} SHA is not a full 40-hex SHA: {sha!r}")

    def mutate(w: dict[str, Any]) -> None:
        if status is not None:
            w["status"] = status
        w["next_owner"] = to
        w["next_action"] = action
        w["updated_reason"] = f"handoff to {to}"
        for side, sha in (shas or {}).items():
            _set_candidate(w, side, "sha", sha)
        # pre-write: the intended candidate must pass the exact-SHA checks for the target state
        ready = (status or w.get("status")) in REVIEW_OR_HANDOFF_STATES
        report = candidate_report(gh, w, ready)
        report.raise_if_failed("HANDOFF_BLOCKED (intended candidate)")

    allowed = {"status", "next_owner", "next_action", "updated_reason", "current_candidate", *REPOS}
    changed, _ = commit_state(gh, repo, number, mutate, allowed, dry_run)
    if dry_run:
        return changed, Report()
    report = handoff_report(gh, repo, number)
    report.raise_if_failed("HANDOFF_BLOCKED (after commit; the state was written and must be repaired)")
    return changed, report


def close(
    gh: GitHub, repo: str, number: int, comment: str, dry_run: bool = False
) -> tuple[list[str], dict[str, str]]:
    """`minion-process close`: verify that every recorded candidate PR is MERGED at its recorded head,
    record each merge commit as `merged_sha` (verified reachable from the default branch), move the work
    package to CLOSED in one checked commit, then close the issue with `comment`. Every closure guard of
    `commit_state` applies (process-only / scoping-only routes, classification by kind). Returns the
    changed keys and the merged SHAs by side."""
    if not comment.strip():
        raise CheckFailed("close needs a non-empty closure comment (the durable closure record)")
    merged: dict[str, str] = {}

    def mutate(w: dict[str, Any]) -> None:
        present = {side: c for side, c in candidates(w).items() if c is not None}
        if not present:
            raise CheckFailed("close requires at least one recorded candidate (§4.3)")
        for side, cand in present.items():
            if not isinstance(cand, dict) or not cand.get("pr") or not cand.get("sha"):
                raise CheckFailed(f"{side} candidate needs pr and sha before closure (§4.3)")
            target = REPOS[side]
            try:
                pr = gh.pr(target, cand["pr"])
            except GitHubError as error:
                raise CheckFailed(f"{side} PR #{cand['pr']} cannot be read: {error}") from error
            if pr.get("state") != "MERGED":
                raise CheckFailed(f"{side} PR #{cand['pr']} is not MERGED (state {pr.get('state')!r})")
            if pr.get("headRefOid") != cand["sha"]:
                raise CheckFailed(
                    f"{side} PR #{cand['pr']} merged head {str(pr.get('headRefOid'))[:12]} != recorded "
                    f"candidate {cand['sha'][:12]} (§11.3)"
                )
            oid = (pr.get("mergeCommit") or {}).get("oid")
            if not (isinstance(oid, str) and SHA.match(oid)):
                raise CheckFailed(f"{side} PR #{cand['pr']} has no merge commit")
            if cand.get("merged_sha") not in (None, oid):
                raise CheckFailed(
                    f"{side} recorded merged_sha {cand['merged_sha'][:12]} != GitHub's {oid[:12]}"
                )
            if not gh.contains(target, gh.default_branch(target), oid):
                raise CheckFailed(f"{side} merge {oid[:12]} is not on the default branch (§12)")
            _set_candidate(w, side, "merged_sha", oid)
            merged[side] = oid
        w["status"] = "CLOSED"
        w["next_owner"] = None
        w["next_action"] = None
        w["updated_reason"] = "CLOSED by minion-process close: " + ", ".join(
            f"{side} merged {oid[:8]}" for side, oid in sorted(merged.items())
        )

    allowed = {"status", "next_owner", "next_action", "updated_reason", "current_candidate", *REPOS}
    changed, _ = commit_state(gh, repo, number, mutate, allowed, dry_run)
    if not dry_run:
        gh.close_issue(repo, number, comment)
    return changed, merged
