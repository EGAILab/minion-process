"""The host policy (B-5, K-37): one authority for every adopting project on the host.

A policy version is published as an effect marker `policy/<version>` that carries its full content. The
journal records the confirmation that authorized it. The policy in force is the highest version that is
readable, whose confirmation is consumed (`confirm/<challenge>` present), and whose version follows the
previous in-force version without a gap. Anything else is unknown, and admission stops until the Owner
re-confirms a policy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

OWNER_DEFAULTS = {  # Owner decision 2026-10-13 (#223 issuecomment-6139069723)
    "limit": 2,
    "floor_bytes": 16 * 1024**3,
    "reservation_seconds": 180,
    "bypass_limit": 3,
}

_POLICY_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*(\.[A-Za-z0-9_-]+)*")
_INT_FIELDS = ("version", "limit", "floor_bytes", "reservation_seconds", "bypass_limit")


class PolicyError(ValueError):
    pass


@dataclass(frozen=True)
class Policy:
    policy_id: str
    version: int
    limit: int
    floor_bytes: int
    reservation_seconds: int
    bypass_limit: int
    projects: dict[str, list[str]]  # project name -> allowed roots (canonical)

    def as_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "version": self.version,
            "limit": self.limit,
            "floor_bytes": self.floor_bytes,
            "reservation_seconds": self.reservation_seconds,
            "bypass_limit": self.bypass_limit,
            "projects": {name: list(roots) for name, roots in sorted(self.projects.items())},
        }


def parse(data: Any) -> Policy:
    if not isinstance(data, dict):
        raise PolicyError("policy must be a mapping")
    missing = [k for k in ("policy_id", *_INT_FIELDS, "projects") if k not in data]
    if missing:
        raise PolicyError(f"policy missing {missing}")
    for key in _INT_FIELDS:
        value = data[key]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise PolicyError(f"policy {key} must be a non-negative integer")
    if data["version"] < 1 or data["limit"] < 1:
        raise PolicyError("policy version and limit must be at least 1")
    if not isinstance(data["policy_id"], str) or not _POLICY_ID.fullmatch(data["policy_id"]):
        # It becomes part of folder names, group names and job labels (K-42): letters, digits, `.`, `_`, `-`.
        raise PolicyError("policy_id must be a name of letters, digits, '.', '_' or '-'")
    projects = data["projects"]
    if not isinstance(projects, dict) or not projects:
        raise PolicyError("policy projects must be a non-empty mapping")
    for name, roots in projects.items():
        if not isinstance(name, str) or not isinstance(roots, list) or not roots:
            raise PolicyError(f"project {name!r} needs a non-empty list of roots")
        if not all(isinstance(r, str) and r for r in roots):
            raise PolicyError(f"project {name!r} roots must be non-empty strings")
    extra = set(data) - {"policy_id", *_INT_FIELDS, "projects"}
    if extra:
        raise PolicyError(f"policy has unknown keys {sorted(extra)}")
    return Policy(
        data["policy_id"],
        data["version"],
        data["limit"],
        data["floor_bytes"],
        data["reservation_seconds"],
        data["bypass_limit"],
        {name: list(roots) for name, roots in projects.items()},
    )
