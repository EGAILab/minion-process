"""The `build`, `session`, `faults` and `dispatch` verbs of `minion-process` (kit 0.4.0).

    minion-process build broker --queue Q [--repair] [--serve]
    minion-process build submit --profile P --class C --launcher L --target T --checkout D [--sha S]
                                --pane P --session S
    minion-process build status --queue Q [--job N]
    minion-process build wait --queue Q --job N [--timeout S]
    minion-process build cancel|unretain --queue Q --job N --pane P --session S
    minion-process build release --queue Q --job N
    minion-process build policy --queue Q --file policy.yaml --decision <link>
    minion-process build repair --queue Q inspect|quarantine|resume
    minion-process build cleanup --profile P --copies C1,C2 --pane P --session S
    minion-process session start --profile P --agent A [--out report.yaml]
    minion-process faults check <matrix.yaml>
    minion-process dispatch <issue> --queue Q --pane P --session S [--mark-undelivered HASH:ATTEMPT]

Override requests (`release`, `policy`, `repair quarantine`, `repair resume`) print the challenge.
The Owner confirms it by typing `CONFIRM QUEUE <code>` in a Claude session (K-21). No agent ever types,
relays or sends keys for that code.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import yaml

from .. import faults
from . import client, layout
from .broker import Broker, BrokerRefused
from .framing import decode_single
from .journal import read as read_journal
from .markers import Markers
from .state import InvariantError, QueueState


def add_parsers(sub: Any) -> None:
    build = sub.add_parser("build")
    verbs = build.add_subparsers(dest="verb", required=True)
    broker = verbs.add_parser("broker")
    broker.add_argument("--queue", required=True)
    broker.add_argument("--repair", action="store_true")
    broker.add_argument("--serve", action="store_true")
    submit = verbs.add_parser("submit")
    for flag in ("--profile", "--class", "--launcher", "--target", "--checkout", "--pane", "--session"):
        submit.add_argument(flag, required=True, dest=flag[2:].replace("class", "klass"))
    submit.add_argument("--sha")
    submit.add_argument("--timeout", type=float, default=30.0)
    status = verbs.add_parser("status")
    status.add_argument("--queue", required=True)
    status.add_argument("--job", type=int)
    wait = verbs.add_parser("wait")
    wait.add_argument("--queue", required=True)
    wait.add_argument("--job", type=int, required=True)
    wait.add_argument("--timeout", type=float, default=3600.0)
    for name in ("cancel", "unretain"):
        verb = verbs.add_parser(name)
        verb.add_argument("--queue", required=True)
        verb.add_argument("--job", type=int, required=True)
        verb.add_argument("--pane", required=True)
        verb.add_argument("--session", required=True)
    release = verbs.add_parser("release")
    release.add_argument("--queue", required=True)
    release.add_argument("--job", type=int, required=True)
    policy = verbs.add_parser("policy")
    policy.add_argument("--queue", required=True)
    policy.add_argument("--file", required=True)
    policy.add_argument("--decision", required=True)
    repair = verbs.add_parser("repair")
    repair.add_argument("--queue", required=True)
    repair.add_argument("action", choices=["inspect", "quarantine", "resume"])
    cleanup = verbs.add_parser("cleanup")
    cleanup.add_argument("--profile", required=True)
    cleanup.add_argument("--copies", required=True)
    cleanup.add_argument("--pane", required=True)
    cleanup.add_argument("--session", required=True)
    session = sub.add_parser("session")
    session.add_argument("action", choices=["start"])
    session.add_argument("--profile", required=True)
    session.add_argument("--agent", required=True)
    session.add_argument("--out")
    fault = sub.add_parser("faults")
    fault.add_argument("action", choices=["check"])
    fault.add_argument("matrix")


def _queue_of(profile: str) -> Path:
    data = yaml.safe_load(Path(profile).read_text(encoding="utf-8")) or {}
    return Path(str((data.get("build_queue") or {})["state"]))


def _show(response: dict[str, Any]) -> int:
    print(json.dumps(response, indent=2, sort_keys=True))
    return 0 if response.get("ok") else 1


def run_build(args: Any, host_factory: Any = None, git_factory: Any = None) -> int:
    if args.verb == "broker":
        from .gitops import RealGit

        host = host_factory() if host_factory else _windows_host()
        broker = Broker(Path(args.queue), host, git_factory() if git_factory else RealGit())
        try:
            report = broker.start(repair=args.repair)
        except BrokerRefused as exc:
            print(f"REFUSED: {exc}")
            return 1
        print(
            json.dumps(
                {
                    "mode": report.mode,
                    "generation": report.generation,
                    "abandoned": report.abandoned,
                    "recovery": report.recovery,
                },
                indent=2,
            )
        )
        if not args.serve:
            broker.stop()
            return 0
        try:  # pragma: no cover - the long-running service loop; each step is tested directly
            while True:
                broker.step()
                time.sleep(1.0)
        finally:  # pragma: no cover
            broker.stop()
    if args.verb == "submit":
        queue = _queue_of(args.profile)
        request = {
            "type": "submit",
            "class": args.klass,
            "profile": str(Path(args.profile).resolve()),
            "launcher": args.launcher,
            "target": args.target,
            "checkout": str(Path(args.checkout).resolve()),
            "submitter": {"pane": args.pane, "session": args.session},
        }
        if args.sha:
            request["sha"] = args.sha
        return _call(queue, request, args.timeout)
    if args.verb == "cleanup":
        return _call(
            _queue_of(args.profile),
            {
                "type": "submit",
                "class": "cleanup",
                "profile": str(Path(args.profile).resolve()),
                "copies": args.copies.split(","),
                "submitter": {"pane": args.pane, "session": args.session},
            },
            30.0,
        )
    queue = Path(args.queue)
    if args.verb == "status":
        return _call(queue, {"type": "status", **({"job_id": args.job} if args.job else {})}, 30.0)
    if args.verb == "wait":
        code, job = client.wait_job(queue, args.job, args.timeout)
        print(json.dumps(job, indent=2, sort_keys=True))
        return code
    if args.verb in ("cancel", "unretain"):
        return _call(
            queue,
            {
                "type": args.verb,
                "job_id": args.job,
                "submitter": {"pane": args.pane, "session": args.session},
            },
            30.0,
        )
    if args.verb == "release":
        return _call(queue, {"type": "release", "job_id": args.job}, 30.0)
    if args.verb == "policy":
        policy = yaml.safe_load(Path(args.file).read_text(encoding="utf-8"))
        return _call(queue, {"type": "policy-set", "policy": policy, "decision": args.decision}, 30.0)
    return _call(queue, {"type": f"repair-{args.action}"}, 30.0)


def _call(queue: Path, request: dict[str, Any], timeout: float) -> int:
    try:
        return _show(client.call(queue, request, timeout))
    except client.Unavailable as exc:
        print(f"UNAVAILABLE: {exc}")
        return 3


def _windows_host() -> Any:  # pragma: no cover - only constructible on the Owner's Windows host
    from .winos import WindowsHostOS

    return WindowsHostOS()


# == session start (Part B) ==================================================================================


def _git(args: list[str], cwd: Path) -> tuple[int, str]:
    try:
        result = subprocess.run(
            ["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=120, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    return result.returncode, (result.stdout if result.returncode == 0 else result.stderr).strip()


def session_start(profile_path: Path, agent: str, gh_issues: Any = None) -> dict[str, Any]:
    """Read-only apart from `git fetch` metadata and the report file the caller writes. Any failed item
    makes the report partial; a partial report is never a green prerequisite (W-26)."""
    report: dict[str, Any] = {
        "partial": False,
        "failed": [],
        "repos": {},
        "work_packages": [],
        "queue": None,
        "cleanup_candidates": [],
    }

    def failed(item: str) -> None:
        report["partial"] = True
        report["failed"].append(item)

    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
    code, top = _git(["rev-parse", "--show-toplevel"], profile_path.parent)
    base = Path(top) if code == 0 else profile_path.parent
    for name, repo in (profile.get("repos") or {}).items():
        path = (base / str(repo.get("path", "."))).resolve()
        entry: dict[str, Any] = {"path": str(path)}
        fetch, out = _git(["fetch", "--quiet", "origin"], path)
        if fetch != 0:
            failed(f"repo {name}: fetch failed: {out}")
        code, branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], path)
        entry["branch"] = branch if code == 0 else None
        code, counts = _git(
            ["rev-list", "--left-right", "--count", f"HEAD...origin/{repo.get('default_branch', 'main')}"],
            path,
        )
        if code == 0 and len(counts.split()) == 2:
            entry["ahead"], entry["behind"] = (int(x) for x in counts.split())
        else:
            failed(f"repo {name}: drift unknown: {counts}")
        code, dirty = _git(["status", "--porcelain"], path)
        entry["dirty"] = bool(dirty) if code == 0 else None
        if code != 0:
            failed(f"repo {name}: status unknown")
        try:
            usage = shutil.disk_usage(path)
            entry["free_gb"] = round(usage.free / 1024**3, 1)
        except OSError as exc:
            failed(f"repo {name}: free space unknown: {exc}")
        report["repos"][name] = entry
    env = profile.get("environment")
    if env and not (base / str(env)).resolve().exists():
        failed(f"environment file missing: {env}")
    report["environment"] = env
    queue_dir = (profile.get("build_queue") or {}).get("state")
    if queue_dir:
        try:
            report["queue"], report["cleanup_candidates"] = _queue_summary(Path(str(queue_dir)))
        except (OSError, InvariantError, ValueError) as exc:
            failed(f"queue unreadable: {exc}")
    if gh_issues is not None:
        try:
            report["work_packages"] = [issue for issue in gh_issues() if issue.get("next_owner") == agent]
        except Exception as exc:  # any failure to list work packages makes the report partial
            failed(f"work packages unknown: {exc}")
    return report


def _queue_summary(queue: Path) -> tuple[dict[str, list[int]], list[str]]:
    """Read-only replay of the current generation. An unreadable generation marker or a missing journal
    is unknown, never an empty queue (K-36)."""
    markers = Markers(queue, None, "reader")  # type: ignore[arg-type]
    names = markers.names("generation")
    if not names:
        return {"running": [], "waiting": [], "uncertain": []}, []
    if not all(n.isdigit() for n in names):
        raise ValueError("unexpected generation marker name")
    generation = max(int(n) for n in names)
    if not isinstance(markers.read("generation", str(generation)), dict):
        raise ValueError(f"generation marker {generation} unreadable")
    path = layout.journal_path(queue, generation)
    if not path.exists():
        raise ValueError(f"journal for generation {generation} missing")
    replay = read_journal(path)
    if replay.anomaly is not None:
        raise ValueError(f"journal anomaly at {replay.anomaly.offset}: {replay.anomaly.reason}")
    state = QueueState()
    for record in replay.records:
        state.apply(record, 0.0)
    summary = {
        "running": [j.job_id for j in state.jobs.values() if j.status in ("launching", "running")],
        "waiting": [j.job_id for j in state.waiting()],
        "uncertain": [j.job_id for j in state.jobs.values() if j.status == "uncertain"],
    }
    candidates = []
    for copy_id, copy in sorted(state.copies.items()):
        creator = state.jobs.get(int(copy["creator"]))
        if (
            copy["state"] == "registered"
            and creator is not None
            and creator.status in ("ended", "refused")
            and not creator.retain
        ):
            candidates.append(copy_id)
    return summary, candidates


def run_session(args: Any, gh_issues: Any = None) -> int:
    report = session_start(Path(args.profile), args.agent, gh_issues)
    text = yaml.safe_dump(report, sort_keys=False)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text, end="")
    print("PARTIAL" if report["partial"] else "COMPLETE")
    return 1 if report["partial"] else 0


def run_faults(args: Any) -> int:
    try:
        matrix = yaml.safe_load(Path(args.matrix).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        print(f"ERROR: matrix unreadable: {exc}")
        return 1
    problems = faults.check(matrix)
    for problem in problems:
        print(problem)
    print("INVALID" if problems else "VALID")
    return 1 if problems else 0


# == dispatch --print (Part D, K-3, K-32) ===================================================================


def render_handoff(workflow: dict[str, Any], pane: str) -> str:
    candidate = workflow.get("current_candidate") or {}
    shas = ", ".join(
        f"{side} PR #{c.get('pr')} at {c.get('sha')}"
        for side, c in sorted(candidate.items())
        if isinstance(c, dict)
    )
    return "\n".join(
        [
            f"Work package {workflow['work_package']}: {workflow.get('title', '')}".rstrip(),
            f"Status {workflow['status']}; candidate: {shas or 'none'}.",
            f"Action for {workflow.get('next_owner')}: {workflow.get('next_action')}",
            f"Reply-to pane for this dispatch: {pane}. When the work item is done, blocked or "
            "needs a decision, "
            f"send a completion notification to {pane} (section 11.17) and stop.",
        ]
    )


def dispatch_print(queue: Path, text: str, pane: str, session: str) -> dict[str, Any]:
    return client.call(queue, {"type": "render", "text": text, "pane": pane, "session": session})


def mark_undelivered(queue: Path, handoff: str, attempt: int, session: str) -> dict[str, Any]:
    return client.call(
        queue, {"type": "undelivered", "hash": handoff, "attempt": attempt, "session": session}
    )


__all__ = [
    "add_parsers",
    "client",
    "decode_single",
    "dispatch_print",
    "mark_undelivered",
    "render_handoff",
    "run_build",
    "run_faults",
    "run_session",
    "session_start",
]
