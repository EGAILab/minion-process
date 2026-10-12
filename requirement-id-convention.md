# Minion-Process — Normative requirement ID convention

**Kit file.** Seeded from `minion-agent-docs` at `dd9fd15`, text preserved. The prefixes in §2 are Minion-Agent's; a project chooses its own.
**Status:** ADOPTED by Minion-Agent (2026-08-22) — normative traceability convention for assurance  
**Purpose:** Give stable identities to normative requirements without creating a second semantic authority.

## 1. Principle

Requirement IDs are **traceability identifiers**, not new semantic definitions.

The semantic rule continues to live in the frozen design/spec and, for covered finite examples, in
canonical conformance.

A requirement ID provides a stable join key for:

```text
spec rule
-> Pi parity-manifest row
-> canonical scenario
-> Python implementation
-> Rust implementation
-> assurance evidence
```

## 2. Prefixes

Use subsystem-oriented prefixes:

```text
RT-###      runtime
LLM-###     LLM vocabulary / stream contract
XFORM-###   target-model transformation
SES-###     session / artifacts / reconstruction
TOOL-###    tool model / registry / execution
AGENT-###   Agent state / run-turn lifecycle / queues
PROV-###    provider-specific behavior
HAR-###     harness / skills / compaction / projections
EXEC-###    fs / shell / subprocess execution seams
TEL-###     telemetry / diagnostics
```

Existing parity-manifest IDs such as `AI-001`, `AG-001`, `TOOL-001`, `PROV-001`, and `HAR-001`
remain parity-manifest identities. Requirement IDs do not need to duplicate those exact IDs.

## 3. Where IDs live

Preferred approach: add stable section anchors/headings to normative spec documents.

Example:

```markdown
## AGENT-001 — Run and turn definition

A run is one high-level prompt/continue invocation. A turn is one assistant response plus tool
calls/results caused by it.
```

Then assurance can cite:

```text
Requirement: AGENT-001
Source: spec/agent.md#agent-001--run-and-turn-definition
Parity rows: AG-004
Conformance: turn-lifecycle-order
```

If a spec document has not yet been converted to headed IDs, an assurance report MAY assign a
temporary ID mapped to an exact spec heading/paragraph. The ID must be promoted into the spec before
that layer is certified.

## 4. Granularity

One requirement ID should represent one independently testable normative rule or tightly coupled
rule cluster.

Avoid both extremes:

```text
too broad:
    AGENT-001 = everything the Agent does

too narrow:
    one ID per individual field when the fields form one inseparable schema rule
```

Good examples:

```text
AGENT-001  run vs turn definition
AGENT-002  initial prompt event ordering
AGENT-003  continue() steering/follow-up ordering
AGENT-004  invocation-local agent_end.messages
AGENT-005  active abort propagation

TOOL-001   batch parallel/sequential contagion
TOOL-002   length-stop executes no tools
TOOL-003   extension-boundary failures become tool error results
TOOL-004   terminate suppresses only tool-driven continuation
```

## 5. Stability

Once a requirement ID is used in released/certified assurance evidence:

- do not reuse it for a different rule;
- do not renumber requirements merely for aesthetics;
- mark removed requirements as superseded/retired with a pointer to replacements;
- preserve aliases during migrations where practical.

## 6. Relationship to parity-manifest IDs

Parity rows answer:

> Which Pi source surface produced this compatibility obligation?

Requirement IDs answer:

> Which normative Minion rule are we certifying?

Mapping may be one-to-one, one-to-many, or many-to-one.

Example:

```text
Pi rows:
    AG-004
    TOOL-007

may jointly support:

    AGENT-006 — post-turn continuation ordering
```

Do not force artificial 1:1 alignment.

## 7. Relationship to conformance

Every canonical conformance scenario should map to at least one normative requirement ID once the
owning layer enters certification.

Every normative requirement must have executable evidence:

```text
canonical conformance
OR
explicitly justified language-specific test
```

The conformance scenario name remains its own stable executable identity.

## 8. Adoption sequence

Use this convention before starting `assurance/layers/01-runtime.md`.

Recommended rollout:

```text
1. Add IDs to runtime normative rules
2. Complete runtime assurance/certification
3. Add IDs to LLM rules before LLM certification
4. Continue layer-by-layer
```

Do not stop all implementation merely to renumber the entire spec at once. Requirement IDs should
lead each layer's certification by a small amount.
