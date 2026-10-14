"""Request shapes, checked before dispatch (PROC-KIT-P3B-R010).

A well-framed request whose fields have the wrong shape is rejected on its own, into `rejected/` with the
reason. It never raises inside the broker, never stalls the inbox, and never reaches a handler. Only field
shapes are checked here. Every semantic decision (does the job exist, is the copy registered, is the
policy valid) stays with the handler. Storage, workload and containment errors are not swallowed as
malformed input.
"""

from __future__ import annotations

from typing import Any


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _submitter(value: Any) -> str | None:
    if not isinstance(value, dict):
        return "submitter must be a mapping"
    for key in ("pane", "session"):
        if key in value and not _text(value[key]):
            return f"submitter.{key} must be a non-empty string"
    return None


def _check_submit(r: dict[str, Any]) -> str | None:
    if not _text(r.get("class")):
        return "class must be a non-empty string"
    if not _text(r.get("profile")):
        return "profile must be a non-empty string"
    problem = _submitter(r.get("submitter"))
    if problem:
        return problem
    if r["class"] == "cleanup":
        copies = r.get("copies")
        if not isinstance(copies, list) or not all(_text(c) for c in copies):
            return "copies must be a list of non-empty strings"
        if "apply" in r and not isinstance(r["apply"], bool):
            return "apply must be true or false"
        return None
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
    for key in ("pane", "session"):
        if key in r and r[key] is not None and not isinstance(r[key], str):
            return f"{key} must be a string"
    return None


def _check_undelivered(r: dict[str, Any]) -> str | None:
    if not _text(r.get("hash")):
        return "hash must be a non-empty string"
    if not _int(r.get("attempt")):
        return "attempt must be a non-negative integer"
    return (
        None
        if "session" not in r or r["session"] is None or isinstance(r["session"], str)
        else "session must be a string"
    )


def _check_confirm(r: dict[str, Any]) -> str | None:
    if not isinstance(r.get("code"), str):
        return "code must be a string"
    return None if r.get("session") is None or isinstance(r["session"], str) else "session must be a string"


def _none(r: dict[str, Any]) -> str | None:
    return None


CHECKS = {
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


def malformed(request: dict[str, Any]) -> str | None:
    """The reason a request is malformed, or None. An unknown type is not malformed: the handler answers
    it with an ordinary refusal."""
    check = CHECKS.get(request.get("type"))  # type: ignore[arg-type]
    return check(request) if check else None
