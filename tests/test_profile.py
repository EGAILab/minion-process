"""`profile validate`: every rule of `profiles/profile.schema.json`, as implemented by
`minion_process.profile`, with the example profiles as positives and one mutation per rule as negatives."""

from __future__ import annotations

import copy
import json
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

from minion_process.cli import main
from minion_process.profile import TOP_OPTIONAL, TOP_REQUIRED, load_profile, validate_profile
from minion_process.validate import errors

KIT = Path(__file__).resolve().parents[1]
PROFILES = KIT / "profiles"
SCHEMA = json.loads((PROFILES / "profile.schema.json").read_text(encoding="utf-8"))


def good() -> dict[str, Any]:
    data = yaml.safe_load((PROFILES / "example.profile.yaml").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def problems(data: Any) -> list[str]:
    return [str(p) for p in validate_profile(data)]


@pytest.mark.parametrize("name", ["example.profile.yaml", "minion-agent.profile.yaml"])
def test_shipped_profiles_are_valid(name: str) -> None:
    data, found = load_profile(PROFILES / name)
    assert data is not None and found == []


def test_schema_and_implementation_agree_on_the_top_level() -> None:
    assert tuple(SCHEMA["required"]) == TOP_REQUIRED
    assert set(SCHEMA["properties"]) == set(TOP_REQUIRED) | set(TOP_OPTIONAL)
    assert SCHEMA["additionalProperties"] is False


def test_kit_version_matches_pyproject_and_changelog() -> None:
    version = tomllib.loads((KIT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    for name in ("example.profile.yaml", "minion-agent.profile.yaml"):
        data = yaml.safe_load((PROFILES / name).read_text(encoding="utf-8"))
        assert data["kit"]["version"] == version
    assert f"## {version}" in (KIT / "CHANGELOG.md").read_text(encoding="utf-8")


def test_not_a_mapping_and_unknown_or_missing_keys() -> None:
    assert problems([]) == ["ERROR: profile: must be a mapping, got list"]
    assert problems({1: 2}) == ["ERROR: profile: keys must be strings"]
    data = good()
    data["surprise"] = 1
    del data["delegation"]
    found = problems(data)
    assert "ERROR: delegation: required" in found
    assert "ERROR: profile: unknown keys ['surprise']" in found


def mutate(path: list[str | int], value: Any, *, delete: bool = False) -> dict[str, Any]:
    data = good()
    node: Any = data
    for key in path[:-1]:
        node = node[key]
    if delete:
        del node[path[-1]]
    else:
        node[path[-1]] = value
    return data


@pytest.mark.parametrize(
    ("path", "value", "expected"),
    [
        (["kit"], "0.1.0", "kit: must be a mapping"),
        (["kit", "extra"], 1, "kit: unknown keys ['extra']"),
        (["kit", "version"], "1.0", "kit.version: must be MAJOR.MINOR.PATCH"),
        (["kit", "source"], "no-slash", "kit.source: must be owner/repo"),
        (["project"], "Bad Name", "project: must be a lower-case kebab-case name"),
        (["project"], "", "project: must be a non-empty string"),
        (["authority"], {}, "authority: must be a list"),
        (["authority"], [], "authority: needs at least one entry"),
        (["authority", 0], "pi", "authority[0]: must be a mapping"),
        (["authority", 0, "kind"], "oracle", "authority[0].kind: must be one of"),
        (["authority", 0, "name"], "", "authority[0].name: must be a non-empty string"),
        (["repos"], [], "repos: must be a mapping"),
        (["repos"], {}, "repos: needs at least one repository"),
        (["repos", "code"], None, "repos.code: must be a mapping"),
        (["repos", "code", "github"], "x", "repos.code.github: must be owner/repo"),
        (["repos", "code", "default_branch"], 3, "repos.code.default_branch: must be a non-empty string"),
        (["coordination"], 1, "coordination: must be a mapping"),
        (["coordination", "backend"], "chat", "coordination.backend: must be one of"),
        (["coordination", "repo"], "", "coordination.repo: must be a non-empty string"),
        (["agents"], [], "agents: must be a mapping"),
        (["agents", "codex"], 1, "agents.codex: must be a mapping"),
        (["agents", "codex", "harness"], "", "agents.codex.harness: must be a non-empty string"),
        (["agents", "codex", "default_pane"], "", "agents.codex.default_pane: must be a non-empty string"),
        (["agents", "codex", "roles"], "reviewer", "agents.codex.roles: must be a list"),
        (["agents", "codex", "roles"], [], "agents.codex.roles: needs at least 1 item(s)"),
        (["agents", "codex", "roles"], ["reviewer", "reviewer"], "agents.codex.roles: items must be unique"),
        (["agents", "codex", "roles"], ["reviewer", "janitor"], "agents.codex.roles[1]: unknown role"),
        (["taxonomy_aliases"], [], "taxonomy_aliases: must be a mapping"),
        (["taxonomy_aliases"], {"bad": "AUTHORITY_PARITY_DEFECT"}, "taxonomy_aliases.bad: alias must be"),
        (["taxonomy_aliases"], {"PI_X": "SOMETHING"}, "taxonomy_aliases.PI_X: must map to one of"),
        (["hazard_families"], [1], "hazard_families[0]: must be a non-empty string"),
        (["gates"], 1, "gates: must be a mapping"),
        (["gates", "python"], 1, "gates.python: must be a mapping"),
        (["gates", "python", "launcher"], "", "gates.python.launcher: must be a non-empty string"),
        (["gates", "python", "tiers"], ["g9"], "gates.python.tiers[0]: must be one of"),
        (["delegation"], "x", "delegation: must be a mapping"),
        (["delegation", "routing"], "yes", "delegation.routing: must be true or false"),
        (["wp_kinds_enabled"], ["magic"], "wp_kinds_enabled[0]: must be one of"),
        (["implementation_order"], ["Python"], "implementation_order[0]: not a language name"),
        (["implementation_order"], ["go"], "implementation_order[0]: no agent holds `implementer:go`"),
        (["environment"], "", "environment: must be a non-empty string"),
    ],
)
def test_one_mutation_per_rule(path: list[str | int], value: Any, expected: str) -> None:
    found = problems(mutate(path, value))
    assert any(expected in p for p in found), found


def test_authority_entry_needs_path_or_pin_and_rejects_unknown_keys() -> None:
    data = good()
    data["authority"][0] = {"kind": "source"}
    assert "ERROR: authority[0]: needs `path` or `pin`" in problems(data)
    data["authority"][0] = {"kind": "source", "pin": "x", "url": "y"}
    assert "ERROR: authority[0]: unknown keys ['url']" in problems(data)


def test_coordination_backends_need_their_locator() -> None:
    assert "ERROR: coordination.repo: required for the github-issue backend" in problems(
        mutate(["coordination"], {"backend": "github-issue"})
    )
    assert "ERROR: coordination.path: required for the state-file backend" in problems(
        mutate(["coordination"], {"backend": "state-file"})
    )
    assert problems(mutate(["coordination"], {"backend": "state-file", "path": "process/state/"})) == []
    assert "ERROR: coordination.path: must be a non-empty string" in problems(
        mutate(["coordination"], {"backend": "state-file", "path": ""})
    )


def test_agent_role_coverage_and_independence() -> None:
    data = good()
    del data["agents"]["codex"]
    found = problems(data)
    assert "ERROR: agents: needs at least two agents: review is independent of authorship" in found
    assert "ERROR: agents: no agent holds `reviewer`" in found
    assert "ERROR: implementation_order[1]: no agent holds `implementer:rust`" in found
    data = good()
    data["agents"]["claude"]["roles"] = ["shared-contract-owner", "reviewer"]
    data["agents"]["codex"]["roles"] = ["reviewer", "shared-contract-owner"]
    del data["implementation_order"]
    found = problems(data)
    assert "ERROR: agents: no agent holds `coordinator`" in found
    assert "ERROR: agents: no agent holds an `implementer:<language>` role" in found
    assert "ERROR: agents: every reviewer also holds `shared-contract-owner`" in " ".join(found)
    data = good()
    data["agents"]["codex"]["roles"] = ["implementer:rust"]
    assert "ERROR: agents: no agent holds `reviewer`" in problems(data)


def test_a_broken_agent_entry_does_not_hide_the_coverage_checks() -> None:
    data = good()
    data["agents"]["codex"]["roles"] = {"reviewer": True}
    found = problems(data)
    assert "ERROR: agents.codex.roles: must be a list, got dict" in found
    assert "ERROR: agents: no agent holds `reviewer`" in found


def test_load_profile_reports_unreadable_and_unparsable_files(tmp_path: Path) -> None:
    data, found = load_profile(tmp_path / "missing.yaml")
    assert data is None and len(found) == 1 and "cannot load: FileNotFoundError" in str(found[0])
    bad = tmp_path / "bad.yaml"
    bad.write_text("kit: [unclosed", encoding="utf-8")
    data, found = load_profile(bad)
    assert data is None and "cannot load:" in str(found[0])


def test_cli_profile_validate(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["profile", "validate", str(PROFILES / "example.profile.yaml")]) == 0
    assert capsys.readouterr().out.strip() == "VALID"
    broken = tmp_path / "p.yaml"
    data = copy.deepcopy(good())
    data["delegation"]["routing"] = "maybe"
    broken.write_text(yaml.safe_dump(data), encoding="utf-8")
    assert main(["profile", "validate", str(broken)]) == 1
    out = capsys.readouterr().out
    assert "ERROR: delegation.routing: must be true or false" in out and out.strip().endswith("INVALID")
    assert errors(validate_profile(data))
