# Consequence classes and work-package kinds

**Referenced by:** `WORKFLOW.md` §4.3, §11.4, §11.7, §11.8; `coordination-state.md` §14; `routing.md`.
**Source:** the Minion-Agent retrospective record §6.2–§6.3 (`docs/origin.md`), adopted by the Owner on
2026-10-11 as decision 2 ("adopt as revised", `minion-agent#205`). Enforced by `minion-process validate`
and the `apply` guard from kit 0.2.0.

A work package carries a **kind** (what it is) and a **consequence class** (what it can do). The kind
names the shape of the work; the class, not the kind, selects the route. `requirements: []` describes
scope, not consequence: process tooling has decided authority, acceptance and destructive execution
(`lessons/PROC-KIT-ROUTE-BY-CONSEQUENCE.md`).

## Consequence predicates

A change is **governing** if it, or the tooling it changes, can do any of:

| Id | Predicate |
|---|---|
| `CP-1` containment | write, rename, delete or change permissions on paths computed at runtime |
| `CP-2` acceptance | decide or record acceptance, closure, merge, certification or quarantine |
| `CP-3` transitions | change which transitions are legal or who may make them |
| `CP-4` authority | select, verify or substitute an authority artifact, pin or lockfile |
| `CP-5` execution | execute or launch gates, containers, probes or the other agent |
| `CP-6` evidence interpretation | interpret evidence: comparators, control selection, "fired/unfired" detection, counting of rounds or findings |

Everything else is **mechanical** (`CP-0`, no predicate applies): prose, templates, rendering,
read-only reports, registry syncs the tool validates, scoping artifacts.

## Kinds and routes

| Kind | Examples | Consequence | Route | Convergence | Feasibility matrix | Final complete review |
|---|---|---|---|---|---|---|
| `semantic` | a layer WP owning product requirements | governing by definition | full §11.4 | yes (§11.8) | mandatory when high-risk | yes |
| `delta` | post-certification delta on a certified layer | governing by definition | contract delta → implementation → targeted closure → closure | yes, scoped to the delta | mandatory; rows measured against the pinned authority | yes |
| `process` | kit, tool or workflow change | governing when any predicate holds | the full route; challenge and convergence available; §11.8.8 final review of the changed candidate | yes | no | yes |
| `process` | templates, prose, renders, records | mechanical | draft → independent review → remediation → targeted closure → final review of the changed candidate → CLOSED (`coordination-state.md` §10.2) | no; a trigger A/B/C firing upgrades the class | no | yes |
| `scoping` | read-only scoping | mechanical | `SCOPING → CLOSED` on the approved artifact (§10.3) | no | no | the approval is the review |
| `status` | registry or status sync | mechanical | the §10.2 route; once `registry validate` exists (P3) the tool's consistency check stands in for review | no | no | none when tool-checked |

## Who classifies

- **Intake.** The coordinator records the kind and the class with the predicate it applied, in the
  state block, before the WP leaves `SCOPING` (the `apply` guard refuses otherwise):

  ```yaml
  kind: process
  consequence: {class: mechanical, rule: CP-0}
  ```

- **A pause before intake keeps intake pending.** A new WP that must stop for the Owner or wait for a
  trigger before it can be classified records `classification_pending: true` when it leaves `SCOPING`;
  the `apply` guard refuses its first working-state entry until `kind` and `consequence` are recorded.
- **Classification is sticky.** Once recorded, `kind` and `consequence` are never removed or nulled.
  Lowering the class by deleting it and re-adding a lighter one is refused as a downgrade.
- **Confirmation.** The first independent review confirms or corrects the class as a required line of
  its record (`templates/review-record.md` `CLASS CONFIRMATION`); the coordinator records `confirmed_by`.
- **Upgrade is automatic and recorded.** Any finding whose subject matches a predicate (a containment
  escape, an acceptance written on a non-approval, a substituted pin, a vacuous comparator) sets the
  class to governing with the finding ID as the rule and in `upgraded_by`. The tool refuses a lighter
  route from then on. Nobody asks the Owner whether to "convert" the WP (`routing.md` RT-5).
- **Downgrade is Owner-only** (`minion-agent#75` Amendment 2, item 11): reviewer agreement plus an Owner
  risk decision, recorded as `consequence.downgrade: {owner_decision, reviewer}` with a
  `governance_source`. Never the coordinator alone.

## Stage skipping (measured)

A stage may be skipped only when all of the following hold and are recorded in the state block:

```yaml
skipped:
  - {stage: IMPLEMENTATION_REVIEW, rule: SK-1, measured_rows: [F1.-0, F1.inf], reviewer: Codex}
```

- the feasibility rows the stage would have examined are **measured against the pinned authority** on
  every platform in scope, not inferred from a parent WP's rows;
- the reviewer consents to the skip in a review record before the stage is passed;
- the skipped stage is never the final complete review, and never a stage on a governing change.

The exact-SHA and negative-control rules are unchanged. Why the rule is this narrow: the size of a delta
does not predict its hidden dimensions (`lessons/PROC-KIT-ROUTE-BY-CONSEQUENCE.md`, L12-D007).

## The signal

The round count is not the failure signal. The signal is a **round that produces no new discriminating
evidence**: a review that rejects without a new witness, a new finding or a new matrix row. Two such
rounds on a candidate are the cue to check the §11.8 triggers (governing, `routing.md` RT-6) or to put
a risk question to the Owner with the default stated (mechanical, RT-4). `WORKFLOW.md` §14.6 measures
this instead of rounds.
