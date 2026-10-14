"""Every filesystem mutation the host queue makes, each preceded by its containment proof (PROC-KIT-P3B-R009).

Every function proves its target immediately before the single operation it performs. A rename proves both
its source and its destination. A removal proves the entry's ancestors, then removes the entry itself
without following it. When a proof fails, `contain.Contained` is raised and the operation does not run. No
module of the host queue mutates the filesystem except through these functions; the static test in
`tests/test_hostqueue_fsops.py` holds that.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Callable
from pathlib import Path

from .contain import assert_inside

Roots = list[Path]


def mkdir(roots: Roots, path: Path) -> None:
    """Create `path` and any missing parents, proving the full path first and each created level after."""
    assert_inside(roots, path)
    missing: list[Path] = []
    current = path
    while not os.path.lexists(current):
        missing.append(current)
        current = current.parent
    for level in reversed(missing):
        assert_inside(roots, level)
        with contextlib.suppress(FileExistsError):
            os.mkdir(level)


def write_new(roots: Roots, path: Path, data: bytes) -> None:
    """Create `path` exclusively, write `data` in full and flush it to disk."""
    assert_inside(roots, path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o644)
    try:
        _write_all(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)


def append(roots: Roots, path: Path, data: bytes) -> None:
    """Append `data` in full and flush it to disk (the journal's write)."""
    assert_inside(roots, path)
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o644)
    try:
        _write_all(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)


def replace(roots: Roots, source: Path, destination: Path) -> None:
    """Rename `source` over `destination`, proving both sides immediately before."""
    assert_inside(roots, source)
    assert_inside(roots, destination)
    os.replace(source, destination)


def write_replace(roots: Roots, temp: Path, final: Path, data: bytes) -> None:
    """Write `data` to a fresh temporary, then rename it over `final`."""
    write_new(roots, temp, data)
    replace(roots, temp, final)


def publish(roots: Roots, temp: Path, final: Path, rename: Callable[[Path, Path], None]) -> None:
    """Rename without replace through the host's publication primitive, both sides proved (K-35)."""
    assert_inside(roots, temp)
    assert_inside(roots, final)
    rename(temp, final)


def unlink(roots: Roots, path: Path) -> None:
    assert_inside(roots, path, final_entry=True)
    os.unlink(path)


def rmdir(roots: Roots, path: Path) -> None:
    assert_inside(roots, path, final_entry=True)
    os.rmdir(path)


def utime(roots: Roots, path: Path) -> None:
    assert_inside(roots, path)
    os.utime(path, None)


def open_append(roots: Roots, path: Path) -> object:
    """An append handle for a log the runner streams into, opened after the proof."""
    assert_inside(roots, path)
    return open(path, "ab")


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        view = view[os.write(fd, view) :]
