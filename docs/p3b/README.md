# P3b contract (kit 0.4.0)

This folder holds the contract the kit 0.4.0 implementation follows, as published on `minion-agent#223`
and reviewed in convergence episode `CE-PROC-P3B-01`.

**History.**
- **Revision 7:** Codex approved it in round 6.
- **Invalidation:** kit `WORKFLOW.md` §11.8.10 invalidated that agreement after Codex round 8. Two
  implementation closure attempts had failed on R002, R003, R006 and R010.
- **Revisions 8 to 15:** characterization resumed.
- **Owner decision (2026-10-14):** cleanup is deferred from 0.4.0, which withdraws R006.

**Precedence.** Read the files in this order. A later file replaces only the rules it names:

1. `contract-r3.md`: the base contract (Parts A–F, rules B-1 to B-33, witnesses W-1 to W-38, controls
   C-1 to C-6).
2. `checkpoint-r4.md`: K-1 to K-20 (no kit keystrokes, active set, build freshness, repair mode, cleanup
   class).
3. `checkpoint-r5.md`: K-21 to K-28 (Owner-chosen `CONFIRM QUEUE` channel, journal fault model).
4. `checkpoint-r6.md`: K-29 to K-31 (write-ahead effect markers, declared fault model, reconciliation).
5. `checkpoint-r7.md`: K-32 to K-40 (render attempts, conservative override fallback, cautions as rules).
6. `checkpoint-r8.md`: K-41 (three-valued observations), K-44 (total request validation), K-45 (generated
   witnesses). Its K-42 and K-43 are superseded.
7. `checkpoint-r9.md` to `checkpoint-r11.md`: K-42 as amended (slot roles, declared access, launch proof
   of every writable directory resource).
8. `checkpoint-r12.md`: K-43″. It is withdrawn, but kept as evidence for a later cleanup release.
9. `checkpoint-r13.md`: the withdrawal of cleanup, K-46 and K-47.
10. `checkpoint-r14.md`: K-48′ (registration lifecycle without cleanup).
11. `checkpoint-r15.md`: K-48″ (human-confirmed end of a copy's creator) and the rule set for
    implementation revision 3.

**Withdrawn from 0.4.0 (Owner decision, `#223`):**
- contract Part C;
- K-17;
- K-18 as a deletion predicate;
- K-39's cleanup markers;
- every revision of K-43;
- the cleanup-dependent clauses of B-12, K-19 and K-38.

The withdrawn text stays in the files above as history. The rule set in `checkpoint-r15.md` is the
effective one.

**Correction folded in from Codex's round-6 note N001 (nonblocking).** K-34 says a crash before the
rename returns leaves only a temporary file. That sentence is too strong. A rename can publish the final
name before its caller sees the call return. Recovery therefore never infers absence from a missing
return value. It reads the final name: a present marker reserves the effect, and a missing one means the
effect did not start. The publication seam tests include this cut.

**Owner values** (decisions on `#209` and `#223`):

- queue folder `E:\AI\Projects\OpenMinds\Minions\.host-queue`;
- 2 concurrent `build` or `control` jobs;
- a 16 GiB memory floor, compared in exact bytes;
- a 3-minute start-up reservation;
- override confirmation by `CONFIRM QUEUE <code>` typed by the Owner in a Claude session;
- no cleanup class in 0.4.0. Registered copies are removed by hand.

**Scope limit.** An agreement covers implementation only. Merge, release and Minion-Agent adoption each
need their own review. Until adoption, Codex keeps running the host build queue under `#209`.
