# Review record

One per review event (`WORKFLOW.md` §11.2.1, §9.2, §9.2.1). Written as a file so it can be published
verbatim with its whole-file hash when the reviewer cannot post it.

**Structured header (kit 0.3.0, record §6.6).** The record starts with one fenced YAML block whose only
top-level key is `review`. The tool reads it (`minion-process review-check <file>` validates it;
`convergence counters` and `metrics` collect the headers published on the coordination issue and the
candidate PRs) and never writes one. The prose below the header stays as before.

````markdown
```yaml
review:
  schema_version: 1
  wp: <work package id>
  type: CONTRACT_REVIEW | IMPLEMENTATION_REVIEW | TARGETED_CLOSURE | CHECKPOINT | FINAL_REVIEW | CLOSURE_REVIEW | PROCESS_REVIEW
  complete: true                    # complete review of the candidate; false for a targeted closure
  reviewer: <agent>                 # must differ from author
  author: <agent>
  candidate: {code: <40-hex>, docs: <40-hex>}   # at least one side; any side name the project uses
  gate_tier_verified: G3            # G0 | G1 | G2 | G3 | none -- what the reviewer re-ran
  class_confirmation: {kind: <kind>, class: <governing | mechanical>, rule: <CP-n>, outcome: CONFIRMED | CORRECTED}
  verdict: APPROVED | CHANGES_REQUESTED | HANDOFF_BLOCKED
  new_evidence: true                # did this round add a witness, a finding or a matrix row (the no-new-evidence signal)
  findings:
    - {id: <FINDING-ID>, class: <taxonomy class or alias>, blocking: true, surface: <root-cause surface>, witness: <path>}
  closed:
    - {id: <FINDING-ID>, negative_control: <known-bad method>}            # or
    - {id: <FINDING-ID>, negative_control: NOT_APPLICABLE, reason: documentary/traceability-only}
```
````

Publishing the same record verbatim on the coordination issue and on each candidate PR is normal
transport: identical headers are one review event and the tool counts them once.

Rules the tool enforces: `reviewer` differs from `author`; `APPROVED` carries no blocking finding;
`HANDOFF_BLOCKED` carries no findings; every closed finding records its negative control, or
`NOT_APPLICABLE` with the reason; `surface` names the root-cause surface so successor findings (trigger
B) can be counted; unknown keys are errors. `CHANGES_REQUESTED` with `new_evidence: false` is a round
without new discriminating evidence (`consequence-classes.md`, "The signal").

```text
REVIEWER ROLE       <agent / pane>, independent of the author
REVIEWED            code: PR #<n> @ <40-hex>   docs: PR #<n> @ <40-hex>
AUTHORITY           <pinned authority identity>
SCOPE               complete | targeted (<finding ids> + touched dependencies + affected regressions)
CLASS CONFIRMATION  <kind> / <governing | mechanical>, <CP-n> CONFIRMED | CORRECTED to <class>, <rule> -- required line
                    of the first independent review (consequence-classes.md "Who classifies")
VERDICT             APPROVED | CHANGES REQUESTED | HANDOFF_BLOCKED (<missing capability>)
NEXT TRANSITION     <state> -> <state>, next_owner <agent>
```

Per finding:

```text
<FINDING ID>        <taxonomy class>   blocking | non-blocking | question
rule believed violated
exact authoritative source (content-addressed: commit / hash / version + path + symbol)
minimal reproducer
candidate observation
expected observation
why existing tests/evidence do not distinguish it
suggested discriminating witness (convertible into a regression test)
```

Per closed finding (targeted closure):

```text
<FINDING ID>        PROVISIONALLY CLOSED @ <candidate SHA>
negative control    method / known-bad mutation or SHA / expected failure / observed failure
candidate           observed pass
                    or NEGATIVE_CONTROL NOT_APPLICABLE -- documentary/traceability-only, reason
```

Footer:

```text
sha256 (this file)  <64-hex>
```

A finding without a verified source record is not filed. A finding without discriminating evidence is
recorded as a question.
