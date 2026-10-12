"""The GitHub side, through the `gh` CLI. Every call goes through an injectable runner so the
deterministic rules can be tested offline."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from typing import Any

from .model import normalize

CODE_REPO = "EGAILab/minion-agent"
DOCS_REPO = "EGAILab/minion-agent-docs"
REPOS = {"code": CODE_REPO, "docs": DOCS_REPO}

Runner = Callable[[list[str], str | None], str]


class GitHubError(RuntimeError):
    pass


def gh_runner(args: list[str], stdin: str | None) -> str:
    """Run `gh` with `stdin` passed as ONE document (never a line array; §11.1.1)."""
    result = subprocess.run(["gh", *args], input=stdin, capture_output=True, text=True, encoding="utf-8")
    if result.returncode:
        raise GitHubError(f"gh {' '.join(args[:3])} failed: {result.stderr.strip()}")
    return result.stdout


class GitHub:
    def __init__(self, run: Runner = gh_runner) -> None:
        self._run = run

    def issue(self, repo: str, number: int) -> dict[str, Any]:
        out = self._run(["issue", "view", str(number), "-R", repo, "--json", "body,state,title"], None)
        data: dict[str, Any] = json.loads(out)
        return data

    def issue_revisions(self, repo: str, number: int) -> list[tuple[str, str]]:
        """The issue body's edit history from GitHub itself, newest first: (revision id, full body)."""
        owner, name = repo.split("/", 1)
        query = (
            "query($o:String!,$n:String!,$i:Int!,$c:String){repository(owner:$o,name:$n){issue(number:$i)"
            "{userContentEdits(first:100,after:$c){pageInfo{hasNextPage endCursor}nodes{id diff}}}}}"
        )
        revisions: list[tuple[str, str]] = []
        cursor: str | None = None
        while True:
            args = [
                "api",
                "graphql",
                "-f",
                f"query={query}",
                "-F",
                f"o={owner}",
                "-F",
                f"n={name}",
                "-F",
                f"i={number}",
            ]
            if cursor:
                args += ["-F", f"c={cursor}"]
            page = json.loads(self._run(args, None))["data"]["repository"]["issue"]["userContentEdits"]
            revisions += [
                (node["id"], node["diff"]) for node in page["nodes"] if isinstance(node.get("diff"), str)
            ]
            if not page["pageInfo"]["hasNextPage"]:
                return revisions
            cursor = page["pageInfo"]["endCursor"]

    def edit_issue_body(self, repo: str, number: int, body: str) -> None:
        self._run(["issue", "edit", str(number), "-R", repo, "--body-file", "-"], body)

    def pr(self, repo: str, number: int) -> dict[str, Any]:
        fields = "state,isDraft,headRefOid,mergeable,baseRefName,mergeCommit,title"
        data: dict[str, Any] = json.loads(
            self._run(["pr", "view", str(number), "-R", repo, "--json", fields], None)
        )
        return data

    def commit_exists(self, repo: str, sha: str) -> bool:
        try:
            self._run(["api", f"repos/{repo}/commits/{sha}", "--jq", ".sha"], None)
        except GitHubError:
            return False
        return True

    def default_branch(self, repo: str) -> str:
        return self._run(["api", f"repos/{repo}", "--jq", ".default_branch"], None).strip()

    def contains(self, repo: str, branch: str, sha: str) -> bool:
        """Whether `sha` is reachable from `branch` (post-merge containment)."""
        status = self._run(["api", f"repos/{repo}/compare/{sha}...{branch}", "--jq", ".status"], None).strip()
        return status in ("identical", "ahead")

    def merge_squash(self, repo: str, number: int, sha: str) -> None:
        self._run(["pr", "merge", str(number), "-R", repo, "--squash", "--match-head-commit", sha], None)

    def comment(self, repo: str, number: int, body: str, kind: str = "issue") -> str:
        url = self._run([kind, "comment", str(number), "-R", repo, "--body-file", "-"], body)
        return url.strip()

    def comment_body(self, repo: str, comment_id: str) -> str:
        return self._run(["api", f"repos/{repo}/issues/comments/{comment_id}", "--jq", ".body"], None)


def same_text(a: str, b: str) -> bool:
    """Equal as one multiline document, ignoring CRLF/BOM and trailing newlines."""
    return normalize(a).rstrip("\n") == normalize(b).rstrip("\n")
