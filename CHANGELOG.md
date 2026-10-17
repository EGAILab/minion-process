# Changelog

All notable changes to the kit. A consuming project pins one version in its `profile.yaml`.

## 0.4.3 - Lessons from the first days of operation (unreleased)

Normative kit change by the kit owner under the role split (`EGAILab/minion-agent#231`
issuecomment-6228553990): process feedback from operating M-Remote and the gru registry on 2026-10-17 and
2026-10-18.

- `orchestrator.md`:
  - OR-5: `gru` sends any Codex message over 500 characters as a pointer, down from 900. In the
    journal, every direct prompt up to 608 characters was submitted (17 of 17). Above that, 8 of 20 were not
    confirmed (UNKNOWN), the shortest at 634. Every pointer was submitted (7 of 7);
  - OR-7: when a window needs the Owner present, the Owner gives a start time. The window opens only
    after the app is on screen and the Owner has confirmed they are there; otherwise the run ends cleanly
    (D5 attempts 2 and 3);
  - OR-8, how to ask the Owner:
    - name herdr spaces and tabs, not pane ids, and give the exact action;
    - never ask the Owner to carry text to an agent bound in `gru`;
    - dim suggestion text is not an answer;
    - a wait on the Owner has a 30-minute deadline;
  - OR-10, session identity: before binding, check the session id against the tool's own session record.
    `herdr pane report-agent-session` corrects herdr's record without a restart. This comes from the
    2026-10-17 misbind, where herdr gave Review-Codex's session to the Rust-Codex pane;
  - OR-11, one route between agents: from ACTIVATE on, every message between agents goes through `gru`,
    and a project's own scripts that prompt or send keys to another pane are retired.
- Witness rows W15 (session identity) and W16 (one route).
- `minion_process/releases/0.4.3.yaml`: `ORCH-SESSION-ID`, `ORCH-ONE-ROUTE` and the profile pin.
- Release: package and shipped profile versions raised to 0.4.3.

## 0.4.2 - Orchestrator onboarding pack (unreleased)

Normative kit change, ordered by the Owner on 2026-10-17 (`EGAILab/minion-agent#231`
issuecomment-6228553990): the full Orchestrator-managed workflow, and every Minion project onboarded.

- `orchestrator.md`:
  - OR-1, who does what: the Orchestrator owns all job management, and Process-CC maintains the
    workflow;
  - OR-2, the implementer merges after an independent exact-SHA APPROVE;
  - OR-3, review depth: one round, blocking findings only, plus one re-review;
  - OR-4, GitHub access: the Orchestrator posts the authenticated GitHub check, and the Owner decides
    the token's scope;
  - OR-5, the onboarding pack and order, with M-Remote's lessons;
  - OR-6, unchanged invariants;
  - OR-7, consent windows: these run under the Owner's standing consent within the project's
    contract. The Orchestrator sets the parameters, records the owner-window record, and gives the
    Owner a heads-up notice, not a question (issuecomment-6228683601);
  - OR-8, Orchestrator autonomy: it decides operational matters itself and records the basis. It
    escalates only for physical Owner-only actions (batched), changes outside the approved plan, or
    Owner-typed codes;
  - OR-9, the read-only brief-file exception for `gru` pointers, with a sha256 check; this resolves
    GRU19.
- One-line pointers to it in `routing.md`, `roles/README.md`, `WORKFLOW.md` §11.6 and §11.7, and
  `onboarding.md`.
- `minion_process/bootstrap/orchestrator/`, shipped as package data, forced LF (`.gitattributes`):
  - templates made from M-Remote's reviewed files (`minion-remote-docs` `4be18ceb`): the Claude
    outside-root guard and its offline witness, `settings.json`, and the Codex Orchestrator rules;
  - new: `codex-launch.ps1`, the entry routing section, the witness rows W0 to W14,
    `owner-acl.ps1` (with `-Check`) and `values.m-remote.yaml`;
  - review 1 fixes (KIT-042-R001 to R006):
    - every value that reaches executable syntax is refused if it holds a quote, `$`, a command
      separator, a redirection or a control character, and PowerShell literals are also escaped;
    - `owner-acl.ps1` refuses a link anywhere in the root's or a target's path, has no
      outside-root option, and counts only a full-scope deny (propagation None);
    - the guard also protects `.claude/skills` and `.minion` (W5, O13 to O15). Its bytes therefore
      differ from M-Remote's installed guard, which M-Remote upgrades when it adopts 0.4.2;
    - the entry rules carry the brief-file exception (OR-9);
    - ruff is clean.
- `minion-process orch-render --root R --values V --out D`: renders the pack into a new folder inside
  the root. Every placeholder is checked, and nothing is overwritten.
- `kit-onboard` skill: Owner steps F (install), G (`owner-acl.ps1`) and H (Codex trust, app-server stop,
  relaunch), mapped from the new manifest steps.
- `minion_process/releases/0.4.2.yaml`: `ORCH-*` steps and the profile pin.
- Release: package and shipped profile versions raised to 0.4.2.

## 0.4.1 - 0.3.2 carried forward (unreleased)

Governing (CP-3) kit change: the 0.3.2 closure route (`EGAILab/minion-process#12`, released from
`release/0.3.x` as `v0.3.2`, `c7cd3b61`) carried into the 0.4 line, so a 0.4.x consumer has it too.

- Every 0.3.2 change below, cherry-picked onto 0.4.0 unchanged; only the version strings differ.
- `minion_process/releases/0.4.1.yaml`: its one adoption step is the profile pin.
- Release: package and shipped profile versions raised to 0.4.1.

## 0.4.0 - project scope by default; onboarding tools (2026-10-16)

Normative kit change, ordered by the Owner on 2026-10-16 (`EGAILab/minion-agent#231`).

- `project-scope.md`: PS-1 agents read and execute in the tools' user-level folders but never write
  them; PS-2 the project-scope location of instructions, settings, hooks, skills, auto-memory
  (`autoMemoryDirectory` to `<root>/.claude/memory/`) and temp for Claude Code and Codex; PS-3 temp,
  caches and build outputs under `<root>/.tmp/`; PS-4 what stays user-level and who changes it; PS-5 the
  Codex sandbox on the launch line; PS-6 full isolation only by Owner decision; PS-7 enforcement; an
  adoption checklist.
- `WORKFLOW.md` §9.8: one paragraph and the link.
- `lessons/PROJECT-SCOPE-2026-10-16.md`: the Owner's words and the audit that led to the rule.
- Onboarding, ordered by the Owner on 2026-10-16 (`onboarding.md`):
  - `minion_process/releases/<version>.yaml` release manifests, one per release from 0.4.0;
  - `minion-process onboard --root R --from A --to B [--markdown]`, a read-only checklist of every
    release's adoption steps between two versions;
  - `minion-process launch-plan` and `session-record`, the session (re)launch plan from
    `<root>/.minion/sessions.yaml`;
  - `bootstrap/install.ps1`, which installs a release inside the project;
  - `relaunch.ps1`, shipped in the package, which relaunches a session with the PS-3 environment and
    the PS-5 Codex line and records its session id for the next relaunch;
  - the `kit-onboard` agent skill, installed by `install.ps1` into `.claude/skills/` and
    `.agents/skills/`: it runs the checklist, does the agent-side steps, prepares every Owner step as
    exact commands and records the result on the coordination issue.
  - `.codex/rules/kit-sentinel.rules`, installed by `install.ps1` as its own file: it forbids the fake
    command `minion-rules-sentinel`, so a refusal in the project's normal Codex session proves that
    session loads the project's rules (`CODEX-RULES`). The inventory covers `~/.codex` and every
    effective `CODEX_HOME` (session, sessions.yaml, user and machine environment). Migrated rules go into a new
    `migrated-<date>.rules`, and no existing rules file is overwritten.
- `project-scope.md` PS-2: `.claude/skills/` is a control file too, since a skill changes how an agent works.
- Release: package and shipped profile versions raised to 0.4.0.

## 0.3.2 - closure route for a clean first review of a process or status WP (2026-10-16, `release/0.3.x`)

Governing (CP-3) kit change, a state-machine routing fix: `EGAILab/minion-process#12`, filed by the
Minion-Agent consumer on Owner decision (`minion-agent#222` issuecomment-6209854474). The Owner ordered it
released as 0.3.2 from `v0.3.1`, so a 0.3.1 consumer can adopt it without 0.4.0. It is carried forward
into 0.4.1.

- `coordination-state.md` §10.2a and the transition table: a guarded `IMPLEMENTATION_REVIEW -> CLOSED`
  for an explicit `process`/`status` WP with `requirements: []` before and after, no open or
  provisionally closed finding (top-level or `convergence`) before or after, the latest published review
  event a complete `APPROVED` `IMPLEMENTATION_REVIEW`/`PROCESS_REVIEW` of exactly the recorded candidate
  SHAs (read from the published review headers, never a hand-recorded marker; a conflicting, unorderable,
  unread or invalid header refuses), read for the current `work_package` from the issue and every
  candidate PR the issue's edit history has recorded (an identity change in that history refuses), no
  change in the closing patch to `work_package` or any candidate field but a newly recorded
  `merged_sha`, every candidate PR merged with the approved head at its recorded
  `merged_sha`, and each merge reachable from the default branch. The §10.2 historical-illegal list now
  names `IMPLEMENTATION_REVIEW -> CLOSED` as illegal for any WP that owns product scope.
- `WORKFLOW.md` §11.4 (a clean process/status WP closes directly, never entering
  `FINAL_CONTRACT_REVIEW` with an unchanged candidate) and §12.6 (the new route's rejections).
- `minion_process`: the transition table, `ops._first_review_closure` in the `commit_state` guard chain
  (so `apply` and `close` both enforce it), and `ops.published_reviews`, shared with `convergence` and
  `metrics`.
  The `FINAL_CONTRACT_REVIEW -> CLOSED` and `CLOSURE_REVIEW -> CLOSED` guards are unchanged.
- `tests/test_first_review_closure.py`: a refusal witness with zero writes for every guard clause, and
  the review-1 regressions (KIT-032-R001 approval-source binding through the closing patch and the edit
  history, R002 findings in every admitted location), each with its unchanged-context control.
- The edit-history read fails closed (review 2): `GitHub.issue_revisions` keeps an edit whose body
  GitHub does not return as `None` instead of dropping it (and `apply --repair` refuses such a
  revision); the closure route refuses a null body or a state-bearing revision that does not parse, and
  skips only a revision that positively has no state block.
- Release: package and shipped profile versions raised to 0.3.2.

## 0.3.1 - lesson: shared build caches and mtime freshness (unreleased)

Mechanical (CP-0) kit change from `EGAILab/minion-process#4`, proposed by the Minion-Agent consumer.

- `lessons/SHARED-BUILD-CACHE-FRESHNESS-2026-10-13.md`: a shared Cargo target executed another checkout's
  and a mutation control's binaries as a gate (`minion-agent#215`); the mechanism (path-independent
  artifact hashes plus mtime freshness) and the rule adopted in `minion-agent#209`.
- `WORKFLOW.md` §9.8: one paragraph: fresh sources before every gate, a separate cache for mutation
  controls, one writer per shared cache with the reviewer in a reviewer-only cache, provenance by embedded
  paths and build times. The replay recipe is recorded in the lesson for the consumer's gate suite.

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
  failure of a recognized claim is `unparsable` and collection continues; a comment whose publication
  metadata the remote does not return is reported as unorderable and makes the statement and metrics
  INCOMPLETE, never a negative result.
  Agreed checkpoint revision 7 (`R003`): the publication domain is the CommonMark parser's block
  structure (`markdown-it-py`, `commonmark` preset, no plugins): a top-level fenced code block whose raw
  info string starts with `yaml`/`yml`; quotations, list items, HTML blocks, outer code blocks, indented
  code and inline code are not publications; content is handed to YAML exactly as the parser yields it
  (the transport replaces U+0000 by U+FFFD). The parser's nesting cutoff is made unreachable so no input
  is silently truncated; a parser failure (including the interpreter's recursion limit) makes the whole
  comment `unread`, reported by id, and the statement and metrics INCOMPLETE.
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
