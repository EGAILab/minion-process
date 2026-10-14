"""Write-ahead effect markers (K-29, K-30, K-32, K-35, K-36).

A marker is published at its final name before the effect it guards, and it is never modified or
removed. Publication renames a fully written, flushed temporary file to the final name without
replace-existing, so the final identity is exclusive. A prepared temporary never authorizes anything.

Reading a marker gives one of three answers:
- `Absent`: the final name does not exist, and under the declared fault model the effect never started;
- `Unreadable`: the file exists but does not decode, so its content is unknown and the caller fails closed;
- the decoded payload.

Failing to inspect the folder raises; it is never reported as absent.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import fsops
from .framing import FramingError, decode_single, encode
from .hostos import HostOS
from .walk import entries

KINDS = (
    "launch",
    "render",
    "undelivered",
    "policy",
    "confirm",
    "register",
    "accept",
    "generation",
)


class MarkerExists(FileExistsError):
    """The final marker name is already published: the guarded effect is already reserved."""


@dataclass(frozen=True)
class Absent:
    pass


@dataclass(frozen=True)
class Unreadable:
    reason: str


ABSENT = Absent()


class Markers:
    def __init__(self, root: Path, host: HostOS, instance: str) -> None:
        self.root = root / "effects"
        self.host = host
        self.instance = instance

    def path(self, kind: str, *identity: str) -> Path:
        if kind not in KINDS:
            raise ValueError(f"unknown marker kind {kind!r}")
        for part in identity:
            if not part or part in (".", "..") or any(ch in part for ch in '/\\:*?"<>|'):
                raise ValueError(f"invalid marker identity part {part!r}")
        return self.root.joinpath(kind, *identity)

    def publish(self, kind: str, identity: tuple[str, ...], payload: dict[str, Any], after_seq: int) -> None:
        """Publish the marker, or raise `MarkerExists` if the final name is taken."""
        final = self.path(kind, *identity)
        roots = [self.root.parent]
        fsops.mkdir(roots, final.parent)
        body = encode({"kind": kind, "identity": list(identity), "after_seq": after_seq, **payload})
        temp = final.parent / f".tmp-{self.instance}-{secrets.token_hex(8)}"
        fsops.write_new(roots, temp, body)
        try:
            fsops.publish(roots, temp, final, self.host.publish)
        except FileExistsError:
            fsops.unlink(roots, temp)  # our own unpublished temporary; never a published marker
            raise MarkerExists(str(final)) from None

    def read(self, kind: str, *identity: str) -> dict[str, Any] | Absent | Unreadable:
        final = self.path(kind, *identity)
        try:
            data = final.read_bytes()
        except FileNotFoundError:
            return ABSENT
        try:
            return decode_single(data)
        except FramingError as exc:
            return Unreadable(exc.reason)

    def names(self, kind: str, *prefix: str) -> list[str]:
        """Published names directly under a kind (or a sub-folder of it), sorted. Temporaries excluded.
        Raises `OSError` if the folder exists but cannot be listed; a missing folder lists nothing."""
        folder = self.path(kind, *prefix) if prefix else self.root / kind
        try:
            entries = os.listdir(folder)
        except FileNotFoundError:
            return []
        return sorted(name for name in entries if not name.startswith(".tmp-"))

    def remove_own_temporaries(self, instance_start_marker: str) -> list[str]:
        """Remove `.tmp-<instance>-*` files this broker instance wrote (K-20, B-29). Never another's."""
        removed: list[str] = []
        if not os.path.lexists(self.root):
            return removed
        prefix = f".tmp-{instance_start_marker}-"
        for entry in entries(self.root):
            if not entry.is_dir and not entry.is_link and entry.path.name.startswith(prefix):
                fsops.unlink([self.root.parent], entry.path)
                removed.append(entry.path.name)
        return removed
