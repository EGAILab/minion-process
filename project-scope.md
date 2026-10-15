# Project scope by default

**Rule (Owner, 2026-10-16):** everything an agent creates or configures lives in its project root. The
user-level folders of the agent tools are not written by agents, unless something really needs to be
there. This file says what goes where, what stays user-level and why, and how a project adopts it.
Rationale and the Owner's words: `lessons/PROJECT-SCOPE-2026-10-16.md`. Storage for gates and builds
is `WORKFLOW.md` §9.8.

In this file:
- **project root** is the root a profile names for the agent's workspace (`repos`/`environment`);
- **user-level folders** are the tools' home folders: Claude Code's `~/.claude` (or `CLAUDE_CONFIG_DIR`),
  Codex's `~/.codex` (or `CODEX_HOME`), and other tools' per-user configuration such as Git's global
  config and the GitHub CLI's config.

## PS-1. Agents read user-level folders; they do not write them

- An agent may **read** and **execute** in the user-level folders and in installed toolchains, for
  example to load a skill, run a compiler or read its own tool's documentation.
- An agent's tool calls **never write** there: no file writes, edits, moves or deletes, no
  `git config --global`, no `gh config set` or `gh auth`, no package installs into a user-level prefix.
- The tool itself still writes its own state there (see PS-4). That is not an agent action.
- Anything that really must change at user level is an **Owner action**: the agent states the exact
  change and why no project-scope option exists, and the Owner makes it.

## PS-2. Project-scope locations

| What | Claude Code | Codex |
|---|---|---|
| Instructions | `<root>/CLAUDE.md` or `<root>/.claude/CLAUDE.md` | `<root>/AGENTS.md` |
| Settings | `<root>/.claude/settings.json`; per machine `<root>/.claude/settings.local.json` | `<root>/.codex/config.toml`, for the keys Codex accepts there (it reports the keys it ignores); the rest on the launch line (PS-5) |
| Hooks | `<root>/.claude/hooks/`, registered in the project settings | `<root>/.codex/hooks` |
| Skills, agents, commands | `<root>/.claude/skills/`, `agents/`, `commands/` | `<root>/.agents/skills`, `<root>/.codex/agents` |
| MCP servers | `<root>/.mcp.json` | project config |
| Auto memory | `<root>/.claude/memory/`, set with `autoMemoryDirectory` in the project settings | `<root>`-scoped notes; no user-level memory |
| Temp and scratch | `TEMP`/`TMP` set to `<root>/.tmp` before launch | the same, plus the sandbox settings in PS-5 |

Notes:
- `autoMemoryDirectory` takes an absolute path; Claude Code shows a trust warning at launch when a project
  sets it. The warning is expected.
- A project's settings, hooks and the memory location are **Owner-controlled**: the project's guard
  refuses tool writes to `<root>/.claude/settings*.json`, `<root>/.claude/hooks/` and
  `<root>/.codex/config.toml`. A proposed change is committed for review and the Owner installs it.
- A project-scope location that the tool version in use does not support is recorded in the project's
  opt-in, with the fallback. It is never silently replaced by a user-level write.

## PS-3. Temp, caches and build outputs

Everything in `WORKFLOW.md` §9.8 goes under `<root>/.tmp/`: `TEMP`, `TMP`, `TMPDIR`, test base temps,
`CARGO_TARGET_DIR`, a private `CARGO_HOME`, `PUB_CACHE`, `GRADLE_USER_HOME`, the pip, uv, npm and yarn
caches, and linter and type-checker caches. They are set in the agent's environment file and on the
launch line, so a tool's default never falls back to the user temp folder.

## PS-4. What stays user-level, and who changes it

These are written by the tool or by the Owner, never by an agent's tool call:
- credentials and logins (Claude Code, Codex, the GitHub CLI, Git credential helpers);
- session transcripts, history, the tools' own caches, logs and update state;
- trust records the tool keeps (Codex project trust and hook trust hashes; Claude Code's accepted
  warnings);
- integrations installed by terminal multiplexers and status tools (for example herdr's agent-state hooks),
  which detect agents for every project;
- user-wide preferences the Owner chose (model, theme).

A user-level instruction file (`~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`) holds no project process
rule. Process rules live in the project.

## PS-5. Codex settings on the launch line

Codex ignores some keys in a project-local config (it lists them). The sandbox and approval settings are
therefore given on the launch line, so no user-level config change is needed and rollback is a relaunch:

```text
codex [resume <session-id>] -C <root> -s workspace-write -a on-request \
  -c sandbox_workspace_write.network_access=true \
  -c sandbox_workspace_write.exclude_tmpdir_env_var=true \
  -c sandbox_workspace_write.exclude_slash_tmp=true
```

`network_access` is on only when the project needs it (for example `git push` and `gh`). With
`on-request`, a command that needs more is asked of the Owner. An Owner approval marked "always" is
stored at user level by Codex; the Owner prefers one-time approvals for project-specific commands.

## PS-6. Full isolation, only if really needed

`CLAUDE_CONFIG_DIR` and `CODEX_HOME` move a tool's entire user-level folder, credentials included, into
a folder the Owner names. That gives complete separation at the cost of a separate login and separate
integrations per project. It is not the default. A project uses it only with an Owner decision that
records why PS-1 to PS-5 are not enough.

## PS-7. Enforcement

- **Claude Code:** the project's `PreToolUse` guard refuses writes outside the root, which includes the
  user-level folders, and refuses writes to its own settings, hooks and memory location setting.
- **Codex:** the `workspace-write` sandbox with the root as the only writable root (PS-5).
- On native Windows a shell command can reach paths a hook parser does not see. The guarantee there is
  the rule plus the hook; the gap is recorded in the project's opt-in.

## Adoption checklist

1. List what the project currently keeps at user level: memory folders, user-level skills it depends on,
   "always" approvals, user-level hooks, temp and cache locations.
2. Move each to its PS-2 or PS-3 location, or record why it stays user-level (PS-4) or the fallback.
3. Migrate existing auto-memory: after the Owner installs `autoMemoryDirectory`, the agent copies its
   memory files from the user-level folder into `<root>/.claude/memory/` (read outside, write inside) and
   lists them. The user-level copies are left for the Owner to remove.
4. Install the guard and the Codex launch line (PS-7) as Owner actions, and run the guard's witness rows.
5. Record the result on the project's coordination issue.
