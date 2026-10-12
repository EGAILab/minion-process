"""Witnesses for Codex review 1 of kit 0.2.0 (`PROC-KIT-P2-R001`..`R003`), each run through the real
`commit_state` with the fake remote and asserting zero writes on refusal, plus positive controls."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from minion_process.github import GitHub
from minion_process.model import render_body, split_body
from minion_process.ops import CheckFailed, classification_guard, commit_state
from minion_process.validate import errors, validate_workflow

from .test_minion_process import CODE, FakeGitHub, workflow

GOVERNING: dict[str, Any] = {
    "schema_version": 2,
    "kind": "process",
    "consequence": {"class": "governing", "rule": "CP-3"},
    "requirements": [],
}
SKIP = {"stage": "IMPLEMENTATION_REVIEW", "rule": "SK-1", "measured_rows": ["r"], "reviewer": "Codex"}


def governing(**overrides: Any) -> dict[str, Any]:
    """A fresh classified governing WP (deep-copied: tests mutate nested mappings)."""
    return workflow(**copy.deepcopy(GOVERNING), **overrides)


def setup(w: dict[str, Any]) -> tuple[FakeGitHub, GitHub]:
    f = FakeGitHub()
    f.issues[(CODE, 10)] = {"body": render_body({"workflow": w}, "probe\n"), "state": "OPEN", "title": "WP-X"}
    return f, GitHub(f.run)


def patch(**changes: Any) -> Any:
    def apply(w: dict[str, Any]) -> None:
        w.update(copy.deepcopy(changes))

    return apply


def remote(f: FakeGitHub) -> dict[str, Any]:
    return split_body(f.issues[(CODE, 10)]["body"]).workflow


def paths(w: dict[str, Any]) -> list[str]:
    return [p.path for p in errors(validate_workflow(w))]


# --- R002: supplied null is a diagnostic, not absence -------------------------------------------


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("kind",), None),
        (("consequence",), None),
        (("consequence", "downgrade"), None),
        (("skipped",), None),
        (("history", "routes"), None),
        (("classification_pending",), None),
        (("classification_pending",), "yes"),
        (("kind",), True),
        (("consequence", "class"), None),
        (("consequence", "rule"), None),
    ],
)
def test_r002_supplied_null_or_wrong_type_is_an_error(path: tuple[str, ...], value: Any) -> None:
    w = governing()
    node: Any = w
    for key in path[:-1]:
        node = node.setdefault(key, {})
    node[path[-1]] = value
    found = paths(w)
    assert ".".join(path) in found, found


def test_r002_genuinely_absent_optional_fields_stay_valid() -> None:
    assert errors(validate_workflow(governing())) == []
    assert errors(validate_workflow(workflow(schema_version=2))) == []  # grandfathered, warns only


def test_pending_flag_never_coexists_with_a_classification() -> None:
    assert "classification_pending" in paths(governing(classification_pending=True))
    assert errors(validate_workflow(governing(classification_pending=False))) == []
    pending = workflow(
        schema_version=2, status="BLOCKED_FOR_OWNER", next_owner="Owner", classification_pending=True
    )
    assert errors(validate_workflow(pending)) == []


# --- R001: classification is sticky; lowering is the Owner-only downgrade -------------------------


def test_r001_erasure_is_refused_with_zero_writes() -> None:
    f, gh = setup(governing())

    def erase(w: dict[str, Any]) -> None:
        del w["consequence"]

    with pytest.raises(CheckFailed, match="sticky"):
        commit_state(gh, CODE, 10, erase, {"consequence"})
    assert f.edits == 0

    def erase_kind(w: dict[str, Any]) -> None:
        del w["kind"]

    with pytest.raises(CheckFailed, match="sticky"):
        commit_state(gh, CODE, 10, erase_kind, {"kind"})

    def null_it(w: dict[str, Any]) -> None:
        w["consequence"] = None

    with pytest.raises(CheckFailed, match="intended state invalid"):
        commit_state(gh, CODE, 10, null_it, {"consequence"})
    assert f.edits == 0 and remote(f)["consequence"] == {"class": "governing", "rule": "CP-3"}


def test_r001_direct_lowering_and_skip_on_governing_are_refused_with_zero_writes() -> None:
    f, gh = setup(governing())
    with pytest.raises(CheckFailed, match="Owner-only"):
        commit_state(
            gh, CODE, 10, patch(consequence={"class": "mechanical", "rule": "CP-0"}), {"consequence"}
        )
    with pytest.raises(CheckFailed, match="intended state invalid"):
        commit_state(gh, CODE, 10, patch(skipped=[SKIP]), {"skipped"})
    assert f.edits == 0


def test_r001_authorized_downgrade_still_works() -> None:
    f, gh = setup(governing())
    authorized = patch(
        consequence={
            "class": "mechanical",
            "rule": "CP-0",
            "downgrade": {"owner_decision": "#205 ...", "reviewer": "Codex"},
        },
        governance_source={"artifact": "minion-agent#205#issuecomment-1"},
    )
    commit_state(gh, CODE, 10, authorized, {"consequence", "governance_source"})
    assert f.edits == 1 and remote(f)["consequence"]["class"] == "mechanical"
    commit_state(gh, CODE, 10, patch(skipped=[SKIP]), {"skipped"})  # now legitimately mechanical
    assert f.edits == 2


def test_r001_guard_treats_absent_new_class_as_lowering() -> None:
    old = governing()
    assert "sticky" in str(classification_guard(old, {**old, "consequence": {}}))  # class absent
    assert "sticky" in str(classification_guard(old, {k: v for k, v in old.items() if k != "kind"}))


# --- R003: pending intake survives a pause -------------------------------------------------------


def test_r003_unclassified_pause_needs_the_pending_flag_and_resume_needs_classification() -> None:
    f, gh = setup(workflow(schema_version=2, status="SCOPING", code=None, docs=None))
    with pytest.raises(CheckFailed, match="classification_pending"):
        commit_state(
            gh, CODE, 10, patch(status="BLOCKED_FOR_OWNER", next_owner="Owner"), {"status", "next_owner"}
        )
    assert f.edits == 0
    commit_state(
        gh,
        CODE,
        10,
        patch(status="BLOCKED_FOR_OWNER", next_owner="Owner", classification_pending=True),
        {"status", "next_owner", "classification_pending"},
    )
    assert f.edits == 1
    resume_unclassified = patch(
        status="CONTRACT_DRAFT", next_owner="Codex", governance_source={"artifact": "Owner resumes this WP"}
    )
    with pytest.raises(CheckFailed, match="pending intake"):
        commit_state(gh, CODE, 10, resume_unclassified, {"status", "next_owner", "governance_source"})
    assert f.edits == 1 and remote(f)["status"] == "BLOCKED_FOR_OWNER"

    def drop_flag(w: dict[str, Any]) -> None:
        del w["classification_pending"]

    with pytest.raises(CheckFailed, match="cannot be dropped"):
        commit_state(gh, CODE, 10, drop_flag, {"classification_pending"})

    def resume_classified(w: dict[str, Any]) -> None:
        w.update(
            status="CONTRACT_DRAFT",
            next_owner="Codex",
            governance_source={"artifact": "Owner resumes this WP"},
            kind="process",
            consequence={"class": "mechanical", "rule": "CP-0"},
        )
        del w["classification_pending"]

    commit_state(
        gh,
        CODE,
        10,
        resume_classified,
        {"status", "next_owner", "governance_source", "kind", "consequence", "classification_pending"},
    )
    assert f.edits == 2 and remote(f)["kind"] == "process"


def test_r003_waiting_for_trigger_pause_is_covered_too() -> None:
    old = workflow(schema_version=2, status="SCOPING")
    paused = {
        **old,
        "status": "WAITING_FOR_TRIGGER",
        "next_owner": None,
        "next_action": None,
        "deferred_trigger": {"type": "x"},
    }
    assert "classification_pending" in str(classification_guard(old, paused))
    assert classification_guard(old, {**paused, "classification_pending": True}) is None


def test_r003_grandfathered_paused_wps_are_not_reclassified() -> None:
    legacy = workflow(schema_version=2, status="BLOCKED_FOR_OWNER", next_owner="Owner")  # no flag: pre-0.2.0
    resumed = {
        **legacy,
        "status": "CONTRACT_DRAFT",
        "next_owner": "Codex",
        "governance_source": {"artifact": "x"},
    }
    assert classification_guard(legacy, resumed) is None
    v1 = workflow(status="SCOPING")
    assert classification_guard(v1, {**v1, "status": "BLOCKED_FOR_OWNER", "next_owner": "Owner"}) is None
