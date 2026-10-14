"""Containment proof before every write, rename and delete (B-31, B-32, K-36; kit WORKFLOW.md §9.8;
PROC-KIT-P3B-R009).

`assert_inside(roots, target)` raises `Contained` unless all of these hold:

1. **Form.** The target is an absolute local path with a drive. It has no `..` segment, is not a
   drive-relative form such as `X:foo`, and is not a UNC or device path.
2. **Lexical.** The normalized target lies strictly below one of the allowed roots.
3. **Real path.** Every component from the drive root down to the target is inspected without following
   links, so the allowed root and all of its ancestors are proved, not only the part below the root:
   - a plain directory or file passes;
   - a link, junction or other reparse point refuses;
   - a missing component ends the walk, but only on a not-found error, because nothing can exist below it;
   - any other error refuses.

With `final_entry=True` the last component is the entry being removed. It may itself be a link, and only
its ancestors are proved, so the caller removes the link object without following it.

Callers run the proof immediately before each operation, through `fsops`. Nothing runs when it fails.
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


def _components(path: str) -> list[str]:
    """Every prefix of `path` from its anchor (drive root) down to `path` itself."""
    pure = Path(path)
    current = Path(pure.anchor)
    found = [str(current)]
    for part in pure.parts[1:]:
        current = current / part
        found.append(str(current))
    return found


def assert_inside(roots: list[Path], target: Path, final_entry: bool = False) -> Path:
    raw = str(target)
    problem = _form_ok(raw)
    if problem:
        raise Contained(f"{problem}: {raw}")
    norm_target = _norm(raw)
    if not any(norm_target.startswith(_norm(str(root)) + os.sep) for root in roots):
        raise Contained(f"outside every allowed root: {raw}")
    components = _components(os.path.normpath(raw))
    if final_entry:
        components = components[:-1]
    for current in components:
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            return target
        except OSError as exc:
            raise Contained(f"cannot inspect {current}: {exc}") from None
        if _is_link(info):
            raise Contained(f"link or reparse point at {current}")
    return target
