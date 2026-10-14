# CE-PROC-P3B-01 checkpoint proposal, revision 6 (base: contract revision 3 + checkpoint revisions 4 and 5)

**Author:** Claude `w1:p8`. **Status:** PROPOSED. Revisions 4 and 5 stand except where replaced here.
Closed at checkpoint level and not reopened: R002, R003, R006, R007 (round 3) and R008 (round 4, under the
Owner's procedural model and K-22's stated limits). Open: **R005**, narrowed in round 4 to whether the
recovery proof covers every protected effect.

**The gap, restated.** K-27 proved "nothing runs now" and "registered roots exist". That says nothing about
an effect that already happened and left nothing behind: a launch that ran and finished, a printed render,
a policy change, a consumed confirmation, or one deleted child of a registered copy. The journal is the
only record of those effects, and its damaged tail is exactly what is unreadable.

**Remedy in kind.** Each protected effect gets a second, independent record written *before* the effect
and never rewritten: an **effect marker**. Recovery reconciles the effect markers with the journal. A marker
proves the effect may have happened. Its absence proves the effect did not happen, under the declared
fault model.

## K-29 effect markers (write-ahead, one file per effect)

Before performing a protected effect, the broker creates its marker with exclusive-create semantics,
then flushes it. The marker file is written in full (content plus checksum) before it is renamed into
place, and it is never modified afterwards. The marker records:

- the effect kind and its exact identity;
- the journal sequence number of the intent record it follows;
- for policy, the full new policy content.

| Effect | Marker created before | Marker identity |
|---|---|---|
| launch | the runner is spawned | `effects/launch/<job-id>` |
| render (`dispatch --print`) | the text is printed | `effects/render/<handoff-hash>` |
| policy change | the new policy takes effect | `effects/policy/<version>` (contains the policy) |
| confirmation consumed | the bound override effect is applied | `effects/confirm/<challenge-id>` |
| cleanup deletion | each entry is deleted | `effects/cleanup/<job-id>/<entry-seq>` (path, kind, size) |
| copy registration | a registered copy is first used | `effects/register/<copy-id>` (complete manifest of entries) |

Exclusive-create makes each effect at-most-once by itself. A second launch of the same job id cannot
create `effects/launch/<job-id>` and is refused even if the journal were lost. B-17 (one launch) therefore
holds independently of the journal.

## K-30 declared fault model (replaces K-25)

Two faults are handled:

- **(a)** a crash at any instant, including mid-append to the journal and mid-write of a marker before its
  rename;
- **(b)** corruption of any bytes inside the journal or inside any marker file.

Loss of a whole file or directory entry through file-system metadata damage is **outside** the model and
is stated as an assumption. A marker file that exists but is unreadable or fails its checksum counts as
**present with unknown content**, so it fails closed. A marker that is absent means the effect never
started, because the marker is always created first.

## K-31 recovery by reconciliation (replaces K-27)

On any journal anomaly the broker stays in repair mode and admits nothing until reconciliation finishes.
Let *G* be the last good record. Reconciliation considers every marker whose sequence is after *G*, and
every marker that names an effect the replayed prefix does not show. It does not need to know the kind of
the ambiguous record, because it scans every marker kind (K-26).

| Marker found | Outcome |
|---|---|
| none for job J, and inspection proves no workload labelled J | J was never launched. J stays `submitted` and is launchable. This is the genuine pre-spawn interruption, recoverable without the Owner. |
| `launch/J` present, workload running | J becomes `uncertain`, active, holding its resources, never relaunched |
| `launch/J` present, no workload, inspection succeeded | J becomes `ended(unknown-outcome)`: not relaunched, `not-eligible`. The agent resubmits under a new job id if it wants a run. |
| `launch/J` present, inspection failed or denied | J becomes `uncertain`, and the host is blocked (K-10) |
| `render/H` present | the render counts as done, and a further render of H is refused until `--mark-undelivered` |
| `policy/V` present and readable | policy V is in effect, with its recorded confirmation |
| `policy/V` unreadable | the policy is unknown; admission is refused until the Owner re-confirms a policy (K-21) |
| `confirm/C` present | challenge C is consumed and can never be used again. Its bound effect is in force if that effect's own marker is present; otherwise the effect is treated as not applied, and a new challenge is needed. |
| `cleanup/J/*` present | for each copy, the registered manifest is compared entry by entry with the disk. If they reconcile (every deleted entry has a marker and every other entry is present), the copy's state is known exactly. Otherwise the copy is `damaged`: never used again, still held by J's lease until a new cleanup job finishes it. |
| `register/R` unreadable | copy R is `damaged` |
| a marker naming an unknown kind or identity | host-blocking `uncertain`, repair needs the Owner |

After reconciliation the broker writes a recovery record that names *G*, the quarantined bytes and every
outcome above. It resumes automatically **only** when every outcome is in the first row's class or is a
known terminal outcome: `ended(unknown-outcome)`, a counted render, a consumed challenge, a readable
policy or a reconciled cleanup. Every other outcome stays in repair mode until the Owner confirms with
K-21.

Mid-journal anomalies still require repair (K-28). The same reconciliation runs inside repair before
`--resume`.

## Witnesses (replace W-70 to W-74; C-14 kept)

**Launch pairs**, each behind the same damaged `launching` record for J (enlarged length, removed marker,
bad checksum):

| # | State behind the damaged record | Expected |
|---|---|---|
| W-75 | never started: no `launch/J` | J `submitted`; launched once in total |
| W-76 | still running | J `uncertain`; launch count 1 |
| W-77 | already finished | J `ended(unknown-outcome)`; launch count **1, not 2** |

**Other effects and fault cases:**

| # | Scenario | Expected |
|---|---|---|
| W-78 | damaged tail after a `dispatch --print` | a second print of the same hand-off is refused |
| W-79 | damaged tail after a confirmed policy change | policy V in force when its marker is readable; admission refused when the marker is corrupted |
| W-80 | damaged tail after a confirmation was consumed | the challenge cannot be reused |
| W-81 | registered root present, one child deleted, its cleanup marker present | reconciled exactly |
| W-82 | registered root present, one child missing, no cleanup marker | `damaged`, never reused |
| W-83 | a marker with corrupted content | treated as present-unknown, fails closed |
| W-84 | an exclusive-create collision on `launch/J` | the second launch is refused |

**Negative controls:**

- **C-14** (kept): discarding every short or markerless tail makes W-76 relaunch.
- **C-15**: K-27's rule, "no live workload, therefore replay submitted", makes W-77 launch twice (intended witness).
- **C-16**: markers written after the effect instead of before make W-77 or W-78 repeat the effect.

## Request

Independent checkpoint review (§11.8.5) of revision 6: APPROVED, or REJECTED with the failing dimension and
a counterexample.
