"""`minion-process launch-plan` and `session-record`: how an agent session of a project is (re)launched
with the project-scope settings (`project-scope.md` PS-3, PS-5), and which session it resumes.

The project lists its sessions in `<root>/.minion/sessions.yaml` (an Owner-controlled file, PS-2):

    version: 1
    sessions:
      impl: {tool: codex, network: true, env: {PUB_CACHE: .tmp/pub-cache}}
      review: {tool: claude}

`plan()` turns one entry into the working folder, environment and argument vector that
`bootstrap/relaunch.ps1` runs. Nothing here starts a process. Every path is inside the root, and every
input that reaches the argument vector is validated first. Anything unexpected is an error, never a
default (fail closed).

The session to resume is, in order: the `--resume` id; none with `--fresh`; the id recorded for this
session in `<root>/.tmp/sessions/<name>.json`. Without any of them the plan is refused, so a relaunch
never silently starts a new session in place of the one the Owner meant to continue."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

import yaml

SESSIONS_FILE = PurePosixPath(".minion/sessions.yaml")
STATE_DIR = PurePosixPath(".tmp/sessions")
TEMP_DIR = PurePosixPath(".tmp")
NAME = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
SESSION_ID = re.compile(r"^[0-9A-Za-z][0-9A-Za-z-]{7,63}$")
ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
TOOLS = frozenset({"claude", "codex"})
RESERVED_ENV = frozenset({"TEMP", "TMP", "TMPDIR"})
CODEX_SANDBOX = (
    "-s",
    "workspace-write",
    "-a",
    "on-request",
    "-c",
    "sandbox_workspace_write.writable_roots=[]",
)
CODEX_TEMP = (
    "-c",
    "sandbox_workspace_write.exclude_tmpdir_env_var=true",
    "-c",
    "sandbox_workspace_write.exclude_slash_tmp=true",
)


class LaunchError(Exception):
    """The sessions file, a name, an id or a path is not acceptable. Nothing was written."""


@dataclass(frozen=True)
class Plan:
    session: str
    tool: str
    cwd: str
    env: dict[str, str]
    argv: list[str]
    resume: str | None
    state_file: str

    def as_json(self) -> str:
        return json.dumps(self.__dict__, indent=2, sort_keys=True)


def relative(value: Any, where: str) -> PurePosixPath:
    """A root-relative path: no absolute, drive, UNC or `..` form (the containment rule)."""
    if not isinstance(value, str) or not value.strip():
        raise LaunchError(f"{where}: must be a non-empty root-relative path")
    if "\\" in value or ":" in value or value.startswith("/") or PureWindowsPath(value).anchor:
        raise LaunchError(f"{where}: must be a root-relative path with '/' separators, got {value!r}")
    path = PurePosixPath(value)
    if any(part in ("", "..", ".") for part in value.split("/")):
        raise LaunchError(f"{where}: must not contain '.' or '..' segments, got {value!r}")
    return path


def inside(root: Path, rel: PurePosixPath) -> Path:
    """`root/rel`, resolved, and asserted to stay under the resolved root (links included)."""
    base = root.resolve()
    target = (base / Path(*rel.parts)).resolve()
    if target != base and base not in target.parents:
        raise LaunchError(f"{rel}: resolves outside the root ({target})")
    return target


def load_sessions(root: Path) -> dict[str, dict[str, Any]]:
    path = inside(root, SESSIONS_FILE)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise LaunchError(f"{SESSIONS_FILE}: not found under {root}") from None
    except yaml.YAMLError as exc:
        raise LaunchError(f"{SESSIONS_FILE}: not valid YAML ({exc})") from None
    if not isinstance(data, dict) or set(data) != {"version", "sessions"}:
        raise LaunchError(f"{SESSIONS_FILE}: must be a mapping with exactly 'version' and 'sessions'")
    if data["version"] != 1:
        raise LaunchError(f"{SESSIONS_FILE}: version must be 1, got {data['version']!r}")
    sessions = data["sessions"]
    if not isinstance(sessions, dict) or not sessions:
        raise LaunchError(f"{SESSIONS_FILE}: sessions must be a non-empty mapping")
    for name, entry in sessions.items():
        _entry(name, entry)
    return sessions


def _entry(name: Any, entry: Any) -> None:
    where = f"sessions.{name}"
    if not isinstance(name, str) or NAME.match(name) is None:
        raise LaunchError(f"{where}: a session name is lower-case letters, digits and '-'")
    if not isinstance(entry, dict) or not set(entry) <= {"tool", "network", "env"}:
        raise LaunchError(f"{where}: must be a mapping of tool, network, env")
    if entry.get("tool") not in TOOLS:
        raise LaunchError(f"{where}.tool: must be one of {sorted(TOOLS)}")
    network = entry.get("network", False)
    if not isinstance(network, bool):
        raise LaunchError(f"{where}.network: must be true or false")
    if network and entry["tool"] != "codex":
        raise LaunchError(f"{where}.network: applies to codex only")
    env = entry.get("env", {})
    if not isinstance(env, dict):
        raise LaunchError(f"{where}.env: must be a mapping")
    for key, value in env.items():
        if not isinstance(key, str) or ENV_NAME.match(key) is None or key in RESERVED_ENV:
            raise LaunchError(f"{where}.env: {key!r} is not an allowed variable name")
        relative(value, f"{where}.env.{key}")


def session_id(value: str, where: str) -> str:
    if SESSION_ID.match(value) is None:
        raise LaunchError(f"{where}: not a session id: {value!r}")
    return value


def recorded(root: Path, name: str) -> str | None:
    path = inside(root, STATE_DIR / f"{name}.json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except ValueError:
        raise LaunchError(f"{STATE_DIR}/{name}.json: not valid JSON") from None
    if not isinstance(data, dict) or not isinstance(data.get("session"), str):
        raise LaunchError(f"{STATE_DIR}/{name}.json: must hold a 'session' string")
    return session_id(data["session"], f"{STATE_DIR}/{name}.json")


def plan(root: Path, name: str, resume: str | None = None, fresh: bool = False) -> Plan:
    if resume is not None and fresh:
        raise LaunchError("--resume and --fresh exclude each other")
    sessions = load_sessions(root)
    if name not in sessions:
        raise LaunchError(f"no session {name!r} in {SESSIONS_FILE} (have {sorted(sessions)})")
    entry = sessions[name]
    base = root.resolve()
    if fresh:
        chosen = None
    elif resume is not None:
        chosen = session_id(resume, "--resume")
    else:
        chosen = recorded(root, name)
        if chosen is None:
            raise LaunchError(
                f"no recorded session for {name!r}: pass --resume <id> once, or --fresh for a new session"
            )
    temp = str(inside(root, TEMP_DIR))
    env = {"TEMP": temp, "TMP": temp, "TMPDIR": temp}
    for key, value in sorted(entry.get("env", {}).items()):
        env[key] = str(inside(root, relative(value, f"sessions.{name}.env.{key}")))
    if entry["tool"] == "claude":
        argv = ["claude", *(["--resume", chosen] if chosen else [])]
    else:
        network = "true" if entry.get("network", False) else "false"
        argv = [
            "codex",
            *(["resume", chosen] if chosen else []),
            "-C",
            str(base),
            *CODEX_SANDBOX,
            "-c",
            f"sandbox_workspace_write.network_access={network}",
            *CODEX_TEMP,
        ]
    state = str(inside(root, STATE_DIR / f"{name}.json"))
    return Plan(name, entry["tool"], str(base), env, argv, chosen, state)


def record(root: Path, name: str, value: str) -> Path:
    """Write `<root>/.tmp/sessions/<name>.json` atomically, for the next relaunch."""
    if name not in load_sessions(root):
        raise LaunchError(f"no session {name!r} in {SESSIONS_FILE}")
    session_id(value, "session id")
    target = inside(root, STATE_DIR / f"{name}.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = inside(root, STATE_DIR / f".{name}.json.{os.getpid()}.tmp")
    temp.write_text(json.dumps({"session": value}) + "\n", encoding="utf-8")
    os.replace(temp, target)
    return target
