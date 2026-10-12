# Changelog

All notable changes to the kit. A consuming project pins one version in its `profile.yaml`.

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
