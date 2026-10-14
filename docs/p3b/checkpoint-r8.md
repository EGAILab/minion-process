# CE-PROC-P3B-01 checkpoint proposal, revision 8 (base: contract revision 3 + checkpoint revisions 4–7)

**Author:** Claude `w1:p8`. **Status:** PROPOSED. Kit `WORKFLOW.md` §11.8.10 invalidated the revision-7
agreement after Codex round 8 (`minion-process#6` @ `02833f92`): R002, R003, R006 and R010 failed a second
targeted closure. Revisions 4 to 7 stand except where this revision replaces them. These closures are not
reopened: R001, R004 and R007, which hold, and R005, R008 and R009, which are provisionally closed at
`02833f92`.

## The unmodeled dimension

Each of the four failures has the same shape. The checkpoint named the hazard, but it described the inputs
by example, not by domain. Each remediation then covered the examples and missed a member of the domain:

| Finding | Domain the checkpoint left implicit | Member the fix missed |
|---|---|---|
| R002 | the values an observation of a process can take | an *unknown* birth time, coerced to the number 0 |
| R003 | the spellings of a host path on Windows | UNC, drive-relative, bare-drive, rooted and device forms |
| R006 | the encodings in which a source can name a path | JSON-escaped backslashes |
| R010 | the JSON kinds a request field can hold | a list or object as the `type` discriminator |

This revision therefore states each rule over its whole domain (K-41 to K-44). It also makes one rule
general (K-45): every witness for these rules is a generated matrix over the domain, and every rule has a
control that reproduces the round-8 counterexample.

## K-41 observations are three-valued; unknown is never coerced (R002)

- **Values.** Every host observation the broker acts on is one of *known value*, *absent* or *unknown*. That
  covers a process birth time, process liveness, the active count of a process group, a boot id, a Git
  status and a reachability answer. Unknown is never replaced by a concrete stand-in, such as `0`, `""`,
  `False`, an empty list or "now".
- **Process identity.** A process identity is a process id plus a birth time that is *known* or
  *unknown*. An identity recorded with an unknown birth stays unknown for its whole life. A later
  successful birth query never makes it known, because the broker cannot tell whether the answer belongs
  to the same process.
- **Liveness of an identity with an unknown birth.**
  - The process id does not exist: **ended**. On Windows, OpenProcess fails with
    `ERROR_INVALID_PARAMETER`.
  - The process id exists, whatever its birth time or exit code: **alive-or-unknown**.
  - Any inspection failure: **unknown**.
  - A birth-time mismatch is proof of reuse only when the recorded birth is known.
- **Consequence.** A job whose runner or stray process has an unknown birth keeps its reservation until
  that process id no longer exists, or until a confirmed Owner repair releases the reservation. The
  broker never terminates a process to manufacture proof.
- **Witnesses.**
  - **W-94, generated matrix:** recorded birth {known, unknown} × current observation {no such id, same
    birth, different birth, birth query fails, open fails} × exit {still active, exited, query fails}.
    The expected liveness follows the rules above. Every cell of the unknown-birth row except "no such
    id" is alive-or-unknown.
  - **W-95, the round-8 composition:** the birth query fails at spawn, assignment fails, and the next
    birth query returns a nonzero time for the same live process. The job stays `uncertain` and its
    reservation is held, both before and after a broker restart.
  - **W-96, static check:** host adapters never use the `x or <constant>` pattern on an observation, and
    the identity type admits no number as the unknown birth.
- **C-18 (control):** recording an unknown birth as `0` makes W-95 release the reservation.

## K-42 one total host-path grammar for argv and environment (R003)

- **Scope.** The grammar applies to every argv element and every environment value of a job:
  launcher-declared values, values bound by the kit, and inherited values.
- **Segments.** A value is split into segments at `=`, at `;` (the path-list separator) and, for a mount
  specification of a declared container launcher, at the host/container separator.
- **Classes.** Each segment is classified by the first rule that matches:
  1. **Device or namespace:** starts with `\\?\`, `\\.\`, `//?/` or `//./`. Refused.
  2. **UNC:** starts with two separators, `\\` or `//`. Refused.
  3. **Drive-relative or bare drive:** a letter and a colon, then anything other than a separator.
     Refused.
  4. **Drive-absolute:** a letter, a colon, then a separator. This is a host path.
  5. **Rooted without a drive:** starts with one separator. It is a container path only in a declared
     container launcher's container-side position. Everywhere else it is a host path on the job's
     drive.
  6. **Relative with a `..` component:** refused.
  7. **Relative:** resolved against the job's working directory. It is a host path if it contains a
     separator.
  8. **Anything else:** not a path.
- **Leases.** Every host path, after canonical resolution, must equal or lie inside a resource the job
  leases, with a lease mode that allows the access. The binding fails closed: a segment the grammar
  cannot classify is refused, never treated as text.
- **Inherited variables.** `inherit_env` may name only variables outside the kit's list of writable-
  location variables. That list includes the Cargo, pip, uv and npm cache variables, `HOME`,
  `USERPROFILE`, `APPDATA`, `LOCALAPPDATA`, the `XDG_*` variables, `TMP`, `TEMP` and `TMPDIR`. A tool
  that needs one of them gets it bound to a declared, leased resource through `cache_env`.
- **Witnesses.**
  - **W-97, generated matrix:** each of the eight classes × each position (whole argv element,
    `--opt=value`, a path-list element, a mount source, a mount target, an env value) × {contained and
    leased, contained and not leased, outside}. Refusals and acceptances follow the classes. The
    ordinary contained positives are accepted.
  - **W-98, the round-8 cases:** `CARGO_HOME` set to a UNC share path, and `CARGO_HOME` set to a
    drive-relative path, as launcher env, are both refused.
  - **W-99:** `inherit_env` naming a writable-location variable is refused.
- **C-19 (control):** the revision-2 recognizer, which knows only drive-absolute paths, accepts the W-98
  values.

## K-43 references are decoded before they are matched (R006)

- **Declared format.** Each reference source declares its format:
  - **`work_packages`:** a command with a declared `format` of `json`, `yaml` or `text`;
  - **`incidents` and `authority_cache`:** files whose format is taken from the extension (`.json`, then
    `.yaml` or `.yml`, otherwise text).
- **Decoding.** A source is decoded by its format into a tree, and every string leaf is collected, keys
  included. Text is one leaf. A decode failure, an unreadable source, a nonzero command exit, or output
  whose format does not match the declaration means **refuse**.
- **Matching.** A copy is referenced when any string leaf satisfies either test:
  - **Path test:** a segment that K-42's grammar classifies as a host path resolves canonically to the
    copy or to anything inside it. Both separators are accepted, case is folded, and redundant
    separators are collapsed.
  - **Identity test:** the leaf contains the copy's unique label as a whole token. This catches relative
    and shortened references.
- **Witnesses.**
  - **W-100, generated matrix:** the copy's path × encoding {plain, JSON-escaped, YAML-quoted, forward
    slashes, mixed case, inside the copy, label only} × source {work_packages in each format, incident
    `.md`, incident `.json`, authority cache}. Every cell refuses the cleanup.
  - **W-101:** malformed JSON or YAML under a declared format refuses, and so does a format mismatch.
  - **W-102:** an unrelated path that shares a prefix with the copy's path (a sibling such as
    `gate-12` beside `gate-1`) does not match.
- **C-20 (control):** raw substring matching on undecoded output authorizes the round-8 JSON case.

## K-44 request validation is total over JSON values (R010)

- **Totality.** The request validator is a total function: for every JSON value it returns *valid* or a
  reason, and it never raises. The top-level value is checked first: anything other than an object is
  malformed. The discriminator `type` is checked next and must be a string. A missing `type` is
  malformed. A string `type` that the broker does not know gets an ordinary refusal. Each field a
  handler reads is checked for kind before dispatch.
- **Isolation.** A malformed request is moved to `rejected/` with its reason. No handler runs and nothing
  is launched. The next valid request is served.
- **Containment of real faults.** The broker does not wrap handlers in a broad exception handler. An
  exception raised outside the validator is a broker fault and is not counted as malformed input.
- **Witnesses.**
  - **W-103, generated matrix:** every JSON kind (null, true, an integer, a float, a string, an empty
    list, a list, an empty object, an object) × every field position of every request type, including
    `type` and a non-object top level. Each cell is followed by a valid `status` request. Malformed cells
    are rejected alone and the `status` request is served.
  - **W-104, property test:** the validator never raises over randomly generated JSON values, with a
    fixed seed recorded in the test.
- **C-21 (control):** looking up the handler before checking the discriminator's kind reproduces the
  round-8 wedge.

## K-45 witnesses for these rules are generated over the domain

- The witness matrices W-94, W-97, W-100 and W-103 are generated from the class lists above, not written
  out case by case. A new class added to a rule adds its row automatically.
- The round-8 counterexamples are each kept as a named permanent test.
- Each control C-18 to C-21 runs against the candidate as an in-memory substitution of the rejected rule
  and shows the round-8 hazard.

## Implementation plan after agreement

Revision 3 of the implementation, on the same PR, contains:
- K-41 to K-45 with their witnesses and controls;
- nothing else that changes behavior.

The targeted closure then covers R002, R003, R006 and R010, and the complete review covers the changed
candidate.

## Request

Independent checkpoint review (§11.8.5, after §11.8.10 invalidation) of revision 8: **AGREED FOR
IMPLEMENTATION**, or REJECTED with the failing dimension and a counterexample. In particular, say whether
any of the four domains above is still incomplete.
