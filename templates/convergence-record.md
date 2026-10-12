# Convergence episode record

One per episode (`WORKFLOW.md` §11.8.1–§11.8.5). It accumulates across the episode's lifetime,
including successor findings folded in under trigger B.

```text
EPISODE             CE-<wp>-<nn>
TRIGGER             A | B | C | D, with the counted evidence (which finding survived which reviews,
                    which successors, how many rejected complete reviews)
OPEN FINDINGS
ROOT-CAUSE SURFACE
AUTHORITY SYMBOLS / TESTS AUDITED
OBSERVABLE RULES
BEHAVIOR MATRIX     (the discriminating dimensions, enumerated; mixed compositions included)
MINIMAL EXECUTABLE WITNESSES
NEGATIVE CONTROLS
CURRENT CANDIDATE FAILURES
SPEC / MANIFEST / CONFORMANCE DELTAS
IMPLEMENTATION CONSTRAINTS
OUT-OF-SCOPE / DEFERRED BEHAVIOR
```

Checkpoint, a two-party barrier:

```text
STEP 1 -- the characterization/implementation owner authors:
CONVERGENCE CHECKPOINT      PROPOSED FOR IMPLEMENTATION
OPEN FINDINGS               <ids>
ACCEPTANCE WITNESSES        <paths / probe ids / tests>
NORMATIVE DELTAS            <spec / manifest / conformance paths>
NEXT_OWNER                  <independent reviewer>

STEP 2 -- the independent reviewer reviews EXACTLY that proposal:
CHECKPOINT REVIEW           APPROVED | REJECTED, with the missing semantic dimension identified

STEP 3 -- only on APPROVED does the control record become:
CONVERGENCE CONTRACT        AGREED FOR IMPLEMENTATION
```

An agent never writes `AGREED FOR IMPLEMENTATION` itself. If the same material finding fails two
targeted closure reviews after an agreed checkpoint, implementation stops and the checkpoint returns to
characterization (§11.8.10).
