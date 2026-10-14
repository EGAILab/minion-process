# Changelog

All notable changes to the kit. A consuming project pins one version in its `profile.yaml`.

## 0.4.0 — P3b: host build queue, session start, dispatch rendering, fault-fired check (2026-10-14)

Coordination `minion-agent#223` (PROC-KIT-P3B, process / governing, `CP-1`, `CP-5`, `CP-6`). Contract
from convergence episode `CE-PROC-P3B-01`: agreed in Codex round 6, invalidated under §11.8.10 after round
8, and agreed again at checkpoint revision 15 (Codex round 16). The texts and their precedence are in
`docs/p3b/README.md`. Owner decisions: window ownership moves to a host queue (`minion-agent#209`
issuecomment-6138907446); the queue folder; 2 jobs / 16 GiB / 3 minutes (`#223`); `CONFIRM QUEUE` through
the Claude chat hook (`#223`); no cleanup class in 0.4.0 (`#223` issuecomment-6164469910).

- `minion_process/hostqueue/`:
  - **Broker:** single instance via the OS mutex. It replays the journal on every start. Clients write one
    immutable request file each.
  - **Journal:** checksummed, commit-marked, gap-free records. Every anomaly is ambiguous.
  - **Effect markers:** write-ahead, exclusive at the final name, never overwritten. Recovery reconciles
    the journal with them.
  - **Admission:** evidence drains the host; bounded bypass on resources only; exact-byte memory floor
    with start-up reservations. Launching and uncertain jobs keep their slot. Unknown-extent work blocks
    the whole host.
  - **Frozen inputs:** re-checked at launch, so any drift refuses the job. Resources are canonical paths
    with overlap. Evidence runs on a fresh worktree of the exact SHA and controls on isolated copies. A
    build gets its freshness touch under an exclusive lease, then shares the checkout.
  - **End proof:** a job object plus labelled containers; the runner drains its job before writing its
    result. Uncertain jobs hold their resources until proof or a confirmed release.
  - **Overrides:** policy set, release, quarantine and resume each need a scope-bound, one-use, expiring
    challenge confirmed by the Owner's `CONFIRM QUEUE <code>` (`hostqueue/confirm.py`, a `UserPromptSubmit`
    hook).
  - **Repair mode:** never admits. Quarantine keeps the original bytes. Placeholders hold the host for
    effects whose footprint is unknown.
  - **Registered copies:** each execution copy stays registered under its creator for good. Its lease
    is released with the creator's proven or confirmed end, to no other job, and it is never reused.
    Removal is manual; there is no cleanup class (K-46 to K-48″). No walk ever follows a link or junction.
  - **Containment:** proved before every write, rename and delete. The broker deletes and renames only
    inside its queue folder.
  - **`winos.py`:** the Windows host adapter (named mutex, process identity, job objects, memory, volume
    type, write-through rename, docker and herdr queries).
- `minion-process build broker|submit|status|wait|cancel|unretain|release|policy|repair`,
  `session start`, `faults check`, `dispatch --print` / `--mark-undelivered`.
- `minion_process/faults.py`: fault-fired accounting for feasibility matrices and control recipes.
- Profile: optional `build_queue` and per-gate `queue` (schema and validator, differential tests).
- `WORKFLOW.md` §9.8 (host build queue), §11.17 (the kit renders but never sends), §12.2 (`session start`).
- CI: a Windows job runs every gate, including the 100% coverage gate and strict mypy, because the host
  adapter is Windows only. The Linux job runs lint, the tests and a non-editable wheel install smoke check.
- Implementation review round 7 remediation:
  - **R002:** the runner records `drained` only after a successful accounting query. A spawn failure keeps
    the identity of any process it created.
  - **R003:** the effective environment is frozen and bound to leased resources: `inherit_env`, `caches`,
    `cache_env`, and a per-job temporary folder. Controls require a controls-kind target.
  - **R005:** a retry grant stands only with its readable marker.
  - **R006:** superseded. The Owner withdrew cleanup from 0.4.0 (below).
  - **R008:** challenges are bound to the boot.
  - **R009:** containment proves the root and its ancestors, and every mutation goes through `fsops`.
  - **R010:** request shapes are validated per type, and a malformed request is rejected alone.
  - **Packaging:** subpackages are included, with a wheel smoke check in CI.
- Implementation revision 3 (checkpoint revision 15 rule set, after the §11.8.10 invalidation):
  - **K-41 (R002):** process observations are three-valued. An unknown birth time stays unknown for the
    life of the identity and is never coerced to a number. An identity with an unknown birth is
    alive-or-unknown until its process id no longer exists.
  - **K-42 (R003):** launcher paths reach a tool only through declared slots
    (`{slot: <template>, access: read|write}`). Every other argv element and env value is a literal with
    no separator, drive, `..` or control character. Writable-location variables are set only by the kit,
    and names compare case-insensitively. A leased path spelled with `=`, `;`, a quote or a control
    character is refused. Every job runs in a working folder it leases exclusively; a build gets a fresh
    one and reaches its checkout through `{checkout}`, which is read only. Before spawning, every writable
    directory resource (working folder, target, caches, temporary folder, log directory) passes an
    ancestor proof and a complete no-follow walk, and its walk time is recorded.
  - **K-44 (R010):** request validation is total over JSON values: the top level, then the `type`
    discriminator, then each field a handler reads.
  - **K-46 to K-48″ (R006 withdrawn, R011):** a cleanup submission is refused, and the `build cleanup`
    verb, `cleanup_references`, the cleanup markers and the cleanup code are removed. `build status` and
    `session start` list registered copies as `held`, `released`, `released (human-confirmed)` or
    `damaged`, with `, absent` after a manual removal. A human-confirmed release is restored on recovery
    only from an intact record and never counts as workload-ended proof. An ambiguous one is not restored.
  - **K-45:** generated witness matrices and executed controls in `tests/test_hostqueue_remediation2.py`.
- Implementation review round 17 remediation (`tests/test_hostqueue_remediation4.py`):
  - **R002:** the recorded runner is observed in every active state. A verified drain shows only that
    the runner was alone in its group; a job ends only once the runner itself is gone.
  - **R003:** `inherit_env` is a closed allow-list of read-only classes: search paths, read-only system
    locations, host identity and locale (`jobspec.INHERITABLE`). A tool cache such as
    `NODE_COMPILE_CACHE` is bound through `cache_env`.
  - **R010:** a decoding failure caused by the data (nesting deeper than the JSON decoder follows) is a
    framing error, so the request is rejected alone and service continues.
- Not in 0.4.0: a cleanup class (Owner decision, `#223`); automatic pane sending (deferred, K-4); the
  incident replay suite (P4).

## 0.3.1 — lesson: shared build caches and mtime freshness (2026-10-13)

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
