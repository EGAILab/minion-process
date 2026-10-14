"""Witnesses and executed controls for implementation revision 3 (checkpoint r15 rule set, `docs/p3b/`).

- K-41 (R002): three-valued process observations; W-94 to W-96, C-18.
- K-44 (R010): total request validation; W-103, W-104, C-21.
- K-42 (R003): slot roles, literals, writable-location variables, the build working folder and the
  launch proof of every writable directory resource; W-97', W-98', W-98a, W-99', W-99a, W-99b, W-99b'',
  W-99c, W-99d; C-19, C-19b, C-19c, C-19d.
- K-46, K-47: no deletion outside queue state, cleanup refused; W-105, W-106, C-22.
- K-48' and K-48'' (R011): the registration lifecycle without cleanup, including the human-confirmed end;
  W-107', W-107a to W-107d; C-23 (two variants), C-24a to C-24c.

K-45: each matrix is generated from its declared dimensions. Each control substitutes the rejected rule in
memory, has its own green baseline (the paired witness, run on the real code), and asserts the failure of
its intended witness observation only.
"""

from __future__ import annotations

import ast
import itertools
import json
import os
import random
import shutil
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

from minion_process.hostqueue import broker as broker_mod
from minion_process.hostqueue import client, fsops, jobspec, layout, requests, walk
from minion_process.hostqueue import state as state_mod
from minion_process.hostqueue.framing import decode_single, encode
from minion_process.hostqueue.hostos import (
    EXITED,
    NO_SUCH_ID,
    OPEN_FAILS,
    QUERY_FAILS,
    STILL_ACTIVE,
    ProcessIdentity,
    SpawnFailed,
    liveness,
)

from .hostqueue_fake import pane_info
from .hostqueue_world import SHA, World, make_world

PACKAGE = Path(__file__).resolve().parent.parent / "minion_process" / "hostqueue"
GIB = 1024**3


def edit_profile(w: World, change: Callable[[dict[str, Any]], None]) -> None:
    data = yaml.safe_load(w.profile.read_text(encoding="utf-8"))
    change(data)
    w.profile.write_text(yaml.safe_dump(data), encoding="utf-8")


def launcher(data: dict[str, Any]) -> dict[str, Any]:
    queue: dict[str, Any] = data["gates"]["rust"]["queue"]
    return queue


def make_link(link: Path, target: Path) -> None:
    """A directory link: a junction on Windows (no privilege needed), a symbolic link elsewhere."""
    link.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:  # pragma: no cover - POSIX
        os.symlink(target, link, target_is_directory=True)


def finish(w: World, job_id: int, drained: bool = True) -> None:
    """The workload of `job_id` ends with a passing, drained result."""
    (w.queue / "jobs" / str(job_id) / "result").write_bytes(
        encode({"exit": 0, "gate_end": 0, "drained": drained})
    )
    job = w.job(job_id)
    w.host.finish(job.spec["group"], ProcessIdentity.from_record(job.runner) if job.runner else None)


def status(w: World) -> dict[str, Any]:
    return w.request({"type": "status"})


def copy_row(w: World, creator: int) -> dict[str, Any]:
    return next(c for c in status(w)["copies"] if c["creator"] == creator)


def held(w: World, path: str) -> bool:
    return (path, "exclusive") in w.broker.state.held_leases()


def _canon(path: Path) -> str:
    from minion_process.hostqueue.resources import canonical

    return canonical(path)


def journal(w: World) -> Path:
    return layout.journal_path(w.queue, w.broker.generation)


# == K-41 (R002) ===========================================================================================


def _expected_liveness(recorded: int | None, opened: str, birth: Any, exit_state: str) -> bool | None:
    """The oracle, written from the K-41 text, not from the implementation."""
    if opened == NO_SUCH_ID:
        return False  # the id does not exist: ended, whatever was recorded
    if opened == OPEN_FAILS:
        return None  # any inspection failure is unknown
    if recorded is None:
        return None  # unknown birth while the id exists: alive-or-unknown, whatever birth or exit
    if birth == QUERY_FAILS:
        return None
    if birth != recorded:
        return False  # a known birth that differs: the id was reused
    return {STILL_ACTIVE: True, EXITED: False, QUERY_FAILS: None}[exit_state]


W94 = list(
    itertools.product(
        [500, None],  # recorded birth: known, unknown
        [NO_SUCH_ID, OPEN_FAILS, "opened"],
        [500, 900, QUERY_FAILS],  # current birth: same, different, query fails
        [STILL_ACTIVE, EXITED, QUERY_FAILS],
    )
)


@pytest.mark.parametrize(("recorded", "opened", "birth", "exit_state"), W94)
def test_w94_liveness_matrix(recorded: int | None, opened: str, birth: Any, exit_state: str) -> None:
    assert liveness(recorded, opened, birth, exit_state) is _expected_liveness(
        recorded, opened, birth, exit_state
    )
    if recorded is None and opened != NO_SUCH_ID:
        assert liveness(recorded, opened, birth, exit_state) is None  # every unknown-birth cell but one


def _w95_world(tmp_path: Path) -> tuple[World, int, ProcessIdentity]:
    """The round-8 composition: the birth query fails at spawn, assignment fails, and the next birth query
    for the same live process returns a nonzero time."""
    w = make_world(tmp_path)
    stray = ProcessIdentity(9100, None)  # the birth query failed: unknown, never a number
    w.host.spawn_error = SpawnFailed("AssignProcessToJobObject failed: 5", stray)
    w.host.spawn_creates_group = False
    job_id = int(w.submit()["job_id"])
    w.host.processes[(9100, 133_000_000)] = True  # the same live process now answers with a birth time
    return w, job_id, stray


def test_w95_unknown_birth_keeps_the_reservation_across_restart(tmp_path: Path) -> None:
    w, job_id, _stray = _w95_world(tmp_path)
    for _ in range(2):
        w.broker.step()
        assert w.job(job_id).status == "uncertain"
        assert w.broker.state.reserved_bytes(w.host.clock, w.broker.policy) == 16 * GIB  # type: ignore[arg-type]
    w.restart()
    w.broker.step()
    assert w.job(job_id).status == "uncertain" and w.job(job_id).runner == {"pid": 9100, "start": None}
    assert w.broker.state.reserved_bytes(w.host.clock, w.broker.policy) == 16 * GIB  # type: ignore[arg-type]
    w.host.processes[(9100, 133_000_000)] = False  # the process id is gone: now it is ended
    w.broker.step()
    assert w.job(job_id).status == "ended" and w.job(job_id).proof == "inspected"


def test_c18_control_recording_unknown_birth_as_zero_releases_the_reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class LaxIdentity(ProcessIdentity):
        def __post_init__(self) -> None:  # the rejected rule: a number may stand for unknown
            pass

        @classmethod
        def from_record(cls, record: dict[str, object]) -> ProcessIdentity:
            return cls(int(str(record["pid"])), int(str(record["start"] or 0)))

    monkeypatch.setattr(broker_mod, "ProcessIdentity", LaxIdentity)
    w, job_id, _stray = _w95_world(tmp_path)
    w.broker.step()
    assert w.job(job_id).status == "ended"  # the hazard: live work released on a coerced 0


def test_w96_no_constant_stands_for_an_observation() -> None:
    offences = []
    for name in ("winos.py", "hostos.py", "gitops.py", "runner.py"):
        tree = ast.parse((PACKAGE / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
                last = node.values[-1]
                if isinstance(last, ast.Constant) or (
                    isinstance(last, ast.List | ast.Dict | ast.Tuple) and not getattr(last, "elts", True)
                ):
                    offences.append(f"{name}:{node.lineno}")
    assert offences == []
    for bad in (0, -1, True, 1.5):
        with pytest.raises(ValueError):
            ProcessIdentity(1, bad)  # type: ignore[arg-type]
    assert ProcessIdentity.from_record({"pid": 3, "start": None}) == ProcessIdentity(3, None)
    assert ProcessIdentity(3, None).as_record() == {"pid": 3, "start": None}


@pytest.mark.skipif(sys.platform != "win32", reason="the Windows adapter")
def test_w94_windows_adapter_maps_each_step(monkeypatch: pytest.MonkeyPatch) -> None:
    from minion_process.hostqueue import winos

    h = winos.WindowsHostOS(mutex_name="Local\\MinionProcessTest-K41")
    me = h.self_identity()
    assert me.start is not None and h.process_alive(me) is True
    assert h.process_alive(ProcessIdentity(me.pid, None)) is None  # alive-or-unknown
    assert h.process_alive(ProcessIdentity(0x7FFFFFF0, None)) is False  # no such id
    monkeypatch.setattr(h.k32, "GetExitCodeProcess", lambda handle, code: 0)
    assert h.process_alive(me) is None
    monkeypatch.setattr(h, "_times", lambda handle: None)
    assert h.self_identity().start is None  # never coerced to a number


# == K-44 (R010) ===========================================================================================

KINDS: list[Any] = [None, True, False, 0, 7, -1, 1.5, "", "x", [], [1], {}, {"a": 1}]

# Every field a handler reads, and the kind it needs: (field path, required, accepts).
_text = lambda v: isinstance(v, str) and bool(v.strip())  # noqa: E731
_count = lambda v: isinstance(v, int) and not isinstance(v, bool) and v >= 0  # noqa: E731
_optional_str = lambda v: v is None or isinstance(v, str)  # noqa: E731
_string = lambda v: isinstance(v, str)  # noqa: E731
FIELDS: dict[str, list[tuple[tuple[str, ...], bool, Callable[[Any], bool]]]] = {
    "submit": [
        (("class",), True, _text),
        (("profile",), True, _text),
        (("submitter",), True, lambda v: isinstance(v, dict)),
        (("submitter", "pane"), False, _text),
        (("submitter", "session"), False, _text),
        (("launcher",), True, _text),
        (("target",), True, _text),
        (("checkout",), True, _text),
        (("sha",), False, _text),
    ],
    "status": [(("job_id",), False, _count)],
    "cancel": [
        (("job_id",), True, _count),
        (("submitter",), True, lambda v: isinstance(v, dict)),
        (("submitter", "pane"), False, _text),
        (("submitter", "session"), False, _text),
    ],
    "unretain": [(("job_id",), True, _count)],
    "release": [(("job_id",), True, _count)],
    "policy-set": [(("policy",), True, lambda v: isinstance(v, dict)), (("decision",), False, _string)],
    "render": [(("text",), True, lambda v: isinstance(v, str)), (("pane",), False, _optional_str)],
    "undelivered": [
        (("hash",), True, _text),
        (("attempt",), True, _count),
        (("session",), False, _optional_str),
    ],
    "hook-confirm": [
        (("code",), True, lambda v: isinstance(v, str)),
        (("origin",), False, _optional_str),
        (("session",), False, _optional_str),
    ],
    "repair-inspect": [],
    "repair-quarantine": [],
    "repair-resume": [],
}
VALID: dict[str, dict[str, Any]] = {
    "submit": {
        "class": "build",
        "profile": "p",
        "submitter": {"pane": "w1:p9", "session": "z"},
        "launcher": "l",
        "target": "t",
        "checkout": "c",
        "sha": "s",
    },
    "status": {"job_id": 1},
    "cancel": {"job_id": 1, "submitter": {"pane": "w1:p9", "session": "z"}},
    "unretain": {"job_id": 1},
    "release": {"job_id": 99},
    "policy-set": {"policy": {}, "decision": "d"},
    "render": {"text": "t", "pane": "p"},
    "undelivered": {"hash": "h", "attempt": 1, "session": "s"},
    "hook-confirm": {"code": "c", "origin": "nobody", "session": "s"},
    "repair-inspect": {},
    "repair-quarantine": {},
    "repair-resume": {},
}
ABSENT = object()


def _cells(kind: str) -> Iterator[tuple[str, dict[str, Any], bool]]:
    """(id, request, malformed?) for every field position x every JSON kind, plus absence."""
    for field_path, required, accepts in FIELDS[kind]:
        for value in [*KINDS, ABSENT]:
            body = json.loads(json.dumps(VALID[kind]))
            holder = body
            for key in field_path[:-1]:
                holder = holder[key]
            if value is ABSENT:
                holder.pop(field_path[-1], None)
                bad = required
            else:
                holder[field_path[-1]] = value
                bad = not accepts(value)
            yield f"{'.'.join(field_path)}={value!r}", {"type": kind, **body}, bad


def test_w103_matrix_rejects_each_malformed_cell_alone(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    assert set(FIELDS) == set(requests.CHECKS)  # every request type is in the matrix
    expected: dict[str, tuple[str, bool]] = {}
    for kind in FIELDS:
        for cell, body, bad in _cells(kind):
            expected[client.put(w.queue, body, _type_check=False)] = (f"{kind} {cell}", bad)
    for value in KINDS:  # the discriminator and the top level
        # A string type the broker does not know is answered with an ordinary refusal, not rejected.
        expected[client.put(w.queue, {"type": value}, _type_check=False)] = (
            f"type={value!r}",
            not isinstance(value, str),
        )
        name = f"top-{len(expected)}"
        (w.queue / "inbox" / f"{name}.req").write_bytes(encode(value))  # type: ignore[arg-type]
        expected[name] = (f"top level {value!r}", True)  # never an object with a type
    missing = client.put(w.queue, {"type": "status"}, _type_check=False)
    (w.queue / "inbox" / f"{missing}.req").write_bytes(encode({"type": "status"}))  # no request_id
    expected[missing] = ("no request_id", True)
    w.broker.step()  # never raises
    for request_id, (cell, bad) in expected.items():
        rejected = (w.queue / "rejected" / f"{request_id}.reason").exists()
        answered = (w.queue / "outbox" / f"{request_id}.res").exists()
        if bad:
            assert rejected and not answered, cell
            reason = (w.queue / "rejected" / f"{request_id}.reason").read_text(encoding="utf-8")
            # a non-object top level is already refused by the framing layer; both reject it alone
            assert reason.startswith(("malformed request:", "unreadable request:")), cell
        else:
            assert answered or "request id does not match" in _reason(w, request_id), cell
    assert status(w)["ok"]  # the next valid request is served
    assert not w.host.spawned


def _reason(w: World, request_id: str) -> str:
    path = w.queue / "rejected" / f"{request_id}.reason"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _random_json(rng: random.Random, depth: int = 0) -> Any:
    choice = rng.randrange(8 if depth < 3 else 5)
    if choice == 0:
        return None
    if choice == 1:
        return rng.random() < 0.5
    if choice == 2:
        return rng.randrange(-5, 5)
    if choice == 3:
        return rng.random() * 10
    if choice == 4:
        return rng.choice(["", "x", "status", "submit", "cleanup", " "])
    if choice == 5:
        return [_random_json(rng, depth + 1) for _ in range(rng.randrange(3))]
    keys = ["type", "request_id", "job_id", "submitter", "class", "policy", "text", "code", "hash", "attempt"]
    body = {rng.choice(keys): _random_json(rng, depth + 1) for _ in range(rng.randrange(5))}
    if choice == 7:
        body["type"] = rng.choice([*requests.CHECKS, "nonsense"])
        body["request_id"] = "r"
    return body


def test_w104_validator_is_total_over_random_json() -> None:
    rng = random.Random(20261014)  # fixed seed, recorded here
    for _ in range(5000):
        value = _random_json(rng)
        result = requests.malformed(value)
        assert result is None or isinstance(result, str)


def test_c21_control_lookup_before_discriminator_check_wedges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = make_world(tmp_path)
    client.put(w.queue, {"type": []}, _type_check=False)
    monkeypatch.setattr(
        broker_mod,
        "malformed",
        lambda r: (requests.CHECKS.get(r.get("type")) or (lambda _r: None))(r),  # the round-8 order
    )
    with pytest.raises(TypeError):
        w.broker.step()  # the hazard: an unhashable discriminator raises on every pass


# == K-42 (R003): slots, literals, writable-location variables ==============================================


def _spec(w: World, klass: str = "evidence", **extra: Any) -> dict[str, Any]:
    request = {
        "type": "submit",
        "class": klass,
        "profile": str(w.profile),
        "launcher": "rust",
        "target": "gate",
        "checkout": str(w.root / "repo"),
        "sha": SHA,
        "submitter": {"pane": "w1:p1", "session": "s1"},
        **extra,
    }
    policy = w.broker.policy
    assert policy is not None
    return jobspec.build_spec(request, policy, policy.policy_id, 50, pane_info("s1"))


ROLES = ("whole", "option", "mount", "env")
SUFFIXES = ("", "/sub/x", "=x", ";x", "x", "/../x", "/./x", "/a:b")
PLACEHOLDERS = (("checkout", "read"), ("checkout", "write"), ("target", "write"), ("nope", "read"))


@pytest.mark.parametrize(
    ("role", "suffix", "placeholder", "access"),
    [(r, s, p, a) for r in ROLES for s in SUFFIXES for p, a in PLACEHOLDERS],
)
def test_w97_slot_matrix(tmp_path: Path, role: str, suffix: str, placeholder: str, access: str) -> None:
    w = make_world(tmp_path)
    slot = {"slot": "{" + placeholder + "}" + suffix, "access": access}

    def change(data: dict[str, Any]) -> None:
        q = launcher(data)
        if role == "whole":
            q["argv"] = ["tool", slot]
        elif role == "option":
            q["argv"] = ["tool", {**slot, "slot": "--out=" + slot["slot"]}]
        elif role == "mount":
            q["argv"] = ["docker", "run", "-v", {**slot, "slot": slot["slot"] + ":/work"}, "img"]
            q["container"] = {"paths": ["/work"]}
        else:
            q["argv"] = ["tool"]
            q["env"] = {"OUT": slot}

    edit_profile(w, change)
    valid = (
        suffix in ("", "/sub/x")
        and not (role == "env" and suffix)
        and placeholder != "nope"
        and (placeholder, access) != ("checkout", "write")
    )
    if not valid:
        with pytest.raises(jobspec.SpecError):
            _spec(w)
        return
    spec = _spec(w)
    value = spec["workdir"] if placeholder == "checkout" else spec["target"]["path"]
    effective = value + suffix.replace("/", os.sep)
    expected = {
        "whole": effective,
        "option": "--out=" + effective,
        "mount": effective + ":/work",
        "env": effective,
    }[role]
    received = spec["env"]["OUT"] if role == "env" else spec["argv"][3 if role == "mount" else 1]
    assert received == expected  # the unsplit effective value is exactly what the tool receives
    assert spec["slots"][0]["access"] == access


def test_w97_mount_form_needs_a_container_launcher_and_a_declared_path(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    slot = {"slot": "{target}:/work", "access": "write"}
    edit_profile(w, lambda d: launcher(d).update(argv=["docker", "-v", slot]))
    with pytest.raises(jobspec.SpecError, match="begin with a separator"):
        _spec(w)
    edit_profile(w, lambda d: launcher(d).update(container={"paths": ["/other"]}))
    with pytest.raises(jobspec.SpecError, match="not declared"):
        _spec(w)
    edit_profile(
        w, lambda d: launcher(d).update(argv=["docker", "-v", {"slot": "{target}", "access": "write"}])
    )
    with pytest.raises(jobspec.SpecError, match="mount slot"):
        _spec(w)


@pytest.mark.parametrize(
    ("container", "message"),
    [
        (True, "container must be false"),
        ({"paths": []}, "container must be false"),
        ({"paths": ["work"]}, "absolute container path"),
        ({"paths": ["//work"]}, "absolute container path"),
        ({"paths": ["/a/../b"]}, "not a plain name|'..'"),
    ],
)
def test_container_declaration_is_checked(tmp_path: Path, container: Any, message: str) -> None:
    w = make_world(tmp_path)
    edit_profile(w, lambda d: launcher(d).update(container=container))
    with pytest.raises(jobspec.SpecError, match=message):
        _spec(w)


def test_container_root_path_and_literal_container_paths(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    edit_profile(
        w,
        lambda d: launcher(d).update(
            argv=["docker", "-v", {"slot": "{target}:/", "access": "write"}, "-w", "/work"],
            container={"paths": ["/", "/work"]},
        ),
    )
    assert _spec(w)["argv"][-1] == "/work"  # a declared container path may stand alone


@pytest.mark.parametrize(
    "bad",
    [
        {"slot": "{target}"},
        {"slot": "{target}", "access": "write", "x": 1},
        {"slot": 5, "access": "write"},
        {"slot": "{target}", "access": "exec"},
        {"slot": "pre{target}", "access": "write"},
        {"slot": "{log}/x", "access": "write"},
        ["{target}"],
    ],
)
def test_w99c_slot_shape_and_access(tmp_path: Path, bad: Any) -> None:
    w = make_world(tmp_path)
    edit_profile(w, lambda d: launcher(d).update(argv=["tool", bad]))
    with pytest.raises(jobspec.SpecError):
        _spec(w)


def test_w99c_checkout_is_read_only_and_access_is_required(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    edit_profile(w, lambda d: launcher(d).update(argv=["tool", {"slot": "{checkout}", "access": "write"}]))
    with pytest.raises(jobspec.SpecError, match="cannot be given write access"):
        _spec(w)
    edit_profile(w, lambda d: launcher(d).update(argv=["tool", {"slot": "{checkout}"}]))
    with pytest.raises(jobspec.SpecError, match="exactly 'slot' and 'access'"):
        _spec(w)


ROUND_8_VALUES = ["\\\\host\\share\\cargo", "//host/share/cargo", "D:cargo", "E:", "\\\\?\\E:\\x"]


@pytest.mark.parametrize("value", ROUND_8_VALUES)
def test_w98_round8_values_are_refused_as_literals(tmp_path: Path, value: str) -> None:
    w = make_world(tmp_path)
    edit_profile(w, lambda d: launcher(d).update(env={"OUT_DIR": value}))
    with pytest.raises(jobspec.SpecError, match="K-42"):
        _spec(w)
    edit_profile(w, lambda d: launcher(d).update(env={"CARGO_HOME": value}))
    with pytest.raises(jobspec.SpecError, match="writable-location"):
        _spec(w)


def test_w98_round9_unsplit_example_is_refused(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    edit_profile(w, lambda d: launcher(d).update(env={"OUT": {"slot": "{target}=other", "access": "write"}}))
    with pytest.raises(jobspec.SpecError, match="exactly one placeholder"):
        _spec(w)
    edit_profile(
        w, lambda d: launcher(d).update(argv=["tool", {"slot": "--x={target}=other", "access": "write"}])
    )
    with pytest.raises(jobspec.SpecError, match="separator"):
        _spec(w)


@pytest.mark.parametrize("char", ["=", ";", '"', "'", "`", "\x01"])
def test_w98a_resource_spelled_with_a_delimiter_is_refused(tmp_path: Path, char: str) -> None:
    w = make_world(tmp_path)
    name = f"odd{char}target"
    if char in ('"', "\x01"):  # not creatable on Windows: the spelling rule alone refuses it
        assert jobspec.spelling_problem(str(w.root / name)) is not None
        return
    (w.root / "targets" / name).mkdir()
    edit_profile(w, lambda d: d["build_queue"]["targets"]["gate"].update(path=str(w.root / "targets" / name)))
    with pytest.raises(jobspec.SpecError, match="W-98a"):
        _spec(w)


@pytest.mark.parametrize("name", ["cargo_home", "Cargo_Home", "CARGO_HOME", "xdg_cache_home", "Tmp"])
def test_w99_writable_location_names_are_kit_only(tmp_path: Path, name: str) -> None:
    w = make_world(tmp_path)
    edit_profile(w, lambda d: launcher(d).update(env={name: "x"}))
    with pytest.raises(jobspec.SpecError):
        _spec(w)
    edit_profile(w, lambda d: (launcher(d).pop("env", None), d["build_queue"].update(inherit_env=[name])))
    with pytest.raises(jobspec.SpecError):
        _spec(w)


@pytest.mark.parametrize(
    "change",
    [
        lambda d: launcher(d).update(env={"Foo": "a", "FOO": "b"}),
        lambda d: launcher(d).update(env={"cargo_target_dir": "a"}),
        lambda d: launcher(d).update(env={"minion_job": "a"}),
        lambda d: d["build_queue"].update(inherit_env=["Path", "PATH"]),
        lambda d: d["build_queue"].update(inherit_env=[3]),
        lambda d: d["build_queue"].update(inherit_env="PATH"),
        lambda d: launcher(d).update(env={"X": 3}),
    ],
)
def test_w99_names_compare_case_insensitively(tmp_path: Path, change: Any) -> None:
    w = make_world(tmp_path)
    edit_profile(w, change)
    with pytest.raises(jobspec.SpecError):
        _spec(w)


@pytest.mark.parametrize(
    "literal",
    ["a/b", "a\\b", "C:x", "--x=C:y", "a;D:z", "a,b:c", "..", "x..y", "x\x01", "{target}", "pre{checkout}"],
)
def test_w99a_literal_classes_are_refused(tmp_path: Path, literal: str) -> None:
    w = make_world(tmp_path)
    edit_profile(w, lambda d: launcher(d).update(argv=["tool", literal]))
    with pytest.raises(jobspec.SpecError):
        _spec(w)


def test_w99a_ordinary_literals_are_accepted(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    literals = [
        "--release",
        "-p",
        "minion-agent",
        "rust:1.85",
        "{job_label}",
        "--label=minion.job={job_label}",
    ]
    edit_profile(
        w, lambda d: launcher(d).update(argv=["tool", *literals], env={"JOBS": "4", "TAG": "{job_label}"})
    )
    spec = _spec(w)
    assert spec["argv"][1:] == [*literals[:4], spec["job_label"], f"--label=minion.job={spec['job_label']}"]
    assert spec["env"]["TAG"] == spec["job_label"] and spec["env"]["JOBS"] == "4"


def test_w99b_build_runs_in_its_own_working_folder(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    job_id = int(w.submit("build")["job_id"])
    spec = w.job(job_id).spec
    spawned = w.host.spawned[0]
    assert Path(spawned["cwd"]) == Path(spec["workdir"]) != Path(spec["checkout"])
    assert spec["argv"][-1] == spec["checkout"]  # the build reaches its checkout only through {checkout}
    assert ([spec["workdir"], "exclusive"]) in spec["leases"] and os.path.isdir(spec["workdir"])
    runner_input = decode_single((w.queue / "jobs" / str(job_id) / "input").read_bytes())
    assert runner_input["cwd"] == spec["workdir"]  # a relative output lands in the job's own folder


def test_build_working_folder_that_already_exists_is_refused(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    job_id = w.broker.state.next_job_id
    (w.root / "exec" / f"host-test-job-{job_id}").mkdir()
    w.submit("build")
    assert w.job(job_id).status == "refused" and "already exists" in str(w.job(job_id).reason)


def test_policy_id_is_a_plain_name(tmp_path: Path) -> None:
    from minion_process.hostqueue.policy import PolicyError, parse

    from .hostqueue_world import policy_dict

    for bad in ("..\\x", "a/b", "", "a b", ".x", 3):
        with pytest.raises(PolicyError):
            parse(policy_dict(tmp_path, policy_id=bad))
    assert parse(policy_dict(tmp_path, policy_id="host-1.v2")).policy_id == "host-1.v2"


# -- controls C-19 and C-19b: the revision-2 recognizer, kept verbatim as the rejected rule ---------------


def _revision2_path_like(token: str) -> list[str]:
    found: list[str] = []
    for piece in token.replace("=", "\n").split("\n"):
        if len(piece) > 2 and piece[0].isalpha() and piece[1] == ":" and piece[2] in "\\/":
            found.append(piece[:2] + piece[2:].split(":", 1)[0])
        found += [piece.split(":", 1)[0]] if (piece.startswith("/") and os.sep == "/") else []
    return found


def test_c19_control_drive_only_recognizer_accepts_round8_values() -> None:
    for value in ("\\\\host\\share\\cargo", "D:cargo"):
        assert _revision2_path_like(value) == []  # the hazard: no path seen, so nothing is checked


def test_c19b_control_split_check_passes_while_the_unsplit_value_is_spawned(tmp_path: Path) -> None:
    cache = str(tmp_path / "cache")
    value = cache + "=other"
    fragments = _revision2_path_like(value)
    assert fragments == [cache]  # each fragment is the leased cache, so the old check passes
    assert value != cache  # while the tool would receive the unsplit value


# == K-42a': the launch proof of every writable directory resource ==========================================

RESOURCES = ("working folder", "target", "cache", "temporary folder", "log directory")
STATES = ("ordinary", "inward", "outward", "dangling", "deep", "enumeration", "inspection")


def _proof_world(tmp_path: Path) -> World:
    w = make_world(tmp_path)
    (w.root / "cache").mkdir()
    edit_profile(
        w,
        lambda d: (
            d["build_queue"].update(caches={"cargo-home": str(w.root / "cache")}),
            launcher(d).update(cache_env={"CARGO_HOME": "cargo-home"}),
        ),
    )
    return w


def _resource_path(w: World, kind: str, job_id: int) -> Path:
    return {
        "working folder": w.root / "exec" / f"host-test-job-{job_id}",
        "target": w.root / "targets" / "gate",
        "cache": w.root / "cache",
        "temporary folder": w.root / "exec" / f"host-test-job-{job_id}-tmp",
        "log directory": w.root / "logs",
    }[kind]


class _FailingEntry:
    def __init__(self, entry: os.DirEntry[str]) -> None:
        self.path = entry.path

    def stat(self, follow_symlinks: bool = True) -> os.stat_result:
        raise PermissionError("inspection denied")


class _Listing:
    def __init__(self, items: list[Any]) -> None:
        self.items = items

    def __enter__(self) -> list[Any]:
        return self.items

    def __exit__(self, *exc: object) -> None:
        return None


def _plant(tmp_path: Path, w: World, resource: Path, state: str, monkeypatch: pytest.MonkeyPatch) -> None:
    resource.mkdir(parents=True, exist_ok=True)
    if state == "ordinary":
        (resource / "out").mkdir(exist_ok=True)
        (resource / "out" / "f.txt").write_text("x")
    elif state == "inward":
        make_link(resource / "out", w.root / "targets" / "gate2")
    elif state == "outward":
        (tmp_path / "outside").mkdir(exist_ok=True)
        make_link(resource / "out", tmp_path / "outside")
    elif state == "dangling":
        gone = tmp_path / "gone"
        gone.mkdir()
        make_link(resource / "out", gone)
        gone.rmdir()
    elif state == "deep":
        make_link(resource / "a" / "b" / "c", w.root / "targets" / "gate2")
    else:
        real = os.scandir
        target = os.path.normcase(str(resource))

        def scandir(path: Any) -> Any:
            if os.path.normcase(str(path)) != target:
                return real(path)
            if state == "enumeration":
                raise PermissionError("enumeration denied")
            with real(path) as listing:
                return _Listing([_FailingEntry(e) for e in listing])

        (resource / "f.txt").write_text("x")
        monkeypatch.setattr(walk.os, "scandir", scandir)


@pytest.mark.parametrize(("kind", "state"), [(k, s) for k in RESOURCES for s in STATES])
def test_w99b2_every_writable_resource_is_proved_at_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, state: str
) -> None:
    w = _proof_world(tmp_path)
    job_id = w.broker.state.next_job_id
    resource = _resource_path(w, kind, job_id)
    if kind == "working folder":  # created by the checkout itself, during preparation
        w.git.plant = lambda workdir: _plant(tmp_path, w, workdir, state, monkeypatch)
    else:
        _plant(tmp_path, w, resource, state, monkeypatch)
    w.submit("evidence", sha=SHA)
    job = w.job(job_id)
    if state == "ordinary":
        assert job.status == "running" and len(w.host.spawned) == 1
        assert _canon(resource) in {p["path"] for p in _proofs(w, job_id)}
        return
    assert job.status == "refused" and w.host.spawned == []  # refused before spawning
    assert f"launch proof failed (K-42a'): {kind}" in str(job.reason)
    assert os.path.lexists(resource)  # nothing was cleaned to make the proof pass


def _proofs(w: World, job_id: int) -> list[dict[str, Any]]:
    records = [r for r in _records(w) if r["kind"] == "running" and r["job_id"] == job_id]
    return list(records[-1]["proofs"])


def _records(w: World) -> list[dict[str, Any]]:
    from minion_process.hostqueue.journal import read

    return read(journal(w)).records


def test_w99b2_round11_junction_at_cargo_home_registry_is_refused(tmp_path: Path) -> None:
    w = _proof_world(tmp_path)
    make_link(w.root / "cache" / "registry", tmp_path)
    job_id = int(w.submit("evidence", sha=SHA)["job_id"])
    assert w.job(job_id).status == "refused" and "cache" in str(w.job(job_id).reason) and not w.host.spawned


def test_w99b2_walk_time_and_entry_count_are_recorded(tmp_path: Path) -> None:
    w = _proof_world(tmp_path)
    (w.root / "cache" / "x").mkdir()
    (w.root / "cache" / "x" / "f").write_text("y")
    job_id = int(w.submit("evidence", sha=SHA)["job_id"])
    proofs = {p["path"]: p for p in _proofs(w, job_id)}
    cache = proofs[_canon(w.root / "cache")]
    assert cache["entries"] == 2 and cache["seconds"] >= 0
    assert len(proofs) == 5


def test_w99d_committed_link_in_the_worktree_is_refused(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    w.git.plant = lambda workdir: make_link(workdir / "linked", workdir / "src")
    job_id = int(w.submit("evidence", sha=SHA)["job_id"])
    assert w.job(job_id).status == "refused" and "working folder" in str(w.job(job_id).reason)
    assert not w.host.spawned


def test_prove_tree_edges(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    roots = [tmp_path]
    assert walk.prove_tree(roots, tmp_path / "missing").entries == 0  # not created yet
    (tmp_path / "file").write_text("x")
    with pytest.raises(walk.Unproven, match="cannot enumerate"):
        walk.prove_tree(roots, tmp_path / "file")
    with pytest.raises(walk.Unproven, match="outside every allowed root"):
        walk.prove_tree([tmp_path / "other"], tmp_path / "file")
    (tmp_path / "d" / "e").mkdir(parents=True)
    real = os.scandir

    def vanished(path: Any) -> Any:
        if str(path).endswith("e"):
            raise FileNotFoundError(path)
        return real(path)

    monkeypatch.setattr(walk.os, "scandir", vanished)
    with pytest.raises(walk.Unproven, match="vanished"):
        walk.prove_tree(roots, tmp_path / "d")


def test_c19c_control_without_the_walk_launches_the_redirected_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = _proof_world(tmp_path)
    w.git.plant = lambda workdir: make_link(workdir / "out", w.root / "targets" / "gate2")
    monkeypatch.setattr(broker_mod.Broker, "_prove_resources", lambda self, job: [])  # the rejected rule
    job_id = int(w.submit("evidence", sha=SHA)["job_id"])
    assert w.job(job_id).status == "running" and len(w.host.spawned) == 1  # the hazard


@pytest.mark.parametrize("kind", ["target", "cache"])
def test_c19d_control_walking_the_working_folder_only_launches_resource_redirects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    w = _proof_world(tmp_path)
    make_link(_resource_path(w, kind, 0) / "out", w.root / "targets" / "gate2")
    original = broker_mod.Broker._writable_resources
    monkeypatch.setattr(
        broker_mod.Broker,
        "_writable_resources",
        lambda self, job: [r for r in original(self, job) if r[0] == "working folder"],  # revision 10 scope
    )
    job_id = int(w.submit("evidence", sha=SHA)["job_id"])
    assert w.job(job_id).status == "running"  # the hazard


# == K-46, K-47: no deletion outside queue state; cleanup refused ===========================================


def test_w105_cleanup_submission_is_refused_without_admission_or_lease(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    before = w.broker.state.next_job_id
    response = w.submit("cleanup")
    assert response == {
        "ok": False,
        "error": "cleanup is not supported in 0.4.0",
        "request_id": response["request_id"],
    }
    kinds = [r["kind"] for r in _records(w)]
    assert "reject" in kinds and w.broker.state.next_job_id == before
    assert w.broker.state.held_leases() == [] and not w.host.spawned


def test_c22_control_admitting_cleanup_fails_w105(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w = make_world(tmp_path)
    real = broker_mod.build_spec

    def revision2(request: dict[str, Any], *a: Any) -> dict[str, Any]:
        if request.get("class") == "cleanup":  # the rejected rule: cleanup is an admitted class
            return {"class": "cleanup", "leases": [], "submitter": request["submitter"]}
        return real(request, *a)

    monkeypatch.setattr(broker_mod, "build_spec", revision2)
    w.host.memory = 0  # observe the admission decision only
    assert w.submit("cleanup")["ok"] is True  # the hazard: W-105's refusal fails


def test_w106_no_deletion_or_rename_outside_the_queue_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    touched: list[Path] = []
    for name in ("unlink", "replace"):
        real = getattr(fsops, name)

        def record(roots: Any, *paths: Path, _real: Any = real) -> Any:
            touched.extend(paths)
            return _real(roots, *paths)

        monkeypatch.setattr(fsops, name, record)
    real_publish = fsops.publish

    def publish(roots: Any, temp: Path, final: Path, rename: Any) -> None:
        touched.extend([temp, final])
        real_publish(roots, temp, final, rename)

    monkeypatch.setattr(fsops, "publish", publish)
    w = make_world(tmp_path)
    job_id = int(w.submit("evidence", sha=SHA)["job_id"])
    client.put(w.queue, {"type": "cancel", "job_id": []}, _type_check=False)  # moved to rejected/
    finish(w, job_id)
    w.broker.step()
    with journal(w).open("ab") as handle:
        handle.write(b"torn tail")  # a crash mid-append
    w.restart()
    w.submit("build")
    assert touched and all(str(p).startswith(str(w.queue) + os.sep) for p in touched), touched
    assert os.path.isdir(w.job(job_id).spec["workdir"])  # the execution copy is never removed


def test_w106_only_fsops_and_the_queue_folder_delete() -> None:
    callers = []
    for path in PACKAGE.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            deleting = ("unlink", "rmdir", "rmtree", "remove", "removedirs")
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in deleting
            ):
                callers.append(f"{path.name}:{node.lineno}:{ast.unparse(node.func)}")
    # Every delete goes through fsops.unlink, whose callers name the queue folder as their only root.
    assert all(":fsops.unlink" in c or c.startswith("fsops.py:") for c in callers), callers
    assert not hasattr(fsops, "rmdir")


# == K-48' and K-48'' (R011): the registration lifecycle ====================================================


def _evidence(w: World) -> tuple[int, str]:
    job_id = int(w.submit("evidence", sha=SHA)["job_id"])
    return job_id, str(w.job(job_id).spec["workdir"])


def _refused_naming(w: World, path: str) -> None:
    """W-107a: a later job naming the copy, or a path inside it, is refused at submit."""
    for checkout in (path, os.path.join(path, "src")):
        response = w.submit("build", checkout=checkout)
        assert response["ok"] is False and "registered copy of job" in response["error"], response


def test_w107_row1_released_in_the_same_step(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    e, r = _evidence(w)
    assert held(w, r) and copy_row(w, e)["state"] == "held"
    _refused_naming(w, r)
    finish(w, e)
    w.broker.step()
    assert w.job(e).status == "ended" and w.job(e).proof == "inspected"
    assert not held(w, r) and copy_row(w, e)["state"] == "released" and os.path.isdir(r)
    _refused_naming(w, r)


def test_w107_row2_released_after_restart(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    e, r = _evidence(w)
    finish(w, e)
    w.broker.step()
    assert w.restart().mode == "normal"
    assert not held(w, r) and copy_row(w, e)["state"] == "released" and os.path.isdir(r)
    _refused_naming(w, r)


def test_w107_row3_cut_end_record_then_repair(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    e, r = _evidence(w)
    size = journal(w).stat().st_size
    finish(w, e)
    w.broker.step()
    data = journal(w).read_bytes()
    journal(w).write_bytes(data[: size + 7])  # the end record is cut mid-write
    w.restart()
    assert w.job(e).status == "running" and held(w, r)  # replay: not ended, so held
    w.broker.step()  # the K-41 outcome after repair: the workload is proven ended
    assert w.job(e).status == "ended" and not held(w, r) and copy_row(w, e)["state"] == "released"
    _refused_naming(w, r)


def test_w107_row4_uncertain_at_restart_stays_held(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    e, r = _evidence(w)
    w.host.group_query_error = True
    w.broker.step()
    assert w.job(e).status == "uncertain"
    w.restart()
    w.broker.step()
    assert w.job(e).status == "uncertain" and held(w, r) and copy_row(w, e)["state"] == "held"
    _refused_naming(w, r)


def test_c23_control_creator_to_cleanup_transfer_strands_the_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = state_mod.QueueState.held_leases

    def transferred(self: state_mod.QueueState) -> list[tuple[str, str]]:
        # The rejected revision-4 rule: the ended creator's copy lease passes to a cleanup holder, which is
        # never admitted in 0.4.0, so the lease is held for good.
        found = real(self)
        for copy in self.copies.values():
            creator = self.jobs[copy["creator"]]
            if creator.status == "ended":
                found.append((copy["path"], "exclusive"))
        return found

    monkeypatch.setattr(state_mod.QueueState, "held_leases", transferred)
    w = make_world(tmp_path)
    e, r = _evidence(w)
    finish(w, e)
    w.broker.step()
    assert held(w, r)  # the hazard: W-107' row 1 expects no lease after E ends


def test_c23_control_release_without_proof_frees_an_uncertain_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = state_mod.Job.run_leases

    def unproven(self: state_mod.Job) -> list[tuple[str, str]]:
        leases = real(self)  # the rejected rule: release the copy when the end is not proven
        return [
            lease for lease in leases if self.status != "uncertain" or lease[0] != self.spec.get("workdir")
        ]

    monkeypatch.setattr(state_mod.Job, "run_leases", unproven)
    w = make_world(tmp_path)
    e, r = _evidence(w)
    w.host.group_query_error = True
    w.broker.step()
    w.restart()
    assert w.job(e).status == "uncertain" and not held(w, r)  # the hazard: W-107' row 4 expects held


def test_w107b_manual_removal_is_reported_absent_and_nothing_else_changes(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    e, r = _evidence(w)
    finish(w, e)
    w.broker.step()
    shutil.rmtree(r)  # the Owner removes the copy by hand (inside this test's sandbox)
    assert copy_row(w, e)["state"] == "released, absent"
    assert w.restart().mode == "normal" and w.broker.unsafe == []
    assert copy_row(w, e)["state"] == "released, absent"
    other = w.submit("build")  # an unrelated path is admitted as usual
    assert other["ok"] and w.job(int(other["job_id"])).status == "running"
    _refused_naming(w, r)  # the registered path itself stays refused


def test_registered_copy_check_at_launch_and_damaged_manifest(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    e, r = _evidence(w)
    w.host.memory = 0  # hold the next job in the queue
    later = w.submit("build", checkout=str(w.root / "repo"))
    w.broker.state.copies["late"] = {"path": str(w.root / "repo"), "creator": e, "damaged": False}
    w.host.memory = 64 * GIB
    w.host.finish(w.job(e).spec["group"])
    finish(w, e)
    w.broker.step()
    w.broker.step()
    assert w.job(int(later["job_id"])).status == "refused"
    assert "registered copy" in str(w.job(int(later["job_id"])).reason)
    del w.broker.state.copies["late"]
    os.remove(os.path.join(r, "Cargo.toml"))  # the manifest no longer matches the disk
    assert w.restart().mode == "normal"
    assert copy_row(w, e)["state"] == "damaged"
    w.restart()
    assert copy_row(w, e)["state"] == "damaged"  # recorded once, still registered


def test_register_marker_recovery(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    e, _r = _evidence(w)
    marker = w.queue / "effects" / "register" / str(w.job(e).spec["job_label"])
    marker.write_bytes(b"garbage")
    assert w.restart().mode == "normal" and copy_row(w, e)["state"] == "damaged"
    w2 = make_world(tmp_path / "second")
    e2, _r2 = _evidence(w2)
    label = str(w2.job(e2).spec["job_label"])
    w2.broker.state.copies.pop(label)  # as if the register record were lost from the journal
    report = w2.broker._reconcile()
    assert any(f"register/{label}: restored" in o for o in report)
    (w2.queue / "effects" / "register" / label).write_bytes(b"garbage")
    w2.broker.state.copies.pop(label, None)
    w2.broker._reconcile()
    assert any("unreadable and not in the journal" in u for u in w2.broker.unsafe)
    w2.broker.unsafe = []
    (w2.queue / "effects" / "register" / label).unlink()
    w2.broker.markers.publish("register", (label,), {"path": "x", "job_id": 999, "manifest": []}, 0)
    w2.broker._reconcile()
    assert any("copy of unknown job 999" in u for u in w2.broker.unsafe)


# -- K-48'': the human-confirmed end (W-107c, W-107d, C-24a to C-24c) ---------------------------------------


def _confirmed(w: World) -> tuple[int, str, str, str]:
    """E holds R; inspection is unknown, so E is uncertain; the Owner confirms its release."""
    e, r = _evidence(w)
    w.host.group_query_error = True
    w.broker.step()
    assert w.job(e).status == "uncertain"
    challenge = w.request({"type": "release", "job_id": e})
    assert challenge["ok"], challenge
    return e, r, challenge["code"], challenge["challenge"]


def _row(w: World, e: int, r: str) -> tuple[str, str, bool, bool, bool]:
    job = w.job(e)
    reserved = w.broker.state.reserved_bytes(w.host.clock, w.broker.policy) > 0  # type: ignore[arg-type]
    return job.status, copy_row(w, e)["state"], held(w, r), reserved, job.eligible


def test_w107c_row_a_intact_override_is_restored(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    e, r, code, _cid = _confirmed(w)
    assert w.confirm(code)["ok"]
    assert _row(w, e, r) == ("ended", "released (human-confirmed)", False, False, False)
    w.restart()
    w.broker.step()  # inspection is still unknown; the confirmation is not second-guessed
    assert _row(w, e, r) == ("ended", "released (human-confirmed)", False, False, False)
    assert w.job(e).outcome == "human-confirmed"
    _refused_naming(w, r)


def test_w107d_human_confirmed_end_carries_no_machine_proof(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    e, _r, code, _cid = _confirmed(w)
    w.confirm(code)
    ended = [x for x in _records(w) if x["kind"] == "ended" and x["job_id"] == e][-1]
    assert ended["proof"] == "human-confirmed" and ended["eligible"] is False
    job = next(j for j in status(w)["jobs"] if j["job_id"] == e)
    assert job["end"] == "human-confirmed" and job["evidence"].startswith("not-eligible")


def test_w107c_row_b_journal_record_unreadable(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    e, r, code, _cid = _confirmed(w)
    size = journal(w).stat().st_size
    w.confirm(code)
    journal(w).write_bytes(journal(w).read_bytes()[:size])  # the confirmed release never reached the journal
    w.restart()
    w.broker.step()
    assert _row(w, e, r) == ("uncertain", "held", True, True, False)
    assert w.confirm(code)["error"] == "challenge already used"  # a fresh confirmation is needed (W-67)
    _refused_naming(w, r)


def test_w107c_row_b_confirmation_marker_unreadable(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    e, r, code, cid = _confirmed(w)
    w.confirm(code)
    (w.queue / "effects" / "confirm" / cid).write_bytes(b"garbage")
    report = w.restart()
    assert any("unreadable confirmation marker" in o for o in report.recovery)
    assert _row(w, e, r) == ("uncertain", "held", True, True, False)
    assert "not restored" in str(w.job(e).reason)
    assert w.confirm(code)["error"] == "challenge already used"


def test_w107c_row_c_record_from_another_generation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w = make_world(tmp_path)
    e, r, code, _cid = _confirmed(w)
    real = broker_mod.Broker._apply_override

    def elsewhere(self: broker_mod.Broker, challenge: dict[str, Any]) -> dict[str, Any]:
        self.generation += 5  # the record is written as if under another generation
        try:
            return real(self, challenge)
        finally:
            self.generation -= 5

    monkeypatch.setattr(broker_mod.Broker, "_apply_override", elsewhere)
    w.confirm(code)
    monkeypatch.undo()
    w.host.group_query_error = True
    report = w.restart()
    assert any("another journal generation" in o for o in report.recovery)
    assert _row(w, e, r) == ("uncertain", "held", True, True, False)
    assert w.confirm(code)["error"] == "challenge already used"
    _refused_naming(w, r)


def test_override_problem_rows(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    e, _r, code, cid = _confirmed(w)
    w.confirm(code)
    job = w.job(e)
    assert w.broker._override_problem(job) is None
    job.override = None
    assert "does not match" in str(w.broker._override_problem(job))
    job.override = {"challenge_id": cid, "generation": w.broker.generation}
    w.broker.state.challenges[cid]["state"] = "open"
    assert "no consumed confirmation" in str(w.broker._override_problem(job))


def test_c24a_control_routing_intact_override_through_the_uncertain_arm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = make_world(tmp_path)
    e, r, code, _cid = _confirmed(w)
    w.confirm(code)
    monkeypatch.setattr(
        broker_mod.Broker, "_override_problem", lambda self, job: "treated as uncertain proof"
    )
    w.restart()
    assert _row(w, e, r) == ("uncertain", "held", True, True, False)  # the hazard: W-107c row a fails


def test_c24b_control_recording_the_confirmation_as_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = make_world(tmp_path)
    e, _r, code, _cid = _confirmed(w)
    real = broker_mod.Broker._record

    def as_proof(self: broker_mod.Broker, kind: str, **fields: Any) -> dict[str, Any]:
        if kind == "ended" and fields.get("proof") == "human-confirmed":
            fields["proof"] = "inspected"  # the rejected rule: the Owner statement as machine proof
        return real(self, kind, **fields)

    monkeypatch.setattr(broker_mod.Broker, "_record", as_proof)
    w.confirm(code)
    ended = [x for x in _records(w) if x["kind"] == "ended" and x["job_id"] == e][-1]
    assert ended["proof"] == "inspected"  # the hazard: W-107d's no-machine-proof observation fails


def test_c24c_control_restoring_an_ambiguous_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Row c: an override recorded under another generation is restored anyway.
    w = make_world(tmp_path)
    e, r, code, cid = _confirmed(w)
    w.confirm(code)
    (w.queue / "effects" / "confirm" / cid).write_bytes(b"garbage")
    monkeypatch.setattr(broker_mod.Broker, "_override_problem", lambda self, job: None)
    w.restart()
    assert _row(w, e, r) == ("ended", "released (human-confirmed)", False, False, False)  # the hazard


def test_c24c_control_restoring_a_cut_override_from_its_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Row b: the journal lost the confirmed release, and the rejected rule restores it from the marker.
    w = make_world(tmp_path)
    e, r, code, cid = _confirmed(w)
    size = journal(w).stat().st_size
    w.confirm(code)
    journal(w).write_bytes(journal(w).read_bytes()[:size])
    real = broker_mod.Broker._reconcile_overrides

    def from_marker(self: broker_mod.Broker, outcomes: list[str], add: Any) -> None:
        real(self, outcomes, add)
        if isinstance(self.markers.read("confirm", cid), dict):
            add(
                "ended",
                job_id=e,
                outcome="human-confirmed",
                eligible=False,
                reason="from marker",
                proof="human-confirmed",
                override={"challenge_id": cid, "generation": self.generation},
            )

    monkeypatch.setattr(broker_mod.Broker, "_reconcile_overrides", from_marker)
    w.restart()
    assert _row(w, e, r) == ("ended", "released (human-confirmed)", False, False, False)  # the hazard


def test_session_start_lists_registered_copies(tmp_path: Path) -> None:
    from minion_process.hostqueue import commands

    w = make_world(tmp_path)
    e, r = _evidence(w)
    _summary, copies = commands._queue_summary(w.queue)
    assert copies == [{"copy": w.job(e).spec["job_label"], "creator": e, "state": "held", "path": r}]


def test_state_rejects_records_for_unknown_copies_and_jobs(tmp_path: Path) -> None:
    q = state_mod.QueueState()
    with pytest.raises(state_mod.InvariantError, match="unknown job"):
        q.apply({"kind": "register", "seq": 1, "copy_id": "c", "path": "p", "job_id": 7}, 0.0)
    q.apply(
        {
            "kind": "accept",
            "seq": 2,
            "request_id": "r",
            "job_id": 1,
            "spec": {"class": "build", "leases": []},
        },
        0.0,
    )
    q.jobs[1].status = "ended"
    q.jobs[1].outcome = "passed"
    with pytest.raises(state_mod.InvariantError, match="no confirmed release"):
        q.apply({"kind": "override-unrestored", "seq": 3, "job_id": 1, "reason": "x"}, 0.0)


def test_broker_records_a_bounded_bypass(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    shutil.copytree(w.root / "repo", w.root / "repo2")
    first = int(w.submit("build")["job_id"])  # holds the gate target
    w.host.memory = 0
    blocked = int(w.submit("build", checkout=str(w.root / "repo2"))["job_id"])  # waits on the gate target
    later = int(w.submit("build", target="gate2", checkout=str(w.root / "repo2"))["job_id"])
    w.host.memory = 64 * GIB
    w.broker.step()
    assert w.job(first).status == "running"
    assert w.job(blocked).status == "submitted" and w.job(blocked).bypasses == 1
    assert w.job(later).status == "running"


def test_a_job_is_never_refused_for_its_own_registered_copy(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    e, _r = _evidence(w)
    w.broker._refuse_registered(w.job(e).spec)  # its own copy: no refusal (a requeued relaunch)
    with pytest.raises(jobspec.SpecError, match="registered copy"):
        w.broker._refuse_registered({**w.job(e).spec, "job_id": e + 100})
