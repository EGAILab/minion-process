"""Structural validation of a coordination-state `workflow` object (`coordination-state.md` §4-§9,
§13). It enforces workflow structure only; it never decides semantics (`agent-workflow.md` §12.6).

CE-PROC-L13-01 (agreed): every field the tool consumes has a shape rule here (the field table in
`assurance/process-ce-proc-l13-01.md`); a supplied malformed value is an error, never treated as
absent or rerouted to another form; containers are checked before their elements; and validation is
total -- it returns diagnostics and never raises, for any JSON-representable value."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .model import ACTIVE, NON_ACTIONABLE, OWNERS, STATUSES

SHA = re.compile(r"^[0-9a-f]{40}$")
FINDING_ID = re.compile(r"^[A-Z][A-Za-z0-9]*(-[A-Za-z0-9.]+)+$")
"""A finding ID such as `L13-WP132-I004` or `L0506-D001-RC001`."""
SCHEMA_VERSIONS = (1, 2)
RELATIONS = frozenset({"blocked_by", "independent_of", "shares_artifact"})
SIDES = ("code", "docs")

LEAN_BODY_CHARS = 8000
"""`coordination-state.md` §13: a current-state body above this is a lean-state warning."""

HISTORY_KEYS = ("remediations", "reviews", "review_history", "history_log")
"""Keys that carry history rather than current state (`coordination-state.md` §13)."""


@dataclass(frozen=True)
class Problem:
    level: str  # "error" | "warning"
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.level.upper()}: {self.path}: {self.message}"


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() in ("", "none", "null"))


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    """A GitHub issue/PR number: a positive integer."""
    return _is_int(value) and value >= 1


def _text(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _finding_id(value: Any) -> bool:
    return isinstance(value, str) and FINDING_ID.match(value) is not None


class _Checker:
    def __init__(self) -> None:
        self.problems: list[Problem] = []

    def error(self, path: str, message: str) -> None:
        self.problems.append(Problem("error", path, message))

    def warn(self, path: str, message: str) -> None:
        self.problems.append(Problem("warning", path, message))

    def optional_string(self, workflow: dict[str, Any], key: str) -> None:
        value = workflow.get(key)
        if value is not None and not isinstance(value, str):
            self.error(key, f"must be a string or null, got {type(value).__name__}")

    def id_list(self, path: str, value: Any, element_ok: Callable[[Any], bool], what: str) -> bool:
        """Container first, then every element; True when the list is well-formed."""
        if not isinstance(value, list):
            self.error(path, "must be a list")
            return False
        ok = True
        for index, item in enumerate(value):
            if not element_ok(item):
                self.error(f"{path}[{index}]", f"must be a {what}, got {item!r}")
                ok = False
        return ok


def validate_workflow(workflow: Any, body_chars: int | None = None) -> list[Problem]:
    """Every structural problem in `workflow`; errors block a state commit, warnings do not."""
    c = _Checker()
    if not isinstance(workflow, dict):
        c.error("workflow", f"must be a mapping, got {type(workflow).__name__}")
        return c.problems

    version = workflow.get("schema_version", 1)
    if not (_is_int(version) and version in SCHEMA_VERSIONS):
        c.error("schema_version", f"unsupported schema_version {version!r} (supported: {SCHEMA_VERSIONS})")
        return c.problems
    lean = version >= 2

    # identity and the plain control fields
    if not _text(workflow.get("work_package")):
        c.error("work_package", f"required non-empty string, got {workflow.get('work_package')!r}")
    for key in ("title", "layer", "next_owner", "next_action", "updated_by", "updated_reason"):
        c.optional_string(workflow, key)

    status = workflow.get("status")
    if not (isinstance(status, str) and status in STATUSES):
        c.error("status", f"unknown status {status!r} (allowed: {', '.join(STATUSES)})")
        return c.problems  # every rule below depends on a well-formed status

    owner, action = workflow.get("next_owner"), workflow.get("next_action")
    if status in ACTIVE:
        if _blank(owner):
            c.error("next_owner", f"active status {status} requires next_owner")
        elif not (isinstance(owner, str) and owner in OWNERS):
            c.error("next_owner", f"unknown owner {owner!r} (allowed: {', '.join(sorted(OWNERS))})")
        if _blank(action):
            c.error("next_action", f"active status {status} requires next_action")
    if status == "BLOCKED_FOR_OWNER" and owner != "Owner":
        c.error("next_owner", "BLOCKED_FOR_OWNER requires next_owner: Owner")

    for key in ("governance_source", "deferred_trigger"):
        value = workflow.get(key)
        if value is not None and not (isinstance(value, dict) or _text(value)):
            c.error(key, "must be a mapping, a non-empty string, or null (§11.10, §11.13)")
    if status == "WAITING_FOR_TRIGGER":
        if _blank(workflow.get("deferred_trigger")):
            c.error("deferred_trigger", "WAITING_FOR_TRIGGER requires deferred_trigger")
        if not _blank(owner) or not _blank(action):
            c.error("next_owner", "WAITING_FOR_TRIGGER requires next_owner/next_action null")

    _candidates(c, workflow)
    _convergence(c, workflow, status)
    _lists(c, workflow, lean)

    quarantine = workflow.get("quarantine")
    if quarantine is not None:
        if not isinstance(quarantine, dict):
            c.error("quarantine", "must be a mapping")
        else:
            flag = quarantine.get("derived_from_quarantined_artifact", False)
            if not isinstance(flag, bool):
                c.error("quarantine.derived_from_quarantined_artifact", f"must be a boolean, got {flag!r}")
            elif flag and status not in NON_ACTIONABLE:
                c.error("quarantine", "candidate derived from a quarantined artifact (§11.12)")

    if lean:
        _lean_extras(c, workflow)

    for key in HISTORY_KEYS:
        if key in workflow or any(isinstance(v, dict) and key in v for v in workflow.values()):
            c.warn(key, "history belongs in assurance/comments; reference it via history.assurance_index")
    if body_chars is not None and body_chars > LEAN_BODY_CHARS:
        c.warn("body", f"{body_chars} characters exceeds the lean current-state budget {LEAN_BODY_CHARS}")
    return c.problems


def _candidates(c: _Checker, workflow: dict[str, Any]) -> None:
    if "current_candidate" in workflow:
        current = workflow["current_candidate"]
        if any(side in workflow for side in SIDES):
            c.error("current_candidate", "mixes the v2 `current_candidate` with v1 top-level `code`/`docs`")
        if not isinstance(current, dict):
            c.error("current_candidate", f"must be a mapping, got {type(current).__name__}")
            return
        extra = sorted(str(key) for key in current if key not in SIDES)
        if extra:
            c.error("current_candidate", f"unknown keys {extra} (allowed: code, docs)")
        entries, prefix = current, "current_candidate."
    else:
        entries, prefix = workflow, ""
    for side in SIDES:
        entry = entries.get(side)
        path = prefix + side
        if entry is None:
            continue  # this side has no candidate
        if not isinstance(entry, dict):
            c.error(path, f"must be a mapping or null, got {type(entry).__name__}")
            continue
        sha, pr, merged = entry.get("sha"), entry.get("pr"), entry.get("merged_sha")
        if sha is not None and not (isinstance(sha, str) and SHA.match(sha)):
            c.error(f"{path}.sha", f"not a full 40-hex SHA: {sha!r}")
        if pr is not None and not _is_number(pr):
            c.error(f"{path}.pr", f"PR must be a positive integer, got {pr!r}")
        if merged is not None and not (isinstance(merged, str) and SHA.match(merged)):
            c.error(f"{path}.merged_sha", f"not a full 40-hex SHA: {merged!r}")
        if (pr is not None or merged is not None) and sha is None:
            c.error(f"{path}.sha", "a PR or merged reference requires the exact candidate SHA (§5)")
        if merged is not None and pr is None:
            c.error(
                f"{path}.merged_sha",
                "a merged baseline requires its PR (`pr`); no other baseline form exists",
            )
        base = entry.get("base")
        if base is not None and not isinstance(base, str):
            c.error(f"{path}.base", "must be a string")


def _convergence(c: _Checker, workflow: dict[str, Any], status: str) -> None:
    convergence = workflow.get("convergence")
    if convergence is None:
        if status == "CONTRACT_CONVERGENCE":
            c.error("convergence.episode", "CONTRACT_CONVERGENCE requires convergence.episode")
        return
    if not isinstance(convergence, dict):
        c.error("convergence", f"must be a mapping, got {type(convergence).__name__}")
        return
    episode = convergence.get("episode")
    if episode is not None and not _text(episode):
        c.error("convergence.episode", f"must be a non-empty string, got {episode!r}")
    elif episode is None and status == "CONTRACT_CONVERGENCE":
        c.error("convergence.episode", "CONTRACT_CONVERGENCE requires convergence.episode")
    checkpoint = convergence.get("checkpoint")
    if checkpoint is not None and not isinstance(checkpoint, str):
        c.error("convergence.checkpoint", "must be a string")
    if "open_findings" in convergence:
        findings = convergence["open_findings"]
        well_formed = c.id_list("convergence.open_findings", findings, _finding_id, "finding ID string")
        if well_formed and status == "FINAL_CONTRACT_REVIEW" and findings:
            c.error(
                "convergence.open_findings",
                "FINAL_CONTRACT_REVIEW with open convergence findings: " + ", ".join(findings),
            )
    if "provisionally_closed" in convergence:
        c.id_list(
            "convergence.provisionally_closed",
            convergence["provisionally_closed"],
            lambda item: _finding_id(item) or (isinstance(item, dict) and _finding_id(item.get("finding"))),
            "finding ID or a mapping with a `finding` ID (§6)",
        )


def _lists(c: _Checker, workflow: dict[str, Any], lean: bool) -> None:
    if workflow.get("requirements") is not None:
        c.id_list(
            "requirements",
            workflow["requirements"],
            lambda item: isinstance(item, str),
            "requirement ID string",
        )
    for key in ("open_findings", "provisionally_closed"):
        value = workflow.get(key)
        if value is None:
            continue
        if isinstance(value, dict) and not lean:
            if all(_finding_id(k) for k in value):
                c.warn(
                    key, "legacy v1 mapping form; schema v2 uses a list of finding IDs (details in assurance)"
                )
            else:
                c.error(key, "legacy v1 mapping keys must be finding IDs")
            continue
        c.id_list(key, value, _finding_id, "finding ID string")


def _lean_extras(c: _Checker, workflow: dict[str, Any]) -> None:
    dependencies = workflow.get("dependencies")
    if dependencies is not None:
        if not isinstance(dependencies, dict):
            c.error("dependencies", "must be a mapping of name -> {issue, relation}")
        else:
            for name, edge in dependencies.items():
                path = f"dependencies.{name}"
                if not isinstance(edge, dict):
                    c.error(path, "must be a mapping {issue, relation}")
                    continue
                if not _is_number(edge.get("issue")):
                    c.error(f"{path}.issue", f"must be an issue number, got {edge.get('issue')!r}")
                relation = edge.get("relation")
                if not (isinstance(relation, str) and relation in RELATIONS):
                    c.error(f"{path}.relation", f"must be one of {sorted(RELATIONS)}, got {relation!r}")
    history = workflow.get("history")
    if history is not None:
        if not isinstance(history, dict):
            c.error("history", "must be a mapping")
        elif history.get("assurance_index") is not None and not isinstance(history["assurance_index"], str):
            c.error("history.assurance_index", "must be a string")


def errors(problems: list[Problem]) -> list[Problem]:
    return [p for p in problems if p.level == "error"]
