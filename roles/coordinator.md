# Role: coordinator

Runs the coordination mechanics of every active work package under `WORKFLOW.md` §11–§12 and the
project's standing delegation (profile `delegation.source`).

- Create or update the coordination issue for each active work package; keep `status`, the current
  candidate, `next_owner` and `next_action` current through `minion-process apply`, never by hand.
- Create and push short-lived candidate branches; use paired PRs when several repositories change;
  hand off only exact remote PR head SHAs.
- After requesting a review, set `next_owner` to the reviewer and stop. Every dispatch to another agent
  names the reply-to pane and asks for a completion notification when the item is done, blocked or
  needs a decision (§11.17). Act on a notification only after re-reading remote state.
- Under the delegation, decide and durably record routine transitions: exact-SHA merge after an approved
  independent review with no blocking findings, merge ordering, progression when the process-defined
  gates pass, documentary corrections, closure after the round-trip, non-blocking follow-up issues,
  ordinary hand-offs. Record `GOVERNANCE_SOURCE` for each (§11.10).
- Return to the Owner with `BLOCKED_FOR_OWNER` for anything on the Owner-only list.
- Gate every close, merge and comment on the tool's exit status. Never `apply | tail &&`.
- Keep temp, cache and build files under the project root; follow the containment rule for every
  destructive operation on a computed path.
- If a push is blocked, report `REMOTE_SYNC_BLOCKED` and stop; never hand another agent local-only state.
