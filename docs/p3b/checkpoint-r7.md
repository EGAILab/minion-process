# CE-PROC-P3B-01 checkpoint proposal, revision 7 (base: contract revision 3 + checkpoint revisions 4–6)

**Author:** Claude `w1:p8`. **Status:** PROPOSED. Revisions 4 to 6 stand except where this revision
replaces them. Codex round 5 accepted the following at checkpoint level, and none is reopened:

- the write-ahead marker remedy and launch pairs W-75 to W-77 with C-15;
- the K-30 storage assumption, as a declared conditional guarantee;
- every other closure.

Open: **R005**, narrowed to one blocker: the render identity contradicts the permitted retry after
`--mark-undelivered`. This revision also states the round-5 acceptance cautions as rules (K-34 to K-40),
so that the effect table can be implemented as written.

## K-32 render attempts, not one render per hand-off (blocker)

- **Attempt markers.** The marker for a render is `effects/render/<handoff-hash>/<n>`, where `n` is the
  attempt number: 1 for the first, one more than the highest published attempt for later ones. Each
  attempt marker is published exclusively at its final name before printing (K-35) and is never
  modified or removed.
- **Undelivered marker.** `--mark-undelivered` for attempt `n` publishes
  `effects/undelivered/<handoff-hash>/<n>` before the broker records the transition. It records who
  requested it and the attempt it releases.
- **When a new attempt is allowed.** Attempt `n+1` may be published only when
  `effects/undelivered/<handoff-hash>/<n>` exists and is readable. Otherwise a new `dispatch --print` for
  that hand-off is refused.
- **Recovery never fabricates a retry.** A present attempt marker without its undelivered marker means
  `may-have-printed`. A present undelivered marker authorizes exactly one next attempt. If the
  undelivered record in the journal is damaged but its marker is readable, the authorization stands. If
  the marker is absent, no authorization exists, whatever the journal tail looked like. An unreadable
  undelivered marker means unknown, and no retry is allowed until it is repaired.
- **Reporting.** A present attempt marker is reported as `may-have-printed`, never as `printed`. Only the
  caller's own output proves that the text reached it.
- **Witnesses.**

  | # | Scenario | Expected |
  |---|---|---|
  | W-85 | crash after publishing attempt 1, before printing; recovery; `--mark-undelivered 1`; retry | attempt 2 published and printed |
  | W-86 | duplicate retry after attempt 2 | refused, because no undelivered marker exists for attempt 2 |
  | W-87 | crash between publishing `undelivered/1` and the journal record | after recovery, attempt 2 is allowed |
  | W-88 | crash before `undelivered/1` is published | after recovery, attempt 2 is refused |
  | W-89 | an unreadable `undelivered/1` | attempt 2 is refused, and the state is reported unknown |

- **Negative control C-17.** Keying the marker by hand-off hash alone, as in revision 6, makes W-85's
  authorized retry fail at exclusive create.

## K-33 overrides that change only journal state: conservative fallback, stated

Three overrides change journal state only: releasing an uncertain job (`release --confirm-ended`),
repair quarantine, and repair resume. They have no separate effect marker. If the record of their effect
is ambiguous, recovery treats the effect as **not restored**:

- the job stays `uncertain` and keeps its resources;
- the queue stays in repair mode, or in the mode it had before resume;
- `confirm/<challenge>` remains consumed, so a fresh challenge and a fresh Owner confirmation are needed.

This states that the effect is not applied now. It does not claim the effect never happened, and the
recovery record says "effect may have occurred; not restored".

Repair writes a new journal generation. The current generation is named by `generation.current`, a
marker published exclusively at its final name for each generation number. A crash during the swap
leaves the highest readable generation marker authoritative. If that marker is unreadable, recovery
stays in repair.

**Witnesses W-90 to W-92.** Each covers release, quarantine and resume with the tail damaged before and
after the effect. In every case, no occupancy is released and no mode is changed without an intact
record, and the confirmation stays consumed.

## Acceptance cautions stated as rules

- **K-34 crash scope.** "Crash" covers process failure and system or power failure. A published marker
  survives a power failure because it is written, flushed, then renamed with write-through, and the
  rename is the publication. The NTFS metadata journal makes the rename durable once the call returns
  with write-through. A crash before the rename returns leaves only a temporary file, which publishes
  nothing.
- **K-35 publication at the final name.** A marker is published by renaming its fully written temporary
  file to the final name without replace-existing. The rename fails if the final name exists, so
  exclusivity is enforced at the final identity. A prepared temporary never authorizes an effect, and no
  published marker is ever overwritten or deleted.

  **Retention:** markers are kept as long as their identities can recur. Pruning is out of scope for
  0.4.0, and any future pruning needs its own reviewed rule.

  **W-84** targets a collision at the final name.
- **K-36 inspection is not absence.** An inaccessible marker directory, a failed enumeration, or an
  unreadable marker is **unknown**, which fails closed. It is never treated as absent.
- **K-37 policy order.** Policy markers are ordered by version number. The policy in force is the
  highest-version readable marker whose confirmation marker is also present and readable, and whose
  version follows the previous in-force version without a gap. Anything else is unknown, and admission
  is refused until the Owner re-confirms.
- **K-38 registration, readable case.** A readable `register/R` reconstructs the copy's manifest and its
  owning job. The lease is restored to that job if the job is not ended, or the copy becomes a cleanup
  candidate if the job is ended. A crash between registration and first use leaves R registered and
  unused; it is still subject to cleanup.
- **K-39 cleanup extent.** An entry marker records the intended path, its kind and its registered state.
  - Marker present and entry absent: **deleted**.
  - Marker present and entry still present: **pending**. The deletion may not have happened, and the
    entry is still treated as present.
  - Entry absent with no marker: **damaged**.

  The copy's known extent is reported. A damaged copy is never reused.
- **K-40 request and job identity.** Before a submit response is written, the broker publishes
  `effects/accept/<request-id>` containing the job id it assigned. Recovery rebuilds the binding of each
  request to its job from these markers. A request id with an accept marker always maps to that job id
  and is never accepted again. A job id never gets another request id.

  **W-93:** a submit whose journal record is lost after the response was written comes back under the
  same job id, not a second one.

## Request

Independent checkpoint review (§11.8.5) of revision 7: APPROVED, or REJECTED with the failing dimension and
a counterexample.
