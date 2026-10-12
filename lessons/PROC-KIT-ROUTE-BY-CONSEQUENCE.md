# PROC-KIT-ROUTE-BY-CONSEQUENCE — route by consequence, not by label; measured stage skips

**Supports:** `WORKFLOW.md` §4.3; `consequence-classes.md`; `coordination-state.md` §14.
**Source:** `minion-agent-docs` `process/2026-10-11-reusable-workflow-retrospective.md` (revision 3 at
`752bbb14`), §6.2 and §6.3, verbatim. Review `PROC-KIT-R002` and findings `K1`, `K2`, `K3` of that record
produced these corrections.

§6.2, why consequence and not kind:

> This is the correction review required (`PROC-KIT-R002`, `K1`, `K2`): `requirements: []` describes scope, not consequence, and the process episodes in §2.3 show tooling deciding authority, acceptance and destructive execution.

§6.2, what it changes in practice:

> For `CE-PROC-L13-01`, `PROC-AUTHDEP`, `#256` and `CE-L12D007-01` nothing: each would classify as governing at intake or on its first finding, and each round of those episodes produced new discriminating evidence (§2.3). For a template, a rendering change or a record like this one, the route loses the convergence checkpoint ceremony but keeps independent review and the final review of the changed candidate. The saving is real but smaller than the first draft claimed, and it is bought without dropping a gate that has caught a defect.

§6.2, the signal:

> The round count is not the failure signal; §2.3's episodes were long *and* productive. The signal is a **round that produces no new discriminating evidence**: a review that rejects without a new witness, a new finding or a new matrix row.

§6.3, why stage skipping is narrow:

> Warp's foreman skips Triage and Planning when a request is already well defined. Minion's equivalent is narrower than the first draft proposed (`PROC-KIT-R002`, `K3`): the size of a delta does not predict its hidden dimensions. `L12-D007` entered implementation with an approved contract and integration and then surfaced `L12D007-PY-I001` (rmdir-first), I001 (path-less fallback), I002 (cached child type), I003 (a swallowed child error), and the `CE-L12D007-02` findings C001 (the Windows recovery stage), C002 (an Owner decision) and C003 (the validation stage), three of which needed new normative text. "One additive row with rows already audited" would not have predicted any of them.
