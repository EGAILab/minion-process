# PROC-KIT-P3B contract draft, revision 3 (kit 0.4.0)

**Work package:** `minion-agent#223`, kind `process`, governing (`CP-1`, `CP-5`, `CP-6` confirmed by Codex,
round 1). **Author:** Claude `w1:p8`. **Status:** PROPOSED. **Authority:** record §6.5 and §6.7; Owner
decisions on `#205`, `#209` issuecomment-6138907446 (window ownership moves to a host queue), the queue
folder `E:\AI\Projects\OpenMinds\Minions\.host-queue` (Q1) and the values of issuecomment-6139069723 (Q2: 2
concurrent build/control jobs, 16 GiB floor in exact bytes, 3-minute start-up reservation); kit `WORKFLOW.md`
§9.7, §9.8 and lesson `SHARED-BUILD-CACHE-FRESHNESS-2026-10-13`.

**What changed, in kind.** Revisions 1–2 let every client process write the shared state and protected it
with a lock file. Codex's round 1 showed that a file rename cannot be a compare-and-swap (R001), that the
death of a supervising process says nothing about its workload (R002), and that per-file atomicity is not
transaction atomicity (R002). Revision 3 removes the shared-writer design instead of patching each race:

- **One broker process per host is the only writer of queue state.** Single instance is enforced by an
  operating-system named mutex, which the OS releases when its holder ends, so there is no stale-lock file
  to inspect or rename.
- **Clients never write shared state.** They drop one immutable request file each and read responses.
- **Every state transition is one journal record**, so a transition is atomic by construction.

Parts B–F are amended for R006, R007 and the per-part notes. The Owner values are unchanged.

## Part A. Host build queue

### A0. Architecture (R001, R002, R004, R005)

- **B-1 the broker.** `minion-process build broker` is the only process that writes the queue's state. It
  holds the host-wide OS named mutex `Global\MinionProcessHostQueue` for its whole life. A second broker,
  for any queue folder, fails to acquire the mutex and exits with a refusal, so evidence exclusivity is
  host-wide rather than per folder (R004). The OS releases the mutex when the holder ends, normally or
  not; the next broker that acquires it is told the previous holder abandoned it and enters recovery
  (A6). No lock file exists, so no stale-lock inspection, rename or tombstone exists (R001).
- **B-2 who may start it.** Any agent of an adopting project may start the broker (`build broker
  --ensure`). If one is already running it does nothing and reports the running instance. The broker never
  stops itself while jobs are admitted.
- **B-3 clients.** `build submit`, `status`, `cancel`, `wait`, `release` and `policy` write exactly one
  new, uniquely named, immutable request file into `inbox/` (temporary name, then rename) and read the
  broker's response from `outbox/<request-id>`. A client never rewrites or deletes any file the broker
  owns. A malformed request is rejected individually into `rejected/<request-id>` with the reason; it
  cannot affect any other request or job (R005).
- **B-4 journal.** Broker state is a journal of transition records, one record per line, each with a
  sequence number, the broker instance id and a checksum. A record is written and flushed to disk before
  the broker acts on it. State is the replay of the journal. A periodic snapshot is an optimisation that
  is always checked against the journal.
- **B-5 policy authority (R004).** The host policy is `policy.yaml` in the queue folder: policy id,
  version, concurrency limit (2), memory floor (16 GiB, exact bytes), start-up reservation (3 minutes),
  and the allow-list of adopting projects with their roots. Only `build policy set --owner-confirmed
  <statement>` changes it, through the broker, as a journal record that quotes the confirmation. A
  project profile names the queue folder and the policy id it expects. A mismatch is refused before any
  job is admitted. A profile may only narrow its own jobs (for example a lower per-project limit), never
  widen the host's. A policy change applies to admissions after its journal record; admitted jobs keep the
  reservations they were admitted under.
- **B-6 clocks.** Reservations and ages use the broker's monotonic clock. After a broker restart, a
  reservation whose elapsed time cannot be established is held for a full window from the restart.

### A1. Jobs, classes and admission

- **B-7 submit.** A job names the project, class (`evidence`, `build`, `control`), launcher (from the
  profile's `gates:`), target, checkout, `--sha` (required for `evidence`), and the reply-to (pane and
  agent session id, A5). At submit the broker **freezes** the job's inputs (A2) and assigns its id from a
  counter in the journal. Ids are gap-free per broker instance. A gap across a crash is recorded in the
  recovery report.
- **B-8 classes.**
  - `evidence` runs alone on the host.
  - `build` is uncredited iteration.
  - `control` is mutation or negative controls, uncredited by the queue.

  A job record carries `evidence: eligible | not-eligible(<reason>)`. Only an `evidence` job that ends
  `passed`, with every A2 check satisfied at launch and completion, can be `eligible`. `build`, `control`,
  failed, cancelled, abandoned or uncertain jobs are `not-eligible` whatever their exit code or log marker.
  The queue never credits controls. Their baseline, intended-witness and isolation rules stay with the
  reviewer (§9.7).
- **B-9 schedule (liveness).** The queue is ordered by job id. The broker admits in order, and a job is
  admitted when all of these hold:
  - **(a)** no `evidence` job is running;
  - **(b)** for an `evidence` job, no job of any class is running;
  - **(c)** for `build` and `control`, fewer than the policy limit are running, and free physical memory
    minus the reservations of jobs still in their start-up window is at least the floor, in exact bytes;
  - **(d)** every resource the job needs is free (A2).

  Ordering rules:
  - **Evidence drains the host.** When the earliest waiting job is `evidence`, nothing behind it is
    admitted, so the host drains and the evidence job runs next.
  - **Bounded bypass.** A `build` or `control` job waiting only on (d) may be bypassed by a later job
    whose resources are free, at most 3 times. After that it blocks later jobs like the head of the line.
  - **No bypass on memory.** A job waiting on (c) memory is never bypassed, because memory is host-wide.

  Every waiting job's status names its position and the condition it waits on.

### A2. Frozen inputs and resource binding (R003)

- **B-10 frozen inputs.** At submit the job records:
  - the profile's content hash;
  - the launcher's resolved definition and its hash;
  - canonical real paths of the checkout and of every target, resolved through links;
  - the environment and mount set the launcher will receive.

  At launch the broker recomputes these. Any difference refuses the job (`refused: input drift`), and
  nothing runs.
- **B-11 resources are canonical paths with overlap.** Every target and every checkout is a resource
  identified by its canonical real path. Two resources conflict when they are equal or one contains the
  other, whatever names the profile uses. A job holds its resources for its whole life.
  - A target is held exclusively.
  - A checkout used read-only, which is how `build` jobs use theirs, is held shared.
  - A checkout that a job mutates is held exclusively.
- **B-12 evidence executes on an immutable copy.** An `evidence` job never runs in an agent's working
  checkout. The launcher creates a fresh, queue-owned execution worktree of the exact `--sha` inside the
  submitting project's root. Fresh files give fresh modification times, which satisfies the freshness rule
  of §9.8 and the lesson by construction. The launcher verifies the copy's `HEAD` equals the SHA and its
  tree is clean, both before and after the run. The execution worktree is a resource held exclusively and
  is registered for cleanup (Part C).
- **B-13 controls execute on isolated copies.** A `control` job mutates only its own queue-owned source
  copy, created and registered like B-12, and builds only into a target of kind `controls`. A control
  never uses an agent's checkout or a gate target.
- **B-14 binding.** The launcher receives its target path, environment and mounts from the broker and may
  not add or override them. Its self-test proves this (Part E): `CARGO_TARGET_DIR`, `CARGO_HOME` and any
  writable container mount equal the declared resources. Container mounts are only declared resources
  inside the project roots, plus a private tmpfs.
- **B-15 reviewer resources and submitter identity.** A `reviewer` target or reviewer `controls` target
  names its owning agent. The submitting agent's identity is the herdr agent kind and agent session id of
  the pane the request came from, which the broker checks with `herdr agent get` at submit and at
  launch. This is a check between cooperating agents on one host, not a security boundary, and the
  contract states it as such. A mismatch is refused.

### A3. Job states and recovery (R002)

- **B-16 states.** Each transition is one journal record:
  - `submitted` → `launching`;
  - `launching` → `running` (records the workload identity: runner process id and start time, and
    container ids with the job's label);
  - `running` → `ended(passed|failed)`;
  - `submitted` → `cancelled`;
  - any state → `refused`;
  - `running` → `uncertain`.

  `cancel` only moves a `submitted` job. It races admission through the broker, which serialises both, so
  exactly one wins.
- **B-17 one launch.** The broker writes `launching`, then starts the runner, then records `running` with
  the runner's identity. A job is launched by exactly one broker, at most once.
- **B-18 workload-ended proof.** Resources and reservations are released only when the broker proves the
  workload ended:
  - the runner and every process it started have exited, tracked through an OS process group the runner
    creates for the job (on Windows, a job object) and by process id plus start time;
  - and no container with the job's label is running.

  A runner that dies while its workload lives is **not** completion.
- **B-19 uncertain.** When the proof cannot be made, the job becomes `uncertain`. Cases: inspection
  denied or failed; a broker restart finding `launching` with no recorded runner; a runner gone with
  descendants or containers alive or unknown. Its resources and reservations stay held, and it is
  reported by `status` and to its reply-to. The queue never kills, stops or signals anything (B-13 of
  revision 2 stands). An `uncertain` job is released when a later inspection proves the workload ended,
  or by `build release --confirm-ended <job> --statement <text>`, a recorded human confirmation. An
  `uncertain` job is never `eligible`.
- **B-20 nobody needs to call run.** The broker launches admitted jobs itself, so a submitter that goes
  away cannot wedge the queue. A `submitted` job whose checkout or frozen inputs vanish is refused when
  it reaches the head.

### A4. Results and evidence records

- **B-21** Each job record holds: frozen inputs, submitter identity, timestamps (monotonic and wall),
  exit code, log path, `GATE-END` agreement, the freshness method (always "fresh copy" for evidence), the
  workload-ended proof or its absence, and `evidence` eligibility with its reason. The log convention and
  the alert-only stall watchdog are unchanged.

### A5. Notifications (R007)

- **B-22 intent before send.** A notification is a journal record `notify-intended(job, pane, agent
  session id, message id)` before any key is sent. Only the broker sends job notifications, one at a time.
- **B-23 send boundary.** Immediately before sending, the broker reads the pane and checks three things:
  - the pane is not blocked and shows no question or permission dialog;
  - its agent session id equals the recorded one;
  - its `state_change_seq` has not moved since that read.

  If any check fails, the record becomes `notify-withheld(reason)` and nothing is sent. The text goes in
  one prompt submission; the queue never sends a separate Enter or any other key.
- **B-24 after send.** The record becomes `notify-sent`. Verification looks for the message id in the
  pane transcript and records `delivered`, or `unknown` when it cannot be confirmed. `unknown` is never
  resent automatically; it is reported. After a broker crash, a `notify-intended` without a later record
  becomes `unknown`, not a resend.
- **B-25 never blocking.** Notification state never holds resources, admission or job completion.
- **B-26 herdr characterization, a precondition.** herdr has no atomic check-and-send. Before
  implementation starts, the behaviour of `herdr agent prompt` against a pane showing a dialog is
  characterized on a disposable pane. If it can deliver keystrokes into a dialog, the residual window
  between the B-23 read and the send goes to the Owner as a risk decision before Part A or D ships.

### A6. Recovery, validation and repair (R005)

- **B-27 replay.** On start, the broker replays the journal. A final record that is truncated or fails its
  checksum is a torn write and is ignored, which is safe because the broker acts only after flushing
  (B-4). Any earlier invalid record, or a violated invariant, makes the broker refuse to start. Invariants
  include:
  - a resource held by two jobs;
  - a job in two states;
  - an evidence job running with another job;
  - a record naming a project absent from the policy allow-list;
  - a path outside its project's roots.

  The refusal is reported with the record's sequence number and the writer's instance id.
- **B-28 repair.** `build repair --inspect` reports the problem read-only. `build repair --quarantine
  --statement <text>` keeps the original journal bytes under `quarantine/<time>/`, then writes a recovery
  journal. That journal keeps every job whose workload cannot be proven ended as `uncertain`, holding its
  resources; it never drops potentially live occupancy. The command requires the human statement and
  records it. While any `uncertain` job exists, its resources stay held; everything else resumes.
- **B-29 temporary files.** Inbox temporary names, unrenamed outbox files and snapshot temporaries are not
  state. Only the journal is. The broker removes its own temporaries older than the current instance's
  start, and nothing else.

### A7. Location and containment

- **B-30** The queue folder is `E:\AI\Projects\OpenMinds\Minions\.host-queue` (Q1). The broker refuses to
  start unless it is on a local fixed volume.
- **B-31 broker writes.** The broker writes only:
  - its folder;
  - job logs, execution worktrees and control copies inside the submitting project's roots from the
    policy allow-list.

  Each write passes the containment proof per operation (lexical, then no-follow real path; refusing
  `..`, drive-relative, bare drive, UNC and outside-absolute forms), and the proof fails closed.
- **B-32 client writes.** Clients write only `inbox/`.
- **B-33 adoption.** Each adopting project's write guard permits the folder before its pin bump. For
  Minion-Agent that is an Owner-approved hook edit at adoption time, not in this work package.

### A8. Adoption and rollback

Unchanged from revision 2. Until Minion-Agent's pin bump to 0.4.0, #209 item 1 stays in force: Codex runs
the host build queue. The rollback is a profile change back to the previous pin, after the broker has no
running jobs.

### A9. Witnesses (permanent tests with injected clock, memory probe, process table, herdr and OS-mutex seams; barrier-controlled interleavings, not stress alone)

| # | Scenario | Expected |
|---|---|---|
| W-1 | evidence job waiting while two build jobs run; a third build submitted later | no admission while evidence waits; evidence admitted after both end; then the third |
| W-2 | evidence running; build offered | not admitted until evidence ends |
| W-3 | memory 20 GiB, floor 16, two builds | first admitted, second waits until the first's reservation window ends and memory allows |
| W-4 | memory exactly 16 GiB / one KiB below | admitted / waits |
| W-5 | two brokers started together (barrier), same folder and different folders | exactly one runs; the other refuses |
| W-6 | broker killed mid-decision; new broker | abandoned mutex detected; journal replay; torn final record ignored |
| W-7 | crash at each cut: after `launching` before runner start; after runner start before `running`; after workload end before `ended` | `uncertain` or proven-ended exactly as B-18/B-19; never a second launch |
| W-8 | runner dies, its cargo child or labelled container survives | resources stay held, job `uncertain`, evidence not admitted |
| W-9 | runner and workload end naturally | released, `ended` |
| W-10 | process id reused with a different start time | not mistaken for the runner |
| W-11 | two targets naming one directory; one target inside another | conflict, second waits |
| W-12 | two control jobs over one project | each on its own copy; neither sees the other's mutant |
| W-13 | profile or launcher changed after submit; launcher env names another target | refused at launch, input drift / binding |
| W-14 | evidence job: copy `HEAD` differs from `--sha`; tree dirty after the run | refused / `not-eligible` |
| W-15 | build or control job ends with exit 0 and `GATE-END 0` | `not-eligible` |
| W-16 | reviewer target submitted from the other agent's session | refused |
| W-17 | cancel races admission | exactly one wins |
| W-18 | conflicting policy id in a profile; profile wider than host policy; policy changed while a reservation is active; wall clock moved | refused / refused / reservation kept / no effect |
| W-19 | corrupt mid-journal record; invariant violation; foreign project in a record | broker refuses with record number; `repair --inspect` names it; quarantine keeps the bytes and the live-occupancy jobs `uncertain` |
| W-20 | malformed inbox request | rejected alone; other jobs unaffected |
| W-21 | notification: pane blocked; session id changed; `state_change_seq` moved | `withheld`, zero keys sent |
| W-22 | crash after send before `notify-sent` | `unknown` after restart, not resent |
| W-23 | two jobs ending together | notifications serialised by the broker, one intent each |
| W-24 | write target outside the roots via `..`, drive-relative, UNC, junction | refused before any write |
| W-25 | bypass bound | a resource-blocked build is bypassed at most 3 times, then blocks |
| **C-1** negative control | single-instance mutex check removed | W-5 runs two brokers (intended witness) |
| **C-2** negative control | workload-ended proof replaced by runner-alive check | W-8 releases resources while cargo still runs |
| **C-3** negative control | evidence exclusivity removed from admission | W-1/W-2 admit alongside evidence |
| **C-4** negative control | input freeze disabled | W-13 runs the drifted launcher |
| **C-5** negative control | intent-before-send removed | W-22 resends |
| **C-6** consumer-side, needs cargo | evidence run in an agent's older checkout with a stale/mutant artifact present instead of a fresh copy | the lesson's replay shows the stale binary; with B-12 the fresh copy shows the candidate (recorded with baseline and exact artifact) |

## Part B. `session start`

It may write only Git metadata through `git fetch` and its own report file; it never touches working
files. W-26 checks an exact allowed-write ledger: the report plus Git metadata, nothing else. A remote that
is unavailable, an unreadable queue, or an environment-source failure makes the report **partial**,
naming each failed item, and partial is never a green prerequisite. It lists cleanup candidates without
removing anything. It lists the calling agent's work packages and the queue's running, waiting and
`uncertain` jobs.

## Part C. `cleanup` (R006)

- **Leased removal.** Cleanup runs as a broker job of class `cleanup` that holds an **exclusive lease**
  on each target resource, using the same resource protocol as B-11. While leased, the target cannot be
  named by a new job (refused at submit) or used by a running one (it would have conflicted at
  admission).
- **Predicates at the boundary.** The runner re-evaluates every predicate at the destructive boundary,
  then deletes entry by entry without following links, with the containment proof for each entry:
  - inside a project root, by lexical and real path;
  - registered by the tool as an execution worktree or control copy (B-12, B-13), or registered
    tool-created scratch;
  - for a Git worktree: clean, and every commit reachable from a remote ref;
  - for registered scratch: its creating job has ended;
  - not referenced by any open work package, incident record, the authority cache or any job.

  A reference source that cannot be read means **refuse**, never "no references". Protected stores are
  never targets: authority caches, shared build targets, the queue folder and `.git` directories.
- **Report and defaults.** The report lists exactly what was removed and what was kept, and why. Dry run
  is the default. Scratch the tool did not create needs the Owner. Nothing is cleaned by age.
- **Witnesses.** W-27–W-32 cover each predicate violated singly, submit-after-scan (lease refuses the
  submission), an unreadable reference source, a nested outward junction (not followed), and a
  successful owned-scratch positive.

## Part D. `handoff` and `dispatch` (R007)

`handoff` renders the hand-off and first runs the existing state, candidate and hand-off guards; no
template bypasses them. `dispatch` is a broker notification of kind `dispatch` and follows A5 exactly:
- the reply-to is pane plus agent session id;
- intent is journaled before send;
- the send boundary has the three checks;
- the text goes in one prompt submission, never a separate Enter;
- the outcome is recorded as `delivered`, `unknown` or `withheld`;
- `unknown` is never resent automatically.

A second dispatch of the same hand-off is refused unless the first is recorded `withheld`, or is recorded
`unknown` and later inspected and marked undelivered. Delivery is not turn acknowledgement; the
completion notification (§11.17) stays the only done signal. W-33–W-37 cover simultaneous dispatchers
(serialised, one send), crash after send (`unknown`), a delivered-but-timed-out prompt, a replaced session
and a pane that becomes blocked before the send, with zero keys in the prohibited cases.

## Part E. Gate launchers

Each launcher's self-test must show:
- environment and cache locations equal the broker-provided resources (B-14);
- the freshness method is recorded;
- a failed preflight forbids launch;
- the exit code and the `GATE-END` marker agree;
- a setup failure is a failure, never a pass;
- no process is ever signalled;
- a blocked or unknown notification is withheld.

Launchers run only through the broker. Minion-Agent's preflight, guard and watchdog become building
blocks. Container-private paths stay distinct from host binds.

## Part F. Fault-fired rule

The filled feasibility matrix and control recipe carry one cell per planned fault or selection, each with
platform and authority/binding attribution and a value of `fired`, `unfired` or `not-applicable(<declared
authority reason>)`. `minion-process` validates the accounting:
- a row is credited only when every planned cell fired, or is declared not-applicable with a reason;
- setup or compile failures are never kills;
- the baseline and intended-witness requirements of §9.7 remain.

The kit validates declared accounting only. It never decides whether a fault or an exception is valid.
W-38 covers a simple unfired cell, a mixed multi-injection row with one unfired cell, a forged
not-applicable without a reason, and a correct positive.

## Owner questions

None open. Q1 and Q2 are decided. B-26 may produce one risk decision after the herdr characterization.

## Out of scope

The replay suite and Minion-Memory re-adoption (P4); the guard hook; second machines and CI runners; any
change to what counts as evidence.
