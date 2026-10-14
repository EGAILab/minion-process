# CE-PROC-P3B-01 checkpoint proposal, revision 13 (base: contract revision 3 + checkpoint revisions 4–12)

**Author:** Claude `w1:p8`. **Status:** PROPOSED.

**Owner decision, 2026-10-14, recorded on `minion-agent#223`:** the cleanup class is deferred from kit
0.4.0. Its trigger was R006, which failed five consecutive checkpoint rounds (Codex rounds 9 to 13). Each
of those reviews found a new free-text spelling of a reference. Asked to choose between deferring cleanup,
approving a definition of "reference", and further rounds, the Owner answered `1`.

This revision states the withdrawal and fixes the agreed rule set for implementation revision 3.

## Withdrawn from 0.4.0

| Rule | Withdrawn part |
|---|---|
| Contract r3 Part C | the whole `cleanup` class: leased removal, the destructive-boundary predicates, the report and dry-run default, W-27 to W-32 |
| K-17 | `cleanup` as a fourth admitted class |
| K-18 | the reference set as a deletion predicate. Its `retain` flag stays as recorded job metadata only. |
| K-39 | cleanup extent markers (`effects/cleanup/...`) and their reconciliation (checkpoint r6 rows, W-81, W-82) |
| K-43 (every revision) | reference decoding, placement, resolution and context, with W-100 to W-102 and C-20 to C-20f |
| Revision-2 code | `apply`/dry-run, `cleanup_references`, `_cleanup_predicates`, late-submission refusal against a cleanup lease, `GitOps.unpushed` as a deletion gate |
| Contract r3 Part B | `session start`'s "lists cleanup candidates". It lists registered copies instead, without classifying them. |

R006 is **withdrawn from 0.4.0 scope by Owner decision**. It is not closed as satisfied. The round-9 to
round-13 records, and K-43's accepted direction, are the starting evidence for a later cleanup release.

## What 0.4.0 guarantees instead

- **K-46 no deletion outside queue state.** The broker deletes and renames only inside its own queue
  folder: its own inbox temporaries (K-20), its own staging files, and request files it moves to
  `rejected/`. All of these stay under the R009 `fsops` guard. It never removes:
  - a registered copy;
  - an execution worktree;
  - a target, cache, log or temporary folder;
  - any path outside the queue folder.
- **K-47 a cleanup request is refused.** A `submit` with class `cleanup` is answered with the ordinary
  refusal `cleanup is not supported in 0.4.0`, with no admission, no lease and no effect. The `build
  cleanup` verb is removed from the CLI.
- **K-48 registration stays.** B-12, B-13, K-19 and K-38 stay as written. Copies are registered with
  their creator job, the lease passes back as specified, and recovery rebuilds registrations. An ended
  job's registered copy simply stays registered. `build status` lists registered copies with their
  creator and state, and removal is manual. A job's own temporary folder is never reused by another
  job.
- **Witnesses:**
  - **W-105:** a cleanup submission is refused, and the journal shows no admission and no lease.
  - **W-106:** a static check finds that only `fsops` calls under queue-folder roots delete or rename.
    Interception over a full job lifecycle, crash recovery included, shows zero deletions outside the
    queue folder.
  - **W-107:** a registered copy survives its creator's end, a broker restart and repair mode, and
    `build status` lists it.
- **C-22 (control):** a broker that admits the cleanup class, as revision 2 did, fails W-105.

## Rule set for implementation revision 3

- **Agreed or accepted at checkpoint level, and implemented:**
  - K-41 with its round-9 cautions (R002);
  - K-42 as revisions 9 to 11 amended: slot roles, declared access, and the launch proof of every
    writable directory resource (R003);
  - K-44 with its round-9 cautions (R010);
  - K-45 for those three rules.
- **New:** K-46 to K-48, with W-105 to W-107 and C-22.
- **Unchanged:**
  - the closures of R001, R004, R005, R007, R008 and R009;
  - every revision-4 to revision-7 rule that does not concern cleanup.
- **Implementation closure:** the targeted closure covers R002, R003 and R010, and confirms that R006's
  scope withdrawal is implemented by K-46 to K-48.

## Adoption impact

- The profile no longer has `cleanup_references`.
- There is no cleanup verb. Copies under the execution root accumulate until someone removes them by
  hand, which is today's practice.
- `ADOPTION.md` and the changelog will say so.

## Request

Independent checkpoint review (§11.8.5) of revision 13, covering two questions:
- Is the withdrawal complete? Specifically, does any remaining rule still delete or depend on cleanup?
- Is the rule set for implementation revision 3 coherent?

Answer **AGREED FOR IMPLEMENTATION**, or REJECTED with the failing dimension and a counterexample.
