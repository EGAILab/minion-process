# Minion-Process — Pinned external authority dependencies (normative)

**Kit file.** Seeded from `minion-agent-docs` at `dd9fd15`, text preserved. The npm implementation and the runner list are Minion-Agent's; the rule and the pattern are generic. The canonical helper is `authority/acquire_npm_pinned.sh` in the kit.

**Source:** the Owner's offline-replay decisions (`minion-agent#99` comments `5930365971` and `5930377491`). They were made when L0506-D002's and L0206-D002's final reviews were blocked only because the reviewer's sandbox could not reach Docker or the npm registry.

## The rule

> Independent authority verification requires the reviewer to independently **VERIFY** the exact authority inputs and independently **EXECUTE** the authority. It does not require the reviewer to independently **DOWNLOAD** identical dependency bytes.

```text
acceptable:
    another actor supplies artifact bytes
    reviewer validates bytes against the authoritative cryptographic pin
    reviewer executes the authority independently
    reviewer evaluates the output independently

not acceptable:
    author executes the authority
    reviewer trusts the author's output
```

- **Docker and network access are execution conveniences, not assurance requirements**, unless container or runtime identity is itself part of the semantic authority.
- **Exact pinned runtime identity stays mandatory.** For example, `node --version` must be exactly `v22.15.1`, together with the V8/ICU/Unicode pins where a harness records them. A host runtime is acceptable only when it proves that identity. No other version substitutes.

## The pattern (any external authority dependency)

```text
external authority dependency
    exact identity / version            from the pinned authoritative record (e.g. Pi's package-lock.json)
    authoritative digest                the pinned record's integrity (e.g. its sha512 SRI), never the supplier's claim;
                                        the record is read from the VERIFIED pinned commit (e.g. `git show <pin>:
                                        package-lock.json`), never from a working tree a supplier could edit
    supplied bytes                      network download OR an explicitly supplied artifact -- both untrusted
    independent digest verification     computed by the runner before anything is unpacked or executed
    independent execution               the SAME authority implementation, whatever the byte source
```

- **One path after acquisition.** Network and offline acquisition converge on the same verified bytes before execution:

  ```text
  network download ─┐
                    ├─> cryptographically verified package -> same authority
  offline artifact ─┘
  ```

  There is never a separate or simplified offline oracle.
- **Failure is deterministic.** A missing file, the wrong package, a modified byte, a wrong version under the right filename, or a pinned record without the expected version or digest each stops the run before execution.
- **Artifacts are not committed.** Supplied artifacts live in a review workspace, CI artifact or cache, with their exact filename, version, digest, SHA-256 and provenance recorded in assurance. The pinned record stays the integrity authority. Vendoring authority artifacts into the source tree would be a separate tooling decision.
- **Scope.** The pattern applies beyond npm to pinned ICU, Photon, `fd`/`ripgrep` and similar artifacts, wherever their digest is pinned in an authoritative record. It does **not** weaken any requirement where the external environment itself is semantically observable (e.g. the pinned ICU build identity a collation result depends on). There the environment's identity remains part of the authority and must be proven.

## The npm implementation

- **`process/tools/authority/acquire_npm_pinned.sh`** (canonical; each evidence harness carries a byte-identical copy, enforced by `process/tools/tests/test_authority_dependencies.py`).
  - **Usage:** `acquire_npm_pinned <package> <version> <pinned package-lock.json> <dest> <work>`.
  - **Offline:** `<PACKAGE>_TGZ=<path>`, e.g. `TYPEBOX_TGZ`, `DIFF_TGZ`.
  - **Network:** `npm pack`, as the fallback.
  - **Verification, in order:**
    1. the lockfile records exactly `<version>` with an `sha512` integrity;
    2. the tarball's SHA-512 equals that integrity;
    3. the unpacked `package.json` declares `<version>`.
- **The pinned record comes from the commit** (`PROC-AUTHDEP-R001`). Each runner extracts `package-lock.json` with `git show <pinned SHA>:package-lock.json` after verifying HEAD. A coherently edited working-tree lockfile (forged digest matching modified bytes) is therefore never consulted. Real-runner witness: `process/tools/authority/runner_witness.sh` (coherent pin substitution FAILS with no authority output; the correct artifact against the pinned blob PASSES), run against all four active runners.
- **Negative controls:** `process/tools/authority/selftest.sh`. The correct artifact passes; a wrong tarball, a modified tarball, a wrong version under the same filename, a wrong expected digest and a lockfile recording another version each fail.
- **Runners.** The active authority runners take `PI_DIR`, `OUT_DIR`, `STAGE_DIR` and `PYTHON` (defaults: the container layout), so the same committed runner executes in `node:22.15.1-alpine` or on a host that proves the runtime pins:
  - `l0506-d001`
  - `l0506-d002`
  - `l0206-raw-boundaries`
  - `13-wp132-evidence`
  - `l05-d001-schema-domain`
  - `l0506-d003-characterization`

  OS tools (`git`, `python3`) are installed only when missing. A fully offline container needs an image providing them; otherwise the runner fails with an explicit message.
- **Historical harnesses** (characterization passes, WP-13.1 differentials) keep their recorded network acquisition. A re-run applies this pattern.
