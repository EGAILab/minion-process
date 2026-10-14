# P3b agreed contract (kit 0.4.0)

This folder holds the contract the kit 0.4.0 implementation follows, exactly as published on
`minion-agent#223` and agreed in convergence episode `CE-PROC-P3B-01`. Codex approved it in round 6,
and the agreement is recorded on `#223`.

**Precedence.** Read the files in this order. A later file replaces only the rules it names:

1. `contract-r3.md`: the base contract (Parts A–F, rules B-1 to B-33, witnesses W-1 to W-38, controls
   C-1 to C-6).
2. `checkpoint-r4.md`: K-1 to K-20 (no kit keystrokes, active set, build freshness, repair mode, cleanup
   class).
3. `checkpoint-r5.md`: K-21 to K-28 (Owner-chosen `CONFIRM QUEUE` channel, journal fault model).
4. `checkpoint-r6.md`: K-29 to K-31 (write-ahead effect markers, declared fault model, reconciliation).
5. `checkpoint-r7.md`: K-32 to K-40 (render attempts, conservative override fallback, cautions as rules).

**Correction folded in from Codex's round-6 note N001 (nonblocking).** K-34 says a crash before the
rename returns leaves only a temporary file. That sentence is too strong. A rename can publish the final
name before its caller sees the call return. Recovery therefore never infers absence from a missing
return value. It reads the final name: a present marker reserves the effect, and a missing one means the
effect did not start. The publication seam tests include this cut.

**Owner values** (decisions on `#209` and `#223`):

- queue folder `E:\AI\Projects\OpenMinds\Minions\.host-queue`;
- 2 concurrent `build`, `control` or `cleanup` jobs;
- a 16 GiB memory floor, compared in exact bytes;
- a 3-minute start-up reservation;
- override confirmation by `CONFIRM QUEUE <code>` typed by the Owner in a Claude session.

**Scope limit.** The agreement covers implementation only. Merge, release and Minion-Agent adoption each
need their own review. Until adoption, Codex keeps running the host build queue under `#209`.
