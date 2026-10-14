"""A small host-queue world for tests: a project with a checkout and targets, a profile, a queue folder, a
broker on the fake host, and a confirmed initial policy."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from minion_process.hostqueue import client, confirm
from minion_process.hostqueue.broker import Broker
from minion_process.hostqueue.framing import decode_single
from minion_process.hostqueue.policy import OWNER_DEFAULTS

from .hostqueue_fake import FakeGit, FakeHost, pane_info

SHA = "a" * 40
SHA2 = "b" * 40


@dataclass
class World:
    tmp: Path
    root: Path
    queue: Path
    profile: Path
    host: FakeHost
    git: FakeGit
    broker: Broker

    # -- requests ---------------------------------------------------------------------------------------
    def request(self, body: dict[str, Any], step: bool = True) -> dict[str, Any]:
        request_id = client.put(self.queue, body)
        if not step:
            return {"request_id": request_id}
        self.broker.step()
        return decode_single((self.queue / "outbox" / f"{request_id}.res").read_bytes())

    def submit(
        self,
        klass: str = "build",
        target: str = "gate",
        sha: str | None = None,
        session: str = "s1",
        pane: str = "w1:p1",
        step: bool = True,
        **extra: Any,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "type": "submit",
            "class": klass,
            "profile": str(self.profile),
            "launcher": "rust",
            "target": target,
            "checkout": str(self.root / "repo"),
            "submitter": {"pane": pane, "session": session},
            **extra,
        }
        if sha:
            body["sha"] = sha
        return self.request(body, step=step)

    def confirm(self, code: str, step: bool = True) -> dict[str, Any]:
        request_id = confirm.handle(
            {"hook_event_name": "UserPromptSubmit", "prompt": f"CONFIRM QUEUE {code}", "session_id": "owner"},
            self.queue,
        )
        assert request_id is not None
        if not step:
            return {"request_id": request_id}
        self.broker.step()
        return decode_single((self.queue / "outbox" / f"{request_id}.res").read_bytes())

    def job(self, job_id: int) -> Any:
        return self.broker.state.jobs[job_id]

    def restart(self, repair: bool = False) -> Any:
        self.broker.stop()
        self.broker = Broker(self.queue, self.host, self.git, python="python")
        return self.broker.start(repair=repair)


def policy_dict(root: Path, version: int = 1, **over: Any) -> dict[str, Any]:
    return {
        "policy_id": "host-test",
        "version": version,
        **OWNER_DEFAULTS,
        "projects": {"proj": [str(root)]},
        **over,
    }


def make_world(tmp: Path, with_policy: bool = True) -> World:
    root = tmp / "proj"
    repo = root / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "lib.rs").write_text("fn main() {}\n", encoding="utf-8")
    (repo / "Cargo.toml").write_text("[package]\n", encoding="utf-8")
    (repo / "README.md").write_text("readme\n", encoding="utf-8")
    for name in ("gate", "controls", "reviewer", "gate2"):
        (root / "targets" / name).mkdir(parents=True)
    (root / "exec").mkdir()
    (root / "logs").mkdir()
    (root / "incidents").mkdir()
    (root / "incidents" / "none.md").write_text("no incidents\n", encoding="utf-8")
    (root / "authority").mkdir()
    (root / "authority" / "pins.txt").write_text("pinned\n", encoding="utf-8")
    profile = root / "profile.yaml"
    profile.write_text(
        yaml.safe_dump(
            {
                "build_queue": {
                    "state": str(tmp / "queue"),
                    "policy_id": "host-test",
                    "project": "proj",
                    "exec_root": str(root / "exec"),
                    "log_root": str(root / "logs"),
                    "targets": {
                        "gate": {"path": str(root / "targets" / "gate"), "kind": "gate"},
                        "gate2": {"path": str(root / "targets" / "gate2"), "kind": "gate"},
                        "alias": {"path": str(root / "targets" / "gate"), "kind": "gate"},
                        "controls": {"path": str(root / "targets" / "controls"), "kind": "controls"},
                        "reviewer": {
                            "path": str(root / "targets" / "reviewer"),
                            "kind": "reviewer",
                            "owner_agent": "claude",
                        },
                    },
                    "cleanup_references": {
                        "work_packages": [sys.executable, "-c", "print('no open work packages')"],
                        "incidents": [str(root / "incidents")],
                        "authority_cache": [str(root / "authority")],
                    },
                },
                "gates": {
                    "rust": {
                        "launcher": "cargo test",
                        "tiers": ["g3"],
                        "queue": {
                            "argv": ["cargo", "test", "--manifest-path", "{checkout}"],
                            "target_env": ["CARGO_TARGET_DIR"],
                            "source_globs": ["src/*.rs", "Cargo.toml"],
                        },
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    host = FakeHost()
    host.panes["w1:p1"] = pane_info("s1", "claude")
    host.panes["w1:p2"] = pane_info("s2", "codex")
    git = FakeGit()
    queue = tmp / "queue"
    broker = Broker(queue, host, git, python="python")
    broker.start()
    world = World(tmp, root, queue, profile, host, git, broker)
    if with_policy:
        response = world.request(
            {"type": "policy-set", "policy": policy_dict(root), "decision": "issuecomment-6139069723"}
        )
        assert response["ok"], response
        applied = world.confirm(response["code"])
        assert applied["ok"], applied
    return world
