"""A directory walk that never follows a link, junction or other reparse point.

`os.walk` may treat a Windows junction as an ordinary directory and descend into it, outside the tree being
walked. Every walk in the host queue uses `entries()` instead. A reparse point is yielded as one entry, so
the caller can remove the link itself, and it is never descended into. Errors propagate, because an
unreadable folder is unknown and never empty (K-36).
"""

from __future__ import annotations

import os
import stat
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


def entries(root: Path, bottom_up: bool = False) -> Iterator[Entry]:
    """Every entry below `root` (not `root` itself), depth first. With `bottom_up`, a directory comes
    after its contents, the order needed for removal."""
    for name in sorted(os.listdir(root)):
        entry = classify(root / name)
        if entry.is_dir and not bottom_up:
            yield entry
        if entry.is_dir:
            yield from entries(entry.path, bottom_up)
        if not entry.is_dir or bottom_up:
            yield entry


def files(root: Path) -> Iterator[Path]:
    """Regular files below `root`, never through a link."""
    for entry in entries(root):
        if not entry.is_dir and not entry.is_link:
            yield entry.path
