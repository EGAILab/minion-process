# Roles

A profile assigns roles to agents (`agents.<name>.roles`). The kit defines four roles; a project's role
files (`CLAUDE.md`, `AGENTS.md`, …) add only ownership paths and environment rules and point here.

| Role | Holds | File |
|---|---|---|
| `coordinator` | the coordination issue, routine governance under the delegation, dispatch and merge mechanics | `coordinator.md` |
| `shared-contract-owner` | the language-neutral contract: spec, manifest, canonical conformance, assurance | `shared-contract-owner.md` |
| `implementer:<language>` | one implementation and its language tests and gates | `implementer.md` |
| `reviewer` | independent review of contracts and candidates at exact SHAs | `reviewer.md` |

One agent may hold several roles. Two roles are never held by one agent for the same candidate:
author and reviewer. An implementer of language A is the natural reviewer of the shared contract that
language B's owner authored, and the reverse.
