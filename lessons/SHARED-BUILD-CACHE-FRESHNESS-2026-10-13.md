# SHARED-BUILD-CACHE-FRESHNESS-2026-10-13 - a shared build cache ran another checkout's, and a mutant's, binaries as a gate

**Supports:** `WORKFLOW.md` section 9.8 (shared build caches: fresh sources, a separate controls cache, one
writer, provenance).
**Source:** `EGAILab/minion-process#4`, proposed by the Minion-Agent consumer (Claude w1:p1) at the Owner's
request on 2026-10-13; evidence `minion-agent#215` issuecomment-6130383125 (the review that executed the
foreign artifacts) and the Owner decision `minion-agent#209` issuecomment-6131831805 (build ownership and
target freshness). The "What happened" and "Mechanism" sections are the proposal's text, verbatim.

## What happened (verbatim)

> Minion-Agent adopted one shared Cargo target per platform (Owner build policy, minion-agent#209, 2026-10-12). During an independent closure review (minion-agent#215 issuecomment-6130383125), the reviewer's gate executed artifacts that the gate's own checkout had not produced:
>
> 1. **A mutant reached G3.** The author's committed gate recipe ended with mutation controls. The last mutant's test binary stayed in the shared target, built at 03:06. The reviewer's rerun copied a checkout whose files dated from 01:29, and G3 ran the mutant: it FAILED with the mutant's exact kill signature.
> 2. **A foreign checkout reached G3.** A rebuild from a copy under another container path was then reused by the next run of the recipe. The integration-test binaries embedded the other path's `CARGO_MANIFEST_DIR` twice and the recipe's own path zero times, and failed `NotFound`.
> 3. **Windows behaves the same.** Two different worktrees of one SHA executed the same `agent_inbox_conformance-<hash>.exe`.

## Mechanism (verbatim)

> - **Path-independent hashes.** Cargo's artifact hash for a workspace member does not include the checkout path or the source content; it covers package identity, features, flags and dependencies.
> - **Mtime freshness.** Cargo's default freshness check compares source mtimes with the stored build.
> - **The consequence.** Any checkout whose files are older than a same-package build from another checkout, or from a mutant, silently runs that build.
>   - Copies that preserve mtimes (`cp -p`, archive extraction) make it likely.
>   - Concurrent worktrees and mutation controls make it routine.
> - **Loud and silent cases.** The loud cases FAIL. The dangerous case is a **false PASS**: candidate B's gate runs candidate A's code for any package B has not touched since A's build.

## The rule as adopted by the kit

1. **Fresh sources before every gate.** Each gate entry point first gives the workspace-member sources a
   fresh mtime: a fresh worktree or copy, a copy without mtime preservation, or a contained,
   content-neutral touch. Registry dependencies can stay shared.
2. **A separate cache for mutation controls.** They never build in a gate cache.
3. **Single writer per shared cache.** One agent owns each shared cache. An independent reviewer reruns in
   a reviewer-only cache built from its own fresh checkout, so author and reviewer states cannot leak
   into each other's verdicts.
4. **Provenance when in doubt.** Evidence from a shared cache is checked by the paths embedded in the
   binaries and their build times against the checkout's time.

The project names its caches and owners in the profile (`environment`, `gates`); the kit rule stays
generic. Minion-Agent adopted 1-3 as the Owner decision in `minion-agent#209` before this record existed.

## Replay (consumer-side; needs the project's build tool)

Build a tiny two-checkout workspace with a shared target. In checkout A, build a test that asserts a
constant. In checkout B, with older mtimes and a different constant, run the test. The unsafe recipe runs
A's binary and reports A's constant; the rule's recipe refreshes B's mtimes first, rebuilds, and observes
B's constant. The replay belongs to the consumer's gate suite (it needs `cargo` or the equivalent), gated
like the other environment-dependent controls; the kit's `replay/` suite (P3b) carries the recipe.
