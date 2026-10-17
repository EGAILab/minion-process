# Orchestrator-managed projects

**Referenced by:** `routing.md`, `roles/README.md`, `WORKFLOW.md` §11.6 and §11.7, `onboarding.md`.
**Authority:** the Owner's decisions of 2026-10-17 on `EGAILab/minion-agent#231`:
- issuecomment-6228553990: roles, merges, onboarding and review depth;
- issuecomment-6227470172: the standing GitHub-check disposition, carried to the job owner in OR-4.
- issuecomment-6228683601: Orchestrator autonomy and standing consent for windows (OR-7, OR-8).

Kit 0.4.3 adds the lessons of the first two days of operation (2026-10-17 and 2026-10-18): Owner
presence in a window (OR-7), how to ask the Owner (OR-8), session identity (OR-10), one route between
agents (OR-11), and a lower Codex pointer threshold (OR-5).

The contract is PROC-KIT-ORCH proposal revision 5 (issuecomment-6178363194). The first project on this
route was M-Remote, activated on 2026-10-17. Its reviewed and installed files are the base of the pack
below.

## OR-1. Who does what

| Session | Owns | Does not |
|---|---|---|
| **Orchestrator-CC** (`gru-orchestrator`, Gru-Maestro) | all daily work and job management: starting jobs from project backlogs, hand-offs between Impl, Review and the host queue, closing jobs, drain sequences, project onboarding with this pack, and implementing each kit version in `gru`. It decides operational matters itself and escalates to the Owner only as OR-8 allows. | write in a project, merge, grant or release a host slot, send keys or codes |
| **Process-CC** (`gru-process-cc`, Minion-Process) | the workflow itself: it takes feedback, improves the process, releases kit versions and hands each one to the Orchestrator to implement | dispatch, drive or merge project work |
| **A project's agents** | their own work under the project's rules, reached only through the Orchestrator once activated (the entry routing section) | address another agent's pane directly |

Process feedback and defects found in operation go from the Orchestrator to Process-CC. They are the
input to the next kit version.

## OR-2. Merges

The **implementer merges its own PR** after an independent reviewer's APPROVE at the exact head SHA
(§11.3). No further approval is needed. The Orchestrator checks that the APPROVE is independent and
exact before it tells the implementer to merge. A changed head needs a new APPROVE first. Kit PRs keep
this kit's own route: an independent review, then an exact-SHA merge by the kit owner.

## OR-3. Review depth (default for all routed work)

- One review round, with **blocking findings only**. Non-blocking points go in a short "later" list,
  not in the verdict.
- One re-review of the changed candidate.
- More rounds are an exception that the reviewer justifies by name, for example a convergence trigger
  (§11.8).

## OR-4. GitHub access

- **Rule.** A worker verifies GitHub references itself before acting on a notice.
- **Without access.** Until a worker has its own GitHub access, **the Orchestrator**, as the job's owner
  (OR-1), checks the job's GitHub facts with an authenticated `gh`: refs, SHAs, states and files. It
  posts them on the job's coordination issue or PR. Process-CC does not do this. The worker cites the
  post in place of its own lookup. It still stops if what it sees locally contradicts the posted facts.
  This carries the Owner's standing disposition (issuecomment-6227470172) over to the job owner.
- **The worker's own access** is an Owner-issued, fine-grained token in its launch environment: one
  token per project, scoped to that project's repositories only, with Contents and Pull requests
  read/write, so its implementer can verify and merge under OR-2 (Owner, issuecomment-6228674156).

## OR-5. Onboarding a project (kit 0.4.2 pack)

**The pack** ships in `minion_process/bootstrap/orchestrator/`. `minion-process orch-render --root <root>
--values <values.yaml> --out <folder>` renders it from one values file. `values.m-remote.yaml` is the
worked example. Rendering it gives back M-Remote's reviewed files byte for byte.

| Rendered file | Installed as | For |
|---|---|---|
| `outside-root-guard.mjs` | `.claude/hooks/outside-root-guard.mjs` | Claude: the PreToolUse containment guard |
| `settings.json` | `.claude/settings.json` | Claude: runs the guard; project memory location |
| `guard-witness.mjs` | not installed | Claude: the offline guard rows (W3) |
| `<rules_file>` | `.codex/rules/<rules_file>` | Codex: allows exactly `herdr agent prompt` and `herdr agent get`, bare `herdr` only |
| `codex-launch.ps1` | run by the Owner | Codex: PS-3 temp and caches, git `safe.directory` in command scope, the PS-5 sandbox line, the computer-use plugin off |
| `entry-routing.md` | appended to the root `AGENTS.md` and `CLAUDE.md` | the routing rules in force from ACTIVATE |
| `witness-rows.md` | not installed | the rows W0 to W16 and their pass criteria |

`owner-acl.ps1` is not rendered. The Owner runs it with `-Root`.

**Steps** (manifest `0.4.2`, Owner steps F, G and H in the `kit-onboard` skill):
1. **Opt-in PR.** A project agent writes the values file, renders the pack into the project's docs
   repository, and opens one opt-in PR. A session that did not author it reviews it independently at
   the exact SHA (OR-3). The implementer merges it (OR-2).
2. **Owner, non-elevated:**
   - F: install the rendered files from the merged commit;
   - H: trust the root in Codex, stop the Codex desktop app and app-server once per host, and relaunch
     each session (Codex with `codex-launch.ps1`);
   - G: after the relaunched Codex session's first sandboxed command, run `owner-acl.ps1`.
3. **Witness rows.** The project's agents run W0 to W16 and record them on the coordination issue. The
   Orchestrator records W15 (session identity, OR-10).
4. **Activation.** Binding and ACTIVATE are **pre-authorized by the Owner** once the rows pass. The
   Orchestrator binds the sessions with the identities checked in W15 (`agent rename`, registry, `registry-check`) and sends
   `ACTIVATE <project>`. The root entry files are then installed from the merged opt-in.

**Order (Owner):**
1. Minion-Agent first. It holds the #209 host queue, which then moves into `gru`.
2. Minion-Assist, Minion-Memory, Minion-Mobile and Minion-Message, two at a time.
3. Minion-Architecture.

**Lessons from M-Remote, built into the pack:**
- A held `node_repl.exe` breaks Codex's sandbox setup (os error 32). Stop the desktop app and the
  app-server first, and keep the computer-use plugin off on the launch line. Stopping the app-server
  disconnects every running `codex` TUI session, so note their ids before stopping it.
- An object created from an elevated shell is owned by Administrators, and the setup refresh then fails
  with WRITE_DAC denied. All Owner steps are non-elevated, and `owner-acl.ps1` refuses to run elevated.
- Codex's setup refresh rewrites the writable root's ACL and dropped a deny there. So G runs after the
  first refresh, and `-Check` runs again after any Codex update.
- A sandboxed git refuses repositories owned by the Owner. `safe.directory` goes in command scope
  (`GIT_CONFIG_COUNT`/`KEY_n`/`VALUE_n`) from the launch shell, with no global config change.
- A project's `.codex/rules` load only for a trusted project root. A trusted ancestor does not count.
- Removing an inherited sandbox grant from a large tree with `icacls /remove:g` rewrites every file
  below it: it took about 49 minutes on `Minions`. `owner-acl.ps1` reports a parent grant and leaves
  the choice to the Owner.
- A pasted text left in the Codex input box is not submitted. Kit 0.4.2 set `gru`'s pointer threshold at
  900 characters, but the journal up to 2026-10-18 shows shorter texts failing too:
  - every direct Codex prompt up to 608 characters was submitted (17 of 17);
  - above that, 8 of 20 ended UNKNOWN, the shortest at 634 characters. Those the Orchestrator looked at
    were left unsubmitted in the input box;
  - every pointer prompt (about 330 characters) was submitted (7 of 7).

  So **`gru` delivers any Codex message over 500 characters as a pointer** to a brief file (OR-9). The
  Orchestrator implements this in `gru`.

## OR-6. Unchanged

This file never weakens:
- implementer-reviewer separation;
- the exact-SHA review invariant (§11.3);
- negative controls;
- convergence checkpoints;
- the containment rules;
- the rule that no agent sends keys or approval codes.

A project's own rules still decide its gate tiers and evidence standards.

## OR-7. Consent windows (live desktop, device, capture)

These windows run under the **Owner's standing consent**, within the project's own contract (Owner,
issuecomment-6228683601). That decision replaces a per-window proposal.
- **Parameters.** The Orchestrator sets every parameter itself from the contract: duration, display or
  device, timing, steps and evidence limits. Where the contract leaves one open, it picks the narrowest
  value that still meets the job's goal.
- **Record.** It records the owner-window record, which cites that comment as the authorizer.
- **Heads-up.** Before the window starts, it gives the Owner a notice, not a question: when, which
  display, and how long.
- **Stopping.** The Owner can stop a window at any time.
- **Outside the contract.** A window outside the project's contract is a change outside the approved
  plan, and OR-8 escalates it.
- **Owner presence (0.4.3).** Some windows need the Owner at the display or device, for example to pair,
  tap or type a PIN. The Owner's presence is then a physical Owner action (OR-8 item 1):
  - The Orchestrator asks once, in its batched request, for a start time.
  - It schedules preparation, such as builds and host slots, so that the window opens at that time.
  - Before the window opens, it checks that the app is on screen and that the Owner has confirmed they
    are present. Only then is the window's start recorded.
  - If that confirmation has not come by the start time, the window does not open. The run ends cleanly
    and waits for a new time from the Owner.

  M-Remote's D5 showed both failures. Attempt 2 ended without pairing because the app was not on screen
  when the window opened. Attempt 3 was closed because the Owner was not there.

## OR-8. Orchestrator autonomy

The Orchestrator decides operational matters itself, records each decision with its basis, and does
not ask the Owner (issuecomment-6228683601). Operational matters include:
- routing, ordering and scheduling;
- cancelling and closing jobs; the handover is its standing authority;
- GitHub fact checks (OR-4);
- host-slot use;
- review depth, within OR-3;
- whether a step is needed;
- test-window parameters (OR-7).

It escalates to the Owner only for:
1. **Physical actions only the Owner can do**, batched into one request:
   - creating tokens;
   - running elevated or admin scripts;
   - restarting sessions;
   - trust or permission prompts;
   - pressing Enter or Esc in a pane.
2. **Changes outside the approved plan:**
   - public visibility;
   - deleting data or repositories;
   - spending;
   - new projects or roles not in issuecomment-6228553990.
3. **Anything the rules reserve for an Owner-typed code.**

**How to ask the Owner (0.4.3):**
- **Name things as the Owner sees them.** The Owner sees herdr's space and tab names, not pane ids. Write
  "space Gru-Maestro, tab Review-Codex", not `w9:p4`.
- **Say exactly what to do.** For example: "quit Codex, then run `codex resume` in the same tab and pick
  the latest session". Do not just write "restart".
- **Never ask the Owner to carry text between agents.** A message to an agent bound in `gru` goes through
  `gru`. If `gru` cannot deliver it, record that as a `gru` defect and ask the Owner to relay it only
  after that.
- **Only a submitted message is an answer.** Dim text in an agent's own input box (`ESC[2m`) is a
  suggestion from that agent's interface. It is neither the Owner's input nor a draft.
- **A wait on the Owner has a deadline.** If no answer arrives within 30 minutes, send one reminder, and
  record the job as paused while it waits on the Owner. On 2026-10-17 the Orchestrator waited about
  1 h 40 min on an Owner paste that a `gru` delivery could have replaced.

## OR-9. Brief-file read exception

`gru` delivers a long Codex message as a pointer to one brief file under `Gru-Maestro\.tmp\briefs\`,
with its sha256 (`gru` candidate 2). "Long" means over 900 characters in kit 0.4.2 and over 500 from
kit 0.4.3 (OR-5). The entry routing section (rules 3,
5 and 8) makes one **deliberate, read-only exception** to cross-workspace containment for it:
- a consumer may read exactly the one file the pointer names, directly in that folder;
- it checks the file's sha256 against the pointer before acting;
- it refuses on a missing file, a path outside that folder, or a hash mismatch, and reports it to the
  Orchestrator;
- no other cross-workspace read, and no write there, is allowed.

**Enforcement:**
- **Codex:** reads are not sandboxed (witness W14 records this as a known gap), so the rule and the hash
  check hold the boundary.
- **Claude:** sessions receive whole messages, never pointers. If a project's Claude guard restricts
  reads and one ever needs a pointer, the briefs folder must be added to that project's
  `read_exec_roots`, in its own reviewed opt-in.

This resolves GRU19 (minion-remote-docs#1 issuecomment-6228701760). There, a brief outside M-Remote's
containment had to be published on the issue instead.

## OR-10. Session identity (0.4.3)

A `gru` binding pairs a herdr name with an agent session, and `gru` refuses to deliver when herdr
reports a different session. That check holds only if the recorded session really belongs to the pane.
On 2026-10-17 herdr reported Review-Codex's Codex session for the Minion-Agent Rust-Codex pane, and the
registry copied it. The check then agreed with itself, and the real Review-Codex session could not be
bound.

**Before the Orchestrator binds a session, and whenever herdr's session for a bound pane changes,** it
confirms the ID against the tool's own session record:
- **Codex:** the rollout file `~/.codex/sessions/YYYY/MM/DD/rollout-*-<id>.jsonl` exists, its first
  `cwd` is the pane's root, and its latest turns are the turns on the pane's screen.
- **Claude:** the transcript `~/.claude/projects/<root slug>/<id>.jsonl` exists, and its latest turns are
  the turns on the pane's screen.

**When herdr reports a wrong session or none**, the Orchestrator corrects herdr's record. This needs no
restart and no keypress to any agent:

```
herdr pane report-agent-session <pane> --source herdr:<tool> --agent <tool> --seq <now in ms> --agent-session-id <id>
```

- It runs this one command outside `gru`'s allow-list, under OR-8, and records the evidence first.
- It checks the result with `herdr agent get`. herdr can ignore a report: on 2026-10-17 the first one
  for Rust-Codex was ignored, and a retry with a later `--seq` was accepted.
- If herdr still refuses, the fallback is an Owner restart of that tab: quit, then `codex resume <id>`
  or `claude --resume <id>`.

## OR-11. One route between agents (0.4.3)

From ACTIVATE on, every message between agents goes through `gru`.
- **Retiring old routes.** A project's own scripts that prompt another agent's pane or send it keys are
  retired in the project's opt-in PR. For example, Minion-Agent's #209 holder uses its own herdr script
  to reach the Orchestrator, and that script presses Enter in the Orchestrator's pane.
- **Before ACTIVATE.** Until a project is activated, its own rules apply. Even then, no script sends
  keys to a pane that is blocked or shows a dialog (OR-6).
- **Witness.** W16 records that no such script remains.
