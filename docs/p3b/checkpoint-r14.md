# CE-PROC-P3B-01 checkpoint proposal, revision 14 (base: contract revision 3 + checkpoint revisions 4–13)

**Author:** Claude `w1:p8`. **Status:** PROPOSED. Codex round 14 accepted:
- the Owner's deferral of cleanup, which withdraws R006 from 0.4.0 scope without closing it as satisfied;
- the destructive withdrawal, K-46 and K-47;
- W-105, W-106 and C-22.

It raised **R011** (MEDIUM, a contract assurance defect). Revision 13's K-48 kept K-19 and K-38 "as
written", but both still hand an ended creator's copy to the refused cleanup class. This revision
replaces K-48 and supersedes only those cleanup-dependent clauses. Everything else in revisions 4 to 13
stands.

## Superseded clauses

| Clause | Superseded text | Replacement |
|---|---|---|
| contract r3 B-12 | "and is registered for cleanup (Part C)" | "and is registered (K-48′)" |
| contract r3 B-13 | "created and registered like B-12" | unchanged in words; registration now means K-48′ |
| K-19 | "The lease passes from creator to cleanup through the broker …" | K-48′ lease disposition |
| K-38 | "or the copy becomes a cleanup candidate if the job is ended"; "it is still subject to cleanup" | K-48′ replay rule |

These stay as written:
- creation-time registration in the journal, under the creator's lease;
- the `register/R` marker and its manifest;
- K-38's readable-case reconstruction of the manifest and the owning job;
- K-39's `damaged` classification, which is reused for a copy found inconsistent at recovery.

## K-48′ registration lifecycle without cleanup

- **States.** A registered copy is `held` while its creator job is in `launching`, `running` or
  `uncertain`. It is `released` once the creator is proven ended. Proof means K-41's workload-ended
  proof: the group is drained and the runner and any stray process are ended. A copy is never released
  early on an unknown or active workload.
- **Lease disposition.** While `held`, the creator keeps its exclusive lease on the copy. When the creator
  is proven ended, the broker **releases** that lease in the same journal transition that ends the job.
  The lease goes to no other job. Registration persists: the manifest and the `released` state.
- **No reuse.** A registered copy, whether `held` or `released`, is never leased by another job. A
  submission whose leases equal or overlap a registered copy's path is refused at submit with `path is a
  registered copy of job <id>`. A released copy can therefore hold no live work, and there is no instant
  in which a third job can claim it.
- **Replay.** On recovery, the broker reads a readable `register/R` and acts on its creator's
  reconstructed state:
  - **Not ended:** the creator is in `launching`, `running` or `uncertain`. The lease is restored to the
    creator, and the copy is `held`.
  - **Ended with workload-ended proof:** no lease is restored, and the copy is `released`.
  - **Unknown:** the creator's state cannot be reconstructed, or its proof is uncertain. The copy is
    `held` by the creator's job, which stays `uncertain` under K-41. Repair mode follows the existing
    rules.

  A registration whose manifest disagrees with the disk is `damaged`, as in K-39, and stays registered.
- **Manual removal.** Only the Owner removes a copy, by hand. `build status` lists every registered copy
  with its creator, state (`held`, `released` or `damaged`) and path. It reports a `released` copy whose
  path is now missing as `released, absent`. The broker never treats an absent copy as a reason to
  refuse or to repair. It never re-creates or deletes one.
- **Witnesses:**
  - **W-107′:** an evidence job E holds copy R, and E ends with workload-ended proof. The rows are:
    - the same step;
    - after a broker restart;
    - after a cut of E's end record followed by repair;
    - with E uncertain at restart.

    The expected disposition is `released` with no lease in the first two rows, then the K-41 outcome
    after repair, then `held` with E's lease restored when E is uncertain. R exists on disk and is listed
    in every row.
  - **W-107a:** a later job that names R, or a path inside R, is refused at submit while R is `held` and
    while it is `released`.
  - **W-107b:** after R is removed by hand, `build status` shows `released, absent`. The broker stays in
    normal mode, and admissions are unaffected.
- **C-23 (control):** keeping revision 4's creator-to-cleanup transfer leaves E's lease stranded after E
  ends, and W-107′ fails on its first row. Releasing at the end without proof also fails W-107′, on the
  uncertain row.

## Rule set for implementation revision 3 (replaces revision 13's list)

- **Implemented:**
  - K-41 (R002), K-42 with the addenda of revisions 9 to 11 (R003), K-44 (R010) and K-45;
  - K-46, K-47 and K-48′, with W-105, W-106, W-107′, W-107a, W-107b, C-22 and C-23.
- **Unchanged:**
  - the closures of R001, R004, R005, R007, R008 and R009;
  - every rule of revisions 4 to 7 that this revision and revision 13 do not withdraw or supersede.
- **Not in 0.4.0:** R006, withdrawn by the Owner's decision.
- **Docs:** `docs/p3b/README.md` now indexes revisions 8 to 14. It separates the effective rule set from
  the withdrawn scope and drops `cleanup` from the admitted classes.

## Request

Independent checkpoint review (§11.8.5) of revision 14's K-48′ and the rule set. Two questions:
- Does R011 close at checkpoint level?
- Is the implementation revision-3 rule set now coherent?

Answer **AGREED FOR IMPLEMENTATION**, or REJECTED with the failing dimension and a counterexample.
