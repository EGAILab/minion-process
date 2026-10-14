# CE-PROC-P3B-01 checkpoint proposal, revision 10 (base: contract revision 3 + checkpoint revisions 4–9)

**Author:** Claude `w1:p8`. **Status:** PROPOSED. Codex round 10 kept these parts of revision 9:
- the unsplit slot mechanism;
- refusal of resource names that contain a delimiter;
- the suffix rules;
- kit-only writable-location bindings, with names compared case-insensitively;
- C-19b;
- the locator-placement matcher, its sibling negatives, and C-20b.

Two dimensions remain open. This revision adds them to K-42 and K-43 and amends K-45. Both are resolved
by **enforcement**. No residual is carried as risk acceptance, so no Owner decision is requested.
Revisions 4 to 9 otherwise stand, and no closure is reopened.

| Rule | Dimension round 10 found missing | Resolution |
|---|---|---|
| K-42 | effective resolution of relative values, through links, and access mode | the working folder is proved link-free at launch, and each slot declares its access |
| K-43 | completeness of the reference spellings | every possible locator is resolved on the host, and anything unresolvable refuses |

## K-42 addendum: effective resolution and access

- **Revision 9's sentence is withdrawn.** Revision 9 claimed a relative value is contained "whatever the
  tool does with it". That sentence is false and is removed.
- **K-42a, launch invariant.** Immediately before spawning, the broker proves the job's working folder.
  Spawning is refused unless all of these hold:
  1. The folder and every ancestor up to the drive root pass the R009 proof, so none is a link or
     reparse point.
  2. A full walk of the folder's subtree finds no entry that is a link, junction, mount point or any
     other reparse point. Dangling links count.
  3. Every entry of the subtree was inspected. A failed enumeration or inspection refuses.

  With these three facts, a relative value with no `..` component, such as `out` or `out\x`, resolves
  inside the folder at launch. The folder is leased exclusively, so a write through that value reaches
  only a resource the job holds.
- **K-42b, the boundary of the guarantee.** The kit binds the values and the filesystem state it hands
  to the tool at launch. It is not a sandbox. A link the tool itself creates during its run is the tool's
  own effect and is outside this guarantee. The adopting project's gate suite owns that behavior, as it
  owns C-6 and C-10. This boundary is stated, not implied.
- **K-42c, declared access for every path slot.** Each path slot in a template declares `access: read`
  or `access: write`. A placeholder's lease mode must permit the declared access:

  | Placeholder | Allowed access |
  |---|---|
  | `{checkout}` (a shared read lease) | read only |
  | `{target}` and `{log}` | write |
  | `{workdir}`, the per-job folder, and the temporary folder | write |
  | a cache | write, under a shared lease |

  A slot declared `write` with `{checkout}` is refused, and so is a slot with no declared access.
- **K-42d, application-specific variables.** A launcher env variable that is not a placeholder carries a
  literal value under revision 9's literal rule. If its tool writes through the value, the value is
  relative and is covered by K-42a. A literal can never be absolute, rooted or contain `..`, by the
  revision-9 literal rule.
- **Witnesses:**
  - **W-99b′:** under one exclusive working folder, the cases are
    - an ordinary directory `out`;
    - `out` as a link to another job's resource;
    - `out` as a link outward from the project root;
    - a dangling link;
    - a junction deeper in the tree;
    - a subtree enumeration failure.

    Only the ordinary case is launched. Every other case is refused before spawning, with zero spawn
    calls.
  - **W-99c:** a `{checkout}` slot declared `write` is refused, and a slot without declared access is
    refused.
  - **W-99d:** an evidence worktree whose exact SHA commits a symbolic link, checked out as a real link,
    is refused at launch.
- **C-19c (control):** spawning on the working folder and its exclusive lease alone, without the
  K-42a walk, launches the redirected-output row of W-99b′.

## K-43 addendum: completeness by host resolution, fail closed

Revision 9's disclosed residual is **withdrawn**. In its place, the matcher resolves every candidate
locator on the host. A spelling the matcher cannot resolve refuses the cleanup, so no unsupported spelling
can ever count as "unreferenced".

- **K-43a, composed variants.** The three transformations are applied in a fixed order: removing a
  `file:` scheme, percent-decoding, then removing Markdown escapes. Every one of the eight subsets is
  applied in that order. Each resulting variant is normalized as in revision 9. A leaf matches if any of
  its eight variants matches.
- **K-43b, environment-variable spellings.** The spellings are `%NAME%`, `$NAME`, `${NAME}` and
  `$env:NAME`, with names compared case-insensitively. Each is expanded in a variant from the broker's
  environment and then matched as text. If any such spelling in a leaf names a variable that is not
  defined in that environment, the leaf is **unresolvable** and the cleanup is refused.
- **K-43c, host resolution of absolute candidates.**
  - **Candidates.** Every substring of a variant that begins with a drive-absolute or UNC form is a
    candidate start. Each candidate is cut at every later boundary character from revision 9's
    right-boundary set, and at the end of the leaf.
  - **Resolution.** The longest existing prefix of each cut is opened without traversal restrictions.
    Its final path is read with GetFinalPathNameByHandle, which resolves links, junctions, `subst`
    drives and 8.3 short names. The remainder is appended lexically.
  - **Match.** The cleanup is refused when a resolved cut equals or lies inside the copy's canonical
    path.
  - **Failure.** Refused also when inspection of an existing prefix fails, or when a candidate is a UNC
    form whose final path is not on a local volume. Both count as unresolvable.
  - **Missing paths.** A cut with no existing prefix below its drive root is matched lexically only, as
    in revision 9.
- **K-43d, root-relative candidates.** Root-relative candidates (revision 9) are joined to each project
  root, then resolved by K-43c.
- **K-43e, the existing producer domain needs no migration.** Existing references keep working in any
  spelling the host can resolve to the copy:
  - canonical, root-relative, short-name, link-alias and `subst` spellings;
  - variable spellings over defined variables;
  - the final component or the label as a token.

  Every other spelling of a locator refuses. Over-refusal blocks a cleanup and never deletes anything.
  The Owner can still remove a copy by hand.
- **Witnesses:**
  - **W-100′** stands.
  - **W-100a, completeness pairs.** Each spelling appears once as a retained reference, which refuses,
    and once with the same text naming an unrelated sibling, which does not refuse:
    - Codex's `%COPY_LOCATION%` example with the variable defined;
    - the same text with the variable undefined, which refuses as unresolvable;
    - an 8.3 short-name spelling, which is Windows only and skipped when short names are disabled on
      the volume;
    - a link elsewhere in the project root that points into the copy;
    - a `subst`-style alias, simulated through the resolution seam;
    - a UNC spelling that the host cannot resolve, which refuses.
  - **W-100b:** representations that combine transformations, for example a percent-encoded `file:` URL
    inside Markdown-escaped prose, each match.
  - **W-100c:** inspection failure while resolving an existing prefix refuses.
- **C-20c (control):** treating an unresolvable or unsupported spelling as absence lets W-100a's
  undefined-variable and alias rows authorize cleanup.

## K-45 amended again

- **K-42 matrices** are generated over role × access × spelling × delimiter × effective-resolution state.
  The resolution states are ordinary, inward link, outward link, dangling link, deep junction and
  inspection failure.
- **K-43 matrices** are generated over placement × transformation subset × spelling × source.
  Completeness pairs are generated over the alias kinds: a defined variable, an undefined variable, a
  short name, a link, `subst` and UNC.
- **Controls** C-18 to C-21 are executed as in-memory substitutions against the candidate, together with
  C-19b, C-19c, C-20b and C-20c.

## Adoption impact

- A build launcher passes `{checkout}` explicitly (revision 9).
- Every path slot declares its access.
- A working tree that contains links is refused at launch. An adopter whose gate needs a link inside its
  checkout must restructure the gate.

`ADOPTION.md` will say all three.

## Request

Independent checkpoint review (§11.8.5) of revision 10's K-42 and K-43 addenda and the amended K-45:
**AGREED FOR IMPLEMENTATION**, or REJECTED with the failing dimension and a counterexample. Please judge in
particular:
- whether K-42b's stated boundary, that tool-created links are outside the guarantee and belong to the
  consumer, is acceptable;
- whether any reference spelling can still be absent from both the resolvable set and the
  refuse-as-unresolvable set.
