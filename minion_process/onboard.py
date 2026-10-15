"""`minion-process onboard`: what a project still has to do to move from one kit version to another.

Every kit release from 0.4.0 on ships a manifest, `minion_process/releases/<version>.yaml`, listing the
adoption steps that release adds. `onboard` reads the manifests of every version after `--from` up to and
including `--to`, runs each step's check against the project root, and prints a checklist. It is
read-only: it never changes the project, and a step without an automatic check is listed as `MANUAL`
for the project to record on its coordination issue.

A step applies to the tools the project uses: those named in `<root>/.minion/sessions.yaml` when it
exists, otherwise both. Check kinds:

- `exists`: a root-relative path exists;
- `json_equals`: a JSON file holds `value` at the dotted `key` (`{root}` in the value is the root,
  written with '/');
- `contains`: a text file contains `text`;
- `manual`: no automatic check."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from .launch import SESSIONS_FILE, LaunchError, inside, load_sessions, relative

SEMVER = re.compile(r"^([0-9]+)\.([0-9]+)\.([0-9]+)$")
STEP_ID = re.compile(r"^[A-Z][A-Z0-9-]{1,39}$")
ACTORS = frozenset({"owner", "agent"})
APPLIES = frozenset({"all", "claude", "codex"})
KINDS = {
    "exists": {"path"},
    "json_equals": {"path", "key", "value"},
    "contains": {"path", "text"},
    "manual": set(),
}


class ManifestError(Exception):
    """A release manifest or a version argument is malformed. Nothing was checked."""


@dataclass(frozen=True)
class Result:
    version: str
    step: str
    title: str
    actor: str
    status: str  # PASS | TODO | MANUAL
    detail: str

    def line(self) -> str:
        tail = f": {self.detail}" if self.detail else ""
        return f"{self.status:<6} {self.version} {self.step} [{self.actor}] {self.title}{tail}"


def version_key(value: str) -> tuple[int, int, int]:
    m = SEMVER.fullmatch(value)
    if m is None:
        raise ManifestError(f"not a MAJOR.MINOR.PATCH version: {value!r}")
    return int(m[1]), int(m[2]), int(m[3])


def available() -> list[str]:
    names = [
        p.name[:-5] for p in resources.files("minion_process.releases").iterdir() if p.name.endswith(".yaml")
    ]
    return sorted(names, key=version_key)


def load_manifest(version: str) -> dict[str, Any]:
    version_key(version)
    try:
        text = resources.files("minion_process.releases").joinpath(f"{version}.yaml").read_text("utf-8")
    except FileNotFoundError:
        raise ManifestError(f"no manifest for kit {version}") from None
    data = yaml.safe_load(text)
    if not isinstance(data, dict) or set(data) != {"version", "summary", "steps"}:
        raise ManifestError(f"{version}: a manifest has exactly version, summary, steps")
    if data["version"] != version:
        raise ManifestError(f"{version}: the manifest says version {data['version']!r}")
    if not isinstance(data["summary"], str) or not data["summary"].strip():
        raise ManifestError(f"{version}: summary must be a non-empty string")
    if not isinstance(data["steps"], list) or not data["steps"]:
        raise ManifestError(f"{version}: steps must be a non-empty list")
    seen: set[str] = set()
    for i, step in enumerate(data["steps"]):
        _step(version, i, step, seen)
    return data


def _step(version: str, i: int, step: Any, seen: set[str]) -> None:
    where = f"{version}: steps[{i}]"
    if not isinstance(step, dict) or set(step) != {"id", "title", "actor", "applies", "check"}:
        raise ManifestError(f"{where}: a step has exactly id, title, actor, applies, check")
    if not isinstance(step["id"], str) or STEP_ID.fullmatch(step["id"]) is None or step["id"] in seen:
        raise ManifestError(f"{where}.id: must be a unique upper-case id")
    seen.add(step["id"])
    if not isinstance(step["title"], str) or not step["title"].strip():
        raise ManifestError(f"{where}.title: must be a non-empty string")
    if step["actor"] not in ACTORS:
        raise ManifestError(f"{where}.actor: must be one of {sorted(ACTORS)}")
    if step["applies"] not in APPLIES:
        raise ManifestError(f"{where}.applies: must be one of {sorted(APPLIES)}")
    check = step["check"]
    if not isinstance(check, dict) or check.get("kind") not in KINDS:
        raise ManifestError(f"{where}.check.kind: must be one of {sorted(KINDS)}")
    if set(check) != {"kind"} | KINDS[check["kind"]]:
        raise ManifestError(f"{where}.check: {check['kind']} takes exactly {sorted(KINDS[check['kind']])}")
    for field in ("key", "value", "text"):
        if field in check and (not isinstance(check[field], str) or not check[field]):
            raise ManifestError(f"{where}.check.{field}: must be a non-empty string")
    if "path" in check:
        try:
            relative(check["path"], f"{where}.check.path")
        except LaunchError as exc:
            raise ManifestError(str(exc)) from None


def between(start: str, end: str) -> list[str]:
    low, high = version_key(start), version_key(end)
    if high <= low:
        raise ManifestError(f"--to {end} must be later than --from {start}")
    chosen = [v for v in available() if low < version_key(v) <= high]
    if end not in chosen:
        raise ManifestError(f"no manifest for kit {end}")
    return chosen


def tools(root: Path) -> set[str]:
    try:
        inside(root, SESSIONS_FILE).stat()
    except FileNotFoundError:
        return {"claude", "codex"}
    return {entry["tool"] for entry in load_sessions(root).values()}


def _run(root: Path, check: dict[str, Any]) -> tuple[bool, str]:
    kind = check["kind"]
    path = inside(root, relative(check["path"], "check.path"))
    if kind == "exists":
        return path.exists(), "" if path.exists() else f"{check['path']} missing"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return False, f"{check['path']} missing"
    if kind == "contains":
        return check["text"] in text, "" if check[
            "text"
        ] in text else f"{check['text']!r} not in {check['path']}"
    try:
        node: Any = json.loads(text)
    except ValueError:
        return False, f"{check['path']} is not valid JSON"
    for part in check["key"].split("."):
        node = node.get(part) if isinstance(node, dict) else None
    want = check["value"].replace("{root}", root.resolve().as_posix())
    got = node.replace("\\", "/") if isinstance(node, str) else node
    ok = isinstance(got, str) and got.casefold() == want.casefold()
    return ok, "" if ok else f"{check['key']} is {node!r}, expected {want!r}"


def onboard(root: Path, start: str, end: str) -> list[Result]:
    used = tools(root)
    results: list[Result] = []
    for version in between(start, end):
        for step in load_manifest(version)["steps"]:
            if step["applies"] != "all" and step["applies"] not in used:
                continue
            if step["check"]["kind"] == "manual":
                status, detail = "MANUAL", ""
            else:
                ok, detail = _run(root, step["check"])
                status = "PASS" if ok else "TODO"
            results.append(Result(version, step["id"], step["title"], step["actor"], status, detail))
    return results


def markdown(results: list[Result], start: str, end: str) -> str:
    lines = [f"### Kit onboarding {start} -> {end}", ""]
    for r in results:
        box = "x" if r.status == "PASS" else " "
        tail = f" ({r.detail})" if r.detail else ""
        lines.append(f"- [{box}] `{r.version}` **{r.step}** [{r.actor}] {r.title}: {r.status}{tail}")
    return "\n".join(lines) + "\n"
