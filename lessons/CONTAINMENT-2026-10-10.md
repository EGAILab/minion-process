# CONTAINMENT-2026-10-10 — a relative `..` chain resolved to the drive root and was removed recursively

**Supports:** `WORKFLOW.md` §9.8 (storage inside the project root; containment before destructive
operations) and every role file's containment section.
**Source:** Minion-Agent `CLAUDE.md`, "Filesystem containment (Owner rule, 2026-10-10)", verbatim. The
retrospective record (`docs/origin.md`) §2.6 records the incident row.

> On 2026-10-10 a characterization probe resolved a relative `..`-chain target to the drive root `E:\` and ran a recursive remove on it, deleting a large amount of the Owner's data across E:. To keep that from happening again:
>
> - **Every file change outside the project root `E:\AI\Projects\OpenMinds\Minions\Minion-Agent` needs the Owner's explicit confirmation before it happens.** That covers writes, edits, moves, renames, deletes, permission changes, installs and Docker bind mounts. Reading outside the root is fine. For Claude this is enforced by the PreToolUse hook `.claude/hooks/outside-root-guard.mjs` (`.claude/settings.json`). For Codex it is a binding rule: ask the Owner on the user channel first and wait for the answer.
> - **Scripts, probes, tests and negative controls** that write, rename or delete paths computed at runtime must:
>   - create their sandbox strictly inside the project root, never from `os.tmpdir()` / `tempfile` defaults that can fall back to C:;
>   - call a containment check on **every** target before **every** destructive or writing operation, including rename destinations, cleanup and `rm -r`: lexical resolution, then the real path through links. Node helper: `.tmp/claude-scratch/lib/fs-guard.mjs` (`makeSandbox`, `assertInside`);
>   - never take `..` chains, drive-relative forms (`X:foo`, which means *drive X*), bare drive letters, UNC paths or absolute paths as targets of destructive operations. Prefix relative names that contain `:` with `./`;
>   - fail closed: a containment failure aborts that case, and nothing runs with the unchecked path.
> - **Destructive probe matrices** (conditions × remove/rename/write) are reviewed for target containment before their first run. Unexpected results such as "drive root"-like rows, `is_directory` for a path that should not exist, or unexplained slowness mean **stop and investigate**; never rerun.
> - When an operation may have touched something outside the root, stop all work, pause the other agent, and report to the Owner immediately.
> - **Owner clarification (confirmed by the Owner in chat, 2026-10-10):** a Docker container's private `--tmpfs /tmp`, and its other container-internal paths, are **not** host files. Writes there need no confirmation. Host bind mounts must be inside the project root, and writable E: mounts only within it. Fixtures inside the container still assert containment within their own sandbox.
> - **Approval codes:** outside-root changes by Claude are hard-blocked until the Owner types the exact `APPROVE OUTSIDE <code>` that the block shows. No agent may ever type, relay as input, or send keys for such a code into another pane.
> - **Agent-to-agent keystrokes:** never send Enter or other keys to the other agent's pane while it is `blocked` or showing a question/permission dialog. A keypress there can answer an Owner-only prompt. Check `herdr agent get` first; if the pane is blocked, do not send, and retry later.

The kit's generic rule (project roots from the profile; containment check before every destructive
operation; fail closed; never send keys to a blocked pane) is in `WORKFLOW.md` §9.8 and §11.17. The
replay for the containment check is P3 work (`replay/`).
