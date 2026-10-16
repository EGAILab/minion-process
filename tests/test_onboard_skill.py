"""The shipped `kit-onboard` skill: package data, frontmatter both tools accept, and the control-file list
it must never write, kept in step with `project-scope.md` PS-2."""

from __future__ import annotations

import re
from importlib import resources
from pathlib import Path

import yaml

KIT = Path(__file__).resolve().parents[1]
CONTROL = (".claude/settings*.json", ".claude/hooks/", ".claude/skills/", ".codex/", ".agents/", ".minion/")


def skill_text() -> str:
    return (resources.files("minion_process.bootstrap") / "skills" / "kit-onboard" / "SKILL.md").read_text(
        "utf-8"
    )


def test_skill_frontmatter() -> None:
    text = skill_text()
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert match
    front = yaml.safe_load(match[1])
    assert set(front) == {"name", "description"} and front["name"] == "kit-onboard"
    assert 50 < len(front["description"]) < 1024


def test_skill_names_every_control_file_and_ps2_agrees() -> None:
    text = skill_text()
    scope = (KIT / "project-scope.md").read_text(encoding="utf-8")
    for path in CONTROL:
        assert f"`{path}`" in text
        assert path.rstrip("/").split("*")[0] in scope


def test_skill_is_package_data_and_the_installer_copies_it() -> None:
    assert '"skills/*/SKILL.md"' in (KIT / "pyproject.toml").read_text(encoding="utf-8")
    installer = (KIT / "bootstrap" / "install.ps1").read_text(encoding="utf-8")
    assert "'.claude\\skills\\kit-onboard', '.agents\\skills\\kit-onboard'" in installer
