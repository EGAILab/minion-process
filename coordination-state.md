# Minion-Process — Coordination state specification

**Kit file.** Seeded from `minion-agent-docs` at `dd9fd15`, text preserved. Section references point into `WORKFLOW.md`, which keeps the same numbering as `agent-workflow.md`. Project-specific identifiers in the examples (layer numbers, `Claude`/`Codex`, `pinned_pi`) illustrate the shape; a profile supplies the real names.
**Referenced by:** `WORKFLOW.md` §11.1, §11.1.3, §11.13, §12.6
**Purpose:** Define a machine-checkable current-state model for GitHub work-package coordination.

---

## 1. Principle

The project separates:

```text
current workflow state
from
historical evidence
```

Current state answers:

- What work package is active?
- What exact candidate is current?
- What findings remain open?
- Who acts next?
- What exact action is authorized?
- Is governance required?
- Is the work waiting on an architectural trigger?

Historical evidence answers:

- What happened previously?
- Which candidates were rejected?
- Why?
- Which witnesses were used?
- Which findings were remediated?
- Which governance decisions were made?

A GitHub issue body (or future dedicated state file) stores current state.

Comments, PR reviews, assurance records, and commits store history/evidence.

---

## 2. Required state block

Recommended representation:

```yaml
workflow:
  schema_version: 1

  layer: "11"
  work_package: "WP-11.4"
  title: "Codex OAuth Network Integration"

  status: CONTRACT_CONVERGENCE

  requirements:
    - PROV-012
    - PROV-016

  code:
    pr: 33
    sha: "0123456789abcdef..."
    base: "main"

  docs:
    pr: 92
    sha: "fedcba9876543210..."
    base: "master"

  pinned_pi: "b7bb00b936dbe21b8e160b3e89efdec361846699"

  convergence:
    episode: "CE-L11-04-02"
    open_findings:
      - L11-SC-R025
      - L11-SC-R027

  next_owner: Claude
  next_action: >
    Implement the agreed R025/R027 acceptance matrix and return the
    exact candidate for targeted closure review.

  governance_source: null
  deferred_trigger: null

  quarantine:
    derived_from_quarantined_artifact: false

  updated_by: "Claude"
  updated_reason: "Entered convergence after repeated/coupled review findings."
```

---

## 3. Allowed values

### 3.1 `status`

```text
SCOPING
CONTRACT_DRAFT
CONTRACT_REVIEW
PYTHON_IMPLEMENTATION
IMPLEMENTATION_REVIEW
REMEDIATION
CONTRACT_CONVERGENCE
FINAL_CONTRACT_REVIEW
RUST_IMPLEMENTATION
CLOSURE_REVIEW
WAITING_FOR_TRIGGER
CLOSED
INCIDENT
INVALID_UNAUTHORIZED
BLOCKED_FOR_OWNER
```

State intent is defined in `process/agent-workflow.md` §11.1.3; this file defines only the machine-checkable shape and invariants.

### 3.2 `next_owner`

```text
Claude
Codex
Owner
none/null
```

Other named owners may be added when the project adds additional implementation/review roles.

---

## 4. State invariants

### 4.1 Active-state invariant

For:

```text
SCOPING
CONTRACT_DRAFT
CONTRACT_REVIEW
PYTHON_IMPLEMENTATION
IMPLEMENTATION_REVIEW
REMEDIATION
CONTRACT_CONVERGENCE
FINAL_CONTRACT_REVIEW
RUST_IMPLEMENTATION
CLOSURE_REVIEW
BLOCKED_FOR_OWNER
```

require:

```text
next_owner != null
next_action != null
```

`BLOCKED_FOR_OWNER` requires:

```text
next_owner: Owner
```

### 4.2 Deferred-state invariant

For:

```text
WAITING_FOR_TRIGGER
```

require:

```text
deferred_trigger != null
next_owner == null
next_action == null
```

### 4.3 Closed-state invariant

For:

```text
CLOSED
```

require:

- no open blocking findings;
- accepted/default-branch milestone recorded;
- final disposition recorded for every owned requirement.

### 4.4 Unauthorized/incident invariant

For:

```text
INCIDENT
INVALID_UNAUTHORIZED
```

the state is non-actionable.

It MUST NOT authorize:

- implementation;
- review of the artifact as a candidate;
- certification;
- handoff;
- merge.

---

## 5. Candidate invariants

When `code.pr` is present:

```text
code.sha
```

must identify that PR's current remote-reachable candidate head unless the state explicitly records a frozen prior candidate under review.

Same for docs.

A final approval is bound to:

```text
(code.sha, docs.sha)
```

If either changes:

```text
final approval becomes stale
```

Intermediate targeted finding closure remains valid as historical evidence for the specific finding/candidate, but the final complete approval gate must operate on the exact final pair.

---

## 6. Convergence model

Recommended shape:

```yaml
convergence:
  episode: "CE-L11-04-02"
  root_cause_surface: >
    pre-response HTTP cleanup and authorization-input parsing witness completeness
  open_findings:
    - L11-SC-R027
  provisionally_closed:
    - finding: L11-SC-R025
      sha: "abc..."
      review_evidence: "docs#103"
```

### Rules

If `status == CONTRACT_CONVERGENCE`:

- `convergence.episode` is required;
- at least one `open_findings` entry is required until targeted closure completes;
- transition to `FINAL_CONTRACT_REVIEW` is forbidden while `open_findings` is non-empty.

When all findings are provisionally closed:

```text
CONTRACT_CONVERGENCE
    -> FINAL_CONTRACT_REVIEW
```

### Convergence provenance is retained into `FINAL_CONTRACT_REVIEW`

The `convergence` object does **not** disappear merely because `open_findings` reaches zero. On this transition, the settled record stays attached to the current-state block, for example:

```yaml
convergence:
  episode: "CE-L12-01-01"
  open_findings: []
  provisionally_closed:
    - finding: L12-R001
      sha: "<candidate SHA>"
      review_evidence: "<review artifact>"
```

This is what lets `FINAL_CONTRACT_REVIEW`'s own route-detection distinguish "final review after convergence" from "final review after ordinary remediation" from the candidate's own recorded state, rather than from historical comments or from whether the episode is still "active" -- by the time a candidate reaches `FINAL_CONTRACT_REVIEW`, its convergence episode (if it has one) is always already settled, never "active," so "active convergence episode exists" is never the right test; "a convergence record exists for this candidate" is (§11).

An ordinary-remediation candidate that never entered convergence still carries no `convergence` object at all -- this section does not require one to be synthesized for that route.

---

## 7. Discriminating witness record

For an executable blocking finding (see `process/agent-workflow.md` §11.8.7.1):

```yaml
witness:
  finding: L11-SC-R027
  positive:
    candidate_sha: "abc..."
    command: "pytest ..."
    expected: "PASS"
    observed: "PASS"
  negative_control:
    method: "temporary source mutation"
    mutation: "remove exactly-one-leading-question-mark normalization"
    expected: "relevant parser regression test fails"
    observed: "FAILED as expected"
```

For documentary-only findings:

```yaml
witness:
  finding: L11-SC-R026
  negative_control:
    method: NOT_APPLICABLE
    reason: "documentary/traceability-only finding"
```

A validator does not need to execute arbitrary mutation tests initially. It can first validate that the closure record contains the required fields.

---

## 8. Governance source

When semantic scope, intentional divergence, lower-layer reopening, Pi-baseline change, or other owner-governed decisions are involved (see `process/agent-workflow.md` §11.10):

```yaml
governance_source:
  artifact: "https://github.com/EGAILab/minion-agent/issues/29#issuecomment-..."
  decision: >
    Adopt PROV-014 separately and keep PROV-013 orchestration deferred.
  scope:
    - PROV-013
    - PROV-014
```

A recommendation is not a governance source.

Silence is not a governance source.

An agent's own assertion that the owner approved something is not a governance source.

---

## 9. Deferred trigger

Example:

```yaml
deferred_trigger:
  type: architecture_event
  description: >
    Minion introduces a real provider/auth composition surface that requires
    Models-equivalent login/logout/checkAuth/getAuth orchestration.
  on_fire:
    action: >
      Perform a fresh contract-first Pi audit against the concrete integration
      requirements. Do not resume directly from the historical deferred audit.
```

The trigger should describe an observable project event, not merely a date.

---

## 10. Legal transition sketch

```text
SCOPING
  -> CONTRACT_DRAFT
  -> WAITING_FOR_TRIGGER
  -> BLOCKED_FOR_OWNER
  -> CLOSED                    # scoping-only WP, scoping approved and merged (§10.3)

CONTRACT_DRAFT
  -> CONTRACT_REVIEW

CONTRACT_REVIEW
  -> PYTHON_IMPLEMENTATION
  -> CONTRACT_DRAFT
  -> CONTRACT_CONVERGENCE
  -> BLOCKED_FOR_OWNER

PYTHON_IMPLEMENTATION
  -> IMPLEMENTATION_REVIEW

IMPLEMENTATION_REVIEW
  -> RUST_IMPLEMENTATION       # clean first review, no blocking findings; merge happens
                                # as part of this transition, not as a separate state
  -> FINAL_CONTRACT_REVIEW     # this instance is itself a re-review of a remediated
                                # candidate (ordinary REMEDIATION or convergence TARGETED
                                # REVIEW); see agent-workflow.md §11.4
  -> REMEDIATION
  -> CONTRACT_CONVERGENCE
  -> CLOSED                    # process/status WP only: clean first review APPROVED, candidate
                                # merged (§10.2a)

REMEDIATION
  -> IMPLEMENTATION_REVIEW
  -> CONTRACT_CONVERGENCE

CONTRACT_CONVERGENCE
  -> FINAL_CONTRACT_REVIEW
  # only when all active episode findings are provisionally closed

FINAL_CONTRACT_REVIEW
  -> RUST_IMPLEMENTATION
  -> REMEDIATION
  -> CONTRACT_CONVERGENCE
  -> BLOCKED_FOR_OWNER

RUST_IMPLEMENTATION
  -> CLOSURE_REVIEW

CLOSURE_REVIEW
  -> CLOSED
  -> RUST_IMPLEMENTATION       # remediation of Rust candidate
  -> BLOCKED_FOR_OWNER

WAITING_FOR_TRIGGER
  -> SCOPING                   # only when trigger fires

BLOCKED_FOR_OWNER
  -> any specifically authorized legal continuation state
```

`INCIDENT` and `INVALID_UNAUTHORIZED` are terminal/non-actionable for candidate workflow purposes.

`FINAL_CONTRACT_REVIEW` is not a mandatory second complete review of every candidate. A clean first `IMPLEMENTATION_REVIEW` (no blocking findings) transitions directly to `RUST_IMPLEMENTATION` — the merge happens as part of that transition, not as a separate reviewed step. `FINAL_CONTRACT_REVIEW` exists for candidates that CHANGED after the first `IMPLEMENTATION_REVIEW`: an ordinary `REMEDIATION` re-review, or a `CONTRACT_CONVERGENCE` episode whose findings are all provisionally closed. Reaching `FINAL_CONTRACT_REVIEW` from `IMPLEMENTATION_REVIEW` therefore always means that `IMPLEMENTATION_REVIEW` instance was itself a re-review of a remediated candidate, not the first pass.

### 10.1 Reconciliation with practice (Layer-13 retrospective, PROPOSED)

Replaying the actual status histories of `minion-agent#49`, `#79` and `#88` against the table above (`assurance/process-friction-layer13.md`) showed that the table did not cover the contract-first phase (`agent-workflow.md` §4.1), and that some transitions outside it went unnoticed. The reconciled table, enforced by `minion-process transition-check` / `apply` (`process/tools/minion_process/transitions.py`), adds exactly:

```text
any active state
  -> BLOCKED_FOR_OWNER         # a governance question can arise at any point (§11.7)

CONTRACT_REVIEW
  -> FINAL_CONTRACT_REVIEW     # contract-first phase: targeted closure of contract findings is
                               # done; one complete contract review follows (§11.4 pattern)

FINAL_CONTRACT_REVIEW
  -> PYTHON_IMPLEMENTATION     # contract-phase final review APPROVED (contract checkpoint)
  -> CONTRACT_DRAFT            # contract-phase final review rejected
```

### 10.2 Process-only work packages (`PROC-L13-F001`)

A process/harness work package (no product requirement: `requirements: []`, e.g. `PROC-L13`) has no Python implementation and no Rust side, so `CLOSURE_REVIEW` (Rust's review) never applies to it. Its §11.8.8 final complete review is its closure review. The table therefore also allows:

```text
FINAL_CONTRACT_REVIEW
  -> CLOSED                    # process-only WP: final complete review APPROVED, candidate merged
```

`minion-process apply` refuses it unless `requirements` is an explicit `[]` in both the current and the intended state (a missing or `null` scope is not process-only, and the closing patch may not reclassify a product WP; a legitimate scope correction is a separate, ordinary checked state change), `open_findings` is empty and every `current_candidate` entry records its `merged_sha` (§4.3). A WP that owns any product requirement still closes only through `CLOSURE_REVIEW`.

It keeps these historical transitions **illegal**, with the legal route stated:
- `CONTRACT_REVIEW -> REMEDIATION` and `REMEDIATION -> CONTRACT_REVIEW` (#49): contract findings are remediated in `CONTRACT_DRAFT`. `REMEDIATION` is for an implementation candidate.
- `RUST_IMPLEMENTATION -> IMPLEMENTATION_REVIEW` (#79): Rust review is `CLOSURE_REVIEW`.
- `IMPLEMENTATION_REVIEW -> CLOSED` for any WP that owns product scope (#79): it closes through `CLOSURE_REVIEW`. The one exception is the guarded clean-first-review route of §10.2a, for `process`/`status` WPs only.
- `BLOCKED` (#49): not a status value.

Historical records keep what they recorded. The table applies to transitions made after adoption.

### 10.2a Clean first review of a process or status work package (`minion-process#12`, kit 0.3.2)

The §10.2 route starts from `FINAL_CONTRACT_REVIEW`, which a candidate may enter only after it changed (`WORKFLOW.md` §11.4, §12.6). A process or status WP whose first independent review approved it cleanly therefore had no legal closure: entering `FINAL_CONTRACT_REVIEW` with an unchanged candidate, inventing a remediation or requesting a redundant second review would each misrecord its history (Owner decision, `minion-agent#222` issuecomment-6209854474). The table therefore also allows:

```text
IMPLEMENTATION_REVIEW
  -> CLOSED                    # process/status WP: clean first review APPROVED, candidate merged
```

`minion-process apply` and `close` refuse it, with zero writes, unless all of the following hold:
- **Kind.** `kind` is explicitly `process` or `status`. Any other kind, or none, is refused; a `semantic` or `delta` WP closes through `CLOSURE_REVIEW`.
- **No product scope.** `requirements` is an explicit `[]` in both the current and the intended state.
- **No open findings.** No finding that is not finally closed, in any location the state admits: `open_findings` and `provisionally_closed`, at the top level and under `convergence`. This holds in both states, so the closing patch can neither clear nor hide one.
- **Approval published, bound to the current identity.** The review events are read for the **current** `work_package` (`CE-PROC-P3A-01`) from the coordination issue and from **every candidate PR the issue has ever recorded**: the current state plus each revision in GitHub's own edit history of the issue body. A candidate re-pointed by an earlier ordinary patch therefore cannot hide a review published on its earlier PR. If any revision recorded a different `work_package`, the route is refused; an identity change cannot borrow another WP's approval. The history fails closed. The route is refused when the edit history cannot be fetched, when GitHub returns no body for an edit (its `diff` is nullable), when a revision that carries a state block does not parse, or when a revision records a candidate PR the tool cannot read. A revision is skipped only when it positively carries no state block: no YAML fence opener and no `workflow:` key anywhere in it. The events must be fully read, orderable, conflict-free and free of invalid headers, and the **latest** event must be a `complete: true`, `APPROVED` review of type `IMPLEMENTATION_REVIEW` or `PROCESS_REVIEW`. The review-header validator already refuses an approval with a blocking finding, or one whose reviewer is the author. The tool reads the published header, never a hand-recorded marker.
- **Exact final candidate, unchanged by the closing patch.** The approval's `candidate` map equals the recorded candidates' `sha` exactly. The closing patch keeps `work_package` and, for every candidate, the same sides, `pr`, `sha`, `base` and any other field. It may only record a `merged_sha` that was not yet recorded. A later review, or a changed candidate, makes the approval stale and is refused.
- **Merged.** Every recorded candidate is a PR that GitHub reports `MERGED`, whose head is the approved SHA and whose merge commit is the recorded `merged_sha`.
- **On the default branch.** Each merge commit is reachable from its repository's default branch.
- **Round trip.** The normal coordination-state commit rule (pre-write YAML round trip, post-write re-fetch and equivalence check) applies unchanged.

The existing `FINAL_CONTRACT_REVIEW -> CLOSED` (§10.2) and `CLOSURE_REVIEW -> CLOSED` routes and their guards are unchanged. The route adds no state and no shortcut from `BLOCKED_FOR_OWNER`.

### 10.3 Scoping-only work packages (Owner decision, `minion-agent#157` issuecomment-6051471806)

A scoping-only work package, such as `WP-14.SCOPE`, produces an approved scoping artifact and the downstream work-package issues. It owns no product requirement, and it never enters a contract, Python, Rust or closure-review state. Routing it through states that never occurred would misrecord its history. The table therefore also allows:

```text
SCOPING
  -> CLOSED                    # scoping-only WP: scoping independently approved and merged
```

`minion-process apply` refuses this transition, with zero writes, unless all of the following hold:
- **No product scope.** `requirements` is an explicit `[]` in both the current and the intended state. Missing or `null` is not scoping-only. The closing patch may not add or reclassify scope, so the closure claims no implementation or product certification.
- **No open findings.** `open_findings` is empty.
- **Approval recorded.** `scoping_review` records:
  - `outcome: APPROVED`, the exact token; anything else is refused, including a recorded rejection, `BLOCKED`, `PENDING`, `approved`, `NOT APPROVED`, `null` or a missing outcome (`PROC-L256-R001`);
  - a non-empty `verdict`, for example the review's verbatim verdict line;
  - a non-empty `source`, for example the published review comment.
- **Artifact merged.** At least one candidate (`code`/`docs`, v1 or v2 form) is recorded, and every recorded candidate is a PR that GitHub reports `MERGED` at its recorded `merged_sha`, with that merge reachable from the repository's default branch.

The tool reads the `outcome` token only. It never parses the verdict prose, so it never treats a substring such as `APPROVED` inside `NOT APPROVED` as approval. The `APPROVED` marker is necessary, not sufficient: review semantics stay recorded evidence, never inferred from an empty findings list, and the agent still verifies that `source` independently approved that exact candidate (§11.3).

The generic state machine is otherwise unchanged:
- There is no `BLOCKED_FOR_OWNER -> CLOSED` shortcut.
- A scoping WP blocked on the Owner returns to `SCOPING` through the existing Owner-authorized continuation rule before it closes.
- No state is added.

---

## 11. Suggested validator rules

A first implementation can be simple and deterministic.

Pseudo-rules:

```text
if status in ACTIVE_STATES:
    require next_owner
    require next_action

if status == WAITING_FOR_TRIGGER:
    require deferred_trigger
    forbid next_owner
    forbid next_action

if status == CONTRACT_CONVERGENCE:
    require convergence.episode
    require convergence.open_findings.length > 0
        unless transition is immediately being made to FINAL_CONTRACT_REVIEW

if transition_to == FINAL_CONTRACT_REVIEW:
    require candidate changed since the original
        IMPLEMENTATION_REVIEW candidate
    # FINAL_CONTRACT_REVIEW is reachable via TWO valid routes -- ordinary
    # remediation (no convergence record at all) and settled convergence
    # (a convergence record is retained, not discarded, once its open
    # findings reach zero -- see section 6) -- so the check branches on
    # which route this candidate took. The route is detected from whether
    # a convergence RECORD/PROVENANCE exists for this candidate, never
    # from whether the episode is still "active": a candidate is not
    # "active" convergence by the time it reaches FINAL_CONTRACT_REVIEW at
    # all (the episode is already settled), so "active convergence
    # episode exists" would incorrectly evaluate false for every genuine
    # convergence-derived candidate and misroute it into the ordinary-
    # remediation branch below.
    if convergence record exists for this candidate:
        require convergence.open_findings.length == 0
        require all convergence findings == PROVISIONALLY_CLOSED
    else:
        require candidate came through ordinary REMEDIATION
        require the preceding targeted IMPLEMENTATION_REVIEW
            closed all blocking remediation findings
    # A normal remediation candidate is not required to carry a synthetic
    # or empty `convergence` object merely to satisfy this rule.

if governance-dependent fields changed:
    require governance_source

if quarantine.derived_from_quarantined_artifact:
    reject handoff

if status in [INCIDENT, INVALID_UNAUTHORIZED]:
    reject candidate handoff/review/merge

if final_approval.sha_pair != current_candidate.sha_pair:
    approval is stale

if provisional_closure is claimed for executable finding:
    require positive witness record
    require negative-control witness record
```

---

## 12. Layer 11 example after migration

This is a **classification overlay only**, applied retroactively for illustration. It does not renumber or rewrite any historical finding ID, commit, PR, or assurance evidence from before this schema existed.

```yaml
layer: "11"
title: "Real Providers"
work_packages:
  - id: WP-11.1
    title: Auth Foundation
    requirements: [PROV-006, PROV-007, PROV-008, PROV-009, PROV-010]
    status: CLOSED
    source_coordination: "issue #24"

  - id: WP-11.2
    title: Codex Account Projection
    requirements: [PROV-011]
    status: CLOSED
    source_coordination: "issue #29"

  - id: WP-11.3
    title: Provider/Auth Interaction Vocabulary
    requirements: [PROV-014]
    status: CLOSED
    source_coordination: "issue #29"

  - id: WP-11.4
    title: Codex OAuth Network Integration
    requirements: [PROV-012, PROV-016]
    status: CLOSED
    source_coordination: "issue #29"

  - id: WP-11.D1
    title: Generic Auth Orchestration
    requirements: [PROV-013]
    status: WAITING_FOR_TRIGGER
    source_coordination: "issue #35"
    deferred_trigger:
      type: architecture_event
      description: >
        A real provider/auth composition surface exists that requires
        Models-equivalent orchestration.

  - id: WP-11.D2
    title: Provider Streaming Extensions
    requirements: [AI-031, AI-032]
    status: WAITING_FOR_TRIGGER
    source_coordination: "issue #37"
    deferred_trigger:
      type: architecture_event
      description: >
        A concrete wire-protocol LLM/model adapter exists with a real
        ProviderStreams-equivalent caller-facing streaming surface capable
        of exposing streamSimple and/or deferred operations.

incidents:
  - issue: 27
    status: INVALID_UNAUTHORIZED
    related_artifacts:
      - "minion-agent PR #28 @ ed58b714613000bdee6eedfb41a38b2ceb9b5a56"
      - "minion-agent-docs PR #73 @ cbc3ba5f373b0a63d5e611fe7e40f6dcca79ff08"
```

This representation makes the project state explicit without rewriting any historical Layer 11 artifact.

---

## 13. Lean current state (schema v2, PROPOSED)

The current-state object answers only the §1 current-state questions. Layer 13 showed bodies growing to 24–35K characters (`#49`, `#88`), because every prior review, old SHA, test count and remediation narrative was kept in the state block. That contradicts §1 and makes every read and write carry history.

### 13.1 What belongs in the state block

```yaml
workflow:
  schema_version: 2
  work_package: WP-13.2
  title: "Filesystem mutation tools (write, edit)"
  status: REMEDIATION
  requirements: [TOOL-029, TOOL-030]

  current_candidate:          # v1 `code` / `docs` stay accepted; one or the other form
    code: {pr: 87, sha: "<40-hex>", base: main}
    docs: {pr: 191, sha: "<40-hex>", base: master}

  dependencies:               # edges for the scheduler (agent-workflow.md §11.15)
    L0506-D001: {issue: 88, relation: blocked_by, status: RUST_IMPLEMENTATION}

  open_findings: [L13-WP132-I004]          # IDs only
  provisionally_closed: [L13-WP132-I001, L13-WP132-I002, L13-WP132-I003]

  convergence:                # only while an episode is active or settled for the candidate
    episode: CE-...
    checkpoint: PROPOSED FOR IMPLEMENTATION | AGREED FOR IMPLEMENTATION
    open_findings: [...]

  governance_source: {...}    # §8, when a governed choice is in force
  deferred_trigger: null
  quarantine: {derived_from_quarantined_artifact: false}

  next_owner: Claude
  next_action: "<one concrete action>"
  updated_by: Claude
  updated_reason: "<one line>"

  history:
    assurance_index: assurance/layers/13-wp132-index.md   # or an issue-comment link
```

### 13.2 What does not belong in it

These move to assurance records or comments, which the `history` reference points at:
- prior reviews and their SHAs;
- old candidate SHAs;
- test counts;
- remediation narratives;
- closed findings' details;
- finding rule/scope prose (it lives in the finding's assurance record);
- status-transition logs.

### 13.3 Rules

- **Budget.** A state body SHOULD stay under 8,000 characters. `minion-process validate` warns above it, and warns on history-shaped keys (`remediations`, `reviews`, `review_history`, `history_log`).
- **Shape.** In v2, `open_findings` / `provisionally_closed` are lists of finding IDs, an error otherwise. The v1 mapping form (ID → details) is accepted with a warning.
- **Provenance** is not lost. Every removed item must be reachable from `history.assurance_index` or from issue comments before it leaves the state block.
- **Commit rule unchanged.** The §11.1.1 commit rule (full semantic round-trip) applies unchanged, and a smaller object makes it cheaper.

### 13.4 Migration

Migration is incremental and per issue, performed when that issue next changes owner:
1. write the history index (assurance record or comment) containing every item being removed;
2. apply the lean state with `minion-process apply` (validated, round-trip checked);
3. link the index from `history.assurance_index`.

Parsers of v1 keep working: `code`/`docs` stay accepted, and `current_candidate` is an alternative, not a replacement, until every open issue is migrated.

### 13.5 Field shapes and entry points (normative, CE-PROC-L13-01)

The field table and the entry-point table in `assurance/process-ce-proc-l13-01.md`, revisions 1–3 (agreed), are the normative shape rules for every field a coordination tool consumes. In summary:

- **Identity.** `work_package` is a required non-empty string; `title` and `layer` are optional strings.
- **Control fields** (`next_owner`, `next_action`, `updated_by`, `updated_reason`) are strings or null. `schema_version` ∈ {1, 2}.
- **Candidates.**
  - A `code`/`docs` side is a mapping or null (null means no candidate).
  - `pr` is a positive integer. `sha` and `merged_sha` are 40-hex.
  - `sha` is required with `pr` or `merged_sha`, and `merged_sha` requires `pr`.
  - A v2 `current_candidate` is a mapping whose only keys are `code`/`docs`. It is never mixed with top-level `code`/`docs`, and a malformed one is never read as absent.
- **Containers** are validated before their elements, at every depth:
  - `requirements`, `open_findings`, `provisionally_closed`, `convergence.open_findings` and `convergence.provisionally_closed` take finding/requirement IDs;
  - `convergence.provisionally_closed` also accepts the §6 `{finding, …}` mapping;
  - the v1 top-level ID → details mapping is a warning in v1 and an error in v2.
- **Other shapes:**
  - `governance_source` and `deferred_trigger` are a mapping, a non-empty string, or null;
  - `quarantine` is a mapping with a boolean flag;
  - v2 `dependencies` maps a name to `{issue, relation}`;
  - v2 `history` is a mapping.
- **Entry points** validate the state they consume before consuming it:
  - validation and the read-only operations are total, reporting diagnostics and never raising;
  - a mutation refuses an invalid *current* or *intended* state with zero writes, and refuses a state YAML cannot carry unchanged;
  - an invalid current state is repaired only by restoring, byte for byte, an earlier valid revision from the issue's own GitHub edit history, then making changes with a normal checked mutation.

### 13.6 The state-block load boundary (normative, CE-PROC-L13-01 revision 5)

A state block is loaded as a **graph**, not just parsed:

- **L1′ (totality).** Any `Exception` raised while loading the fenced YAML, or while checking the loaded graph, is malformed content and is reported as a body-format error. A non-`Exception` `BaseException` is not caught.
- **L2′ (shape).** The loaded state must be an **acyclic** graph of JSON-domain nodes: mappings with string keys, lists, strings, ints, floats, bools, null.
  - **Depth:** container depth at most **64**. The root mapping is 1, and each nested mapping or list adds 1; a shared alias counts at its deepest reference.
  - **Size:** expanded size at most **100 000** nodes, each shared alias counted once per reference.
  - **Implementation:** the check is iterative.
- **L3 (resolver).** Implicit scalars resolve only per the YAML 1.2 core / JSON schema:
  - **resolved:** `true`/`false`, decimal ints without leading zeros, floats with a `.` (and `.inf`/`.nan`), and `null`/`~`/empty;
  - **left as strings:** `yes`/`no`/`on`/`off`, sexagesimal numbers, implicit timestamps and leading-zero numbers;
  - **left literal:** the `<<` merge key.

  Explicit tags still construct their types, and L2′ then rejects the non-JSON ones.
- **L4 (symmetry).** Writes are checked with the same loader: a state that would not read back unchanged is never written.

---

## 14. Kind, consequence class, stage skips and routes (kit 0.2.0, normative)

Owner decisions 2 and 3 of 2026-10-11 (`minion-agent#205`) and `minion-agent#75` Amendment 2. Rules in
`consequence-classes.md` and `routing.md`; enforced by `minion-process validate` and the `apply` guard.

```yaml
workflow:
  kind: process                           # semantic | delta | process | scoping | status
  consequence:
    class: mechanical                     # governing | mechanical
    rule: CP-0                            # CP-0 (none applies) | CP-1..CP-6 | the upgrading finding ID
    confirmed_by: Codex                   # the first independent review confirms or corrects the class
    upgraded_by: [PROC-X-R003]            # findings that matched a predicate (automatic upgrade)
    downgrade: {owner_decision: "...", reviewer: Codex}   # Owner-only (#75 item 11); needs governance_source
  skipped:                                # measured stage skips only (consequence-classes.md)
    - {stage: IMPLEMENTATION_REVIEW, rule: SK-1, measured_rows: [F1.-0, F1.inf], reviewer: Codex}
  history:
    routes: [{rule: RT-2, at: "2026-10-12", reason: "WP-B idle while Codex reviews WP-A"}]
```

### 14.1 Shape rules (validator)

- `kind` ∈ the five kinds. `consequence` is a mapping with `class` ∈ {governing, mechanical} and `rule` a
  predicate id `CP-0`–`CP-6` or a finding ID; `CP-0` only with `mechanical`; a `CP-1..6` or finding rule
  only with `governing`. `confirmed_by` non-empty string; `upgraded_by` a list of finding IDs; `downgrade`
  a mapping with non-empty `owner_decision` and `reviewer`. Unknown keys are errors.
- `semantic` and `delta` are governing by definition. `process`, `scoping` and `status` carry
  `requirements: []`; `semantic` and `delta` carry a non-empty list.
- A `scoping` WP is only ever in `SCOPING`, `BLOCKED_FOR_OWNER`, `CLOSED`, `INCIDENT` or
  `INVALID_UNAUTHORIZED` (§10.3).
- A `mechanical` WP is never in `CONTRACT_CONVERGENCE`: a firing trigger upgrades the class first.
- `skipped` entries name a stage (never `FINAL_CONTRACT_REVIEW`), a rule `SK-n`, non-empty
  `measured_rows` and the consenting `reviewer`; a governing WP has no skipped stage.
- `history.routes` entries name a rule `RT-1`–`RT-6`, `at` and `reason`.
- All four fields are optional in the shape, so WPs opened before kit 0.2.0 stay valid; a v2 state
  without `kind`/`consequence` draws a warning. **Presence is decided by the key**: a supplied `null`
  in any of these positions is a malformed value and an error, never absence (`PROC-KIT-P2-R002`).
- `classification_pending: true` marks a new WP that paused (`BLOCKED_FOR_OWNER`, `WAITING_FOR_TRIGGER`)
  before intake; it is a boolean and never coexists with `kind`/`consequence`.
- A stage is skipped only on a WP classified `mechanical`; an unclassified or governing WP has no
  `skipped` entries.

### 14.2 Transition rules (`apply` guard)

- **Intake.** Leaving `SCOPING` for an active working state requires `kind` and `consequence` in the
  intended state. Leaving `SCOPING` unclassified for a pause state requires `classification_pending:
  true`; a WP carrying that flag cannot enter a working state until classified, and cannot drop the
  flag while unclassified (`PROC-KIT-P2-R003`).
- **Classification is sticky.** Once recorded, `kind` and `consequence` are never removed or nulled;
  any effective lowering from `governing` (to `mechanical` or to absent) is the Owner-only downgrade
  (`PROC-KIT-P2-R001`).
- **No schema rollback.** `schema_version` never decreases in an ordinary `apply`; the intake
  obligation is computed from the higher of the current and intended versions, so a new v2 record
  cannot be retagged as legacy v1 to escape intake (`PROC-KIT-P2-R003`, refined). A genuine v1 record
  may be upgraded to v2 and takes the v2 rules from then on.
- **Kind is fixed after intake.** A different kind is a new WP.
- **Downgrade is Owner-only.** governing → mechanical requires `consequence.downgrade` and a recorded
  `governance_source`; the tool checks presence, the agent validates the source (§11.10).
- **Closure by kind.** `FINAL_CONTRACT_REVIEW -> CLOSED` (§10.2) and `IMPLEMENTATION_REVIEW -> CLOSED`
  (§10.2a) only for `process`/`status`; `SCOPING -> CLOSED` (§10.3) only for `scoping`;
  `semantic`/`delta` close through `CLOSURE_REVIEW`.
- Existing §10.2/§10.3 checks (explicit `[]`, no open findings, merged candidates, approved scoping
  review) are unchanged and run after this guard.
