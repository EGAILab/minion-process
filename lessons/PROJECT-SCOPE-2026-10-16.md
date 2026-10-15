# PROJECT-SCOPE-2026-10-16 — agent state and settings belong to the project, not the user-level tool folders

**Supports:** `project-scope.md` (PS-1 to PS-7) and `WORKFLOW.md` §9.8.
**Source:** the Owner's instructions to the kit owner (Process-CC) on 2026-10-16, during the
PROC-KIT-ORCH opt-in of the first pilot project, recorded on `EGAILab/minion-agent#231`.

> "~/.claude is global memory, the memory writable should be in PROJECT_ROOT/.claude/"

> "yes, add it to the kit as default, not just memory, avoid writing to global ~/.claude if possible,
> everything should be project scope unless really need to, audit the current pack if anything else
> require global update"

## What led to it

- The pilot project's containment plan exempted the tools' own state folders for reading and execution
  only. Its reviewer then asked whether Claude Code's auto-memory folder, which by default sits under the
  user-level `~/.claude/projects/`, should stay writable.
- The Owner's answer moved the writable memory into the project, and extended the rule to everything an
  agent creates or configures.
- An audit of the host at that point found project-specific state at user level: auto-memory for every
  project under `~/.claude/projects/*/memory`, project-specific "always allow" command rules in Codex's
  user-level rules file, agent scratch in the user temp folder, and Codex sessions launched without a
  sandbox. The audit is on the coordination issue for this change.

## Why it matters

- **Containment.** An agent that writes a user-level folder writes outside its project root, which the
  containment rule (`lessons/CONTAINMENT-2026-10-10.md`) forbids without the Owner.
- **Reviewability.** Project-scope settings and memory can be committed, reviewed and rolled back with
  the project. User-level state is shared by every project and is invisible to a project's reviewer.
- **Isolation between projects.** A memory or rule written for one project is loaded by every other
  project on the host.
