# Adopting the host build queue (kit 0.4.0)

A project adopts the queue through its own reviewed pin-bump PR. Until that PR merges, the project's
previous arrangement stays in force; for Minion-Agent that is `#209` item 1, under which Codex runs the
host build queue.

1. **Allow the queue folder.** Every agent harness that writes the folder must permit it. That folder is
   `E:\AI\Projects\OpenMinds\Minions\.host-queue` on the Owner's host.
   - **Claude:** the outside-root guard needs the folder added as an allowed root. That is an Owner
     approval code.
   - **Codex:** the binding rule names the folder.
2. **Block the confirmation phrase in tool calls.** Every Claude guard denies a tool call whose text
   contains `CONFIRM QUEUE` (K-22).
3. **Install the confirmation hook** in each Claude project's settings as a `UserPromptSubmit` hook:
   `python -m minion_process.hostqueue.confirm --queue <queue folder>`. It acts only on a whole message
   `CONFIRM QUEUE <8 hex>`.
4. **Profile, `build_queue`.**
   - The queue folder, the host `policy_id` and the project name.
   - Execution and log roots inside the project.
   - Targets with their kinds (`gate`, `controls`, `reviewer`) and reviewer owners.
   - Shared `caches`, such as the Cargo home.
   - `inherit_env`: the only host variables a launcher inherits. The default is `PATH`, `PATHEXT`,
     `SYSTEMROOT`, `SYSTEMDRIVE`, `WINDIR` and `COMSPEC`. The list is closed: it may name only a
     read-only search path, a read-only system location (the Windows and Program Files folders), a
     host identity value or a locale value (`jobspec.INHERITABLE`). Anything else is refused. A tool
     cache such as `NODE_COMPILE_CACHE` or `PYTHONPYCACHEPREFIX` is bound to a declared cache through
     `cache_env`.

   A leased path (root, target or cache) may not contain `=`, `;`, a quote, a backtick or a control
   character. `profile validate` refuses it. There is no `cleanup_references`: 0.4.0 has no cleanup.
5. **Profile, `gates.<name>.queue` for each queued gate (K-42).**
   - `argv`: literal strings and declared path slots. A path reaches the tool only through a slot,
     written `{slot: <template>, access: read|write}`. The slot forms are:
     - a whole element: `{p}` or `{p}/relative/name`;
     - an option: `--name={p}` with an optional relative suffix;
     - a mount source, in a container launcher only, after `-v`, `--volume` or `--mount`:
       `{p}:<container path>`.

     The placeholders are `{checkout}` (read only), `{workdir}`, `{target}`, `{tmp}` and `{log}`.
     `{job_label}` may appear inside a literal.
   - **Literals** (every other element, and every `env` value that is not a slot) contain no `\` or
     `/`, no drive letter, no `..` and no control character. A container path is the exception when it
     is a whole element declared under `container.paths`.
   - `env`: literal values, or slots that are exactly one placeholder.
   - `target_env`: the variables bound to the target. `cache_env`: each variable mapped to a declared
     cache.
   - `source_globs`, and `container`: `false`, or `{paths: [...]}` for a container launcher.

   **Writable-location variables** are set only by the kit: the Cargo and rustup homes, the target
   directory, the pip, uv, npm and yarn caches, `HOME`, `USERPROFILE`, `APPDATA`, `LOCALAPPDATA`, the
   `XDG_*` variables, and `TMP`/`TEMP`/`TMPDIR` (the job's own temporary folder). A launcher binds them
   through `target_env` and `cache_env` only. Variable names compare case-insensitively.
6. **Working folders and the launch proof.**
   - Every job runs in a folder it alone leases. A `build` gets a fresh folder under the execution root,
     not its checkout. A build launcher therefore names its checkout explicitly, for example
     `{slot: "{checkout}/Cargo.toml", access: read}`.
   - Before spawning, the broker walks every writable directory resource without following anything: the
     working folder, the target, each cache, the temporary folder and the log directory. Any link,
     junction or other reparse point, or any entry it cannot inspect, refuses the launch. The broker never
     cleans a resource to make the proof pass. Repair the reported entry yourself. A gate that needs a
     link inside its tree must be restructured. The job record shows each walk's duration and entry
     count.
   - The guarantee covers the values and the filesystem state handed to the tool at launch. A link the
     tool itself creates while it runs is outside it (K-42b) and belongs to the project's own gates.
   - **Execution copies are never removed by the kit.** `build status` lists every registered copy with
     its creator and state (`held`, `released`, `released (human-confirmed)` or `damaged`). A copy stays
     registered and is never reused by another job. Remove released copies by hand when you no longer
     need them; `build status` then shows `released, absent`.
7. **Host policy (first adopter only).**
   - Start the broker: `minion-process build broker --queue <folder> --serve`, kept running in its own
     terminal.
   - Request policy version 1 with `minion-process build policy --queue <folder> --file policy.yaml
     --decision <link>`. The file lists every adopting project and its roots.
   - The Owner confirms the printed `CONFIRM QUEUE <code>`.
   - A later project joins with a new policy version that adds it, again with the Owner's confirmation.
8. **Instruction files.** Replace "ask Codex for a native window" with `build submit`, then `build wait`
   in the background. Evidence comes only from `evidence` jobs that report `eligible`.

Rollback: stop submitting, wait until `build status` shows no active jobs, then return the profile to the
previous pin.
