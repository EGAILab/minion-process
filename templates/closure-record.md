# Closure record

One per work package at `CLOSED` (`WORKFLOW.md` §13, §14.6, §15). Summarizes the material intermediate
evidence; every review event does not need its own merged document.

```text
WORK PACKAGE        <id> (coordination issue #<n>)
DISPOSITION         certified | deferred parity (trigger: ...) | intentional divergence (governance: ...) | process-only | scoping-only
REQUIREMENTS        <ids> with final disposition each
ACCEPTED            code: <default-branch merge SHA>   docs: <default-branch merge SHA>
AUTHORITY           <pinned identity>
REVIEWS             <reviewer, candidate SHA, verdict, record link> per event
FINDINGS            <id, class, outcome, witness, negative control> per finding
INTENTIONAL DIVERGENCES / DEFERRED PARITY
STATUS SYNC         <manifest rows / spec status lines / registry entries merged before closure>
GATES               G3 at <SHA>: fresh counts, platforms, recipe link
CROSS-LAYER IMPACT  <deltas raised on certified lower layers, or none>
```

Process metrics (§14.6), per work package:

```text
review events to contract approval
complete reviews / targeted reviews
rounds without new discriminating evidence
post-contract semantic discoveries
lower-layer deltas discovered after implementation started
Owner escalations (routing / semantic / risk)
documentary / status-only PRs
full-suite (G3) runs
findings discovered by the reusable hazard families vs ad hoc by review
```
