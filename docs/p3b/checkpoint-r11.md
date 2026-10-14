# CE-PROC-P3B-01 checkpoint proposal, revision 11 (base: contract revision 3 + checkpoint revisions 4–10)

**Author:** Claude `w1:p8`. **Status:** PROPOSED. Codex round 11 accepted these at checkpoint level:
- K-42b, the non-sandbox boundary for cooperating tools;
- the K-42a mechanism: the ancestor proof, the complete no-follow walk, and refusal when inspection
  fails;
- K-42c, declared access;
- the K-43 direction: no residual, host resolution, and refusal of what is unresolvable.

Two coverage gaps remain. This revision replaces K-42a's scope and K-43's discovery order, and amends K-45
again. Revisions 4 to 10 otherwise stand, and no closure is reopened.

| Rule | Gap | Resolution |
|---|---|---|
| K-42a | only the working folder was walked | every launch-supplied writable directory resource is walked |
| K-43 | normalization collapsed a UNC root before discovery | discovery runs on the unnormalized text and keeps the root kind |

## K-42a′ every writable directory resource is proved at launch

- **Resources proved.** Immediately before spawning, the broker applies K-42a's proof to every writable
  directory resource the job receives:
  - the working folder;
  - the target;
  - each cache bound by `cache_env`;
  - the job's temporary folder;
  - the directory that holds the job's log.

  For each resource, the root and its ancestors pass the R009 proof. The complete subtree is then walked
  without following anything. Any link, junction, mount point or other reparse point refuses the launch,
  dangling ones included. So does any failed enumeration or inspection.
- **Leaf slots.** A writable leaf slot, such as the log file itself, keeps the retained immediate proof of
  the target and its ancestors.
- **No shortcut by cleaning.** The broker never cleans, rebuilds or empties a resource to make a proof
  pass. A refused resource is reported with the offending entry, and the Owner or the adopter repairs it.
- **Shared caches** keep their shared-lease protocol. Every job that receives the cache walks it at its
  own launch. A link that a concurrent job's tool creates during its run is that tool's own effect, under
  K-42b.
- **Cost is accepted, not avoided.** The walk only reads metadata, using large-fetch enumeration. Its
  duration and entry count are recorded in the job record. A long walk is never a reason to skip the
  proof.
- **Witnesses:**
  - **W-99b″, generated:** resource kind {working folder, target, cache, temporary folder, log directory}
    × resolution state {ordinary, inward link, outward link, dangling link, deep junction, enumeration
    failure, entry inspection failure}. Only the ordinary row launches. Every other row is refused before
    spawning, with zero spawn calls. Codex's round-11 case, a junction at `cargo-home\registry`, is a
    named permanent test.
- **C-19d (control):** walking the working folder only, which was revision 10's scope, launches the
  cache and target redirect rows. C-19c is kept.

## K-43′ discovery keeps the root kind

- **Order.** For each leaf, the eight transformation subsets of K-43a are applied first. Candidates are
  then discovered on each transformed variant **before any separator normalization**. Normalization then
  applies to each candidate's components only, and the root prefix keeps its kind.
- **Transformations that preserve the root.**
  - Removing `file:` maps `file:///X:/p` to `X:/p`. It maps `file://host/share/p`, where the host is not
    empty and not `localhost`, to the UNC form `\\host\share\p`. It maps `file://localhost/X:/p` to
    `X:/p`.
  - Removing Markdown escapes is one subset among the eight. A variant that keeps the escapes is always
    examined too, so a literal `\\` in the source survives in at least one variant.
- **Root kinds.** Candidates are discovered as the longest-match prefix at any position, and each kind is
  handled as follows:

  | Kind | Prefix | Handling |
  |---|---|---|
  | device or extended | `\\?\`, `\\.\`, `//?/`, `//./` or `\??\` | the inner path is handled by its own kind; an inner form that is not drive-absolute or UNC refuses |
  | UNC | `\\host\share` or `//host/share` | resolved by K-43c; refused unless it resolves on a local volume |
  | drive-absolute | `X:\` or `X:/` | resolved by K-43c |
  | drive-relative | `X:` followed by a name character | joined to the drive root and to each project root on that drive, then resolved |
  | rooted without a drive | a separator at a token start, not part of a longer prefix | joined to the root of each drive that holds a project root, then resolved |
- **Normalization of candidates.** Every separator after the root prefix becomes `\`. Runs of separators
  after the root are collapsed, and the components are case-folded. The root prefix itself is never
  collapsed.
- **Unresolvable means refuse.** A candidate whose root or volume cannot be inspected refuses. Neither
  can ever count as lexical evidence of absence. Name-token and label matching (revision 9) still runs on
  every variant.
- **Witnesses:**
  - **W-100d, generated:** root kind {UNC with backslashes, UNC with forward slashes, extended
    `\\?\X:\`, extended UNC `\\?\UNC\h\s`, device `\\.\`, `\??\`, drive-absolute, drive-relative, rooted
    without a drive} × transformation subset (all eight) × placement {exact leaf, prose, quoted,
    Markdown link}. Each cell names either the copy, which refuses, or an unresolvable root, which
    refuses. Codex's round-11 leaf, which names a foreign host's share, is a named permanent test and
    refuses.
  - **W-100e:** sibling negatives for each locally resolvable root kind name an unrelated resolvable
    folder and do not refuse.
  - **W-100f:** `file://host/share/x` reaches UNC handling, and `file://localhost/X:/x` reaches
    drive-absolute handling.
- **C-20d (control):** normalizing separators before scanning, which was revision 10's order, misses the
  round-11 UNC leaf and authorizes the cleanup. C-20c is kept, and its rows now include the UNC discovery
  pair.

## K-45 amended again

- **K-42 matrices** add the dimension resource kind × effective-resolution state.
- **K-43 matrices** add the dimension root kind × transformation subset × discovery.
- **Controls** C-18 to C-21 are executed as in-memory substitutions against the candidate, together with
  C-19b, C-19c, C-19d, C-20b, C-20c and C-20d.

## Adoption impact

Revision 10's impact stands. It also extends to resources:
- **Launch proof:** a target, cache or temporary folder that contains a link or junction is refused at
  launch. The adopter repairs the resource, and the kit never cleans it.
- **Walk time:** every launch walks each writable directory resource it receives, and the job record
  shows how long each walk took.

## Request

Independent checkpoint review (§11.8.5) of revision 11's K-42a′, K-43′ and the amended K-45: **AGREED FOR
IMPLEMENTATION**, or REJECTED with the failing dimension and a counterexample.
