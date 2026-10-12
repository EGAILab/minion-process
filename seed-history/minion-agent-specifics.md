# Seed history — Minion-Agent-specific text that left the core

**Source:** `EGAILab/minion-agent-docs` `process/agent-workflow.md` at
`dd9fd15188d89597fd09a538c2652788604d0d92`, verbatim. **Purpose:** the P1 split (`WORKFLOW.md`) keeps
every rule but replaces Minion-Agent's own names and facts with profile references. This record
preserves those project-specific sentences so the claim "every rule of the seed survives" can be
checked against one file, and so Minion-Agent's adoption PR can confirm its profile carries each one
(`profiles/minion-agent.profile.yaml`). Added for `PROC-KIT-P1-R003`.

| Seed section | Where it lives now |
|---|---|
| Workspace layout, entry points | `profiles/minion-agent.profile.yaml` `repos`, `environment`; the project's role files |
| §1 goal and practical compatibility | profile `authority`; the Owner decision stays in Minion-Agent's docs (`minion-agent#75` comment `5973629428`) |
| §1 adopted Pi revision | profile `authority[0].pin` |
| §2 reading list | `WORKFLOW.md` §2 generic list; profile `authority` kinds |
| §3 authority chain | profile `authority` order |
| §6 finding names | profile `taxonomy_aliases` (`PI_*` → generic classes) |
| §8 shared artifacts | profile `authority` entries of kind `manifest`, `conformance`, `spec`, `design`, `register` |
| §9 canonical behavior families | profile `conformance.families` / `conformance.support` (this record, below) |
| §9.8 local storage rule | `lessons/PLATFORM-EVIDENCE.md` (verbatim) and profile `environment` |
| §11.1 example state block | `coordination-state.md` examples (seeded, text preserved) |
| §11.5 default branches | profile `repos.*.default_branch` |
| §11.7 standing delegation | profile `delegation.source` (`minion-agent#75`) |
| §11.17 pane identities | profile `agents.*.default_pane` |

## Verbatim text

### Workspace layout (preamble)

> **Canonical location:** `minion-agent-docs/process/agent-workflow.md`
>
> ```text
> Minions/Minion-Agent/
> ├── .claude/CLAUDE.md
> ├── .agents/AGENTS.md
> ├── minion-agent/          # code + conformance + parity manifest
> └── minion-agent-docs/     # design + spec + process + assurance
> ```
>
> `CLAUDE.md` and `AGENTS.md` are role-specific entry points. This file is the shared persistent workflow for both coding agents.

### §1 Project goal

> Minion Agent is one product with one language-neutral semantic contract and two first-class implementations.
>
> For Pi-derived behavior, reproduce Pi's observable semantics as closely as practical. Do not replace Pi behavior with a cleaner, more generalized, or more abstract design merely because it is easier to implement. Minion's plugin/runtime architecture may change ownership, registration, lifecycle, composition, and implementation mechanics; it does not by itself justify changing Pi-visible behavior.
>
> **Practical compatibility** (Owner decision, 2026-10-04: `minion-agent#75` comment `5973629428`).
> - Minion targets practical behavioral compatibility with Pi, not exhaustive emulation of incidental JavaScript, Node.js, operating-system or dependency-runtime behavior.
> - Core agent semantics and realistic operational behavior remain parity requirements.
> - The rule applies to unfinished work: WP-13.3, WP-13.4, Layers 14–18, and any lower-layer delta they surface. Already-certified work is not reopened because of it.
> - A divergence is accepted only through §6.1 and Owner governance.
>
> The adopted Pi revision is recorded by the frozen master design. At the time this file was introduced it is:
>
> `b7bb00b936dbe21b8e160b3e89efdec361846699`
>
> If the frozen design later adopts a different Pi baseline, the frozen design wins over this literal SHA.

### §2 Read these before substantive work

> 1. `minion-agent-docs/design/2026-08-20-minion-agent-design.md`
> 2. `minion-agent-docs/process/implementation-conformance-workflow.md`
> 3. `minion-agent-docs/process/coordination-state.md` — the machine-checkable coordination-state schema referenced throughout §11
> 4. the current work package's `spec/**` and `assurance/layers/**` artifacts
> 5. `/pi-parity-manifest.yaml`
> 6. the applicable canonical scenarios under `/conformance/**`
> 7. the adopted Pi source for the symbols being implemented or reviewed
> 8. `minion-agent-docs/process/hazard-families.md` and `process/gate-tiers.md` (§9.5, §13.1)

### §3 Semantic authority

> For Pi-derived behavior:
>
> `adopted Pi source -> parity manifest -> normative spec -> canonical conformance -> implementations`
>
> The frozen master design defines architecture, scope, and the mandatory Pi-fidelity goal. [...]
>
> Python is never the behavioral oracle for Rust. Rust is never the behavioral oracle for Python.

### §6 Finding taxonomy (names)

> - `PI_BEHAVIOR_UNCERTAIN`: Pi behavior is not sufficiently known. Stop the semantic decision, inspect adopted Pi, then update contract/evidence.
> - `PI_PARITY_DEFECT`: Minion differs from known adopted Pi-visible behavior. Fix before certification unless an intentional divergence is explicitly approved.

(The other three names are unchanged in `finding-taxonomy.md`.) An accepted divergence needs "an entry in `assurance/pi-divergences.md`" (profile `authority` kind `register`).

### §8 Shared artifacts

> - `/pi-parity-manifest.yaml`
> - `/conformance/**`
> - `minion-agent-docs/spec/**`
> - frozen design/process documents
> - assurance documents as historical evidence

### §9 Canonical conformance (`PROC-KIT-P1-R003`)

> There are exactly three canonical behavior families:
>
> - `conformance/runtime`
> - `conformance/session`
> - `conformance/agent`
>
> `conformance/schema` is support infrastructure, not a fourth behavior family.

Also in §9: "In particular it must not fabricate queue behavior, ordering, shadowing, message transforms, tool execution semantics, lifecycle, reset behavior, or expected results." and "Valid mocking uses a scripted provider/tool through the real Minion seam." — the core keeps the rule with generic nouns.

### §9.3 Characterization probe location

> ```text
> reference/pi-characterization/<surface>/
> ```

and §9.5: "**Executable harnesses** live under `reference/pi-characterization/families/<family>/` (non-normative, §9.3)."

### §11.1 Coordination issue location

> Create one coordination issue in `minion-agent` for each **active work package** (§4.2), not necessarily one issue for the entire architectural layer.

### §11.5 Default branches

> Use `minion-agent/main` and `minion-agent-docs/master` as accepted milestone branches, not ordinary work branches.

### §11.6 Merge policy (identities)

> Formal GitHub approval count may remain `0` while Claude/Codex do not have reliably distinct GitHub identities. Procedural independence is still mandatory.

### §11.7 Standing delegation

> **Standing delegation (in force).** The owner has delegated routine workflow governance to Claude. The authoritative text is the pinned issue `minion-agent#75`, a verbatim transcription of the owner's decision.

### §11.15 Parallel work (example)

> For example, while Codex implements Rust L0506-D001, Claude progresses the WP-13.3 contract/Pi characterization, and a read-only research agent (§11.9) collects WP-13.4 pinned `fd`/`rg` evidence.

### §11.16 Tooling location

> Deterministic workflow mechanics use `minion-process` (`process/minion-process-cli-design.md`, `process/tools/`) instead of per-agent scripts.

### §11.17 Pane identities

> - Pane identities belong to the environment, not to the contract: each agent reads its own (`HERDR_PANE_ID`) and includes it in its dispatch. As of 2026-10-09, Claude (Python and shared contract) is `w1:p1` and Codex (Rust) is `w1:p2`.

### §14.3 Improvement rule (file names)

> 2. update the appropriate persistent project guidance (`agent-workflow.md`, `CLAUDE.md`, `AGENTS.md`, or normative process docs);

### §15 Standard final report (names)

> 1. `STARTING STATE` — actual code/docs HEADs and Pi baseline.
> 2. `PI AUDIT` — symbols audited and any uncertainty.
