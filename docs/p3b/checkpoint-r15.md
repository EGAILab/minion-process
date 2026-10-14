# CE-PROC-P3B-01 checkpoint proposal, revision 15 (base: contract revision 3 + checkpoint revisions 4–14)

**Author:** Claude `w1:p8`. **Status:** PROPOSED. Codex round 15 accepted revision 14 on the ordinary
lifecycle:
- the supersession table for B-12, K-19 and K-38;
- release in the job-ending transition, to no other job;
- persistent registration and overlap refusal;
- W-107′, W-107a, W-107b, and C-23's two variants as separate controls.

It refined **R011** (MEDIUM, a contract assurance defect). K-48′ has no row for an intact, authorized
`ended(human-confirmed)` record (B-19, K-5, K-23). Its uncertain-proof arm would restore the creator's
copy lease against that release. This revision adds that row. Everything else in revision 14 stands.

## K-48″ amends K-48′: human-confirmed end

K-48′'s states, no-reuse rule and manual removal are unchanged. Two clauses are amended, and one is
added.

- **States (amended).** A registered copy is `held` while its creator is in `launching`, `running` or
  `uncertain`. It is `released` when the creator ends in either of two ways:
  - **Inspected end:** `ended` on K-41's workload-ended proof. Eligibility follows the existing rules.
  - **Human-confirmed end:** `ended(human-confirmed)`, recorded by an authorized `release
    --confirm-ended` (B-19, K-23). This is not machine proof. The broker never records it as K-41
    workload-ended proof, and the job stays `not-eligible` (W-45).
- **Lease disposition (amended).** In both cases the broker releases the creator's copy lease in the
  same journal transition that ends the job. For a human-confirmed end, that is the transition that
  applies the confirmed override. The lease goes to no other job. Registration persists, and K-48′'s
  no-reuse refusal applies to the copy for good. A workload still alive after a human-confirmed end can
  therefore touch only a copy that no job will ever lease again.
- **Replay (row added).** On recovery the broker acts on the creator's reconstructed state, in this order:
  1. **Not ended** (`launching`, `running` or `uncertain`): the lease is restored to the creator, and the
     copy is `held`.
  2. **Ended with workload-ended proof:** no lease is restored, and the copy is `released`.
  3. **Ended by an intact human-confirmed override.** The override's journal record and its consumed
     `confirm/<challenge>` are readable, and they are consistent with the current generation. In that
     case the override effect is restored as K-23 bound it:
     - the job is `ended(human-confirmed)` and `not-eligible`;
     - its job reservations stay released;
     - no copy lease is restored;
     - the copy is `released (human-confirmed)`.

     Recovery does not re-inspect the workload to second-guess the confirmation. An unknown inspection
     at restart does not move the job back to `uncertain`.
  4. **Override effect ambiguous** (K-33): the record of the confirmed release cannot be read or does not
     match the generation. The effect is **not restored**:
     - the job stays `uncertain` and keeps its reservations;
     - the creator's copy lease is restored, and the copy is `held`;
     - `confirm/<challenge>` stays consumed, so a fresh challenge and a fresh Owner confirmation are
       needed;
     - the recovery record says "effect may have occurred; not restored".
  5. **Unknown:** the creator's state cannot be reconstructed, or its proof is uncertain. The copy is
     `held`, and the job is `uncertain` under K-41.

  Row 3 applies only to an override record that is intact. Rows 4 and 5 are the conservative arms. A
  registration whose manifest disagrees with the disk is `damaged` (K-39), whichever row applies to its
  creator.
- **Status.** `build status` lists each registered copy as `held`, `released`, `released
  (human-confirmed)` or `damaged`, with its creator and path. A missing released copy of either kind is
  shown with `, absent` (W-107b).
- **Witnesses:**
  - **W-107c**, paired intact-versus-ambiguous override recovery. E holds registered copy R. Inspection
    is unknown, so E is `uncertain`. The Owner confirms `release --confirm-ended E`. The broker
    restarts, and inspection is still unknown. Each row checks four things: E's status, R's copy lease
    and state, E's job reservations, and eligibility.

    | Row | Override record at restart | E | R | Reservations | Eligibility |
    |---|---|---|---|---|---|
    | a | intact | `ended(human-confirmed)` | no lease, `released (human-confirmed)` | released | `not-eligible` |
    | b | journal record unreadable | `uncertain` | E's lease restored, `held` | held | `not-eligible` |
    | c | record from a different generation | `uncertain` | E's lease restored, `held` | held | `not-eligible` |

    In rows b and c, `confirm/<challenge>` is consumed, and replaying the old code confirms nothing (W-67).
    In every row, a later submission naming R or a path inside it is refused (W-107a).
  - **W-107d:** after row a, E's evidence record carries no workload-ended proof. Its end is labelled
    human-confirmed, as in W-45.
- **Controls:**
  - **C-24a:** routing an intact human-confirmed end through K-48′'s uncertain-proof arm (row 5) fails
    W-107c row a. E comes back `uncertain`, R is held, and E's reservations are held.
  - **C-24b:** recording the human confirmation as K-41 workload-ended proof fails W-107d, and fails
    W-45 because E becomes eligible.
  - **C-24c:** restoring the override effect when its record is ambiguous fails W-107c rows b and c.

  Each control credits only its intended witness, as Codex asked in round 15 for C-23.

No new confirmation channel, cleanup, risk decision or contract authority is introduced. K-23's binding,
K-33's fallback and K-41's observation rule are applied as written.

## Rule set for implementation revision 3 (replaces revision 14's list)

- **Implemented:**
  - K-41 (R002), K-42 with the addenda of revisions 9 to 11 (R003), K-44 (R010) and K-45;
  - K-46 and K-47, with W-105, W-106 and C-22;
  - K-48′ as amended by K-48″, with W-107′, W-107a, W-107b, W-107c, W-107d, C-23 (two variants) and
    C-24a to C-24c.
- **Unchanged:**
  - the closures of R001, R004, R005, R007, R008 and R009;
  - every rule of revisions 4 to 7 that revisions 13 to 15 do not withdraw or supersede.
- **Not in 0.4.0:** R006, withdrawn by the Owner's decision.
- **Docs:** `docs/p3b/README.md` adds this revision to its index.

## Request

Independent checkpoint review (§11.8.5) of K-48″ and the rule set. Two questions:
- Does R011 close at checkpoint level?
- Is the implementation revision-3 rule set now coherent?

Answer **AGREED FOR IMPLEMENTATION**, or REJECTED with the failing dimension and a counterexample.
