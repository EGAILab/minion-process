"""The `CONFIRM QUEUE <code>` chat hook (K-21 to K-24; Owner decision on #223, option 1).

A Claude Code `UserPromptSubmit` hook runs `python -m minion_process.hostqueue.confirm --queue <dir>`
with the hook event as JSON on standard input. The hook acts only when the whole prompt, trimmed, is
exactly `CONFIRM QUEUE ` followed by 8 lowercase hex digits. A prefix such as `Codex w1:p2: ...`, trailing
text, a truncated code or any other form confirms nothing, which is the parsing the outside-root guard
already applies to `APPROVE OUTSIDE`.

When the prompt matches, the hook drops one `hook-confirm` request for the broker. The broker never trusts
the request's content; it checks the challenge's code, scope, use and expiry itself. This is a procedural
channel between cooperating agents. It is not a machine proof that a human typed the code: the standing
rule that no agent ever types, relays or sends keys for a confirmation code carries that weight, and every
Claude guard denies a tool call containing `CONFIRM QUEUE`.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from .client import put

PATTERN = re.compile(r"CONFIRM QUEUE ([0-9a-f]{8})")


def parse(prompt: str) -> str | None:
    match = PATTERN.fullmatch(prompt.strip())
    return match.group(1) if match else None


def handle(event: dict[str, Any], queue: Path) -> str | None:
    if event.get("hook_event_name") != "UserPromptSubmit":
        return None
    code = parse(str(event.get("prompt", "")))
    if code is None:
        return None
    return put(
        queue,
        {
            "type": "hook-confirm",
            "origin": "user-prompt-hook",
            "code": code,
            "session": event.get("session_id"),
        },
        _type_check=False,
    )


def main(argv: list[str], stdin: Any = None) -> int:
    if len(argv) != 2 or argv[0] != "--queue":
        print("usage: python -m minion_process.hostqueue.confirm --queue <queue-dir>", file=sys.stderr)
        return 64
    try:
        event = json.load(stdin or sys.stdin)
    except ValueError:
        return 0  # not a hook event: confirm nothing, never block the prompt
    handle(event if isinstance(event, dict) else {}, Path(argv[1]))
    return 0


if __name__ == "__main__":  # pragma: no cover - entry point; `main` is tested directly
    raise SystemExit(main(sys.argv[1:]))
