"""Git operations the broker needs for execution copies (B-12, B-13). A seam, so tests run without git."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Protocol


class GitOps(Protocol):
    def add_worktree(self, source: Path, workdir: Path, sha: str) -> None: ...

    def head(self, workdir: Path) -> str | None: ...

    def clean(self, workdir: Path) -> bool | None: ...


class RealGit:
    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", *args], capture_output=True, text=True, check=False)

    def add_worktree(self, source: Path, workdir: Path, sha: str) -> None:
        result = self._run(["-C", str(source), "worktree", "add", "--detach", str(workdir), sha])
        if result.returncode != 0:
            raise OSError(f"git worktree add failed: {result.stderr.strip()}")

    def head(self, workdir: Path) -> str | None:
        result = self._run(["-C", str(workdir), "rev-parse", "HEAD"])
        return result.stdout.strip() if result.returncode == 0 else None

    def clean(self, workdir: Path) -> bool | None:
        result = self._run(["-C", str(workdir), "status", "--porcelain", "--untracked-files=all"])
        return (result.stdout.strip() == "") if result.returncode == 0 else None
