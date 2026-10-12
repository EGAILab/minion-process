# Minion-Process — Reusable runtime hazard families

**Kit file.** Seeded from `minion-agent-docs` at `dd9fd15`, text preserved. "Pinned Pi" is Minion-Agent's authority; read "the pinned authority" for another project.
**Referenced by:** `WORKFLOW.md` §4.1.1, §9.4, §9.5; `templates/cross-language-feasibility-matrix.md`.

A **hazard family** is a recurring language/runtime behavior class whose members must be probed together. Every family here was paid for with a late finding (source column).

**Rules.**
- **When a WP's semantic path touches a family**, the feasibility matrix (§4.1.1) lists every member as a probe point. Each member is characterized against pinned Pi and recorded `AUDITED`, `NOT_APPLICABLE` (with reason) or `DEFERRED_WITH_REASON`.
- **When a review finding hits one member**, the neighborhood-expansion rule (§9.4) requires the whole family to be characterized before remediation is proposed.
- **When a new hazard class is discovered** and is generalizable, add it here as part of that finding's remediation. Add a new member to an existing family, or a new family.
  - *Generalizable* means another WP could plausibly reach the same runtime behavior.
  - The addition is a process change, and it is reviewed with the finding.
- **Families are characterization inputs, not semantic authority.** Pinned Pi remains the source, and the spec/conformance remain the contract (`agent-workflow.md` §3, §9.3).

**Reusable probes.** Where a family has an executable pinned-Pi harness, it lives under `reference/pi-characterization/families/<family>/` (non-normative, §9.3), with a member-per-case layout that a WP-specific probe can import. Until a family harness exists, the WP's own characterization harness enumerates the members from this file.

---

## F1. JS Number

**Source:** WP-13.2 I002 (JSON number beyond binary64), I002-refinement (`-0`), I004 (runtime ±Infinity); L0506-D001 C001, I002 (numeric-looking string).

| Member | Probe |
|---|---|
| normal finite | a representative value survives each boundary unchanged |
| integer ≤ 2^53 | exact |
| 2^53 boundary | 2^53, 2^53+1 (rounds), −2^53 |
| large finite | 1e308, `Number.MAX_VALUE` |
| overflow → +Infinity | `1e309` through `JSON.parse` / arithmetic |
| overflow → −Infinity | `-1e309` |
| +0 | stays `0` |
| −0 | sign preserved at runtime; `JSON.stringify(-0) === "0"` |
| NaN | reachable at this boundary? (only via shim/arithmetic, never via JSON) |
| numeric-looking string | `"Infinity"`, `"NaN"`, `"1"`: never silently a number unless Pi coerces |
| JSON.stringify projection | non-finite → `null`, `-0` → `0`; a diagnostic projection is not a runtime value |
| declared integer vs number | non-finite and fractional in an `integer` position |

## F2. JS String / UTF-16

**Source:** WP-13.2 I003 (valid surrogate pair held as two characters); WP-13.1 read projection; WP132-RUST-C001 / L0506-D002 (a prepared lone surrogate that a binding's string type cannot hold).

| Member | Probe |
|---|---|
| ASCII | baseline |
| BMP non-ASCII | e.g. `é`, `中` |
| astral scalar | e.g. `😀` (2 code units, 1 scalar) |
| explicit surrogate pair | `"\uD83D\uDE00"` built from escapes |
| lone high surrogate | `"\uD83D"` |
| lone low surrogate | `"\uDE00"` |
| lone surrogate position | high and low each at start / middle / end / alone |
| adjacent and reversed surrogates | two highs, two lows, low-then-high, high-then-non-low |
| mixed | a valid pair next to a lone surrogate, in both orders |
| empty / NUL | `""`, `"\u0000"`, NUL in the middle |
| string in a key | an object key carries the same domain (lone surrogates, pairs, empty) |
| schema keywords | `minLength`/`maxLength` count code points; `pattern` is Unicode mode; `const`/`enum` compare code units |
| every observer | prepare, validation, each hook, a hook's replacement, execute: one value, never re-encoded between them |
| length / index / slice units | `String.length`, offsets, `slice`, diff hunks in UTF-16 code units |
| encoding / replacement | UTF-8 encode of lone surrogates (→ U+FFFD), decode of invalid bytes |
| JSON.stringify projection | a lone surrogate is escaped `\udXXX`; a valid pair is emitted as the character |
| provider-outbound projection | Pi's `sanitizeSurrogates` **deletes** unpaired surrogates from outbound text (Layer 11) |
| raw decoding | does wire JSON decoding (`JSON.parse` of an escaped lone surrogate) reach the raw argument type at all? |

## F3. Unicode / ICU

**Source:** WP-13.1 R006 (`ls` collation, 5 revisions), R006-C (pinned ICU profile), FR003 (profile not enforced).

| Member | Probe |
|---|---|
| pinned runtime Unicode / ICU version | the version Pi's Node embeds vs Python/Rust; pinned build identity |
| normalization version drift | NFC/NFD of characters whose composition changed across versions |
| case mapping | locale-sensitive (`İ`, `ß`), `toLowerCase` vs `toLocaleLowerCase` |
| collation | locale, strength, numeric option, ties; `localeCompare` vs byte order |
| characters newer than the pinned version | unassigned in the pinned version, assigned in the host's |

## F4. Async / order

**Source:** WP-13.2 I001 (settle window instead of firing timers; queue witness weakness); Layers 08/09 listener ordering.

| Member | Probe |
|---|---|
| abort before work | already-aborted signal at entry |
| abort during await | abort while suspended at each await point |
| work settles before abort | completion wins |
| error settles before abort | failure wins; which error is observed |
| queue waiter | second operation waits on the first (same key) |
| prior operation fails | waiter proceeds; no per-key residue |
| prior operation aborts | waiter proceeds; ordering preserved |
| timer beyond naive polling interval | completion scheduled later than any fixed settle window (fire timers, don't wait them out) |
| microtask vs macrotask | continuation ordering relative to listeners |

## F5. Error / coercion projection

**Source:** L0506-D001 R001 (diagnostic serialization), I001/C002 (union/callback coercion), I002 (numeric-looking string → `finite_number`); WP-12.E3 C001; WP-13.1 R010 (error projection).

| Member | Probe |
|---|---|
| fixed Pi-authored template | exact text from Pi source |
| raw provider / host text | passed through unchanged vs templated |
| hybrid template + provider text | composition order and separators |
| same Minion error code from multiple sources | every host/runtime condition that yields the code; can a *coercion* produce it from a non-matching value? |
| platform-specific host result | Windows vs POSIX errno/messages |
| coercion vs original value | does a check judge the delivered value or a coerced copy? |
| union / alternative selection | complete-value alternatives in both orders; a mismatched sibling must not exempt another position |
| callback / hook output | values produced after validation (after-validators, hooks) are judged as delivered |

## F6. ECMASCRIPT_OBJECT_ORDER

**Source:** L0506-D002 characterization K1 (`JSON.parse` enumerates array-index keys first); the Owner decision on K1 (`minion-agent#99` comment `5924847773` §11), tracked as `L0206-D001` (`minion-agent#100`).

A JavaScript object enumerates its own string keys in ECMAScript order: **array-index** keys (canonical decimal integers 0 … 2^32 − 2) first, ascending numerically, then the other keys in insertion order. A Python `dict` enumerates in pure insertion order, and a sorted map in key order. A JS-derived surface that hands an object to an observer may therefore differ by binding.

Every JS-derived surface involving object arguments answers, in its feasibility matrix:
1. Does property enumeration order matter here (an observer iterates the object, or output depends on it)?
2. Does a JSON serialization expose it (`JSON.stringify` emits enumeration order)?
3. Do the Python and Rust representations preserve the same order?
4. Are integer-index-like keys possible?
5. Are nested objects affected?

| Member | Probe |
|---|---|
| insertion order | non-index keys only: insertion order everywhere |
| array-index keys first | `{"b":1,"2":2,"1":3,"a":4}` enumerates `1, 2, b, a` |
| index boundaries | `"0"`, `"4294967294"` (largest index), `"4294967295"` (not an index) |
| non-canonical numerals | `"00"`, `"01"`, `"-0"`, `"-1"`, `"1.0"`, `"+1"`: ordinary keys, insertion order |
| nested objects | the rule applies at every level |
| duplicate key | last value wins, at the first occurrence's position (`JSON.parse`) |
| boundaries | raw decoding, prepared value, each hook, execute, every JSON serialization (events, session, provider payload) |
| independence | when no owned output depends on order, a focused witness proves it (permuted orders, identical outputs) |

## F7. SCHEMA_RUNTIME_DOMAIN

**Source:** L0506-D002-R001 (a validation case put a lone surrogate in the **schema**, which the Rust schema seam cannot hold). Owner decision `minion-agent#99` comment `5926416181` §12. Tracked as `L05-D001` (`minion-agent#104`).

The same textual type, "string" or "number", lives in four value domains whose representability can differ by binding. A JS-derived validation or value surface answers each separately:

| Domain | Question |
|---|---|
| INSTANCE | Which values can the prepared/runtime instance hold, and do both bindings carry them losslessly? |
| SCHEMA | Which values can the schema itself hold (property names, `required`, `const`/`enum` literals, `pattern`), what operation does Pi perform on each role, and can each binding's **schema** seam express it? |
| RAW/WIRE | What does wire decoding (`JSON.parse`) produce into the raw value, and can the raw type hold it? |
| SERIALIZED/PROJECTED | What does each serialization boundary (`JSON.stringify`, UTF-8 encoding, provider sanitizing) project, and where exactly? |
| TOOL RESULT (`WP132-RUST-C002`, `L0506-D003`) | Which values can a tool result carry in `content` text and recursively in `details` (leaves, nesting, **keys**, `-0`/±Infinity/`NaN`), and do the after-hook, `tool_execution_end`, `ToolResultMessage` and session replay carry them losslessly? |

The feasibility template (§1.1) splits these into six carriers, separating persistence projection from provider projection.

| Member | Probe |
|---|---|
| schema property name / `properties` key | a non-scalar name; the instance supplies the same name, a U+FFFD look-alike, or nothing |
| `required` entry | present vs absent key with a non-scalar name |
| `const` / `enum` literal | lone surrogate vs U+FFFD vs valid pair vs ordinary scalar |
| `pattern` | what Pi's RegExp compilation accepts and how it matches: not assumed equal to code-unit equality |
| documentary fields | `title`, `description`, `examples`: excluded unless they reach a certified observable |
| canonical-case audit | does any canonical case put a non-scalar value in the schema? If so, its delta must own the schema domain |
