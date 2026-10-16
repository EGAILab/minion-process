# Onboarding a project to a kit release

How a project moves to a new kit version, and how the kit keeps that streamlined for later releases.
The project's own rules still decide when it adopts. The kit never approves its own adoption.

## For each release (kit owner)

- Every release from 0.4.0 on ships `minion_process/releases/<version>.yaml`: a short summary and the
  adoption **steps** the release adds. Each step has:
  - an id;
  - who does it (`owner` or `agent`);
  - which tool it applies to (`all`, `claude` or `codex`);
  - a check (`exists`, `json_equals`, `contains`, or `manual` when no file shows it).
- A release with nothing to adopt still ships a manifest with one `manual` step saying so. The tests
  require a manifest for every version in `CHANGELOG.md` from 0.4.0 on, and for the package version.
- A step's check looks only at files inside the project root and never changes them.
- At release, the package version in `pyproject.toml` and the shipped profiles are raised to the release
  version, and the release is tagged `vX.Y.Z` on `EGAILab/minion-process`. `install.ps1` installs by tag
  and refuses an installed version that differs from the one asked for.

## For each project (Owner and agents)

1. **Install the release inside the project** (Owner, PowerShell, from a kit checkout or the release tag):

   ```powershell
   .\bootstrap\install.ps1 -Root <project root> -Version 0.4.0
   ```

   - It creates `<root>\.tmp\kit\0.4.0\venv` and installs the kit there.
   - Nothing is written outside the root:
     - it refuses any junction or link below the root on the way to a destination;
     - it refuses any link, junction or hard-linked file inside the venv, before and after pip;
     - temp and the pip cache are a new folder for each run, `<root>\.tmp\kit\<version>\run-*`;
     - `kit.json` and `relaunch.ps1` are written to a new file and renamed into place, never written
       through an existing (possibly linked) file;
     - pip runs isolated, with every inherited `PIP_*` and Python path variable removed and no
       configuration file loaded;
     - it checks that the package is imported from the venv.
   - It copies `relaunch.ps1` to `<root>\.minion\` and writes `<root>\.minion\kit.json`.
   - A later version is installed beside the old one, and `kit.json` switches to it. Going back is
     re-running the script with the old version.
2. **List the sessions once** in `<root>\.minion\sessions.yaml`. This is an Owner-controlled file
   (`project-scope.md` PS-2).

   ```yaml
   version: 1
   sessions:
     impl: {tool: codex, network: true, env: {PUB_CACHE: .tmp/pub-cache, GRADLE_USER_HOME: .tmp/gradle}}
     review: {tool: claude}
   ```

   - `network` applies to Codex only and is off unless set.
   - `env` values are root-relative folders. `TEMP`, `TMP` and `TMPDIR` are always set to `<root>\.tmp`.
3. **See what is left:**

   ```powershell
   & <python from kit.json> -m minion_process onboard --root <root> --from <current> --to 0.4.0 [--markdown]
   ```

   - Each step prints `PASS`, `TODO` or `MANUAL`. Steps for a tool the project does not use are left
     out.
   - The exit code is 0 only when every automatic check passes.
   - `--markdown` prints the checklist for the project's coordination issue. `MANUAL` steps are
     recorded there, with their evidence.
4. **Relaunch each session** in its own pane after the agent has exited (Owner):

   ```powershell
   & <root>\.minion\relaunch.ps1 impl -Resume <session id>   # first time only
   & <root>\.minion\relaunch.ps1 impl                        # afterwards
   & <root>\.minion\relaunch.ps1 impl -DryRun                # print the plan, start nothing
   ```

   - The launch line is the one in `project-scope.md` PS-5 for Codex, and the plain `claude --resume`
     for Claude, with the PS-3 environment.
   - An id given with `-Resume` is recorded first, with provenance `owner`.
   - While the agent runs, a background job records the session id herdr reports, with provenance
     `herdr`, in `<root>\.tmp\sessions\<name>.json`. The next relaunch resumes that session without
     an id. An observation is recorded only when all of these hold:
     - it is for this pane;
     - it names this session's tool;
     - its working folder is the project root;
     - its id is not the one the pane showed before the launch, not one already recorded, and for a
       `-Fresh` launch not the id recorded before it.
     Anything else is ignored, so a stale or foreign id never replaces a usable recorded one. If herdr
     cannot be read before the launch, nothing is recorded for that launch and a warning says so.
   - Without a recorded id, the plan is refused rather than starting a new session by accident. Pass
     `-Resume <id>` once, or `-Fresh` for a new session.
   - After a relaunch, the PS-5 effective-policy check still applies.
5. **Raise the profile pin** (`kit.version`) through the project's own review. Record the completed
   checklist on the coordination issue.

## Upgrading later

Repeat steps 1, 3, 4 and 5 with the new version: `onboard --from <old> --to <new>` lists the steps of
every release in between, in order. A skipped release's steps are not lost.
