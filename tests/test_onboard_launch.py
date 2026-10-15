"""Kit onboarding (`onboard`, release manifests) and session launch (`launch-plan`, `session-record`).

Positives check the exact plan and checklist. Each negative feeds one malformed input and expects an
error naming it, with nothing written (fail closed)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from minion_process import launch, onboard
from minion_process.cli import main
from minion_process.launch import LaunchError, plan, record
from minion_process.onboard import ManifestError

UUID = "01a12898-e54a-7450-b79d-9bc4d8b6cec2"
KIT = Path(__file__).resolve().parents[1]


def sessions(root: Path, data: Any) -> Path:
    (root / ".minion").mkdir(parents=True, exist_ok=True)
    path = root / ".minion" / "sessions.yaml"
    path.write_text(data if isinstance(data, str) else yaml.safe_dump(data), encoding="utf-8")
    return path


@pytest.fixture
def root(tmp_path: Path) -> Path:
    r = tmp_path / "proj"
    sessions(
        r,
        {
            "version": 1,
            "sessions": {
                "impl": {"tool": "codex", "network": True, "env": {"PUB_CACHE": ".tmp/pub-cache"}},
                "review": {"tool": "claude"},
                "offline": {"tool": "codex"},
            },
        },
    )
    return r


# -- launch-plan --------------------------------------------------------------------------------------
def test_codex_plan_is_the_ps5_launch_line(root: Path) -> None:
    p = plan(root, "impl", resume=UUID)
    base = str(root.resolve())
    assert p.argv == [
        "codex",
        "resume",
        UUID,
        "-C",
        base,
        "-s",
        "workspace-write",
        "-a",
        "on-request",
        "-c",
        "sandbox_workspace_write.writable_roots=[]",
        "-c",
        "sandbox_workspace_write.network_access=true",
        "-c",
        "sandbox_workspace_write.exclude_tmpdir_env_var=true",
        "-c",
        "sandbox_workspace_write.exclude_slash_tmp=true",
    ]
    temp = str(root.resolve() / ".tmp")
    assert p.env == {
        "TEMP": temp,
        "TMP": temp,
        "TMPDIR": temp,
        "PUB_CACHE": str(root.resolve() / ".tmp/pub-cache"),
    }
    assert (p.cwd, p.tool, p.resume) == (base, "codex", UUID)
    assert json.loads(p.as_json())["argv"] == p.argv


def test_codex_network_defaults_off_and_fresh_has_no_resume(root: Path) -> None:
    p = plan(root, "offline", fresh=True)
    assert "sandbox_workspace_write.network_access=false" in p.argv
    assert "resume" not in p.argv and p.resume is None


def test_claude_plan(root: Path) -> None:
    assert plan(root, "review", resume=UUID).argv == ["claude", "--resume", UUID]
    assert plan(root, "review", fresh=True).argv == ["claude"]


def test_recorded_session_is_resumed_and_explicit_wins(root: Path) -> None:
    written = record(root, "review", UUID)
    assert json.loads(written.read_text(encoding="utf-8")) == {"session": UUID, "source": "owner"}
    assert plan(root, "review").resume == UUID
    other = "d38a7a9e-4b92-4b3d-b93a-f8a20a35644b"
    assert plan(root, "review", resume=other).resume == other
    assert sorted(p.name for p in written.parent.iterdir()) == ["review.json"]  # no temporary left behind


def test_no_recorded_session_refuses(root: Path) -> None:
    with pytest.raises(LaunchError, match="pass --resume <id> once, or --fresh"):
        plan(root, "review")


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"resume": UUID, "fresh": True}, "exclude each other"),
        ({"resume": "x; rm -rf /"}, "not a session id"),
        ({"resume": "-rf"}, "not a session id"),
    ],
)
def test_plan_argument_errors(root: Path, kwargs: dict[str, Any], message: str) -> None:
    with pytest.raises(LaunchError, match=message):
        plan(root, "review", **kwargs)


def test_unknown_session(root: Path) -> None:
    with pytest.raises(LaunchError, match="no session 'nope'"):
        plan(root, "nope", fresh=True)
    with pytest.raises(LaunchError, match="no session 'nope'"):
        record(root, "nope", UUID)
    with pytest.raises(LaunchError, match="not a session id"):
        record(root, "review", "bad id")
    assert not (root / ".tmp").exists()


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("{", "not valid YAML"),
        ("[]", "exactly 'version' and 'sessions'"),
        ({"version": 2, "sessions": {"a": {"tool": "claude"}}}, "version must be 1"),
        ({"version": 1, "sessions": {}}, "non-empty mapping"),
        ({"version": 1, "sessions": {"Bad": {"tool": "claude"}}}, "session name"),
        ({"version": 1, "sessions": {"a": "claude"}}, "mapping of tool, network, env"),
        ({"version": 1, "sessions": {"a": {"tool": "claude", "x": 1}}}, "mapping of tool, network, env"),
        ({"version": 1, "sessions": {"a": {"tool": "vim"}}}, "tool: must be one of"),
        ({"version": 1, "sessions": {"a": {"tool": "codex", "network": "yes"}}}, "true or false"),
        ({"version": 1, "sessions": {"a": {"tool": "claude", "network": True}}}, "codex only"),
        ({"version": 1, "sessions": {"a": {"tool": "codex", "env": []}}}, "env: must be a mapping"),
        ({"version": 1, "sessions": {"a": {"tool": "codex", "env": {"lower": ".tmp/x"}}}}, "not an allowed"),
        ({"version": 1, "sessions": {"a": {"tool": "codex", "env": {"TEMP": ".tmp/x"}}}}, "not an allowed"),
    ],
)
def test_sessions_file_errors(tmp_path: Path, content: Any, message: str) -> None:
    sessions(tmp_path, content)
    with pytest.raises(LaunchError, match=message):
        plan(tmp_path, "a", fresh=True)


@pytest.mark.parametrize(
    "value", ["", "C:/x", "C:x", "/etc", "\\\\server\\share", "a\\b", "../x", ".tmp/../../x", "./x", ".", 5]
)
def test_env_paths_stay_inside(tmp_path: Path, value: Any) -> None:
    sessions(tmp_path, {"version": 1, "sessions": {"a": {"tool": "codex", "env": {"X": value}}}})
    with pytest.raises(LaunchError):
        plan(tmp_path, "a", fresh=True)


def test_missing_sessions_file(tmp_path: Path) -> None:
    with pytest.raises(LaunchError, match="not found"):
        plan(tmp_path, "a", fresh=True)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("{", "not valid JSON"),
        ('{"id": "x"}', "'session' string"),
        ('{"session": "no good"}', "not a session id"),
    ],
)
def test_recorded_file_errors(root: Path, content: str, message: str) -> None:
    (root / ".tmp/sessions").mkdir(parents=True)
    (root / ".tmp/sessions/review.json").write_text(content, encoding="utf-8")
    with pytest.raises(LaunchError, match=message):
        plan(root, "review")


def test_link_out_of_the_root_is_refused(tmp_path: Path, root: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (root / ".tmp").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symbolic links need a privilege on this host")
    with pytest.raises(LaunchError, match="resolves outside the root"):
        record(root, "review", UUID)
    assert list(outside.iterdir()) == []


# -- release manifests and onboard ----------------------------------------------------------------------
def test_shipped_manifests_load() -> None:
    versions = onboard.available()
    assert "0.4.0" in versions
    for v in versions:
        assert onboard.load_manifest(v)["version"] == v


def test_every_release_from_0_4_0_has_a_manifest() -> None:
    changelog = (KIT / "CHANGELOG.md").read_text(encoding="utf-8")
    listed = set(re.findall(r"^## ([0-9]+\.[0-9]+\.[0-9]+)", changelog, re.M))
    due = {v for v in listed if onboard.version_key(v) >= (0, 4, 0)}
    assert due and due <= set(onboard.available())


def test_the_package_version_has_a_manifest() -> None:
    text = (KIT / "pyproject.toml").read_text(encoding="utf-8")
    version = re.search(r'^version = "([^"]+)"', text, re.M)
    assert version
    if onboard.version_key(version[1]) >= (0, 4, 0):  # the package version is raised at release time
        assert version[1] in onboard.available()


@pytest.mark.parametrize(
    ("start", "end", "message"),
    [
        ("0.4.0", "0.3.0", "must be later"),
        ("0.4.0", "0.4.0", "must be later"),
        ("0.3.1", "9.9.9", "no manifest"),
        ("x", "0.4.0", "MAJOR.MINOR.PATCH"),
    ],
)
def test_between_errors(start: str, end: str, message: str) -> None:
    with pytest.raises(ManifestError, match=message):
        onboard.between(start, end)


def test_onboard_fresh_project_lists_todo(tmp_path: Path) -> None:
    results = onboard.onboard(tmp_path, "0.3.1", "0.4.0")
    status = {r.step: r.status for r in results}
    assert (
        status["KIT-INSTALL"] == "TODO" and status["MEMORY-DIR"] == "TODO" and status["WITNESSES"] == "MANUAL"
    )
    assert {"CODEX-RELAUNCH", "MEMORY-MIGRATED"} <= set(status)  # no sessions file: both tools
    assert "missing" in next(r.detail for r in results if r.step == "GUARD")


def adopted(root: Path, memory: str) -> None:
    (root / ".minion").mkdir(parents=True, exist_ok=True)
    (root / ".minion/kit.json").write_text("{}", encoding="utf-8")
    (root / ".tmp").mkdir(exist_ok=True)
    (root / ".claude").mkdir(exist_ok=True)
    settings = {"autoMemoryDirectory": memory, "hooks": {"PreToolUse": []}}
    (root / ".claude/settings.json").write_text(json.dumps(settings), encoding="utf-8")


def test_onboard_adopted_claude_project_passes(tmp_path: Path) -> None:
    sessions(tmp_path, {"version": 1, "sessions": {"review": {"tool": "claude"}}})
    adopted(tmp_path, str(tmp_path.resolve() / ".claude" / "memory").upper())  # backslashes and case
    results = onboard.onboard(tmp_path, "0.3.1", "0.4.0")
    assert {r.status for r in results if r.status != "MANUAL"} == {"PASS"}
    assert not any(r.step.startswith("CODEX") for r in results)  # codex steps do not apply
    assert main(["onboard", "--root", str(tmp_path), "--from", "0.3.1", "--to", "0.4.0"]) == 0


def test_onboard_wrong_memory_and_bad_json(tmp_path: Path) -> None:
    adopted(tmp_path, "C:/Users/someone/.claude/projects/x/memory")
    detail = next(r for r in onboard.onboard(tmp_path, "0.3.1", "0.4.0") if r.step == "MEMORY-DIR")
    assert detail.status == "TODO" and "expected" in detail.detail
    (tmp_path / ".claude/settings.json").write_text("{", encoding="utf-8")
    detail = next(r for r in onboard.onboard(tmp_path, "0.3.1", "0.4.0") if r.step == "MEMORY-DIR")
    assert detail.detail.endswith("is not valid JSON")
    (tmp_path / ".claude/settings.json").write_text('{"hooks": 1}', encoding="utf-8")
    guard = next(r for r in onboard.onboard(tmp_path, "0.3.1", "0.4.0") if r.step == "GUARD")
    assert guard.status == "TODO" and "not in" in guard.detail


def test_onboard_cli_markdown_and_exit(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["onboard", "--root", str(tmp_path), "--from", "0.3.1", "--to", "0.4.0", "--markdown"]) == 1
    out = capsys.readouterr().out
    assert out.startswith("### Kit onboarding 0.3.1 -> 0.4.0") and "- [ ] `0.4.0` **KIT-INSTALL**" in out
    assert out.rstrip().endswith("5 TODO, 6 MANUAL") and "INCOMPLETE" in out
    assert main(["onboard", "--root", str(tmp_path), "--from", "0.3.1", "--to", "0.4.0"]) == 1
    assert "TODO   0.4.0 KIT-INSTALL [owner]" in capsys.readouterr().out
    assert main(["onboard", "--root", str(tmp_path), "--from", "0.4.0", "--to", "0.3.0"]) == 1
    assert capsys.readouterr().out.startswith("ERROR: --to 0.3.0 must be later")


def test_launch_cli(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["session-record", "--root", str(root), "review", UUID]) == 0
    capsys.readouterr()
    assert main(["launch-plan", "--root", str(root), "review"]) == 0
    assert json.loads(capsys.readouterr().out)["argv"] == ["claude", "--resume", UUID]
    assert main(["launch-plan", "--root", str(root), "impl"]) == 1
    assert capsys.readouterr().out.startswith("ERROR: no recorded session for 'impl'")


# -- manifest shape: one mutation per rule ----------------------------------------------------------------
GOOD_STEP = {"id": "A-1", "title": "t", "actor": "owner", "applies": "all", "check": {"kind": "manual"}}


@pytest.fixture
def releases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "releases"
    folder.mkdir()
    monkeypatch.setattr("minion_process.onboard.resources.files", lambda package: folder)
    return folder


def write(folder: Path, version: str, data: Any) -> None:
    (folder / f"{version}.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")


def manifest(**step: Any) -> dict[str, Any]:
    return {"version": "1.0.0", "summary": "s", "steps": [{**GOOD_STEP, **step}]}


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ([], "exactly version, summary, steps"),
        ({**manifest(), "version": "1.0.1"}, "says version"),
        ({**manifest(), "summary": ""}, "summary"),
        ({**manifest(), "steps": []}, "non-empty list"),
        ({**manifest(), "steps": ["x"]}, "exactly id, title"),
        ({**manifest(), "steps": [GOOD_STEP, GOOD_STEP]}, "unique"),
        (manifest(id="lower"), "unique upper-case id"),
        (manifest(title=" "), "title"),
        (manifest(actor="robot"), "actor"),
        (manifest(applies="vim"), "applies"),
        (manifest(check={"kind": "run"}), "check.kind"),
        (manifest(check={"kind": "exists"}), "takes exactly"),
        (manifest(check={"kind": "contains", "path": "a", "text": ""}), "check.text"),
        (manifest(check={"kind": "exists", "path": "../a"}), "'..'"),
    ],
)
def test_manifest_shape_errors(releases: Path, data: Any, message: str) -> None:
    write(releases, "1.0.0", data)
    with pytest.raises(ManifestError, match=message):
        onboard.load_manifest("1.0.0")


def test_manifest_missing_and_ordering(releases: Path) -> None:
    with pytest.raises(ManifestError, match=r"no manifest for kit 1\.0\.0"):
        onboard.load_manifest("1.0.0")
    for v in ("1.10.0", "1.2.0", "1.9.0"):
        write(releases, v, {**manifest(), "version": v})
    (releases / "README.txt").write_text("not a manifest", encoding="utf-8")
    assert onboard.available() == ["1.2.0", "1.9.0", "1.10.0"]
    assert onboard.between("1.2.0", "1.10.0") == ["1.9.0", "1.10.0"]


def test_launch_module_constants_match_the_kit_text() -> None:
    text = (KIT / "project-scope.md").read_text(encoding="utf-8")
    for flag in (*launch.CODEX_SANDBOX, *launch.CODEX_TEMP):
        assert flag.strip("'") in text or flag in ("-s", "-a", "-c")
