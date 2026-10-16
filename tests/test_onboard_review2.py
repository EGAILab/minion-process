"""KIT-ONBOARDING review 2 remediation, run through the unmodified scripts against synthetic projects under
the test's base temp:

- R001: a hard-linked output file is replaced, never written through; pip's cache and temp are a new
  per-run folder, so a pre-existing junction in an old cache is never used; a hard-linked file inside
  the venv is refused before pip runs.
- R002: relaunch.ps1 records nothing when its pre-launch read of the pane fails, and a fresh launch never
  records the id recorded before it. herdr and the agent are fakes found first on a PATH that holds only
  them and the Windows system folders, so no real agent can start."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import sysconfig
from pathlib import Path
from typing import Any

import pytest
import yaml

from minion_process import launch

from .test_onboard_review1 import fake_pip_venv, install, junction

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell scripts")
KIT = Path(__file__).resolve().parents[1]
RELAUNCH = KIT / "minion_process" / "bootstrap" / "relaunch.ps1"
OWNER = "0aaaaaaa-0000-4000-8000-000000000001"
STALE = "0bbbbbbb-0000-4000-8000-000000000002"
NEW = "0ccccccc-0000-4000-8000-000000000003"


def two_folders(tmp_path: Path) -> tuple[Path, Path]:
    project, sibling = tmp_path / "project", tmp_path / "sibling"
    project.mkdir()
    sibling.mkdir()
    return project, sibling


def fake_env(project: Path) -> dict[str, str]:
    return {**os.environ, "FAKE_PIP_LOG": str(project / "fake-pip.json")}


# -- R001 --------------------------------------------------------------------------------------------------
def test_r001_hard_linked_output_is_replaced_not_written_through(tmp_path: Path) -> None:
    project, sibling = two_folders(tmp_path)
    fake_pip_venv(project)
    (sibling / "kit.json").write_text("KEEP", encoding="utf-8")
    (project / ".minion").mkdir()
    os.link(sibling / "kit.json", project / ".minion" / "kit.json")
    result = install(
        "-Root", str(project), "-Version", "0.4.0", "-From", "minion-process", env=fake_env(project)
    )
    assert result.returncode == 0, result.stderr
    assert (sibling / "kit.json").read_text(encoding="utf-8") == "KEEP"
    assert json.loads((project / ".minion" / "kit.json").read_text(encoding="utf-8"))["version"] == "0.4.0"
    assert os.stat(project / ".minion" / "kit.json").st_nlink == 1


def test_r001_cache_and_temp_are_a_new_folder_each_run(tmp_path: Path) -> None:
    project, sibling = two_folders(tmp_path)
    fake_pip_venv(project)
    (project / ".tmp" / "pip-cache").mkdir(parents=True)
    junction(project / ".tmp" / "pip-cache" / "wheels", sibling)  # an old cache layout, redirected
    result = install(
        "-Root", str(project), "-Version", "0.4.0", "-From", "minion-process", env=fake_env(project)
    )
    assert result.returncode == 0, result.stderr
    seen = json.loads((project / "fake-pip.json").read_text(encoding="utf-8"))
    cache = Path(seen["argv"][seen["argv"].index("--cache-dir") + 1])
    run = cache.parent
    assert run.parent == project / ".tmp" / "kit" / "0.4.0" and run.name.startswith("run-")
    assert seen["env"]["TEMP"] == str(run / "temp") and (cache / "wheels" / "probe.txt").exists()
    assert list(sibling.iterdir()) == []


def test_r001_hard_linked_file_in_the_venv_is_refused_before_pip(tmp_path: Path) -> None:
    project, sibling = two_folders(tmp_path)
    fake_pip_venv(project)
    (sibling / "shared.py").write_text("KEEP", encoding="utf-8")
    os.link(sibling / "shared.py", project / ".tmp" / "kit" / "0.4.0" / "venv" / "Lib" / "shared.py")
    result = install(
        "-Root", str(project), "-Version", "0.4.0", "-From", "minion-process", env=fake_env(project)
    )
    assert result.returncode != 0 and "hard-linked file" in result.stderr + result.stdout
    assert not (project / "fake-pip.json").exists()
    assert (sibling / "shared.py").read_text(encoding="utf-8") == "KEEP"


# -- R002: the unmodified relaunch.ps1 with fake herdr and a fake agent ------------------------------------
FAKE_HERDR = """
import json, os, pathlib, sys
state = pathlib.Path(os.environ["FAKE_HERDR_DIR"])
script = json.loads((state / "script.json").read_text(encoding="utf-8"))
count = state / "count"
n = int(count.read_text()) if count.exists() else 0
count.write_text(str(n + 1))
with (state / "calls.txt").open("a", encoding="utf-8") as log:
    log.write(" ".join(sys.argv[1:]) + "\\n")
step = script[min(n, len(script) - 1)]
print(step["out"])
sys.exit(step["exit"])
"""


def python_with_kit(tmp_path: Path) -> Path:
    """A venv whose `-I` interpreter imports this checkout and the test environment's dependencies."""
    venv = tmp_path / "kitpy"
    subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", str(venv)], check=True, capture_output=True
    )
    py = venv / "Scripts" / "python.exe"
    query = "import sysconfig; print(sysconfig.get_paths()['purelib'])"
    purelib = Path(
        subprocess.run([str(py), "-c", query], check=True, capture_output=True, text=True).stdout.strip()
    )
    paths = [str(KIT), sysconfig.get_paths()["purelib"]]
    (purelib / "kit-under-test.pth").write_text("\n".join(paths) + "\n", encoding="utf-8")
    return py


def root_pane(
    sid: str | None, tool: str = "codex", status: str = "done", agent: bool | None = None
) -> dict[str, Any]:
    """A `herdr pane get w7:p1` result in the project root (`<ROOT>` is filled in by `relaunch`)."""
    body: dict[str, Any] = {"pane_id": "w7:p1", "agent_status": status, "cwd": "<ROOT>"}
    if agent or (agent is None and sid is not None):
        body["agent"] = tool
    if sid is not None:
        body["agent_session"] = {"value": sid}
    return {"exit": 0, "out": json.dumps({"result": {"pane": body, "type": "pane_info"}})}


FAIL = {"exit": 1, "out": json.dumps({"error": {"code": "server_unavailable"}})}


def relaunch(
    tmp_path: Path, script: list[dict[str, Any]], *args: str
) -> tuple[Path, subprocess.CompletedProcess[str]]:
    project = tmp_path / "project"
    (project / ".minion").mkdir(parents=True)
    sessions = {"version": 1, "sessions": {"impl": {"tool": "codex"}}}
    (project / ".minion" / "sessions.yaml").write_text(yaml.safe_dump(sessions), encoding="utf-8")
    kit = {"version": "0.4.0", "python": str(python_with_kit(tmp_path))}
    (project / ".minion" / "kit.json").write_text(json.dumps(kit), encoding="utf-8")
    (project / ".minion" / "relaunch.ps1").write_bytes(RELAUNCH.read_bytes())
    launch.record(project, "impl", OWNER)
    fakes, state = tmp_path / "fakebin", tmp_path / "herdr-state"
    fakes.mkdir()
    state.mkdir()
    script = [{**s, "out": s["out"].replace("<ROOT>", str(project).replace("\\", "\\\\"))} for s in script]
    (state / "script.json").write_text(json.dumps(script), encoding="utf-8")
    (fakes / "herdr.py").write_text(FAKE_HERDR, encoding="utf-8")
    (fakes / "herdr.cmd").write_text(f'@"{sys.executable}" "{fakes / "herdr.py"}" %*\r\n', encoding="utf-8")
    (fakes / "codex.cmd").write_text("@ping -n 5 127.0.0.1 >nul\r\n", encoding="utf-8")  # about 4 s
    system = os.environ["SYSTEMROOT"]
    env = {
        **{k: v for k, v in os.environ.items() if k.upper() not in ("PATH", "HERDR_PANE_ID")},
        "PATH": ";".join([str(fakes), f"{system}\\System32", f"{system}\\System32\\WindowsPowerShell\\v1.0"]),
        "HERDR_PANE_ID": "w7:p1",
        "FAKE_HERDR_DIR": str(state),
        "MINION_RELAUNCH_POLL_SECONDS": "1",
    }
    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(project / ".minion" / "relaunch.ps1"),
    ]
    result = subprocess.run(
        [*command, "impl", *args], capture_output=True, text=True, env=env, timeout=120, check=False
    )
    return project, result


def recorded(project: Path) -> dict[str, Any]:
    body: dict[str, Any] = json.loads(
        (project / ".tmp" / "sessions" / "impl.json").read_text(encoding="utf-8")
    )
    return body


def test_r002_unreadable_baseline_records_nothing(tmp_path: Path) -> None:
    project, result = relaunch(tmp_path, [FAIL, root_pane(STALE)], "-Fresh")
    assert result.returncode == 0, result.stderr
    assert "no usable herdr baseline" in result.stderr + result.stdout
    assert recorded(project) == {"session": OWNER, "source": "owner"}


def test_r002_fresh_launch_never_records_the_previous_id(tmp_path: Path) -> None:
    project, result = relaunch(tmp_path, [root_pane(None), root_pane(OWNER)], "-Fresh")
    assert result.returncode == 0, result.stderr
    assert recorded(project) == {"session": OWNER, "source": "owner"}
    calls = (tmp_path / "herdr-state" / "calls.txt").read_text(encoding="utf-8").splitlines()
    assert calls[0] == "pane get w7:p1" and len(calls) >= 2  # the recorder did observe


def test_r002_stale_id_shown_before_the_launch_is_excluded(tmp_path: Path) -> None:
    project, result = relaunch(tmp_path, [root_pane(STALE)], "-Fresh")
    assert result.returncode == 0, result.stderr
    assert recorded(project)["session"] == OWNER


def test_r002_new_session_of_this_launch_is_recorded(tmp_path: Path) -> None:
    project, result = relaunch(tmp_path, [root_pane(None), root_pane(NEW, status="working")], "-Fresh")
    assert result.returncode == 0, result.stderr
    assert recorded(project) == {"session": NEW, "source": "herdr", "pane": "w7:p1", "tool": "codex"}


def test_r002_agent_without_a_detected_id_is_not_an_empty_pane(tmp_path: Path) -> None:
    project, result = relaunch(tmp_path, [root_pane(None, agent=True), root_pane(STALE)], "-Fresh")
    assert result.returncode == 0, result.stderr
    assert "no usable herdr baseline" in result.stderr + result.stdout
    assert recorded(project) == {"session": OWNER, "source": "owner"}


def test_r001_inherited_tmpdir_does_not_redirect_child_temp(tmp_path: Path) -> None:
    project, sibling = two_folders(tmp_path)
    fake_pip_venv(project)
    env = {**fake_env(project), "TMPDIR": str(sibling), "TEMP": str(sibling), "TMP": str(sibling)}
    result = install("-Root", str(project), "-Version", "0.4.0", "-From", "minion-process", env=env)
    assert result.returncode == 0, result.stderr
    assert list(sibling.iterdir()) == []
    seen = json.loads((project / "fake-pip.json").read_text(encoding="utf-8"))
    run_temp = Path(seen["env"]["TEMP"])
    assert seen["env"]["TMPDIR"] == str(run_temp) and run_temp.parent.name.startswith("run-")
    assert [p.read_bytes() for p in run_temp.iterdir()] == [b"probe"]  # the default-temp write landed here
