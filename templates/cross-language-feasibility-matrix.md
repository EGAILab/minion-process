# Cross-Language Feasibility Matrix — `<WP id>`: `<title>`

**Kit file.** Seeded from `minion-agent-docs` at `dd9fd15`, text preserved.
**Required by:** `WORKFLOW.md` §4.1.1, for every high-risk Pi-derived work package, before its contract may become `AGREED FOR IMPLEMENTATION`.
**Pinned Pi:** `<sha>`. **Author:** `<shared-contract owner>`. **Independent checkpoint reviewer:** `<other agent>`.
**Candidate:** docs `<sha>` / code `<sha>`.

## How to fill this in

- **Silence is not an answer.** Every row, and every checklist item in §3, ends in one of `AUDITED` (with evidence), `NOT_APPLICABLE` (with a one-line reason) or `DEFERRED_WITH_REASON` (with the reason and the trigger or owner).
- **Audit the transitive semantic path**, not just the entry function. Follow the value from the raw wire/source through Pi's preparation, validation, hooks, execution, results and serialization, as far as the WP's observable surface reaches.
- **Use `process/hazard-families.md`.** For each family that applies, copy its member list into the relevant table below. Family members are pre-enumerated probe points; do not re-derive them.
- **A row marked "lossless across all? = NO"** or "representation sufficient = NO" is a *finding*, not a footnote. Classify it with the normal taxonomy (`agent-workflow.md` §6) and resolve it — including any lower-layer extension or Owner decision — **before** the checkpoint.

---

## 1. Runtime value-domain matrix

One row per observable value or field that crosses a layer boundary. Do not assume JSON-domain values and JavaScript-runtime values are identical: `JSON.parse` output, preparation shims, arithmetic and coercions can produce runtime values that no JSON document contains.

| Observable value / field | Pi wire/source repr | Pi runtime repr | Python repr | Rust repr | Canonical/wire serialization | Lossless across all? | Risk / witness needed |
|---|---|---|---|---|---|---|---|
| `<field>` | | | | | | | |

For JavaScript-derived behavior, consider where applicable, and record each as a row or an explicit `NOT_APPLICABLE`:

```text
finite binary64            +0                    -0
large integer rounding     2^53 boundary         largest finite values
+Infinity                  -Infinity             NaN
undefined / missing        null                  false / empty
numeric-looking string     JSON.stringify projection
UTF-16 code units          valid surrogate pair  lone surrogate (high / low)
Unicode normalization / version
```

### 1.1 Value-domain carriers (F7: `L0506-D002-R001`, `WP132-RUST-C002`)

Answer each separately for every validation or value feature. The same textual type does not imply the same representability in every carrier. This is the Owner's list (`minion-agent#49` comment `5937380474` §18):

| Carrier | Pi repr | Python repr | Rust repr | Owning seam | Lossless across all? |
|---|---|---|---|---|---|
| RAW INPUT VALUE DOMAIN (decoded provider `ToolCall.arguments`, `L0206-D002`) | | | | | |
| PREPARED VALUE DOMAIN (prepared/runtime instance, `L0506-D001`/`D002`) | | | | | |
| SCHEMA VALUE DOMAIN (property names, `required`, `const`/`enum`, `pattern`; `L05-D001`) | | | | | |
| TOOL RESULT VALUE DOMAIN (`content` text, recursive `details`: after-hook, `tool_execution_end`, `ToolResultMessage`; `L0506-D003`) | | | | | |
| PERSISTENCE PROJECTION (session log/file: `JSON.stringify`, reload) | | | | | |
| PROVIDER PROJECTION (outbound payloads: provider sanitizing, serialization) | | | | | |

For **every public/runtime value carrier** the WP touches, answer the Owner's six questions in the row:

1. What values can Pi produce?
2. Can Python represent them?
3. Can Rust represent them?
4. What do hooks/events see?
5. How are they serialized?
6. Where is lossy projection actually allowed?

A language-native JSON type (`serde_json::Value`, `String`, Python `json`) is never the semantic authority. It has been narrower than the JavaScript runtime domain four times (raw, prepared, schema, result).

**Canonical-case audit:** list every canonical case whose *schema* holds a value outside the scalar/JSON domain. Each one needs the SCHEMA row answered.

## 2. Lower-layer capability matrix

One row per semantic operation the WP requires. A missing seam must be found **here**, not at implementation. (WP-13.2's combined read+write access check, `EXEC-009`, and its prepared runtime ±Infinity, L0506-D001, were both found late.)

| Required semantic operation | Owning lower layer | Existing certified seam/API | Expresses exact Pi semantics? | Python repr sufficient? | Rust repr sufficient? | New additive extension required? | Non-additive reopen required? |
|---|---|---|---|---|---|---|---|
| `<operation>` | | | | | | | |

- **Additive extension** (a new seam, a new certified requirement): name the extension WP and its dependency edge (§11.15).
- **Non-additive reopen:** this is Owner-only (`minion-agent#75`). Status `BLOCKED_FOR_OWNER` until decided.

## 3. Cross-runtime hazard checklist

Mark every item. `NOT_APPLICABLE` needs a one-line reason; `DEFERRED_WITH_REASON` needs a reason and a trigger or owner.

| Hazard | State | Evidence / reason |
|---|---|---|
| `JSON.parse` (number precision, duplicate keys, `__proto__`) | | |
| `JSON.stringify` (non-finite → `null`, `-0` → `0`, `undefined` omission, key order) | | |
| `Number` conversion / numeric coercion | | |
| `Math` semantics (NaN propagation, rounding, `Math.max/min`) | | |
| negative zero | | |
| non-finite values (±Infinity, NaN) | | |
| `String.length` / UTF-16 code units | | |
| `RegExp` (flags, `u`/`v` mode, lastIndex) | | |
| Unicode / ICU version (normalization, case mapping, collation) | | |
| Array ordering (sort stability, comparator) | | |
| Object property ordering (integer-like keys first) | | |
| Promise scheduling (microtask vs macrotask) | | |
| `AbortSignal` (reason, already-aborted, listener order) | | |
| `setTimeout` / timers (clamping, ordering, fake-clock drift) | | |
| Node/libuv error mapping (errno → code, message text) | | |
| filesystem access semantics (permissions, symlinks, races) | | |
| platform-specific path handling (separators, drive letters, case) | | |
| external package / runtime versions (pinned + integrity) | | |

## 4. Concurrency / order matrix

Required for any async or concurrent WP. One row per operation.

| Operation | Start | Registration point | Lock acquisition | Await points | Abort checkpoints | Failure points | Settle point | Cleanup / release | Observable completion ordering |
|---|---|---|---|---|---|---|---|---|---|
| `<op>` | | | | | | | | | |

For **each material ordering guarantee**, give at least one realistic wrong implementation. It becomes a negative control before implementation starts:

| Ordering guarantee | Realistic wrong implementation | Witness that kills it |
|---|---|---|
| `<guarantee>` | | |

## 5. Neighborhood expansion record

For each hazard family touched (`process/hazard-families.md`), list the members probed against pinned Pi and the resulting rows:

| Family | Members probed | Pi observation source (probe / symbol) | New rows / findings |
|---|---|---|---|
| | | | |

## 6. Verdict

```text
FEASIBILITY
    READY                     every row AUDITED / NOT_APPLICABLE / DEFERRED_WITH_REASON; no open finding
  or
    BLOCKED                   open finding(s): <IDs> (taxonomy, owner, resolution path)
```

The independent checkpoint reviewer verifies this matrix as part of the contract checkpoint (§4.1, §11.8.5). An incomplete matrix is a `CONTRACT_ASSURANCE_DEFECT` against the checkpoint.
