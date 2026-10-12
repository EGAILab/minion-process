# Coordination issue

One per active work package (`WORKFLOW.md` §11.1; shape in `coordination-state.md` §13). The fenced
block is the current control state and is changed only through `minion-process apply`. Prose below it
is context; comments are history.

````markdown
```yaml
workflow:
  schema_version: 2
  work_package: <WP id>
  title: '<title>'
  status: SCOPING
  requirements: [<requirement ids>]          # [] for a process-only or scoping-only WP
  current_candidate: {}                      # code: {pr, sha, base}  docs: {pr, sha, base}
  dependencies: {}                           # <WP>: {issue, relation: blocked_by|independent_of|shares_artifact}
  open_findings: []
  provisionally_closed: []
  governance_source: null                    # {standing_delegation|artifact, decision, scope} when a governed choice is in force
  deferred_trigger: null
  quarantine:
    derived_from_quarantined_artifact: false
  next_owner: <agent>
  next_action: '<one concrete action>'
  updated_by: <agent>
  updated_reason: '<one line>'
  history:
    assurance_index: <assurance record or comment link>
```

**<WP id>** -- <one paragraph: semantic surface, scope and exclusions, authority inputs>.

**Route:** <semantic | delta | process | scoping | status>; <complete-review hand-offs and the gates they need>.
````

Budget: under 8,000 characters. History-shaped keys draw a warning from `validate`.
