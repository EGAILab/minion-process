# Minion-Process — Coding-agent workflow (normative core)

**Kit version:** see `CHANGELOG.md`. A project pins one in `profile.yaml`.
**Profile:** the project-specific names used below come from the project's profile
(`profiles/profile.schema.json`): the **authority** chain (§3), the **repositories** and their default
branches, the **agents** and the roles they hold (`roles/`), the taxonomy **aliases**
(`finding-taxonomy.md`), the **gate launchers** (`gate-tiers.md`), the **delegation** source and the
**coordination backend** (`coordination-state.md`). Where this file says "the authority", "the
coordinator", "the reviewer", "the first/second implementation language", read the profile's values.
**Numbering:** sections keep the numbers of Minion-Agent's `agent-workflow.md`, which this core was
split from, so cross-references in the other kit files and in historical records stay valid. Incident
narratives moved verbatim to `lessons/<ID>.md`; each rule that was paid for by one links to it. The
project-specific sentences that became profile values are preserved verbatim in
`seed-history/minion-agent-specifics.md`, with the profile field each one maps to.
**Role files** (`CLAUDE.md`, `AGENTS.md`, …) of a consuming project add only ownership paths and
environment rules, and point here for everything else.

## 1. Project goal

The project is one product with one language-neutral semantic contract and one or more first-class
implementations (profile `implementation_order`).

For authority-derived behavior, reproduce the authority's observable semantics as closely as practical.
Do not replace that behavior with a cleaner, more generalized, or more abstract design merely because it
is easier to implement. The project's own architecture may change ownership, registration, lifecycle,
composition, and implementation mechanics; it does not by itself justify changing authority-visible
behavior. A project's compatibility policy (for example Minion-Agent's practical-parity Owner decision)
is recorded in the project's own docs and governs through §6.1 and Owner governance; the kit does not
restate it.

The adopted authority revision is pinned in the profile (`authority[].pin`). If the project's frozen
design later adopts a different baseline, the frozen design wins over the pin, and the profile is
updated in the same reviewed change.

## 2. Read these before substantive work

Always use the current repository contents, not remembered state.

1. the project's frozen design (profile `authority` entries of kind `design`);
2. this file, `coordination-state.md` (the machine-checkable coordination-state schema referenced
   throughout §11), `gate-tiers.md` and `hazards/hazard-families.md` (§9.5, §13.1);
3. the current work package's spec and assurance artifacts;
4. the manifest (profile `authority` kind `manifest`);
5. the applicable canonical scenarios (kind `conformance`);
6. the adopted authority source for the symbols being implemented or reviewed.

Do not assume old prompt SHAs, test counts, scenario counts, file names, or layer status are still
current. Fetch first and record actual HEADs.

## 3. Semantic authority

For authority-derived behavior the chain is the profile's `authority` list, highest first, for example:

`adopted source -> parity manifest -> normative spec -> canonical conformance -> implementations`

The frozen design defines architecture, scope, and the fidelity goal. Canonical conformance is the
executable oracle for the finite examples it covers. The language-neutral spec governs the general rule
and behavior outside those examples. Assurance records evidence and release status; it does not create
semantics.

No implementation is the behavioral oracle for another implementation.

A contradiction among the frozen design, normative spec, and applicable canonical conformance is a
release-blocking contract defect. Do not silently choose one side.

## 4. Standard layer workflow

Unless the task explicitly narrows the pass further, use this sequence:

1. Fetch every repository, inspect status, record actual starting HEADs, preserve unrelated work.
2. Read the current layer assurance/handoff and exact scope/exclusions.
3. Audit the relevant adopted authority source first.
4. Build or verify the authority-to-project behavior/ownership mapping.
5. Repair shared contract/evidence before implementing around a bad contract.
6. Implement only the current layer through real existing seams.
7. Add focused language tests and applicable language-neutral canonical evidence.
8. Run the gates the stage requires (`gate-tiers.md`, §13.1). A complete-review hand-off (first
   implementation review, final complete review, closure review) and certification require G3
   evidence, including regressions for previously certified layers; a targeted finding-closure
   hand-off requires only the tier its stage row gives.
9. Perform the required independent cross-language review/implementation handoff.
10. Certify/freeze only when the layer's gate is satisfied.
11. Stop. Do not automatically start the next layer.

The first implementation language may lead the second by roughly half to one layer. `NOT_IMPLEMENTED`
in the lagging language is a valid state and is not itself a defect.

### 4.1 Contract-first checkpoint for high-risk semantics

For a layer or semantic slice with substantial concurrency, async scheduling, callback/listener
ordering, cancellation, failure recovery, lifecycle interleaving, provider/tool interaction, or another
behavior where small ordering differences are observable, front-load independent contract work before a
large implementation pass:

```text
shared-contract owner: authority audit + draft behavior matrix/spec/conformance
                    ↓
reviewer: independent authority audit of the same semantic slice
                    ↓
resolve contract/evidence findings
                    ↓
CONTRACT CHECKPOINT
                    ↓
first-language implementation
                    ↓
independent implementation-readiness review
```

The checkpoint is not cross-language certification and does not authorize the second implementation.
It exists to move semantic discovery earlier so the implementation review is not used as the primary
contract-discovery mechanism.

A contract checkpoint SHOULD be used when any of the following is true: the surface depends on
scheduler or callback timing; it has several interacting dimensions whose cross-product matters; prior
layers have shown repeated late semantic discoveries in similar code; the same rule would be expensive
to repeatedly rewrite after implementation; a reviewer cannot state a finite discriminating behavior
matrix before implementation.

### 4.1.1 Cross-Language Feasibility Audit (mandatory before a high-risk contract freeze)

For every high-risk authority-derived work package (§4.1's criteria, or any WP whose values cross a
lower-layer boundary, touch strings, numbers or Unicode, or depend on lower-layer seams), the
shared-contract owner produces a **Cross-Language Feasibility Matrix** from
`templates/cross-language-feasibility-matrix.md`.

The contract cannot become `AGREED FOR IMPLEMENTATION` (§11.8.5) or pass its contract checkpoint
(§4.1) until the independent checkpoint reviewer has verified the matrix.

**What the matrix covers.** It audits the WP's relevant **transitive** authority semantic path, not
just the entry function: the runtime value-domain matrix; the lower-layer capability matrix; the
cross-runtime hazard checklist; the concurrency/order matrix, with a realistic wrong implementation per
material ordering guarantee.

**What an entry may say.** Every entry ends `AUDITED`, `NOT_APPLICABLE` (with a reason) or
`DEFERRED_WITH_REASON`. Silence is not an answer.

**A gap is a finding.** A row that shows a lossy representation, a missing lower-layer seam, or a
hazard the contract does not state is classified with the normal taxonomy (§6) and resolved **before**
the checkpoint. That includes any additive lower-layer extension WP, or an Owner decision for a
non-additive reopen.

Why: two semantic dimensions of one work package were discovered only after implementation began
(`lessons/WP-13-2-FEASIBILITY.md`).

### 4.2 Work-package slicing

A large assurance layer MAY be divided into smaller **work packages** without changing the
architectural layer boundary. A work package is the smallest unit that has all of: a bounded semantic
surface; an explicit set of requirement IDs; a coherent contract/evidence set; a single coordination
state; a clear certification or deferred-parity outcome.

A work package SHOULD be organized around observable semantic ownership, not implementation modules.
It is not independently certified as the whole layer: a layer is complete for the current baseline
only when every in-scope requirement is `CERTIFIED`/`ADOPTED`, `DEFERRED PARITY` with an explicit
closure trigger, or `INTENTIONAL DIVERGENCE` with valid governance provenance (§11.1, §11.13).

**Semantic-risk map at scoping.** During `SCOPING`, record for each candidate surface: the semantic
surface; lower-layer dependencies; external runtime/library dependencies; cross-language representation
risk; concurrency risk; likely review independence. Optimize for an independently characterizable
surface, an independently reviewable behavior matrix, minimal cross-layer dependencies and a bounded
blast radius. Do not group surfaces merely because they live in one source folder. If one WP combines
several largely independent high-risk surfaces, split it **before** contract drafting.

Do not use "Pass" as a semantic or certification level. Review rounds are events within a work
package, not additional project hierarchy.

### 4.3 Kinds, consequence classes and stage skipping

Every work package is classified at intake, before it leaves `SCOPING`, with a **kind** (`semantic`,
`delta`, `process`, `scoping`, `status`) and a **consequence class** (`governing` or `mechanical`)
derived from the consequence predicates: containment, acceptance, transitions, authority, execution,
evidence interpretation (`consequence-classes.md`, `coordination-state.md` §14). The class, not the
kind, selects the route: a governing change takes the full route of §11.4 and §11.8; a mechanical
change keeps independent review and the final complete review of the changed candidate and drops only
the convergence checkpoint ceremony. `semantic` and `delta` are governing by definition. The first
independent review confirms or corrects the class. An upgrade is automatic and recorded when a finding
matches a predicate; a downgrade is Owner-only. A stage is skipped only on a mechanical change, with
the feasibility rows it would have examined measured against the pinned authority, the reviewer's
consent recorded, and never the final complete review. The failure signal is a round that produces no
new discriminating evidence, not the round count (`lessons/PROC-KIT-ROUTE-BY-CONSEQUENCE.md`).

## 5. Scope discipline

The current task's layer boundary is binding.

- Do not implement a later layer to make the current layer easier to test.
- It is fine to inspect later-layer code/callsites to understand a boundary; do not certify that later
  behavior accidentally.
- Do not start future work unless the current task explicitly owns it.
- Reuse already-certified lower-layer seams. Do not duplicate existing authorities in a new layer.
- A higher layer may project or compose lower-layer state without changing the lower layer's
  observable contract. Do not reopen a certified lower layer merely because it lacks a convenience API.

## 6. Finding taxonomy

Every material issue uses exactly one established classification from `finding-taxonomy.md`:
`AUTHORITY_BEHAVIOR_UNCERTAIN`, `AUTHORITY_PARITY_DEFECT`, `CONTRACT_ASSURANCE_DEFECT`,
`PARITY_NEUTRAL_HARDENING`, `PARITY_CONSTRAINED_RISK`. A profile may alias historical names onto them.
Do not invent softer labels to avoid a blocker.

### 6.1 Divergence dispositions

A reviewer still reports every confirmed difference from the authority, with discriminating evidence
and its usual classification. Its disposition is **required parity**, **an existing approved
architectural mapping**, or **an intentional divergence**, which needs Owner governance. The screening
questions, the "no, no, yes" heuristic and the four requirements of an accepted divergence are in
`finding-taxonomy.md`. Only the Owner accepts a divergence; the author brings an options packet and
never self-accepts. This relaxes the compatibility goal; it is not permission to leave an ordinary
parity defect unfixed.

## 7. Contract-quality rule

Contract stability is not a goal in itself. If implementation evidence shows that the observable
contract is incomplete, contradictory, or forces a semantically artificial design, reopen the affected
contract and repair spec/conformance/traceability before certification. But do not change the contract
merely because another implementation is cleaner; if the better implementation preserves the observable
contract, use it without changing semantics.

Warning signs: a conformance runner simulating missing library semantics; the same normative rule
reimplemented in multiple layers; special cases needed only to preserve underspecification; errors
swallowed or distorted to fit the contract; bypassing an already-certified abstraction; two reasonable
independent implementations forced to choose observably different behavior because the boundary is
undefined; new normative prose that is true in isolation but contradicts an already-certified section
elsewhere in the same document (fixing one finding's own narrow claim without re-checking whether a
general-sounding phrase like "fixed," "never changes," or "set once" still holds once other certified
sections covering the same field/value are accounted for).

## 8. Shared artifacts and dispositions

Shared semantic artifacts are single-source and must not be forked by language: the manifest, the
canonical conformance, the normative spec, frozen design/process documents, and assurance documents as
historical evidence.

Every relevant manifest row has an explicit disposition: `adopted`, `deferred parity` or
`intentional divergence`. Silence is not a valid disposition. A useful row traces:

`authority path + symbol -> project rule -> canonical scenario or explicit language test -> evidence per language -> disposition`

Preserve review/remediation history. Do not rewrite a historical rejection into an approval; add later
remediation/re-review evidence.

Machine validation of traceability artifacts validates each field's container shape before validating
or iterating its contents. An iterable scalar or mapping must not accidentally satisfy a required list
field. Keep negative probes for plausible malformed container shapes alongside the validator.

## 9. Canonical conformance

The project declares its **canonical behavior families** and its **support infrastructure** in the
profile (`conformance.families`, `conformance.support`). The families are the only behavior families;
a support directory (schemas, fixtures, runner helpers) is not an additional behavior family and
never carries behavior of its own. Minion-Agent declares exactly three families, `runtime`, `session`
and `agent`, with `schema` as support (`seed-history/minion-agent-specifics.md`).

Canonical data is language-neutral. Language-specific runners are thin adapters:

`parse scenario -> construct typed inputs -> invoke the real project seam -> normalize observations`

A runner MUST NOT implement the semantics it is supposed to test: it never fabricates queue behavior,
ordering, shadowing, transforms, execution semantics, lifecycle, reset behavior, or expected results.
Valid mocking uses a scripted dependency through the real seam; invalid mocking has the runner itself
simulate missing behavior.

Do not force a canonical scenario through an unfinished later layer. If behavior is not independently
observable at the current layer, document the boundary and use explicit language evidence or a
justified deferred scenario until the real seam exists. Discover scenario counts dynamically.

When canonical observations convert an unordered or implementation-defined collection into an ordered
list, the shared contract specifies the canonicalization key, including field precedence, distinct from
any production return-order rule. The evidence contains at least two entries chosen to distinguish
plausible but different sort keys; single-entry observations cannot certify ordering agreement.

### 9.1 Discriminating evidence

Evidence must distinguish the claimed semantic rule from plausible incorrect implementations. A test
that proves only a weaker neighboring condition does not close a review finding (required rule: "prompt
lifecycle completes before steering is claimed"; insufficient evidence: "turn_start happens before
steering is claimed").

For callback, listener, scheduler, failure, and concurrency semantics, tests SHOULD cover the smallest
cross-product necessary to distinguish the rule. Typical dimensions: listener count (0 | 1 | 2+),
listener behavior (synchronous | suspending), listener result (success | throw), execution mode
(sequential | parallel), event stage (start | update | end), state timing (before | during | after
listener), completion timing (callback return | work continuation | event join). Do not test every
theoretical combination mechanically. Select the combinations that distinguish the adopted rule from
realistic incorrect implementations.

For an authority-protection fix on a multi-field payload, enumerate each protected field's own redirect
and omission separately, and construct omission witnesses that are genuinely shorter than the full
payload with the field specifically absent, never a bare argument-less continuation
(`lessons/L09-R015.md`).

### 9.2 Reviewer witness rule

Every blocking `AUTHORITY_PARITY_DEFECT`, `CONTRACT_ASSURANCE_DEFECT`, or
`AUTHORITY_BEHAVIOR_UNCERTAIN` discovered in independent review MUST include a minimal discriminating
witness when the behavior is executable or observable, stating: finding ID; authority/source basis;
minimal setup; expected observable trace/state; candidate observed trace/state; why the difference is
discriminating. When practical, the reviewer provides an executable probe against the pinned authority
and/or the real project seam.

The remediation owner MUST turn the exact discriminating observation into permanent regression evidence
before handing the finding back for closure. A prose-only finding is acceptable only when the defect is
inherently documentary/traceability-only and no executable distinction exists.

If the review states that existing code already satisfies a new witness, the remediation owner MUST
run that exact witness against the UNCHANGED candidate and confirm it directly before relying on the
claim, and report the confirmation. A "no code change" remediation still needs the full
discriminating-evidence treatment: the new regression test is what closes the contract ambiguity.

#### 9.2.1 Reviewer factual-evidence rule

A reviewer verifies every factual or source claim before filing a blocker on it. For a source-reference
claim (an authority symbol, a library or runtime behavior, a citation, a claim that "these lines are
unrelated"): fetch the exact version or tag; locate the exact symbol; verify the content; record the
commit, hash or version with a **content-addressed** link. A blocker without such a record is not filed
(`lessons/WP-12-E3-C002.md`).

A semantic finding states, in the review record: the rule believed violated; the exact authoritative
source (content-addressed); a minimal reproducer; the candidate observation; the expected observation;
why existing tests/evidence do not distinguish it; a suggested discriminating witness convertible into a
regression test (`templates/review-record.md`).

A finding that expresses suspicion without discriminating evidence is recorded as a **question**, not
a blocker. The remediation owner answers it; it does not by itself move the WP to `REMEDIATION`.

### 9.3 Pinned-authority characterization probes

**Authority dependencies** (normative, `authority-dependencies.md`). An independent reviewer must
independently **verify** the exact authority inputs and **execute** the authority; downloading identical
bytes is not required. External dependencies are verified against their authoritative pinned digest,
whatever their source. Docker and network access are conveniences; exact pinned runtime identity stays
mandatory.

For subtle observable behavior that depends on runtime mechanics, maintain development-only
characterization probes against the pinned authority revision, in a clearly non-normative location. A
probe may normalize observable traces (`listener_1_enter`, `tool_continues`, …). Rules: the pinned
authority source remains the semantic source; the spec and canonical conformance remain the contract;
characterization output is derivation/debugging evidence, not a new semantic authority; production code
never depends on the authority's harness; pin the revision the probe used; prefer deterministic,
minimal examples; when a probe reveals a rule, express it in the normal manifest/spec/conformance/
evidence chain.

**Verify engine and platform premises by execution.** A design premise about how a delegated engine, a
pinned library or a platform behaves is not adopted until it has been executed: the premise cites an
executed probe against the pinned artifact, recorded with the design and repeated on each platform the
premise covers. Documentation, memory or another version is a hypothesis until probed
(`lessons/CE-L13-WP134-01.md`).

**Expected results come from the authority, not from the construction under review.** Derive
expectations from the authority itself (its own transformation run on the real engine), never from the
proposal's own construction. When an oracle uses a predicate to select or classify cases, check that
predicate against independently written expectations before trusting its output
(`lessons/CE-L13-WP134-01.md`).

### 9.4 Semantic-neighborhood expansion

When a finding hits one member of a known semantic family, do not close only that point. Before
remediation is proposed, the remediation owner characterizes the **smallest coherent partition**
containing it: every member of the matching hazard family (`hazards/hazard-families.md`), probed
against the pinned authority, recorded in the finding's remediation record or the convergence episode
record (§11.8.1). Members that need no change are recorded `AUDITED — no change` and become regression
witnesses where cheaply executable. The reviewer checks the expansion record at targeted closure. A
missing partition member is a `CONTRACT_ASSURANCE_DEFECT` against the remediation, not a new
independent finding. Adjacent members discovered one review cycle at a time are what this prevents
(`lessons/WP-13-2-FEASIBILITY.md`).

**Characterize compositions of scoped rules, not only each class alone.** A rule of the form "rule X
applies to this class, and everything else keeps the authority's meaning" needs mixed cases where both
occur in **one** input (`lessons/CE-L13-WP134-01.md`).

**Re-check the neighbourhood after every fix.** After changing behaviour, the remediation owner
re-checks the nearest rules that share the changed mechanism, representation, lifecycle boundary or
error path, and records that re-check with the remediation. Keep it proportional (decoder fix → EOF,
BOM and replacement; timer fix → ordering of success, timeout and abort; stream-disposal fix → wait,
read, close, terminate; error-mapping fix → every other source of the same code; cancellation fix →
races before, during and after completion; filesystem mutation fix → sibling operations on the same
path or error mechanism). An unexpected change in a neighbouring rule is new evidence
(`lessons/WP-13-3-NEIGHBOURHOOD.md`).

### 9.5 Reusable hazard families

Families are consulted up front: `hazards/hazard-families.md` holds the reusable runtime hazard
families; the feasibility matrix (§4.1.1) and neighborhood expansion (§9.4) consult them instead of
rediscovering them. When a finding reveals a generalizable hazard class, its remediation also adds the
member or family there: *a model discovers a class once → the harness remembers it → future work gets
the probes automatically.* Executable harnesses live in the project's non-normative characterization
location (§9.3).

### 9.6 Event-driven witnesses

When the behaviour under test has a meaningful observable event or synchronization boundary (process
exit, stream EOF, callback entry, write completion, cancellation propagation, queue acquisition or
release, listener invocation, an explicit readiness signal), a test coordinates on that event. It does
not infer the event from elapsed wall-clock time. Timed sleeps remain acceptable when wall-clock timing
is itself the contract, or as bounded safety timeouts. Don't use an arbitrary sleep as the primary
discriminator when an event-driven synchronization point is available (`lessons/WP-13-3-TIMING.md`).

### 9.7 A negative control is caught only by its intended witness

A negative-control mutation counts as killed only when the test or witness meant to discriminate that
defect actually fails, for the expected reason (§11.8.7.1). It is not enough that some unrelated test
fails; that the suite becomes red somewhere else; that the mutation crashes or fails to import, collect
or compile before the intended assertion; that another invariant happens to detect it; or that a
missing environment prerequisite fails tests regardless of the mutation. For each control the record
identifies the mutation, the intended witness, the expected and the observed discriminating failure.
Control runners reject collection, setup and compile failures as kills mechanically and report the
identity of each killing test.

**A control runner proves its own baseline first.** Before any mutant, it executes the unmutated
candidate and stops as INVALID unless every witness it will rely on runs and passes, each mutant's
intended test appears among the baseline's PASSED nodes (a witness dropped by a filter, path, marker or
parametrize id can neither kill nor reveal that it could not), and no pending marker hides the result
(`xfail(strict=True)` turns a real failure into a false SURVIVED; neutralize such markers explicitly and
clear inherited options). The recipe that produced a recorded kill, including any overlay of a planned
fix and any marker bypass, is part of the evidence (`lessons/PLATFORM-EVIDENCE.md`).

### 9.8 Reproducible platform evidence

When second-platform evidence materially supports a review, closure or certification, record enough of
the environment that another reviewer can reproduce it without reconstructing the setup from chat: the
image or distribution and architecture; language and runtime versions; kernel or capability
assumptions; required system packages and pinned toolchains; exact commands and environment variables;
mounted paths and repository setup, including line-ending normalization; platform-specific skips;
expected test and witness counts. Prefer a committed script to prose. A missing prerequisite is
disclosed as such and is never reported as a passing gate (`lessons/PLATFORM-EVIDENCE.md`).

**Gate runs do not share host load.** Complete gate batches run **sequentially** on a host; no other
gate batch or container build runs concurrently. A result produced under concurrent load is re-run in
isolation, not credited, pass or fail alike, and the evidence record says so.

**Local storage stays inside the project roots.** Every file a gate, probe or control creates goes
under a project root named in the profile's `repos`/`environment`: worktrees, scratch and disposable
copies, temp directories (`TMP`, `TEMP`, `TMPDIR`, test tempdirs and pytest base temps), build caches
and targets, package caches. Agent-home scratch locations are not used for builds. Each agent keeps one
sourced environment file (profile `environment`) that sets all of these. Containers bind-mount
project-root directories and use a private tmpfs for their temp directory, never named volumes; a
Windows bind mount lacks the POSIX semantics some fixtures need. Check free space before a long batch;
a gate failure caused by a full disk is environmental: free space, re-run, disclose. Delete only scratch
you created; anything else needs the Owner.

**Containment.** Scripts, probes, tests and controls that write, rename or delete paths computed at
runtime create their sandbox strictly inside a project root, assert containment (lexical resolution,
then the real path through links) on every target before every destructive or writing operation
including rename destinations and cleanup, never take `..` chains, drive-relative forms, bare drive
letters, UNC or absolute paths as destructive targets, and fail closed. Destructive probe matrices are
reviewed for target containment before their first run; an unexpected result means stop and
investigate, never rerun. A change outside the project roots needs the Owner's explicit confirmation
before it happens (`lessons/CONTAINMENT-2026-10-10.md`).

## 10. Cross-language contract hazards

Review these explicitly whenever relevant: missing vs `null` vs `false` vs empty values; required vs
optional fields; exact enum/string serialization and canonical case form; integer width/sign behavior;
deterministic ordering; arbitrary JSON/schema round-tripping at dynamic boundaries; message-role unions
and variant coverage; IDs and identity rules; timestamps and generated values; async/cancellation/
callback semantics; lifecycle/disposal ownership; whether an implementation-specific mechanism has
leaked into the shared contract; floating-point special values and language-specific numeric coercion;
whether a test double's own timing simulation can manufacture drift a real clock would never produce.
The runtime-value hazards are enumerated member-by-member in `hazards/hazard-families.md` and audited
per WP in the feasibility matrix (§4.1.1).

Implement the semantic contract, not the other language's mechanics. For async/callback semantics,
describe observable scheduling boundaries language-neutrally; do not encode one language's primitives
into the contract unless the primitive itself is part of the observable API.

**Floating-point tolerance is never added to production arithmetic to compensate for a test double's
own drift, no matter how narrowly the call site is scoped.** Fix the double instead, and before adding
any epsilon enumerate every reachable code path that produces the tolerated value, not just the one the
failing test exercises (`lessons/PROV-010.md`).

## 11. Coordination model

The coordination backend (profile `coordination.backend`) is the shared surface for all parties. Three
distinct durable objects:

```text
coordination issue / state record = active workflow/control state
open PR(s)                        = current durable candidate / handoff object
default branches                  = latest accepted project milestone
```

Assurance artifacts explain why a milestone is accepted. Chat and local working state never substitute
for these objects.

### 11.1 Coordination issue per active work package

One coordination record per **active work package** (§4.2), in the coordination repository
(`coordination.repo`) or state directory (`coordination.path`); a layer MAY also have one umbrella
record. The record contains one machine-readable current-state block in the **exact canonical schema**
of `coordination-state.md` (`templates/coordination-issue.md`); there is only one normative shape. The
block is the **current control state**. Comments and assurance records are historical event/evidence
records and are never the primary source of current ownership or status when the block exists. Agents
hand off directly through this control plane; the Owner does not translate routine review feedback. A
receiving agent fetches the record, candidate PRs, review comments and review artifacts directly.

#### 11.1.1 Current-state update rule

Whenever `status`, the current candidate SHA(s), the open finding set, `next_owner`, `next_action`, a
governance dependency or a deferred closure trigger changes, the current-state block MUST be updated.
Do not leave a stale body and rely on a later comment to override it.

Treat the body as one multiline document when reading and writing it. Tooling MUST NOT round-trip it
through a line array, whitespace join, argument expansion or other transform that can flatten the
fenced YAML or alter scalar content; this rule is transport-agnostic (`lessons/STATE-BODY-FLATTENING.md`).

**Coordination state commit rule.** A state mutation is not committed merely because the write command
succeeds. It becomes authoritative only after, in this order: (1) constructing the intended next
canonical workflow object; (2) validating it locally against the schema; (3) writing the body; (4)
re-fetching it; (5) extracting and parsing the state block with the canonical schema; (6) verifying that
the complete re-fetched object is semantically equivalent to the intended object, not merely equal on a
subset of fields; (7) only then treating the mutation as committed and performing any dependent
handoff, merge, close or certification. The post-write remote check is part of committing the
transition, not an audit that follows it. The equivalence check is schema-aware, not byte-for-byte
Markdown equality, but a difference anywhere in control-critical state fails it. Named diagnostics
(`status`, candidate SHA(s), the open-finding set, `next_owner`, `next_action`, governance source,
deferred trigger, quarantine state, convergence/checkpoint and closure metadata where applicable) are
surfaced for readability and do not replace step 6.

**A failed post-write check is a failed state commit, not a warning.** Treat the mutation as FAILED;
perform or authorize no downstream action whose authority depends on it; repair the remote body from
the last known-good canonical state plus the intended delta; re-fetch; re-run the full equivalence
check; proceed only after the remote state passes. `minion-process apply` implements this rule.

#### 11.1.2 Exactly one active owner

For active states there is exactly one `next_owner` and one concrete `next_action`. For the passive
state `WAITING_FOR_TRIGGER` they MAY be `none`; `deferred_trigger` MUST be present and binding (§11.13).

#### 11.1.3 Work-package states

Allowed `status` values and their intent (`coordination-state.md` §3 defines the shape):

`SCOPING` read-only audit and boundary definition; no implementation authorization. A scoping-only WP
(`requirements: []`) closes directly from here once its scoping artifact is independently approved and
merged (`coordination-state.md` §10.3). `CONTRACT_DRAFT` the shared contract/evidence is being authored.
`CONTRACT_REVIEW` independent review of the proposed contract. `PYTHON_IMPLEMENTATION` the
first-language owner implements an approved/checkpointed contract. `IMPLEMENTATION_REVIEW` independent
review of implementation plus permanent evidence. `REMEDIATION` narrow correction of review findings
before convergence has triggered. `CONTRACT_CONVERGENCE` repeated/coupled semantic defects are being
characterized and closed through §11.8. `FINAL_CONTRACT_REVIEW` the candidate changed since the first
`IMPLEMENTATION_REVIEW`; one complete exact-SHA review of that changed candidate is pending; not used
for a clean first review (§11.4). `RUST_IMPLEMENTATION` the second-language implementation against the
merged approved contract. `CLOSURE_REVIEW` cross-language closure verification. `WAITING_FOR_TRIGGER`
deferred parity is valid and nothing is authorized until a named event occurs (§11.13). `CLOSED`
durably complete for its disposition; for a WP that certifies requirements, `CLOSED` requires its
**status sync** (manifest rows, spec status lines, registry) merged first
(`lessons/L0506-D004-STATUS-SYNC.md`). `INCIDENT` retained for forensic history; not actionable.
`INVALID_UNAUTHORIZED` created or mutated outside valid authorization; quarantine semantics (§11.12).
`BLOCKED_FOR_OWNER` a governance decision is required (§11.7, §11.10).

The state names `PYTHON_IMPLEMENTATION` and `RUST_IMPLEMENTATION` denote the first and second language
of the profile's `implementation_order`; renaming them is a schema change (`coordination-state.md`).

#### 11.1.4 Lean current state

The state block holds current state only: the current candidate, open blockers, dependencies, next
owner/action, the active convergence/checkpoint, the governing source. History moves out to assurance
records or comments linked from `history.assurance_index` (`coordination-state.md` §13). A body over the
lean budget, or history-shaped keys, draws a warning from `minion-process validate`. Migration of
existing records is incremental and preserves provenance.

### 11.2 PRs are candidate and handoff objects

Every substantive pass is pushed to a remote branch and represented by a PR before another agent is
asked to review or continue it. Use short-lived branches named by work package and purpose (`layer/08-
python-shared`, `review/08-rust-contract`, `remediate/08-python-pass2`, `converge/08-agent-events`), not
permanent agent branches. When several repositories change, use paired PRs and cross-link them; each
description identifies the WP, companion PR, coordination record, exact candidate head SHA, pass type
and stop condition (`templates/handoff.md`). Work-in-progress PRs stay Draft until ownership transfers
to an independent reviewer.

#### 11.2.1 Review evidence packaging

A separate docs PR is not required for every review event. Prefer one candidate PR pair, one durable
review ledger/assurance record and coordination event comments over a branch per review round. Create a
separate assurance PR when normative/process/assurance source files are intentionally changed, when the
review artifact must become part of the accepted milestone, when a convergence checkpoint needs durable
repository content before implementation, or when repository policy requires it. Otherwise a SHA-bound
review record attached to the coordination record or PR suffices if it contains reviewer role,
candidate SHA(s), authority revision, scope, findings, witness links, verdict and next transition
(`templates/review-record.md`). At certification, summarize material intermediate evidence into the
final assurance record. Do not reduce evidence quality; reduce redundant repository objects.

### 11.3 Exact-SHA review invariant

An independent **final approval** approves the exact remote candidate SHA(s) it reviewed. If the
candidate head changes, the previous final approval is stale and a final re-review is required. A
reviewer fetches and verifies the referenced remote SHA before starting and never approves prose
descriptions of unavailable or local-only state. Intermediate targeted finding closure under §11.8 is
not final approval and does not waive this invariant for the final complete review.

### 11.4 Standard work-package ownership flow

```text
SCOPING -> CONTRACT_DRAFT -> independent CONTRACT_REVIEW -> checkpoint / approval for implementation
   -> PYTHON_IMPLEMENTATION -> IMPLEMENTATION_REVIEW
        no blocking findings  -> approved clean exact-SHA candidate -> merge
        blocking findings     -> REMEDIATION -> trigger §11.8 (A/B/C)?
                                     no  -> IMPLEMENTATION_REVIEW (targeted re-review)
                                     yes -> CONTRACT_CONVERGENCE: characterize + challenge -> checkpoint
                                            -> coherent fix pass -> negative-control witness gate
                                            -> TARGETED REVIEW -> all blockers provisionally closed
                                 both -> targeted closure reached -> FINAL_CONTRACT_REVIEW
                                      -> ONE complete exact-SHA independent review -> merge
   -> RUST_IMPLEMENTATION -> CLOSURE_REVIEW -> CLOSED -> workflow retrospective
```

If an ordinary `IMPLEMENTATION_REVIEW` re-review still finds blocking issues, return to `REMEDIATION`
and re-check triggers A, B and C against the finding's now-larger history before another pass; do not
merge from a re-review that still has blocking findings, and do not treat a still-open re-review as a
`FINAL_CONTRACT_REVIEW`.

After ordinary `REMEDIATION`, the following `IMPLEMENTATION_REVIEW` is normally a **targeted
finding-closure review**, scoped to the blocking findings being remediated, the semantic dependencies
touched by the fix, and previously-closed high-risk regressions affected by the change. It SHOULD NOT
repeat a complete review unless the reviewer records a concrete blast-radius reason. Once the
remediation findings are closed, `FINAL_CONTRACT_REVIEW` performs the one complete independent
exact-SHA review of the changed candidate: *initial complete review → findings → remediation → targeted
closure → one final complete review*. Convergence's stricter targeted-closure rules (§11.8.7) are
unchanged; neither path weakens independent review or §11.3.

The second implementation starts from the merged approved shared contract, never from an unapproved
candidate branch. A WP MUST NOT move from `CONTRACT_CONVERGENCE` to a complete final review while a
known convergence finding remains open. A **mechanical** WP (§4.3) follows draft → independent review
→ remediation → targeted closure → final review of the changed candidate; it has no convergence
episode, and a trigger firing on it upgrades its class instead (`routing.md` RT-5). `FINAL_CONTRACT_REVIEW` is for a candidate that CHANGED after
the first `IMPLEMENTATION_REVIEW`; a truly clean first review merges directly without a second full
review of the same content.

### 11.5 Default branches are accepted milestones

The default branches named in the profile's `repos` are accepted milestone branches, not work branches.
A layer is not cross-language `CLOSED` merely because implementation exists on a branch or PR; closure
is durably represented in default-branch state and assurance evidence.

### 11.6 Merge policy

Follow the repository ruleset: PR required, conversation resolution required, squash merge, linear
history, force pushes and default-branch deletion blocked. Formal approval count may remain `0` while
the agents lack reliably distinct GitHub identities; procedural independence is still mandatory.

### 11.7 Owner role

The Owner is governance authority, not the routine merge bottleneck. Escalate for intentional
divergence, authority-baseline changes, genuine lower-layer reopen decisions, unresolved agent
disagreement, design/layer-boundary changes, destructive history operations or ruleset bypass, and
release-level governance. Routine review/remediation handoff proceeds agent-to-agent without Owner
relay.

**Standing delegation.** When the profile names a `delegation.source`, the Owner has delegated routine
workflow governance to the coordinator; that durable record is the authoritative text. Within its scope
the coordinator decides and durably records routine transitions without a fresh Owner response:
exact-SHA merges after an APPROVED independent review with no blocking findings; merge ordering;
progression to the next language or phase once the process-defined gates pass; targeted remediation
that implements an agreed contract or decision; documentary/status-only corrections; `CERTIFIED` /
`CERTIFIED_CLOSED` declarations and coordination closure once every predefined gate passes;
non-blocking follow-up issues; ordinary handoffs. The delegation never weakens implementer-reviewer
separation, exact-SHA approval (§11.3), negative controls (§11.8.7.1), convergence checkpoints, required
final complete reviews, default-branch verification (§12) or the canonical round-trip. The Owner-only
list in the delegation governs escalation; only the Owner amends or revokes the delegation.

**Routing by rule.** When the profile says `delegation.routing: true`, the Owner has extended the
delegation to the routes of `routing.md` (`RT-1`–`RT-6`): the coordinator takes the route and records
it with its rule ID in `history.routes` instead of asking. `RT-6`, the convergence trigger, is
notify-and-proceed, never silent. The Owner-only list stays open-ended and includes consequence-class
downgrades, remote creation, risk acceptance and amending the delegation itself. With
`delegation.routing: false` the coordinator asks as before.

### 11.8 Contract convergence protocol

The remediation/re-review loop is intentionally strict, but it MUST NOT become an unbounded
semantic-discovery loop. Enter `CONTRACT_CONVERGENCE` when any of:

```text
A. the same material finding survives two independent reviews;
B. the same semantic root-cause surface produces two successor findings after remediation, even when the finding IDs differ;
C. the work package accumulates three rejected complete contract reviews;
D. the reviewer and implementation owner agree that the remaining blockers form one tightly-coupled semantic surface.
```

A is finding-specific, B root-cause/surface-specific, C work-package-wide, D an early opt-in; do not
reinterpret one as another. Entering convergence is a workflow decision: it does not weaken fidelity,
reopen certified semantics or change the taxonomy.

**The trigger check is mandatory, not advisory.** Before a new ordinary remediation pass, the
remediation owner explicitly checks A, B and C against the finding's own review history, root-cause
surface and the WP's rejected-review count, and states the result ("R003 has survived one independent
review, so A has not fired; …"). Being at two surviving reviews is A fired, not "approaching". If a
trigger is met, convergence is the default; another point-fix pass requires stating why. Do not weaken
the thresholds (`lessons/L08-TRIGGER-CHECK.md`). Where routing is delegated (`routing.md` RT-6), a fired
trigger is recorded with its counters and **notified to the Owner with the default route**; the
coordinator proceeds on that default unless the Owner objects within the round. On a mechanical WP a
fired trigger upgrades the class to governing first (RT-5).

#### 11.8.1 Objective and episode tracking

Stop discovering one semantic edge per implementation pass: freeze unrelated work; define the
remaining surface completely enough to implement once; convert every open finding into discriminating
acceptance evidence; agree contract/evidence before another large pass; use targeted closure until all
blockers are provisionally closed; then one final complete exact-SHA review. Each episode has a stable
ID (`CE-<wp>-<nn>`) and an accumulating record (`templates/convergence-record.md`) across its lifetime,
including successor findings folded in under B. Refined characterization of a finding is not a new
finding.

#### 11.8.2 Coordination state

Update the WP's state block (`status: CONTRACT_CONVERGENCE`, `convergence.episode`,
`root_cause_surface`, `open_findings`, `next_owner`, `next_action`), never a second competing format.
Exactly one owner acts at a time; convergence is collaboration through durable artifacts.

#### 11.8.3 Characterization pass

Normally the reviewer who discovered the repeated defect produces the compact convergence artifact
(open findings, authority symbols/tests audited, observable rules, behavior matrix, minimal executable
witnesses, current candidate failures, normative deltas needed, implementation constraints,
out-of-scope behavior). For concurrency surfaces, enumerate the discriminating dimensions. Add pinned
characterization probes (§9.3). This is contract/evidence characterization, not implementation.

#### 11.8.4 Challenge pass

The shared-contract owner independently reviews the characterization before coding: is the authority
mapping correct; is the matrix complete enough to distinguish realistic wrong implementations; are any
cases mechanics rather than observable semantics; does a proposed fix silently reopen a certified lower
layer; can every implementation language implement the rule idiomatically; does the defect's root cause
depend on an extensibility point that only one language's certified lower layers expose, so that one
side may need nothing (`lessons/L09-REENTRANT-OBSERVER.md`); are all previous findings represented by
an acceptance criterion. Disagreements resolve against the pinned authority and §3; escalate only for
§11.7 cases.

#### 11.8.5 Convergence contract checkpoint

A genuine two-party barrier (`templates/convergence-record.md`): the characterization/implementation
owner writes `PROPOSED FOR IMPLEMENTATION` with open findings, acceptance witnesses, normative deltas
and the independent reviewer as next owner; the reviewer reviews EXACTLY that proposal and returns
`APPROVED` or `REJECTED` with the missing semantic dimension; only on `APPROVED` does the record become
`AGREED FOR IMPLEMENTATION`. No new status value; this is checkpoint metadata within
`CONTRACT_CONVERGENCE`. An agent MUST NOT write `AGREED FOR IMPLEMENTATION` itself and MUST NOT
implement in the same uninterrupted pass as its own proposal (`lessons/CE-L12-PY-01-01.md`). This is not
final approval; it means both agents agree the remaining surface is characterized enough for another
attempt.

#### 11.8.6 Implementation pass

Remediate the agreed surface in one coherent pass: implement against the agreed matrix, not only the
latest comment; convert reviewer witnesses into permanent regression evidence; keep spec/manifest/
conformance synchronized; rerun directly affected previously-closed findings; avoid unrelated cleanup;
push the candidate and update exact remote SHAs.

#### 11.8.7 Targeted convergence closure is mandatory

After a convergence implementation pass the reviewer performs a targeted finding-closure review scoped
to the open convergence finding(s), the semantic dependencies touched by the fix, and previously-closed
high-risk regressions affected. A complete review MUST NOT be substituted merely because the SHA
changed; it is permitted before all findings are provisionally closed only with a recorded reason that
the remediation changed semantic surface outside the checkpoint. A successful targeted review records
`<ID> PROVISIONALLY CLOSED @ <candidate SHA>`, which means discriminating evidence at that candidate per
§11.8.7.1, not final approval. If a finding remains open, the reviewer provides a new or refined
discriminating witness, never a restatement.

##### 11.8.7.1 Negative-control gate for discriminating witnesses

Before a blocking executable finding is `PROVISIONALLY CLOSED`, its permanent witness demonstrates
both `known-bad behavior -> FAIL` and `candidate behavior -> PASS`. The control may revert the fix in a
temporary worktree, run against a known-bad prior SHA, substitute a deliberately incorrect
implementation at the seam, or use another deterministic mutation reproducing the defect. The record
states finding ID, method, known-bad mutation/SHA, expected failure, observed failure, candidate SHA,
observed pass (`coordination-state.md` §7). A test that passes only on the candidate is supporting
evidence, not a closure witness. Documentary-only findings record `NEGATIVE_CONTROL NOT_APPLICABLE`
with the reason.

#### 11.8.8 One final complete review per settled episode

Once every blocking finding is provisionally closed: freeze one exact remote SHA pair; run the complete
gates; transition to `FINAL_CONTRACT_REVIEW`; perform **one** complete independent review of that exact
candidate; if approved, apply the exact-SHA merge gate. If the final review finds a new blocker that is
demonstrably outside the settled root-cause surface (Case A), route `FINAL_CONTRACT_REVIEW ->
REMEDIATION -> IMPLEMENTATION_REVIEW (targeted) -> FINAL_CONTRACT_REVIEW` without re-running
characterization. If it exposes another coupled surface or invalidates the matrix (Case B), open a new
episode. A changed SHA alone is never a reason for a complete review before targeted closure is done.

#### 11.8.9 No weakening of independence

The authority remains the source; shared spec/conformance remain language-neutral; no implementation
becomes another's oracle; review does not prescribe the other language's mechanics; final approval
stays independent and exact-SHA-bound; the second implementation begins only after the shared contract
is approved and merged. The improvement is earlier characterization, not reduced strictness.

#### 11.8.10 Checkpoint invalidation on repeated targeted-closure failure

If the same material finding fails TWO targeted convergence-closure reviews after an `AGREED FOR
IMPLEMENTATION` checkpoint, implementation stops; the checkpoint is presumed inadequate. Before a third
attempt: return to characterization/challenge; identify the unmodeled dimension; independently
re-review the revised checkpoint; obtain a new explicit `AGREED FOR IMPLEMENTATION`. The count is per
material/root finding, not per renamed ID. The rule applies only once convergence exists
(`lessons/CE-L12-PY-01-01.md`).

#### 11.8.11 Cross-language revalidation on shared-semantics discovery

If implementation or review of language B (a) discovers a new shared semantic requirement, (b) reveals
that an existing one was materially mischaracterized, or (c) produces new discriminating evidence that
an already-certified implementation does NOT satisfy an existing, correctly characterized requirement,
then an already-certified language A does NOT remain automatically certified for the AFFECTED surface:
it becomes `REVALIDATE_REQUIRED` until its own owner checks it against the revised contract and new
witnesses. Trigger (c) never makes a certified implementation's behavior a competing authority;
reopening the contract itself still takes §11.10. Revalidation is scoped narrowly to the affected
requirement IDs with the exact reason recorded; the certifying review stays valid history (§11.14)
(`lessons/CE-L12-PY-01-01.md`).

### 11.9 Subagent and background-agent capability boundary

`READ_ONLY AGENT MEANS READ_ONLY CAPABILITY.` A subagent, fork or background agent assigned read-only
work MUST NOT be given or exercise authority to create, update or close issues or PRs, push, commit,
edit spec/manifest/assurance content, change any coordination field, emit a handoff signal, merge,
claim certification or claim Owner approval. Prompt wording is not an authorization boundary: launch
without write credentials where possible; otherwise tell the subagent any remaining write capability is
unusable, and the launching agent verifies afterwards that no writes occurred before treating the output
as authoritative. A subagent's self-report is not evidence.

### 11.10 Governance-decision provenance

An agent may say "Owner approved/decided" ONLY when it can cite an explicit governance record for that
exact decision: an Owner message in the controlling conversation once durably recorded into project
coordination/assurance evidence, or an existing governance record in the project's artifacts that
names and scopes the decision. Record `GOVERNANCE_SOURCE` with artifact, exact decision and exact scope.
A decision under the standing delegation is recorded as `standing_delegation: <source>`,
`delegated_decision: <record>`, `scope: <WP / PR / transition>` and is never described as an Owner
decision on that item. Without a source, report `STATUS BLOCKED_FOR_OWNER / NEXT_OWNER Owner`. Never
infer approval from a recommendation, an architectural preference, the existence of a draft, another
agent's unverified statement, silence, or the word "Recommended" on a menu option: a question to the
Owner becomes a decision only when the Owner answers it, and that answer is durably recorded before
anyone acts on it.

### 11.11 Handoff validation

Before treating a coordination record, PR or SHA as eligible for review, implementation or handoff,
verify: the record is OPEN and valid; the status is not `INVALID_UNAUTHORIZED` / `INCIDENT` /
`BLOCKED_FOR_OWNER`; `next_owner` and `next_action` are present; referenced PRs are open/current where
the status claims; candidate SHAs are remote-reachable; any governance-dependent choice carries a valid
`GOVERNANCE_SOURCE`; the candidate is not derived from a quarantined artifact. Any failure is
`HANDOFF_BLOCKED` and nothing begins from that handoff (`minion-process handoff-check`).

**Reviewer environment loss is `HANDOFF_BLOCKED`, not a verdict.** A reviewer who loses the environment
the review needs stops and reports the missing capability, issuing no partial approval or rejection.
The author records the block and routes it to the Owner; once access is confirmed, the author
re-dispatches the **unchanged** candidate.

### 11.12 Quarantine semantics

An artifact produced outside its author's actual authorization, or resting on a false governance claim,
is `QUARANTINED_ARTIFACT`: it may be preserved for forensic history; it must not be merged, reviewed as
a candidate, cherry-picked, used as evidence, used for certification, or used as a base. Mark the
record's title and body with a governance-correction notice above the preserved content, close without
merging, keep the branches until the retrospective and hardening have landed. A useful observation
inside a quarantined artifact is RE-DERIVED independently before it is relied on.

### 11.13 Deferred parity and trigger-based work

A requirement may remain deferred (`WAITING_FOR_TRIGGER`) when its disposition is `deferred parity`,
the reason is integration readiness rather than semantic uncertainty, a concrete closure trigger is
recorded (`deferred_trigger`), and no implementation is authorized; `next_owner`/`next_action` are
null. When the trigger fires: create or reactivate a normal WP; fetch default-branch reality; perform a
fresh contract-first authority audit; do not resume from the historical audit; consume certified
lower-layer requirements normally.

### 11.14 Current state versus historical event log

Current state (the state block) is mutable and kept current. History/evidence (comments, review
records, assurance, PR timeline, commits) is append-only; a prior rejection is never rewritten into an
approval; a later comment never silently supersedes a stale state block; readers read current state
first and use history to validate it; historical assurance stays durable evidence after the block
advances.

### 11.15 Parallel work and dependency edges

The rule is one active owner per work package, not one active WP in the project. When WP-A waits on
one agent and WP-B is semantically independent and owned by the other, the idle agent SHOULD progress
WP-B. Each state records its dependency edges (`dependencies`: `blocked_by`, `independent_of`,
`shares_artifact`). Never edit the same shared semantic artifact in two WPs concurrently; for
`shares_artifact` pairs parallelize only read-only characterization and serialize the edits; a
`blocked_by` WP may still do read-only characterization that does not presuppose the blocking outcome.

### 11.16 Workflow mechanics tooling

Deterministic workflow mechanics use `minion-process` (`design/minion-process-cli-design.md`) instead
of per-agent scripts: state validation; the §11.1.1 commit round-trip (`apply`); transition legality;
handoff validation; exact-head merge with post-merge containment; byte-verified history comments;
profile validation. The tool decides only mechanical legality. It never decides semantics, never
records a verdict on its own, and never approves. Every close, merge and comment is gated on the tool's
exit status.

### 11.17 Completion notification between agent sessions

Agents run as separate interactive sessions (panes). A work item handed from one to the other ends with
a **completion notification**, so the loop continues without the Owner relaying it. **When:** on
hand-back, completion, `HANDOFF_BLOCKED`, `BLOCKED_FOR_OWNER` or a needed decision, and only after the
durable state is pushed and verified (PR heads, the coordination update, any verdict comment). **How:**
a short ASCII prompt to the receiving pane naming sender, work item, state and the durable pointers;
pane identities belong to the environment (profile `agents.*.default_pane` are defaults; the reply-to
pane is stated in each dispatch). **Every dispatch asks for it** and names the sender's pane. **It is a
wake-up, not evidence:** the receiver re-reads remote reality (§12.2) before acting; a notification
never carries an approval, a verdict or Owner authority. **Dispatch discipline:** send once, verify
delivery by reading the pane, never re-send blindly; never send Enter or any key to a pane that is
blocked or showing a question or permission dialog, and never type or relay an approval code
(`lessons/CONTAINMENT-2026-10-10.md`). Polling the other session or the expected artifact is the
fallback for a lost notification, not the primary signal.

## 12. Repository and remote-state discipline

### 12.1 The remote is the durable project state

The repositories are the shared durable system of record for implementation progress, review handoffs
and milestone status, because every participant can inspect them. This does not change semantic
authority. Local working trees, branches and local-only commits are execution state. A pass that
changes code, shared artifacts or assurance is not ready for cross-party handoff until its commits are
remote-reachable.

### 12.2 Start every pass from remote reality

Fetch all with prune; identify the actual default branch and remote HEAD; record local and remote HEADs
separately when they differ; inspect status and divergence before editing; preserve unrelated and
untracked work; never reset or overwrite unrelated work to match an old instruction SHA. Do not infer
progress from chat history, stale handoff text or local-only commits when the remote says otherwise.

### 12.3 Commit and push every completed pass

Before reporting a pass completed, reviewed, remediated, approved, certified or ready for another agent:
run the required gates; review the final diff; commit task-owned changes coherently; leave unrelated
changes untouched; push; verify every SHA in the report is remote-reachable; report the remote ref and
exact SHA(s). Never hand another agent a local-only SHA. A local-only commit is marked
`REMOTE_SYNC_BLOCKED / LOCAL_ONLY` with the reason; if push fails (credentials, permissions, network,
protection, tooling), claim no durable completion, preserve the local commits, report the failure and
local SHA(s), mark the pass `REMOTE_SYNC_BLOCKED` and stop at the handoff boundary. Never force-push or
rewrite shared history unless explicitly authorized.

### 12.4 Branches, PRs, and milestone visibility

Follow the repository's branch/PR policy. Pushing a branch makes a candidate state durable; the report
states remote branch, remote SHA, PR link and whether it is merged into the default branch. For
milestone checks prefer the default branches plus current assurance. A layer is not cross-language
`CLOSED` while its implementation exists only on an unmerged branch.

### 12.5 Commit discipline

Small, reviewable, semantically coherent commits; review-only evidence separate from implementation
when practical; shared semantic changes coordinated explicitly; evidence-only updates never silently
change semantics; historical rejection/remediation/re-review evidence stays reachable from remote
history.

### 12.6 Machine validation of coordination state

Automation rejects: unknown states; active states without `next_owner`/`next_action`;
`WAITING_FOR_TRIGGER` without `deferred_trigger`; `INVALID_UNAUTHORIZED`/`INCIDENT` attempting a
handoff; candidate SHAs that are not remote-reachable; a changed candidate paired with a stale final
approval; governance-dependent decisions without `governance_source`; a candidate derived from a
quarantined artifact; a transition to `FINAL_CONTRACT_REVIEW` when the candidate did not change since
the original `IMPLEMENTATION_REVIEW`, when a convergence record exists with open or not-provisionally-
closed findings, when the ordinary-remediation route still has blocking findings, or when neither valid
route applies (route detection uses whether a convergence record exists for the candidate, never whether
the episode is "active", `coordination-state.md` §6, §11); a transition to the second implementation
before the shared contract is approved and merged; a provisional closure without its negative-control
evidence (§11.8.7.1). The validator enforces structure only. Every automated body mutation performs the
§11.1.1 post-write re-fetch and full equivalence check, and the re-fetched state passes the validator.

### 12.7 Moving rules from prompts to enforcement

A deterministic rule moves out of natural-language prompts into schema validation, `minion-process`,
CI, generated templates or pre-flight scripts (state shape, legal transitions, exact-SHA and PR-head
checks, round-trip verification, convergence trigger counters, closure prerequisites, negative-control
record fields). The prose rule is shortened **only after** equivalent enforcement exists and is
independently reviewed. Safety and governance checks are never removed ahead of their enforcement. Role
prompts keep what tooling cannot decide: semantic authority, scope ownership, fidelity, review
independence, finding classification and cross-language reasoning.

## 13. Certification gate

Do not certify a layer merely because tests pass. Certification requires, as applicable: authority
audit complete; manifest/spec/conformance complete and mutually consistent; implemented-language tests
green; applicable canonical scenarios green through real seams; assurance evidence recorded; every
finding classified; no active `AUTHORITY_BEHAVIOR_UNCERTAIN`, `AUTHORITY_PARITY_DEFECT` or
`CONTRACT_ASSURANCE_DEFECT`; no unapproved observable divergence; deferred parity/risk explicitly owned
and tracked; all certification/assurance commits pushed and remote-reachable; milestone status on the
appropriate default branch. Approval of a shared contract is not implementation certification; a layer
is not cross-language closed until the required implementations and assurance are complete and durable.
`PROVISIONALLY CLOSED` findings do not satisfy this gate by themselves; final certification requires one
complete independent review of the exact final candidate.

### 13.1 Gate tiers

Verification is tiered G0 (development), G1 (finding closure), G2 (integration), G3 (certification),
with a minimum tier per stage (`gate-tiers.md`). Ordinary remediation needs G0+G1; targeted convergence
closure needs G1 plus the relevant G2; complete-review hand-offs need G3 evidence at the exact
candidate; G3 is author-run evidence, not a review, and certification needs both. Running more is
always allowed; a required escalation records its reason; every hand-off reports the tier actually run
with fresh counts. Gate commands come from the profile's `gates` launchers.

## 14. Workflow improvement and periodic retrospective

The workflow is versioned project infrastructure, reviewed regularly rather than treated as permanently
correct.

### 14.1 When to review the workflow

After each cross-language layer closes; after any repeated rejection/remediation cycle; immediately
when a §11.8 trigger fires; after any handoff failure, stale-state incident, remote-sync problem,
duplicated work or unclear ownership boundary; immediately after any unauthorized agent action or
authorization-control failure (§11.9–§11.12); when an agent repeatedly needs instructions not captured
here; when a new language, tool, provider, CI system or collaboration pattern materially changes how
work is done. A deeper review happens every few layers even without an obvious failure.

### 14.2 What to look for

Which instructions were repeated manually and should become persistent guidance? Which rule was
ambiguous enough for two agents to read differently? Did any agent rely on local or chat state instead
of remote durable state? Did review discover a contract defect only after implementation that could have
been caught earlier? Did a runner or test duplicate production semantics? Did an ownership boundary
cause blocking or duplicate work? Are any checks ceremonial, stale, redundant or missing? Are any
labels, states or stop conditions ambiguous? Did the workflow encourage overlong prompts? Can the same
assurance be achieved more simply or deterministically? Did a remediation test prove the exact review
observation or only a weaker condition? Did the reviewer provide a witness the owner could turn into a
regression test? Should characterization have happened before implementation? Did repeated full
re-reviews add value, or would targeted closure plus one final review have been stronger and cheaper?
Did the WP boundary match the certifiable surface? Did the WP create more artifacts than the assurance
value justified? After convergence fired, were targeted closures used until every blocker was
provisionally closed? Did a final review reopen a settled surface because the matrix was incomplete? Did
every executable witness demonstrate a realistic negative control killed by its intended witness (§9.7)?
Were witnesses event-driven (§9.6) and second-platform evidence reproducible (§9.8)? Was the
neighbourhood re-checked after each fix (§9.4)? Did the state block stay synchronized? Should deferred
work have been `WAITING_FOR_TRIGGER`? Did a design rest on an unexecuted premise, or an oracle restate
the construction (§9.3)? Were mixed compositions characterized (§9.4)? Did any gate run share host load
(§9.8)? Was a closure made without its status sync (§11.1.3)? Were there rounds that produced no new
discriminating evidence?

### 14.3 Improvement rule

When a reusable process improvement is found: distinguish a workflow/process improvement from a
semantic-contract change; propose it against the **kit** (a small PR with the lesson record and, where
mechanical, its replay test) rather than only in the project's own files, so every consumer receives
it at the next pin bump; keep semantic rules in spec/conformance rather than agent instruction files;
add or update automation where a repeated manual check can be made deterministic; commit and push so
all agents receive the same rule; record significant process changes in the project's process-history
artifact when they materially affect certification or handoff behavior. Do not wait for the next failure
once a generalizable improvement is known. A new rule enters this core only with a `lessons/` record.

### 14.4 Do not let process review destabilize active semantics

Workflow improvement must not silently reopen certified semantics. A semantic defect found in a
retrospective is classified with the taxonomy and takes the contract-reopen path; a better way to
coordinate, test, review, report or persist state updates the workflow without changing the contract.

### 14.5 Preferred outcome

The persistent workflow absorbs recurring boilerplate so task-specific instructions get shorter: *long
repeated prompt → recurring rule identified → kit updated → future prompt states only the deltas*. For
repeated semantic-review cycles the healthy trend is *rejection → discriminating witness → convergence
→ provisional closure → one final complete review*, not *rejection → broad implementation pass →
complete review → adjacent edge → repeat*.

### 14.6 Process metrics

Record per work package, in its closure record (`templates/closure-record.md`): review events to
contract approval; complete vs targeted reviews; rounds without new discriminating evidence;
post-contract semantic discoveries; lower-layer deltas discovered after implementation started; Owner
escalations (routing / semantic / risk); documentary/status-only PRs; full-suite (G3) runs; findings
discovered by the hazard families vs ad hoc. These evaluate the workflow, not the agents. The metric to
drive down most is semantic dimensions discovered after implementation begins, without an increase in
escaped defects.

## 15. Standard final report

Unless the task specifies another format, finish with: `STARTING STATE` (actual HEADs and authority
baseline); `AUTHORITY AUDIT` (symbols audited, uncertainty); `FINDINGS` (by taxonomy); `CHANGES`
(shared and language-specific files); `CANONICAL / TEST GATES` (exact fresh results, tier run);
`CROSS-LAYER IMPACT`; `ASSURANCE / VERDICT` (precise status, no overclaim); `REMOTE STATE`
(coordination record, remote refs, remote-reachable SHAs, paired PRs, merge state); `NEW CANDIDATE`;
`NEXT ACTION` (exactly one). In `CONTRACT_CONVERGENCE`, also report the open surface, the agreed matrix
or witness artifact, provisional closure status, and readiness for the final complete review. Respect
the stop condition in the current task. Never continue automatically into the next review,
implementation or layer.
