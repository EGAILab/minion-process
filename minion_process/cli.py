"""`minion-process`: deterministic workflow mechanics. Semantics stay with the agents.

    python -m minion_process profile validate <profile.yaml>
    python -m minion_process review-check <review-record.md>
    python -m minion_process status <issue>
    python -m minion_process validate <issue> | --file <body.md>
    python -m minion_process transition-check <FROM> <TO>
    python -m minion_process apply <issue> <patch.py> [--dry-run]
    python -m minion_process handoff <issue> --to <owner> --action <text> [--status <S>] [--sha side=<sha>]...
    python -m minion_process close <issue> --comment-file <file> [--dry-run]
    python -m minion_process handoff-check <issue>
    python -m minion_process candidate-check <issue> [--ready]
    python -m minion_process convergence counters <issue>
    python -m minion_process metrics <issue> [--out <file>]
    python -m minion_process merge <code|docs|owner/repo> <pr> <sha>
    python -m minion_process comment <code|docs|owner/repo> <number> <file> [--pr]
    python -m minion_process build <verb> ...   (see `minion_process.hostqueue.commands`)
    python -m minion_process session start --profile <profile.yaml> --agent <claude|codex> [--out <file>]
    python -m minion_process faults check <matrix.yaml>
    python -m minion_process dispatch <issue> --queue <dir> --pane <pane> --session <id>
                                     [--mark-undelivered HASH:N]

A patch file for `apply` defines `apply(workflow)` (mutates it; may return replacement prose) and
`ALLOWED` (the set of top-level workflow keys it may change)."""

from __future__ import annotations

import argparse
import json
import runpy
import sys
from pathlib import Path
from typing import Any

import yaml

from .composite import close as composite_close
from .composite import handoff as composite_handoff
from .github import CODE_REPO, REPOS, GitHub
from .hostqueue import commands as hostqueue_commands
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
from .review import (
    Copy,
    Selection,
    UnreadComment,
    counters,
    metrics,
    parse_review_records,
    select_reviews,
    trigger_statement,
    validate_review,
)
from .transitions import check_transition
from .validate import errors, validate_workflow


def _repo(name: str) -> str:
    return REPOS.get(name, name)


def _collect_reviews(gh: GitHub, repo: str, number: int) -> tuple[dict[str, Any], Selection]:
    """The state block plus the review events published on the issue and its candidate PRs
    (`CE-PROC-P3A-01`): every comment's claims become copies carrying the remote's publication metadata;
    `select_reviews` groups them into distinct events, mirrors, conflicts and invalid headers."""
    workflow = split_body(gh.issue(repo, number)["body"]).workflow
    invalid = errors(validate_workflow(workflow))
    if invalid:
        raise CheckFailed("current state invalid: " + "; ".join(map(str, invalid)))
    comments = list(gh.issue_comments(repo, number))
    for side, entry in candidates(workflow).items():
        if isinstance(entry, dict) and entry.get("pr"):
            comments += gh.issue_comments(REPOS[side], int(entry["pr"]))
    copies: list[Copy] = []
    unread: list[int | None] = []
    for comment in comments:
        try:
            claims = parse_review_records(comment["body"])
        except UnreadComment:  # R11: the whole comment is excluded, visibly; nothing partial is credited
            unread.append(comment["id"])
            continue
        copies += [Copy(comment["created_at"], comment["id"], claim) for claim in claims]
    return workflow, select_reviews(copies, str(workflow["work_package"]), unread)


def main(argv: list[str] | None = None, gh: GitHub | None = None) -> int:
    parser = argparse.ArgumentParser(prog="minion-process", description=__doc__.split("\n")[0])
    parser.add_argument("--repo", default=CODE_REPO, help="coordination-issue repository")
    sub = parser.add_subparsers(dest="command", required=True)
    profile = sub.add_parser("profile")
    profile.add_argument("action", choices=["validate"])
    profile.add_argument("path")
    sub.add_parser("review-check").add_argument("file")
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
    handoff = sub.add_parser("handoff")
    handoff.add_argument("issue", type=int)
    handoff.add_argument("--to", required=True)
    handoff.add_argument("--action", required=True)
    handoff.add_argument("--status")
    handoff.add_argument("--sha", action="append", default=[], metavar="SIDE=SHA")
    handoff.add_argument("--dry-run", action="store_true")
    close = sub.add_parser("close")
    close.add_argument("issue", type=int)
    close.add_argument("--comment-file", required=True)
    close.add_argument("--dry-run", action="store_true")
    sub.add_parser("handoff-check").add_argument("issue", type=int)
    candidate = sub.add_parser("candidate-check")
    candidate.add_argument("issue", type=int)
    candidate.add_argument("--ready", action="store_true")
    convergence = sub.add_parser("convergence")
    convergence.add_argument("action", choices=["counters"])
    convergence.add_argument("issue", type=int)
    metrics_cmd = sub.add_parser("metrics")
    metrics_cmd.add_argument("issue", type=int)
    metrics_cmd.add_argument("--out")
    merge = sub.add_parser("merge")
    merge.add_argument("repo")
    merge.add_argument("pr", type=int)
    merge.add_argument("sha")
    comment = sub.add_parser("comment")
    comment.add_argument("repo")
    comment.add_argument("number", type=int)
    comment.add_argument("file")
    comment.add_argument("--pr", action="store_true")
    hostqueue_commands.add_parsers(sub)
    dispatch = sub.add_parser("dispatch")
    dispatch.add_argument("issue", type=int)
    dispatch.add_argument("--queue", required=True)
    dispatch.add_argument("--pane", required=True)
    dispatch.add_argument("--session", required=True)
    dispatch.add_argument("--mark-undelivered", metavar="HASH:ATTEMPT")
    args = parser.parse_args(argv)

    if args.command == "profile":  # offline: no `gh`, no network
        _, problems = load_profile(Path(args.path))
        for problem in problems:
            print(problem)
        print("INVALID" if errors(problems) else "VALID")
        return 1 if errors(problems) else 0
    if args.command == "review-check":  # offline
        try:
            claims = parse_review_records(Path(args.file).read_text(encoding="utf-8"))
        except UnreadComment as exc:
            print(f"ERROR: review: the record could not be fully read by the Markdown parser ({exc})")
            print("INVALID")
            return 1
        if len(claims) != 1:
            print(f"ERROR: review: expected exactly one `review:` header, found {len(claims)}")
            print("INVALID")
            return 1
        if claims[0].reason is not None:
            print(f"ERROR: review: {claims[0].reason}")
            print("INVALID")
            return 1
        problems = validate_review(claims[0].record)
        for problem in problems:
            print(problem)
        print("INVALID" if errors(problems) else "VALID")
        return 1 if errors(problems) else 0

    if args.command == "build":  # offline: the queue folder only
        return hostqueue_commands.run_build(args)
    if args.command == "faults":  # offline
        return hostqueue_commands.run_faults(args)

    gh = gh or GitHub()

    if args.command == "session":
        client = gh

        def issues() -> list[dict[str, Any]]:
            found = []
            for issue in client.open_issues(args.repo):
                try:
                    workflow = split_body(issue["body"]).workflow
                except BodyFormatError:
                    continue
                found.append(
                    {
                        "issue": issue["number"],
                        "work_package": workflow.get("work_package"),
                        "next_owner": workflow.get("next_owner"),
                        "status": workflow.get("status"),
                    }
                )
            return found

        return hostqueue_commands.run_session(args, issues)
    if args.command == "dispatch":
        queue = Path(args.queue)
        try:
            if args.mark_undelivered:
                handoff, _, attempt = args.mark_undelivered.partition(":")
                response = hostqueue_commands.mark_undelivered(queue, handoff, int(attempt), args.session)
            else:
                report = handoff_report(gh, args.repo, args.issue)
                if report.failed:
                    for label in report.failed:
                        print(f"  FAIL {label}")
                    print("HANDOFF_BLOCKED")
                    return 1
                workflow = split_body(gh.issue(args.repo, args.issue)["body"]).workflow
                text = hostqueue_commands.render_handoff(workflow, args.pane)
                response = hostqueue_commands.dispatch_print(queue, text, args.pane, args.session)
        except hostqueue_commands.client.Unavailable as exc:
            print(f"UNAVAILABLE: {exc}")
            return 3
        if response.get("ok") and "text" in response:
            print(response["text"])
            print(
                f"-- render {response['hash']} attempt {response['attempt']}: may-have-printed; "
                "delivery is the project's helper, never the kit (K-1)"
            )
            return 0
        print(json.dumps(response, indent=2, sort_keys=True))
        return 0 if response.get("ok") else 1

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
        if args.command == "handoff":
            shas: dict[str, str] = {}
            for item in args.sha:
                side, _, sha = item.partition("=")
                shas[side] = sha
            changed, report = composite_handoff(
                gh, args.repo, args.issue, args.to, args.action, args.status, shas, args.dry_run
            )
            for label in report.ok:
                print(f"  ok   {label}")
            print(
                ("DRY-RUN OK " if args.dry_run else "HANDED OFF ") + f"#{args.issue} -> {args.to} {changed}"
            )
            return 0
        if args.command == "close":
            text = Path(args.comment_file).read_text(encoding="utf-8")
            changed, merged = composite_close(gh, args.repo, args.issue, text, args.dry_run)
            for side, oid in sorted(merged.items()):
                print(f"  ok   {side} merged {oid}")
            print(("DRY-RUN OK " if args.dry_run else "CLOSED ") + f"#{args.issue} {changed}")
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
        if args.command == "convergence":
            _, selection = _collect_reviews(gh, args.repo, args.issue)
            print(trigger_statement(counters(selection)))
            return 0
        if args.command == "metrics":
            workflow, selection = _collect_reviews(gh, args.repo, args.issue)
            text = yaml.safe_dump(metrics(workflow, selection), sort_keys=False)
            if args.out:
                Path(args.out).write_text(text, encoding="utf-8")
                print(f"metrics written to {args.out}")
            else:
                print(text, end="")
            return 0
        if args.command == "merge":
            merged_sha = guarded_merge(gh, _repo(args.repo), args.pr, args.sha)
            print(f"MERGED #{args.pr} -> {merged_sha} (reachable from the default branch)")
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
