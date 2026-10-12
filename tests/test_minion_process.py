"""Offline tests for `minion_process`: a fake `gh` runner stands in for GitHub."""

from __future__ import annotations

import itertools
import json
from pathlib import Path
from typing import Any

import pytest

from minion_process.cli import main
from minion_process.github import GitHub
from minion_process.model import BodyFormatError, render_body, split_body
from minion_process.ops import (
    CheckFailed,
    commit_state,
    guarded_merge,
    handoff_report,
    verified_comment,
)
from minion_process.transitions import LEGAL, check_transition
from minion_process.validate import errors, validate_workflow

SHA_A = "a" * 40
SHA_B = "b" * 40
CODE, DOCS = "EGAILab/minion-agent", "EGAILab/minion-agent-docs"


def workflow(**overrides: Any) -> dict[str, Any]:
    w: dict[str, Any] = {
        "schema_version": 1,
        "work_package": "WP-X",
        "status": "IMPLEMENTATION_REVIEW",
        "code": {"pr": 1, "sha": SHA_A, "base": "main"},
        "docs": {"pr": 2, "sha": SHA_B, "base": "master"},
        "next_owner": "Codex",
        "next_action": "review",
        "quarantine": {"derived_from_quarantined_artifact": False},
    }
    w.update(overrides)
    return w


class FakeGitHub:
    """Enough of `gh` for the operations: issues, PRs, commits, compare, comments."""

    def __init__(self) -> None:
        self.issues: dict[tuple[str, int], dict[str, Any]] = {}
        self.prs: dict[tuple[str, int], dict[str, Any]] = {}
        self.commits: set[str] = set()
        self.default = {CODE: "main", DOCS: "master"}
        self.on_default: set[str] = set()
        self.comments: dict[str, str] = {}
        self.corrupt_next_edit = False
        self.edits = 0
        self.merges: list[tuple[str, int, str]] = []
        self.revisions: dict[tuple[str, int], list[tuple[str, str]]] = {}
        self.history_fails = False

    def run(self, args: list[str], stdin: str | None) -> str:
        from minion_process.github import GitHubError

        head = args[0]
        if head == "issue" and args[1] == "view":
            return json.dumps(self.issues[(args[4], int(args[2]))])
        if head == "issue" and args[1] == "edit":
            assert stdin is not None
            self.edits += 1
            body = " ".join(stdin.split("\n")) if self.corrupt_next_edit else stdin
            self.corrupt_next_edit = False
            self.issues[(args[4], int(args[2]))]["body"] = body
            return ""
        if head == "pr" and args[1] == "view":
            if (args[4], int(args[2])) not in self.prs:
                raise GitHubError(f"no pull request {args[2]}")
            return json.dumps(self.prs[(args[4], int(args[2]))])
        if head == "pr" and args[1] == "merge":
            repo, number, sha = args[4], int(args[2]), args[-1]
            pr = self.prs[(repo, number)]
            merge_sha = "m" * 39 + str(number)
            pr.update(state="MERGED", mergeCommit={"oid": merge_sha})
            self.on_default.add(merge_sha)
            self.merges.append((repo, number, sha))
            return ""
        if head in ("issue", "pr") and args[1] == "comment":
            cid = str(len(self.comments) + 1)
            self.comments[cid] = stdin or ""
            return f"https://github.com/{args[4]}/issues/{args[2]}#issuecomment-{cid}\n"
        if head == "api" and args[1] == "graphql":
            if self.history_fails:
                raise GitHubError("graphql unavailable")
            fields = dict(a.split("=", 1) for a in args[2:] if "=" in a and not a.startswith("query="))
            key = (f"{fields['o']}/{fields['n']}", int(fields["i"]))
            nodes = [{"id": rid, "diff": body} for rid, body in self.revisions.get(key, [])]
            page = {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": nodes}
            return json.dumps({"data": {"repository": {"issue": {"userContentEdits": page}}}})
        if head == "api":
            path = args[1]
            if "/commits/" in path:
                if path.rsplit("/", 1)[1] in self.commits:
                    return path.rsplit("/", 1)[1]
                raise GitHubError("404")
            if "/compare/" in path:
                sha = path.split("/compare/")[1].split("...")[0]
                return "ahead" if sha in self.on_default else "diverged"
            if "/issues/comments/" in path:
                return self.comments[path.rsplit("/", 1)[1]]
            repo = path.removeprefix("repos/")
            return self.default[repo]
        raise AssertionError(f"unexpected gh call {args}")


@pytest.fixture
def fake() -> FakeGitHub:
    f = FakeGitHub()
    f.issues[(CODE, 10)] = {
        "body": render_body({"workflow": workflow()}, "Prose kept.\n"),
        "state": "OPEN",
        "title": "WP-X",
    }
    f.prs[(CODE, 1)] = {"state": "OPEN", "isDraft": False, "headRefOid": SHA_A, "mergeable": "MERGEABLE"}
    f.prs[(DOCS, 2)] = {"state": "OPEN", "isDraft": False, "headRefOid": SHA_B, "mergeable": "MERGEABLE"}
    f.commits |= {SHA_A, SHA_B}
    return f


# --- body container ----------------------------------------------------------------------------


def test_body_round_trips_and_keeps_prose() -> None:
    body = render_body({"workflow": workflow()}, "History lives below.\n")
    parsed = split_body("\ufeff" + body.replace("\n", "\r\n"))
    assert parsed.workflow == workflow()
    assert parsed.prose == "History lives below.\n"


@pytest.mark.parametrize("body", ["no block", "```yaml\nworkflow: {}\n", "```yaml\n- a\n```\n"])
def test_malformed_bodies_are_rejected(body: str) -> None:
    with pytest.raises(BodyFormatError):
        split_body(body).workflow  # noqa: B018


def test_a_flattened_body_is_rejected() -> None:
    """The Layer-12 incident: a body flattened into one line is not a valid state block."""
    flat = " ".join(render_body({"workflow": workflow()}, "").split("\n"))
    with pytest.raises(BodyFormatError):
        split_body(flat)


# --- validation ------------------------------------------------------------------------------


def test_a_valid_state_has_no_errors() -> None:
    assert errors(validate_workflow(workflow())) == []


@pytest.mark.parametrize(
    ("overrides", "path"),
    [
        ({"status": "BLOCKED"}, "status"),  # the #49 incident: not a legal status value
        ({"next_owner": None}, "next_owner"),
        ({"next_action": ""}, "next_action"),
        ({"next_owner": "Gemini"}, "next_owner"),
        ({"status": "BLOCKED_FOR_OWNER", "next_owner": "Claude"}, "next_owner"),
        ({"status": "WAITING_FOR_TRIGGER"}, "deferred_trigger"),
        ({"code": {"pr": 1, "sha": "abc123"}}, "code.sha"),
        ({"code": {"pr": "1", "sha": SHA_A}}, "code.pr"),
        ({"status": "CONTRACT_CONVERGENCE", "convergence": {}}, "convergence.episode"),
        (
            {
                "status": "FINAL_CONTRACT_REVIEW",
                "convergence": {"episode": "CE", "open_findings": ["L13-X-R1"]},
            },
            "convergence.open_findings",
        ),
        ({"requirements": "TOOL-041"}, "requirements"),  # a string is iterable but not a list
        ({"quarantine": {"derived_from_quarantined_artifact": True}}, "quarantine"),
    ],
)
def test_structural_errors(overrides: dict[str, Any], path: str) -> None:
    found = errors(validate_workflow(workflow(**overrides)))
    assert path in [p.path for p in found], found


def test_waiting_for_trigger_needs_null_owner_and_a_trigger() -> None:
    ok = workflow(
        status="WAITING_FOR_TRIGGER", next_owner=None, next_action=None, deferred_trigger={"type": "x"}
    )
    assert errors(validate_workflow(ok)) == []
    assert errors(validate_workflow({**ok, "next_owner": "Claude"}))


def test_history_and_size_are_warnings_not_errors() -> None:
    problems = validate_workflow(workflow(python_implementation={"remediations": [1]}), body_chars=34759)
    assert errors(problems) == []
    assert {p.path for p in problems} == {"remediations", "body"}


# --- transitions -----------------------------------------------------------------------------


def test_every_status_has_a_row() -> None:
    assert check_transition("CLOSED", "SCOPING")
    assert check_transition("SCOPING", "CONTRACT_DRAFT") is None
    assert check_transition("CONTRACT_REVIEW", "CONTRACT_REVIEW") is None


@pytest.mark.parametrize(
    "sequence",
    [
        # #88 (L0506-D001), contract-first then convergence -- legal under the reconciled table
        [
            "CONTRACT_DRAFT",
            "CONTRACT_REVIEW",
            "CONTRACT_DRAFT",
            "CONTRACT_REVIEW",
            "FINAL_CONTRACT_REVIEW",
            "CONTRACT_DRAFT",
            "CONTRACT_REVIEW",
            "FINAL_CONTRACT_REVIEW",
            "PYTHON_IMPLEMENTATION",
            "IMPLEMENTATION_REVIEW",
            "REMEDIATION",
            "IMPLEMENTATION_REVIEW",
            "CONTRACT_CONVERGENCE",
            "FINAL_CONTRACT_REVIEW",
            "CONTRACT_CONVERGENCE",
            "FINAL_CONTRACT_REVIEW",
            "RUST_IMPLEMENTATION",
        ],
        ["SCOPING", "WAITING_FOR_TRIGGER", "SCOPING"],
        ["RUST_IMPLEMENTATION", "CLOSURE_REVIEW", "RUST_IMPLEMENTATION", "CLOSURE_REVIEW", "CLOSED"],
    ],
)
def test_legal_sequences(sequence: list[str]) -> None:
    for old, new in itertools.pairwise(sequence):
        assert check_transition(old, new) is None, (old, new)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("CONTRACT_REVIEW", "REMEDIATION"),  # #49: contract findings go back to CONTRACT_DRAFT
        ("REMEDIATION", "CONTRACT_REVIEW"),  # #49
        ("RUST_IMPLEMENTATION", "IMPLEMENTATION_REVIEW"),  # #79: Rust review is CLOSURE_REVIEW
        ("IMPLEMENTATION_REVIEW", "CLOSED"),  # #79
        ("CONTRACT_CONVERGENCE", "RUST_IMPLEMENTATION"),  # skipping the final complete review
        ("PYTHON_IMPLEMENTATION", "RUST_IMPLEMENTATION"),  # Rust before shared/Python approval
        ("INVALID_UNAUTHORIZED", "SCOPING"),
        ("CLOSED", "BLOCKED_FOR_OWNER"),
        ("IMPLEMENTATION_REVIEW", "BLOCKED"),
    ],
)
def test_historical_and_forbidden_transitions_are_rejected(old: str, new: str) -> None:
    assert check_transition(old, new)


def test_any_active_state_may_block_for_the_owner_and_resume() -> None:
    for status in LEGAL:
        if status in ("CLOSED", "INCIDENT", "INVALID_UNAUTHORIZED", "WAITING_FOR_TRIGGER"):
            continue
        assert check_transition(status, "BLOCKED_FOR_OWNER") is None, status
    assert check_transition("BLOCKED_FOR_OWNER", "REMEDIATION") is None


# --- state commit (§11.1.1) ------------------------------------------------------------------


def _handoff(w: dict[str, Any]) -> None:
    w["status"] = "REMEDIATION"
    w["next_owner"] = "Claude"
    w["next_action"] = "fix R1"


def test_commit_writes_verifies_and_keeps_prose(fake: FakeGitHub) -> None:
    changed, _ = commit_state(GitHub(fake.run), CODE, 10, _handoff, {"status", "next_owner", "next_action"})
    assert changed == ["next_action", "next_owner", "status"]
    parsed = split_body(fake.issues[(CODE, 10)]["body"])
    assert parsed.workflow["status"] == "REMEDIATION"
    assert parsed.prose == "Prose kept.\n"


def test_commit_rejects_keys_outside_allowed_before_writing(fake: FakeGitHub) -> None:
    with pytest.raises(CheckFailed, match="outside ALLOWED"):
        commit_state(GitHub(fake.run), CODE, 10, _handoff, {"status"})
    assert fake.edits == 0


def test_commit_rejects_an_illegal_transition_before_writing(fake: FakeGitHub) -> None:
    def to_closed(w: dict[str, Any]) -> None:
        w["status"] = "CLOSED"

    with pytest.raises(CheckFailed, match="illegal transition"):
        commit_state(GitHub(fake.run), CODE, 10, to_closed, {"status"})
    assert fake.edits == 0


def test_commit_rejects_an_invalid_intended_state_before_writing(fake: FakeGitHub) -> None:
    def drop_owner(w: dict[str, Any]) -> None:
        w["next_owner"] = None

    with pytest.raises(CheckFailed, match="intended state invalid"):
        commit_state(GitHub(fake.run), CODE, 10, drop_owner, {"next_owner"})
    assert fake.edits == 0


def test_a_transport_flattened_write_is_a_failed_commit(fake: FakeGitHub) -> None:
    fake.corrupt_next_edit = True
    with pytest.raises((CheckFailed, BodyFormatError)):
        commit_state(GitHub(fake.run), CODE, 10, _handoff, {"status", "next_owner", "next_action"})


def test_dry_run_never_writes(fake: FakeGitHub) -> None:
    commit_state(GitHub(fake.run), CODE, 10, _handoff, {"status", "next_owner", "next_action"}, dry_run=True)
    assert fake.edits == 0


# --- handoff / candidate (§11.11, §11.3) -----------------------------------------------------


def test_handoff_passes_for_a_current_candidate(fake: FakeGitHub) -> None:
    report = handoff_report(GitHub(fake.run), CODE, 10)
    assert report.failed == []


@pytest.mark.parametrize(
    ("mutate", "label"),
    [
        (lambda f: f.prs[(CODE, 1)].update(headRefOid="c" * 40), "head =="),
        (lambda f: f.prs[(DOCS, 2)].update(isDraft=True), "ready for review"),
        (lambda f: f.prs[(CODE, 1)].update(state="CLOSED"), "open"),
        (lambda f: f.commits.discard(SHA_B), "remote-reachable"),
        (lambda f: f.issues[(CODE, 10)].update(state="CLOSED"), "coordination issue OPEN"),
    ],
)
def test_handoff_blocks(fake: FakeGitHub, mutate: Any, label: str) -> None:
    mutate(fake)
    report = handoff_report(GitHub(fake.run), CODE, 10)
    assert any(label in failed for failed in report.failed), report.failed


def test_handoff_blocks_for_owner_and_incident_states(fake: FakeGitHub) -> None:
    for status, owner in (("BLOCKED_FOR_OWNER", "Owner"), ("INCIDENT", "Claude")):
        fake.issues[(CODE, 10)]["body"] = render_body(
            {"workflow": workflow(status=status, next_owner=owner)}, ""
        )
        assert any("permits a handoff" in f for f in handoff_report(GitHub(fake.run), CODE, 10).failed)


# --- guarded merge ---------------------------------------------------------------------------


def test_merge_exact_head_and_containment(fake: FakeGitHub) -> None:
    merged = guarded_merge(GitHub(fake.run), CODE, 1, SHA_A, wait=lambda _: None)
    assert fake.merges == [(CODE, 1, SHA_A)]
    assert merged in fake.on_default


def test_merge_stops_when_the_head_moved(fake: FakeGitHub) -> None:
    fake.prs[(CODE, 1)]["headRefOid"] = "c" * 40
    with pytest.raises(CheckFailed, match="MERGE BLOCKED"):
        guarded_merge(GitHub(fake.run), CODE, 1, SHA_A, wait=lambda _: None)
    assert fake.merges == []


def test_merge_not_reachable_from_default_is_a_failure(fake: FakeGitHub) -> None:
    original = fake.run

    def run(args: list[str], stdin: str | None) -> str:
        out = original(args, stdin)
        if args[:2] == ["pr", "merge"]:
            fake.on_default.clear()
        return out

    with pytest.raises(CheckFailed, match="not reachable"):
        guarded_merge(GitHub(run), CODE, 1, SHA_A, wait=lambda _: None)


# --- comments / CLI ----------------------------------------------------------------------------


def test_verified_comment(fake: FakeGitHub) -> None:
    url = verified_comment(GitHub(fake.run), CODE, 10, "line 1\nline 2\n")
    assert url.endswith("issuecomment-1")


def test_cli_transition_and_validate(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["transition-check", "CONTRACT_CONVERGENCE", "FINAL_CONTRACT_REVIEW"]) == 0
    assert main(["transition-check", "CONTRACT_CONVERGENCE", "RUST_IMPLEMENTATION"]) == 1
    good = tmp_path / "good.md"
    good.write_text(render_body({"workflow": workflow()}, ""), encoding="utf-8")
    assert main(["validate", "--file", str(good)]) == 0
    bad = tmp_path / "bad.md"
    bad.write_text(render_body({"workflow": workflow(status="BLOCKED")}, ""), encoding="utf-8")
    assert main(["validate", "--file", str(bad)]) == 1
    assert "INVALID" in capsys.readouterr().out


def test_cli_apply_with_a_patch_file(fake: FakeGitHub, tmp_path: Path) -> None:
    patch = tmp_path / "patch.py"
    patch.write_text(
        "ALLOWED = {'status', 'next_owner', 'next_action'}\n"
        "def apply(w):\n    w['status'] = 'REMEDIATION'\n    w['next_owner'] = 'Claude'\n"
        "    w['next_action'] = 'fix'\n",
        encoding="utf-8",
    )
    assert main(["apply", "10", str(patch)], gh=GitHub(fake.run)) == 0
    assert split_body(fake.issues[(CODE, 10)]["body"]).workflow["status"] == "REMEDIATION"


# ---- PROC-L13-F001: a process-only WP closes from FINAL_CONTRACT_REVIEW (coordination-state.md §10.2)


def _process_wp(**changes: Any) -> dict[str, Any]:
    state = {k: v for k, v in workflow(schema_version=2).items() if k not in ("code", "docs")}
    state.update(
        status="FINAL_CONTRACT_REVIEW",
        requirements=[],
        open_findings=[],
        current_candidate={"docs": {"pr": 7, "sha": "a" * 40, "merged_sha": "b" * 40}},
    )
    state.update(changes)
    return state


def _close(state: dict[str, Any]) -> None:
    from minion_process.github import GitHub
    from minion_process.model import render_body
    from minion_process.ops import commit_state

    fake = FakeGitHub()
    fake.issues[(CODE, 10)] = {"body": render_body({"workflow": state}, ""), "state": "OPEN", "title": "x"}

    def mutate(w: dict[str, Any]) -> None:
        w["status"] = "CLOSED"
        w["next_owner"] = None
        w["next_action"] = None

    commit_state(GitHub(fake.run), CODE, 10, mutate, {"status", "next_owner", "next_action"}, dry_run=True)


def test_a_process_only_wp_may_close_from_final_review() -> None:
    assert check_transition("FINAL_CONTRACT_REVIEW", "CLOSED") is None
    _close(_process_wp())


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"requirements": ["TOOL-041"]}, "process-only"),
        ({"open_findings": ["X-R001"]}, "open findings"),
        ({"current_candidate": {"docs": {"pr": 7, "sha": "a" * 40}}}, "merged_sha"),
        (
            {
                "current_candidate": {
                    "docs": {"pr": 7, "sha": "a" * 40, "merged_sha": "b" * 40},
                    "code": {"pr": 8, "sha": "c" * 40},
                }
            },
            "merged_sha",
        ),
    ],
    ids=["product-requirement", "open-finding", "unmerged", "one-candidate-unmerged"],
)
def test_process_closure_is_refused_unless_mechanically_complete(
    changes: dict[str, Any], message: str
) -> None:
    with pytest.raises(CheckFailed, match=message):
        _close(_process_wp(**changes))


def _close_for_real(state: dict[str, Any], clear_requirements: bool = False) -> FakeGitHub:
    from minion_process.github import GitHub
    from minion_process.model import render_body
    from minion_process.ops import commit_state

    fake = FakeGitHub()
    fake.issues[(CODE, 10)] = {"body": render_body({"workflow": state}, ""), "state": "OPEN", "title": "x"}

    def mutate(w: dict[str, Any]) -> None:
        w["status"] = "CLOSED"
        w["next_owner"] = None
        w["next_action"] = None
        if clear_requirements:
            w["requirements"] = []

    allowed = {"status", "next_owner", "next_action", "requirements"}
    with pytest.raises(CheckFailed, match="explicit"):
        commit_state(GitHub(fake.run), CODE, 10, mutate, allowed)
    return fake


@pytest.mark.parametrize(
    ("scope", "clear"),
    [("missing", False), (None, False), (["TOOL-041"], True)],
    ids=["requirements-missing", "requirements-null", "closure-clears-product-requirements"],
)
def test_process_closure_needs_an_explicit_empty_scope_before_and_after(scope: object, clear: bool) -> None:
    """PROC-L13-F001 refinement (Codex F001 review): each bypass is refused with ZERO writes."""
    state = _process_wp()
    if scope == "missing":
        del state["requirements"]
    else:
        state["requirements"] = scope
    fake = _close_for_real(state, clear_requirements=clear)
    assert fake.edits == 0
