# Routing table

**Referenced by:** `WORKFLOW.md` §11.7, §11.8; `consequence-classes.md`. **In force for a project only
when its profile says `delegation.routing: true`**, which the project sets after its Owner has extended
the standing delegation to these routes. For Minion-Agent that is `minion-agent#75` **Amendment 2**
(Owner, 2026-10-12, issuecomment-6115715796), whose text the table below reproduces; the amendment is
the authority, this file is the kit's copy.

Routing answers "how should I proceed" mechanically. The coordinator takes the route and records it,
with its rule ID, in the coordination record (`history.routes: [{rule, at, reason}]`), instead of
asking. The Owner decides semantics, scope and risk.

## Delegated routes

| Rule | Situation | Route (no Owner question) |
|---|---|---|
| `RT-1` | a targeted closure on an agreed checkpoint returns new findings, or the same finding survives | one fix pass per round; the §11.8.10 invalidation rule fires on the second failure of the same material finding |
| `RT-2` | a semantically independent work package is idle while the other agent works | progress it, recording the dependency edges (§11.15) |
| `RT-3` | the reviewer loses the environment the review needs | `HANDOFF_BLOCKED`: record the block, route the access question to the Owner, re-dispatch the **unchanged** candidate when access is confirmed (§11.11) |
| `RT-4` | a **mechanical** work package has had two consecutive rounds without new discriminating evidence | file one Owner risk question with the default the process would otherwise take, and continue on that default unless the Owner answers otherwise within the round |
| `RT-5` | a finding matches a consequence predicate on a mechanical work package | the class upgrades to governing with the finding ID recorded; no question is asked. An upgrade only adds review; a downgrade is Owner-only (item 11) |

## Convergence trigger: notify and proceed

| Rule | Situation | Route |
|---|---|---|
| `RT-6` | a convergence trigger fires (A, B or C of §11.8, or the governing work-package trigger check) | record the counters that fired it and **notify the Owner** with the default route to be taken (enter `CONTRACT_CONVERGENCE`, or state why a single targeted fix closes the surface); proceed on that default unless the Owner objects within the round; record the notification in the coordination record. **This is not a silent route.** |

## Owner-only (not routed)

The Owner-only list of the standing delegation stays open-ended. Amendment 2 adds:

11. a consequence-class downgrade (governing → mechanical) of a work package;
12. creation of a remote: a new repository, a new remote, or a new default branch, in any organization;
13. acceptance of a risk the process would otherwise block on (RT-4's question when the Owner does not
    accept the default);
14. amending the delegation itself, including these routes.

Each Owner question is filed with its options packet and the default the process would otherwise take,
so the Owner can answer "default" in one word. Closing the list is revisited after P2 and P3, using the
per-work-package metric "Owner questions, split into routing vs semantic vs risk" (§14.6).

## Unchanged

Routing never bypasses implementer-reviewer separation, exact-SHA approval, negative controls,
convergence checkpoints, the final complete review, default-branch verification or the
coordination-state round-trip. A project whose profile has `delegation.routing: false` asks as before.
