# Minion-Process — Gate tiers (G0–G3)

**Kit file.** Seeded from `minion-agent-docs` at `dd9fd15`, text preserved. The examples name Minion-Agent tools (pytest, cargo, the pinned ICU); a profile's `gates` section names the project's own.
**Referenced by:** `WORKFLOW.md` §13.1.
**Purpose:** match the verification required at each workflow stage to that stage's actual blast radius. A three-line witness correction should not re-run a 2,000+ test release gate unless there is a concrete reason. A certification must never skip one.

## 1. Tiers

Each tier includes everything below it.

### G0 — development

- The focused tests for the directly changed code and its direct callers.
- Syntax, lint and type checks of the changed files (`ruff`/`mypy` on changed Python files; `cargo check` / `clippy` on the affected crate target).
- Any new or changed witness executed.

### G1 — finding closure

G0, plus:
- **the affected semantic surface:** every test module owning the touched requirement IDs;
- **discriminating witnesses** for each closed finding;
- **realistic negative controls** for each executable finding (`agent-workflow.md` §11.8.7.1): known-bad → FAIL, candidate → PASS;
- **directly dependent regressions:** previously closed findings on the same root-cause surface, and high-risk regressions the fix touches.

### G2 — integration

G1, plus:
- the canonical scenarios for every requirement and dependency touched (`conformance/**` suites of the affected families, through real seams);
- cross-layer regressions for lower-layer seams the change consumes or extends;
- cross-language affected gates where a shared artifact changed: the shared schema/manifest validation and the other language's canonical runner for the touched scenarios, run by that language's owner at its next pass. **Python never runs as Rust's oracle, nor Rust as Python's.**

### G3 — certification evidence

G2, plus:
- the **full** language suite;
- the **full** applicable conformance for that language;
- manifest and shared-schema validation;
- the coverage requirement (currently 100% of the certified Python surface);
- formatting on changed files; strict type checks (`mypy` strict, `clippy -D warnings`, rustdoc where applicable);
- the pinned-toolchain environment (e.g. the pinned ICU build).

G3 is **evidence the candidate's author runs and reports** at the exact candidate SHA. It is not itself a review. The independent complete exact-SHA review (`agent-workflow.md` §11.3, §11.8.8, §13) is the separate act of the stage that **consumes** this evidence; the reviewer re-runs what it needs. Certification requires both: G3 evidence at the exact candidate **and** an independent complete review of that candidate. Entering a first complete review therefore needs G3 evidence, never a prior review.

## 2. Minimum tier per workflow stage

There are two kinds of hand-off to an independent reviewer, and this table is authoritative for both:
- **Complete-review hand-offs.** These are the first `IMPLEMENTATION_REVIEW`, `FINAL_CONTRACT_REVIEW` and the Rust closure review (`CLOSURE_REVIEW`). They need G3 evidence.
- **Targeted finding-closure hand-offs.** These are ordinary remediation returned for targeted closure (§11.4) and targeted convergence closure (§11.8.7). They need only the tier the table gives them, and G3 is not required. G3 is required again at the next complete-review hand-off.

| Stage | Minimum tier | Notes |
|---|---|---|
| Development commits inside an owner's pass | G0 | |
| Contract / convergence **checkpoint** evidence | G1 characterization | The pinned-Pi authority harnesses and the feasibility matrix; production suites are not required |
| Ordinary `REMEDIATION` handed back for targeted closure | G0 + G1 | |
| Targeted convergence closure (§11.8.7) | G1 + the relevant G2 | G2 for the scenarios/dependencies the fix touched |
| `IMPLEMENTATION_REVIEW` hand-off (first, complete) | G3 evidence | The first complete review sees a certification-grade candidate |
| `FINAL_CONTRACT_REVIEW` hand-off (§11.8.8, complete) | G3 evidence | |
| Merge of an approved candidate | G3 evidence already recorded at the exact approved SHA, plus the independent complete review's approval | Plus the post-merge containment check (§12) |
| Post-merge default branch | G3 re-run **only** if the merge was not a fast-forward of the approved tree (other commits landed in between) | The delta files must be identical to the approved head |
| Rust closure-review hand-off (complete) | G3 evidence (Rust) | A targeted Rust finding-closure hand-off follows the targeted rows above |
| Documentary / status-only change | G0 + manifest/schema validation | No semantic surface |

## 3. Escalation and reporting

- **Escalating above the minimum is always allowed.** When a *required* escalation happens (the change's blast radius exceeds the stage's tier), record one line in the handoff:

  ```text
  GATE: G2 (escalated from G1) — reason: fix changed the shared TOOL-026 preprocessing used by read/ls
  ```

- **Every handoff reports the tier actually run** and its fresh counts (`agent-workflow.md` §15). Do not quote counts from an earlier tier or an earlier SHA.
- **A reviewer may require a higher tier** for closure by recording a concrete blast-radius reason. "The SHA changed" alone is not a reason (§11.8.7).
- **De-escalation below the stage minimum is not permitted.** A G3 stage cannot be satisfied by G1 plus an argument.

## 4. What does not change

- Independent review, exact-SHA binding and negative controls are unchanged.
- The final complete review still requires G3 evidence at the exact candidate.
- Certification (§13) still requires every G3 item and an independent complete review.

Tiers only remove the requirement to run release-level gates at intermediate stages where they add no discriminating value.
