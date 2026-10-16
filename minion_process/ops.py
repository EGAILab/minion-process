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
from .review import Copy, Selection, UnreadComment, parse_review_records, select_reviews
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


INTAKE_EXEMPT = frozenset(
    {"SCOPING", "BLOCKED_FOR_OWNER", "WAITING_FOR_TRIGGER", "INCIDENT", "INVALID_UNAUTHORIZED"}
)
"""Leaving SCOPING for any state outside this set is intake: the WP must be classified first."""


def classification_guard(old: dict[str, Any], new: dict[str, Any]) -> str | None:
    """Kind and consequence class across a transition (`coordination-state.md` §14, kit 0.2.0):

    - **Intake.** A WP leaving `SCOPING` for an active working state records `kind` and
      `consequence.class` (with its predicate rule) in the intended state.
    - **Kind is fixed after intake.** A different kind is a new WP, not a patch (scope corrections stay
      ordinary checked changes to `requirements`, within the kind's rule).
    - **Downgrade is Owner-only** (`minion-agent#75` Amendment 2, item 11): governing -> mechanical needs
      `consequence.downgrade` with the Owner decision and the consenting reviewer, and a recorded
      `governance_source`. The tool checks presence; the agent validates the source (§11.10).
    - **Closure routes by kind.** `FINAL_CONTRACT_REVIEW -> CLOSED` (§10.2) is for `process`/`status`
      kinds, and so is `IMPLEMENTATION_REVIEW -> CLOSED` (§10.2a, `_first_review_closure`);
      `SCOPING -> CLOSED` (§10.3) is for `scoping`. A semantic or delta WP closes through
      `CLOSURE_REVIEW` only.
    - **Classification is sticky** (`PROC-KIT-P2-R001`): once recorded, `kind` and `consequence` are never
      removed or nulled, so a class cannot be laundered through an unclassified state; any effective
      lowering from governing is the Owner-only downgrade.
    - **Pending intake survives a pause** (`PROC-KIT-P2-R003`): a new v2 WP that leaves `SCOPING` for
      `BLOCKED_FOR_OWNER` or `WAITING_FOR_TRIGGER` unclassified records `classification_pending: true`,
      and may not enter a working state until it is classified. WPs opened before kit 0.2.0 carry no
      flag and are not re-classified mid-flight.
    - **No schema rollback** (`PROC-KIT-P2-R003`, refined): `schema_version` never decreases in an ordinary
      apply, and the intake obligation is computed from the higher of the current and intended versions,
      so a new v2 record cannot be retagged as legacy v1 to escape intake."""
    old_status, new_status = old["status"], new["status"]
    kind_old, kind_new = old.get("kind"), new.get("kind")
    class_old = (
        (old.get("consequence") or {}).get("class") if isinstance(old.get("consequence"), dict) else None
    )
    class_new = (
        (new.get("consequence") or {}).get("class") if isinstance(new.get("consequence"), dict) else None
    )
    version_old, version_new = old.get("schema_version", 1), new.get("schema_version", 1)
    if version_new < version_old:
        return (
            f"schema_version cannot be rolled back ({version_old} -> {version_new}); a record is legacy only "
            "if it was never a later version (§14, PROC-KIT-P2-R003)"
        )
    # Intake applies from schema v2 on. The obligation is computed from the higher of the current and
    # intended versions, so a newly opened v2 WP cannot be retagged into the legacy exemption.
    lean = max(version_old, version_new) >= 2
    unclassified_new = kind_new is None or class_new is None
    if kind_old is not None and kind_new is None:
        return "classification is sticky: `kind` cannot be removed or nulled once recorded (§14)"
    if class_old is not None and class_new is None:
        return "classification is sticky: `consequence` cannot be removed or nulled once recorded (§14)"
    if lean and old_status == "SCOPING" and new_status not in INTAKE_EXEMPT and unclassified_new:
        return (
            "intake requires classification: record `kind` and `consequence: {class, rule}` before leaving "
            "SCOPING (§14; consequence-classes.md)"
        )
    if (
        lean
        and old_status == "SCOPING"
        and new_status in ("BLOCKED_FOR_OWNER", "WAITING_FOR_TRIGGER")
        and unclassified_new
        and new.get("classification_pending") is not True
    ):
        return (
            "an unclassified WP leaving SCOPING for a pause state records `classification_pending: true` "
            "so intake still applies when it resumes (§14)"
        )
    if old.get("classification_pending") is True and unclassified_new:
        if new_status not in INTAKE_EXEMPT:
            return (
                "pending intake: this WP was never classified; record `kind` and `consequence` before it "
                "enters a working state (§14)"
            )
        if new.get("classification_pending") is not True:
            return "classification_pending cannot be dropped while the WP is unclassified (§14)"
    if kind_old is not None and kind_new != kind_old and old_status != "SCOPING":
        return f"kind is fixed after intake ({kind_old}); a different kind is a new work package (§14)"
    if class_old == "governing" and class_new != "governing":
        downgrade = (new.get("consequence") or {}).get("downgrade")
        source = new.get("governance_source")
        if not (
            isinstance(downgrade, dict) and downgrade.get("owner_decision") and downgrade.get("reviewer")
        ):
            return (
                "consequence-class downgrade is Owner-only (#75 Amendment 2 item 11): record "
                "consequence.downgrade {owner_decision, reviewer}"
            )
        if not source or (isinstance(source, dict) and not any(source.values())):
            return "consequence-class downgrade requires a recorded governance_source (§11.10)"
    if (
        old_status == "FINAL_CONTRACT_REVIEW"
        and new_status == "CLOSED"
        and kind_new not in (None, "process", "status")
    ):
        return (
            f"FINAL_CONTRACT_REVIEW -> CLOSED is the process-only route; a {kind_new} WP closes through "
            "CLOSURE_REVIEW (§10.2, §14)"
        )
    if old_status == "SCOPING" and new_status == "CLOSED" and kind_new not in (None, "scoping"):
        return (
            f"SCOPING -> CLOSED is the scoping-only route; a {kind_new} WP does not close from SCOPING "
            "(§10.3, §14)"
        )
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


def _candidate_prs(workflow: dict[str, Any]) -> set[tuple[str, int]]:
    """The (repository, PR number) of every candidate the workflow records."""
    return {
        (REPOS[side], int(entry["pr"]))
        for side, entry in candidates(workflow).items()
        if isinstance(entry, dict) and entry.get("pr")
    }


def published_reviews(
    gh: GitHub,
    repo: str,
    number: int,
    workflow: dict[str, Any],
    prs: set[tuple[str, int]] | None = None,
) -> Selection:
    """The review events published on the coordination issue and on the candidate PRs (`CE-PROC-P3A-01`):
    every comment's claims become copies carrying the remote's publication metadata; `select_reviews`
    groups them into distinct events, mirrors, conflicts and invalid headers. `prs` defaults to the
    workflow's current candidate PRs."""
    comments = list(gh.issue_comments(repo, number))
    for pr_repo, pr_number in sorted(_candidate_prs(workflow) if prs is None else prs):
        comments += gh.issue_comments(pr_repo, pr_number)
    copies: list[Copy] = []
    unread: list[int | None] = []
    for comment in comments:
        try:
            claims = parse_review_records(comment["body"])
        except UnreadComment:  # R11: the whole comment is excluded, visibly; nothing partial is credited
            unread.append(comment["id"])
            continue
        copies += [Copy(comment["created_at"], comment["id"], claim) for claim in claims]
    return select_reviews(copies, str(workflow["work_package"]), unread)


FIRST_REVIEW_CLOSURE_KINDS = ("process", "status")
FIRST_REVIEW_TYPES = ("IMPLEMENTATION_REVIEW", "PROCESS_REVIEW")
"""The published review types that can be the clean first review of a process/status WP (§10.2a)."""


def _outstanding_findings(workflow: dict[str, Any]) -> list[Any]:
    """Every finding the state still carries as not finally closed, in every location the validator
    admits: `open_findings` and `provisionally_closed`, at the top level and under `convergence`
    (KIT-032-R002)."""
    found: list[Any] = []
    for scope in (workflow, workflow.get("convergence")):
        if isinstance(scope, dict):
            for key in ("open_findings", "provisionally_closed"):
                found += list(scope.get(key) or [])
    return found


def _same_candidates(old: dict[str, Any], new: dict[str, Any]) -> bool:
    """The closing patch keeps every candidate's identity: the same sides, and per side the same `pr`,
    `sha`, `base` and any other field. Only `merged_sha` may be recorded, never changed (KIT-032-R001)."""
    before = {side: c for side, c in candidates(old).items() if c is not None}
    after = {side: c for side, c in candidates(new).items() if c is not None}
    if set(before) != set(after):
        return False
    for side, entry in after.items():
        prior = before[side]  # both validated: a candidate side is a mapping or null
        strip = {k: v for k, v in entry.items() if k != "merged_sha"}
        if strip != {k: v for k, v in prior.items() if k != "merged_sha"}:
            return False
        if prior.get("merged_sha") not in (None, entry.get("merged_sha")):
            return False
    return True


def _approval_sources(
    gh: GitHub, repo: str, number: int, current: dict[str, Any]
) -> tuple[set[tuple[str, int]], str | None]:
    """Every candidate PR this coordination issue has ever recorded, from GitHub's own edit history of the
    issue body plus the current state, so a candidate re-pointed in an earlier ordinary patch cannot hide
    a review published on its earlier PR. Refuses (second value) when the history cannot be read or when
    the work-package identity ever differed from the current one (KIT-032-R001)."""
    prs = _candidate_prs(current)
    try:
        revisions = gh.issue_revisions(repo, number)
    except GitHubError as error:
        return prs, f"cannot read the issue's edit history to bind the approval source: {error}"
    for _, body in revisions:
        try:
            state = split_body(body).workflow
        except BodyFormatError:
            continue  # a revision without a state block records no candidate and no identity
        if state.get("work_package") != current["work_package"]:
            return prs, (
                f"the issue recorded work package {state.get('work_package')!r} before "
                f"{current['work_package']!r}; an identity change cannot borrow an approval (§10.2a)"
            )
        try:
            prs |= _candidate_prs(state)
        except (KeyError, TypeError, ValueError, AttributeError):
            return prs, "an earlier revision records a candidate PR this route cannot read; refused (§10.2a)"
    return prs, None


def _first_review_closure(
    gh: GitHub, repo: str, number: int, old: dict[str, Any], new: dict[str, Any]
) -> str | None:
    """`IMPLEMENTATION_REVIEW -> CLOSED` is legal only for a clean process-only or status-only work package
    whose first independent review approved the exact candidate (`coordination-state.md` §10.2a,
    `minion-process#12`). Every clause is checked against the current and intended state and against
    GitHub, never against a hand-recorded marker:

    1. `kind` is explicitly `process` or `status`;
    2. `requirements` is an explicit `[]` before and after;
    3. no finding that is not finally closed, before or after, in any admitted location: `open_findings`
       and `provisionally_closed`, at the top level and under `convergence` (the closing patch cannot
       clear one; KIT-032-R002);
    4. the latest published review event of the WP (a complete, readable, conflict-free selection) is a
       `complete: true`, `APPROVED` `IMPLEMENTATION_REVIEW`/`PROCESS_REVIEW` whose candidate map is
       exactly the recorded candidates' SHAs (independence and zero blocking findings are enforced by
       the review-header validator). The approval source is bound to the current state, never the
       intended one: reviews are read for the current `work_package` from the coordination issue and
       from every candidate PR the issue's edit history has ever recorded, and an identity that ever
       changed refuses (KIT-032-R001);
    5. the closing patch keeps `work_package` and every candidate's sides, `pr`, `sha` and `base`; it may
       only record `merged_sha`;
    6. every candidate PR is `MERGED`, its head is the approved SHA and its merge commit is the recorded
       `merged_sha`;
    7. each merge commit is reachable from its repository's default branch.

    The coordination-state round trip (the eighth clause) is `commit_state`'s own. Semantic and delta WPs,
    unapproved or stale approvals, unmerged candidates and open findings are refused; they keep the
    existing routes (§10.2 `FINAL_CONTRACT_REVIEW -> CLOSED`, `CLOSURE_REVIEW -> CLOSED`)."""
    if not (old["status"] == "IMPLEMENTATION_REVIEW" and new["status"] == "CLOSED"):
        return None
    route = "IMPLEMENTATION_REVIEW -> CLOSED"
    kind = new.get("kind")
    if kind not in FIRST_REVIEW_CLOSURE_KINDS:
        return (
            f"{route} is for a clean process or status WP; kind is {kind!r}. A semantic or delta WP closes "
            "through CLOSURE_REVIEW (§10.2a, §14)"
        )
    if old.get("requirements") != [] or new.get("requirements") != []:
        return f"{route} requires requirements to be an explicit [] before and after the transition (§10.2a)"
    if _outstanding_findings(old) or _outstanding_findings(new):
        return (
            "cannot close with open findings (top-level or convergence, provisionally closed included), and "
            "the closing patch cannot clear them (§4.3, §10.2a)"
        )
    if new.get("work_package") != old.get("work_package"):
        return f"{route}: the closing patch may not change work_package (§10.2a)"
    present = {side: c for side, c in candidates(new).items() if c is not None}
    if not present:
        return f"{route} requires at least one recorded candidate (§4.3)"
    for side, candidate in present.items():
        if not (
            isinstance(candidate, dict)
            and candidate.get("pr")
            and candidate.get("sha")
            and candidate.get("merged_sha")
        ):
            return f"cannot close before the {side} candidate records its pr, sha and merged_sha (§4.3)"
    final = {side: c["sha"] for side, c in present.items()}
    if not _same_candidates(old, new):
        return (
            f"{route}: the closing patch changed the candidate (sides, pr, sha or base); only merged_sha "
            "may be recorded (§10.2a)"
        )
    sources, refusal = _approval_sources(gh, repo, number, old)
    if refusal:
        return f"{route}: {refusal}"
    selection = published_reviews(gh, repo, number, old, sources)
    if not selection.complete or selection.conflicts or selection.invalid_total:
        return (
            f"{route} needs an unambiguous published review record: {len(selection.unread_comments)} unread "
            f"comment(s), {selection.unorderable} unorderable, {len(selection.conflicts)} conflict(s), "
            f"{selection.invalid_total} invalid header(s) (§10.2a)"
        )
    if not selection.events:
        return f"{route} requires a published review of the exact candidate; none found (§10.2a)"
    latest = selection.events[-1]
    label = f"{route}: latest review ({latest['reviewer']}, round {latest['round']}, {latest['type']})"
    if latest["verdict"] != "APPROVED" or latest["complete"] is not True:
        return f"{label} is {latest['verdict']} complete={latest['complete']}, not a complete APPROVED"
    if latest["type"] not in FIRST_REVIEW_TYPES:
        return f"{label} is not one of {', '.join(FIRST_REVIEW_TYPES)} (§10.2a)"
    if latest["candidate"] != final:
        return f"{label} approved {latest['candidate']}, not the exact final candidate {final} (§10.2a)"
    for side, candidate in present.items():
        target, merged, number_ = REPOS[side], candidate["merged_sha"], candidate["pr"]
        pr = gh.pr(target, number_)
        if pr.get("state") != "MERGED" or (pr.get("mergeCommit") or {}).get("oid") != merged:
            return f"{side} PR #{number_} is not merged at {merged[:12]} (§10.2a)"
        if pr.get("headRefOid") != candidate["sha"]:
            return f"{side} PR #{number_} merged head is not the approved {candidate['sha'][:12]} (§11.3)"
        if not gh.contains(target, gh.default_branch(target), merged):
            return f"{side} merge {merged[:12]} is not on the default branch (§10.2a)"
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
        or classification_guard(old, new_workflow)
        or _process_closure(old, new_workflow)
        or _scoping_closure(gh, old, new_workflow)
        or _first_review_closure(gh, repo, number, old, new_workflow)
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
