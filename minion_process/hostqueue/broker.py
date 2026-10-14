"""The host broker: the only writer of queue state (`docs/p3b/`, effective rule set of checkpoint r15).

One `Broker` holds the host-wide OS mutex for its whole life. Each `step()` does three things:

1. answers inbox requests;
2. checks every active job for proof that it ended;
3. admits jobs.

Every state change is a flushed journal record written before the change is acted on. Every protected
effect is guarded by a write-ahead marker published before the effect. The broker never kills, stops or
signals a process, and it sends no keystrokes to any pane (K-1). It deletes and renames only inside its own
queue folder (K-46): there is no cleanup class in 0.4.0 (K-47), and a registered copy is removed only by
hand (K-48'').
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

from . import fsops, layout
from .contain import Contained, assert_inside
from .framing import FramingError, decode_single, encode
from .gitops import GitOps
from .hostos import HostOS, ProcessIdentity
from .jobspec import SpecError, build_spec, drift
from .journal import Journal, Replay, parse
from .markers import MarkerExists, Markers, Unreadable
from .policy import Policy, PolicyError
from .policy import parse as parse_policy
from .requests import malformed
from .resources import canonical, overlaps
from .state import InvariantError, Job, QueueState, decide
from .walk import TreeProof, Unproven, entries, files, prove_tree

CHALLENGE_SECONDS = 15 * 60
INSPECTED = "inspected"  # an end established by K-41 workload inspection
HUMAN_CONFIRMED = "human-confirmed"  # an end established by an authorized confirmed release (K-23)


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
            fsops.unlink([self.root], entry.path)

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
        fsops.write_new([self.root], path, good)
        last = self.replay.last_seq if self.replay else 0
        self.markers.publish("generation", (str(target),), {"from": self.generation}, last)
        self.generation = target
        self.journal = Journal(path, last + 1, self.instance, [self.root])

    def _quarantine(self, data: bytes, name: str) -> Path:
        folder = self.root / layout.QUARANTINE / self.host.wall_time().replace(":", "-")
        fsops.mkdir([self.root], folder)
        path = folder / f"{name}-{secrets.token_hex(4)}"
        fsops.write_new([self.root], path, data)
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
            self._reconcile_overrides(outcomes, add)
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
                        proof=INSPECTED,
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
        """K-32, R005. Each published attempt is restored as may-have-printed. A grant authorizes exactly
        one retry, and a retry consumes it, so only the latest attempt can hold a live grant. That grant
        stands only with its readable published marker: a journal grant whose marker is unreadable or
        missing is revoked, and nothing is ever granted from an unreadable marker."""
        for handoff in self.markers.names("render"):
            known = self.state.renders.get(handoff, 0)
            granted = set(self.state.undelivered.get(handoff, set()))
            for attempt in sorted(int(a) for a in self.markers.names("render", handoff) if a.isdigit()):
                if attempt <= known:
                    continue
                if known and known not in granted:
                    marker = self.markers.read("undelivered", handoff, str(known))
                    if not isinstance(marker, dict):
                        unsafe(
                            f"render/{handoff}/{attempt}: published without a readable grant "
                            f"for attempt {known}"
                        )
                        break
                    add("undelivered", hash=handoff, attempt=known)
                    granted.add(known)
                add("render", hash=handoff, attempt=attempt, pane=None, session=None, restored=True)
                outcomes.append(f"render/{handoff}/{attempt}: may-have-printed")
                granted.discard(known)
                known = attempt
            if not known:
                continue
            marker = self.markers.read("undelivered", handoff, str(known))
            if isinstance(marker, dict):
                if known not in granted:
                    add("undelivered", hash=handoff, attempt=known)
                    outcomes.append(f"undelivered/{handoff}/{known}: one retry authorized")
                continue
            if known in granted:
                add("undelivered-revoked", hash=handoff, attempt=known)
            if isinstance(marker, Unreadable) or known in granted:
                unsafe(f"undelivered/{handoff}/{known}: authorization not readable; no retry until repaired")

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

    def _reconcile_overrides(self, outcomes: list[str], add: Any) -> None:
        """K-48'' replay rows 3 and 4. An intact authorized confirmed release is restored as K-23 bound it,
        without re-inspecting the workload. An ambiguous one is not restored (K-33): the job is uncertain
        again and holds its resources, its copy lease included."""
        for job in sorted(self.state.jobs.values(), key=lambda j: j.job_id):
            if job.status != "ended" or job.outcome != HUMAN_CONFIRMED:
                continue
            problem = self._override_problem(job)
            if problem is None:
                outcomes.append(
                    f"job {job.job_id}: confirmed release intact; ended(human-confirmed) restored, "
                    "not re-inspected"
                )
                continue
            add(
                "override-unrestored",
                job_id=job.job_id,
                reason=f"confirmed release {problem}; effect may have occurred; not restored (K-33)",
            )
            outcomes.append(f"job {job.job_id}: confirmed release {problem}; uncertain, resources held")

    def _override_problem(self, job: Job) -> str | None:
        """Why the record of a job's confirmed release is not intact, or None. Intact means its journal
        record names the release challenge for this job, that challenge was consumed in the generation it
        was bound to, and its `confirm/<challenge>` marker reads back."""
        override = job.override if isinstance(job.override, dict) else {}
        challenge = self.state.challenges.get(str(override.get("challenge_id")))
        if (
            challenge is None
            or challenge.get("action") != "release"
            or challenge.get("scope", {}).get("job_id") != job.job_id
        ):
            return "does not match a release challenge for this job"
        if challenge.get("state") != "consumed":
            return "has no consumed confirmation"
        if challenge["scope"].get("generation") != override.get("generation"):
            return "was recorded under another journal generation"
        if not isinstance(self.markers.read("confirm", str(override["challenge_id"])), dict):
            return "has an unreadable confirmation marker"
        return None

    def _reconcile_copies(self, outcomes: list[str], add: Any, unsafe: Any) -> None:
        """K-38, K-39, K-48'': rebuild registrations from readable `register/` markers. A registration whose
        manifest disagrees with the disk is `damaged` and stays registered. A missing copy is not damage:
        `status` reports it as absent, and the broker never re-creates, repairs or deletes it."""
        jobs = self._restored_jobs()
        for copy_id in self.markers.names("register"):
            marker = self.markers.read("register", copy_id)
            known = self.state.copies.get(copy_id)
            if not isinstance(marker, dict):
                if known is None:
                    unsafe(f"register/{copy_id}: unreadable and not in the journal; its path is unknown")
                elif not known.get("damaged"):
                    add("copy-damaged", copy_id=copy_id, reason="registration marker unreadable")
                    outcomes.append(f"copy {copy_id}: registration marker unreadable; damaged, registered")
                continue
            if known is None:
                if marker["job_id"] not in jobs:
                    unsafe(f"register/{copy_id}: copy of unknown job {marker['job_id']}")
                    continue
                add("register", copy_id=copy_id, path=marker["path"], job_id=marker["job_id"])
                outcomes.append(f"register/{copy_id}: restored")
            problem = _manifest_problem(Path(str(marker["path"])), marker["manifest"])
            if problem and not (known or {}).get("damaged"):
                add("copy-damaged", copy_id=copy_id, reason=problem)
                outcomes.append(f"copy {copy_id}: {problem}; damaged, registered, never reused")

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

    def _workload(self, spec: dict[str, Any], runner: dict[str, Any] | None = None) -> bool | None:
        """True if any process of the job's group, the recorded runner or stray process, or any container
        with its label is running; None if any of these cannot be established (K-36). A group that cannot
        be inspected counts as ended only when the runner's result records a verified drain (`drained:
        true`), which the runner writes only after a successful accounting query showed it alone in its
        job (PROC-KIT-P3B-R002)."""
        active = self.host.group_active(str(spec.get("group", "")))
        if active is None and spec.get("job_id") is not None:
            result = self._read_result(int(spec["job_id"]))
            if result is not None and result.get("drained") is True:
                active = False
        alive: bool | None = False
        if runner:
            alive = self.host.process_alive(ProcessIdentity.from_record(runner))
        containers = self.host.containers_running(str(spec.get("job_label", "")))
        if active is None or containers is None or alive is None:
            return None
        return bool(active or containers or alive)

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
            problem = malformed(request)  # K-44: total, so it runs before any field is read
            if problem is not None:  # R010: rejected alone, never raised, never dispatched
                self._reject_file(path, request_id, f"malformed request: {problem}")
                continue
            if request["request_id"] != request_id:
                self._reject_file(path, request_id, "request id does not match its file name")
                continue
            self._respond(request_id, self._handle(request))
            fsops.unlink([self.root], path)

    def _reject_file(self, path: Path, request_id: str, reason: str) -> None:
        target = self.root / layout.REJECTED / f"{request_id}.req"
        fsops.replace([self.root], path, target)
        reason_path = self.root / layout.REJECTED / f"{request_id}.reason"
        fsops.write_replace(
            [self.root],
            reason_path.with_name(f".tmp-broker-broker-{self.instance}-reason"),
            reason_path,
            reason.encode("utf-8"),
        )

    def _respond(self, request_id: str, response: dict[str, Any]) -> None:
        final = self.root / layout.OUTBOX / f"{request_id}.res"
        temp = self.root / layout.OUTBOX / f".tmp-broker-broker-{self.instance}-{request_id}"
        fsops.write_replace([self.root], temp, final, encode({"request_id": request_id, **response}))

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
            self._refuse_registered(spec)
        except SpecError as exc:
            self._record("reject", request_id=request_id, reason=str(exc))
            return {"ok": False, "error": str(exc)}
        spec["request"] = {k: v for k, v in request.items() if k != "request_id"}
        self.markers.publish("accept", (request_id,), {"job_id": job_id, "spec": spec}, self._seq())
        self._record("accept", request_id=request_id, job_id=job_id, spec=spec)
        return {"ok": True, "job_id": job_id}

    def _refuse_registered(self, spec: dict[str, Any]) -> None:
        """K-48' no reuse: a registered copy, held or released, is never leased by another job. A job
        whose leases equal or overlap a registered copy's path is refused, at submit and again at launch,
        so no third job can ever claim a released copy."""
        for _copy_id, copy in sorted(self.state.copies.items()):
            if copy["creator"] == spec["job_id"]:
                continue
            for path, _mode in spec["leases"]:
                if overlaps(canonical(str(copy["path"])), str(path)):
                    raise SpecError(f"path is a registered copy of job {copy['creator']}: {path}")

    def _copies(self) -> list[dict[str, Any]]:
        """K-48'': every registered copy with its creator, state and path; `, absent` when removed by hand."""
        listed = []
        for copy_id, copy in sorted(self.state.copies.items()):
            state = self.state.copy_state(copy_id)
            if state != "held" and not os.path.lexists(str(copy["path"])):
                state += ", absent"
            listed.append({"copy": copy_id, "creator": copy["creator"], "state": state, "path": copy["path"]})
        return listed

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
                    "end": job.proof,
                    "log": job.spec.get("log"),
                }
            )
        return {
            "ok": True,
            "mode": self.state.mode,
            "generation": self.generation,
            "policy_version": self.state.policy_version,
            "jobs": jobs,
            "copies": self._copies(),
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
                return {
                    "ok": False,
                    "error": "the current journal generation is unknown; the queue folder needs the Owner",
                }
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
            "boot": self.host.boot_id(),
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
        boot = self.host.boot_id()
        if boot is None or challenge.get("boot") != boot or self.host.monotonic() > challenge["expires_mono"]:
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
            # K-23, K-48'': the confirmation is the end's provenance, never machine proof, and never eligible.
            # Its copy lease is released in this same transition, to no other job.
            self._record(
                "ended",
                job_id=job_id,
                outcome=HUMAN_CONFIRMED,
                eligible=False,
                reason=f"released by challenge {challenge['challenge_id']}",
                proof=HUMAN_CONFIRMED,
                override={"challenge_id": challenge["challenge_id"], "generation": self.generation},
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
            if job.status == "launching" or not job.extent_known:
                continue  # unknown extent: only inspected proof by repair, or an Owner release, resolves it
            workload = self._workload(job.spec, job.runner if job.status == "uncertain" else None)
            if workload is None:
                if job.status == "running":
                    self._record(
                        "uncertain", job_id=job.job_id, reason="workload inspection failed", extent_known=True
                    )
                continue
            if workload:
                if job.status == "running":
                    alive = (
                        self.host.process_alive(ProcessIdentity.from_record(job.runner))
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
                proof=INSPECTED,
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
                proof=INSPECTED,
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
            proof=INSPECTED,
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
        assert self.policy is not None
        try:
            rebuilt = build_spec(
                {**job.spec["request"], "request_id": job.request_id},
                self.policy,
                self.policy.policy_id,
                job.job_id,
                self.host.pane(str(job.spec["submitter"]["pane"])),
            )
            self._refuse_registered(rebuilt)
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
        fsops.mkdir([self.root], job_dir)
        fsops.write_replace(
            [self.root],
            job_dir / f".tmp-broker-broker-{self.instance}-input",
            job_dir / "input",
            encode(
                {
                    "argv": job.spec["argv"],
                    "cwd": job.spec["run_dir"],
                    "log": job.spec["log"],
                    "roots": job.spec["roots"],
                }
            ),
        )
        fsops.mkdir([Path(r) for r in job.spec["roots"]], Path(str(job.spec["tmp"])))
        try:
            proofs = self._prove_resources(job)
        except Unproven as exc:  # nothing is cleaned to make a proof pass; the entry is reported
            self._record("refused", job_id=job.job_id, reason=f"launch proof failed (K-42a'): {exc}")
            return
        env = dict(job.spec["env"])  # the frozen effective environment only (B-10, B-14, K-42)
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
            stray = getattr(exc, "stray", None)
            runner = stray.as_record() if stray is not None else None
            started = self._workload(job.spec, runner)
            exists = self.host.group_exists(job.spec["group"])
            if runner is not None:
                self._record(
                    "uncertain",
                    job_id=job.job_id,
                    reason=f"spawn failed after creating process {runner['pid']}: {exc}",
                    extent_known=True,
                    runner=runner,
                )
            elif started is False and exists is False:
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
            runner=spawned.runner.as_record(),
            group=spawned.group,
            freshness=freshness,
            proofs=[proof.as_record() for proof in proofs],
        )

    def _writable_resources(self, job: Job) -> list[tuple[str, str]]:
        """K-42a': every writable directory resource the job receives, as (kind, path)."""
        spec = job.spec
        found = [("working folder", str(spec["workdir"])), ("target", str(spec["target"]["path"]))]
        found += [("cache", str(path)) for path in spec["caches"]]
        found += [("temporary folder", str(spec["tmp"])), ("log directory", str(spec["log_dir"]))]
        return found

    def _prove_resources(self, job: Job) -> list[TreeProof]:
        """K-42a', immediately before spawning: the ancestor proof and a complete no-follow walk of every
        writable directory resource. Raises `Unproven` naming the resource and the offending entry."""
        roots = [Path(r) for r in job.spec["roots"]]
        proofs = []
        for kind, path in self._writable_resources(job):
            try:
                proofs.append(prove_tree(roots, Path(path)))
            except Unproven as exc:
                raise Unproven(f"{kind} {exc}") from None
        return proofs

    def _prepare(self, job: Job) -> str:
        """Preparation under the job's exclusive leases. Returns the freshness method it applied
        (K-12a, B-12). Every job gets a working folder it alone leases (K-42): a fresh folder for a
        build, and the execution worktree for evidence and control."""
        roots = [Path(r) for r in job.spec["roots"]]
        workdir = Path(str(job.spec["workdir"]))
        assert_inside(roots, workdir)
        if os.path.lexists(workdir):
            raise ValueError(f"working folder {workdir} already exists")
        if job.klass == "build":
            fsops.mkdir(roots, workdir)
            touched = 0
            checkout = Path(str(job.spec["checkout"]))
            for path in files(checkout):
                relative = path.relative_to(checkout).as_posix()
                if relative.startswith(".git/"):
                    continue
                if any(fnmatch.fnmatch(relative, pattern) for pattern in job.spec["source_globs"]):
                    fsops.utime(roots, path)
                    touched += 1
            return f"touch: {touched} workspace-member source files"
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


def _manifest_problem(root: Path, manifest: list[str]) -> str | None:
    """K-39 without cleanup: an existing copy that lacks an entry of its manifest is damaged. A copy that
    is absent as a whole is not damage; it was removed by hand (K-48'', W-107b)."""
    if not os.path.lexists(root):
        return None
    for relative in manifest:
        if not os.path.lexists(root / relative):
            return f"manifest entry {relative} is missing"
    return None


__all__ = ["Broker", "BrokerRefused", "Contained", "StartReport"]
