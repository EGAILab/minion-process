# STATE-BODY-FLATTENING — a multiline state body flattened by shell round-tripping

**Supports:** `WORKFLOW.md` §11.1.1 (one-document writes; the commit round-trip), §12.6.
**Source:** `agent-workflow.md` §11.1.1 and §12.6 at `dd9fd15`, verbatim. The incident narrative is in
`minion-agent-docs` `assurance/process-history.md`.

> Treat the issue body as one multiline document when reading and writing it. Shell and CLI tooling MUST NOT round-trip the body through an implicit line array, whitespace join, argument expansion, or other transform that can flatten the fenced YAML or alter scalar content. The PowerShell/ native-command flattening incident recorded in `assurance/process-history.md` is the motivating example, not the only prohibited failure mechanism; this rule is transport/tool-agnostic.

> Any automated coordination issue-body mutation path MUST perform the post-write remote re-fetch and full semantic-equivalence check defined in §11.1.1's coordination state commit rule -- not merely check the four named diagnostic fields. This catches transport and shell round-trip corruption (for example, a multiline body silently flattened into one line) that local validation cannot observe.

Enforcement: `minion-process apply` (`design/minion-process-cli-design.md` §1; transport-corruption
tests in `tests/`).
