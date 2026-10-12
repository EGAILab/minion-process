# Finding taxonomy

**Referenced by:** `WORKFLOW.md` §6. A profile maps its historical names onto these classes with
`taxonomy_aliases` (for example Minion-Agent's `PI_PARITY_DEFECT` → `AUTHORITY_PARITY_DEFECT`). Aliases
are names for the same class, never a sixth class.

Every material issue uses exactly one established classification:

- `AUTHORITY_BEHAVIOR_UNCERTAIN`: the authority's behavior is not sufficiently known. Stop the semantic
  decision, inspect the authority, then update contract and evidence.
- `AUTHORITY_PARITY_DEFECT`: the implementation differs from known authority-visible behavior. Fix
  before certification unless an intentional divergence is explicitly approved.
- `CONTRACT_ASSURANCE_DEFECT`: spec, conformance, manifest or evidence is incomplete, contradictory, or
  insufficient for independent implementation. Repair before certification; this is not risk debt.
- `PARITY_NEUTRAL_HARDENING`: internal quality improvement that preserves observable semantics. Normally
  fix in the current phase.
- `PARITY_CONSTRAINED_RISK`: fixing the issue would change authority-visible behavior. Preserve the
  compatible baseline and record the risk unless governance explicitly approves a divergence.

Do not invent softer labels to avoid a blocker.

## Dispositions of a confirmed difference

A reviewer still reports every confirmed difference from the authority, with discriminating evidence
and its usual classification. Its disposition is one of:

- **required parity**: fix it;
- **an existing approved architectural mapping**;
- **an intentional divergence**: this needs Owner governance.

Screening questions for a divergence candidate:

1. Is the behaviour part of the authority's intentional abstraction?
2. Can it realistically occur during normal documented usage?
3. Would exact parity require substantial architecture or emulation primarily for this behaviour?

"No, no, yes" is a strong candidate, but only the Owner accepts a divergence. The author brings an
options packet and never self-accepts.

An accepted divergence must have all of:

- a deterministic, documented behaviour;
- a permanent witness showing exactly where the implementation and the authority differ;
- an entry in the project's divergence register (profile `authority` section names it);
- the manifest's existing `intentional divergence` disposition on its row.

This relaxes the compatibility goal. It is not permission to leave an ordinary parity defect unfixed.

## Findings versus questions

A finding that expresses suspicion without discriminating evidence is recorded as a **question**, not a
blocker (`WORKFLOW.md` §9.2.1). The remediation owner answers it; it does not by itself move the work
package to `REMEDIATION`.
