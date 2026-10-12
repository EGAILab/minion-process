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

KINDS = ("semantic", "delta", "process", "scoping", "status")
"""Work-package kinds (`coordination-state.md` §14, kit 0.2.0; Owner decision 2 of 2026-10-11)."""
CLASSES = ("governing", "mechanical")
"""Consequence classes (`consequence-classes.md`). The class, not the kind, selects the route."""
GOVERNING_KINDS = frozenset({"semantic", "delta"})
"""Kinds that are governing by definition."""
SCOPE_FREE_KINDS = frozenset({"process", "scoping", "status"})
"""Kinds with no product requirement: `requirements` must be an explicit `[]`."""
SCOPING_STATES = frozenset({"SCOPING", "BLOCKED_FOR_OWNER", "CLOSED", "INCIDENT", "INVALID_UNAUTHORIZED"})
"""The only states a `scoping` WP may be in (`coordination-state.md` §10.3)."""
PREDICATE_ID = re.compile(r"^CP-[0-6]$")
"""A consequence predicate id: CP-0 (none applies) or CP-1..CP-6 (`consequence-classes.md`)."""
SKIP_RULE = re.compile(r"^SK-[0-9]+$")
ROUTE_RULE = re.compile(r"^RT-[1-6]$")
"""A delegated route id (`routing.md`; `minion-agent#75` Amendment 2)."""


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
    _classification(c, workflow, status, lean)

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


def _classification(c: _Checker, workflow: dict[str, Any], status: str, lean: bool) -> None:
    """`kind`, `consequence`, `skipped` and `history.routes` (`coordination-state.md` §14, kit 0.2.0).

    All four are optional in the state shape, so work packages opened before kit 0.2.0 stay valid; the
    `apply` guard (`ops.classification_guard`) requires `kind` and `consequence` from intake on. Presence
    is decided by the key, not by truthiness: a supplied `null` is a malformed value and an error, never
    absence (`PROC-KIT-P2-R002`)."""
    kind: Any = None
    if "kind" in workflow:
        kind = workflow["kind"]
        if not (isinstance(kind, str) and kind in KINDS):
            c.error("kind", f"must be one of {', '.join(KINDS)}, got {kind!r}")
            kind = None
    klass: str | None = None
    if "consequence" in workflow:
        consequence = workflow["consequence"]
        if not isinstance(consequence, dict):
            c.error("consequence", f"must be a mapping, got {type(consequence).__name__}")
        else:
            klass = _consequence(c, consequence)
    if "classification_pending" in workflow:
        pending = workflow["classification_pending"]
        if not isinstance(pending, bool):
            c.error("classification_pending", f"must be a boolean, got {pending!r}")
        elif pending and ("kind" in workflow or "consequence" in workflow):
            c.error(
                "classification_pending", "a classified WP is not pending classification; drop the flag (§14)"
            )
    if lean and "kind" not in workflow and "consequence" not in workflow:
        c.warn("kind", "kind and consequence not recorded; kit 0.2.0 classifies every WP at intake (§14)")

    if kind in GOVERNING_KINDS and klass == "mechanical":
        c.error("consequence.class", f"a {kind} WP is governing by definition (§14)")
    if kind in SCOPE_FREE_KINDS and workflow.get("requirements") not in ([], None):
        c.error("requirements", f"a {kind} WP owns no product requirement: requirements must be [] (§14)")
    if kind in GOVERNING_KINDS and workflow.get("requirements") == []:
        c.error("requirements", f"a {kind} WP owns product requirements: requirements must not be [] (§14)")
    if kind == "scoping" and status not in SCOPING_STATES:
        c.error("status", f"a scoping WP never enters {status}; it closes from SCOPING (§10.3, §14)")
    if klass == "mechanical" and status == "CONTRACT_CONVERGENCE":
        c.error(
            "consequence.class",
            "a mechanical WP has no convergence; a firing trigger upgrades the class (§14)",
        )

    if "skipped" in workflow:
        skipped = workflow["skipped"]
        if not isinstance(skipped, list):
            c.error("skipped", "must be a list of {stage, rule, measured_rows, reviewer}")
        else:
            if skipped and klass != "mechanical":
                c.error(
                    "skipped",
                    "a stage is skipped only on a WP classified mechanical; never on a governing or "
                    "unclassified one (§14, record §6.3)",
                )
            for i, entry in enumerate(skipped):
                _skip(c, f"skipped[{i}]", entry)

    history = workflow.get("history")
    if isinstance(history, dict) and "routes" in history:
        routes = history["routes"]
        if not isinstance(routes, list):
            c.error("history.routes", "must be a list of {rule, at, reason}")
        else:
            for i, entry in enumerate(routes):
                _route(c, f"history.routes[{i}]", entry)


def _consequence(c: _Checker, consequence: dict[str, Any]) -> str | None:
    klass = consequence.get("class")
    if not (isinstance(klass, str) and klass in CLASSES):
        c.error("consequence.class", f"must be one of {', '.join(CLASSES)}, got {klass!r}")
        klass = None
    rule = consequence.get("rule")
    if not (isinstance(rule, str) and (PREDICATE_ID.match(rule) or _finding_id(rule))):
        c.error(
            "consequence.rule", f"must be a predicate id CP-0..CP-6 or the upgrading finding ID, got {rule!r}"
        )
    elif klass == "mechanical" and not PREDICATE_ID.match(rule):
        c.error(
            "consequence.rule", "a finding ID as rule records an upgrade; the class is then governing (§14)"
        )
    elif klass == "mechanical" and rule != "CP-0":
        c.error("consequence.rule", f"{rule} is a governing predicate; a mechanical WP records CP-0 (§14)")
    elif klass == "governing" and rule == "CP-0":
        c.error(
            "consequence.rule",
            "CP-0 means no predicate applies; a governing WP names its predicate or finding",
        )
    for key in ("confirmed_by",):
        if key in consequence and not _text(consequence[key]):
            c.error(f"consequence.{key}", "must be a non-empty string")
    if "upgraded_by" in consequence:
        c.id_list("consequence.upgraded_by", consequence["upgraded_by"], _finding_id, "finding ID string")
    if "downgrade" in consequence:
        downgrade = consequence["downgrade"]
        if not isinstance(downgrade, dict):
            c.error("consequence.downgrade", "must be a mapping {owner_decision, reviewer}")
        else:
            for key in ("owner_decision", "reviewer"):
                if not _text(downgrade.get(key)):
                    c.error(f"consequence.downgrade.{key}", "required non-empty string (Owner-only item 11)")
    extra = sorted(set(consequence) - {"class", "rule", "confirmed_by", "upgraded_by", "downgrade"})
    if extra:
        c.error("consequence", f"unknown keys {extra}")
    return klass


def _skip(c: _Checker, path: str, entry: Any) -> None:
    if not isinstance(entry, dict):
        c.error(path, "must be a mapping {stage, rule, measured_rows, reviewer}")
        return
    if not _text(entry.get("stage")):
        c.error(f"{path}.stage", "required non-empty string")
    elif entry["stage"] == "FINAL_CONTRACT_REVIEW":
        c.error(f"{path}.stage", "the final complete review is never skipped (§14, record §6.3)")
    rule = entry.get("rule")
    if not (isinstance(rule, str) and SKIP_RULE.match(rule)):
        c.error(f"{path}.rule", f"must be a skip rule id SK-n, got {rule!r}")
    rows = entry.get("measured_rows")
    if not (isinstance(rows, list) and rows and all(_text(r) for r in rows)):
        c.error(
            f"{path}.measured_rows",
            "required non-empty list of feasibility rows measured against the authority",
        )
    if not _text(entry.get("reviewer")):
        c.error(f"{path}.reviewer", "required: the reviewer who consented to the skip in a review record")


def _route(c: _Checker, path: str, entry: Any) -> None:
    if not isinstance(entry, dict):
        c.error(path, "must be a mapping {rule, at, reason}")
        return
    rule = entry.get("rule")
    if not (isinstance(rule, str) and ROUTE_RULE.match(rule)):
        c.error(f"{path}.rule", f"must be a delegated route id RT-1..RT-6, got {rule!r}")
    for key in ("at", "reason"):
        if not _text(entry.get(key)):
            c.error(f"{path}.{key}", "required non-empty string")


def errors(problems: list[Problem]) -> list[Problem]:
    return [p for p in problems if p.level == "error"]
