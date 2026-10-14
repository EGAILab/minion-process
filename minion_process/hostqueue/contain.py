"""Containment proof before every write, rename or delete (B-31, B-32, K-36; kit WORKFLOW.md §9.8).

`assert_inside(roots, target)` raises `Contained` unless all of these hold:

1. **Form.** The target is an absolute local path with a drive or root. It has no `..` segment, is not a
   drive-relative form such as `X:foo`, and is not a UNC or device path.
2. **Lexical.** The normalized target lies strictly below one of the allowed roots.
3. **Real path.** Every component from that root down to the target is inspected without following links:
   - a plain directory or file passes;
   - a link, junction or other reparse point refuses;
   - a missing component ends the walk, but only on a not-found error, because nothing can exist below it;
   - any other error refuses.

Callers run the proof immediately before each operation. Nothing runs when it fails.
"""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path, PureWindowsPath

_REPARSE = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT
_DRIVE_RELATIVE = re.compile(r"^[A-Za-z]:(?![\\/])")


class Contained(PermissionError):
    """The containment proof failed; the operation must not run."""


def _norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def _form_ok(raw: str) -> str | None:
    if not raw:
        return "empty path"
    if raw.startswith(("\\\\", "//")):
        return "UNC or device path"
    if _DRIVE_RELATIVE.match(raw):
        return "drive-relative path"
    parts = re.split(r"[\\/]", raw)
    if ".." in parts:
        return "'..' segment"
    if not os.path.isabs(raw):
        return "relative path"
    if os.name == "nt" and not PureWindowsPath(raw).drive:
        return "no drive"
    return None


def _is_link(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & _REPARSE)


def assert_inside(roots: list[Path], target: Path) -> Path:
    raw = str(target)
    problem = _form_ok(raw)
    if problem:
        raise Contained(f"{problem}: {raw}")
    norm_target = _norm(raw)
    for root in roots:
        norm_root = _norm(str(root))
        if norm_target.startswith(norm_root + os.sep):
            break
    else:
        raise Contained(f"outside every allowed root: {raw}")
    relative = os.path.relpath(os.path.normpath(raw), os.path.normpath(str(root)))
    current = os.path.normpath(str(root))
    for part in [p for p in relative.split(os.sep) if p]:
        current = os.path.join(current, part)
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            return target
        except OSError as exc:
            raise Contained(f"cannot inspect {current}: {exc}") from None
        if _is_link(info):
            raise Contained(f"link or reparse point at {current}")
    return target
