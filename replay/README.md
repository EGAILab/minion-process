# Incident replay suite (planned, P3)

Each mechanical rule in `WORKFLOW.md` will have a replay test here that reproduces the incident its
`lessons/` record describes and shows the rule's enforcement catching it. `profile validate` (or a kit
lint) will fail when a rule marked mechanical has no replay test, so the core cannot drift from its
evidence. Seeded from both consuming projects' lessons in P3/P4.

Until then, the executable evidence for the state model lives in `tests/` (historical-replay tests for
`minion-agent#49`, `#79`, `#88`; transport-corruption tests; the CE-PROC-L13-01 field table and load
boundary).
