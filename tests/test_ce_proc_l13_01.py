"""CE-PROC-L13-01 acceptance witnesses (`assurance/process-ce-proc-l13-01.md`, revisions 1-3, AGREED):
fail-closed control data across every consumed field and entry point, totality, and restore-only
repair. FakeGitHub only -- never a real GitHub write."""

from __future__ import annotations

import contextlib
import copy
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from minion_process.cli import main
from minion_process.github import GitHub, GitHubError
from minion_process.model import BodyFormatError, render_body, split_body
from minion_process.ops import CheckFailed, candidate_report, commit_state, handoff_report, restore_revision
from minion_process.validate import errors, validate_workflow

from .test_minion_process import CODE, DOCS, SHA_A, SHA_B, FakeGitHub, workflow

GOOD_V2: dict[str, Any] = {
    "schema_version": 2,
    "work_package": "WP-X",
    "status": "IMPLEMENTATION_REVIEW",
    "current_candidate": {"code": {"pr": 1, "sha": SHA_A}, "docs": {"pr": 2, "sha": SHA_B}},
    "open_findings": [],
    "next_owner": "Codex",
    "next_action": "review",
}


def _paths(result: list[Any]) -> list[str]:
    return [p.path for p in errors(result)]


# --- field x malformation-class table (revisions 1 and 2) --------------------------------------

MALFORMED: list[tuple[str, dict[str, Any], str]] = [
    ("schema_version string", {"schema_version": "2"}, "schema_version"),
    ("schema_version bool", {"schema_version": True}, "schema_version"),
    ("work_package absent", {"work_package": None}, "work_package"),
    ("work_package list", {"work_package": [None]}, "work_package"),
    ("work_package empty", {"work_package": "  "}, "work_package"),
    ("title non-string", {"title": 3}, "title"),
    ("layer non-string", {"layer": ["13"]}, "layer"),
    ("status list", {"status": ["IMPLEMENTATION_REVIEW"]}, "status"),
    ("next_owner list", {"next_owner": ["Codex"]}, "next_owner"),
    ("next_action list", {"next_action": [1]}, "next_action"),
    ("updated_by mapping", {"updated_by": {"a": 1}}, "updated_by"),
    ("requirements string", {"requirements": "TOOL-041"}, "requirements"),
    ("requirements element", {"requirements": [None]}, "requirements[0]"),
    ("open_findings element", {"open_findings": ["bad id"]}, "open_findings[0]"),
    ("v1 mapping bad keys", {"open_findings": {"bad": 1}}, "open_findings"),
    ("code non-mapping", {"code": "x"}, "code"),
    ("code.pr bool", {"code": {"pr": True, "sha": SHA_A}}, "code.pr"),
    ("code.pr zero", {"code": {"pr": 0, "sha": SHA_A}}, "code.pr"),  # found by the totality search
    ("code.pr negative", {"code": {"pr": -3, "sha": SHA_A}}, "code.pr"),
    ("code.sha short", {"code": {"sha": "abc"}}, "code.sha"),
    ("code pr without sha", {"code": {"pr": 1}}, "code.sha"),
    ("code merged without pr", {"code": {"sha": SHA_A, "merged_sha": "e" * 40}}, "code.merged_sha"),
    ("code merged malformed", {"code": {"pr": 1, "sha": SHA_A, "merged_sha": "x"}}, "code.merged_sha"),
    ("code.base non-string", {"code": {"sha": SHA_A, "base": 1}}, "code.base"),
    ("current_candidate non-mapping", {"current_candidate": "not a mapping"}, "current_candidate"),
    ("current_candidate mixed with v1", {"current_candidate": {"code": None}}, "current_candidate"),
    ("convergence non-mapping", {"convergence": ["CE"]}, "convergence"),
    ("convergence.episode list", {"convergence": {"episode": ["CE"]}}, "convergence.episode"),
    ("convergence.checkpoint int", {"convergence": {"checkpoint": 3}}, "convergence.checkpoint"),
    (
        "convergence.open_findings null element",
        {"convergence": {"open_findings": [None]}},
        "convergence.open_findings[0]",
    ),
    (
        "convergence.provisionally_closed bad",
        {"convergence": {"provisionally_closed": [{"x": 1}]}},
        "convergence.provisionally_closed[0]",
    ),
    ("governance_source int", {"governance_source": 5}, "governance_source"),
    ("deferred_trigger list", {"deferred_trigger": ["x"]}, "deferred_trigger"),
    ("quarantine list", {"quarantine": ["x"]}, "quarantine"),
    (
        "quarantine flag string",
        {"quarantine": {"derived_from_quarantined_artifact": "no"}},
        "quarantine.derived_from_quarantined_artifact",
    ),
]


@pytest.mark.parametrize(
    ("overrides", "path"), [(o, p) for _, o, p in MALFORMED], ids=[n for n, _, _ in MALFORMED]
)
def test_every_consumed_field_rejects_its_malformed_classes(overrides: dict[str, Any], path: str) -> None:
    assert path in _paths(validate_workflow(workflow(**overrides)))


V2_MALFORMED: list[tuple[str, dict[str, Any], str]] = [
    ("v2 unknown candidate key", {"current_candidate": {"code": None, "tests": {}}}, "current_candidate"),
    ("v2 candidate side non-mapping", {"current_candidate": {"code": "x"}}, "current_candidate.code"),
    ("v2 mapping findings", {"open_findings": {"L13-X-R1": {}}}, "open_findings"),
    ("v2 dependencies list", {"dependencies": ["L0506"]}, "dependencies"),
    ("v2 dependency edge string", {"dependencies": {"L0506": "x"}}, "dependencies.L0506"),
    (
        "v2 dependency issue string",
        {"dependencies": {"L0506": {"issue": "88", "relation": "blocked_by"}}},
        "dependencies.L0506.issue",
    ),
    (
        "v2 dependency relation list",
        {"dependencies": {"L0506": {"issue": 88, "relation": ["x"]}}},
        "dependencies.L0506.relation",
    ),
    ("v2 history list", {"history": ["x"]}, "history"),
    ("v2 history index int", {"history": {"assurance_index": 1}}, "history.assurance_index"),
]


@pytest.mark.parametrize(
    ("overrides", "path"), [(o, p) for _, o, p in V2_MALFORMED], ids=[n for n, _, _ in V2_MALFORMED]
)
def test_v2_fields_reject_their_malformed_classes(overrides: dict[str, Any], path: str) -> None:
    assert path in _paths(validate_workflow({**GOOD_V2, **overrides}))


@pytest.mark.parametrize(
    "state",
    [
        workflow(),
        workflow(code=None, docs=None),
        workflow(code={"sha": SHA_A}, docs=None),  # SHA-only reference
        workflow(code={"pr": 1, "sha": SHA_A, "merged_sha": "e" * 40}),  # PR-backed baseline
        workflow(open_findings={"L13-X-R1": {"state": "OPEN"}}),  # legacy v1 mapping (warning)
        workflow(
            status="CONTRACT_CONVERGENCE",
            convergence={
                "episode": "CE-X",
                "open_findings": ["L13-X-R1"],
                "provisionally_closed": [{"finding": "L13-X-R2", "sha": SHA_A}],
            },
        ),
        workflow(
            status="WAITING_FOR_TRIGGER", next_owner=None, next_action=None, deferred_trigger="a trigger"
        ),
        GOOD_V2,
        {
            **GOOD_V2,
            "dependencies": {"L0506": {"issue": 88, "relation": "blocked_by"}},
            "history": {"assurance_index": "x.md"},
        },
    ],
)
def test_documented_valid_forms_pass(state: dict[str, Any]) -> None:
    assert errors(validate_workflow(state)) == []


# --- Codex's refined witnesses (PROC-L13 targeted closure at cc44a13b) -------------------------


def _fake_with(state: dict[str, Any]) -> FakeGitHub:
    fake = FakeGitHub()
    fake.issues[(CODE, 10)] = {"body": render_body({"workflow": state}, ""), "state": "OPEN", "title": "x"}
    fake.prs[(CODE, 1)] = {"state": "CLOSED", "isDraft": True, "headRefOid": "c" * 40}
    fake.prs[(DOCS, 2)] = {"state": "OPEN", "isDraft": False, "headRefOid": SHA_B, "mergeable": "MERGEABLE"}
    fake.commits.update({SHA_A, SHA_B})
    return fake


@pytest.mark.parametrize(
    "state",
    [
        workflow(code={"sha": SHA_A, "merged_sha": "e" * 40}, docs=None),  # R001: merged claim without a PR
        {
            **{k: v for k, v in workflow(schema_version=2).items() if k not in ("code", "docs")},
            "current_candidate": "not a mapping",
        },  # R003 witness 1
        workflow(
            status="FINAL_CONTRACT_REVIEW", convergence={"episode": "CE-X", "open_findings": [None]}
        ),  # R003 witness 2
    ],
    ids=["merged-claim-without-pr", "malformed-v2-container", "null-convergence-finding"],
)
def test_refined_witnesses_fail_closed(state: dict[str, Any]) -> None:
    assert errors(validate_workflow(state))  # diagnostics, no TypeError
    fake = _fake_with(state)
    assert handoff_report(GitHub(fake.run), CODE, 10).failed
    assert candidate_report(GitHub(fake.run), state, require_ready=True).failed


# --- entry points: cli status (C-PROC-L13-01-01) -----------------------------------------------


def _ok_fake(state: dict[str, Any]) -> FakeGitHub:
    fake = _fake_with(state)
    fake.prs[(CODE, 1)] = {"state": "OPEN", "isDraft": False, "headRefOid": SHA_A, "mergeable": "MERGEABLE"}
    return fake


@pytest.mark.parametrize("state", [workflow(), GOOD_V2], ids=["v1", "v2"])
def test_cli_status_shows_the_recorded_candidates(
    state: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["status", "10"], gh=GitHub(_ok_fake(state).run)) == 0
    out = capsys.readouterr().out
    assert f"code: PR 1 sha {SHA_A}" in out and f"docs: PR 2 sha {SHA_B}" in out
    assert "PR None" not in out


@pytest.mark.parametrize(
    "state",
    [workflow(work_package=[None]), workflow(status=["X"]), {**GOOD_V2, "current_candidate": "bad"}],
)
def test_cli_status_on_malformed_state_reports_and_exits_1(
    state: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["status", "10"], gh=GitHub(_fake_with(state).run)) == 1
    assert "INVALID" in capsys.readouterr().out


@pytest.mark.parametrize("command", ["validate", "handoff-check", "candidate-check", "status"])
def test_cli_on_an_unparseable_body_reports_and_exits_1(command: str) -> None:
    fake = _fake_with(workflow())
    fake.issues[(CODE, 10)]["body"] = "not a state block"
    assert main([command, "10"], gh=GitHub(fake.run)) == 1


# --- mutation boundary (C-PROC-L13-01-02) ------------------------------------------------------


def _set_status(w: dict[str, Any]) -> None:
    w["status"] = "IMPLEMENTATION_REVIEW"


@pytest.mark.parametrize(
    "current",
    [
        workflow(status=["IMPLEMENTATION_REVIEW"]),
        workflow(work_package=[None]),
        {**GOOD_V2, "current_candidate": "not a mapping"},
    ],
    ids=["status-list", "identity", "v2-container"],
)
def test_invalid_current_state_is_refused_before_any_use(current: dict[str, Any]) -> None:
    fake = _fake_with(current)
    with pytest.raises(CheckFailed, match="current state invalid"):
        commit_state(GitHub(fake.run), CODE, 10, _set_status, {"status"})
    assert fake.edits == 0


@pytest.mark.parametrize(("key", "value"), [(k, v) for _, o, _p in MALFORMED for k, v in o.items()][:20])
def test_invalid_intended_state_is_refused(key: str, value: Any) -> None:
    fake = _ok_fake(workflow())

    def corrupt(w: dict[str, Any]) -> None:
        w[key] = value

    with pytest.raises(CheckFailed, match="intended state invalid"):
        commit_state(GitHub(fake.run), CODE, 10, corrupt, {key})
    assert fake.edits == 0


def test_patch_and_remote_exceptions_are_out_of_scope() -> None:
    """Rule 9: a caller's own exception and a GitHubError propagate unchanged."""
    fake = _ok_fake(workflow())

    def boom(w: dict[str, Any]) -> None:
        raise RuntimeError("patch bug")

    with pytest.raises(RuntimeError, match="patch bug"):
        commit_state(GitHub(fake.run), CODE, 10, boom, {"status"})

    def failing(args: list[str], stdin: str | None) -> str:
        raise GitHubError("network down")

    with pytest.raises(GitHubError):
        commit_state(GitHub(failing), CODE, 10, _set_status, {"status"})


def test_a_missing_pr_is_a_failed_check_not_an_exception() -> None:
    fake = _ok_fake(workflow(code={"pr": 77, "sha": SHA_A}))
    assert any(
        "PR #77 exists" in label
        for label in candidate_report(GitHub(fake.run), workflow(code={"pr": 77, "sha": SHA_A}), True).failed
    )


def test_patch_returning_non_string_prose_is_refused() -> None:
    fake = _ok_fake(workflow())
    with pytest.raises(CheckFailed, match="non-string prose"):
        commit_state(GitHub(fake.run), CODE, 10, lambda w: 5, set())  # type: ignore[arg-type,return-value]
    assert fake.edits == 0


def test_a_state_yaml_cannot_carry_is_refused_before_writing() -> None:
    """Found by the bounded totality search: a key containing U+0085 (YAML NEL) passed validation,
    was written, and only then failed the remote round trip. Now refused with zero writes."""
    fake = _ok_fake(workflow())

    def nel(w: dict[str, Any]) -> None:
        w["code"] = {"pr": 1, "sha": SHA_A, chr(0x85): None}

    with pytest.raises(CheckFailed, match="does not survive YAML serialization"):
        commit_state(GitHub(fake.run), CODE, 10, nel, {"code"})
    assert fake.edits == 0


# --- restore-only repair (revision 3) -----------------------------------------------------------

SCOPING = workflow(status="SCOPING", code=None, docs=None, next_owner="Claude", next_action="scope")
BLOCKED = workflow(
    status="BLOCKED_FOR_OWNER", next_owner="Owner", next_action="decide", governance_source=None
)


def _repair_fake(baseline: dict[str, Any], corrupted: dict[str, Any] | str) -> tuple[FakeGitHub, str]:
    good_body = render_body({"workflow": baseline}, "prose\n")
    fake = _ok_fake(baseline)
    bad_body = corrupted if isinstance(corrupted, str) else render_body({"workflow": corrupted}, "prose\n")
    fake.issues[(CODE, 10)]["body"] = bad_body
    fake.revisions[(CODE, 10)] = [("UCE_bad", bad_body), ("UCE_good", good_body), ("UCE_other", "junk")]
    return fake, good_body


def test_restore_writes_the_earlier_revision_byte_for_byte_then_a_legal_apply_works() -> None:
    corrupted = copy.deepcopy(SCOPING)
    corrupted["status"] = ["SCOPING"]
    fake, good_body = _repair_fake(SCOPING, corrupted)
    restored = restore_revision(GitHub(fake.run), CODE, 10, "UCE_good")
    assert restored == good_body and fake.issues[(CODE, 10)]["body"] == good_body
    assert split_body(fake.issues[(CODE, 10)]["body"]).workflow["status"] == "SCOPING"

    def draft(w: dict[str, Any]) -> None:
        w["status"] = "CONTRACT_DRAFT"

    commit_state(GitHub(fake.run), CODE, 10, draft, {"status"})
    assert fake.edits == 2


def test_restore_then_illegal_transition_is_refused() -> None:
    """Codex's witness: last known-good SCOPING; the follow-up apply to RUST_IMPLEMENTATION is refused."""
    corrupted = copy.deepcopy(SCOPING)
    corrupted["status"] = ["SCOPING"]
    fake, _ = _repair_fake(SCOPING, corrupted)
    restore_revision(GitHub(fake.run), CODE, 10, "UCE_good")

    def jump(w: dict[str, Any]) -> None:
        w["status"] = "RUST_IMPLEMENTATION"

    with pytest.raises(CheckFailed, match="illegal transition"):
        commit_state(GitHub(fake.run), CODE, 10, jump, {"status"})
    assert fake.edits == 1  # only the restoration wrote


def test_restore_then_owner_blocked_resume_without_provenance_is_refused() -> None:
    corrupted = copy.deepcopy(BLOCKED)
    corrupted["work_package"] = [None]
    fake, _ = _repair_fake(BLOCKED, corrupted)
    restore_revision(GitHub(fake.run), CODE, 10, "UCE_good")

    def resume(w: dict[str, Any]) -> None:
        w.update(status="REMEDIATION", next_owner="Claude", next_action="go")

    with pytest.raises(CheckFailed, match="governance_source"):
        commit_state(GitHub(fake.run), CODE, 10, resume, {"status", "next_owner", "next_action"})
    assert fake.edits == 1


@pytest.mark.parametrize(
    ("setup", "match"),
    [
        (lambda f: None, "not in issue"),  # unknown revision id (see below)
        (lambda f: setattr(f, "history_fails", True), "edit history"),
        (lambda f: f.revisions.update({(CODE, 10): [("UCE_x", "junk")]}), "does not parse"),
        (
            lambda f: f.revisions.update(
                {(CODE, 10): [("UCE_x", render_body({"workflow": workflow(status="X")}, ""))]}
            ),
            "not a valid state",
        ),
    ],
    ids=["unknown-revision", "history-fetch-fails", "unparseable-revision", "invalid-revision"],
)
def test_repair_refusals_write_nothing(setup: Any, match: str) -> None:
    corrupted = copy.deepcopy(SCOPING)
    corrupted["status"] = ["SCOPING"]
    fake, _ = _repair_fake(SCOPING, corrupted)
    setup(fake)
    revision = "UCE_missing" if match == "not in issue" else "UCE_x"
    with pytest.raises(CheckFailed, match=match):
        restore_revision(GitHub(fake.run), CODE, 10, revision)
    assert fake.edits == 0


def test_repair_is_refused_when_the_current_state_is_valid() -> None:
    fake, _ = _repair_fake(SCOPING, SCOPING)
    with pytest.raises(CheckFailed, match="current state is valid"):
        restore_revision(GitHub(fake.run), CODE, 10, "UCE_good")
    assert fake.edits == 0


def test_repair_restores_an_unparseable_current_body_and_dry_run_writes_nothing() -> None:
    fake, good_body = _repair_fake(SCOPING, "flattened garbage")
    assert restore_revision(GitHub(fake.run), CODE, 10, "UCE_good", dry_run=True) == good_body
    assert fake.edits == 0
    restore_revision(GitHub(fake.run), CODE, 10, "UCE_good")
    assert fake.issues[(CODE, 10)]["body"] == good_body


def test_cli_repair_takes_only_a_revision_id(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """No caller-supplied baseline exists: --repair with a patch/body file, or without
    --revision, is a usage error."""
    corrupted = copy.deepcopy(SCOPING)
    corrupted["status"] = ["SCOPING"]
    fake, good_body = _repair_fake(SCOPING, corrupted)
    body_file = tmp_path / "baseline.md"
    body_file.write_text(good_body, encoding="utf-8")
    for argv in (
        ["apply", "10", str(body_file), "--repair", "--revision", "UCE_good"],
        ["apply", "10", "--repair"],
    ):
        with pytest.raises(SystemExit):
            main(argv, gh=GitHub(fake.run))
    with pytest.raises(SystemExit):
        main(["apply", "10"], gh=GitHub(fake.run))
    assert fake.edits == 0
    assert main(["apply", "10", "--repair", "--revision", "UCE_good", "--dry-run"], gh=GitHub(fake.run)) == 0
    assert main(["apply", "10", "--repair", "--revision", "UCE_good"], gh=GitHub(fake.run)) == 0
    assert "RESTORED #10 to UCE_good" in capsys.readouterr().out
    assert main(["apply", "10", "--repair", "--revision", "UCE_good"], gh=GitHub(fake.run)) == 1  # now valid


# --- bounded totality over every entry point (rule 4) ------------------------------------------

JSON = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats(allow_nan=False) | st.text(max_size=8),
    lambda inner: st.lists(inner, max_size=3) | st.dictionaries(st.text(max_size=6), inner, max_size=3),
    max_leaves=8,
)
PATHS = [
    ("schema_version",),
    ("work_package",),
    ("title",),
    ("layer",),
    ("status",),
    ("next_owner",),
    ("next_action",),
    ("updated_by",),
    ("updated_reason",),
    ("requirements",),
    ("open_findings",),
    ("provisionally_closed",),
    ("current_candidate",),
    ("code",),
    ("docs",),
    ("code", "pr"),
    ("code", "sha"),
    ("code", "merged_sha"),
    ("code", "base"),
    ("convergence",),
    ("convergence", "episode"),
    ("convergence", "open_findings"),
    ("convergence", "provisionally_closed"),
    ("convergence", "checkpoint"),
    ("governance_source",),
    ("deferred_trigger",),
    ("quarantine",),
    ("quarantine", "derived_from_quarantined_artifact"),
    ("dependencies",),
    ("history",),
]


def _substituted(path: tuple[str, ...], value: Any, base: dict[str, Any]) -> dict[str, Any]:
    state = copy.deepcopy(base)
    if len(path) == 2:
        if not isinstance(state.get(path[0]), dict):
            state[path[0]] = {}
        state[path[0]][path[1]] = value
    else:
        state[path[0]] = value
    return state


SETTINGS = settings(
    max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)


@SETTINGS
@given(path=st.sampled_from(PATHS), value=JSON, lean=st.booleans())
def test_read_only_entry_points_are_total(path: tuple[str, ...], value: Any, lean: bool) -> None:
    state = _substituted(
        path,
        value,
        {**workflow(schema_version=2), "convergence": {"episode": "CE-X"}} if lean else workflow(),
    )
    problems = validate_workflow(state)  # never raises
    fake = _ok_fake(workflow())
    fake.issues[(CODE, 10)]["body"] = render_body({"workflow": state}, "")
    gh = GitHub(fake.run)
    report = candidate_report(gh, state, require_ready=True)  # never raises
    handoff = handoff_report(gh, CODE, 10)  # never raises
    if errors(problems):
        assert report.failed and handoff.failed  # fail closed
    assert main(["status", "10"], gh=gh) in (0, 1)  # diagnostics, never a traceback
    assert main(["validate", "10"], gh=gh) in (0, 1)


@SETTINGS
@given(path=st.sampled_from(PATHS), value=JSON, intended=st.booleans())
def test_commit_state_refuses_malformed_data_with_controlled_exceptions(
    path: tuple[str, ...], value: Any, intended: bool
) -> None:
    base = workflow()
    fake = _ok_fake(base)
    if not intended:  # malformed CURRENT state
        fake.issues[(CODE, 10)]["body"] = render_body({"workflow": _substituted(path, value, base)}, "")

    def mutate(w: dict[str, Any]) -> None:
        if intended:  # malformed INTENDED state
            w.clear()
            w.update(_substituted(path, value, base))

    try:
        commit_state(GitHub(fake.run), CODE, 10, mutate, set(base) | {path[0]})
    except (CheckFailed, BodyFormatError):
        assert fake.edits == 0


# --- remaining branches -------------------------------------------------------------------------


def test_a_non_mapping_workflow_and_a_missing_convergence_are_diagnosed() -> None:
    assert _paths(validate_workflow([1])) == ["workflow"]
    assert "convergence.episode" in _paths(validate_workflow(workflow(status="CONTRACT_CONVERGENCE")))


def test_a_side_without_any_exact_reference_fails_the_candidate_check() -> None:
    state = workflow(code={"base": "main"}, docs=None)  # legacy-style side: no sha, no pr
    fake = _ok_fake(state)
    assert "code candidate records an exact SHA" in candidate_report(GitHub(fake.run), state, True).failed


def test_issue_revisions_follow_pagination() -> None:
    import json

    pages = iter(
        [
            {"pageInfo": {"hasNextPage": True, "endCursor": "C1"}, "nodes": [{"id": "A", "diff": "a"}]},
            {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "nodes": [{"id": "B", "diff": "b"}, {"id": "C"}],
            },
        ]
    )
    seen: list[list[str]] = []

    def run(args: list[str], stdin: str | None) -> str:
        seen.append(args)
        return json.dumps({"data": {"repository": {"issue": {"userContentEdits": next(pages)}}}})

    assert GitHub(run).issue_revisions(CODE, 10) == [("A", "a"), ("B", "b")]
    assert "c=C1" in seen[1]


# --- PROC-L13-R003 refinement (Codex targeted closure at 290677bd): invalid YAML inside a valid fence ----

FENCE = "```yaml" + chr(10)
CLOSE = chr(10) + "```" + chr(10)
NL = chr(10)
YAML_SYNTAX_FAILURES = [
    FENCE + "workflow:" + NL + "  status: [" + CLOSE,  # Codex's exact witness: unclosed flow sequence
    FENCE + "workflow:" + NL + '  status: "open' + CLOSE,  # unterminated quote
    FENCE + "workflow:" + NL + chr(9) + "status: SCOPING" + CLOSE,  # tab indentation
    FENCE + "workflow:" + NL + "  a: 1" + NL + " b: 2" + CLOSE,  # bad indentation
    FENCE + "workflow: !!python/object:os.system {}" + CLOSE,  # a tag safe_load refuses
    FENCE + "workflow: *missing" + CLOSE,  # undefined alias
    FENCE + "workflow:" + NL + "  - a" + NL + "  b: c" + CLOSE,  # mixed sequence/mapping
]


def _raw_fake(body: str) -> FakeGitHub:
    fake = FakeGitHub()
    fake.issues[(CODE, 10)] = {"body": body, "state": "OPEN", "title": "x"}
    fake.revisions[(CODE, 10)] = [("GOOD", render_body({"workflow": workflow()}, ""))]
    return fake


@pytest.mark.parametrize("body", YAML_SYNTAX_FAILURES)
def test_invalid_yaml_is_a_controlled_body_error(body: str) -> None:
    with pytest.raises(BodyFormatError):
        split_body(body)


@pytest.mark.parametrize("body", YAML_SYNTAX_FAILURES)
@pytest.mark.parametrize("command", ["status", "validate", "candidate-check", "handoff-check"])
def test_invalid_yaml_is_a_controlled_read_refusal(command: str, body: str) -> None:
    fake = _raw_fake(body)
    assert main([command, "10"], gh=GitHub(fake.run)) == 1
    assert fake.edits == 0


@pytest.mark.parametrize("body", YAML_SYNTAX_FAILURES)
def test_invalid_yaml_current_state_is_refused_by_apply_and_restorable(body: str) -> None:
    fake = _raw_fake(body)
    with pytest.raises((CheckFailed, BodyFormatError)):
        commit_state(GitHub(fake.run), CODE, 10, lambda w: None, set())
    assert fake.edits == 0
    expected = fake.revisions[(CODE, 10)][0][1]
    assert restore_revision(GitHub(fake.run), CODE, 10, "GOOD") == expected
    assert fake.edits == 1 and fake.issues[(CODE, 10)]["body"] == expected


@pytest.mark.parametrize("body", YAML_SYNTAX_FAILURES)
def test_an_invalid_yaml_baseline_is_a_controlled_refusal(body: str) -> None:
    fake = _raw_fake("flattened garbage")
    fake.revisions[(CODE, 10)] = [("BAD", body)]
    with pytest.raises(CheckFailed, match="does not parse"):
        restore_revision(GitHub(fake.run), CODE, 10, "BAD")
    assert fake.edits == 0


@SETTINGS
@given(inner=st.text(max_size=60), prose=st.text(max_size=10))
def test_raw_body_text_is_total_for_every_entry_point(inner: str, prose: str) -> None:
    """The raw-body dimension the object-level property cannot reach: arbitrary text inside the fence."""
    body = FENCE + inner + CLOSE + prose
    fake = _raw_fake(body)
    gh = GitHub(fake.run)
    for command in ("status", "validate", "candidate-check", "handoff-check"):
        assert main([command, "10"], gh=gh) in (0, 1)
    with contextlib.suppress(CheckFailed, BodyFormatError):
        commit_state(gh, CODE, 10, lambda w: None, set())
    with contextlib.suppress(CheckFailed):
        restore_revision(gh, CODE, 10, "GOOD")
