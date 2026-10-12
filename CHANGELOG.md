# Changelog

All notable changes to the kit. A consuming project pins one version in its `profile.yaml`.

## 0.3.0 — P3a: structured review header, convergence counters, metrics, composite verbs (2026-10-12)

Record §6.6; coordination `minion-agent#213` (PROC-KIT-P3, process / governing CP-6).

- `templates/review-record.md`: the fenced `review:` header (schema version 1) every review record now
  opens with; `minion-process review-check <file>` validates it offline (`minion_process/review.py`):
  reviewer ≠ author, no blocking finding under `APPROVED`, no findings under `HANDOFF_BLOCKED`, a
  negative control or `NOT_APPLICABLE` with reason for every closed finding, `surface` for successor
  counting, `new_evidence` for the no-new-evidence signal; fail-closed shapes.
- `minion-process convergence counters <issue>`: reads the headers published on the coordination issue
  and the candidate PRs, computes triggers A (a blocking finding in two or more reviews), B (two
  distinct blocking findings on one surface) and C (three rejected complete reviews) plus the rounds
  without new evidence, and prints the mandatory §11.8 statement. Invalid headers are counted, never
  silently dropped.
- `minion-process metrics <issue> [--out file]`: the §14.6 metrics available from the state block and
  the headers (review events, complete vs targeted, approvals, rounds without new evidence, findings by
  class, closures with and without negative control, gate tiers verified, routes taken, Owner questions
  routed, triggers).
- Composite verbs (`minion_process/composite.py`): `handoff <issue> --to --action [--status] [--sha
  side=sha]` sets owner, action and heads in one checked commit and refuses with zero writes when the
  intended candidate would be `HANDOFF_BLOCKED`; `close <issue> --comment-file` verifies every
  recorded candidate PR is merged at its recorded head, records the merge commits, moves to `CLOSED`
  through every closure guard, then closes the issue. Both are built only from the existing primitives.
- `GitHub.issue_comments` (paginated) and `GitHub.close_issue`.
- Review 1 (`PROC-KIT-P3-R001`–`R003`): identical headers published on the issue and the candidate PRs
  are one review event (transport copies are counted and ignored, never counted as reviews);
  `handoff` checks the issue is OPEN and the target status permits a hand-off before any write; every
  fenced YAML block whose first key is `review` is a review header however its value is written, unknown
  keys of any YAML type are diagnostics, and a boolean `schema_version` is rejected.
- Convergence episode `CE-PROC-P3A-01` (`R001`/`R003` refined twice; checkpoint agreed on revision 4):
  header `schema_version: 2` with required `round`; review-event identity `(wp, reviewer, round)`,
  mirrors by parsed-value equality, conflicts reported and excluded; chronology from the remote's
  comment metadata with the total key `(created_at, round, comment id, fence ordinal)` and multi-header
  comments reported; discovery of review claims by the YAML scanner's token prefix up to the first key
  scalar, with one disposition per claim in priority `unsupported publication form` (root or key
  properties, explicit key) > `unparsable` > `invalid shape` > valid; the statement and the metrics show
  every excluded header. `GitHub.issue_comments` returns `{id, created_at, body}`.
  Targeted closure 1 (`R001`/`R003` refined, `R004`): conflicts name the differing fields; any loader
  failure of a recognized claim is `unparsable` and collection continues; review fences are CommonMark
  fenced code blocks (content of an outer block is literal, openers are line-level); a comment whose
  publication metadata the remote does not return is reported as unorderable and makes the statement
  and metrics INCOMPLETE, never a negative result.
- Not yet: `dispatch`, `session start`, `cleanup`, launchers, fault-fired rule, replay suite (0.4.0).

## 0.2.0 — P2: kinds, consequence classes, routing (2026-10-12)

Owner decisions 2 and 3 (`minion-agent#205`); `minion-agent#75` Amendment 2 (Owner, 2026-10-12).
Coordination `minion-agent#212` (PROC-KIT-P2).

- `consequence-classes.md`: work-package kinds, the six consequence predicates `CP-1`–`CP-6`, who
  classifies (intake, reviewer confirmation, automatic recorded upgrade, Owner-only downgrade), the
  measured stage-skip rule and the no-new-evidence signal.
- `routing.md`: delegated routes `RT-1`–`RT-6` with the text of `#75` Amendment 2; `RT-6` is
  notify-and-proceed; the Owner-only additions 11–14. In force per profile `delegation.routing`.
- `coordination-state.md` §14: `kind`, `consequence`, `skipped`, `history.routes` shapes and the
  transition rules. `minion-process validate` checks the shapes (optional fields; a v2 state without
  them warns); the `apply` guard requires classification at intake, fixes the kind after intake, makes
  a downgrade Owner-only, and routes closure by kind.
- `WORKFLOW.md`: new §4.3; §11.4 mechanical route; §11.7 routing by rule; §11.8 trigger notification.
- `templates/coordination-issue.md` carries `kind` and `consequence`.
- `lessons/PROC-KIT-ROUTE-BY-CONSEQUENCE.md` (record §6.2–§6.3, verbatim).
- `profiles/minion-agent.profile.yaml`: `delegation.routing: true` (Amendment 2 posted).
- Review 1 (`PROC-KIT-P2-R001`–`R003`): classification is sticky (no removal or null; every effective
  lowering is the Owner-only downgrade); supplied `null` in the new fields is a diagnostic, not absence;
  `classification_pending` keeps intake pending across a pause; a skip needs an explicit `mechanical`
  class; `RT-1` wording aligned with Amendment 2; `CLASS CONFIRMATION` line in the review-record template.
  Re-review (`R003` refined): `schema_version` never rolls back in an ordinary `apply`, and the intake
  obligation is computed from the higher of the current and intended versions.
- Not yet: `convergence counters`, structured review-record header, metrics, launchers, replay (P3);
  state-file backend and profile-driven repositories (P3/P4).

## 0.1.0 — P1 seed (2026-10-12)

Seeded from `EGAILab/minion-agent-docs` at `dd9fd15188d89597fd09a538c2652788604d0d92`
(`process/**`, `process/tools/`). Owner decisions on `EGAILab/minion-agent#205`; coordination
`EGAILab/minion-agent#211` (PROC-KIT-P1).

- `WORKFLOW.md`: the normative core of `agent-workflow.md`, made project-neutral. The semantic
  authority, repositories, agents, panes, taxonomy aliases and gate commands come from the profile. The
  text of every rule is preserved; incident narratives moved verbatim to `lessons/` and are linked from
  the rule they support.
- `coordination-state.md`, `gate-tiers.md`, `hazards/hazard-families.md`, `authority-dependencies.md`,
  `requirement-id-convention.md`, `templates/cross-language-feasibility-matrix.md`: seeded with their
  text preserved; headers point at the kit.
- `finding-taxonomy.md`: the five generic classes and the alias mechanism.
- `templates/`: hand-off, review record, convergence record, closure record and coordination issue, each
  the field list the workflow already required.
- `roles/`: generic role texts for coordinator, shared-contract owner, implementer and reviewer.
- `profiles/profile.schema.json`, `profiles/example.profile.yaml`, `profiles/minion-agent.profile.yaml`.
  The profile declares the project's canonical behavior families and support infrastructure
  (`conformance`), which `WORKFLOW.md` §9 refers to.
- `seed-history/minion-agent-specifics.md`: the Minion-Agent-specific sentences that became profile
  values, verbatim, with the field each maps to (review 1, `PROC-KIT-P1-R003`).
- `minion_process profile validate <path>`: validates a profile against the schema's rules offline;
  total on malformed values (`PROC-KIT-P1-R001`); the schema expresses role coverage and independence
  as constraints and both validators are tested differentially (`PROC-KIT-P1-R002`). Everything else in
  the CLI is unchanged from the Minion-Agent tool.
- Not yet: the `state-file` backend, profile-driven repository names, kinds and consequence classes
  (P2), structured review-record header, metrics, composite verbs, launchers, `replay/` (P3).
