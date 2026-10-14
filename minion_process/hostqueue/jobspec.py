"""Building and revalidating a job's frozen inputs (B-7, B-10 to B-15).

The broker builds a job spec when it accepts a submit request. That spec is everything the job will
execute: the resolved launcher, the canonical paths, the environment and the leases. At launch the broker
builds the spec again from the same request and compares the two. Any difference refuses the job as input
drift (W-13).
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import yaml

from .contain import Contained, assert_inside
from .policy import Policy
from .resources import EXCLUSIVE, SHARED, canonical

PLACEHOLDERS = ("checkout", "target", "log", "job_label", "workdir")
DEFAULT_INHERIT = ["PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC"]


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


def _inside(roots: list[str], path: str, what: str) -> str:
    try:
        assert_inside([Path(r) for r in roots], Path(path))
    except Contained as exc:
        raise SpecError(f"{what} is not contained: {exc}") from None
    return canonical(path)


def build_spec(
    request: dict[str, Any], policy: Policy, queue_id: str, job_id: int, pane_info: dict[str, Any] | None
) -> dict[str, Any]:
    """Resolve a submit request into a frozen job spec, or raise `SpecError`."""
    klass = request.get("class")
    if klass not in ("evidence", "build", "control", "cleanup"):
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
    exec_root = _inside(roots, str(queue_cfg.get("exec_root", "")), "exec_root")
    log_root = _inside(roots, str(queue_cfg.get("log_root", "")), "log_root")
    workdir = os.path.join(exec_root, f"{queue_id}-job-{job_id}")
    spec: dict[str, Any] = {
        "job_id": job_id,
        "class": klass,
        "project": project,
        "profile": str(request["profile"]),
        "profile_hash": profile_hash,
        "submitter": {"pane": submitter["pane"], "session": submitter["session"], "agent": agent},
        "roots": roots,
        "log": os.path.join(log_root, f"{queue_id}-job-{job_id}.log"),
        "job_label": f"{queue_id}-{job_id}",
        "group": f"minion-job-{queue_id}-{job_id}",
    }
    if klass == "cleanup":
        copies = request.get("copies")
        if not isinstance(copies, list) or not copies or not all(isinstance(c, str) for c in copies):
            raise SpecError("cleanup needs a list of registered copy ids")
        spec["copies"] = list(copies)
        spec["apply"] = request.get("apply") is True  # dry run unless the request explicitly applies (Part C)
        spec["leases"] = []  # filled by the broker from the registry, which owns the copy paths
        spec["downgrade_after_prepare"] = None
        return spec
    gates = profile.get("gates")
    gate = gates.get(request.get("launcher")) if isinstance(gates, dict) else None
    if not isinstance(gate, dict) or not isinstance(gate.get("queue"), dict):
        raise SpecError(f"launcher {request.get('launcher')!r} has no queue definition in the profile")
    launcher = gate["queue"]
    argv = launcher.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
        raise SpecError("launcher argv must be a non-empty list of strings")
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
    target_path = _inside(roots, str(target.get("path", "")), "target")
    checkout = _inside(roots, str(request.get("checkout", "")), "checkout")
    sha = request.get("sha")
    bad_sha = not isinstance(sha, str) or len(sha) != 40 or any(c not in "0123456789abcdef" for c in sha)
    if klass in ("evidence", "control") and bad_sha:
        raise SpecError(f"{klass} jobs need --sha with a 40-hex commit")
    run_dir = workdir if klass in ("evidence", "control") else checkout
    values = {
        "checkout": run_dir,
        "target": target_path,
        "log": spec["log"],
        "job_label": spec["job_label"],
        "workdir": workdir,
    }
    job_tmp = os.path.join(exec_root, f"{queue_id}-job-{job_id}-tmp")
    caches = queue_cfg.get("caches") or {}
    if not isinstance(caches, dict):
        raise SpecError("build_queue.caches must be a mapping")
    cache_env = launcher.get("cache_env") or {}
    if not isinstance(cache_env, dict):
        raise SpecError("cache_env must be a mapping")
    cache_paths: dict[str, str] = {}
    for var, name in cache_env.items():
        if name not in caches:
            raise SpecError(
                f"cache_env.{var} names cache {name!r}, which build_queue.caches does not declare"
            )
        cache_paths[str(var)] = _inside(roots, str(caches[name]), f"cache {name!r}")
    bound = {
        "target": target_path,
        "run_dir": run_dir,
        "workdir": workdir,
        "log": spec["log"],
        "tmp": job_tmp,
    }
    owned_dirs = [run_dir, workdir, job_tmp]  # writable locations owned by this job alone

    def allowed(path: str, where: str) -> str:
        """A host path the job may name: a leased resource exactly, or a path inside one it owns."""
        canon = _inside(roots, path, where)
        exact = {canonical(v) for v in (*bound.values(), *cache_paths.values())}
        if canon in exact or any(canon.startswith(canonical(d) + os.sep) for d in owned_dirs):
            return canon
        raise SpecError(f"{where} names {path!r}, which is not a leased resource of this job (B-14)")

    resolved = [_substitute(a, values) for a in argv]
    for token in resolved:
        for candidate in _path_like(token):
            allowed(candidate, f"argv path {candidate!r}")
    reserved = {*(str(v) for v in launcher.get("target_env") or []), *cache_paths, "TMP", "TEMP", "TMPDIR"}
    env: dict[str, str] = {}
    inherit = queue_cfg.get("inherit_env", DEFAULT_INHERIT)
    if not isinstance(inherit, list) or not all(isinstance(v, str) for v in inherit):
        raise SpecError("build_queue.inherit_env must be a list of variable names")
    for var in inherit:
        if var in reserved:
            raise SpecError(f"inherit_env may not name the bound variable {var}")
        if var in os.environ:
            env[var] = os.environ[var]  # frozen at submit, compared again at launch (B-10)
    for key, value in (launcher.get("env") or {}).items():
        if str(key) in reserved:
            raise SpecError(f"launcher env may not set the bound variable {key} (B-14)")
        text = _substitute(str(value), values)
        for candidate in _path_like(text):
            allowed(candidate, f"env {key} path {candidate!r}")
        env[str(key)] = text
    for var in launcher.get("target_env") or []:
        env[str(var)] = target_path
    env.update(cache_paths)
    for var in ("TMP", "TEMP", "TMPDIR"):
        env[var] = job_tmp
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
            "workdir": workdir if klass in ("evidence", "control") else None,
            "run_dir": run_dir,
            "argv": resolved,
            "env": env,
            "tmp": job_tmp,
            "source_globs": list(globs),
            "container": bool(launcher.get("container", False)),
        }
    )
    leases = [[target_path, EXCLUSIVE], [job_tmp, EXCLUSIVE]]
    leases += [[path, SHARED] for path in sorted(set(cache_paths.values()))]
    if klass == "build":
        leases.append([checkout, EXCLUSIVE])
        spec["downgrade_after_prepare"] = checkout
    else:
        leases.append([checkout, SHARED])
        leases.append([workdir, EXCLUSIVE])
        spec["downgrade_after_prepare"] = None
    spec["leases"] = leases
    return spec


def _substitute(text: str, values: dict[str, str]) -> str:
    for name in PLACEHOLDERS:
        text = text.replace("{" + name + "}", values[name])
    return text


def _path_like(token: str) -> list[str]:
    """Host paths inside an argv token, including `--opt=path` forms and `host:container[:mode]` mount
    specs. On a Windows host a host path starts with a drive letter. A drive-less rooted path such as
    `/t` is container-internal and is not a host path. On a POSIX host a leading `/` is a host path up to
    the first `:`."""
    found: list[str] = []
    for piece in token.replace("=", "\n").split("\n"):
        if len(piece) > 2 and piece[0].isalpha() and piece[1] == ":" and piece[2] in "\\/":
            found.append(piece[:2] + piece[2:].split(":", 1)[0])
        found += [piece.split(":", 1)[0]] if (piece.startswith("/") and os.sep == "/") else []
    return found


def drift(original: dict[str, Any], rebuilt: dict[str, Any]) -> list[str]:
    """Fields of the frozen spec that differ when rebuilt at launch (B-10)."""
    keys = sorted(set(original) | set(rebuilt))
    return [k for k in keys if original.get(k) != rebuilt.get(k)]
