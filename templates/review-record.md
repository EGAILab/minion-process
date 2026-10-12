# Review record

One per review event (`WORKFLOW.md` §11.2.1, §9.2, §9.2.1). Written as a file so it can be published
verbatim with its whole-file hash when the reviewer cannot post it.

```text
REVIEWER ROLE       <agent / pane>, independent of the author
REVIEWED            code: PR #<n> @ <40-hex>   docs: PR #<n> @ <40-hex>
AUTHORITY           <pinned authority identity>
SCOPE               complete | targeted (<finding ids> + touched dependencies + affected regressions)
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
