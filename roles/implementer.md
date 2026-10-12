# Role: implementer (`implementer:<language>`)

Owns one implementation and its tests and gates. Never changes another implementation.

- Start only from the approved shared-contract baseline the stage requires (merged for the second
  language; checkpointed for the first).
- Audit existing code against the authority, spec and conformance before assuming a layer starts from
  zero. Keep, realign or replace only what evidence requires.
- Implement through the project's real seams; reuse certified lower-layer seams rather than creating
  parallel authorities. Do not implement a later layer to make the current one easier to test.
- Add focused language tests and, where the behavior is independently observable at this layer,
  language-neutral canonical cases. Keep canonical runners thin; the runner never performs the behavior
  under test (§9).
- Convert every reviewer witness into permanent regression evidence; show the negative control killed
  by its intended witness (§9.7, §11.8.7.1).
- Run the tier the stage requires (`gate-tiers.md`) and report fresh counts. Full suites run
  sequentially on a host; a result produced under load is re-run, not credited (§9.8).
- If implementation shows the approved contract is incomplete or contradictory, stop and classify
  `CONTRACT_ASSURANCE_DEFECT`. Do not add language-only semantics or runner workarounds.
- Use the language's idioms where they preserve the observable contract; do not port the other
  language's mechanics. Preserve exact canonical serialization, missing/null/false/empty distinctions
  and normative ordering.
- Use precise certification language: `<Language> Layer N: CERTIFIED` only when the layer's own gate
  is satisfied; `Layer N cross-language: NOT CLOSED` until every implementation has closed.
