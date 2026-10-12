# PLATFORM-EVIDENCE — control baselines, missing prerequisites, drvfs temp, host load

**Supports:** `WORKFLOW.md` §9.7 (a control runner proves its baseline first), §9.8 (reproducible
platform evidence; sequential gate runs; storage inside the project root).
**Source:** `agent-workflow.md` §9.7 and §9.8 at `dd9fd15`, verbatim.

§9.7, baseline and recipe:

> The recipe that produced a recorded kill is part of the evidence. That includes any overlay of a planned fix, and any marker bypass. A kill that cannot be reproduced from the committed script and the documented recipe is not evidence. (L03-D001 `L03D001-R001`; L08-D002 remediation 1, section 8.)

§9.8, missing prerequisites:

> A missing prerequisite is disclosed as such and is never reported as a passing gate. In L12-D002, a Rust EXEC-010 test failed only because its image lacked Node.js, and the WP-13.3 property tests did not collect without `hypothesis`.

§9.8, host load:

> In the WP-13.4 Rust closure, a concurrent Docker build made a Windows full-suite target fail spuriously; it passed on its own.

§9.8, Docker temp on a Windows bind mount:

> A Windows bind mount (drvfs) lacks the POSIX semantics some fixtures need: backslash file names and real symlinks. In L08-D002's Rust closure, a `TMPDIR` on drvfs failed `canonical_skill_discovery` and stalled the deep-walk witness. That batch was discarded and re-run on tmpfs.

§9.8, the storage rule as adopted by Minion-Agent (Owner rule, 2026-10-09; the kit keeps the generic
rule and the profile names the paths):

> **Local storage stays inside the project root** (Owner rule, 2026-10-09). On the Windows host, every file a gate, probe or control creates goes under the project root on E: (`E:/AI/Projects/OpenMinds/Minions/Minion-Agent/`), never on C:. That covers:
> - worktrees, under `review-worktrees/`;
> - scratch and disposable copies, under `.tmp/`;
> - temp directories (`TMP`, `TEMP`, `TMPDIR`), which also hold test `tempdir()`s and pytest base temps;
> - `CARGO_HOME` and `CARGO_TARGET_DIR`;
> - the pip, uv and npm caches.
>
> Agent-home scratch locations (`AppData/Local/Temp`, `~/.codex/tmp`, `~/.claude/jobs`) are not used for builds. Setting only `CARGO_TARGET_DIR` is not enough: test temp directories still land in the user temp folder. Each agent keeps one sourced environment file that sets all of these.
