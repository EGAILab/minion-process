"""Witnesses and executed controls for Codex implementation review round 17 (PROC-KIT-P3B-R002, R003,
R010) and its note N001.

- R002: the recorded runner is part of the end proof in every active state; a verified drain is not
  proof that the runner itself exited. W-108 (generated), C-25.
- R003: the inherited-variable domain is closed by an allow-list of read-only classes. W-109
  (generated), the spawn envelope, C-26.
- R010: a data-triggered decoding failure is contained at the framing boundary. W-110 (depth pairs),
  C-27.
- N001: an exact wrong-generation control for W-107c row c.

Each control substitutes the rejected rule in memory and asserts only its intended witness observation.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

from minion_process.hostqueue import broker as broker_mod
from minion_process.hostqueue import framing, jobspec
from minion_process.hostqueue.framing import COMMIT, MAGIC, decode_single, encode

from .hostqueue_world import SHA, World, make_world
from .test_hostqueue_remediation2 import _confirmed, _row, _spec, edit_profile, launcher

GIB = 1024**3


# == R002: the runner is observed in every active state =====================================================


def _drained_running(w: World, birth_unknown: bool) -> int:
    """An evidence job is running. Its runner has written a passing, verified-drain result but has not
    exited yet (runner.run writes the result before it returns). The group query then fails."""
    w.host.spawn_birth_unknown = birth_unknown
    job_id = int(w.submit("evidence", sha=SHA)["job_id"])
    assert w.job(job_id).status == "running"
    (w.queue / "jobs" / str(job_id) / "result").write_bytes(
        encode({"exit": 0, "gate_end": 0, "drained": True})
    )
    w.host.group_query_error = True
    return job_id


@pytest.mark.parametrize("birth_unknown", [False, True], ids=["known-birth", "unknown-birth"])
@pytest.mark.parametrize("runner_alive", [True, False], ids=["runner-alive", "runner-gone"])
def test_w108_drained_result_is_not_proof_that_the_runner_exited(
    tmp_path: Path, birth_unknown: bool, runner_alive: bool
) -> None:
    w = make_world(tmp_path)
    job_id = _drained_running(w, birth_unknown)
    runner = w.host.spawned[-1]["runner"]
    if not runner_alive:
        w.host.processes[(runner.pid, runner.start)] = False  # its process id is gone
    w.broker.step()
    job = w.job(job_id)
    reserved = w.broker.state.reserved_bytes(w.host.clock, w.broker.policy)  # type: ignore[arg-type]
    if runner_alive:
        expected = "uncertain" if birth_unknown else "running"  # alive-or-unknown, or alive
        assert job.status == expected and not job.eligible and reserved == 16 * GIB
    else:
        assert job.status == "ended" and job.eligible and job.proof == "inspected"


def test_c25_control_omitting_the_running_runner_ends_live_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = broker_mod.Broker._workload
    monkeypatch.setattr(
        broker_mod.Broker,
        "_workload",
        lambda self, spec, runner=None: real(self, spec, None),  # the rejected rule: runner not observed
    )
    w = make_world(tmp_path)
    job_id = _drained_running(w, birth_unknown=False)
    w.broker.step()
    job = w.job(job_id)
    assert job.status == "ended" and job.eligible  # the hazard: W-108's live-runner row fails


# == R003: the inherited-variable domain is closed ===========================================================

INHERITED_OK = sorted(name for names in jobspec.INHERITABLE.values() for name in names)
INHERITED_REFUSED = [
    "NODE_COMPILE_CACHE",
    "node_compile_cache",
    "PYTHONPYCACHEPREFIX",
    "RUFF_CACHE_DIR",
    "MYPY_CACHE_DIR",
    "GRADLE_USER_HOME",
    "CARGO_HOME",
    "TEMP",
    "XDG_CACHE_HOME",
    "PROGRAMDATA",
    "ALLUSERSPROFILE",
    "SOME_TOOL_SETTING",
]


@pytest.mark.parametrize("name", INHERITED_OK)
def test_w109_each_read_only_class_member_is_inherited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    w = make_world(tmp_path)
    monkeypatch.setenv(name, "value-of-" + name)
    edit_profile(w, lambda d: d["build_queue"].update(inherit_env=[name]))
    assert _spec(w)["env"][name] == "value-of-" + name


@pytest.mark.parametrize("name", INHERITED_REFUSED)
def test_w109_any_other_inherited_name_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    w = make_world(tmp_path)
    monkeypatch.setenv(name, str(tmp_path / "outside-cache"))
    edit_profile(w, lambda d: d["build_queue"].update(inherit_env=["PATH", name]))
    with pytest.raises(jobspec.SpecError, match=r"inherit_env may name only|repeats"):
        _spec(w)


def test_w109_a_tool_cache_is_bound_through_cache_env(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    cache = w.root / "node-cache"
    cache.mkdir()
    edit_profile(
        w,
        lambda d: (
            d["build_queue"].update(caches={"node": str(cache)}),
            launcher(d).update(cache_env={"NODE_COMPILE_CACHE": "node"}),
        ),
    )
    spec = _spec(w)
    from minion_process.hostqueue.resources import canonical

    assert spec["env"]["NODE_COMPILE_CACHE"] == canonical(cache)
    assert [canonical(cache), "shared"] in spec["leases"]


def _spawned_env(w: World, monkeypatch: pytest.MonkeyPatch, inherit: list[str]) -> dict[str, str]:
    monkeypatch.setenv("NODE_COMPILE_CACHE", str(w.tmp / "outside-cache"))
    edit_profile(w, lambda d: d["build_queue"].update(inherit_env=inherit))
    response = w.submit("evidence", sha=SHA)
    assert response["ok"], response
    env: dict[str, str] = w.host.spawned[-1]["env"]
    return env


def test_w109_spawn_envelope_holds_only_kit_bound_and_allow_listed_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = make_world(tmp_path)
    env = _spawned_env(w, monkeypatch, ["PATH", "SYSTEMROOT"])
    kit = {"MINION_JOB", "MINION_JOB_GROUP", "TMP", "TEMP", "TMPDIR", "CARGO_TARGET_DIR"}
    assert set(env) <= kit | {"PATH", "SYSTEMROOT"} and "NODE_COMPILE_CACHE" not in env
    w2 = make_world(tmp_path / "second")
    edit_profile(w2, lambda d: d["build_queue"].update(inherit_env=["PATH", "NODE_COMPILE_CACHE"]))
    refused = w2.submit("evidence", sha=SHA)
    assert refused["ok"] is False and "NODE_COMPILE_CACHE" in refused["error"] and not w2.host.spawned


def test_c26_control_blacklist_only_inheritance_spawns_an_unbound_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Blacklist:  # the rejected rule: anything not on the writable-location list is inherited
        def __contains__(self, name: object) -> bool:
            return not jobspec.is_writable_location(str(name))

    monkeypatch.setattr(jobspec, "_INHERITABLE", Blacklist())
    w = make_world(tmp_path)
    env = _spawned_env(w, monkeypatch, ["PATH", "NODE_COMPILE_CACHE"])
    assert env["NODE_COMPILE_CACHE"] == str(w.tmp / "outside-cache")  # the hazard: an unleased writable path


# == R010: decoding failure is contained at the framing boundary =============================================


def _frame(body: bytes) -> bytes:
    return (
        MAGIC
        + f"{len(body):08x}".encode()
        + b" "
        + hashlib.sha256(body).hexdigest().encode()
        + b" "
        + body
        + COMMIT
    )


def _nested_cancel(depth: int) -> bytes:
    return _frame(
        b'{"type":"cancel","request_id":"000-bad","job_id":' + b"[" * depth + b"0" + b"]" * depth + b"}"
    )


# The depth at which the JSON decoder gives up is a build-time property of the interpreter: Python 3.12
# on Windows raises at 5000 levels, while the Linux CI build decodes 5000 and raises well before 100000.
# Codex's 5000 row is kept with the property that matters on every platform: it is rejected alone and the
# next request is served. DEEP is beyond every supported interpreter's limit.
DEEP = 100_000


@pytest.mark.parametrize(
    ("depth", "reasons"),
    [
        (4, ("malformed request",)),
        (2000, ("malformed request",)),
        (5000, ("malformed request", "unreadable request")),
        (DEEP, ("unreadable request",)),
    ],
)
def test_w110_deep_nesting_is_rejected_alone_and_service_continues(
    tmp_path: Path, depth: int, reasons: tuple[str, ...]
) -> None:
    w = make_world(tmp_path)
    (w.queue / "inbox" / "000-bad.req").write_bytes(_nested_cancel(depth))
    (w.queue / "inbox" / "999-good.req").write_bytes(encode({"type": "status", "request_id": "999-good"}))
    w.broker.step()
    assert not (w.queue / "inbox" / "000-bad.req").exists()
    assert (w.queue / "rejected" / "000-bad.reason").read_text(encoding="utf-8").startswith(reasons)
    assert decode_single((w.queue / "outbox" / "999-good.res").read_bytes())["ok"] is True


def test_w110_framing_reports_deep_nesting_as_a_framing_error() -> None:
    with pytest.raises(framing.FramingError, match="too deep"):
        decode_single(_nested_cancel(DEEP))


def test_c27_control_without_loader_containment_wedges_the_inbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def uncontained(data: bytes) -> dict[str, Any]:  # the rejected rule: the loader's failure escapes
        start = data.index(b" ", len(MAGIC) + 9) + 1
        parsed: dict[str, Any] = json.loads(data[start : len(data) - len(COMMIT)])
        return parsed

    monkeypatch.setattr(broker_mod, "decode_single", uncontained)
    w = make_world(tmp_path)
    (w.queue / "inbox" / "000-bad.req").write_bytes(_nested_cancel(DEEP))
    (w.queue / "inbox" / "999-good.req").write_bytes(encode({"type": "status", "request_id": "999-good"}))
    with pytest.raises(RecursionError):
        w.broker.step()
    assert (w.queue / "inbox" / "000-bad.req").exists()  # the hazard: the bad request stays
    assert not (w.queue / "outbox" / "999-good.res").exists()  # and the next request is never served


# == N001: the exact row-c control ===========================================================================


def test_c24c_control_omitting_only_the_generation_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = make_world(tmp_path)
    e, r, code, _cid = _confirmed(w)
    real_apply = broker_mod.Broker._apply_override

    def elsewhere(self: broker_mod.Broker, challenge: dict[str, Any]) -> dict[str, Any]:
        self.generation += 5  # W-107c row c: the record is written under another generation
        try:
            return real_apply(self, challenge)
        finally:
            self.generation -= 5

    monkeypatch.setattr(broker_mod.Broker, "_apply_override", elsewhere)
    w.confirm(code)
    monkeypatch.undo()
    real_problem = broker_mod.Broker._override_problem

    def without_generation(self: broker_mod.Broker, job: Any) -> str | None:
        problem = real_problem(self, job)  # the rejected rule: every check except the generation one
        return None if problem == "was recorded under another journal generation" else problem

    monkeypatch.setattr(broker_mod.Broker, "_override_problem", without_generation)
    w.host.group_query_error = True
    w.restart()
    assert _row(w, e, r) == ("ended", "released (human-confirmed)", False, False, False)  # the hazard


assert os.sep
