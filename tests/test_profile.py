"""`profile validate`: every rule of `profiles/profile.schema.json` as implemented by
`minion_process.profile`, with the shipped profiles as positives and one mutation per rule as negatives.

PROC-KIT-P1-R001: non-string values in enum positions (list, mapping, null, bool, int) are diagnostics,
never a raise, through the function and the CLI. PROC-KIT-P1-R002: the JSON schema (checked with
`jsonschema`) and the Python validator accept and reject the same profiles over the whole mutation
neighbourhood, except for the named SUPPLEMENTAL_RULES, which only the Python side can express."""

from __future__ import annotations

import copy
import json
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml
from jsonschema import Draft202012Validator

from minion_process.cli import main
from minion_process.profile import (
    SUPPLEMENTAL_RULES,
    TOP_OPTIONAL,
    TOP_REQUIRED,
    load_profile,
    validate_profile,
)
from minion_process.validate import errors

KIT = Path(__file__).resolve().parents[1]
PROFILES = KIT / "profiles"
SCHEMA = json.loads((PROFILES / "profile.schema.json").read_text(encoding="utf-8"))
SCHEMA_VALIDATOR = Draft202012Validator(SCHEMA)


def good() -> dict[str, Any]:
    data = yaml.safe_load((PROFILES / "example.profile.yaml").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def problems(data: Any) -> list[str]:
    return [str(p) for p in validate_profile(data)]


def schema_rejects(data: Any) -> bool:
    return not SCHEMA_VALIDATOR.is_valid(data)


def both(data: Any) -> tuple[bool, bool]:
    """(python rejects, schema rejects) -- the differential observation."""
    return bool(errors(validate_profile(data))), schema_rejects(data)


@pytest.mark.parametrize("name", ["example.profile.yaml", "minion-agent.profile.yaml"])
def test_shipped_profiles_are_valid_for_both_validators(name: str) -> None:
    data, found = load_profile(PROFILES / name)
    assert data is not None and found == []
    assert not schema_rejects(data)


def test_schema_and_implementation_agree_on_the_top_level_and_name_the_supplemental_rules() -> None:
    Draft202012Validator.check_schema(SCHEMA)
    assert tuple(SCHEMA["required"]) == TOP_REQUIRED
    assert set(SCHEMA["properties"]) == set(TOP_REQUIRED) | set(TOP_OPTIONAL)
    assert SCHEMA["additionalProperties"] is False
    for rule in SUPPLEMENTAL_RULES:
        assert rule in SCHEMA["description"], rule


def test_kit_version_matches_pyproject_and_changelog() -> None:
    version = tomllib.loads((KIT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    for name in ("example.profile.yaml", "minion-agent.profile.yaml"):
        data = yaml.safe_load((PROFILES / name).read_text(encoding="utf-8"))
        assert data["kit"]["version"] == version
    assert f"## {version}" in (KIT / "CHANGELOG.md").read_text(encoding="utf-8")


def test_not_a_mapping_and_unknown_or_missing_keys() -> None:
    assert problems([]) == ["ERROR: profile: must be a mapping, got list"]
    assert problems({1: 2}) == ["ERROR: profile: keys must be strings"]
    assert both([]) == (True, True)
    data = good()
    data["surprise"] = 1
    del data["delegation"]
    found = problems(data)
    assert "ERROR: delegation: required" in found
    assert "ERROR: profile: unknown keys ['surprise']" in found
    assert both(data) == (True, True)


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


MUTATIONS: list[tuple[list[str | int], Any, str]] = [
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
    (["authority", 0, "name"], "   ", "authority[0].name: must be a non-empty string"),
    (["repos"], [], "repos: must be a mapping"),
    (["repos"], {}, "repos: needs at least one repository"),
    (["repos", "code"], None, "repos.code: must be a mapping"),
    (["repos", "code", "github"], "x", "repos.code.github: must be owner/repo"),
    (["repos", "code", "default_branch"], 3, "repos.code.default_branch: must be a non-empty string"),
    (["coordination"], 1, "coordination: must be a mapping"),
    (["coordination", "backend"], "chat", "coordination.backend: must be one of"),
    (["coordination", "repo"], "", "coordination.repo: must be a non-empty string"),
    (["coordination"], {"backend": "state-file", "path": "state/", "repo": False}, "coordination.repo: must"),
    (["coordination"], {"backend": "github-issue", "repo": "a/b", "path": " "}, "coordination.path: must"),
    (["conformance"], [], "conformance: must be a mapping"),
    (["conformance"], {"support": ["schema"]}, "conformance.families: required"),
    (["conformance", "families"], [], "conformance.families: needs at least 1 item(s)"),
    (["conformance", "support"], [""], "conformance.support[0]: must be a non-empty string"),
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
    (["taxonomy_aliases"], {"PI_X": "SOMETHING"}, "taxonomy_aliases.PI_X: must be one of"),
    (["hazard_families"], [1], "hazard_families[0]: must be a non-empty string"),
    (["gates"], 1, "gates: must be a mapping"),
    (["gates", "python"], 1, "gates.python: must be a mapping"),
    (["gates", "python", "launcher"], "", "gates.python.launcher: must be a non-empty string"),
    (["gates", "python", "tiers"], ["g9"], "gates.python.tiers[0]: must be one of"),
    (["gates", "python", "tiers"], [], "gates.python.tiers: needs at least 1 item(s)"),
    (["gates", "rust", "queue"], 1, "gates.rust.queue: must be a mapping"),
    (["gates", "rust", "queue", "argv"], "cargo", "gates.rust.queue.argv: must be a list"),
    (["gates", "rust", "queue", "argv"], [], "gates.rust.queue.argv: needs at least 1 item(s)"),
    (["gates", "rust", "queue", "argv"], [""], "gates.rust.queue.argv[0]: must be a non-empty string"),
    (["gates", "rust", "queue", "env"], [], "gates.rust.queue.env: must be a mapping"),
    (["gates", "rust", "queue", "env"], {"A": ""}, "gates.rust.queue.env.A: must be a non-empty string"),
    (["gates", "rust", "queue", "target_env"], "X", "gates.rust.queue.target_env: must be a list"),
    (["gates", "rust", "queue", "container"], "no", "gates.rust.queue.container: must be true or false"),
    (["gates", "rust", "queue", "extra"], 1, "gates.rust.queue: unknown keys ['extra']"),
    (["build_queue"], [], "build_queue: must be a mapping"),
    (["build_queue", "state"], "", "build_queue.state: must be a non-empty string"),
    (["build_queue", "extra"], 1, "build_queue: unknown keys ['extra']"),
    (["build_queue", "targets"], {}, "build_queue.targets: needs at least one target"),
    (["build_queue", "targets"], [], "build_queue.targets: must be a mapping"),
    (["build_queue", "targets", "rust-gate"], 1, "build_queue.targets.rust-gate: must be a mapping"),
    (
        ["build_queue", "targets", "rust-gate", "kind"],
        "cache",
        "build_queue.targets.rust-gate.kind: must be one of",
    ),
    (
        ["build_queue", "targets", "rust-gate", "path"],
        "",
        "build_queue.targets.rust-gate.path: must be a non-empty string",
    ),
    (
        ["build_queue", "targets", "claude-rust", "owner_agent"],
        "",
        "build_queue.targets.claude-rust.owner_agent: must be",
    ),
    (["build_queue", "caches"], [], "build_queue.caches: must be a mapping"),
    (
        ["build_queue", "caches", "cargo-home"],
        "",
        "build_queue.caches.cargo-home: must be a non-empty string",
    ),
    (["build_queue", "inherit_env"], "PATH", "build_queue.inherit_env: must be a list"),
    (["build_queue", "cleanup_references"], [], "build_queue.cleanup_references: must be a mapping"),
    (
        ["build_queue", "cleanup_references", "incidents"],
        [],
        "build_queue.cleanup_references.incidents: needs at least 1",
    ),
    (
        ["build_queue", "cleanup_references", "extra"],
        1,
        "build_queue.cleanup_references: unknown keys ['extra']",
    ),
    (["gates", "rust", "queue", "cache_env"], [], "gates.rust.queue.cache_env: must be a mapping"),
    (
        ["gates", "rust", "queue", "cache_env", "CARGO_HOME"],
        "",
        "gates.rust.queue.cache_env.CARGO_HOME: must be",
    ),
    (["delegation"], "x", "delegation: must be a mapping"),
    (["delegation", "routing"], "yes", "delegation.routing: must be true or false"),
    (["wp_kinds_enabled"], ["magic"], "wp_kinds_enabled[0]: must be one of"),
    (["implementation_order"], ["Python"], "implementation_order[0]: not a language name"),
    (["environment"], "", "environment: must be a non-empty string"),
]

ENUM_POSITIONS: list[list[str | int]] = [
    ["authority", 0, "kind"],
    ["coordination", "backend"],
    ["taxonomy_aliases", "PI_X"],
    ["gates", "python", "tiers", 0],
    ["build_queue", "targets", "rust-gate", "kind"],
    ["wp_kinds_enabled", 0],
    ["agents", "codex", "roles", 0],
]
MALFORMED_SHAPES: list[Any] = [[], ["reviewer"], {}, {"a": 1}, None, True, 0, 1.5]


@pytest.mark.parametrize(("path", "value", "expected"), MUTATIONS)
def test_one_mutation_per_rule_and_both_validators_reject_it(
    path: list[str | int], value: Any, expected: str
) -> None:
    data = mutate(path, value)
    found = problems(data)
    assert any(expected in p for p in found), found
    assert both(data) == (True, True)


def _shape_id(shape: Any) -> str:
    return type(shape).__name__ + (str(len(shape)) if hasattr(shape, "__len__") else str(shape))


@pytest.mark.parametrize("shape", MALFORMED_SHAPES, ids=_shape_id)
@pytest.mark.parametrize("path", ENUM_POSITIONS, ids=lambda p: ".".join(map(str, p)))
def test_r001_non_string_enum_values_are_diagnostics(path: list[str | int], shape: Any) -> None:
    data = good()
    data.setdefault("taxonomy_aliases", {})["PI_X"] = "AUTHORITY_PARITY_DEFECT"
    node: Any = data
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = shape
    found = problems(data)  # must not raise
    joined = ".".join(str(k) for k in path).replace(".0", "[0]")
    assert any(p.startswith("ERROR: ") and joined.split("[")[0] in p for p in found), found
    assert both(data) == (True, True)


def test_r001_through_the_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    data = good()
    data["coordination"]["backend"] = ["github-issue"]
    path = tmp_path / "enum-list.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    assert main(["profile", "validate", str(path)]) == 1
    out = capsys.readouterr().out
    assert "ERROR: coordination.backend: must be a string, got list" in out
    assert out.strip().endswith("INVALID")


def test_authority_entry_needs_path_or_pin_and_rejects_unknown_keys() -> None:
    data = good()
    data["authority"][0] = {"kind": "source"}
    assert "ERROR: authority[0]: needs `path` or `pin`" in problems(data)
    assert both(data) == (True, True)
    data["authority"][0] = {"kind": "source", "pin": "x", "url": "y"}
    assert "ERROR: authority[0]: unknown keys ['url']" in problems(data)
    assert both(data) == (True, True)


def test_coordination_backends_need_their_locator_and_validate_inactive_ones() -> None:
    assert "ERROR: coordination.repo: required for the github-issue backend" in problems(
        mutate(["coordination"], {"backend": "github-issue"})
    )
    assert "ERROR: coordination.path: required for the state-file backend" in problems(
        mutate(["coordination"], {"backend": "state-file"})
    )
    assert problems(mutate(["coordination"], {"backend": "state-file", "path": "process/state/"})) == []
    state_file = mutate(["coordination"], {"backend": "state-file", "path": "process/state/"})
    assert both(state_file) == (False, False)
    assert "ERROR: coordination.path: must be a non-empty string" in problems(
        mutate(["coordination"], {"backend": "state-file", "path": ""})
    )
    # R002: a locator the selected backend does not use is still validated
    inactive = mutate(["coordination"], {"backend": "state-file", "path": "state/", "repo": "not-a-repo"})
    assert "ERROR: coordination.repo: must be owner/repo, got 'not-a-repo'" in problems(inactive)
    assert both(inactive) == (True, True)


def test_conformance_support_is_not_a_family() -> None:
    data = mutate(["conformance"], {"families": ["runtime", "schema"], "support": ["schema"]})
    assert "ERROR: conformance.support[0]: 'schema' is also a behavior family; it cannot be both" in problems(
        data
    )
    assert both(data) == (True, False)  # supplemental rule: Python only


def test_agent_role_coverage_and_independence_in_both_validators() -> None:
    data = good()
    del data["agents"]["codex"]
    found = problems(data)
    assert "ERROR: agents: needs at least two agents: review is independent of authorship" in found
    assert "ERROR: agents: no agent holds `reviewer`" in found
    assert "ERROR: implementation_order[1]: no agent holds `implementer:rust`" in found
    assert both(data) == (True, True)
    data = good()
    data["agents"]["claude"]["roles"] = ["shared-contract-owner", "reviewer"]
    data["agents"]["codex"]["roles"] = ["reviewer", "shared-contract-owner"]
    del data["implementation_order"]
    found = problems(data)
    assert "ERROR: agents: no agent holds `coordinator`" in found
    assert "ERROR: agents: no agent holds an `implementer:<language>` role" in found
    assert "ERROR: agents: every reviewer also holds `shared-contract-owner`" in " ".join(found)
    assert both(data) == (True, True)
    data = good()  # R002's own observation: a second agent with no reviewer role
    data["agents"]["codex"]["roles"] = ["implementer:rust"]
    assert "ERROR: agents: no agent holds `reviewer`" in problems(data)
    assert both(data) == (True, True)
    data = good()  # independence alone: the only reviewer also owns the shared contract
    data["agents"]["codex"]["roles"] = ["reviewer", "shared-contract-owner", "implementer:rust"]
    assert both(data) == (True, True)


def test_supplemental_rule_implementation_order_is_python_only() -> None:
    data = mutate(["implementation_order"], ["go"])
    assert "ERROR: implementation_order[0]: no agent holds `implementer:go`" in problems(data)
    assert both(data) == (True, False)


def test_a_broken_agent_entry_does_not_hide_the_coverage_checks() -> None:
    data = good()
    data["agents"]["codex"]["roles"] = {"reviewer": True}
    found = problems(data)
    assert "ERROR: agents.codex.roles: must be a list, got dict" in found
    assert "ERROR: agents: no agent holds `reviewer`" in found
    assert both(data) == (True, True)


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
