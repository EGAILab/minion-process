"""Witnesses for Codex's re-review of kit 0.2.0 (`PROC-KIT-P2-R003` refined): a schema-version rollback
cannot launder a newly opened v2 work package into the legacy intake exemption. Real `commit_state`,
fake remote, zero-write assertions, forward-upgrade and genuine-legacy positive controls."""

from __future__ import annotations

import pytest

from minion_process.ops import CheckFailed, classification_guard, commit_state

from .test_classification_review1 import patch, remote, setup
from .test_minion_process import CODE, workflow


def test_simultaneous_rollback_out_of_scoping_is_refused_with_zero_writes() -> None:
    f, gh = setup(workflow(schema_version=2, status="SCOPING", code=None, docs=None))
    with pytest.raises(CheckFailed, match="rolled back"):
        commit_state(
            gh, CODE, 10, patch(schema_version=1, status="CONTRACT_DRAFT"), {"schema_version", "status"}
        )
    assert f.edits == 0 and remote(f)["schema_version"] == 2


def test_two_step_rollback_is_refused_at_the_first_step() -> None:
    f, gh = setup(workflow(schema_version=2, status="SCOPING", code=None, docs=None))
    with pytest.raises(CheckFailed, match="rolled back"):
        commit_state(gh, CODE, 10, patch(schema_version=1), {"schema_version"})
    assert f.edits == 0
    old = workflow(schema_version=2, status="SCOPING")
    assert "rolled back" in str(
        classification_guard(old, {**old, "schema_version": 1, "status": "CONTRACT_DRAFT"})
    )
    assert "rolled back" in str(classification_guard(old, {**old, "schema_version": 1}))


def test_forward_upgrade_and_genuine_legacy_stay_valid() -> None:
    f, gh = setup(workflow(status="SCOPING", code=None, docs=None))  # a genuine schema-v1 record
    commit_state(gh, CODE, 10, patch(status="CONTRACT_DRAFT"), {"status"})  # legacy intake needs no class
    assert f.edits == 1
    commit_state(gh, CODE, 10, patch(schema_version=2), {"schema_version"})  # forward upgrade is allowed
    assert f.edits == 2 and remote(f)["schema_version"] == 2


def test_a_record_upgraded_to_v2_in_scoping_takes_the_v2_intake_rule() -> None:
    old = workflow(status="SCOPING")
    assert "intake requires classification" in str(
        classification_guard(old, {**old, "schema_version": 2, "status": "CONTRACT_DRAFT"})
    )
    classified = {
        **old,
        "schema_version": 2,
        "status": "CONTRACT_DRAFT",
        "kind": "process",
        "consequence": {"class": "mechanical", "rule": "CP-0"},
        "requirements": [],
    }
    assert classification_guard(old, classified) is None
