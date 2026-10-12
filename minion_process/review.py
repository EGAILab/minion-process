"""Structured review records (`templates/review-record.md`, record §6.6; kit 0.3.0).

A review record carries one fenced YAML block whose top-level key is `review:`; the prose stays below
it. The tool reads these headers from the published verdicts (comments on the coordination issue and
on the candidate PRs) to compute the §11.8 convergence counters and the §14.6 metrics. It never writes
a verdict and never decides semantics: the labels are the recorded verdicts and negative controls.

Validation is total (diagnostics, never a raise) and fails closed (unknown keys and malformed values are
errors). Presence is decided by the key, never by truthiness."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import yaml

from .profile import TAXONOMY
from .validate import FINDING_ID, SHA, Problem, _finding_id, _text

REVIEW_TYPES = (
    "CONTRACT_REVIEW",
    "IMPLEMENTATION_REVIEW",
    "TARGETED_CLOSURE",
    "CHECKPOINT",
    "FINAL_REVIEW",
    "CLOSURE_REVIEW",
    "PROCESS_REVIEW",
)
VERDICTS = ("APPROVED", "CHANGES_REQUESTED", "HANDOFF_BLOCKED")
TIERS = ("G0", "G1", "G2", "G3", "none")
CLASS_OUTCOMES = ("CONFIRMED", "CORRECTED")
ALIAS = re.compile(r"^[A-Z][A-Z0-9_]*$")
NOT_APPLICABLE = "NOT_APPLICABLE"
FENCE = re.compile(r"```ya?ml[ \t]*\r?\n(.*?)\r?\n```", re.DOTALL)
"""Every fenced YAML block; `REVIEW_BLOCK` then decides which ones claim to be review headers."""
REVIEW_BLOCK = re.compile(r"\A\s*review\s*:")
"""A block whose first key is `review`, however its value is written (nested, inline, null)."""

TOP_REQUIRED = (
    "schema_version",
    "wp",
    "type",
    "complete",
    "reviewer",
    "author",
    "candidate",
    "verdict",
    "new_evidence",
    "findings",
    "closed",
)
TOP_OPTIONAL = ("gate_tier_verified", "class_confirmation")


class _Check:
    def __init__(self) -> None:
        self.problems: list[Problem] = []

    def error(self, path: str, message: str) -> None:
        self.problems.append(Problem("error", path, message))


def parse_review_records(text: str) -> list[Any]:
    """Every `review:` header found in `text`, as loaded YAML (any value; validation decides shape).
    A block that is not valid YAML is returned as the string `"<unparsable>"` so it is counted and
    reported, never silently dropped."""
    found: list[Any] = []
    for match in FENCE.finditer(text):
        block = match.group(1)
        if not REVIEW_BLOCK.match(block):
            continue  # an ordinary YAML block (a state block, an example): not a review header
        try:
            found.append(yaml.safe_load(block))
        except Exception:  # totality: a bad block is a diagnostic, never a traceback
            found.append("<unparsable>")
    return found


def _unknown(keys: Any, allowed: set[str]) -> list[str]:
    """Unknown keys as sorted strings; any YAML key type is tolerated (R003)."""
    return sorted(str(k) for k in keys if k not in allowed)


def validate_review(record: Any) -> list[Problem]:
    """Every rule of the review header. Returns diagnostics; never raises."""
    c = _Check()
    if not isinstance(record, dict) or set(record) != {"review"}:
        c.error("review", "a review record is one mapping with the single top-level key `review`")
        return c.problems
    r = record["review"]
    if not isinstance(r, dict):
        c.error("review", f"must be a mapping, got {type(r).__name__}")
        return c.problems
    for key in TOP_REQUIRED:
        if key not in r:
            c.error(f"review.{key}", "required")
    extra = _unknown(r, set(TOP_REQUIRED) | set(TOP_OPTIONAL))
    if extra:
        c.error("review", f"unknown keys {extra}")
    version = r.get("schema_version")
    if "schema_version" in r and (not isinstance(version, int) or isinstance(version, bool) or version != 1):
        c.error(
            "review.schema_version",
            f"unsupported review schema_version {r['schema_version']!r} (supported: 1)",
        )
    if "wp" in r and not _text(r["wp"]):
        c.error("review.wp", "must be a non-empty string")
    if "type" in r and r["type"] not in REVIEW_TYPES:
        c.error("review.type", f"must be one of {', '.join(REVIEW_TYPES)}, got {r['type']!r}")
    for key in ("complete", "new_evidence"):
        if key in r and not isinstance(r[key], bool):
            c.error(f"review.{key}", f"must be a boolean, got {r[key]!r}")
    for key in ("reviewer", "author"):
        if key in r and not _text(r[key]):
            c.error(f"review.{key}", "must be a non-empty string")
    reviewer, author = r.get("reviewer"), r.get("author")
    if (
        isinstance(reviewer, str)
        and isinstance(author, str)
        and _text(reviewer)
        and _text(author)
        and reviewer.strip().lower() == author.strip().lower()
    ):
        c.error("review.reviewer", "the reviewer must differ from the candidate's author (independence)")
    if "candidate" in r:
        _candidate(c, r["candidate"])
    if "gate_tier_verified" in r and r["gate_tier_verified"] not in TIERS:
        c.error(
            "review.gate_tier_verified", f"must be one of {', '.join(TIERS)}, got {r['gate_tier_verified']!r}"
        )
    if "class_confirmation" in r:
        _class_confirmation(c, r["class_confirmation"])
    verdict = r.get("verdict")
    if "verdict" in r and verdict not in VERDICTS:
        c.error("review.verdict", f"must be one of {', '.join(VERDICTS)}, got {verdict!r}")
    blocking = _findings(c, r["findings"]) if "findings" in r else 0
    if "closed" in r:
        _closed(c, r["closed"])
    if verdict == "APPROVED" and blocking:
        c.error(
            "review.verdict",
            f"APPROVED with {blocking} blocking finding(s): a blocking finding is a rejection",
        )
    if verdict == "HANDOFF_BLOCKED" and isinstance(r.get("findings"), list) and r["findings"]:
        c.error(
            "review.findings", "HANDOFF_BLOCKED is not a verdict on the candidate; it carries no findings"
        )
    return c.problems


def _candidate(c: _Check, candidate: Any) -> None:
    if not isinstance(candidate, dict) or not candidate:
        c.error("review.candidate", "must be a non-empty mapping of side -> 40-hex SHA")
        return
    for side, sha in candidate.items():
        if not (isinstance(side, str) and _text(side)):
            c.error("review.candidate", "sides must be non-empty strings")
        elif not (isinstance(sha, str) and SHA.match(sha)):
            c.error(f"review.candidate.{side}", f"not a full 40-hex SHA: {sha!r}")


def _class_confirmation(c: _Check, cc: Any) -> None:
    if not isinstance(cc, dict):
        c.error("review.class_confirmation", "must be a mapping {kind, class, rule, outcome}")
        return
    for key in ("kind", "class", "rule"):
        if not _text(cc.get(key)):
            c.error(f"review.class_confirmation.{key}", "required non-empty string")
    if cc.get("outcome") not in CLASS_OUTCOMES:
        c.error(
            "review.class_confirmation.outcome",
            f"must be one of {', '.join(CLASS_OUTCOMES)}, got {cc.get('outcome')!r}",
        )
    extra = _unknown(cc, {"kind", "class", "rule", "outcome"})
    if extra:
        c.error("review.class_confirmation", f"unknown keys {extra}")


def _findings(c: _Check, findings: Any) -> int:
    """Validates the findings list and returns the number of blocking findings."""
    if not isinstance(findings, list):
        c.error("review.findings", "must be a list of {id, class, blocking, surface?, witness?}")
        return 0
    blocking = 0
    seen: set[str] = set()
    for i, f in enumerate(findings):
        path = f"review.findings[{i}]"
        if not isinstance(f, dict):
            c.error(path, "must be a mapping {id, class, blocking, surface?, witness?}")
            continue
        if not _finding_id(f.get("id")):
            c.error(f"{path}.id", f"must be a finding ID, got {f.get('id')!r}")
        elif f["id"] in seen:
            c.error(f"{path}.id", f"duplicate finding {f['id']}")
        else:
            seen.add(f["id"])
        klass = f.get("class")
        if not (isinstance(klass, str) and (klass in TAXONOMY or ALIAS.match(klass))):
            c.error(f"{path}.class", f"must be a taxonomy class or a profile alias, got {klass!r}")
        if not isinstance(f.get("blocking"), bool):
            c.error(f"{path}.blocking", f"must be a boolean, got {f.get('blocking')!r}")
        elif f["blocking"]:
            blocking += 1
        for key in ("surface", "witness"):
            if key in f and not _text(f[key]):
                c.error(f"{path}.{key}", "must be a non-empty string when present")
        extra = _unknown(f, {"id", "class", "blocking", "surface", "witness"})
        if extra:
            c.error(path, f"unknown keys {extra}")
    return blocking


def _closed(c: _Check, closed: Any) -> None:
    if not isinstance(closed, list):
        c.error("review.closed", "must be a list of {id, negative_control, reason?}")
        return
    for i, entry in enumerate(closed):
        path = f"review.closed[{i}]"
        if not isinstance(entry, dict):
            c.error(path, "must be a mapping {id, negative_control, reason?} (§11.8.7.1)")
            continue
        if not _finding_id(entry.get("id")):
            c.error(f"{path}.id", f"must be a finding ID, got {entry.get('id')!r}")
        control = entry.get("negative_control")
        if not (isinstance(control, str) and _text(control)):
            c.error(
                f"{path}.negative_control",
                "required: the known-bad method, or NOT_APPLICABLE with a reason",
            )
        elif control.strip() == NOT_APPLICABLE and not _text(entry.get("reason")):
            c.error(f"{path}.reason", "NOT_APPLICABLE requires the reason (documentary/traceability-only)")
        extra = _unknown(entry, {"id", "negative_control", "reason"})
        if extra:
            c.error(path, f"unknown keys {extra}")


# --- counters and metrics ---------------------------------------------------------------------------


@dataclass
class Counters:
    """The §11.8 triggers from the recorded reviews of one work package."""

    reviews: int = 0
    survived: dict[str, int] = field(default_factory=dict)  # blocking finding id -> reviews it survived
    successors: dict[str, list[str]] = field(default_factory=dict)  # surface -> distinct blocking ids
    rejected_complete: int = 0
    rounds_without_new_evidence: int = 0
    consecutive_without_new_evidence: int = 0
    invalid: int = 0
    duplicates: int = 0

    @property
    def a_fired(self) -> list[str]:
        return sorted(f for f, n in self.survived.items() if n >= 2)

    @property
    def b_fired(self) -> list[str]:
        return sorted(s for s, ids in self.successors.items() if len(ids) >= 2)

    @property
    def c_fired(self) -> bool:
        return self.rejected_complete >= 3


def select_reviews(records: list[Any], wp: str) -> tuple[list[dict[str, Any]], int, int]:
    """The valid, distinct review headers for `wp`, in the order given; the number of invalid headers
    seen; and the number of transport copies ignored. One review event is routinely published verbatim
    on the coordination issue and on each candidate PR: identical headers are one event, counted once
    (`PROC-KIT-P3-R001`). Two headers differ in any field are two events."""
    valid: list[dict[str, Any]] = []
    seen: set[str] = set()
    invalid = duplicates = 0
    for record in records:
        if validate_review(record):
            invalid += 1
            continue
        review = record["review"]
        if review["wp"] != wp:
            continue
        key = json.dumps(review, sort_keys=True, default=str)
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        valid.append(review)
    return valid, invalid, duplicates


def counters(reviews: list[dict[str, Any]], invalid: int = 0, duplicates: int = 0) -> Counters:
    k = Counters(reviews=len(reviews), invalid=invalid, duplicates=duplicates)
    streak = 0
    for r in reviews:
        if r["verdict"] == "HANDOFF_BLOCKED":
            continue  # not a review of the candidate (§11.11)
        for f in r["findings"]:
            if f["blocking"]:
                k.survived[f["id"]] = k.survived.get(f["id"], 0) + 1
                if f.get("surface"):
                    ids = k.successors.setdefault(f["surface"], [])
                    if f["id"] not in ids:
                        ids.append(f["id"])
        if r["complete"] and r["verdict"] == "CHANGES_REQUESTED":
            k.rejected_complete += 1
        if r["verdict"] == "CHANGES_REQUESTED" and not r["new_evidence"]:
            k.rounds_without_new_evidence += 1
            streak += 1
        else:
            streak = 0
        k.consecutive_without_new_evidence = max(k.consecutive_without_new_evidence, streak)
    return k


def trigger_statement(k: Counters) -> str:
    """The mandatory §11.8 trigger statement, from recorded evidence only."""
    ignored = f"; {k.invalid} invalid header(s) ignored" if k.invalid else ""
    copies = f"; {k.duplicates} transport cop{'y' if k.duplicates == 1 else 'ies'} of the same event ignored"
    lines = [f"{k.reviews} distinct review event(s) read{ignored}{copies if k.duplicates else ''}"]
    if k.a_fired:
        lines.append(f"Trigger A HAS FIRED: {', '.join(k.a_fired)} survived two or more independent reviews.")
    else:
        worst = max(k.survived.values(), default=0)
        lines.append(f"Trigger A has not fired: no blocking finding survived two reviews (max {worst}).")
    if k.b_fired:
        parts = [f"{s} ({', '.join(k.successors[s])})" for s in k.b_fired]
        lines.append(f"Trigger B HAS FIRED: successor findings on the same surface: {'; '.join(parts)}.")
    else:
        lines.append("Trigger B has not fired: no root-cause surface has two distinct blocking findings.")
    if k.c_fired:
        lines.append(f"Trigger C HAS FIRED: {k.rejected_complete} rejected complete reviews.")
    else:
        lines.append(f"Trigger C has not fired: {k.rejected_complete} rejected complete review(s).")
    lines.append(
        f"Rounds without new discriminating evidence: {k.rounds_without_new_evidence} "
        f"(longest streak {k.consecutive_without_new_evidence})."
    )
    fired = bool(k.a_fired or k.b_fired or k.c_fired)
    lines.append(
        "CONVERGENCE TRIGGER FIRED: enter CONTRACT_CONVERGENCE, or state why a single targeted fix closes "
        "the surface (routing.md RT-6 where routing is delegated)."
        if fired
        else "No trigger fired. Proceeding with ordinary remediation is permitted."
    )
    return "\n".join(lines)


def metrics(
    workflow: dict[str, Any], reviews: list[dict[str, Any]], invalid: int = 0, duplicates: int = 0
) -> dict[str, Any]:
    """The §14.6 metrics available from the state block and the recorded reviews."""
    k = counters(reviews, invalid, duplicates)
    by_class: Counter[str] = Counter()
    by_tier: Counter[str] = Counter()
    closed_nc = closed_na = 0
    for r in reviews:
        by_tier[str(r.get("gate_tier_verified", "none"))] += 1
        for f in r["findings"]:
            by_class[f["class"]] += 1
        for entry in r["closed"]:
            if entry["negative_control"].strip() == NOT_APPLICABLE:
                closed_na += 1
            else:
                closed_nc += 1
    history: dict[str, Any] = workflow["history"] if isinstance(workflow.get("history"), dict) else {}
    routes: list[Any] = history["routes"] if isinstance(history.get("routes"), list) else []
    route_ids = [r.get("rule") for r in routes if isinstance(r, dict)]
    consequence: dict[str, Any] = (
        workflow["consequence"] if isinstance(workflow.get("consequence"), dict) else {}
    )
    return {
        "work_package": workflow.get("work_package"),
        "kind": workflow.get("kind"),
        "class": consequence.get("class"),
        "status": workflow.get("status"),
        "review_events": k.reviews,
        "complete_reviews": sum(1 for r in reviews if r["complete"]),
        "targeted_reviews": sum(1 for r in reviews if not r["complete"]),
        "approvals": sum(1 for r in reviews if r["verdict"] == "APPROVED"),
        "rejected_complete_reviews": k.rejected_complete,
        "handoff_blocked": sum(1 for r in reviews if r["verdict"] == "HANDOFF_BLOCKED"),
        "rounds_without_new_evidence": k.rounds_without_new_evidence,
        "longest_streak_without_new_evidence": k.consecutive_without_new_evidence,
        "findings_recorded": sum(len(r["findings"]) for r in reviews),
        "findings_by_class": dict(sorted(by_class.items())),
        "closed_with_negative_control": closed_nc,
        "closed_documentary": closed_na,
        "gate_tiers_verified": dict(sorted(by_tier.items())),
        "routes_taken": sorted(Counter(str(r) for r in route_ids).items()),
        "owner_questions_routed": sum(1 for r in route_ids if r in ("RT-4", "RT-6")),
        "triggers": {"A": k.a_fired, "B": k.b_fired, "C": k.c_fired},
        "invalid_review_headers": invalid,
        "transport_copies_ignored": duplicates,
    }


__all__ = [
    "FINDING_ID",
    "Counters",
    "counters",
    "metrics",
    "parse_review_records",
    "select_reviews",
    "trigger_statement",
    "validate_review",
]
