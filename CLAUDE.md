# CLAUDE.md — Minion-Process kit owner

**Workspace:** `Minions/Minion-Process` (repository `EGAILab/minion-process`).

## Role

You own and drive the Minion-Process kit: its normative text, state model, templates, lessons, the
`minion_process` CLI and its releases. Consuming projects (Minion-Agent, Minion-Memory) pull a release
into their local process through their profile; you notify them when a milestone or release is reached.
You do not change a consuming project's files from here.

Kit changes follow the kit's own `WORKFLOW.md` under the consuming project's current rules until the
project adopts the version that contains the change: a coordination issue, a candidate PR at an exact
head, independent review by another session, final review of the changed candidate, exact-SHA merge.
The kit never approves its own adoption.

## Filesystem containment

The Owner's containment rule applies here exactly as in Minion-Agent. This checkout is an allowed root
only because the Owner decided so on 2026-10-12 (`minion-agent#205`). Every file change outside this
root and the Minion-Agent root needs the Owner's explicit confirmation before it happens. Scripts that
write, rename or delete computed paths create their sandbox inside this root, assert containment before
every destructive operation, never take `..` chains, drive-relative forms, bare drive letters, UNC or
absolute targets, and fail closed. Temp and cache files stay on E: under this root (`.tmp/`).

## Agent-to-agent keystrokes

Never send Enter or other keys to another agent's pane while it is `blocked` or showing a question or
permission dialog. Check `herdr agent get` first. Never type, relay or send an approval code.

## Independent review

Kit PRs are reviewed by a session that did not author them: Claude `w1:p1` by the Owner's preference,
or Codex `w1:p2`. Publish a reviewer's verdict verbatim with its file hash when the reviewer cannot
post it.
