"""`minion-process orch-render`: render the Orchestrator onboarding pack for one project (`orchestrator.md`).

The pack ships in `minion_process/bootstrap/orchestrator/` as templates with `{{NAME}}` placeholders. They
were made from M-Remote's reviewed and installed files (`minion-remote-docs` `4be18ceb`), with only the
project-specific strings replaced. Rendering them with M-Remote's values gives those files back byte for
byte (tests/test_orchestrator_pack.py).

`render_pack` reads a values file inside the project root and writes the rendered files into a new
folder inside the root. The project commits them in its opt-in PR for independent review, and the Owner
installs the reviewed bytes. Nothing is written outside the root, and an existing non-empty output
folder is refused rather than overwritten. Every placeholder must be known and every one must be used."""

from __future__ import annotations

import hashlib
import re
from importlib import resources
from pathlib import Path, PureWindowsPath
from typing import Any

import yaml

from .launch import LaunchError, inside, relative

PACKAGE = "minion_process.bootstrap"
FOLDER = "orchestrator"
# Template -> rendered file name, and which tool's sessions need it.
TEMPLATES = {
    "outside-root-guard.mjs.tmpl": ("outside-root-guard.mjs", "claude"),
    "guard-witness.mjs.tmpl": ("guard-witness.mjs", "claude"),
    "settings.json.tmpl": ("settings.json", "claude"),
    "orchestrator.rules.tmpl": ("{rules_file}", "codex"),
    "codex-launch.ps1.tmpl": ("codex-launch.ps1", "codex"),
    "entry-routing.md.tmpl": ("entry-routing.md", "all"),
    "witness-rows.md.tmpl": ("witness-rows.md", "all"),
}
PLACEHOLDER = re.compile(r"\{\{([A-Z][A-Z0-9_]*)\}\}")
SLUG = re.compile(r"^[a-z][a-z0-9-]{1,39}$")
GRU_NAME = re.compile(r"^gru-[a-z0-9-]{1,40}$")
RULES_FILE = re.compile(r"^[a-z][a-z0-9-]{0,39}\.rules$")
ISSUE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#[0-9]+$")
TEXT = re.compile(r"^[^\r\n{}\"`\\]{1,120}$")
KEYS = {
    "project", "slug", "short", "claude_sessions", "codex_sessions", "root", "home", "temp",
    "git_install", "exempt_decision", "read_exec_roots", "repos", "orchestrator", "issue", "rules_file",
}


class PackError(Exception):
    """A values file, template or output folder is not acceptable. Nothing was written."""


def _absolute(value: Any, where: str) -> str:
    """A plain absolute Windows path on a drive: no UNC, device, drive-relative, `..` or quote forms."""
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z]:\\[^\r\n\"*?<>|:]*", value):
        raise PackError(f"{where}: must be an absolute path such as C:\\Folder, got {value!r}")
    parts = PureWindowsPath(value).parts[1:]
    if any(p in (".", "..") for p in parts) or value.endswith("\\") or "\\\\" in value:
        raise PackError(f"{where}: no '.', '..', doubled or trailing separators, got {value!r}")
    return value


def _text(value: Any, where: str) -> str:
    if not isinstance(value, str) or not TEXT.fullmatch(value):
        raise PackError(f"{where}: must be one line of plain text without quotes, braces or backslashes")
    return value


def load_values(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict) or set(data) != KEYS:
        missing, extra = KEYS - set(data or {}), set(data or {}) - KEYS
        raise PackError(f"values: missing {sorted(missing)}, unknown {sorted(extra)}")
    for key in ("project", "short", "claude_sessions", "codex_sessions", "exempt_decision"):
        _text(data[key], key)
    if not SLUG.fullmatch(str(data["slug"])):
        raise PackError("slug: lowercase letters, digits and '-'")
    if not GRU_NAME.fullmatch(str(data["orchestrator"])):
        raise PackError("orchestrator: the Orchestrator's bound gru- name")
    if not ISSUE.fullmatch(str(data["issue"])):
        raise PackError("issue: owner/repo#N, the project's coordination issue")
    if not RULES_FILE.fullmatch(str(data["rules_file"])):
        raise PackError("rules_file: a lowercase file name ending in .rules")
    for key in ("root", "home", "temp", "git_install"):
        _absolute(data[key], key)
    if PureWindowsPath(data["root"]).name != data["project"]:
        raise PackError("root: its last folder must be the project name")
    roots = data["read_exec_roots"]
    if not isinstance(roots, list) or not roots:
        raise PackError("read_exec_roots: a non-empty list of absolute paths")
    for i, item in enumerate(roots):
        _absolute(item, f"read_exec_roots[{i}]")
    repos = data["repos"]
    if not isinstance(repos, list) or not repos:
        raise PackError("repos: a non-empty list of the project's repository folders, root-relative")
    for i, item in enumerate(repos):
        try:
            relative(item, f"repos[{i}]")
        except LaunchError as exc:
            raise PackError(str(exc)) from None
    return data


def _js(path: str) -> str:
    return path.replace("\\", "\\\\")


def mapping(v: dict[str, Any]) -> dict[str, str]:
    """Placeholder -> text. Derived forms (JS-escaped, '/'-separated, blocks) come only from here."""
    root_fwd = v["root"].replace("\\", "/")
    safe = [f"{root_fwd}/{repo}" for repo in v["repos"]]
    git_env = [f"$env:GIT_CONFIG_COUNT   = '{len(safe)}'"]
    for i, path in enumerate(safe):
        git_env += [f"$env:GIT_CONFIG_KEY_{i}   = 'safe.directory'", f"$env:GIT_CONFIG_VALUE_{i} = '{path}'"]
    return {
        "PROJECT": v["project"],
        "PROJECT_RE": re.sub(r"([.^$*+?()\[\]{}|/\\])", r"\\\1", v["project"]),
        "SLUG": v["slug"],
        "SHORT": v["short"],
        "CLAUDE_SESSION": v["claude_sessions"],
        "CODEX_SESSION": v["codex_sessions"],
        "ROOT": v["root"],
        "ROOT_FWD": root_fwd,
        "ROOT_JS": _js(v["root"]),
        "HOME_JS": _js(v["home"]),
        "TEMP_JS": _js(v["temp"]),
        "GIT_INSTALL_JS": _js(v["git_install"]),
        "EXEMPT_DECISION": v["exempt_decision"],
        "READ_EXEC_ROOTS_JS": "".join(f'    "{_js(p)}",\n' for p in v["read_exec_roots"]),
        "GIT_SAFE_DIRECTORIES_PS": "\n".join(git_env),
        "ORCHESTRATOR": v["orchestrator"],
        "ISSUE": v["issue"],
        "RULES_FILE": v["rules_file"],
    }


def template(name: str) -> str:
    return resources.files(PACKAGE).joinpath(FOLDER, name).read_text(encoding="utf-8")


def render(text: str, values: dict[str, str]) -> str:
    """Substitute every placeholder. An unknown placeholder, or a value that would leave one, refuses."""
    unknown = sorted(set(PLACEHOLDER.findall(text)) - set(values))
    if unknown:
        raise PackError(f"unknown placeholders {unknown}")
    out = PLACEHOLDER.sub(lambda m: values[m.group(1)], text)
    if "{{" in out or "}}" in out:
        raise PackError("a placeholder survived rendering")
    return out


def render_all(v: dict[str, Any]) -> dict[str, str]:
    values = mapping(load_values(v))
    files: dict[str, str] = {}
    for name, (target, _) in TEMPLATES.items():
        files[target.format(rules_file=v["rules_file"])] = render(template(name), values)
    return files


def render_pack(root: Path, values_file: str, out: str) -> list[tuple[str, str]]:
    """Render into `<root>/<out>`, a new or empty folder. Returns (file, sha256) pairs."""
    try:
        values_path = inside(root, relative(values_file, "--values"))
        out_dir = inside(root, relative(out, "--out"))
    except LaunchError as exc:
        raise PackError(str(exc)) from None
    try:
        data = yaml.safe_load(values_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise PackError(f"--values: {exc}") from None
    files = render_all(data)
    if out_dir.exists() and (not out_dir.is_dir() or any(out_dir.iterdir())):
        raise PackError(f"--out: {out_dir} exists and is not an empty folder; nothing written")
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[tuple[str, str]] = []
    for name, text in files.items():
        target = inside(root, relative(f"{out}/{name}", "--out"))
        data_bytes = text.encode("utf-8")
        with open(target, "xb") as fh:  # never over an existing file
            fh.write(data_bytes)
        written.append((name, hashlib.sha256(data_bytes).hexdigest()))
    return written
