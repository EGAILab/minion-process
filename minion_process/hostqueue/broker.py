"""The host broker: the only writer of queue state (B-1 to B-33, K-1 to K-40 of `docs/p3b/`).

One `Broker` holds the host-wide OS mutex for its whole life. Each `step()` does three things:

1. answers inbox requests;
2. checks every active job for proof that it ended;
3. admits jobs.

Every state change is a flushed journal record written before the change is acted on. Every protected
effect is guarded by a write-ahead marker published before the effect. The broker never kills, stops or
signals a process, and it sends no keystrokes to any pane (K-1).
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import secrets
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from . import layout
from .contain import Contained, assert_inside
from .framing import FramingError, decode_single, encode
from .gitops import GitOps
from .hostos import HostOS, ProcessIdentity
from .jobspec import SpecError, build_spec, drift
from .journal import Journal, Replay, parse
from .markers import MarkerExists, Markers, Unreadable
from .policy import Policy, PolicyError
from .policy import parse as parse_policy
from .state import TERMINAL, InvariantError, Job, QueueState, decide
from .walk import classify, entries, files, remove_entry

CHALLENGE_SECONDS = 15 * 60
CLEANUP_BATCH = 200


class BrokerRefused(RuntimeError):
    """The broker cannot start or must stop; the message says why."""


@dataclass
class StartReport:
    mode: str
    generation: int
    abandoned: bool
    recovery: list[str] = field(default_factory=list)


class Broker:
    def __init__(self, root: Path, host: HostOS, git: GitOps, python: str | None = None) -> None:
        self.root = root
        self.host = host
        self.git = git
        self.python = python or sys.executable
        self.instance = secrets.token_hex(6)
        self.markers = Markers(root, host, "broker-" + self.instance)
        self.state = QueueState()
        self.journal: Journal | None = None
        self.generation = 0
        self.policy: Policy | None = None
        self.repair_challenges: dict[str, dict[str, Any]] = {}  # repair mode without a journal: in memory
        self.replay: Replay | None = None
        self.cleanup_progress: dict[int, list[tuple[str, str]]] = {}
        self.pending: list[tuple[str, dict[str, Any]]] = []
        self.unsafe: list[str] = []
        self.generation_unknown = False

    # == start ===============================================================================================

    def start(self, repair: bool = False) -> StartReport:
        mutex = self.host.acquire_broker_mutex()
        if mutex.error:
            raise BrokerRefused(f"broker mutex unavailable: {mutex.error}")
        if not mutex.acquired:
            raise BrokerRefused("another broker holds the host mutex")
        local = self.host.is_local_fixed_volume(self.root)
        if local is not True:
            self.host.release_broker_mutex()
            raise BrokerRefused(f"queue folder is not on a local fixed volume (inspection: {local})")
        layout.ensure(self.root)
        self._remove_previous_broker_temporaries()
        generation = self._current_generation()
        if generation is None:
            self.state.mode = "repair"
            self.generation_unknown = True
            return StartReport("repair", 0, mutex.abandoned, ["current journal generation is unknown"])
        self.generation = generation
        data = layout.journal_path(self.root, generation).read_bytes() if generation else b""
        self.replay = parse(data)
        now = self.host.monotonic()
        for index, record in enumerate(self.replay.records):
            try:
                self.state.apply(record, now)
            except InvariantError as exc:
                self.replay.keep(index)
                self.state.mode = "repair"
                return StartReport("repair", generation, mutex.abandoned, [f"invariant: {exc}"])
        anomaly = self.replay.anomaly
        if anomaly is not None and anomaly.position == "mid":
            self.state.mode = "repair"
            return StartReport(
                "repair",
                generation,
                mutex.abandoned,
                [f"mid-journal anomaly at {anomaly.offset}: {anomaly.reason}"],
            )
        outcomes = self._reconcile()
        if self.unsafe or (anomaly is not None and repair):
            self.state.mode = "repair"
            return StartReport("repair", generation, mutex.abandoned, outcomes)
        if anomaly is not None or generation == 0:
            self._new_generation()
        else:
            self.journal = Journal(
                layout.journal_path(self.root, generation), self.replay.last_seq + 1, self.instance
            )
        self._apply_pending(outcomes)
        pid = self.host.self_identity()
        self._record(
            "broker-start",
            pid=pid.pid,
            start=pid.start,
            abandoned=mutex.abandoned,
            wall=self.host.wall_time(),
        )
        if repair:
            self._record("mode", mode="repair")
        self._load_policy()
        return StartReport(self.state.mode, self.generation, mutex.abandoned, outcomes)

    def stop(self) -> None:
        self.host.release_broker_mutex()

    def _remove_previous_broker_temporaries(self) -> None:
        # Only temporaries a broker wrote (".tmp-broker-*"), never a client's in-progress file (K-20, B-29).
        own = f".tmp-broker-broker-{self.instance}-"
        for entry in entries(self.root):
            name = entry.path.name
            if entry.is_dir or entry.is_link or not name.startswith(".tmp-broker-") or name.startswith(own):
                continue
            assert_inside([self.root], entry.path)
            os.unlink(entry.path)

    def _current_generation(self) -> int | None:
        names = self.markers.names("generation")
        if not names:
            return 0
        if not all(n.isdigit() for n in names):
            return None
        highest = max(int(n) for n in names)
        marker = self.markers.read("generation", str(highest))
        return highest if isinstance(marker, dict) else None

    def _new_generation(self) -> None:
        """Write the next journal generation from the good prefix, then publish its marker (K-33)."""
        good = b""
        if self.replay is not None and self.generation:
            old = layout.journal_path(self.root, self.generation).read_bytes()
            good = old[: self.replay.good_end]
            if len(old) > self.replay.good_end:
                self._quarantine(old[self.replay.good_end :], f"gen-{self.generation}-tail")
        target = self.generation + 1
        path = layout.journal_path(self.root, target)
        assert_inside([self.root], path)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o644)
        try:
            view = memoryview(good)
            while view:
                view = view[os.write(fd, view) :]
            os.fsync(fd)
        finally:
            os.close(fd)
        last = self.replay.last_seq if self.replay else 0
        self.markers.publish("generation", (str(target),), {"from": self.generation}, last)
        self.generation = target
        self.journal = Journal(path, last + 1, self.instance)

    def _quarantine(self, data: bytes, name: str) -> Path:
        folder = self.root / layout.QUARANTINE / self.host.wall_time().replace(":", "-")
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / name
        assert_inside([self.root], path)
        path.write_bytes(data)
        return path

    def _record(self, kind: str, **fields: Any) -> dict[str, Any]:
        if self.journal is None:
            raise BrokerRefused("no writable journal (repair mode)")
        record = self.journal.append(kind, **fields)
        self.state.apply(record, self.host.monotonic())
        return record

    def _seq(self) -> int:
        return self.journal.next_seq - 1 if self.journal else 0

    def _load_policy(self) -> None:
        self.policy = None
        if self.state.policy_version is None:
            return
        marker = self.markers.read("policy", str(self.state.policy_version))
        if not isinstance(marker, dict):
            self.state.mode = "repair"
            return
        self.policy = parse_policy(marker["policy"])

    # == reconciliation (K-31, K-33, K-37 to K-40) ===========================================================

    def _reconcile(self) -> list[str]:
        """Compare every effect marker with the replayed state. The records to journal go to
        `self.pending`. Anything that cannot be established safely goes to `self.unsafe` (K-31)."""
        outcomes: list[str] = []
        self.pending = []
        self.unsafe = []

        def add(kind: str, **fields: Any) -> None:
            self.pending.append((kind, fields))

        def unsafe(text: str) -> None:
            outcomes.append(text)
            self.unsafe.append(text)

        try:
            self._reconcile_accepts(outcomes, add, unsafe)
            self._reconcile_launches(outcomes, add, unsafe)
            self._reconcile_renders(outcomes, add, unsafe)
            for challenge in self.markers.names("confirm"):
                if self.state.challenges.get(challenge, {}).get("state") != "consumed":
                    add("challenge-consumed", challenge_id=challenge)
                    outcomes.append(
                        f"confirm/{challenge}: consumed; "
                        "an effect without its own marker is not restored (K-33)"
                    )
            self._reconcile_policies(outcomes, add, unsafe)
            self._reconcile_copies(outcomes, add, unsafe)
        except OSError as exc:
            unsafe(f"marker inspection failed: {exc}")
        return outcomes

    def _reconcile_accepts(self, outcomes: list[str], add: Any, unsafe: Any) -> None:
        next_id = self.state.next_job_id
        for request_id in sorted(self.markers.names("accept"), key=self._accept_order):
            if request_id in self.state.requests:
                continue
            marker = self.markers.read("accept", request_id)
            if not isinstance(marker, dict):
                unsafe(f"accept/{request_id}: unreadable; a host-blocking placeholder job holds its place")
                self._placeholder(add, next_id, f"unreadable accept marker {request_id}")
                next_id += 1
                continue
            if marker["job_id"] != next_id:
                unsafe(f"accept/{request_id}: job id {marker['job_id']} out of order (expected {next_id})")
                continue
            add("accept", request_id=request_id, job_id=marker["job_id"], spec=marker["spec"])
            outcomes.append(f"accept/{request_id}: job {marker['job_id']} restored as submitted")
            next_id += 1

    def _accept_order(self, request_id: str) -> int:
        marker = self.markers.read("accept", request_id)
        return int(marker["job_id"]) if isinstance(marker, dict) else 1 << 62

    def _restored_jobs(self) -> dict[int, tuple[str, dict[str, Any]]]:
        """Jobs known from the journal or from pending accept records: id -> (status, spec)."""
        jobs = {j.job_id: (j.status, j.spec) for j in self.state.jobs.values()}
        for kind, fields in self.pending:
            if kind == "accept":
                jobs[fields["job_id"]] = ("submitted", fields["spec"])
        return jobs

    def _reconcile_launches(self, outcomes: list[str], add: Any, unsafe: Any) -> None:
        names = set(self.markers.names("launch"))
        jobs = self._restored_jobs()
        placeholder_id = max([*jobs, self.state.next_job_id - 1]) + 1
        for name in sorted(names):
            if not name.isdigit() or int(name) not in jobs:
                unsafe(
                    f"launch/{name}: marker for an unknown job; "
                    "a host-blocking placeholder job holds its place"
                )
                self._placeholder(add, placeholder_id, f"launch marker {name} for an unknown job")
                placeholder_id += 1
        for job_id, (status, spec) in sorted(jobs.items()):
            if str(job_id) in names and status in ("submitted", "launching"):
                if status == "submitted":
                    add("launching", job_id=job_id, restored=True)
                workload = self._workload(spec)
                if workload is None:
                    add(
                        "uncertain",
                        job_id=job_id,
                        reason="launch marker present; inspection failed",
                        extent_known=True,
                    )
                    unsafe(f"job {job_id}: launched; inspection failed; uncertain, host blocked")
                elif workload:
                    add(
                        "uncertain",
                        job_id=job_id,
                        reason="launch marker present; workload running",
                        extent_known=True,
                    )
                    unsafe(f"job {job_id}: launched and still running; uncertain")
                else:
                    add(
                        "uncertain",
                        job_id=job_id,
                        reason="launch marker present; no workload",
                        extent_known=True,
                    )
                    add(
                        "ended",
                        job_id=job_id,
                        outcome="unknown-outcome",
                        eligible=False,
                        reason="launched before the damaged record; outcome unknown",
                    )
                    outcomes.append(
                        f"job {job_id}: launched and finished; ended(unknown-outcome), not relaunched"
                    )
            elif str(job_id) not in names and status == "launching":
                workload = self._workload(spec)
                if workload is False:
                    add("requeue", job_id=job_id)
                    outcomes.append(
                        f"job {job_id}: never launched (no launch marker, no workload); submitted"
                    )
                else:
                    add(
                        "uncertain",
                        job_id=job_id,
                        reason="launching without a marker; workload unknown",
                        extent_known=True,
                    )
                    unsafe(f"job {job_id}: launching without a marker and the workload cannot be ruled out")

    def _reconcile_renders(self, outcomes: list[str], add: Any, unsafe: Any) -> None:
        for handoff in self.markers.names("render"):
            known = self.state.renders.get(handoff, 0)
            released = set(self.state.undelivered.get(handoff, set()))
            for attempt in sorted(int(a) for a in self.markers.names("render", handoff) if a.isdigit()):
                if attempt > known:
                    add("render", hash=handoff, attempt=attempt, pane=None, session=None, restored=True)
                    outcomes.append(f"render/{handoff}/{attempt}: may-have-printed")
                    known = attempt
                marker = self.markers.read("undelivered", handoff, str(attempt))
                if isinstance(marker, Unreadable):
                    unsafe(f"undelivered/{handoff}/{attempt}: unreadable; no retry until repaired")
                    break
                if isinstance(marker, dict) and attempt not in released:
                    add("undelivered", hash=handoff, attempt=attempt)
                    outcomes.append(f"undelivered/{handoff}/{attempt}: one retry authorized")
                    released.add(attempt)

    def _reconcile_policies(self, outcomes: list[str], add: Any, unsafe: Any) -> None:
        current = self.state.policy_version or 0
        for version in sorted(int(v) for v in self.markers.names("policy") if v.isdigit()):
            if version <= current:
                continue
            marker = self.markers.read("policy", str(version))
            highest = max(int(v) for v in self.markers.names("policy") if v.isdigit())
            if not isinstance(marker, dict) or version != current + 1:
                unsafe(f"policy/{version}: unreadable or out of order; policy unknown until re-confirmed")
                add("policy-unknown", highest=highest)
                return
            if not isinstance(self.markers.read("confirm", str(marker.get("challenge", "-"))), dict):
                unsafe(f"policy/{version}: its confirmation is not readable; policy unknown")
                add("policy-unknown", highest=highest)
                return
            add("policy", version=version, challenge=marker["challenge"])
            outcomes.append(f"policy/{version}: in force")
            current = version

    def _reconcile_copies(self, outcomes: list[str], add: Any, unsafe: Any) -> None:
        for copy_id in self.markers.names("register"):
            marker = self.markers.read("register", copy_id)
            if not isinstance(marker, dict):
                unsafe(f"register/{copy_id}: unreadable; copy damaged")
                continue
            if copy_id not in self.state.copies:
                add("register", copy_id=copy_id, path=marker["path"], job_id=marker["job_id"])
                outcomes.append(f"register/{copy_id}: restored")
        for job_name in self.markers.names("cleanup"):
            for copy_id, copy in self.state.copies.items():
                if str(copy.get("job_id")) != job_name or copy.get("state") == "removed":
                    continue
                extent = self.copy_extent(copy_id, int(job_name))
                if extent != copy.get("state"):
                    add("copy-state", copy_id=copy_id, state=extent)
                outcomes.append(f"copy {copy_id}: {extent}")
                if extent == "damaged":
                    unsafe(f"copy {copy_id}: damaged; never reused, held until a cleanup job finishes it")

    def _placeholder(self, add: Any, job_id: int, why: str) -> None:
        """A job whose footprint is unknown: evidence class, uncertain, extent unknown, so it blocks the
        whole host until inspected proof or an Owner release (K-10, K-12)."""
        spec = {
            "class": "evidence",
            "leases": [],
            "submitter": {},
            "placeholder": why,
            "group": "",
            "job_label": "",
        }
        add("accept", request_id=f"placeholder-{job_id}", job_id=job_id, spec=spec)
        add("launching", job_id=job_id, restored=True)
        add("uncertain", job_id=job_id, reason=why, extent_known=False)

    def _workload(self, spec: dict[str, Any]) -> bool | None:
        """True if any process of the job's group or any container with its label is running. A group that
        cannot be inspected counts as ended only when the runner's result file exists: the runner writes it
        only after every other process of its job has exited."""
        active = self.host.group_active(str(spec.get("group", "")))
        if (
            active is None
            and spec.get("job_id") is not None
            and self._read_result(int(spec["job_id"])) is not None
        ):
            active = False
        containers = self.host.containers_running(str(spec.get("job_label", "")))
        if active is None or containers is None:
            return None
        return bool(active or containers)

    def copy_extent(self, copy_id: str, job_id: int) -> str:
        """K-39: `registered` (untouched), `cleaning` (every missing entry has a marker; some entries may be
        pending), or `damaged` (an entry is missing without a marker, or a marker is unreadable)."""
        reg = self.markers.read("register", copy_id)
        if not isinstance(reg, dict):
            return "damaged"
        deleted: set[str] = set()
        for entry in self.markers.names("cleanup", str(job_id)):
            marker = self.markers.read("cleanup", str(job_id), entry)
            if not isinstance(marker, dict):
                return "damaged"
            if marker.get("copy_id") == copy_id:
                deleted.add(str(marker["path"]))
        root = Path(str(reg["path"]))
        for relative in reg["manifest"]:
            if not os.path.lexists(root / relative) and relative not in deleted:
                return "damaged"
        return "cleaning" if deleted else "registered"

    def _apply_pending(self, outcomes: list[str]) -> None:
        for kind, fields in self.pending:
            self._record(kind, **fields)
        self.pending = []
        if outcomes:
            self._record("recovery", outcomes=outcomes)

    # == repair (K-12, K-28, K-31) ==========================================================================

    def inspect(self) -> dict[str, Any]:
        anomaly = self.replay.anomaly if self.replay else None
        return {
            "mode": self.state.mode,
            "generation": self.generation,
            "anomaly": None
            if anomaly is None
            else {"offset": anomaly.offset, "reason": anomaly.reason, "position": anomaly.position},
            "records": len(self.replay.records) if self.replay else 0,
            "unsafe": list(self.unsafe),
        }

    def _repair_quarantine(self) -> str:
        """Keep the original bytes, write a recovery generation from the good prefix, journal every
        reconciled outcome, and leave every job whose state cannot be established `uncertain`. The broker
        stays in repair until a confirmed resume."""
        if self.generation:
            self._quarantine(
                layout.journal_path(self.root, self.generation).read_bytes(), f"gen-{self.generation}-full"
            )
        outcomes = self._reconcile()
        self._new_generation()
        self._apply_pending(outcomes)
        # Every unsafe outcome is now represented in state (uncertain jobs, placeholders, unknown policy,
        # refused retries) except a failed inspection, which needs a new quarantine after it is fixed.
        self.unsafe = [u for u in self.unsafe if u.startswith("marker inspection failed")]
        self._record("mode", mode="repair")
        pid = self.host.self_identity()
        self._record(
            "broker-start", pid=pid.pid, start=pid.start, abandoned=False, wall=self.host.wall_time()
        )
        return f"generation {self.generation} written; resume needs its own confirmation"

    # == requests ===========================================================================================

    def step(self) -> None:
        self._serve_inbox()
        if self.state.mode == "normal":
            self._check_active()
            self._admit()

    def _serve_inbox(self) -> None:
        inbox = self.root / layout.INBOX
        for name in sorted(os.listdir(inbox)):
            if name.startswith(".tmp-") or not name.endswith(".req"):
                continue
            path = inbox / name
            request_id = name[: -len(".req")]
            try:
                request = decode_single(path.read_bytes())
            except FramingError as exc:
                self._reject_file(path, request_id, f"unreadable request: {exc}")
                continue
            if request.get("request_id") != request_id:
                self._reject_file(path, request_id, "request id does not match its file name")
                continue
            self._respond(request_id, self._handle(request))
            assert_inside([self.root], path)
            path.unlink()

    def _reject_file(self, path: Path, request_id: str, reason: str) -> None:
        target = self.root / layout.REJECTED / f"{request_id}.req"
        assert_inside([self.root], target)
        assert_inside([self.root], path)
        os.replace(path, target)
        (self.root / layout.REJECTED / f"{request_id}.reason").write_text(reason, encoding="utf-8")

    def _respond(self, request_id: str, response: dict[str, Any]) -> None:
        final = self.root / layout.OUTBOX / f"{request_id}.res"
        temp = self.root / layout.OUTBOX / f".tmp-broker-broker-{self.instance}-{request_id}"
        assert_inside([self.root], temp)
        assert_inside([self.root], final)
        temp.write_bytes(encode({"request_id": request_id, **response}))
        os.replace(temp, final)

    def _handle(self, request: dict[str, Any]) -> dict[str, Any]:
        kind = request.get("type")
        if kind == "hook-confirm":
            return self._confirm(request)
        if kind == "repair-inspect":
            return {"ok": True, "report": self.inspect()}
        if kind == "status":
            return self._status(request)
        if kind in ("repair-quarantine", "repair-resume"):
            return self._challenge(str(kind), request)
        if self.state.mode != "normal":
            return {
                "ok": False,
                "error": f"broker in {self.state.mode} mode; only repair requests are served",
            }
        handlers = {
            "submit": self._submit,
            "cancel": self._cancel,
            "release": lambda r: self._challenge("release", r),
            "policy-set": lambda r: self._challenge("policy-set", r),
            "render": self._render,
            "undelivered": self._mark_undelivered,
            "unretain": self._unretain,
        }
        handler = handlers.get(str(kind))
        if handler is None:
            return {"ok": False, "error": f"unknown request type {kind!r}"}
        return handler(request)

    def _submit(self, request: dict[str, Any]) -> dict[str, Any]:
        request_id = str(request["request_id"])
        known = self.state.requests.get(request_id)
        if isinstance(known, int):
            return {"ok": True, "job_id": known, "duplicate": True}
        if isinstance(known, str):
            return {"ok": False, "error": known, "duplicate": True}
        if self.policy is None:
            return {"ok": False, "error": "no policy in force"}
        job_id = self.state.next_job_id
        pane = (request.get("submitter") or {}).get("pane")
        try:
            spec = build_spec(
                request,
                self.policy,
                self.policy.policy_id,
                job_id,
                self.host.pane(str(pane)) if pane else None,
            )
            if spec["class"] == "cleanup":
                spec["leases"] = self._cleanup_leases(spec["copies"])
        except SpecError as exc:
            self._record("reject", request_id=request_id, reason=str(exc))
            return {"ok": False, "error": str(exc)}
        spec["request"] = {k: v for k, v in request.items() if k != "request_id"}
        self.markers.publish("accept", (request_id,), {"job_id": job_id, "spec": spec}, self._seq())
        self._record("accept", request_id=request_id, job_id=job_id, spec=spec)
        return {"ok": True, "job_id": job_id}

    def _cleanup_leases(self, copies: list[str]) -> list[list[str]]:
        leases = []
        for copy_id in copies:
            copy = self.state.copies.get(copy_id)
            if copy is None or copy.get("state") == "removed":
                raise SpecError(f"copy {copy_id!r} is not a registered copy")
            owner = self.state.jobs.get(int(copy["job_id"]))
            if owner is not None and owner.status not in TERMINAL:
                raise SpecError(f"copy {copy_id!r} belongs to job {owner.job_id}, which is {owner.status}")
            creator = self.state.jobs.get(int(copy["creator"]))
            if creator is not None and creator.retain:
                raise SpecError(
                    f"copy {copy_id!r} is retained by eligible evidence job {creator.job_id} (K-18)"
                )
            leases.append([copy["path"], "exclusive"])
        return leases

    def _status(self, request: dict[str, Any]) -> dict[str, Any]:
        decision = decide(self.state, self.policy, self.host.free_memory_bytes(), self.host.monotonic())
        jobs = []
        for job in sorted(self.state.jobs.values(), key=lambda j: j.job_id):
            if request.get("job_id") not in (None, job.job_id):
                continue
            jobs.append(
                {
                    "job_id": job.job_id,
                    "class": job.klass,
                    "status": job.status,
                    "outcome": job.outcome,
                    "evidence": "eligible" if job.eligible else f"not-eligible({job.reason or job.status})",
                    "waits": decision.waits.get(job.job_id),
                    "retain": job.retain,
                    "log": job.spec.get("log"),
                }
            )
        return {
            "ok": True,
            "mode": self.state.mode,
            "generation": self.generation,
            "policy_version": self.state.policy_version,
            "jobs": jobs,
        }

    def _cancel(self, request: dict[str, Any]) -> dict[str, Any]:
        job = self.state.jobs.get(int(request.get("job_id", 0)))
        if job is None or job.status != "submitted":
            return {"ok": False, "error": "only a submitted job can be cancelled"}
        if (request.get("submitter") or {}).get("session") != job.spec["submitter"]["session"]:
            return {"ok": False, "error": "only the submitting session can cancel"}
        self._record("cancelled", job_id=job.job_id)
        return {"ok": True}

    def _unretain(self, request: dict[str, Any]) -> dict[str, Any]:
        job = self.state.jobs.get(int(request.get("job_id", 0)))
        if job is None or not job.retain:
            return {"ok": False, "error": "job is not retained"}
        self._record("unretain", job_id=job.job_id)
        return {"ok": True}

    # == render / undelivered (K-3, K-32) ===================================================================

    def _render(self, request: dict[str, Any]) -> dict[str, Any]:
        text = request.get("text")
        if not isinstance(text, str) or not text:
            return {"ok": False, "error": "render needs the hand-off text"}
        handoff = hashlib.sha256(text.encode("utf-8")).hexdigest()
        previous = self.state.renders.get(handoff, 0)
        if previous and previous not in self.state.undelivered.get(handoff, set()):
            return {
                "ok": False,
                "error": f"hand-off already rendered (attempt {previous}, may-have-printed); "
                "mark it undelivered first",
            }
        attempt = previous + 1
        self.markers.publish(
            "render",
            (handoff, str(attempt)),
            {"pane": request.get("pane"), "session": request.get("session")},
            self._seq(),
        )
        self._record(
            "render", hash=handoff, attempt=attempt, pane=request.get("pane"), session=request.get("session")
        )
        return {
            "ok": True,
            "hash": handoff,
            "attempt": attempt,
            "text": text,
            "delivery": "not sent by the kit (K-1); may-have-printed once returned",
        }

    def _mark_undelivered(self, request: dict[str, Any]) -> dict[str, Any]:
        handoff = str(request.get("hash", ""))
        attempt = int(request.get("attempt", 0))
        if self.state.renders.get(handoff) != attempt:
            return {"ok": False, "error": "only the latest attempt can be marked undelivered"}
        if attempt in self.state.undelivered.get(handoff, set()):
            return {"ok": True, "duplicate": True}
        self.markers.publish(
            "undelivered", (handoff, str(attempt)), {"by": request.get("session")}, self._seq()
        )
        self._record("undelivered", hash=handoff, attempt=attempt)
        return {"ok": True}

    # == challenges and confirmations (K-21 to K-24, K-33) ===================================================

    def _challenge(self, action: str, request: dict[str, Any]) -> dict[str, Any]:
        scope: dict[str, Any] = {"generation": self.generation}
        if action == "release":
            job = self.state.jobs.get(int(request.get("job_id", 0)))
            if job is None or job.status != "uncertain":
                return {"ok": False, "error": "release applies only to an uncertain job"}
            scope["job_id"] = job.job_id
            effect = f"mark job {job.job_id} ended(human-confirmed), not-eligible, and release its resources"
        elif action == "policy-set":
            try:
                proposed = parse_policy(request.get("policy"))
            except PolicyError as exc:
                return {"ok": False, "error": f"invalid policy: {exc}"}
            expected = max(self.state.policy_version or 0, self.state.policy_floor) + 1
            if proposed.version != expected:
                return {"ok": False, "error": f"policy version must be {expected}"}
            scope["policy"] = proposed.as_dict()
            scope["decision"] = request.get("decision")
            effect = (
                f"put policy version {proposed.version} in force: "
                f"{json.dumps(proposed.as_dict(), sort_keys=True)}"
            )
        elif action == "repair-quarantine":
            if self.state.mode != "repair":
                return {"ok": False, "error": "not in repair mode"}
            if self.generation_unknown:
                return {"ok": False, "error": "the current journal generation is unknown; the queue folder needs the Owner"}
            effect = "quarantine the current journal and write a recovery generation"
        else:
            if self.state.mode != "repair" or self.journal is None or self.unsafe:
                return {
                    "ok": False,
                    "error": "resume needs repair mode with a recovery generation and nothing unsafe",
                }
            effect = "return the broker to normal mode"
        code = secrets.token_hex(4)
        record: dict[str, Any] = {
            "challenge_id": secrets.token_hex(8),
            "code_sha256": hashlib.sha256(code.encode()).hexdigest(),
            "action": action,
            "scope": scope,
            "effect": effect,
            "expires_mono": self.host.monotonic() + CHALLENGE_SECONDS,
        }
        if self.journal is not None:
            self._record("challenge", **record)
        else:
            self.repair_challenges[record["challenge_id"]] = {**record, "state": "open"}
        return {
            "ok": True,
            "challenge": record["challenge_id"],
            "code": code,
            "effect": effect,
            "confirm_with": f"CONFIRM QUEUE {code}",
            "expires_seconds": CHALLENGE_SECONDS,
        }

    def _confirm(self, request: dict[str, Any]) -> dict[str, Any]:
        if request.get("origin") != "user-prompt-hook":
            return {"ok": False, "error": "confirmations come only from the Owner's chat hook (K-21)"}
        digest = hashlib.sha256(str(request.get("code", "")).encode()).hexdigest()
        pool = {**self.state.challenges, **self.repair_challenges}
        match = [c for c in pool.values() if c.get("code_sha256") == digest]
        if not match:
            return {"ok": False, "error": "no challenge for that code"}
        challenge = match[0]
        if challenge["state"] != "open":
            return {"ok": False, "error": "challenge already used"}
        if self.host.monotonic() > challenge["expires_mono"]:
            return {"ok": False, "error": "challenge expired"}
        if challenge["scope"].get("generation") != self.generation:
            return {"ok": False, "error": "challenge belongs to another journal generation"}
        if challenge["action"] == "release":
            job = self.state.jobs.get(int(challenge["scope"]["job_id"]))
            if job is None or job.status != "uncertain":
                return {"ok": False, "error": "the job is no longer uncertain; the challenge is stale"}
        self.markers.publish(
            "confirm",
            (challenge["challenge_id"],),
            {"session": request.get("session"), "action": challenge["action"]},
            self._seq(),
        )
        if challenge["challenge_id"] in self.repair_challenges:
            self.repair_challenges[challenge["challenge_id"]]["state"] = "consumed"
        else:
            self._record("confirmed", challenge_id=challenge["challenge_id"], session=request.get("session"))
        return self._apply_override(challenge)

    def _apply_override(self, challenge: dict[str, Any]) -> dict[str, Any]:
        action = challenge["action"]
        if action == "release":
            job_id = challenge["scope"]["job_id"]
            self._record(
                "ended",
                job_id=job_id,
                outcome="human-confirmed",
                eligible=False,
                reason=f"released by challenge {challenge['challenge_id']}",
            )
            return {"ok": True, "applied": f"job {job_id} ended(human-confirmed), not-eligible"}
        if action == "policy-set":
            policy = challenge["scope"]["policy"]
            self.markers.publish(
                "policy",
                (str(policy["version"]),),
                {
                    "policy": policy,
                    "challenge": challenge["challenge_id"],
                    "decision": challenge["scope"].get("decision"),
                },
                self._seq(),
            )
            self._record("policy", version=policy["version"], challenge=challenge["challenge_id"])
            self._load_policy()
            return {"ok": True, "applied": f"policy version {policy['version']} in force"}
        if action == "repair-quarantine":
            return {"ok": True, "applied": self._repair_quarantine()}
        self._record("mode", mode="normal")
        self._load_policy()
        return {"ok": True, "applied": "broker resumed in normal mode"}

    # == running jobs: end proof (B-16 to B-19) =============================================================

    def _check_active(self) -> None:
        for job in list(self.state.active()):
            if job.klass == "cleanup":
                if job.status == "running":
                    self._cleanup_step(job)
                continue
            if job.status == "launching" or not job.extent_known:
                continue  # unknown extent: only inspected proof by repair, or an Owner release, resolves it
            workload = self._workload(job.spec)
            if workload is None:
                if job.status == "running":
                    self._record(
                        "uncertain", job_id=job.job_id, reason="workload inspection failed", extent_known=True
                    )
                continue
            if workload:
                if job.status == "running":
                    alive = (
                        self.host.process_alive(
                            ProcessIdentity(int(job.runner["pid"]), int(job.runner["start"]))
                        )
                        if job.runner
                        else None
                    )
                    if alive is not True:
                        self._record(
                            "uncertain",
                            job_id=job.job_id,
                            reason="runner gone or unknown while its workload lives",
                            extent_known=True,
                        )
                continue
            self._finish(job)

    def _finish(self, job: Job) -> None:
        if job.status == "uncertain":
            self._record(
                "ended",
                job_id=job.job_id,
                outcome="unknown-outcome",
                eligible=False,
                reason="workload proven ended after uncertainty",
            )
            return
        result = self._read_result(job.job_id)
        if result is None:
            self._record(
                "ended",
                job_id=job.job_id,
                outcome="unknown-outcome",
                eligible=False,
                reason="no readable runner result",
            )
            return
        passed = result.get("exit") == 0 and result.get("gate_end") == 0
        eligible = False
        reason = None if passed else f"exit {result.get('exit')}, GATE-END {result.get('gate_end')}"
        if job.klass == "evidence" and passed:
            workdir = Path(str(job.spec["workdir"]))
            head = self.git.head(workdir)
            clean = self.git.clean(workdir)
            eligible = head == job.spec["sha"] and clean is True
            if not eligible:
                reason = f"post-run copy check: HEAD {head}, clean {clean}"
        elif passed:
            reason = f"{job.klass} jobs are never evidence"
        self._record(
            "ended",
            job_id=job.job_id,
            outcome="passed" if passed else "failed",
            eligible=eligible,
            reason=reason,
            retain=eligible,
            exit=result.get("exit"),
        )

    def _read_result(self, job_id: int) -> dict[str, Any] | None:
        try:
            return decode_single((self.root / layout.JOBS / str(job_id) / "result").read_bytes())
        except (OSError, FramingError):
            return None

    # == admission and launch (B-9 to B-17, K-9 to K-12a) ===================================================

    def _admit(self) -> None:
        while True:
            decision = decide(self.state, self.policy, self.host.free_memory_bytes(), self.host.monotonic())
            if decision.admit is None:
                return
            for earlier in decision.bypassed:
                self._record("bypass", job_id=earlier, count=self.state.jobs[earlier].bypasses + 1)
            self._launch(self.state.jobs[decision.admit])

    def _launch(self, job: Job) -> None:
        self._record("launching", job_id=job.job_id)
        if job.klass == "cleanup":
            self._record("running", job_id=job.job_id, runner=None, group=None)
            return
        assert self.policy is not None
        try:
            rebuilt = build_spec(
                {**job.spec["request"], "request_id": job.request_id},
                self.policy,
                self.policy.policy_id,
                job.job_id,
                self.host.pane(str(job.spec["submitter"]["pane"])),
            )
        except SpecError as exc:
            self._record("refused", job_id=job.job_id, reason=f"refused at launch: {exc}")
            return
        rebuilt["request"] = job.spec["request"]
        changed = drift(job.spec, rebuilt)
        if changed:
            self._record("refused", job_id=job.job_id, reason=f"input drift: {', '.join(changed)}")
            return
        try:
            freshness = self._prepare(job)
        except (OSError, ValueError) as exc:
            self._record("refused", job_id=job.job_id, reason=f"preparation failed: {exc}")
            return
        try:
            self.markers.publish("launch", (str(job.job_id),), {"group": job.spec["group"]}, self._seq())
        except MarkerExists:
            self._record(
                "uncertain",
                job_id=job.job_id,
                reason="launch marker already exists; never launched twice (W-84)",
                extent_known=True,
            )
            return
        job_dir = self.root / layout.JOBS / str(job.job_id)
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "input").write_bytes(
            encode({"argv": job.spec["argv"], "cwd": job.spec["run_dir"], "log": job.spec["log"]})
        )
        env = dict(os.environ)
        env.update(job.spec["env"])
        env["MINION_JOB"] = job.spec["job_label"]
        env["MINION_JOB_GROUP"] = job.spec["group"]
        try:
            assert_inside([Path(r) for r in job.spec["roots"]], Path(job.spec["log"]))
            spawned = self.host.spawn(
                [self.python, "-m", "minion_process.hostqueue.runner", str(job_dir)],
                env,
                Path(job.spec["run_dir"]),
                Path(job.spec["log"]),
                job.spec["group"],
            )
        except OSError as exc:
            started = self._workload(job.spec)
            exists = self.host.group_exists(job.spec["group"])
            if started is False and exists is False:
                self._record("refused", job_id=job.job_id, reason=f"spawn failed before any workload: {exc}")
            else:
                self._record(
                    "uncertain",
                    job_id=job.job_id,
                    reason=f"spawn failed after the group existed: {exc}",
                    extent_known=True,
                )
            return
        self._record(
            "running",
            job_id=job.job_id,
            runner={"pid": spawned.runner.pid, "start": spawned.runner.start},
            group=spawned.group,
            freshness=freshness,
        )

    def _prepare(self, job: Job) -> str:
        """Preparation under the job's exclusive leases. Returns the freshness method it applied
        (K-12a, B-12)."""
        roots = [Path(r) for r in job.spec["roots"]]
        if job.klass == "build":
            touched = 0
            checkout = Path(str(job.spec["checkout"]))
            for path in files(checkout):
                relative = path.relative_to(checkout).as_posix()
                if relative.startswith(".git/"):
                    continue
                if any(fnmatch.fnmatch(relative, pattern) for pattern in job.spec["source_globs"]):
                    assert_inside(roots, path)
                    os.utime(path, None)
                    touched += 1
            return f"touch: {touched} workspace-member source files"
        workdir = Path(str(job.spec["workdir"]))
        assert_inside(roots, workdir)
        if os.path.lexists(workdir):
            raise ValueError(f"execution copy {workdir} already exists")
        self.git.add_worktree(Path(str(job.spec["checkout"])), workdir, str(job.spec["sha"]))
        manifest = sorted(entry.path.relative_to(workdir).as_posix() for entry in entries(workdir))
        copy_id = str(job.spec["job_label"])
        self.markers.publish(
            "register",
            (copy_id,),
            {"path": str(workdir), "job_id": job.job_id, "manifest": manifest},
            self._seq(),
        )
        self._record("register", copy_id=copy_id, path=str(workdir), job_id=job.job_id)
        if self.git.head(workdir) != job.spec["sha"] or self.git.clean(workdir) is not True:
            raise ValueError("fresh copy does not match the requested SHA or is not clean")
        return f"fresh copy at {job.spec['sha']}"

    # == cleanup (K-17 to K-19, K-39) =======================================================================

    def _cleanup_step(self, job: Job) -> None:
        todo = self.cleanup_progress.get(job.job_id)
        if todo is None:
            refusal = self._cleanup_references(job)
            if refusal:
                self._record("ended", job_id=job.job_id, outcome="failed", eligible=False, reason=refusal)
                return
            todo = []
            for copy_id in job.spec["copies"]:
                self._record("lease-transfer", copy_id=copy_id, to_job=job.job_id)
                root = Path(self.state.copies[copy_id]["path"])
                if os.path.lexists(root):
                    todo += [(copy_id, str(entry.path)) for entry in entries(root, bottom_up=True)]
                    todo.append((copy_id, str(root)))
            self.cleanup_progress[job.job_id] = todo
        roots = [Path(r) for r in job.spec["roots"]]
        done = 0
        while todo and done < CLEANUP_BATCH:
            copy_id, text = todo[0]
            path = Path(text)
            copy_root = Path(self.state.copies[copy_id]["path"])
            relative = "." if path == copy_root else path.relative_to(copy_root).as_posix()
            assert_inside(roots, path.parent if path != copy_root else path)
            seq = len(self.markers.names("cleanup", str(job.job_id))) + 1
            self.markers.publish(
                "cleanup",
                (str(job.job_id), f"{seq:08d}"),
                {"copy_id": copy_id, "path": relative},
                self._seq(),
            )
            remove_entry(classify(path))
            todo.pop(0)
            done += 1
        if todo:
            return
        for copy_id in job.spec["copies"]:
            self._record("copy-state", copy_id=copy_id, state="removed")
            creator = self.state.jobs.get(int(self.state.copies[copy_id]["creator"]))
            if creator is not None and creator.spec.get("checkout"):
                self.git.prune(Path(str(creator.spec["checkout"])))
        self._record(
            "ended",
            job_id=job.job_id,
            outcome="passed",
            eligible=False,
            reason="cleanup jobs are never evidence",
        )
        self.cleanup_progress.pop(job.job_id, None)

    def _cleanup_references(self, job: Job) -> str | None:
        """K-18: the reference set, evaluated at the destructive boundary. Unreadable means refuse."""
        try:
            profile = yaml.safe_load(Path(str(job.spec["profile"])).read_text(encoding="utf-8")) or {}
            sources = list((profile.get("build_queue") or {}).get("reference_sources") or [])
        except (OSError, yaml.YAMLError) as exc:
            return f"reference sources unreadable: {exc}"
        for copy_id in job.spec["copies"]:
            path = str(self.state.copies[copy_id]["path"])
            for other in self.state.jobs.values():
                if other.job_id == job.job_id or other.status in TERMINAL:
                    continue
                for lease_path, _mode in other.leases():
                    if (
                        lease_path == path
                        or lease_path.startswith(path + os.sep)
                        or path.startswith(lease_path + os.sep)
                    ):
                        return f"copy {copy_id} is referenced by job {other.job_id} ({other.status})"
            creator = self.state.jobs.get(int(self.state.copies[copy_id]["creator"]))
            if creator is not None and creator.retain:
                return f"copy {copy_id} is retained by job {creator.job_id}"
            for source in sources:
                found = _mentions(Path(str(source)), path)
                if found is None:
                    return f"reference source unreadable: {source}"
                if found:
                    return f"copy {copy_id} is referenced in {source}"
        return None


def _mentions(source: Path, needle: str) -> bool | None:
    """Does any file under `source` mention `needle`? None if anything cannot be read (K-18)."""
    try:
        targets = [source] if not source.is_dir() else list(files(source))
        return any(needle in path.read_text(encoding="utf-8", errors="replace") for path in targets)
    except OSError:
        return None


__all__ = ["Broker", "BrokerRefused", "Contained", "StartReport"]
