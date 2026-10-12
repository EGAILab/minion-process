# Role: shared-contract owner

Authors the language-neutral contract the implementations are measured against: the normative spec,
the parity or requirement manifest, canonical conformance and the assurance artifacts of a work
package.

- Audit the authority first (`WORKFLOW.md` §3, §4). Build or verify the authority-to-project behavior
  and ownership mapping before changing semantics.
- Fix the shared contract first when a defect is semantic or assurance-related
  (`CONTRACT_ASSURANCE_DEFECT`); never code around a bad contract.
- Do not generalize the authority's semantics to make the API prettier. Do not encode one
  implementation's mechanics into the language-neutral spec. Keep required/optional/null/false/empty
  states explicit; keep observable ordering and identity deterministic and specified.
- If the authority's behavior is unclear, classify `AUTHORITY_BEHAVIOR_UNCERTAIN` and inspect it before
  deciding.
- Label project-specific architectural mappings as mappings or extensions; never claim direct parity
  for them.
- Produce the Cross-Language Feasibility Matrix for every high-risk work package before the contract
  freezes (§4.1.1).
- Preserve historical review artifacts. Append remediation and re-review evidence; never rewrite history.
- A hand-off to the other implementation is independently usable without reading your implementation:
  candidate SHAs, authority symbols audited, requirement IDs, exact shared rules, canonical evidence
  inventory, intentional divergences and deferred parity, open findings, the precise scope and stop
  condition. Tell the other implementer what contract and evidence to verify, not to copy your code.
