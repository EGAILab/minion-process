# Hand-off record

One per hand-off to another agent (`WORKFLOW.md` §11.2, §11.17, §12.3). Independently usable without
reading the author's implementation.

```text
WORK PACKAGE        <id> (coordination issue #<n>)
PASS TYPE           contract draft | implementation | remediation | targeted closure | convergence | closure
CANDIDATE           code: PR #<n> @ <40-hex>   docs: PR #<n> @ <40-hex>   (remote-reachable, verified)
BASE                <default branch(es)>
AUTHORITY           <pinned authority identity, e.g. source SHA / bundle digest>
REQUIREMENTS        <requirement / manifest IDs>
AUTHORITY SYMBOLS AUDITED
                    <symbols / files, with any AUTHORITY_BEHAVIOR_UNCERTAIN>
SHARED RULES        <the exact rules the receiver must verify>
CANONICAL EVIDENCE  <scenarios / tests added or changed; counts discovered dynamically>
INTENTIONAL DIVERGENCES / DEFERRED PARITY
                    <ids and their governance source, or none>
OPEN FINDINGS       <ids, or none>
GATE                <tier actually run> (escalated from <tier> -- reason: ...) fresh counts: ...
REVIEW SCOPE        <complete | targeted: findings + touched dependencies + affected regressions>
STOP CONDITION      <exactly where the receiver stops>
REPLY TO            <sender pane>; send a completion notification when done, blocked or needing a decision
```

A hand-off is not ready until every SHA above is pushed and verified reachable on GitHub. If push is
blocked, report `REMOTE_SYNC_BLOCKED` instead of this record.
