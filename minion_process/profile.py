"""`minion-process profile validate`: offline validation of a project's `profile.yaml`
(`profiles/profile.schema.json`). It implements the schema's rules plus the few cross-field rules a JSON
schema cannot express (`SUPPLEMENTAL_RULES`), is total (diagnostics, never a raise, for any YAML value)
and fails closed (an unknown key or a malformed value is an error, never ignored or defaulted). It
needs neither network nor `gh`.

`PROC-KIT-P1-R001`: a non-string value in an enum position is a shape error, checked before any
membership test, so a list or mapping there can never raise. `PROC-KIT-P1-R002`: every supplied value
is validated whether or not the selected backend uses it, and the schema expresses the role-coverage
rules as constraints; `tests/test_profile.py` runs both validators differentially."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from .validate import Problem, _text

SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
PROJECT = re.compile(r"^[a-z0-9][a-z0-9-]*$")
LANGUAGE = re.compile(r"^[a-z][a-z0-9+-]*$")
ROLE = re.compile(r"^(coordinator|shared-contract-owner|reviewer|implementer:[a-z][a-z0-9+-]*)$")
ALIAS = re.compile(r"^[A-Z][A-Z0-9_]*$")

TOP_REQUIRED = ("kit", "project", "authority", "repos", "coordination", "agents", "delegation")
TOP_OPTIONAL = (
    "conformance",
    "taxonomy_aliases",
    "hazard_families",
    "gates",
    "build_queue",
    "wp_kinds_enabled",
    "implementation_order",
    "environment",
)
AUTHORITY_KINDS = frozenset({"source", "bundle", "manifest", "spec", "conformance", "design", "register"})
BACKENDS = frozenset({"github-issue", "state-file"})
TARGET_KINDS = frozenset({"gate", "controls", "reviewer"})
TAXONOMY = frozenset(
    {
        "AUTHORITY_BEHAVIOR_UNCERTAIN",
        "AUTHORITY_PARITY_DEFECT",
        "CONTRACT_ASSURANCE_DEFECT",
        "PARITY_NEUTRAL_HARDENING",
        "PARITY_CONSTRAINED_RISK",
    }
)
TIERS = frozenset({"g0", "g1", "g2", "g3"})
WP_KINDS = frozenset({"semantic", "delta", "process", "scoping", "status"})

SUPPLEMENTAL_RULES = (
    "implementation_order: every language listed has an `implementer:<language>` agent",
    "conformance: `support` entries are not also `families` entries",
)
"""Cross-field rules the JSON schema cannot express. Each is named in the schema's `description` so a
reader of either artifact knows the full rule set; `tests/test_profile.py` checks that agreement."""


class _Check:
    def __init__(self) -> None:
        self.problems: list[Problem] = []

    def error(self, path: str, message: str) -> None:
        self.problems.append(Problem("error", path, message))

    def mapping(self, value: Any, path: str) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            self.error(path, f"must be a mapping, got {type(value).__name__}")
            return None
        if any(not isinstance(k, str) for k in value):
            self.error(path, "keys must be strings")
            return None
        return value

    def keys(
        self, value: dict[str, Any], path: str, required: tuple[str, ...], optional: tuple[str, ...]
    ) -> bool:
        ok = True
        for key in required:
            if key not in value:
                self.error(f"{path}.{key}" if path else key, "required")
                ok = False
        extra = sorted(set(value) - set(required) - set(optional))
        if extra:
            self.error(path or "profile", f"unknown keys {extra}")
            ok = False
        return ok

    def text(self, value: Any, path: str, pattern: re.Pattern[str] | None = None, what: str = "") -> bool:
        if not _text(value):
            self.error(path, "must be a non-empty string")
            return False
        if pattern is not None and pattern.match(value) is None:
            self.error(path, f"must be {what}, got {value!r}")
            return False
        return True

    def enum(self, value: Any, path: str, allowed: frozenset[str]) -> bool:
        """Shape first (R001): only a string is ever tested for membership."""
        if not isinstance(value, str):
            self.error(path, f"must be a string, got {type(value).__name__}")
            return False
        if value not in allowed:
            self.error(path, f"must be one of {sorted(allowed)}, got {value!r}")
            return False
        return True

    def string_list(self, value: Any, path: str, minimum: int = 0) -> list[str] | None:
        if not isinstance(value, list):
            self.error(path, f"must be a list, got {type(value).__name__}")
            return None
        if len(value) < minimum:
            self.error(path, f"needs at least {minimum} item(s)")
            return None
        items: list[str] = []
        for i, item in enumerate(value):
            if self.text(item, f"{path}[{i}]"):
                items.append(item)
        if len(set(items)) != len(items):
            self.error(path, "items must be unique")
        return items

    def enum_list(self, value: Any, path: str, allowed: frozenset[str], minimum: int = 0) -> list[str]:
        items = self.string_list(value, path, minimum) or []
        return [item for i, item in enumerate(items) if self.enum(item, f"{path}[{i}]", allowed)]


def _kit(c: _Check, value: Any) -> None:
    kit = c.mapping(value, "kit")
    if kit is None or not c.keys(kit, "kit", ("version", "source"), ()):
        return
    c.text(kit["version"], "kit.version", SEMVER, "MAJOR.MINOR.PATCH")
    c.text(kit["source"], "kit.source", REPO, "owner/repo")


def _authority(c: _Check, value: Any) -> None:
    if not isinstance(value, list):
        c.error("authority", f"must be a list, got {type(value).__name__}")
        return
    if not value:
        c.error("authority", "needs at least one entry (highest authority first)")
        return
    for i, raw in enumerate(value):
        path = f"authority[{i}]"
        entry = c.mapping(raw, path)
        if entry is None or not c.keys(entry, path, ("kind",), ("name", "path", "pin", "verify")):
            continue
        c.enum(entry["kind"], f"{path}.kind", AUTHORITY_KINDS)
        if "path" not in entry and "pin" not in entry:
            c.error(path, "needs `path` or `pin`")
        for key in ("name", "path", "pin", "verify"):
            if key in entry:
                c.text(entry[key], f"{path}.{key}")


def _repos(c: _Check, value: Any) -> None:
    repos = c.mapping(value, "repos")
    if repos is None:
        return
    if not repos:
        c.error("repos", "needs at least one repository")
        return
    for name, raw in repos.items():
        path = f"repos.{name}"
        repo = c.mapping(raw, path)
        if repo is None or not c.keys(repo, path, ("path", "default_branch"), ("github",)):
            continue
        c.text(repo["path"], f"{path}.path")
        c.text(repo["default_branch"], f"{path}.default_branch")
        if "github" in repo:
            c.text(repo["github"], f"{path}.github", REPO, "owner/repo")


def _coordination(c: _Check, value: Any) -> None:
    coord = c.mapping(value, "coordination")
    if coord is None or not c.keys(coord, "coordination", ("backend",), ("repo", "path")):
        return
    # R002: every supplied locator is validated, whichever backend is selected.
    if "repo" in coord:
        c.text(coord["repo"], "coordination.repo", REPO, "owner/repo")
    if "path" in coord:
        c.text(coord["path"], "coordination.path")
    if not c.enum(coord["backend"], "coordination.backend", BACKENDS):
        return
    needed = "repo" if coord["backend"] == "github-issue" else "path"
    if needed not in coord:
        c.error(f"coordination.{needed}", f"required for the {coord['backend']} backend")


def _conformance(c: _Check, value: Any) -> None:
    conf = c.mapping(value, "conformance")
    if conf is None or not c.keys(conf, "conformance", ("families",), ("support",)):
        return
    families = c.string_list(conf["families"], "conformance.families", minimum=1) or []
    support = c.string_list(conf["support"], "conformance.support") if "support" in conf else []
    for i, item in enumerate(support or []):
        if item in families:
            c.error(f"conformance.support[{i}]", f"{item!r} is also a behavior family; it cannot be both")


def _agents(c: _Check, value: Any) -> set[str]:
    """Validates the agents and returns the implementer languages found."""
    languages: set[str] = set()
    agents = c.mapping(value, "agents")
    if agents is None:
        return languages
    if len(agents) < 2:
        c.error("agents", "needs at least two agents: review is independent of authorship")
    roles_by_agent: dict[str, set[str]] = {}
    for name, raw in agents.items():
        path = f"agents.{name}"
        agent = c.mapping(raw, path)
        if agent is None or not c.keys(agent, path, ("roles", "harness"), ("default_pane",)):
            continue
        c.text(agent["harness"], f"{path}.harness")
        if "default_pane" in agent:
            c.text(agent["default_pane"], f"{path}.default_pane")
        roles = c.string_list(agent["roles"], f"{path}.roles", minimum=1)
        if roles is None:
            continue
        held: set[str] = set()
        for i, role in enumerate(roles):
            if ROLE.match(role) is None:
                c.error(f"{path}.roles[{i}]", f"unknown role {role!r}")
                continue
            held.add(role)
            if role.startswith("implementer:"):
                languages.add(role.split(":", 1)[1])
        roles_by_agent[name] = held
    all_roles = set().union(*roles_by_agent.values()) if roles_by_agent else set()
    if "coordinator" not in all_roles:
        c.error("agents", "no agent holds `coordinator`")
    if "reviewer" not in all_roles:
        c.error("agents", "no agent holds `reviewer`")
    if not languages:
        c.error("agents", "no agent holds an `implementer:<language>` role")
    independent = [
        n for n, r in roles_by_agent.items() if "reviewer" in r and "shared-contract-owner" not in r
    ]
    if "reviewer" in all_roles and not independent:
        c.error("agents", "every reviewer also holds `shared-contract-owner`: no independent reviewer")
    return languages


def _aliases(c: _Check, value: Any) -> None:
    aliases = c.mapping(value, "taxonomy_aliases")
    if aliases is None:
        return
    for alias, target in aliases.items():
        if ALIAS.match(alias) is None:
            c.error(f"taxonomy_aliases.{alias}", "alias must be an UPPER_CASE identifier")
        c.enum(target, f"taxonomy_aliases.{alias}", TAXONOMY)


def _gates(c: _Check, value: Any) -> None:
    gates = c.mapping(value, "gates")
    if gates is None:
        return
    for name, raw in gates.items():
        path = f"gates.{name}"
        gate = c.mapping(raw, path)
        if gate is None or not c.keys(gate, path, ("launcher", "tiers"), ("queue",)):
            continue
        c.text(gate["launcher"], f"{path}.launcher")
        c.enum_list(gate["tiers"], f"{path}.tiers", TIERS, minimum=1)
        if "queue" in gate:
            _gate_queue(c, gate["queue"], f"{path}.queue")


def _gate_queue(c: _Check, value: Any, path: str) -> None:
    """A launcher the kit host queue can run (docs/p3b/, B-10, B-14)."""
    queue = c.mapping(value, path)
    optional = ("env", "target_env", "source_globs", "container", "cache_env")
    if queue is None or not c.keys(queue, path, ("argv",), optional):
        return
    argv = queue["argv"]
    if not isinstance(argv, list):
        c.error(f"{path}.argv", f"must be a list, got {type(argv).__name__}")
    elif not argv:
        c.error(f"{path}.argv", "needs at least 1 item(s)")
    else:
        for i, item in enumerate(argv):
            c.text(item, f"{path}.argv[{i}]")
    for section in ("env", "cache_env"):
        if section in queue:
            mapping = c.mapping(queue[section], f"{path}.{section}")
            for key, item in (mapping or {}).items():
                c.text(item, f"{path}.{section}.{key}")
    for key in ("target_env", "source_globs"):
        if key in queue:
            c.string_list(queue[key], f"{path}.{key}")
    if "container" in queue and not isinstance(queue["container"], bool):
        c.error(f"{path}.container", "must be true or false")


def _build_queue(c: _Check, value: Any) -> None:
    queue = c.mapping(value, "build_queue")
    required = ("state", "policy_id", "project", "exec_root", "log_root", "targets")
    if queue is None or not c.keys(
        queue, "build_queue", required, ("caches", "inherit_env", "cleanup_references")
    ):
        return
    for key in required[:-1]:
        c.text(queue[key], f"build_queue.{key}")
    targets = c.mapping(queue["targets"], "build_queue.targets")
    if targets is not None and not targets:
        c.error("build_queue.targets", "needs at least one target")
    for name, raw in (targets or {}).items():
        path = f"build_queue.targets.{name}"
        target = c.mapping(raw, path)
        if target is None or not c.keys(target, path, ("path", "kind"), ("owner_agent",)):
            continue
        c.text(target["path"], f"{path}.path")
        c.enum(target["kind"], f"{path}.kind", TARGET_KINDS)
        if "owner_agent" in target:
            c.text(target["owner_agent"], f"{path}.owner_agent")
    if "caches" in queue:
        caches = c.mapping(queue["caches"], "build_queue.caches")
        for name, item in (caches or {}).items():
            c.text(item, f"build_queue.caches.{name}")
    if "inherit_env" in queue:
        c.string_list(queue["inherit_env"], "build_queue.inherit_env")
    if "cleanup_references" in queue:
        refs = c.mapping(queue["cleanup_references"], "build_queue.cleanup_references")
        kinds = ("work_packages", "incidents", "authority_cache")
        if refs is not None and c.keys(refs, "build_queue.cleanup_references", kinds, ()):
            for kind in kinds:
                c.string_list(refs[kind], f"build_queue.cleanup_references.{kind}", minimum=1)


def _delegation(c: _Check, value: Any) -> None:
    delegation = c.mapping(value, "delegation")
    if delegation is None or not c.keys(delegation, "delegation", ("source", "routing"), ()):
        return
    c.text(delegation["source"], "delegation.source")
    if not isinstance(delegation["routing"], bool):
        c.error("delegation.routing", "must be true or false")


def validate_profile(data: Any) -> list[Problem]:
    """Every rule of `profiles/profile.schema.json` plus `SUPPLEMENTAL_RULES`, as diagnostics. Never
    raises."""
    c = _Check()
    profile = c.mapping(data, "profile")
    if profile is None:
        return c.problems
    c.keys(profile, "", TOP_REQUIRED, TOP_OPTIONAL)
    if "kit" in profile:
        _kit(c, profile["kit"])
    if "project" in profile:
        c.text(profile["project"], "project", PROJECT, "a lower-case kebab-case name")
    if "authority" in profile:
        _authority(c, profile["authority"])
    if "repos" in profile:
        _repos(c, profile["repos"])
    if "coordination" in profile:
        _coordination(c, profile["coordination"])
    if "conformance" in profile:
        _conformance(c, profile["conformance"])
    languages = _agents(c, profile["agents"]) if "agents" in profile else set()
    if "taxonomy_aliases" in profile:
        _aliases(c, profile["taxonomy_aliases"])
    if "hazard_families" in profile:
        c.string_list(profile["hazard_families"], "hazard_families")
    if "gates" in profile:
        _gates(c, profile["gates"])
    if "build_queue" in profile:
        _build_queue(c, profile["build_queue"])
    if "delegation" in profile:
        _delegation(c, profile["delegation"])
    if "wp_kinds_enabled" in profile:
        c.enum_list(profile["wp_kinds_enabled"], "wp_kinds_enabled", WP_KINDS)
    if "implementation_order" in profile:
        order = c.string_list(profile["implementation_order"], "implementation_order", minimum=1) or []
        for i, language in enumerate(order):
            if LANGUAGE.match(language) is None:
                c.error(f"implementation_order[{i}]", f"not a language name: {language!r}")
            elif language not in languages:
                c.error(f"implementation_order[{i}]", f"no agent holds `implementer:{language}`")
    if "environment" in profile:
        c.text(profile["environment"], "environment")
    return c.problems


def load_profile(path: Path) -> tuple[Any, list[Problem]]:
    """Reads and validates a profile file. Unreadable or unparsable input is a diagnostic, not a raise."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as failure:  # totality: any load failure is a diagnostic, never a traceback
        return None, [Problem("error", str(path), f"cannot load: {type(failure).__name__}: {failure}")]
    return data, validate_profile(data)
