# CE-PROC-P3B-01 checkpoint proposal, revision 4 (contract base: revision 3)

**Work package:** `minion-agent#223`, `CONTRACT_CONVERGENCE`, episode `CE-PROC-P3B-01` (trigger A: R002,
R003, R005, R006 and R007 survived Codex rounds 1 and 2). **Author:** Claude `w1:p8`. **Status:** PROPOSED;
needs Codex's independent approval before AGREED FOR IMPLEMENTATION. **Base:** contract revision 3
(issuecomment-6139424852). Every rule of revision 3 stands unless this checkpoint replaces it. R001 and R004
are closed at proposal level (round 2) and are not reopened. The Owner values are unchanged: the
`.host-queue` folder; 2 concurrent build, control or cleanup jobs; a 16 GiB floor in exact bytes; a
3-minute start-up reservation.

```text
EPISODE             CE-PROC-P3B-01
TRIGGER             A, R002 R003 R005 R006 R007 (two independent reviews each)
OPEN FINDINGS       R002 (HIGH), R003 (MEDIUM), R005 (HIGH), R006 (MEDIUM), R007 (HIGH), R008 (HIGH)
ROOT-CAUSE SURFACE  host build queue contract: occupancy, freshness, recovery, cleanup, send boundary, override authority
AUTHORITY           kit WORKFLOW.md §11.8, §11.10; record §6.5, §6.7; Owner decisions on #209 and #223
```

**Approach in kind.** Two of the six findings are about the edges where the queue touches something it
cannot control atomically: another agent's pane (R007) and a human's authority (R008). For R007,
revision 4 **removes the side effect from scope** rather than trying to make it safe. P3b sends no
keystrokes to any pane. For R008 it uses the one channel the agents' tools do not drive: an interactive
console. The remaining four findings are finite rule completions.

## R007: no keystrokes from the kit in P3b (scope narrowing)

- **K-1 (replaces B-11 of revision 2, B-22–B-26 and Part D's send path of revision 3).** In kit 0.4.0,
  neither the broker nor any `minion-process` verb sends keys, prompts or Enter to any herdr pane.
- **K-2 job completion is pulled, not pushed.** `build wait <job> [--timeout <s>]` blocks until the job
  ends, is refused or becomes `uncertain`, or the timeout passes. It then prints the job record and exits
  with a code that encodes the outcome. An agent runs it in the background, and its own harness tells it
  when the command finishes. That is the completion signal; the job record is the evidence. `build
  status` lists everything.
- **K-3 dispatch is rendering only.** `handoff <wp> --type <t>` renders the hand-off after running the
  existing state, candidate and hand-off guards. `dispatch <wp> --print` journals a dispatch record (work
  package, exact hand-off hash, target pane and agent session id) and prints the text. Delivery stays
  with each project's existing, Owner-governed helper (Minion-Agent: `.tmp/claude-scratch/lib/
  codex-dispatch.sh`). A second `dispatch --print` of the same hand-off hash is refused unless the first
  is marked undelivered by `dispatch --mark-undelivered <id>`.
- **K-4 deferred, not dropped.** Automatic, verified sending (record §6.5 steps 2–4) moves to a later work
  package. That package starts with the adversarial read-to-send characterization Codex specified in
  round 2 (a state or session change between the read and the submission, and reported-state lag). Until
  then nothing in the kit sends keys. This narrows record §6.5; the Owner is notified of the deferral.
- **Witnesses.**
  - W-21 and W-33–W-37 of revision 3 are withdrawn; nothing is sent.
  - **W-39:** `build wait` returns on `ended`, `refused`, `uncertain` and timeout, with distinct exit
    codes.
  - **W-40:** no kit code path calls herdr with `prompt`, `send-keys` or an equivalent. This is a static
    check over the package plus a runtime seam that fails on any call.
  - **W-41:** a duplicate `dispatch --print` of the same hand-off is refused across a broker restart.
  - **C-7 (negative control):** a `prompt` call injected into the broker makes W-40 fail.

## R008: human overrides need an interactive console confirmation

- **K-5 overrides.** These actions need a human: `policy set`, `release --confirm-ended`, `repair
  --quarantine`, and repair's final `resume` (K-12). For each, the broker issues a **challenge**: a random
  one-time code bound to the action, the job id and journal generation (or the policy version), and the
  exact effect. The challenge is journaled and expires after 15 minutes.
- **K-6 confirming.** A challenge is confirmed only by `minion-process build confirm`. That command
  refuses unless its standard input is an interactive console: not redirected, not a pipe, not null. The
  agents' harnesses run commands without an interactive console, so agents cannot confirm. The command
  shows the bound action and effect, reads the code typed at the console, and appends the confirmation,
  with the console user name, to the journal.
- **K-7 trust statement.** This separates a human at the console from an agent's command. It is not
  authentication against a hostile program run by the same Windows user, and the contract says so. It
  meets §11.10's provenance requirement because the record names the action, its exact scope and when a
  person at the console confirmed it.
- **K-8 effects of an override.**
  - Agents may *request* an override; the request only creates the challenge.
  - An unconfirmed, expired, wrong-scope, replayed or stale-generation confirmation changes nothing.
  - A confirmed `release --confirm-ended` marks the job `ended(human-confirmed)`, which is always
    `not-eligible` and distinct from an inspected `ended`.
  - A policy change's challenge also records the Owner decision it implements: a comment link supplied
    in the request and shown at the console.
- **Witnesses.**
  - **W-42:** confirm with redirected, piped and null stdin is refused, and nothing changes.
  - **W-43:** a wrong code, a used code, an expired challenge, and a challenge for job A used on job B or
    on a later generation are each refused.
  - **W-44:** a valid console confirmation changes exactly the bound effect.
  - **W-45:** a human-confirmed end is `not-eligible` and labelled as such.
  - **C-8 (negative control):** with the console check removed, W-42 confirms from a pipe.

## R002: launching and uncertain jobs occupy the host

- **K-9 the active set.** The admission-active set is every job in `launching`, `running` or `uncertain`.
  B-9 is restated over that set:
  - **(a)** no admission of any class while an active job is `evidence`;
  - **(b)** `evidence` is admitted only when the active set is empty;
  - **(c)** for `build`, `control` and `cleanup`, the active set holds fewer than 2 jobs, and memory minus
    reservations is at least the floor.

  An active job's reservation does not expire while it is `uncertain`; only `running` jobs leave the
  3-minute window.
- **K-10 unknown extent.** An `uncertain` job whose resource footprint cannot be read, for example after
  repair (K-12), is **host-blocking**: it acts as an active `evidence` job, so nothing is admitted until
  it is resolved by inspected proof or a K-6 confirmation.
- **K-11 transitions.** The transition list adds `launching → uncertain` and `launching → refused`. The
  latter is allowed only when the broker proves no workload started: the job object exists empty and no
  labelled container exists. A failed launch that cannot prove this becomes `uncertain`; changing a
  state never releases occupancy by itself.
- **Witnesses.**
  - **W-46:** an `uncertain` control job on unrelated paths, then an evidence submit: not admitted.
  - **W-47:** an `uncertain` job past 3 minutes still reserves memory.
  - **W-48:** crash after `launching`, before `running`: the job is active, and evidence is not admitted.
  - **W-49:** a partially failed launch (job object created, container start error) becomes `uncertain`,
    not `refused`.
  - **W-50:** an unknown-extent uncertain job blocks every class.
  - **C-9 (negative control):** an admission that counts only `running` jobs fails W-46 and W-48.

## R003: freshness for build jobs

- **K-12a build preparation phase.** A `build` job takes an **exclusive** lease on the agent's checkout for
  a short preparation step. That step gives every workspace-member source a fresh modification time, a
  contained, content-neutral touch with per-entry containment, and records the method. The lease then
  drops to shared for the run. The preparation waits for any job holding the checkout shared, so it never
  touches a checkout another job is reading. Build results stay uncredited.
- **Witness W-51:** an older checkout and a newer shared target with a planted stale artifact. With the
  preparation step the build recompiles and runs the checkout's code. **C-10 (negative control):** the
  same scenario with preparation disabled runs the stale artifact, observed through a marker constant.
  This is consumer-side and needs cargo, like C-6, and is recorded with its baseline and exact artifact.
  A kit-level seam test proves the ordering: exclusive, then touch, then shared.

## R005: repair without a healthy broker, and honest torn-write handling

- **K-12 repair mode.** `build broker --repair` acquires the same Global mutex, never admits a job and
  never launches anything. It is the only writer while repairing.
  - `--inspect` is read-only.
  - `--quarantine` copies the original journal bytes to `quarantine/<time>/` and writes a recovery
    journal, after a K-6 confirmation.
  - Every job whose state or footprint the damaged journal cannot establish becomes `uncertain`
    (host-blocking under K-10 when its footprint is unknown).
  - `--resume` (K-6 confirmed) returns to normal mode.
- **K-13 record framing.** Each journal record is length-prefixed, carries a checksum, and ends with a
  commit marker written in the same flushed write.
  - **Incomplete append:** the final record has a short length or no commit marker. Only this case may be
    discarded at replay, because the broker never acts on an uncommitted record.
  - **Corruption:** a complete record, with its commit marker, whose checksum fails, at any position.
    The broker refuses to start and repair is needed. It never infers that the record's effect did not
    happen.
- **K-14 request deduplication.** The journal records every accepted request id. On replay, a request id
  already in the journal returns its recorded outcome and is never accepted again, so a committed request
  whose response file is missing cannot become a second job.
- **K-15 snapshots.** A snapshot names the journal sequence and hash it reflects. On load it must match
  the journal, or it is ignored and the journal is replayed.
- **K-16 OS notes from round 2 adopted.**
  - Replay runs on every start, whether or not the mutex reports abandonment.
  - Access denied or a type conflict on `Global\` refuses; there is no fallback to `Local\`.
  - One broker thread owns the mutex for the broker's lifetime.
  - Job objects:
    - each workload is created suspended, assigned to its job object, then resumed;
    - breakaway is not permitted;
    - no kill-on-close or other kill limit is set;
    - broken tracking means `uncertain`.
  - Containers are labelled at creation.
  - Client waits are bounded. `status` reports `unavailable`, `starting`, `recovering` or `running`; a
    stale heartbeat only alerts.
  - Bypass counters are journaled, and an earlier evidence job blocks later admission even when a build
    ahead of it is bypassable.
- **Witnesses.**
  - **W-52:** an invalid journal with no healthy broker, then `--repair --inspect`, quarantine and
    resume, each confirmed: no job is admitted until resume.
  - **W-53:** a complete final record with a bad checksum makes the broker refuse; an incomplete
    uncommitted append is discarded.
  - **W-54:** restart after the first `launching`: active, not relaunched.
  - **W-55:** a damaged resource identity becomes a host-blocking `uncertain` job.
  - **W-56:** repair with process inspection denied: jobs stay `uncertain`.
  - **W-57:** a committed request with a lost response is returned, not re-accepted.
  - **W-58:** a snapshot mismatched with the journal is ignored.
  - **W-59:** two brokers, the first's last handle closed (no abandonment signal): the second still
    replays.
  - **W-60:** `Global\` access denied refuses.
  - **C-11 (negative control):** discarding every bad-checksum final record makes W-53 lose the live job.

## R006: cleanup as an admitted class with an exact reference set

- **K-17 class.** `cleanup` is a fourth class. It is admitted like `build` and `control` (counts toward
  the limit of 2) and never alongside `evidence`. It is never evidence. It holds an exclusive lease on
  each target from admission until the last entry is deleted or the job ends.
- **K-18 reference set.** A path is referenced, and cannot be removed, when any of these name it:
  - a job in `submitted`, `launching`, `running` or `uncertain` state;
  - a job record marked `retain` (an `eligible` evidence job keeps its execution worktree until its work
    package closes);
  - an open work package's state;
  - an incident record;
  - the authority cache.

  Excluded, and only these: the ended creator job of a registered copy, and the cleanup job itself.
  Historical records of ended jobs keep their text and do not count as references. A reference source
  that cannot be read means refuse.
- **K-19 registration lease.** A tool-created copy is registered in the journal by its creator job at
  creation, under that job's lease. The lease passes from creator to cleanup through the broker, so no
  instant exists in which a third job can claim the path unseen.
- **K-20 inbox temporaries.** Inbox temporaries belong to their writing client. The broker removes only
  temporaries it wrote itself, identified by its instance id in the name, and never another client's
  in-progress temporary.
- **Witnesses.**
  - **W-61:** a real positive through ordinary submit and admission, with the creator and cleanup job
    records present: removed.
  - **W-62:** the same copy named by a submitted job: refused.
  - **W-63:** named in an incident record: refused.
  - **W-64:** a `retain` evidence worktree: refused.
  - **W-65:** a client's in-progress inbox temporary across a broker restart: untouched.
  - **C-12 (negative control):** an empty reference set makes W-62 remove a live job's copy.

## Parts B and E notes adopted

- W-26's write ledger names the Git fetch's actual metadata and temporary writes, and the report file
  inside the project root.
- Client inbox writes use the per-operation containment proof (lexical, then no-follow real path), the
  same as the broker's writes.
- Launcher self-tests add build-preparation freshness (K-12a).

## Request

Independent checkpoint review (§11.8.5) of revision 4 on revision 3: APPROVED, or REJECTED naming the
failing dimension, with a concrete counterexample for each rejection. AGREED FOR IMPLEMENTATION is
recorded on #223 only after Codex approves. The K-4 deferral is reported to the Owner; it needs no Owner
decision because it removes an action and grants no new authority.
