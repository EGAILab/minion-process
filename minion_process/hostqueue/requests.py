"""Request shapes, checked before dispatch (K-44, PROC-KIT-P3B-R010).

`malformed` is total over JSON values: for any decoded value it returns None (well formed) or the reason,
and it never raises. It checks, in this order:

1. the top level is an object;
2. the discriminator `type` is present and a string;
3. every field the handler for that type reads has the kind the handler expects, including nested fields.

A malformed request is moved to `rejected/` with its reason. No handler runs. A string `type` the broker
does not know is not malformed: the dispatcher answers it with an ordinary refusal. Only field kinds are
checked here. Every semantic decision (does the job exist, is the policy valid) stays with the handler,
and a fault raised outside this function is a broker fault, never counted as malformed input.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _optional_string(r: dict[str, Any], key: str) -> str | None:
    return None if r.get(key) is None or isinstance(r[key], str) else f"{key} must be a string"


def _submitter(value: Any) -> str | None:
    if not isinstance(value, dict):
        return "submitter must be a mapping"
    for key in ("pane", "session"):
        if key in value and not _text(value[key]):
            return f"submitter.{key} must be a non-empty string"
    return None


def _check_submit(r: dict[str, Any]) -> str | None:
    for key in ("class", "profile"):
        if not _text(r.get(key)):
            return f"{key} must be a non-empty string"
    problem = _submitter(r.get("submitter"))
    if problem:
        return problem
    if r["class"] == "cleanup":
        return None  # refused by the handler as unsupported in 0.4.0 (K-47); no other field is read
    for key in ("launcher", "target", "checkout"):
        if not _text(r.get(key)):
            return f"{key} must be a non-empty string"
    if "sha" in r and not _text(r["sha"]):
        return "sha must be a non-empty string"
    return None


def _check_job(r: dict[str, Any]) -> str | None:
    return None if _int(r.get("job_id")) else "job_id must be a non-negative integer"


def _check_job_and_submitter(r: dict[str, Any]) -> str | None:
    return _check_job(r) or _submitter(r.get("submitter"))


def _check_status(r: dict[str, Any]) -> str | None:
    return None if "job_id" not in r or _int(r["job_id"]) else "job_id must be a non-negative integer"


def _check_policy(r: dict[str, Any]) -> str | None:
    if not isinstance(r.get("policy"), dict):
        return "policy must be a mapping"
    return None if "decision" not in r or isinstance(r["decision"], str) else "decision must be a string"


def _check_render(r: dict[str, Any]) -> str | None:
    if not isinstance(r.get("text"), str):
        return "text must be a string"
    return _optional_string(r, "pane") or _optional_string(r, "session")


def _check_undelivered(r: dict[str, Any]) -> str | None:
    if not _text(r.get("hash")):
        return "hash must be a non-empty string"
    if not _int(r.get("attempt")):
        return "attempt must be a non-negative integer"
    return _optional_string(r, "session")


def _check_confirm(r: dict[str, Any]) -> str | None:
    if not isinstance(r.get("code"), str):
        return "code must be a string"
    return _optional_string(r, "origin") or _optional_string(r, "session")


def _none(r: dict[str, Any]) -> str | None:
    return None


CHECKS: dict[str, Callable[[dict[str, Any]], str | None]] = {
    "submit": _check_submit,
    "status": _check_status,
    "cancel": _check_job_and_submitter,
    "unretain": _check_job,
    "release": _check_job,
    "policy-set": _check_policy,
    "render": _check_render,
    "undelivered": _check_undelivered,
    "hook-confirm": _check_confirm,
    "repair-inspect": _none,
    "repair-quarantine": _none,
    "repair-resume": _none,
}


def malformed(request: Any) -> str | None:
    """The reason a decoded request is malformed, or None (K-44)."""
    if not isinstance(request, dict):
        return f"a request must be an object, got {type(request).__name__}"
    if "type" not in request:
        return "type is missing"
    kind = request["type"]
    if not isinstance(kind, str):
        return f"type must be a string, got {type(kind).__name__}"
    if not isinstance(request.get("request_id"), str):
        return "request_id must be a string"
    check = CHECKS.get(kind)
    return check(request) if check else None
