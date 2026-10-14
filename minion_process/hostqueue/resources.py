"""Resources are canonical real paths, and two resources conflict when they overlap (B-11, W-11).

A job holds a list of `(path, mode)` leases, where mode is `exclusive` or `shared`. Two leases conflict
when their paths are equal or one contains the other, unless both are `shared`. Paths are canonicalized
once, at submit (B-10). At launch, input drift is detected by canonicalizing again and comparing.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path

EXCLUSIVE = "exclusive"
SHARED = "shared"


def canonical(path: str | Path) -> str:
    """The real path, case-normalized on Windows, without a trailing separator."""
    return os.path.normcase(os.path.realpath(os.path.normpath(str(path))))


def overlaps(a: str, b: str) -> bool:
    return a == b or a.startswith(b.rstrip(os.sep) + os.sep) or b.startswith(a.rstrip(os.sep) + os.sep)


def conflicts(held: Iterable[tuple[str, str]], wanted: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    """Pairs `(held_path, wanted_path)` that conflict."""
    found: list[tuple[str, str]] = []
    held = list(held)
    for want_path, want_mode in wanted:
        for have_path, have_mode in held:
            if overlaps(have_path, want_path) and not (have_mode == SHARED and want_mode == SHARED):
                found.append((have_path, want_path))
    return found
