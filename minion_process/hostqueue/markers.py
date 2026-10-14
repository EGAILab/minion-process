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

from .framing import FramingError, decode_single, encode
from .hostos import HostOS

KINDS = (
    "launch",
    "render",
    "undelivered",
    "policy",
    "confirm",
    "cleanup",
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
        final.parent.mkdir(parents=True, exist_ok=True)
        body = encode({"kind": kind, "identity": list(identity), "after_seq": after_seq, **payload})
        temp = final.parent / f".tmp-{self.instance}-{secrets.token_hex(8)}"
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o644)
        try:
            view = memoryview(body)
            while view:
                view = view[os.write(fd, view) :]
            os.fsync(fd)
        finally:
            os.close(fd)
        try:
            self.host.publish(temp, final)
        except FileExistsError:
            temp.unlink()  # our own unpublished temporary; never a published marker
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
        if not self.root.exists():
            return removed
        prefix = f".tmp-{instance_start_marker}-"
        for folder, _dirs, files in os.walk(self.root):
            for name in files:
                if name.startswith(prefix):
                    os.unlink(os.path.join(folder, name))
                    removed.append(name)
        return removed
