# Minion-Process

A versioned, project-neutral **process kit** for two-agent coding work: the normative workflow, the
machine-checkable coordination state, gate tiers, hazard families, templates, role texts, the incident
lessons behind every rule, and the `minion-process` CLI that enforces the mechanical parts.

A project adopts the kit through one file, its **profile** (`profile.yaml`), which names the project's
semantic authority chain, repositories, coordination backend, agents and roles, taxonomy aliases, gate
launchers and delegation. Nothing project-specific lives in the kit.

Origin: the Minion-Agent Layers 11–14 / Minion-Memory retrospective
(`docs/origin.md`). First consumer: Minion-Agent. Second: Minion-Memory.

## Layout

```text
WORKFLOW.md                         normative core (project-neutral)
coordination-state.md               the current-state model, invariants, transitions, load boundary
gate-tiers.md                       G0–G3 and the minimum tier per stage
finding-taxonomy.md                 generic finding classes; a profile supplies aliases
authority-dependencies.md           pinned external authority dependencies (verify + execute, never trust)
requirement-id-convention.md        stable requirement IDs as traceability keys
hazards/hazard-families.md          reusable runtime hazard families F1–F7
templates/                          feasibility matrix, hand-off, review record, convergence record, closure record, coordination issue
roles/                              coordinator, shared-contract owner, implementer, reviewer (generic)
lessons/                            incident records by ID, linked from the rules they support
design/                             CLI design and certification-registry design
profiles/                           profile.schema.json and example profiles (the live profile lives in the consuming project)
minion_process/                     the CLI (one code base; backends: github-issue today, state-file planned)
tests/                              offline tests against a fake `gh` (100% statement coverage expected)
authority/                          pinned-authority acquisition scripts and their self-tests
replay/                             incident replay suite (planned, P3)
CHANGELOG.md                        kit versions; a consumer pins one in its profile
```

## Using the CLI

```sh
python -m minion_process profile validate path/to/profile.yaml
python -m minion_process --repo OWNER/REPO status <issue>
python -m minion_process --repo OWNER/REPO validate <issue>
python -m minion_process transition-check CONTRACT_CONVERGENCE FINAL_CONTRACT_REVIEW
python -m minion_process --repo OWNER/REPO handoff-check <issue>
python -m minion_process --repo OWNER/REPO apply <issue> patch.py [--dry-run]
python -m minion_process merge code <pr> <approved-sha>
python -m minion_process comment docs <pr> review.md --pr
```

Requirements: Python ≥ 3.12, `pyyaml`, and an authenticated `gh` CLI for the GitHub commands.
`profile validate` needs neither network nor `gh`.

**Patch files** for `apply` define `ALLOWED` (the top-level workflow keys the patch may change) and
`apply(workflow)` (mutates in place; may return replacement prose).

Tests and lint:

```sh
python -m pytest -q --cov=minion_process      # 100% statement coverage expected
ruff check . && mypy minion_process
```

## Adopting the kit

1. Copy `profiles/example.profile.yaml` to your docs repository as `process/profile.yaml` and fill it in.
2. `python -m minion_process profile validate process/profile.yaml` must print `VALID`.
3. Your role files (`CLAUDE.md`, `AGENTS.md`, …) keep only ownership and environment rules and point at
   `WORKFLOW.md` of the pinned kit version for everything else.
4. A kit upgrade is a version bump in the profile plus the kit's changelog entry, reviewed like any
   process change in your project.

## Status

Version 0.1.0 is the P1 seed: the text of every rule of Minion-Agent's `agent-workflow.md` at
`minion-agent-docs` `dd9fd15` is preserved, either in `WORKFLOW.md` or verbatim in a `lessons/` record
linked from the rule it supports. The `minion_process` package is the Minion-Agent tool at the same
commit plus `profile validate`. The GitHub repository names the tool uses for the `code`/`docs` sides
are still the Minion-Agent ones (`minion_process/github.py`); the profile-driven backend is P3 work.
See `CHANGELOG.md`.
