"""CE-PROC-L13-01 revision 5 (AGREED, Codex #204 comment 5925476157): the YAML load boundary as a
constructor pipeline producing a graph -- L1' totality over load and post-load check, L2' acyclic
depth-bounded JSON-domain graph, L3 YAML 1.2 core resolver, L4 write/read symmetry. Each row of the
split intended-outcome table is checked at every entry point. FakeGitHub only."""

from __future__ import annotations

import contextlib
import string

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from minion_process.cli import main
from minion_process.github import GitHub
from minion_process.model import MAX_DEPTH, BodyFormatError, load_state, render_body, split_body
from minion_process.ops import CheckFailed, commit_state, restore_revision
from minion_process.validate import errors, validate_workflow

from .test_minion_process import CODE, FakeGitHub, workflow

NL = chr(10)
FENCE, CLOSE = "```yaml" + NL, NL + "```" + NL


def _body(extra_in_workflow: str = "", extra_top: str = "") -> str:
    """A valid rendered state with one extra line inside `workflow` and/or one extra top-level line."""
    rendered = render_body({"workflow": workflow()}, "")
    head, rest = rendered.split("workflow:" + NL, 1)
    inner = ("  " + extra_in_workflow + NL) if extra_in_workflow else ""
    top = (extra_top + NL) if extra_top else ""
    return head + top + "workflow:" + NL + inner + rest


GOOD = _body()

# (id, body, intended load: "ok" | "error", workflow valid when loaded)
ROWS: list[tuple[str, str, str, bool]] = [
    ("implicit-date-in-updated_reason", _body("updated_reason: 2026-02-30"), "ok", True),
    (
        "implicit-date-as-work_package-string",
        _body().replace("work_package: WP-X", "work_package: 2026-02-30"),
        "ok",
        True,
    ),
    ("no-as-next_owner-string", _body().replace("next_owner: Codex", "next_owner: no"), "ok", False),
    ("yes-top-level-string-key", _body(extra_top="yes: 1"), "ok", True),
    ("sexagesimal-string", _body("note: 1:30"), "ok", True),
    ("merge-literal-key", _body('"<<": 1'), "ok", True),
    ("leading-zero-string", _body("note: 010"), "ok", True),
    ("tagged-invalid-timestamp", _body("note: !!timestamp 2026-02-30"), "error", False),
    ("tagged-valid-timestamp", _body("note: !!timestamp 2026-02-28"), "error", False),
    ("tagged-bad-int", _body("note: !!int not-an-int"), "error", False),
    ("tagged-bad-float", _body("note: !!float abc"), "error", False),
    ("tagged-bad-bool", _body("note: !!bool maybe"), "error", False),
    ("binary", _body("note: !!binary aGk="), "error", False),
    ("binary-garbage", _body("note: !!binary '@@@'"), "error", False),
    ("set", _body("note: !!set {a: null}"), "error", False),
    ("omap", _body("note: !!omap [a: 1]"), "error", False),
    ("pairs", _body("note: !!pairs [a: 1]"), "error", False),
    ("tagged-int-key", _body(extra_top="!!int 1: a"), "error", False),
    ("tagged-bool-key", _body(extra_top="!!bool true: a"), "error", False),
    ("tagged-null-key", _body(extra_top="!!null '': a"), "error", False),
    ("self-map-cycle", _body("note: &W {history: *W}"), "error", False),
    ("self-list-cycle", _body("note: {history: &H [*H]}"), "error", False),
    ("indirect-cycle", _body("note: &A {b: {c: *A}}"), "error", False),
    ("shared-acyclic-alias", _body("note: {a: &A {x: 1}, b: *A}"), "ok", True),
    ("depth-64", _body("note: " + "[" * (MAX_DEPTH - 2) + "]" * (MAX_DEPTH - 2)), "ok", True),
    ("depth-65", _body("note: " + "[" * (MAX_DEPTH - 1) + "]" * (MAX_DEPTH - 1)), "error", False),
    ("deep-5000", _body("note: " + "[" * 5000 + "]" * 5000), "error", False),
    ("unclosed-flow", FENCE + "workflow:" + NL + "  status: [" + CLOSE, "error", False),
]


def _fake(body: str, revisions: list[tuple[str, str]] | None = None) -> FakeGitHub:
    fake = FakeGitHub()
    fake.issues[(CODE, 10)] = {"body": body, "state": "OPEN", "title": "x"}
    fake.revisions[(CODE, 10)] = revisions if revisions is not None else [("GOOD", GOOD)]
    return fake


@pytest.mark.parametrize(("name", "body", "load", "valid"), ROWS, ids=[r[0] for r in ROWS])
def test_intended_outcome_at_every_entry_point(name: str, body: str, load: str, valid: bool) -> None:
    del name
    # the body boundary
    if load == "error":
        with pytest.raises(BodyFormatError):
            split_body(body)
    else:
        state = split_body(body).state
        assert (not errors(validate_workflow(state["workflow"]))) is valid

    # read commands: diagnostics, never a traceback
    for command in ("status", "validate", "candidate-check", "handoff-check"):
        fake = _fake(body)
        code = main([command, "10"], gh=GitHub(fake.run))
        if load == "error" or not valid:
            assert code == 1, command
        elif command in ("status", "validate"):
            assert code == 0, command

    # apply with this as the CURRENT state
    fake = _fake(body)
    if load == "error" or not valid:
        with pytest.raises((CheckFailed, BodyFormatError)):
            commit_state(GitHub(fake.run), CODE, 10, lambda w: None, set())
        assert fake.edits == 0
    else:
        commit_state(GitHub(fake.run), CODE, 10, lambda w: None, set(), dry_run=True)

    # repair with this as the CURRENT state
    fake = _fake(body)
    if load == "error" or not valid:
        assert restore_revision(GitHub(fake.run), CODE, 10, "GOOD") == GOOD
        assert fake.edits == 1
    else:
        with pytest.raises(CheckFailed, match="current state is valid"):
            restore_revision(GitHub(fake.run), CODE, 10, "GOOD")
        assert fake.edits == 0

    # repair TO this as the baseline (from a corrupted current state)
    fake = _fake("flattened garbage", [("ROW", body)])
    if load == "error":
        with pytest.raises(CheckFailed, match="does not parse"):
            restore_revision(GitHub(fake.run), CODE, 10, "ROW")
        assert fake.edits == 0
    elif not valid:
        with pytest.raises(CheckFailed, match="not a valid state"):
            restore_revision(GitHub(fake.run), CODE, 10, "ROW")
        assert fake.edits == 0
    else:
        assert restore_revision(GitHub(fake.run), CODE, 10, "ROW") == body


def test_the_depth_convention_is_root_mapping_one() -> None:
    """The state root is depth 1, `workflow` 2, each nested container +1: MAX_DEPTH containers deep loads,
    one more does not."""
    nested = "[" * (MAX_DEPTH - 1) + "]" * (MAX_DEPTH - 1)
    load_state("a: " + "[" * (MAX_DEPTH - 2) + "]" * (MAX_DEPTH - 2))  # depth MAX_DEPTH - 1 + 1
    load_state("a: " + nested)  # root 1 + (MAX_DEPTH - 1) lists = MAX_DEPTH
    with pytest.raises(BodyFormatError, match="nesting deeper"):
        load_state("a: [" + nested + "]")


def _alias_bomb(levels: int) -> str:
    names = string.ascii_lowercase
    lines = ['a: &a ["x","x","x","x","x","x","x","x","x"]']
    lines += [
        f"{names[i]}: &{names[i]} [" + ",".join(["*" + names[i - 1]] * 9) + "]" for i in range(1, levels)
    ]
    return NL.join(lines) + NL


def test_an_alias_bomb_is_refused_and_modest_sharing_is_not() -> None:
    """Same-root neighborhood addition (flagged in the record): acyclic sharing that expands
    exponentially makes graph equality -- the remote round-trip check -- run for hours."""
    with pytest.raises(BodyFormatError, match="expands to more than"):
        load_state(_alias_bomb(10))
    assert load_state(_alias_bomb(3))["c"][0][0] == ["x"] * 9  # 3 levels: 729 leaves, accepted
    fake = _fake(FENCE + "workflow:" + NL + "  status: SCOPING" + NL + _alias_bomb(10) + CLOSE)
    assert main(["validate", "10"], gh=GitHub(fake.run)) == 1


def test_live_body_compatibility_is_identical_under_both_loaders() -> None:
    """L3 changes nothing for any body the tool writes: render -> new loader == the state."""
    import yaml  # type: ignore[import-untyped]

    for state in (
        {"workflow": workflow()},
        {"workflow": workflow(updated_reason="2026-02-28", next_action="yes", title="1:30 on off 010")},
        {"workflow": workflow(note={"shared": [1.5, 1.0e308, float("inf"), None, True, -0.0, "~", "null"]})},
    ):
        body = render_body(state, "")
        block = body[len(FENCE) : body.rfind(CLOSE)]
        assert load_state(block) == yaml.safe_load(block) == state


# --- the grammar-based property: implicit scalars, tags, anchors/aliases (cycles), depth ---------

IMPLICIT = st.sampled_from(
    [
        "2026-02-30",
        "2026-02-28",
        "2026-02-28 10:00:00",
        "1:30",
        "yes",
        "no",
        "on",
        "off",
        "y",
        "n",
        "010",
        "0x1f",
        "0o17",
        "1_000",
        "1e3",
        "1.5",
        ".5",
        ".inf",
        "-.inf",
        ".nan",
        "~",
        "null",
        "true",
        "False",
        "abc",
        "''",
        '""',
    ]
)
TAGGED = st.sampled_from(
    ["!!int", "!!float", "!!bool", "!!null", "!!timestamp", "!!binary", "!!str"]
).flatmap(
    lambda tag: st.sampled_from(["1", "abc", "2026-02-30", "aGk=", "@@", "yes", ""]).map(
        lambda v: f"{tag} {v}".strip()
    )
)
COLLECTION_TAGS = st.sampled_from(["!!set {a: null}", "!!omap [a: 1]", "!!pairs [a: 1]"])
SCALAR = st.one_of(IMPLICIT, TAGGED, COLLECTION_TAGS)
KEY = st.one_of(st.sampled_from(["a", "b", "yes", "1", "~", "<<", "2026-02-28"]), TAGGED)


def _node(depth: int) -> st.SearchStrategy[str]:
    if depth <= 0:
        return SCALAR
    child = _node(depth - 1)
    return st.one_of(
        SCALAR,
        st.lists(child, max_size=3).map(lambda xs: "[" + ", ".join(xs) + "]"),
        st.lists(st.tuples(KEY, child), max_size=3).map(
            lambda kv: "{" + ", ".join(f"{k}: {v}" for k, v in kv) + "}"
        ),
        st.tuples(st.sampled_from("ABC"), child).map(lambda t: f"&{t[0]} {t[1]}"),
        st.sampled_from(["*A", "*B", "*C"]),
        st.integers(min_value=MAX_DEPTH - 3, max_value=MAX_DEPTH + 3).map(lambda n: "[" * n + "]" * n),
    )


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(value=_node(3))
def test_generated_yaml_is_total_and_json_domain_at_every_entry_point(value: str) -> None:
    for block in (f"x: {value}", f"workflow:{NL}  note: {value}"):
        try:
            state = load_state(block)
        except BodyFormatError:
            continue
        assert isinstance(state, dict)  # L2' held: a JSON-domain, acyclic, bounded graph
    body = _body(f"note: {value}")
    for command in ("status", "validate", "candidate-check", "handoff-check"):
        assert main([command, "10"], gh=GitHub(_fake(body).run)) in (0, 1)
    fake = _fake(body)
    with contextlib.suppress(CheckFailed, BodyFormatError):
        commit_state(GitHub(fake.run), CODE, 10, lambda w: None, set(), dry_run=True)
    with contextlib.suppress(CheckFailed):
        restore_revision(GitHub(_fake(body).run), CODE, 10, "GOOD")


def test_a_shared_alias_counts_at_its_deepest_reference() -> None:
    """A deep node anchored shallowly and referenced deeper exceeds the bound only through the memoized
    height (the walk never re-descends a shared node): it must still be refused."""
    deep = "[" * 60 + "]" * 60
    load_state("a: &D " + deep)  # depth 61: fine where it is anchored
    with pytest.raises(BodyFormatError, match="nesting deeper"):
        load_state("a: &D " + deep + chr(10) + "b: [[[[[*D]]]]]")  # referenced 5 deeper: 66


# ---- PROC-L13-R003 targeted-closure refinement (Codex CLOSURE4, #204 comment 5925696530): L3's
# resolved VALUES and TYPES are asserted directly at the load boundary, not only through workflow
# validity, and every old SafeLoader resolver restored in memory must be caught by them.

L3_VALUES: list[tuple[str, object]] = [
    ("2026-02-30", "2026-02-30"),  # implicit timestamp: invalid date -> string
    ("2026-02-28", "2026-02-28"),  # implicit timestamp: valid date -> string, not a date
    ("2026-02-28 10:00:00", "2026-02-28 10:00:00"),
    ("yes", "yes"),
    ("no", "no"),
    ("on", "on"),
    ("off", "off"),
    ("y", "y"),
    ("1:30", "1:30"),  # sexagesimal -> string, not 90
    ("010", "010"),  # leading zero -> string, not 8
    ("0x1f", "0x1f"),
    ("0o17", "0o17"),
    ("1_000", "1_000"),
    ("1e3", "1e3"),  # no dot: a string (section 13.6 L3)
    ("1_0.5", "1_0.5"),  # YAML 1.1 underscore float -> string
    ("1:30.0", "1:30.0"),  # YAML 1.1 sexagesimal float -> string
    ("true", True),
    ("False", False),
    ("TRUE", True),
    ("0", 0),
    ("-12", -12),
    ("+7", 7),
    ("1.5", 1.5),
    (".5", 0.5),
    ("1.0e+3", 1000.0),
    ("~", None),
    ("null", None),
    ("", None),
    ("abc", "abc"),
]


def _resolved(scalar: str) -> object:
    return load_state(f"x: {scalar}".rstrip())["x"]


@pytest.mark.parametrize(("scalar", "expected"), L3_VALUES, ids=[repr(s) for s, _ in L3_VALUES])
def test_l3_resolves_each_implicit_scalar_to_its_exact_value_and_type(scalar: str, expected: object) -> None:
    for got in (
        _resolved(scalar),
        split_body(_body(f"note: {scalar}".rstrip())).state["workflow"]["note"],
    ):
        assert got == expected and type(got) is type(expected), (scalar, got)


def test_l3_infinities_and_nan_are_floats() -> None:
    assert _resolved(".inf") == float("inf") and _resolved("-.inf") == float("-inf")
    nan = _resolved(".nan")
    assert isinstance(nan, float) and nan != nan


def test_l3_top_level_and_nested_keys_resolve_as_strings() -> None:
    state = split_body(_body(extra_top="yes: 1")).state
    assert "yes" in state and True not in state
    assert load_state("m: {no: 1, 010: 2, 1:30: 3}")["m"] == {"no": 1, "010": 2, "1:30": 3}


UNQUOTED_MERGE = "a: &A {x: 1}" + NL + "b: {<<: *A}"


def test_an_unquoted_merge_key_stays_literal_and_splices_nothing() -> None:
    state = load_state(UNQUOTED_MERGE)
    assert state["b"] == {"<<": {"x": 1}}  # the literal key "<<", holding the aliased mapping
    assert "x" not in state["b"]
    assert state["b"]["<<"] is state["a"]  # the alias itself stays a valid, shared, acyclic reference
    body = _body("note: {a: &A {x: 1}, b: {<<: *A}}")
    assert split_body(body).state["workflow"]["note"]["b"] == {"<<": {"x": 1}}
    assert errors(validate_workflow(split_body(body).state["workflow"])) == []


def _with_old_resolvers(monkeypatch: pytest.MonkeyPatch, tags: set[str]) -> None:
    """Restore SafeLoader's YAML 1.1 implicit resolvers for `tags` on the candidate loader, in
    memory only (the realistic regression Codex's CLOSURE4 mutants demonstrate)."""
    import yaml  # type: ignore[import-untyped]

    from minion_process import model

    resolvers = {k: list(v) for k, v in model._StateLoader.yaml_implicit_resolvers.items()}
    for first, entries in yaml.SafeLoader.yaml_implicit_resolvers.items():
        old = [(tag, regex) for tag, regex in entries if tag in tags]
        if old:
            kept = [(tag, regex) for tag, regex in resolvers.get(first, []) if tag not in tags]
            resolvers[first] = old + kept
    monkeypatch.setattr(model._StateLoader, "yaml_implicit_resolvers", resolvers)


def _l3_violations() -> list[str]:
    bad = []
    for scalar, expected in L3_VALUES:
        try:
            got = _resolved(scalar)
        except BodyFormatError:
            bad.append(scalar)
            continue
        if not (got == expected and type(got) is type(expected)):
            bad.append(scalar)
    with contextlib.suppress(BodyFormatError):
        if load_state(UNQUOTED_MERGE)["b"] == {"<<": {"x": 1}}:
            return bad
    return [*bad, "<<"]


@pytest.mark.parametrize(
    ("tag", "killed_by"),
    [
        ("int", {"1:30", "010", "0x1f", "1_000"}),
        ("merge", {"<<"}),
        ("bool", {"yes", "no", "on", "off"}),
        ("timestamp", {"2026-02-30", "2026-02-28", "2026-02-28 10:00:00"}),
        ("float", {"1_0.5", "1:30.0"}),
    ],
)
def test_each_old_resolver_restored_in_memory_is_caught(
    monkeypatch: pytest.MonkeyPatch, tag: str, killed_by: set[str]
) -> None:
    assert _l3_violations() == []  # GREEN on the candidate
    _with_old_resolvers(monkeypatch, {f"tag:yaml.org,2002:{tag}"})
    assert killed_by <= set(_l3_violations()), tag  # RED under the mutant


_KNOWN = dict(L3_VALUES)


def _known_tree(depth: int) -> st.SearchStrategy[tuple[str, object]]:
    """(YAML text, intended value) over L3_VALUES scalars nested in flow lists and mappings."""
    leaf = st.sampled_from([(s, v) for s, v in L3_VALUES if s])
    if depth <= 0:
        return leaf
    child = _known_tree(depth - 1)
    return st.one_of(
        leaf,
        st.lists(child, max_size=3).map(
            lambda xs: ("[" + ", ".join(t for t, _ in xs) + "]", [v for _, v in xs])
        ),
        st.lists(
            st.tuples(st.sampled_from(["a", "b", "c"]), child), max_size=3, unique_by=lambda kv: kv[0]
        ).map(
            lambda kv: ("{" + ", ".join(f"{k}: {t}" for k, (t, _) in kv) + "}", {k: v for k, (_, v) in kv})
        ),
    )


@settings(max_examples=200, deadline=None)
@given(tree=_known_tree(3))
def test_generated_known_scalars_resolve_to_their_intended_values(tree: tuple[str, object]) -> None:
    text, intended = tree
    got = load_state(f"x: {text}")["x"]

    def same(a: object, b: object) -> bool:
        if isinstance(b, dict):
            return isinstance(a, dict) and a.keys() == b.keys() and all(same(a[k], b[k]) for k in b)
        if isinstance(b, list):
            return isinstance(a, list) and len(a) == len(b) and all(map(same, a, b))
        return type(a) is type(b) and a == b

    assert same(got, intended), (text, got)
