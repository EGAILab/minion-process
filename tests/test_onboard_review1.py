"""KIT-ONBOARDING review 1 remediation: R001 installer reparse points, R002 bound session recording,
R003 whole-string identifiers, R004 isolated pip. Installer witnesses run the unmodified script under the
test's base temp with a fake pip; nothing is installed and nothing outside the base temp is touched."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from minion_process import launch, onboard
from minion_process.cli import main
from minion_process.launch import LaunchError, plan, record
from minion_process.onboard import ManifestError

UUID = "01a12898-e54a-7450-b79d-9bc4d8b6cec2"
OLD = "d38a7a9e-4b92-4b3d-b93a-f8a20a35644b"
KIT = Path(__file__).resolve().parents[1]
INSTALL = KIT / "bootstrap" / "install.ps1"


def sessions(root: Path, data: Any) -> None:
    (root / ".minion").mkdir(parents=True, exist_ok=True)
    (root / ".minion" / "sessions.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    r = tmp_path / "proj"
    sessions(r, {"version": 1, "sessions": {"impl": {"tool": "codex"}, "review": {"tool": "claude"}}})
    return r


# -- R003 ------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("bad", [UUID + "\n", UUID + "\r\n", "\n" + UUID, UUID + " "])
def test_r003_session_ids_are_whole_string(root: Path, bad: str) -> None:
    with pytest.raises(LaunchError, match="not a session id"):
        plan(root, "review", resume=bad)
    with pytest.raises(LaunchError, match="not a session id"):
        record(root, "review", bad)
    assert not (root / ".tmp").exists()


def test_r003_names_and_versions_are_whole_string(tmp_path: Path) -> None:
    sessions(tmp_path, {"version": 1, "sessions": {"a\n": {"tool": "claude"}}})
    with pytest.raises(LaunchError, match="session name"):
        plan(tmp_path, "a\n", fresh=True)
    sessions(tmp_path, {"version": 1, "sessions": {"a": {"tool": "codex", "env": {"X\n": ".tmp/x"}}}})
    with pytest.raises(LaunchError, match="not an allowed"):
        plan(tmp_path, "a", fresh=True)
    with pytest.raises(ManifestError, match=r"MAJOR.MINOR.PATCH"):
        onboard.version_key("0.4.0\n")


def test_r003_step_id_is_whole_string(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("minion_process.onboard.resources.files", lambda package: tmp_path)
    step = {"id": "A-1\n", "title": "t", "actor": "owner", "applies": "all", "check": {"kind": "manual"}}
    data = {"version": "1.0.0", "summary": "s", "steps": [step]}
    (tmp_path / "1.0.0.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ManifestError, match="unique upper-case id"):
        onboard.load_manifest("1.0.0")


# -- R002 ------------------------------------------------------------------------------------------------
def herdr_get(pane: str, tool: str, cwd: Path | str, sid: Any) -> str:
    agent: dict[str, Any] = {"pane_id": pane, "agent": tool, "cwd": str(cwd), "agent_status": "working"}
    if sid is not None:
        agent["agent_session"] = {"value": sid}
    return json.dumps({"result": {"agent": agent, "type": "agent_info"}})


def test_r002_observation_of_this_launch_is_recorded(root: Path) -> None:
    sid, reason = launch.observe(root, "impl", herdr_get("w7:p1", "codex", root, UUID), "w7:p1", [])
    assert (sid, reason) == (UUID, "recorded")
    body = json.loads((root / ".tmp/sessions/impl.json").read_text(encoding="utf-8"))
    assert body == {"session": UUID, "source": "herdr", "pane": "w7:p1", "tool": "codex"}
    assert plan(root, "impl").resume == UUID


@pytest.mark.parametrize(
    ("observation", "exclude", "reason"),
    [
        (lambda r: herdr_get("w7:p2", "codex", r, UUID), [], "for pane 'w7:p2'"),
        (lambda r: herdr_get("w7:p1", "claude", r, UUID), [], "pane runs 'claude'"),
        (lambda r: herdr_get("w7:p1", "codex", r.parent, UUID), [], "not the project root"),
        (lambda r: herdr_get("w7:p1", "codex", r, OLD), [OLD], "excluded for this launch"),
        (lambda r: herdr_get("w7:p1", "codex", r, None), [], "no session id observed"),
        (lambda r: herdr_get("w7:p1", "codex", r, UUID + "\n"), [], "not a session id"),
        (lambda r: "{", [], "not a herdr agent observation"),
        (lambda r: '{"result": {}}', [], "not a herdr agent observation"),
        (lambda r: '{"result": {"agent": []}}', [], "not a herdr agent observation"),
    ],
)
def test_r002_foreign_or_stale_observations_write_nothing(
    root: Path, observation: Any, exclude: list[str], reason: str
) -> None:
    record(root, "impl", OLD)  # a usable target recorded earlier must survive
    sid, why = launch.observe(root, "impl", observation(root), "w7:p1", exclude)
    assert sid is None and reason in why
    assert json.loads((root / ".tmp/sessions/impl.json").read_text(encoding="utf-8"))["session"] == OLD


def test_r002_owner_record_has_provenance(root: Path) -> None:
    assert json.loads(record(root, "review", UUID).read_text(encoding="utf-8")) == {
        "session": UUID,
        "source": "owner",
    }
    with pytest.raises(LaunchError, match="no session 'nope'"):
        launch.observe(root, "nope", "{}", "w7:p1", [])


def test_r002_observe_cli(
    root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(herdr_get("w7:p1", "codex", root, UUID)))
    assert main(["session-observe", "--root", str(root), "impl", "--pane", "w7:p1"]) == 0
    assert capsys.readouterr().out.strip() == UUID
    monkeypatch.setattr("sys.stdin", io.StringIO(herdr_get("w7:p1", "codex", root, UUID)))
    assert main(["session-observe", "--root", str(root), "impl", "--pane", "w7:p1", "--exclude", UUID]) == 2
    assert capsys.readouterr().out.startswith("NOT-RECORDED: id was excluded")


# -- R001 and R004: the installer, run unmodified ----------------------------------------------------------
windows = pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell installer")


def install(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    command = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(INSTALL), *args]
    return subprocess.run(command, capture_output=True, text=True, env=env, timeout=300, check=False)


def junction(link: Path, target: Path) -> None:
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True)


@windows
@pytest.mark.parametrize("redirected", [".minion", ".tmp"])
def test_r001_junction_below_the_root_is_refused_before_any_write(tmp_path: Path, redirected: str) -> None:
    project, sibling = tmp_path / "project", tmp_path / "sibling"
    project.mkdir()
    sibling.mkdir()
    junction(project / redirected, sibling)
    result = install("-Root", str(project), "-Version", "0.4.0", "-Python", "no-such-python")
    assert result.returncode != 0
    assert "redirected path component" in result.stderr + result.stdout
    assert list(sibling.iterdir()) == []
    assert [p.name for p in project.iterdir()] == [redirected]


FAKE_PIP = """
import json, os, pathlib, sys, sysconfig
seen = {k: v for k, v in os.environ.items() if k.startswith(("PIP_", "PYTHON", "TEMP", "TMP"))}
log = {"argv": sys.argv[1:], "env": seen}
pathlib.Path(os.environ["FAKE_PIP_LOG"]).write_text(json.dumps(log), encoding="utf-8")
import tempfile
with tempfile.NamedTemporaryFile(delete=False) as handle:
    handle.write(b"probe")
cache = pathlib.Path(sys.argv[sys.argv.index("--cache-dir") + 1])
(cache / "wheels").mkdir(parents=True, exist_ok=True)
(cache / "wheels" / "probe.txt").write_text("probe", encoding="utf-8")
site = pathlib.Path(sysconfig.get_paths()["purelib"])
(site / "minion_process" / "bootstrap").mkdir(parents=True, exist_ok=True)
(site / "minion_process" / "__init__.py").write_text("", encoding="utf-8")
(site / "minion_process" / "bootstrap" / "__init__.py").write_text("", encoding="utf-8")
(site / "minion_process" / "bootstrap" / "relaunch.ps1").write_text("# fake", encoding="utf-8")
skill = site / "minion_process" / "bootstrap" / "skills" / "kit-onboard"
skill.mkdir(parents=True, exist_ok=True)
(skill / "SKILL.md").write_text("# skill", encoding="utf-8")
rules = site / "minion_process" / "bootstrap" / "rules"
rules.mkdir(parents=True, exist_ok=True)
(rules / "kit-sentinel.rules").write_text("# sentinel", encoding="utf-8")
meta = site / "minion_process-0.4.0.dist-info"
meta.mkdir(exist_ok=True)
metadata = "Metadata-Version: 2.1\\nName: minion-process\\nVersion: 0.4.0\\n"
(meta / "METADATA").write_text(metadata, encoding="utf-8")
"""


def fake_pip_venv(project: Path) -> None:
    venv = project / ".tmp" / "kit" / "0.4.0" / "venv"
    subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", str(venv)], check=True, capture_output=True
    )
    query = "import sysconfig; print(sysconfig.get_paths()['purelib'])"
    purelib = subprocess.run(
        [str(venv / "Scripts" / "python.exe"), "-c", query], check=True, capture_output=True, text=True
    ).stdout.strip()
    (Path(purelib) / "pip").mkdir()
    (Path(purelib) / "pip" / "__init__.py").write_text("", encoding="utf-8")
    (Path(purelib) / "pip" / "__main__.py").write_text(FAKE_PIP, encoding="utf-8")


@windows
def test_r004_inherited_pip_destination_and_config_do_not_reach_pip(tmp_path: Path) -> None:
    project, sibling = tmp_path / "project", tmp_path / "sibling"
    project.mkdir()
    sibling.mkdir()
    fake_pip_venv(project)
    (project / ".codex" / "rules").mkdir(parents=True)
    (project / ".codex" / "rules" / "default.rules").write_text("# project", encoding="utf-8")
    log = project / ".tmp" / "fake-pip.json"
    env = {
        **os.environ,
        "FAKE_PIP_LOG": str(log),
        "PIP_TARGET": str(sibling),
        "PIP_PREFIX": str(sibling),
        "PIP_CONFIG_FILE": str(sibling / "pip.ini"),
        "PYTHONPATH": str(sibling),
    }
    result = install("-Root", str(project), "-Version", "0.4.0", "-From", "minion-process", env=env)
    assert result.returncode == 0, result.stderr
    seen = json.loads(log.read_text(encoding="utf-8"))
    assert "--isolated" in seen["argv"] and "--cache-dir" in seen["argv"]
    assert not {"PIP_TARGET", "PIP_PREFIX", "PYTHONPATH"} & set(seen["env"])
    assert seen["env"]["PIP_CONFIG_FILE"] == "nul"
    assert list(sibling.iterdir()) == []
    assert json.loads((project / ".minion" / "kit.json").read_text(encoding="utf-8"))["version"] == "0.4.0"
    assert (project / ".minion" / "relaunch.ps1").read_text(encoding="utf-8") == "# fake"
    for base in (".claude", ".agents"):
        assert (project / base / "skills" / "kit-onboard" / "SKILL.md").read_text(
            encoding="utf-8"
        ) == "# skill"
    # The rules sentinel is its own file; the project's existing rules are left as they were.
    assert (project / ".codex" / "rules" / "kit-sentinel.rules").read_text(encoding="utf-8") == "# sentinel"
    assert (project / ".codex" / "rules" / "default.rules").read_text(encoding="utf-8") == "# project"


@windows
def test_r001_link_inside_the_venv_is_refused(tmp_path: Path) -> None:
    project, sibling = tmp_path / "project", tmp_path / "sibling"
    project.mkdir()
    sibling.mkdir()
    fake_pip_venv(project)
    junction(project / ".tmp" / "kit" / "0.4.0" / "venv" / "Lib" / "escape", sibling)
    env = {**os.environ, "FAKE_PIP_LOG": str(project / ".tmp" / "fake-pip.json")}
    result = install("-Root", str(project), "-Version", "0.4.0", "-From", "minion-process", env=env)
    assert result.returncode != 0 and "refusing a link, junction" in result.stderr + result.stdout
    assert not (project / ".tmp" / "fake-pip.json").exists()  # refused before pip ran
    assert list(sibling.iterdir()) == []
