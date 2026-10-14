"""Building and revalidating a job's frozen inputs (B-7, B-10 to B-15, K-42).

The broker builds a job spec when it accepts a submit request. That spec is everything the job will
execute: the resolved launcher, the canonical paths, the environment and the leases. At launch the broker
builds the spec again from the same request and compares the two. Any difference refuses the job as input
drift (W-13).

**Slots, not recognizers (K-42, revisions 9 to 11).** The binding never splits or scans a runtime value.
The profile's launcher template says where every path is, and the kit checks the exact string the tool
receives:

- **Path slots.** A placeholder appears only in a path slot, written in the profile as a mapping
  `{slot: <template>, access: read|write}`. The slot forms are:
  1. a whole argv element: `{p}` plus an optional suffix;
  2. an option assignment: a literal option name ending in `=`, then `{p}` plus an optional suffix;
  3. a mount source, in a container launcher only, after a literal `-v`, `--volume` or `--mount`: `{p}`
     plus an optional suffix, a literal `:` and a container path declared under `container.paths`;
  4. an environment value: exactly `{p}`.

  A suffix is a separator followed by relative components, none of them `.` or `..`. The slot's
  effective value is the substituted placeholder plus its suffix, never split. The declared access must
  be one the placeholder's lease permits (`{checkout}` is read only).
- **Literals.** Any other argv element, and any launcher `env` value that is not a slot, is a literal. A
  literal has no separator (except a declared container path, as a whole element of a container
  launcher), no letter followed by a colon at its start or after `=`, `;`, `,` or `:`, no `..`, no control
  character and no placeholder other than `{job_label}`.
- **Writable-location variables** (`WRITABLE_LOCATION`) are set only by the kit, from `target_env`,
  `cache_env` and the job's temporary folder. Variable names are compared case-insensitively; two names
  that differ only by case are refused.
- **Inherited variables** come from a closed allow-list of read-only classes (`INHERITABLE`). Any other
  name in `inherit_env` is refused; a tool cache is bound through `cache_env` (R003).
- **Leased resource spellings.** A leased path containing `=`, `;`, a quote, a backtick or a control
  character is refused, so it can never be put into a slot.
- **Working folder.** Every job runs in a folder it leases exclusively: the execution worktree for
  `evidence` and `control`, and a fresh per-job folder for `build`, which reaches its checkout only
  through `{checkout}`.

The launch proof of every writable directory resource (K-42a') is the broker's (`broker._launch`).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

import yaml

from .contain import Contained, assert_inside
from .policy import Policy
from .resources import EXCLUSIVE, SHARED, canonical

READ = "read"
WRITE = "write"
# Path placeholders and the access each one's lease permits (K-42c).
PATH_ACCESS: dict[str, frozenset[str]] = {
    "checkout": frozenset({READ}),
    "workdir": frozenset({READ, WRITE}),
    "target": frozenset({READ, WRITE}),
    "tmp": frozenset({READ, WRITE}),
    "log": frozenset({READ, WRITE}),
}
LEAF_PLACEHOLDERS = frozenset({"log"})  # a file: no suffix
MOUNT_FLAGS = ("-v", "--volume", "--mount")
DEFAULT_INHERIT = ["PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC"]
WRITABLE_LOCATION = frozenset(
    {
        "CARGO_HOME",
        "RUSTUP_HOME",
        "CARGO_TARGET_DIR",
        "CARGO_BUILD_TARGET_DIR",
        "PIP_CACHE_DIR",
        "UV_CACHE_DIR",
        "NPM_CONFIG_CACHE",
        "YARN_CACHE_FOLDER",
        "HOME",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
        "TMP",
        "TEMP",
        "TMPDIR",
    }
)
WRITABLE_PREFIXES = ("XDG_",)
# R003: the inherited-variable domain is closed. A host variable is inherited only when the kit knows it as
# one of these read-only classes. Every other name is refused, so a writable location (a tool cache such
# as NODE_COMPILE_CACHE or PYTHONPYCACHEPREFIX) can never pass as a search value by being absent from a
# list. A tool cache is bound to a declared, leased cache through `cache_env` instead.
INHERITABLE: dict[str, tuple[str, ...]] = {
    "search path": ("PATH", "PATHEXT"),
    "read-only system location": (
        "SYSTEMROOT",
        "SYSTEMDRIVE",
        "WINDIR",
        "COMSPEC",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "PROGRAMW6432",
        "COMMONPROGRAMFILES",
        "COMMONPROGRAMFILES(X86)",
        "COMMONPROGRAMW6432",
    ),
    "host identity": (
        "OS",
        "COMPUTERNAME",
        "USERNAME",
        "USERDOMAIN",
        "NUMBER_OF_PROCESSORS",
        "PROCESSOR_ARCHITECTURE",
        "PROCESSOR_IDENTIFIER",
        "PROCESSOR_LEVEL",
        "PROCESSOR_REVISION",
    ),
    "locale": ("LANG", "LANGUAGE", "LC_ALL", "LC_CTYPE", "TZ"),
}
_INHERITABLE = frozenset(name for names in INHERITABLE.values() for name in names)
KIT_VARIABLES = ("MINION_JOB", "MINION_JOB_GROUP")
UNSUPPORTED_CLASSES = {"cleanup": "cleanup is not supported in 0.4.0"}  # K-47

_PLACEHOLDER = re.compile(r"\{([A-Za-z_]+)\}")
_WHOLE = re.compile(r"^\{([A-Za-z_]+)\}(.*)$", re.DOTALL)
_OPTION = re.compile(r"^(--?[A-Za-z0-9][A-Za-z0-9_.-]*=)\{([A-Za-z_]+)\}(.*)$", re.DOTALL)
_MOUNT = re.compile(r"^\{([A-Za-z_]+)\}([^:]*):(.*)$", re.DOTALL)
_DRIVE_AT_BOUNDARY = re.compile(r"(^|[=;,:])[A-Za-z]:")
_BAD_SPELLING = re.compile(r"[=;\"'`\x00-\x1f\x7f]")
_BAD_COMPONENT = re.compile(r"[<>:\"|?*=;,'`\x00-\x1f\x7f]")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class SpecError(ValueError):
    """The request cannot become a job; the reason is returned to the client."""


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode("utf-8")).hexdigest()


def _load_profile(path: str) -> tuple[dict[str, Any], str]:
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise SpecError(f"profile unreadable: {exc}") from None
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise SpecError(f"profile is not YAML: {exc}") from None
    if not isinstance(data, dict):
        raise SpecError("profile is not a mapping")
    return data, hashlib.sha256(raw).hexdigest()


def spelling_problem(path: str) -> str | None:
    """Why a resource path cannot be put into a slot, or None (K-42, W-98a)."""
    found = _BAD_SPELLING.search(path)
    if found is None:
        return None
    return f"contains {found.group(0)!r}, which a slot value may not carry"


def _resource(roots: list[str], path: str, what: str) -> str:
    """A leased resource: contained, canonical, and spelled without a slot delimiter."""
    try:
        assert_inside([Path(r) for r in roots], Path(path))
    except Contained as exc:
        raise SpecError(f"{what} is not contained: {exc}") from None
    canon = canonical(path)
    problem = spelling_problem(canon)
    if problem:
        raise SpecError(f"{what} {canon!r} {problem} (W-98a)")
    return canon


def is_writable_location(name: str) -> bool:
    upper = name.upper()
    return upper in WRITABLE_LOCATION or upper.startswith(WRITABLE_PREFIXES)


def literal_problem(text: str, container_paths: tuple[str, ...] = ()) -> str | None:
    """Why `text` cannot be a literal argv element or env value, or None (K-42)."""
    if text in container_paths:
        return None
    if _PLACEHOLDER.search(text.replace("{job_label}", "")):
        return "a placeholder may appear only in a declared path slot"
    if _CONTROL.search(text):
        return "contains a control character"
    if "\\" in text or "/" in text:
        return "contains a path separator; a path must come through a placeholder slot"
    if _DRIVE_AT_BOUNDARY.search(text):
        return "contains a drive letter and colon"
    if ".." in text:
        return "contains '..'"
    return None


def container_path_problem(path: str) -> str | None:
    """A declared container path is an absolute POSIX path of plain components."""
    if not path.startswith("/") or path.startswith("//"):
        return "must be an absolute container path starting with one '/'"
    return suffix_problem(path) if path != "/" else None


def suffix_problem(suffix: str) -> str | None:
    """A slot suffix is empty, or a separator followed by relative components without `.` or `..`."""
    if not suffix:
        return None
    if suffix[0] not in "\\/":
        return f"suffix {suffix!r} must begin with a separator"
    for part in re.split(r"[\\/]", suffix[1:]):
        if part in ("", ".", ".."):
            return f"suffix {suffix!r} has an empty, '.' or '..' component"
        if _BAD_COMPONENT.search(part) or part.endswith((" ", ".")):
            return f"suffix component {part!r} is not a plain name"
    return None


def _slot(
    raw: Any, where: str, values: dict[str, str], container_paths: tuple[str, ...], mount: bool, env: bool
) -> tuple[str, dict[str, Any]]:
    """The effective value of one declared path slot, and its record."""
    if not isinstance(raw, dict) or set(raw) != {"slot", "access"}:
        raise SpecError(f"{where}: a path slot is a mapping with exactly 'slot' and 'access'")
    template, access = raw["slot"], raw["access"]
    if not isinstance(template, str) or access not in (READ, WRITE):
        raise SpecError(f"{where}: slot must be a string and access read or write (K-42c)")
    prefix, container = "", None
    if env:
        whole = _WHOLE.match(template)
        if whole is None or whole.group(2):
            raise SpecError(f"{where}: an environment slot is exactly one placeholder")
        name, suffix = whole.group(1), ""
    elif mount:
        found = _MOUNT.match(template)
        if found is None:
            raise SpecError(f"{where}: a mount slot is {{p}}[suffix]:<declared container path>")
        name, suffix, container = found.group(1), found.group(2), found.group(3)
        if container not in container_paths:
            raise SpecError(f"{where}: container path {container!r} is not declared in container.paths")
    else:
        option = _OPTION.match(template)
        whole = _WHOLE.match(template)
        if option is not None:
            prefix, name, suffix = option.group(1), option.group(2), option.group(3)
        elif whole is not None:
            name, suffix = whole.group(1), whole.group(2)
        else:
            raise SpecError(f"{where}: {template!r} is not a whole-element or option slot")
    if name not in PATH_ACCESS:
        raise SpecError(f"{where}: {{{name}}} is not a path placeholder")
    if access not in PATH_ACCESS[name]:
        raise SpecError(f"{where}: {{{name}}} cannot be given {access} access (K-42c)")
    problem = suffix_problem(suffix)
    if problem is None and suffix and name in LEAF_PLACEHOLDERS:
        problem = f"{{{name}}} is a file and takes no suffix"
    if problem:
        raise SpecError(f"{where}: {problem}")
    effective = values[name] + suffix.replace("/", os.sep).replace("\\", os.sep)
    text = prefix + effective + (f":{container}" if container is not None else "")
    return text, {"where": where, "placeholder": name, "access": access, "value": effective}


def build_spec(
    request: dict[str, Any], policy: Policy, queue_id: str, job_id: int, pane_info: dict[str, Any] | None
) -> dict[str, Any]:
    """Resolve a submit request into a frozen job spec, or raise `SpecError`."""
    klass = request.get("class")
    if klass in UNSUPPORTED_CLASSES:
        raise SpecError(UNSUPPORTED_CLASSES[str(klass)])
    if klass not in ("evidence", "build", "control"):
        raise SpecError(f"unknown class {klass!r}")
    profile, profile_hash = _load_profile(str(request.get("profile", "")))
    queue_cfg = profile.get("build_queue")
    if not isinstance(queue_cfg, dict):
        raise SpecError("profile has no build_queue section")
    if queue_cfg.get("policy_id") != policy.policy_id:
        raise SpecError(
            f"profile expects policy {queue_cfg.get('policy_id')!r}, host policy is {policy.policy_id!r}"
        )
    project = queue_cfg.get("project")
    if project not in policy.projects:
        raise SpecError(f"project {project!r} is not in the host policy allow-list")
    roots = [canonical(r) for r in policy.projects[project]]
    submitter = request.get("submitter")
    if not isinstance(submitter, dict) or not submitter.get("pane") or not submitter.get("session"):
        raise SpecError("submitter pane and agent session are required")
    if pane_info is None:
        raise SpecError(f"submitter pane {submitter['pane']} cannot be read")
    session = (
        (pane_info.get("agent_session") or {}).get("value")
        if isinstance(pane_info.get("agent_session"), dict)
        else None
    )
    if session != submitter["session"]:
        raise SpecError("submitter session does not match its pane (B-15)")
    agent = str(pane_info.get("agent", ""))
    exec_root = _resource(roots, str(queue_cfg.get("exec_root", "")), "exec_root")
    log_root = _resource(roots, str(queue_cfg.get("log_root", "")), "log_root")
    workdir = _resource(roots, os.path.join(exec_root, f"{queue_id}-job-{job_id}"), "working folder")
    job_tmp = _resource(roots, os.path.join(exec_root, f"{queue_id}-job-{job_id}-tmp"), "temporary folder")
    log = _resource(roots, os.path.join(log_root, f"{queue_id}-job-{job_id}.log"), "log")
    spec: dict[str, Any] = {
        "job_id": job_id,
        "class": klass,
        "project": project,
        "profile": str(request["profile"]),
        "profile_hash": profile_hash,
        "submitter": {"pane": submitter["pane"], "session": submitter["session"], "agent": agent},
        "roots": roots,
        "log": log,
        "log_dir": log_root,
        "job_label": f"{queue_id}-{job_id}",
        "group": f"minion-job-{queue_id}-{job_id}",
    }
    gates = profile.get("gates")
    gate = gates.get(request.get("launcher")) if isinstance(gates, dict) else None
    if not isinstance(gate, dict) or not isinstance(gate.get("queue"), dict):
        raise SpecError(f"launcher {request.get('launcher')!r} has no queue definition in the profile")
    launcher = gate["queue"]
    argv = launcher.get("argv")
    if not isinstance(argv, list) or not argv:
        raise SpecError("launcher argv must be a non-empty list")
    targets = queue_cfg.get("targets")
    target = targets.get(request.get("target")) if isinstance(targets, dict) else None
    if not isinstance(target, dict):
        raise SpecError(f"target {request.get('target')!r} is not declared in the profile")
    kind = target.get("kind")
    if kind not in ("gate", "controls", "reviewer"):
        raise SpecError(f"target kind {kind!r} is not gate, controls or reviewer")
    if klass == "control" and kind != "controls":
        raise SpecError(
            "a control job may use only a controls-kind target, "
            "never a gate or reviewer gate cache (B-6, B-13)"
        )
    if klass in ("evidence", "build") and kind == "controls":
        raise SpecError("evidence and build jobs never use a controls target (B-6)")
    if target.get("owner_agent") and target["owner_agent"] != agent:
        raise SpecError(
            f"target {request['target']!r} belongs to {target['owner_agent']}, not {agent} (B-15)"
        )
    target_path = _resource(roots, str(target.get("path", "")), "target")
    checkout = _resource(roots, str(request.get("checkout", "")), "checkout")
    sha = request.get("sha")
    bad_sha = not isinstance(sha, str) or len(sha) != 40 or any(c not in "0123456789abcdef" for c in sha)
    if klass in ("evidence", "control") and bad_sha:
        raise SpecError(f"{klass} jobs need --sha with a 40-hex commit")
    container = launcher.get("container", False)
    if container is False or container is None:
        container_paths: tuple[str, ...] = ()
    elif isinstance(container, dict) and isinstance(container.get("paths"), list) and container["paths"]:
        container_paths = tuple(str(p) for p in container["paths"])
        for path in container_paths:
            problem = container_path_problem(path)
            if problem:
                raise SpecError(f"container path {path!r}: {problem}")
    else:
        raise SpecError("container must be false or a mapping with a non-empty paths list")
    values = {
        "checkout": workdir if klass in ("evidence", "control") else checkout,
        "workdir": workdir,
        "target": target_path,
        "tmp": job_tmp,
        "log": log,
    }
    slots: list[dict[str, Any]] = []
    resolved: list[str] = []
    for index, raw in enumerate(argv):
        where = f"argv[{index}]"
        if isinstance(raw, str):
            problem = literal_problem(raw, container_paths)
            if problem:
                raise SpecError(f"{where} {raw!r}: {problem} (K-42)")
            resolved.append(raw.replace("{job_label}", spec["job_label"]))
            continue
        mount = bool(container_paths) and index > 0 and argv[index - 1] in MOUNT_FLAGS
        text, record = _slot(raw, where, values, container_paths, mount, env=False)
        resolved.append(text)
        slots.append(record)
    caches = queue_cfg.get("caches") or {}
    if not isinstance(caches, dict):
        raise SpecError("build_queue.caches must be a mapping")
    cache_env = launcher.get("cache_env") or {}
    if not isinstance(cache_env, dict):
        raise SpecError("cache_env must be a mapping")
    names: dict[str, str] = {}

    def claim(name: Any, source: str) -> str:
        if not isinstance(name, str) or not name:
            raise SpecError(f"{source}: variable names are non-empty strings")
        folded = name.upper()
        if folded in names:
            raise SpecError(f"{source}: {name} repeats {names[folded]} (names compare case-insensitively)")
        names[folded] = f"{source} {name}"
        return name

    for var in KIT_VARIABLES:
        claim(var, "kit")
    env: dict[str, str] = {}
    for var in ("TMP", "TEMP", "TMPDIR"):
        env[claim(var, "kit temporary folder")] = job_tmp
    for var in launcher.get("target_env") or []:
        env[claim(var, "target_env")] = target_path
    cache_paths: dict[str, str] = {}
    for var, name in cache_env.items():
        if name not in caches:
            raise SpecError(
                f"cache_env.{var} names cache {name!r}, which build_queue.caches does not declare"
            )
        cache_paths[claim(var, "cache_env")] = _resource(roots, str(caches[name]), f"cache {name!r}")
    env.update(cache_paths)
    for key, raw in (launcher.get("env") or {}).items():
        claim(key, "launcher env")
        if is_writable_location(str(key)):
            raise SpecError(f"launcher env may not set the writable-location variable {key} (K-42)")
        if isinstance(raw, str):
            problem = literal_problem(raw)
            if problem:
                raise SpecError(f"env {key} {raw!r}: {problem} (K-42)")
            env[str(key)] = raw.replace("{job_label}", spec["job_label"])
            continue
        text, record = _slot(raw, f"env {key}", values, (), mount=False, env=True)
        env[str(key)] = text
        slots.append(record)
    inherit = queue_cfg.get("inherit_env", DEFAULT_INHERIT)
    if not isinstance(inherit, list):
        raise SpecError("build_queue.inherit_env must be a list of variable names")
    for var in inherit:
        claim(var, "inherit_env")
        if str(var).upper() not in _INHERITABLE:
            raise SpecError(
                f"inherit_env may name only a read-only search, system, identity or locale variable, not "
                f"{var} (K-42, R003); bind a tool cache through cache_env"
            )
        if var in os.environ:
            env[str(var)] = os.environ[var]  # read-only search paths, frozen at submit (B-10)
    globs = launcher.get("source_globs") or []
    if klass == "build" and not globs:
        raise SpecError("a build launcher needs source_globs for the freshness step (K-12a)")
    spec.update(
        {
            "launcher": request["launcher"],
            "launcher_def": launcher,
            "launcher_hash": _digest(launcher),
            "checkout": checkout,
            "sha": sha,
            "target": {"name": request["target"], "path": target_path, "kind": kind},
            "workdir": workdir,
            "run_dir": workdir,
            "argv": resolved,
            "env": env,
            "slots": slots,
            "tmp": job_tmp,
            "caches": sorted(set(cache_paths.values())),
            "source_globs": list(globs),
            "container": list(container_paths),
        }
    )
    leases = [[target_path, EXCLUSIVE], [job_tmp, EXCLUSIVE], [workdir, EXCLUSIVE]]
    leases += [[path, SHARED] for path in spec["caches"]]
    if klass == "build":
        leases.append([checkout, EXCLUSIVE])
        spec["downgrade_after_prepare"] = checkout
    else:
        leases.append([checkout, SHARED])
        spec["downgrade_after_prepare"] = None
    spec["leases"] = leases
    return spec


def drift(original: dict[str, Any], rebuilt: dict[str, Any]) -> list[str]:
    """Fields of the frozen spec that differ when rebuilt at launch (B-10)."""
    keys = sorted(set(original) | set(rebuilt))
    return [k for k in keys if original.get(k) != rebuilt.get(k)]
