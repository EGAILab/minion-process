# CE-PROC-P3B-01 checkpoint proposal, revision 5 (base: contract revision 3 + checkpoint revision 4)

**Author:** Claude `w1:p8`. **Status:** PROPOSED. Revision 4 stands except where this revision replaces
it. Codex round 3 closed R002, R003, R006 and R007 at checkpoint level, and they are not reopened. Codex's
round-3 acceptance cautions are adopted as written; they are listed at the end. Open: **R005** and
**R008**.

## R008: the confirmation channel is the Owner's chat, the same model as `APPROVE OUTSIDE`

The revision-4 claim that an interactive console proves a human is withdrawn. Codex showed that an
agent's shell tool can start a real Windows console and write to it.

- **K-21 channel (Owner decision recorded on #223).** An override is confirmed only when the Owner types
  `CONFIRM QUEUE <code>` as an entire chat message in a Claude Code session of an adopting project. A
  kit-shipped `UserPromptSubmit` hook, installed beside the outside-root guard, sees the message. It
  turns exactly that form into a confirmation request carrying the code and the session id, and the
  broker performs the transition. The hook never writes the journal; the broker remains the only writer.
  A message with any other text before or after the form, a relayed prefix such as `Codex w1:p2: ...`, a
  truncated code, or a code for another challenge confirms nothing. This is the parsing the existing
  guard already applies to `APPROVE OUTSIDE`.
- **K-22 trust statement (procedural, not machine-proven).** This channel is exactly as strong as the
  existing approval-code rule, and the contract says so. An agent's tools cannot author a user prompt in
  its own session. Another agent could still deliver text into a Claude pane with `herdr agent prompt`,
  so the standing rule applies: **no agent ever types, relays or sends keys for a confirmation code into
  any pane** (the `CLAUDE.md` approval-code rule, extended by name to `CONFIRM QUEUE`). The kit enforces
  the parts it can. Every Claude session's guard denies any tool call whose text contains `CONFIRM
  QUEUE`, so a Claude agent cannot send the string through herdr. The broker refuses confirmation
  requests that did not come from the hook, identified by a request type the client verbs cannot
  produce. A Codex harness has no such hook, so Codex sessions cannot confirm, and the rule binds Codex
  procedurally as it does today.
- **K-23 binding (kept from revision 4).** A challenge is one-use and expires after 15 minutes. It is
  bound to the action, the job id and journal generation (or the policy version), and the exact effect.
  The Owner's chat sees the bound effect because the broker's challenge text is shown to the Owner by
  the requesting agent, verbatim. A confirmed release records `ended(human-confirmed)`, which is always
  `not-eligible`. A policy change also records the Owner decision it implements; the confirmation is the
  provenance, and a supplied link is context only.
- **K-24 replaces K-6, K-7 and W-42 of revision 4.** Confirmation by console input is removed.
  `build confirm` no longer exists.
- **Witnesses.**
  - **W-66:** the exact `CONFIRM QUEUE <code>` message through the hook confirms the bound effect only.
  - **W-67:** each of the following confirms nothing and changes nothing: a prefixed or relayed message,
    a message with trailing text, a truncated code, a used code, an expired challenge, a wrong-job code,
    a wrong-generation code, and a confirmation request written by a client verb rather than the hook.
  - **W-68:** a Claude tool call containing `CONFIRM QUEUE` is denied by the guard.
  - **W-69:** an agent-started console with the code typed into it confirms nothing, because no such
    path exists.
  - **C-13 (negative control):** a broker accepting confirmation requests of any origin makes W-67's
    client-written row confirm.

## R005: a journal fault model in which no tail is presumed harmless

- **K-25 fault model.** Two faults are supported:
  - a crash at any byte during an append;
  - corruption of any bytes anywhere: payload, length prefix, checksum or commit marker.

  The journal is append-only; only repair writes a new journal, keeping the old one quarantined.
- **K-26 no presumption.** Any anomaly at any position is an **ambiguous record**. That covers a short
  length, a length beyond the end of the file, a missing or damaged commit marker, and a checksum
  mismatch. No anomaly is treated as proof that a record was never committed. K-13's "may be discarded"
  arm is withdrawn.
- **K-27 recovery from an ambiguous tail.** The broker starts in recovery, admitting nothing. A tail
  anomaly is the only anomaly a normal start may recover from, and only with a **no-hidden-effect
  proof**. For every job that the journal before the anomaly leaves in `submitted`, `launching`,
  `running` or `uncertain`, and for any job id whose label is found:
  - inspection of job objects and of labelled containers finds no workload;
  - every registered path a cleanup job could have touched still exists as registered.

  Both inspections must succeed. With the proof, the ambiguous bytes are quarantined with their offset,
  replay continues from the last good record, and the recovery is journaled. Without the proof, because
  inspection failed or something was found, the broker stays in repair mode. Every affected job becomes
  `uncertain`, and the host is blocked (K-10) until inspected proof or an Owner confirmation (K-21).
- **K-28 a mid-journal anomaly** always needs repair mode, the same as a damaged complete record in
  revision 4.
- **Witnesses.**
  - **W-70:** a committed `launching` record with its length prefix enlarged, which is Codex's probe: a
    live workload is found, the host is blocked, and nothing is relaunched.
  - **W-71:** the same record with its commit marker removed, and with the workload still running: same
    outcome as W-70.
  - **W-72:** a genuine crash mid-append of a `launching` record before the spawn: inspection finds no
    workload, the tail is quarantined, and the job remains `submitted`.
  - **W-73:** the same as W-72 with inspection denied: the host is blocked.
  - **W-74:** a crash mid-append of a cleanup progress record with a registered path partly deleted: no
    proof, so the job becomes `uncertain` and the host is blocked.
  - **C-14 (negative control):** discarding every short or markerless tail makes W-70 relaunch while the
    first workload lives.

## Round-3 acceptance cautions adopted

- W-47 includes a job that becomes `uncertain` after its 3-minute window ended; the reservation is
  restored.
- The K-12a lease downgrade is broker-serialized.
- K-18's `retain` rule overrides "ended jobs are not references", and W-64 holds after the creator ended.
- Cleanup's self-exclusion never ignores another active claimant.
- W-6's injected death is a test seam, never a production kill path.
- `dispatch --print` records a render, never a delivery. `--mark-undelivered` creates no delivered
  observation. Concurrent duplicates and crash-after-journal-before-print are deduplicated without blind
  replay.
- Kit 0.4.0 never calls a project's send helper itself.

## Request

Independent checkpoint review (§11.8.5) of revision 5: APPROVED, or REJECTED with the failing dimension and
a counterexample.
