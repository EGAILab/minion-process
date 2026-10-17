"""Kit 0.4.2 Orchestrator onboarding pack (`orchestrator.md` OR-5): templates, `orch-render` and the
Owner ACL script.

The discriminating check is the M-Remote round trip. The templates were made from M-Remote's reviewed and
installed files (`minion-remote-docs` `4be18ceb`, `process/enforcement/`). Rendering them with M-Remote's
values gives `settings.json` and the Codex rules back byte for byte. The guard and its witness gained the
`.claude/skills` and `.minion` control paths in review 1 (KIT-042-R004), so their M-Remote rendering is
pinned to the new expected bytes, and M-Remote upgrades its installed guard when it adopts 0.4.2."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
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
    "settings.json": "f34bb1073255c591dcb058913a656da34c6d6d3ba1187f2f80e2f8d3999ed4ca",
    "m-remote.rules": "66854a83e1476b2556015e251bdef9fed56d325758bb0b8c5727dc6f971f2878",
}
# The M-Remote guard and witness as installed (4be18ceb), and their 0.4.2 rendering (R004 paths added).
INSTALLED_GUARD = {
    "outside-root-guard.mjs": "7fcbc336745c575e1b14ca355b646024d87a3d925e47ef99a80b0d6d25f637c0",
    "guard-witness.mjs": "950b77089b0db52fd6dbf84a1699589892d37cb8554eed8b252d06ba68368c15",
}
EXPECTED_042 = {
    "outside-root-guard.mjs": "48e66c678fd6816cb0114bb9065b3d0618e345bfe82175dcef62a25a5cb001b4",
    "guard-witness.mjs": "16d273f0ce704b2e37a1db5d5443b8684caf184c09d2a014a2f7cd0ca5d951ad",
}
POWERSHELL = shutil.which("powershell")


def m_remote() -> dict[str, Any]:
    return yaml.safe_load((PACK / "values.m-remote.yaml").read_text("utf-8"))


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_m_remote_values_render_the_reviewed_files_byte_for_byte() -> None:
    files = orchestrator.render_all(m_remote())
    for name, digest in REVIEWED.items():
        assert sha(files[name]) == digest, name


def test_guard_and_witness_are_pinned_to_the_0_4_2_rendering() -> None:
    files = orchestrator.render_all(m_remote())
    for name, digest in EXPECTED_042.items():
        assert sha(files[name]) == digest, name
        assert digest != INSTALLED_GUARD[name]  # M-Remote must upgrade its guard at adoption
    guard = files["outside-root-guard.mjs"]
    assert '[".claude\\\\hooks", ".claude\\\\skills", ".codex", ".agents", ".minion"]' in guard
    witness = files["guard-witness.mjs"]
    for row in (
        "O13 write under .claude/skills",
        "O14 write .minion/kit.json",
        "O15 shell copy into .minion",
    ):
        assert row in witness
    rows = files["witness-rows.md"]
    assert "`.claude\\skills\\<probe>`" in rows and "`.minion\\<probe>`" in rows


def test_control_a_changed_value_changes_the_reviewed_bytes() -> None:
    """Negative control for the round trip: the comparison is sensitive to a single value."""
    values = m_remote()
    values["read_exec_roots"] = values["read_exec_roots"][:-1]
    guard = orchestrator.render_all(values)["outside-root-guard.mjs"]
    assert sha(guard) != EXPECTED_042["outside-root-guard.mjs"]
    values = m_remote() | {"exempt_decision": "Owner decision 2026-10-16, item 4"}
    assert sha(orchestrator.render_all(values)["settings.json"]) == REVIEWED["settings.json"]
    assert (
        sha(orchestrator.render_all(values)["outside-root-guard.mjs"])
        != EXPECTED_042["outside-root-guard.mjs"]
    )


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


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("root", "E:\\AI\\it's\\Minion-Remote"),  # an ordinary apostrophe
        ("root", "E:\\AI\\a'; Write-Output INJECTED; #\\Minion-Remote"),  # command-shaped
        ("home", "C:\\Users\\x$env:PATH"),
        ("temp", "C:\\T\\a&b"),
        ("read_exec_roots", ["C:\\Tools\\a|b"]),
        ("read_exec_roots", ["C:\\Tools\\a`b"]),
        ("repos", ["it's"]),  # safe.directory values
        ("repos", ["a;b"]),
        ("repos", ["a>b"]),
        ("exempt_decision", "Owner decision\nWrite-Output x"),
        ("claude_sessions", "Review-CC\x07"),
    ],
)
def test_values_that_could_become_code_are_refused(key: str, value: object) -> None:
    """KIT-042-R001: every value reaches executable syntax (PowerShell, rules, JSON, JavaScript)."""
    values = copy.deepcopy(m_remote())
    values[key] = value
    with pytest.raises(PackError, match="must not contain"):
        orchestrator.render_all(values)


def test_powershell_literals_are_escaped_as_defence_in_depth() -> None:
    assert orchestrator.ps_quote("it's") == "it''s"
    launch = orchestrator.template("codex-launch.ps1.tmpl")
    assert "$W = '{{ROOT_PS}}'" in launch and "'{{ROOT}}'" not in launch
    values = orchestrator.load_values(m_remote())
    mapped = orchestrator.mapping(values)
    assert mapped["ROOT_PS"] == values["root"]
    assert (
        "'E:/AI/Projects/OpenMinds/Minions/Minion-Remote/minion-remote'" in mapped["GIT_SAFE_DIRECTORIES_PS"]
    )


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
    assert "Remove-Item" not in text and "Move-Item" not in text
    assert "/remove" not in text.replace('Write-Output "       icacls `"$parent`" /remove:g $Group', "")
    assert "ProtectParent" not in text  # no outside-root effect (KIT-042-R002)
    assert "Assert-NoLinkChain $Root" in text and "Assert-NoLinkChain $p" in text
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


def run_ps(tmp_path: Path, code: str, *args: object) -> dict[str, Any]:
    """Run a PowerShell witness that dot-sources functions extracted from owner-acl.ps1. It changes no ACL."""
    script = tmp_path / "witness.ps1"
    script.write_text(code, encoding="utf-8")
    argv = [str(POWERSHELL), "-NoProfile", "-NonInteractive", "-File", str(script), *map(str, args)]
    done = subprocess.run(
        argv, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
    )
    assert done.returncode == 0, done.stderr
    result: dict[str, Any] = json.loads(done.stdout.strip().splitlines()[-1])
    return result


EXTRACT = """param($Script)
$tokens = $null; $errors = $null
$tree = [System.Management.Automation.Language.Parser]::ParseFile($Script, [ref]$tokens, [ref]$errors)
foreach ($name in @(NAMES)) {
    $fn = $tree.Find({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $n.Name -eq $name }.GetNewClosure(), $true)
    . ([scriptblock]::Create($fn.Extent.Text))
}
"""


@pytest.mark.skipif(POWERSHELL is None, reason="needs Windows PowerShell")
@pytest.mark.parametrize("linked", [False, True])
def test_owner_acl_refuses_a_junction_anywhere_above_a_target(tmp_path: Path, linked: bool) -> None:
    """KIT-042-R002: an ordinary root below a junction is refused before any target is selected."""
    import _winapi

    real = tmp_path / "real"
    (real / "Project" / ".claude").mkdir(parents=True)
    (real / "Project" / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
    alias = tmp_path / "alias"
    if linked:
        _winapi.CreateJunction(str(real), str(alias))  # type: ignore[attr-defined]
    selected = (alias if linked else real) / "Project"
    code = (
        EXTRACT.replace("NAMES", "'Assert-NoLinkChain', 'Resolve-Target'")
        + """
$Root = $args[0]
try {
    Assert-NoLinkChain $Root
    $p = Resolve-Target '.claude\\settings.json'
    @{ refused = $false; path = $p } | ConvertTo-Json -Compress
} catch { @{ refused = $true; reason = $_.Exception.Message } | ConvertTo-Json -Compress }
"""
    )
    code = code.replace("param($Script)", "param($Script, $SelectedRoot)").replace(
        "$args[0]", "$SelectedRoot"
    )
    result = run_ps(tmp_path, code, PACK / "owner-acl.ps1", selected)
    assert result["refused"] is linked, result


@pytest.mark.skipif(POWERSHELL is None, reason="needs Windows PowerShell")
@pytest.mark.parametrize(
    ("propagation", "inherit", "accepted"),
    [
        ("None", True, True),
        ("InheritOnly", True, False),
        ("NoPropagateInherit", True, False),
        ("None", False, True),
    ],
)
def test_test_deny_counts_only_a_full_scope_deny(
    tmp_path: Path, propagation: str, inherit: bool, accepted: bool
) -> None:
    """KIT-042-R003: an inherit-only (or one-level) deny is reported missing, so -Check and apply see it."""
    code = (
        EXTRACT.replace("NAMES", "'Test-Deny'").replace(
            "param($Script)", "param($Script, $Fixture, $Prop, $Inherit)"
        )
        + """
$sid = New-Object Security.Principal.SecurityIdentifier('S-1-5-32-545')
$rights = 'WriteData,AppendData,Delete,ChangePermissions,TakeOwnership'
$mask = [int][Security.AccessControl.FileSystemRights]$rights
$wantInherit = $Inherit -eq 'True'
$IF = [Security.AccessControl.InheritanceFlags]
$flags = if ($wantInherit) { $IF::ContainerInherit -bor $IF::ObjectInherit } else { $IF::None }
$prop = [Security.AccessControl.PropagationFlags]$Prop
$ace = New-Object Security.AccessControl.FileSystemAccessRule($sid, $mask, $flags, $prop, 'Deny')
function Get-Acl { param($LiteralPath) [pscustomobject]@{ Access = @($ace) } }
@{ accepted = (Test-Deny $Fixture $mask $wantInherit) } | ConvertTo-Json -Compress
"""
    )
    result = run_ps(tmp_path, code, PACK / "owner-acl.ps1", tmp_path, propagation, inherit)
    assert result["accepted"] is accepted, result
