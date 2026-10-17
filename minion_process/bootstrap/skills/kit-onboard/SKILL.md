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
   from the section below, with this project's paths and session ids filled in. Use this mapping from
   manifest step to Owner step; a step not listed here is reported to the Owner as having no runbook,
   never improvised:

   | Manifest step | Owner step |
   |---|---|
   | `KIT-INSTALL`, `SKILL-CLAUDE`, `SKILL-CODEX` | A |
   | `SESSIONS`, `MEMORY-DIR`, `GUARD` | B |
   | `CONTROL-DENY` | C |
   | `CODEX-RELAUNCH` | D (then your effective-policy record, step 6) |
   | `CODEX-RULES` | E |
   | `ORCH-GUARD`, `ORCH-GUARD-FILE`, `ORCH-RULES` | F |
   | `ORCH-ACL` | G |
   | `ORCH-TRUST`, `ORCH-LAUNCH` | H |

   Post them in this order: A, B, E, C, D. For the Orchestrator opt-in (kit 0.4.2): F, H, then G after
   the relaunched Codex session has run one sandboxed command.
6. **Witnesses**, after the Owner reports the guard, permissions and relaunch done. Run your own rows of
   `project-scope.md` PS-7 and record each command with its result:
   - a write outside the root is refused or asked;
   - a write to each control file you must not change is refused (or the recorded gap);
   - Codex only: renaming or replacing the `.claude` folder is refused (for example
     `Rename-Item .claude .claude-moved`);
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
C. Codex sessions only, to keep Codex off Claude's control files. Create `.claude\memory` first, then run
   the commands below. The first two protect the `.claude` folder itself: it cannot be renamed, deleted
   or replaced. The first does this through its own DELETE right; the second removes the project root's
   delete-child path for the sandbox. Ordinary files in the root keep their own delete rights.
   The rest protect the control files inside it.
   ```powershell
   icacls "<root>\.claude" /deny "CodexSandboxUsers:(D,WD,AD,DC)"
   icacls "<root>" /deny "CodexSandboxUsers:(DC)"
   icacls "<root>\.claude\settings.json" /deny "CodexSandboxUsers:(W,D,WDAC,WO)"
   icacls "<root>\.claude\hooks" /deny "CodexSandboxUsers:(OI)(CI)(W,D,DC,WDAC,WO)"
   icacls "<root>\.claude\skills" /deny "CodexSandboxUsers:(OI)(CI)(W,D,DC,WDAC,WO)"
   ```
   Repeat the `settings.json` line for `settings.local.json` if it exists.
D. Relaunch each session in its own pane after the agent has exited. Check first with `-DryRun`, then run:
   `& <root>\.minion\relaunch.ps1 <session> -Resume <current session id>`
   The id is in herdr `pane get` (`agent_session.value`). Later relaunches need no id.
E. Codex sessions only: project-specific approvals live in the project, not in the user-level rules
   (`CODEX-RULES`). You prepare it:
   1. Find each Codex session's effective user-level home, `<home>`: its `CODEX_HOME` when set, otherwise
      `~/.codex`. Check every place that can set it: your own session (`$env:CODEX_HOME`), each Codex
      entry's `env` in `.minion/sessions.yaml`, and the Owner's user and machine environment
      (`[Environment]::GetEnvironmentVariable('CODEX_HOME', 'User')`, and the same with `'Machine'`).
      Inventory `~/.codex` and every distinct `<home>` found. List each home with the sessions that use it.
   2. Read every rules file in each home, `<home>/rules/*.rules`, not only `default.rules`. Reading is
      allowed; never write them. List the rules that name this project (its paths, repositories,
      branches or commands), each with its home, file and line.
   3. If there are none, post that evidence (the homes, each file's sha256 and the lines you checked)
      and go to 5.
   4. Otherwise, commit those exact lines for review under `process/enforcement/codex-rules.rules`. Then
      post the Owner commands. They install the reviewed lines as a **new** file and change no existing
      project rules file:
      ```powershell
      $rules = "<root>\.codex\rules"; $new = "$rules\migrated-<date>.rules"
      New-Item -ItemType Directory -Force $rules | Out-Null
      if (Test-Path -LiteralPath $new) { throw "$new exists; choose another name" }
      Copy-Item "<reviewed process\enforcement\codex-rules.rules>" $new
      Copy-Item "<home>\rules\<file>.rules" "<root>\.tmp\<home-label>-<file>.rules.before-<date>"   # each home and file listed in 2
      ```
      Ask the Owner to remove exactly the listed lines from the listed files in each listed home, and
      nothing else.
      Rules for other projects, and rules of general use, stay.
   5. Loading proof, in your own session after the relaunch (step D):
      - The installer ships `.codex\rules\kit-sentinel.rules`, which forbids the command
        `minion-rules-sentinel`.
      - Run `minion-rules-sentinel`. It must be refused by the rule, not fail as an unknown command.
        That shows your normal session loads this project's rules folder.
      - Record your session's `$env:CODEX_HOME` with the result. If that home is not one listed in 1,
        the inventory is incomplete: go back to 1.
      - For each migrated file, also record `codex execpolicy check -r <file> <one listed command>`, as
        a syntax check.
F. Orchestrator opt-in (kit 0.4.2, `orchestrator.md`). Install the files rendered by
   `minion-process orch-render` from the **merged** opt-in commit, byte for byte, and post each sha256:
   - Claude sessions: `outside-root-guard.mjs` as `<root>\.claude\hooks\outside-root-guard.mjs`, and
     `settings.json` as `<root>\.claude\settings.json`. Create `<root>\.claude\memory` too.
   - Codex sessions: `<rules file>` as `<root>\.codex\rules\<rules file>`.
   Use a NON-elevated shell: an object created from an elevated shell is owned by Administrators, and
   Codex's sandbox setup refresh then fails with WRITE_DAC denied.
G. Codex sessions only, after step H's relaunch and one sandboxed command (Codex's setup refresh
   rewrites the root's ACL first): from a NON-elevated PowerShell, in a kit checkout or the installed
   package's `bootstrap\orchestrator` folder:
   ```powershell
   .\owner-acl.ps1 -Root <root> -Check
   .\owner-acl.ps1 -Root <root>
   ```
   It stops before any change if an object is owned by Administrators, and prints the one elevated
   repair. Post the ACLs it prints. Run `-Check` again after any Codex update.
H. Codex sessions only:
   1. Trust the project root in Codex. Without this, its `.codex\rules` do not load:
      ```toml
      [projects.'<root, lower case>']
      trust_level = "trusted"
      ```
      in `~/.codex/config.toml`. It is the tool's own user-level trust record (PS-4).
   2. Stop the Codex desktop app and its app-server, once per host. A held `node_repl.exe` makes the
      sandbox setup refresh fail with os error 32. Stopping the app-server disconnects every running
      `codex` TUI session; note their session ids first, so they can be resumed.
   3. In the session's pane, after the agent has exited: `& <root>\<rendered codex-launch.ps1> -Resume <id>`.
