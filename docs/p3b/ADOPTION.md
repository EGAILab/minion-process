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
     `SYSTEMROOT`, `SYSTEMDRIVE`, `WINDIR` and `COMSPEC`.
   - `cleanup_references`, which cleanup requires before it removes anything:
     - `work_packages`: a command whose output is the open work packages' states;
     - `incidents`: paths of incident records;
     - `authority_cache`: paths of the authority cache.
5. **Profile, `gates.<name>.queue` for each queued gate.**
   - `argv`, using the placeholders `{checkout}`, `{target}`, `{log}`, `{workdir}` and `{job_label}`.
   - `target_env`: the variables bound to the target.
   - `cache_env`: each variable mapped to a declared cache.
   - `source_globs`, `env` and `container`.

   Every host path in `argv` or `env` must be a leased resource of the job. The kit sets
   `TMP`/`TEMP`/`TMPDIR` to the job's own temporary folder, and a launcher can neither set those nor
   override the target and cache variables. Anything else a tool writes must therefore go through those
   variables.
6. **Cleanup runs as a dry run unless `apply` is given.** The dry run writes a report of what it would
   remove. An applied cleanup re-checks every Part C predicate before each batch.
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
