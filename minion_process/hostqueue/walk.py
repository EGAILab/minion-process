"""A directory walk that never follows a link, junction or other reparse point.

`os.walk` may treat a Windows junction as an ordinary directory and descend into it, outside the tree being
walked. Every walk in the host queue uses `entries()` or `prove_tree()` instead. A reparse point is yielded
as one entry and never descended into. Errors propagate, because an unreadable folder is unknown and never
empty (K-36). `prove_tree()` is the launch proof of a writable directory resource (K-42a'): it refuses on
any reparse point and on any failed inspection.
"""

from __future__ import annotations

import os
import stat
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

_REPARSE = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT
_DIRECTORY = 0x10  # FILE_ATTRIBUTE_DIRECTORY


@dataclass(frozen=True)
class Entry:
    path: Path
    is_dir: bool  # a real directory (not a link)
    is_link: bool  # a link, junction or other reparse point
    link_is_dir: bool  # the link object itself is a directory entry (junction, directory symlink)


def classify(path: Path) -> Entry:
    info = os.lstat(path)
    attributes = getattr(info, "st_file_attributes", 0)
    link = stat.S_ISLNK(info.st_mode) or bool(attributes & _REPARSE)
    link_is_dir = link and bool(attributes & _DIRECTORY)
    return Entry(path, stat.S_ISDIR(info.st_mode) and not link, link, link_is_dir)


def entries(root: Path) -> Iterator[Entry]:
    """Every entry below `root` (not `root` itself), depth first, a directory before its contents."""
    for name in sorted(os.listdir(root)):
        entry = classify(root / name)
        yield entry
        if entry.is_dir:
            yield from entries(entry.path)


def files(root: Path) -> Iterator[Path]:
    """Regular files below `root`, never through a link."""
    for entry in entries(root):
        if not entry.is_dir and not entry.is_link:
            yield entry.path


class Unproven(RuntimeError):
    """A writable directory resource failed its launch proof (K-42a'); the message names the entry."""


@dataclass(frozen=True)
class TreeProof:
    path: str
    entries: int
    seconds: float

    def as_record(self) -> dict[str, object]:
        return {"path": self.path, "entries": self.entries, "seconds": round(self.seconds, 6)}


def prove_tree(roots: list[Path], root: Path) -> TreeProof:
    """K-42a': prove a writable directory resource at launch, or raise `Unproven`.

    1. The resource and every ancestor up to the drive root pass the R009 proof: none is a link or a
       reparse point (`contain.assert_inside`).
    2. The complete subtree is walked without following anything. A link, junction, mount point or any
       other reparse point refuses, dangling ones included.
    3. Every entry is inspected. A failed enumeration or inspection refuses.

    The walk only reads metadata and never changes anything. A resource that does not exist yet proves
    empty once its ancestors pass. The duration and entry count are returned for the job record."""
    from .contain import Contained, assert_inside

    began = time.perf_counter()
    try:
        assert_inside(roots, root)
    except Contained as exc:
        raise Unproven(f"{root}: {exc}") from None
    count = 0
    pending = [str(root)]
    while pending:
        folder = pending.pop()
        try:
            with os.scandir(folder) as listing:
                found = list(listing)
        except FileNotFoundError as exc:
            if folder == str(root):  # not created yet: nothing below it can exist
                return TreeProof(str(root), 0, time.perf_counter() - began)
            raise Unproven(f"{folder}: vanished during the walk: {exc}") from None
        except OSError as exc:
            raise Unproven(f"{folder}: cannot enumerate: {exc}") from None
        for item in found:
            try:
                info = item.stat(follow_symlinks=False)
            except OSError as exc:
                raise Unproven(f"{item.path}: cannot inspect: {exc}") from None
            count += 1
            attributes = getattr(info, "st_file_attributes", 0)
            if stat.S_ISLNK(info.st_mode) or attributes & _REPARSE:
                raise Unproven(f"{item.path}: link, junction or reparse point")
            if stat.S_ISDIR(info.st_mode):
                pending.append(item.path)
    return TreeProof(str(root), count, time.perf_counter() - began)
