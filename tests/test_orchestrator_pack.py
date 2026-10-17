"""Kit 0.4.2 Orchestrator onboarding pack (`orchestrator.md` OR-5): templates, `orch-render` and the
Owner ACL script.

The discriminating check is the M-Remote round trip. The templates were made from M-Remote's reviewed and
installed files (`minion-remote-docs` `4be18ceb`, `process/enforcement/`). Rendering them with M-Remote's
values must give those exact bytes back, so the generalisation changed nothing but project strings."""

from __future__ import annotations

import copy
import hashlib
from importlib import resources
from pathlib import Path
from typing import Any

import pytest
import yaml

from minion_process import onboard, orchestrator
from minion_process.cli import main
from minion_process.orchestrator import PackError

KIT = Path(__file__).resolve().parents[1]
PACK = resources.files("minion_process.bootstrap") / "orchestrator"
# sha256 of the reviewed files at minion-remote-docs 4be18ceb (installed in Minion-Remote on 2026-10-17).
REVIEWED = {
    "outside-root-guard.mjs": "7fcbc336745c575e1b14ca355b646024d87a3d925e47ef99a80b0d6d25f637c0",
    "guard-witness.mjs": "950b77089b0db52fd6dbf84a1699589892d37cb8554eed8b252d06ba68368c15",
    "settings.json": "f34bb1073255c591dcb058913a656da34c6d6d3ba1187f2f80e2f8d3999ed4ca",
    "m-remote.rules": "66854a83e1476b2556015e251bdef9fed56d325758bb0b8c5727dc6f971f2878",
}


def m_remote() -> dict[str, Any]:
    return yaml.safe_load((PACK / "values.m-remote.yaml").read_text("utf-8"))


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_m_remote_values_render_the_reviewed_files_byte_for_byte() -> None:
    files = orchestrator.render_all(m_remote())
    for name, digest in REVIEWED.items():
        assert sha(files[name]) == digest, name


def test_control_a_changed_value_changes_the_reviewed_bytes() -> None:
    """Negative control for the round trip: the comparison is sensitive to a single value."""
    values = m_remote()
    values["read_exec_roots"] = values["read_exec_roots"][:-1]
    guard = orchestrator.render_all(values)["outside-root-guard.mjs"]
    assert sha(guard) != REVIEWED["outside-root-guard.mjs"]


def test_every_template_is_rendered_and_every_placeholder_is_known() -> None:
    names = {p.name for p in PACK.iterdir() if p.name.endswith(".tmpl")}
    assert names == set(orchestrator.TEMPLATES)
    known = set(orchestrator.mapping(m_remote()))
    used = set()
    for name in names:
        used |= set(orchestrator.PLACEHOLDER.findall(orchestrator.template(name)))
    assert used == known


def test_another_project_renders_with_no_m_remote_string_left() -> None:
    values = m_remote() | {
        "project": "Minion-Memory",
        "slug": "minion-memory",
        "short": "M-Memory",
        "root": r"E:\AI\Projects\OpenMinds\Minions\Minion-Memory",
        "repos": ["minion-memory"],
        "issue": "EGAILab/minion-memory#1",
        "rules_file": "m-memory.rules",
        "exempt_decision": "Owner decision 2026-10-17 (kit 0.4.2 pack)",
    }
    files = orchestrator.render_all(values)
    assert "m-memory.rules" in files
    for name, text in files.items():
        lowered = text.replace("Minions\\\\Minion-Remote", "").replace('"Minions", "Minion-Remote"', "")
        assert "minion-remote" not in lowered.lower(), name  # the witness keeps only its synthetic layout
    assert "E:/AI/Projects/OpenMinds/Minions/Minion-Memory/minion-memory" in files["codex-launch.ps1"]
    assert "$env:GIT_CONFIG_COUNT   = '1'" in files["codex-launch.ps1"]


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("root", r"\\server\share\Minion-Remote"),
        ("root", r"E:\AI\..\Minion-Remote"),
        ("root", r"E:Minion-Remote"),
        ("root", r"E:\AI\Projects\OpenMinds\Minions\Other"),
        ("read_exec_roots", ["C:\\Windows\\"]),
        ("read_exec_roots", []),
        ("repos", ["../minion-agent"]),
        ("repos", [r"C:\abs"]),
        ("project", 'Minion"Remote'),
        ("orchestrator", "orchestrator"),
        ("rules_file", "../x.rules"),
        ("issue", "minion-remote#1"),
    ],
)
def test_bad_values_are_refused(key: str, value: object) -> None:
    values = copy.deepcopy(m_remote())
    values[key] = value
    with pytest.raises(PackError):
        orchestrator.render_all(values)


def test_missing_or_unknown_value_keys_are_refused() -> None:
    values = m_remote()
    with pytest.raises(PackError):
        orchestrator.render_all({k: v for k, v in values.items() if k != "home"})
    with pytest.raises(PackError):
        orchestrator.render_all(values | {"extra": 1})


def test_unknown_or_surviving_placeholders_are_refused() -> None:
    with pytest.raises(PackError):
        orchestrator.render("{{NOPE}}", {"A": "x"})
    with pytest.raises(PackError):
        orchestrator.render("{{A}}", {"A": "{{B}}"})


def test_orch_render_writes_only_a_new_folder_inside_the_root(tmp_path: Path) -> None:
    root = tmp_path / "Minion-Remote"
    (root / "docs").mkdir(parents=True)
    values = m_remote() | {"root": str(root)}
    (root / "docs" / "values.yaml").write_text(yaml.safe_dump(values), "utf-8")

    def run(values: str, *out: str) -> int:
        return main(["orch-render", "--root", str(root), "--values", values, *out])

    assert run("docs/values.yaml", "--out", "docs/pack") == 0
    out = root / "docs" / "pack"
    assert sorted(p.name for p in out.iterdir()) == sorted(
        n.format(rules_file="m-remote.rules") for n, _ in orchestrator.TEMPLATES.values()
    )
    assert b"\r\n" not in (out / "settings.json").read_bytes()
    # A second run into the same (now non-empty) folder is refused and changes nothing.
    before = {p.name: p.read_bytes() for p in out.iterdir()}
    assert run("docs/values.yaml", "--out", "docs/pack") == 1
    assert {p.name: p.read_bytes() for p in out.iterdir()} == before
    # Output and values outside the root are refused before anything is written.
    for bad in (["--out", "../escape"], ["--out", str(tmp_path / "abs")]):
        assert run("docs/values.yaml", *bad) == 1
    assert not (tmp_path / "escape").exists() and not (tmp_path / "abs").exists()
    assert run("../v.yaml", "--out", "docs/p2") == 1


def test_manifest_0_4_2_and_its_owner_steps_have_runbook_letters() -> None:
    steps = {s["id"]: s for s in onboard.load_manifest("0.4.2")["steps"]}
    wanted = {"ORCH-OPTIN", "ORCH-GUARD", "ORCH-ACL", "ORCH-TRUST", "ORCH-LAUNCH", "ORCH-ACTIVATE"}
    assert wanted <= set(steps)
    skill_file = resources.files("minion_process.bootstrap") / "skills" / "kit-onboard" / "SKILL.md"
    skill = skill_file.read_text("utf-8")
    for letter in "FGH":
        assert f"\n{letter}. " in skill
    assert "owner-acl.ps1 -Root <root> -Check" in skill


def test_owner_acl_script_fails_closed_and_has_a_check_mode() -> None:
    text = (PACK / "owner-acl.ps1").read_text("utf-8")
    assert "[switch]$Check" in text
    assert "ReparsePoint" in text and "Resolves outside the root" in text
    assert "NON-elevated" in text and "/setowner" in text
    assert "Remove-Item" not in text and "Move-Item" not in text and "/remove" not in text.replace(
        "/remove:g $Group  - slow", ""
    )
    # The deny set matches M-Remote's reviewed Owner commands (root D,DC; .claude; settings; hooks; .codex).
    for spec in ("@('D', 'DC')", "@('WD', 'AD', 'DC', 'D', 'WDAC', 'WO')", "@('W', 'D', 'WDAC', 'WO')"):
        assert spec in text


def test_pack_is_package_data_and_kept_lf() -> None:
    assert '"orchestrator/*"' in (KIT / "pyproject.toml").read_text(encoding="utf-8")
    attributes = (KIT / ".gitattributes").read_text("utf-8")
    assert "minion_process/bootstrap/orchestrator/** text eol=lf" in attributes


def test_entry_routing_section_carries_the_owner_rules() -> None:
    text = orchestrator.render_all(m_remote())["entry-routing.md"]
    assert text.startswith("## Orchestrator routing (PROC-KIT-ORCH)\n")
    assert "herdr agent prompt gru-orchestrator <text>" in text
    assert "The implementer merges its own PR after an independent reviewer's APPROVE" in text
    assert "blocking findings only" in text and "issuecomment-6228553990" in text
