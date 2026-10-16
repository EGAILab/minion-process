---
name: kit-onboard
description: Move this project to the Minion-Process kit release installed in .minion/kit.json. Use when the Owner or the Orchestrator asks to onboard or upgrade the project to a kit version, or to check what is left of an onboarding. Runs the onboard checklist, does the agent-side steps, prepares every Owner step as exact commands, and records the result on the project's coordination issue.
---

# Kit onboarding (agent side)

You are an agent of this project. This skill moves the project to the kit release installed in
`.minion/kit.json`, under the project's own rules. The kit's rules are in `project-scope.md` and
`onboarding.md` of that release.

## Hard limits

- **Never write control files.** These are `.claude/settings*.json`, `.claude/hooks/`, `.claude/skills/`,
  `.codex/`, `.agents/` and `.minion/`. You prepare them as a reviewed commit in the project's repository
  and the Owner installs them. A future Orchestrator rollout may install them instead, but only under an
  Owner-ordered `ROLLOUT`, never at your request.
- **Never write user-level folders** (`~/.claude`, `~/.codex`, global Git or `gh` config). Reading them
  is allowed.
- **Never send keys** to any pane, never restart your own session, never type or relay an approval code.
- Work and temp files go under `<root>/.tmp/`.

## Steps

Run every command from the project root. `PY` is the `python` value in `.minion/kit.json`. Always call it
as `PY -I -m minion_process ...`.

1. **Where are we.** Read `.minion/kit.json` (installed version) and the profile's `kit.version` (current
   pin). If `kit.json` is missing, stop. The kit is not installed yet: give the Owner the install command
   from Owner step A and end.
2. **Checklist.** Run `PY -I -m minion_process onboard --root . --from <pin> --to <installed> --markdown`.
   Post the output on the project's coordination issue as "Kit onboarding <pin> -> <installed>: start".
3. **Sessions file.**
   - If `.minion/sessions.yaml` is missing, draft it from the sessions you know: herdr `pane list`
     entries whose working folder is this root, with their tool. Use `network: true` only for a Codex
     session that pushes to GitHub, and `env` only for root-relative cache folders the project needs.
   - Commit the draft in the project's repository under `process/enforcement/sessions.yaml` for review.
   - Do not write `.minion/` yourself.
4. **Memory (Claude sessions).** When `MEMORY-DIR` passes:
   - copy every file from your user-level memory folder (`~/.claude/projects/<this root's slug>/memory/`)
     into `<root>/.claude/memory/`;
   - list the copied files on the issue;
   - leave the user-level copies for the Owner to remove.
5. **Owner steps.** For every `TODO` or `MANUAL` step whose actor is `owner`, post the exact commands
   from the section below, with this project's paths and session ids filled in. Post them in this order:
   install, sessions file and settings, guard and permissions, relaunch.
6. **Witnesses**, after the Owner reports the guard, permissions and relaunch done. Run your own rows of
   `project-scope.md` PS-7 and record each command with its result:
   - a write outside the root is refused or asked;
   - a write to each control file you must not change is refused (or the recorded gap);
   - writes to `<root>/.claude/memory/` (Claude) and `<root>/.tmp/` succeed.
   For Codex, also record the effective policy you run under: sandbox mode and writable roots.
7. **Pin.** Propose raising the profile's `kit.version` to the installed version through the project's
   normal review.
8. **Close.** Run the checklist again and post it as "Kit onboarding <pin> -> <installed>: result", with
   every `MANUAL` step's evidence linked. List any gap for the Owner to accept.

## Owner steps (prepare these, never run them)

A. Install the release, from a kit checkout:
   `.\bootstrap\install.ps1 -Root <root> -Version <version>`
B. Install the reviewed sessions file and settings: copy them from the project repository at the
   reviewed commit into `.minion\sessions.yaml` and `.claude\settings.json`. The settings include
   `"autoMemoryDirectory": "<root>/.claude/memory"` and the `PreToolUse` guard.
C. Codex sessions only, to keep Codex off Claude's control files. Create `.claude\memory` first, then:
   ```powershell
   icacls "<root>\.claude" /deny "CodexSandboxUsers:(WD,AD,DC)"
   icacls "<root>\.claude\settings.json" /deny "CodexSandboxUsers:(W,D,WDAC,WO)"
   icacls "<root>\.claude\hooks" /deny "CodexSandboxUsers:(OI)(CI)(W,D,DC,WDAC,WO)"
   icacls "<root>\.claude\skills" /deny "CodexSandboxUsers:(OI)(CI)(W,D,DC,WDAC,WO)"
   ```
   Repeat the `settings.json` line for `settings.local.json` if it exists.
D. Relaunch each session in its own pane after the agent has exited. Check first with `-DryRun`, then run:
   `& <root>\.minion\relaunch.ps1 <session> -Resume <current session id>`
   The id is in herdr `pane get` (`agent_session.value`). Later relaunches need no id.
