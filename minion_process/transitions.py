"""Legal workflow transitions (`coordination-state.md` §10, as reconciled in §10.1).

The table is data: the tool decides only whether a transition is mechanically legal, never whether
the semantic work behind it is done."""

from __future__ import annotations

from .model import ACTIVE, STATUSES

LEGAL: dict[str, frozenset[str]] = {
    "SCOPING": frozenset(
        {
            "CONTRACT_DRAFT",
            "WAITING_FOR_TRIGGER",
            "CLOSED",  # a scoping-only WP, scoping approved and merged (§10.3; ops guard)
        }
    ),
    "CONTRACT_DRAFT": frozenset({"CONTRACT_REVIEW"}),
    "CONTRACT_REVIEW": frozenset(
        {
            "PYTHON_IMPLEMENTATION",  # clean contract checkpoint
            "CONTRACT_DRAFT",  # contract findings: remediate the draft
            "FINAL_CONTRACT_REVIEW",  # contract-phase targeted closure done (§10.1)
            "CONTRACT_CONVERGENCE",
        }
    ),
    "PYTHON_IMPLEMENTATION": frozenset({"IMPLEMENTATION_REVIEW"}),
    "IMPLEMENTATION_REVIEW": frozenset(
        {
            "RUST_IMPLEMENTATION",  # clean first review; merge is part of this transition
            "FINAL_CONTRACT_REVIEW",  # this review was a targeted re-review of a remediated candidate
            "REMEDIATION",
            "CONTRACT_CONVERGENCE",
        }
    ),
    "REMEDIATION": frozenset({"IMPLEMENTATION_REVIEW", "CONTRACT_CONVERGENCE"}),
    "CONTRACT_CONVERGENCE": frozenset({"FINAL_CONTRACT_REVIEW"}),
    "FINAL_CONTRACT_REVIEW": frozenset(
        {
            "RUST_IMPLEMENTATION",
            "REMEDIATION",
            "CONTRACT_CONVERGENCE",
            "PYTHON_IMPLEMENTATION",  # contract-phase final review approved (§10.1)
            "CONTRACT_DRAFT",  # contract-phase final review rejected (§10.1)
            "CLOSED",  # a process-only WP, final review approved and merged (§10.2; ops guard)
        }
    ),
    "RUST_IMPLEMENTATION": frozenset({"CLOSURE_REVIEW"}),
    "CLOSURE_REVIEW": frozenset({"CLOSED", "RUST_IMPLEMENTATION"}),
    "WAITING_FOR_TRIGGER": frozenset({"SCOPING"}),
    "BLOCKED_FOR_OWNER": frozenset(ACTIVE - {"BLOCKED_FOR_OWNER"}),
    "CLOSED": frozenset(),
    "INCIDENT": frozenset(),
    "INVALID_UNAUTHORIZED": frozenset(),
}
"""Every active state may also go to `BLOCKED_FOR_OWNER` (§10.1): governance can arise anywhere.
`BLOCKED_FOR_OWNER` may return to any active state the governance source authorizes; the tool
cannot check that authorization's content, only that a `governance_source` is recorded."""

assert set(LEGAL) == set(STATUSES)


def check_transition(old: str, new: str) -> str | None:
    """None when `old -> new` is legal (or unchanged); otherwise the reason it is not."""
    if new not in LEGAL:
        return f"unknown status {new!r}"
    if old not in LEGAL:
        return f"unknown current status {old!r}"
    if old == new:
        return None
    if new == "BLOCKED_FOR_OWNER" and old in ACTIVE:
        return None
    if new in LEGAL[old]:
        return None
    allowed = sorted(LEGAL[old] | ({"BLOCKED_FOR_OWNER"} if old in ACTIVE else set()))
    return f"illegal transition {old} -> {new}; legal from {old}: {', '.join(allowed) or 'none'}"
