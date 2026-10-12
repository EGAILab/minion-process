"""`minion-process`: deterministic workflow mechanics. Semantics stay with the agents.

    python -m minion_process profile validate <profile.yaml>
    python -m minion_process status <issue>
    python -m minion_process validate <issue> | --file <body.md>
    python -m minion_process transition-check <FROM> <TO>
    python -m minion_process apply <issue> <patch.py> [--dry-run]
    python -m minion_process handoff-check <issue>
    python -m minion_process candidate-check <issue> [--ready]
    python -m minion_process merge <code|docs|owner/repo> <pr> <sha>
    python -m minion_process comment <code|docs|owner/repo> <number> <file> [--pr]

A patch file for `apply` defines `apply(workflow)` (mutates it; may return replacement prose) and
`ALLOWED` (the set of top-level workflow keys it may change)."""

from __future__ import annotations

import argparse
import runpy
import sys
from pathlib import Path

from .github import CODE_REPO, REPOS, GitHub
from .model import BodyFormatError, candidates, split_body
from .ops import (
    CheckFailed,
    candidate_report,
    commit_state,
    guarded_merge,
    handoff_report,
    restore_revision,
    verified_comment,
)
from .profile import load_profile
from .transitions import check_transition
from .validate import errors, validate_workflow


def _repo(name: str) -> str:
    return REPOS.get(name, name)


def main(argv: list[str] | None = None, gh: GitHub | None = None) -> int:
    parser = argparse.ArgumentParser(prog="minion-process", description=__doc__.split("\n")[0])
    parser.add_argument("--repo", default=CODE_REPO, help="coordination-issue repository")
    sub = parser.add_subparsers(dest="command", required=True)
    profile = sub.add_parser("profile")
    profile.add_argument("action", choices=["validate"])
    profile.add_argument("path")
    sub.add_parser("status").add_argument("issue", type=int)
    validate = sub.add_parser("validate")
    validate.add_argument("issue", type=int, nargs="?")
    validate.add_argument("--file")
    transition = sub.add_parser("transition-check")
    transition.add_argument("old")
    transition.add_argument("new")
    apply = sub.add_parser("apply")
    apply.add_argument("issue", type=int)
    apply.add_argument("patch", nargs="?")
    apply.add_argument("--dry-run", action="store_true")
    apply.add_argument("--repair", action="store_true", help="restore an earlier revision (restore only)")
    apply.add_argument("--revision", help="the issue edit-history revision id to restore (with --repair)")
    sub.add_parser("handoff-check").add_argument("issue", type=int)
    candidate = sub.add_parser("candidate-check")
    candidate.add_argument("issue", type=int)
    candidate.add_argument("--ready", action="store_true")
    merge = sub.add_parser("merge")
    merge.add_argument("repo")
    merge.add_argument("pr", type=int)
    merge.add_argument("sha")
    comment = sub.add_parser("comment")
    comment.add_argument("repo")
    comment.add_argument("number", type=int)
    comment.add_argument("file")
    comment.add_argument("--pr", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "profile":  # offline: no `gh`, no network
        _, problems = load_profile(Path(args.path))
        for problem in problems:
            print(problem)
        print("INVALID" if errors(problems) else "VALID")
        return 1 if errors(problems) else 0

    gh = gh or GitHub()

    try:
        if args.command == "transition-check":
            reason = check_transition(args.old, args.new)
            print(reason or f"LEGAL {args.old} -> {args.new}")
            return 1 if reason else 0
        if args.command == "validate":
            if args.file:
                text = Path(args.file).read_text(encoding="utf-8")
            elif args.issue is not None:
                text = gh.issue(args.repo, args.issue)["body"]
            else:
                parser.error("validate needs an issue number or --file")
            problems = validate_workflow(split_body(text).workflow, len(text))
            for problem in problems:
                print(problem)
            print("INVALID" if errors(problems) else "VALID")
            return 1 if errors(problems) else 0
        if args.command == "status":
            issue = gh.issue(args.repo, args.issue)
            w = split_body(issue["body"]).workflow
            invalid = errors(validate_workflow(w))
            if invalid:  # rule 4: diagnostics, never a traceback on malformed state
                for problem in invalid:
                    print(problem)
                print(f"#{args.issue} INVALID")
                return 1
            conv = w.get("convergence") or {}
            print(f"#{args.issue} [{issue['state']}] {w['work_package']}: {w['status']}")
            for side, entry in candidates(w).items():  # rule 8: the one accessor, v1 and v2 alike
                entry = entry or {}
                print(f"  {side}: PR {entry.get('pr')} sha {entry.get('sha')}")
            print(f"  open findings: {w.get('open_findings') or conv.get('open_findings') or []}")
            print(f"  next: {w.get('next_owner')} -- {w.get('next_action')}")
            print(f"  body: {len(issue['body'])} chars")
            return 0
        if args.command == "apply" and args.repair:
            if not args.revision or args.patch:
                parser.error("--repair takes --revision <id> and no patch: it only restores (CE-PROC-L13-01)")
            restore_revision(gh, args.repo, args.issue, args.revision, args.dry_run)
            print(
                ("DRY-RUN " if args.dry_run else "")
                + f"RESTORED #{args.issue} to {args.revision} (current state was invalid)"
            )
            return 0
        if args.command == "apply":
            if not args.patch:
                parser.error("apply needs a patch file (or --repair --revision <id>)")
            patch = runpy.run_path(args.patch)
            changed, _ = commit_state(
                gh, args.repo, args.issue, patch["apply"], set(patch["ALLOWED"]), args.dry_run
            )
            print(("DRY-RUN OK " if args.dry_run else "COMMITTED ") + f"#{args.issue} {changed}")
            return 0
        if args.command in ("handoff-check", "candidate-check"):
            if args.command == "handoff-check":
                report = handoff_report(gh, args.repo, args.issue)
                verdict = "HANDOFF_BLOCKED"
            else:
                w = split_body(gh.issue(args.repo, args.issue)["body"]).workflow
                report = candidate_report(gh, w, args.ready)
                verdict = "CANDIDATE_INVALID"
            for label in report.ok:
                print(f"  ok   {label}")
            for label in report.failed:
                print(f"  FAIL {label}")
            print(verdict if report.failed else "OK")
            return 1 if report.failed else 0
        if args.command == "merge":
            merged = guarded_merge(gh, _repo(args.repo), args.pr, args.sha)
            print(f"MERGED #{args.pr} -> {merged} (reachable from the default branch)")
            return 0
        if args.command == "comment":
            text = Path(args.file).read_text(encoding="utf-8")
            kind = "pr" if args.pr else "issue"
            print(verified_comment(gh, _repo(args.repo), args.number, text, kind), "byte-verified")
            return 0
    except (CheckFailed, BodyFormatError) as failure:
        print(failure, file=sys.stderr)
        return 1
    return 2  # pragma: no cover  (argparse requires a known command)
