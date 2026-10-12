"""The pinned external authority dependency rule (`authority-dependencies.md`): every active
authority runner acquires npm dependencies ONLY through the canonical `acquire_npm_pinned.sh`, whose
per-evidence copies are byte-identical, so offline and network acquisition share one verification
path. The helper's own negative controls are `authority/selftest.sh`.

The canonical helper lives in the kit. The evidence harnesses that carry copies live in a consuming
project's assurance data; that project runs the copy check by pointing `MINION_PROCESS_EVIDENCE_DATA`
at its `assurance/layers/data` directory (Minion-Agent's six active runners are listed below). Without
it, the copy check is skipped and reported as such; the helper's own structure is always checked."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[1]
CANONICAL = KIT / "authority" / "acquire_npm_pinned.sh"
EVIDENCE_DATA = os.environ.get("MINION_PROCESS_EVIDENCE_DATA")
ACTIVE_RUNNERS = [
    ("l0506-d001", "harness/run_authority.sh"),
    ("l0506-d002", "harness/run_authority.sh"),
    ("l0206-raw-boundaries", "harness/run.sh"),
    ("13-wp132-evidence", "harness/run_authority.sh"),
    ("l05-d001-schema-domain", "harness/run.sh"),
    ("l0506-d003-characterization", "harness/run.sh"),
]


@pytest.mark.skipif(EVIDENCE_DATA is None, reason="MINION_PROCESS_EVIDENCE_DATA not set (consumer check)")
@pytest.mark.parametrize(("evidence", "relative"), ACTIVE_RUNNERS, ids=[e for e, _ in ACTIVE_RUNNERS])
def test_an_active_runner_acquires_only_through_the_canonical_helper(  # pragma: no cover
    evidence: str, relative: str
) -> None:
    runner = Path(str(EVIDENCE_DATA)) / evidence / relative
    source = runner.read_text(encoding="utf-8")
    code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
    assert '. "$H/acquire_npm_pinned.sh"' in code
    assert "acquire_npm_pinned " in code
    assert "npm pack" not in code  # no side door around the shared verification
    # PROC-AUTHDEP-R001: the pin is read from the verified pinned COMMIT, never the working tree
    assert 'show "' in code
    assert ':package-lock.json" > "$S/pinned-package-lock.json"' in code
    assert '"$S/pinned-package-lock.json"' in code.split("acquire_npm_pinned ", 2)[-1]
    assert '"$PI/package-lock.json"' not in code
    copy = runner.parent / "acquire_npm_pinned.sh"
    assert copy.read_bytes() == CANONICAL.read_bytes(), f"{copy} differs from the canonical helper"


def test_the_helper_reads_its_pin_from_the_lockfile_and_verifies_before_unpacking() -> None:
    helper = CANONICAL.read_text(encoding="utf-8")
    verify = helper.index('[ "$_got" = "$_sri" ]')
    assert helper.index('"node_modules/" + process.argv[2]') < verify  # the pin comes from the lockfile
    assert verify < helper.index("tar -xzf")  # bytes are verified before anything is unpacked
    assert helper.index("tar -xzf") < helper.index("unpacked $_name declares version")
