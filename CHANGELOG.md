# Changelog

All notable changes to the kit. A consuming project pins one version in its `profile.yaml`.

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
