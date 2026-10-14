"""Client side of the queue: one immutable request file per request, then wait for the response (B-3).

A client writes only `inbox/`. It writes a temporary file named `.tmp-client-...`, then renames it to
`<request-id>.req`. Each write goes through the containment proof. The client never touches a file the broker
owns. Waits are bounded, and a missing response is reported as `unavailable`, never as success (K-16).
The client cannot produce a `hook-confirm` request: only `confirm.py`, run by the Owner's chat hook, does
that (K-21, K-22).
"""

from __future__ import annotations

import os
import secrets
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import fsops, layout
from .framing import FramingError, decode_single, encode

CLIENT_TYPES = (
    "submit",
    "status",
    "cancel",
    "release",
    "policy-set",
    "render",
    "undelivered",
    "unretain",
    "repair-inspect",
    "repair-quarantine",
    "repair-resume",
)


class Unavailable(RuntimeError):
    """No response arrived within the bound: the broker is unavailable, starting or recovering."""


def new_request_id() -> str:
    return f"{int(time.time())}-{secrets.token_hex(6)}"


def put(queue: Path, request: dict[str, Any], *, _type_check: bool = True) -> str:
    if _type_check and request.get("type") not in CLIENT_TYPES:
        raise ValueError(f"clients cannot send request type {request.get('type')!r}")
    request_id = str(request.get("request_id") or new_request_id())
    body = encode({**request, "request_id": request_id})
    inbox = queue / layout.INBOX
    temp = inbox / f".tmp-client-{os.getpid()}-{secrets.token_hex(6)}"
    final = inbox / f"{request_id}.req"
    fsops.write_new([queue], temp, body)
    fsops.replace([queue], temp, final)
    return request_id


def get(
    queue: Path,
    request_id: str,
    timeout: float,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    final = queue / layout.OUTBOX / f"{request_id}.res"
    deadline = clock() + timeout
    while True:
        try:
            return decode_single(final.read_bytes())
        except FileNotFoundError:
            pass
        except FramingError as exc:
            raise Unavailable(f"response for {request_id} is unreadable: {exc}") from None
        if clock() >= deadline:
            raise Unavailable(
                f"no response for {request_id} within {timeout:.0f} s; "
                "broker unavailable, starting or recovering"
            )
        sleep(0.2)


def call(queue: Path, request: dict[str, Any], timeout: float = 30.0, **kw: Any) -> dict[str, Any]:
    return get(queue, put(queue, request), timeout, **kw)


def wait_job(
    queue: Path,
    job_id: int,
    timeout: float,
    poll: Callable[[], dict[str, Any]] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[int, dict[str, Any]]:
    """`build wait` (K-2): poll the job's status until it ends, is refused, becomes uncertain, or the
    timeout passes. Exit codes: 0 ended passed, 1 ended otherwise, 2 refused or cancelled, 3 uncertain,
    4 timeout."""
    deadline = clock() + timeout
    while True:
        response = poll() if poll else call(queue, {"type": "status", "job_id": job_id})
        jobs = response.get("jobs") or []
        job = jobs[0] if jobs else {}
        status = job.get("status")
        if status == "ended":
            return (0 if job.get("outcome") == "passed" else 1), job
        if status in ("refused", "cancelled"):
            return 2, job
        if status == "uncertain":
            return 3, job
        if clock() >= deadline:
            return 4, job
        sleep(2.0)
