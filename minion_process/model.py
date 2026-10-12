"""Coordination-state model: the canonical vocabulary of `process/coordination-state.md` and the
issue-body container (one fenced YAML block, then free prose)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, ClassVar

import yaml  # type: ignore[import-untyped,unused-ignore]

MAX_DEPTH = 64
"""CE-PROC-L13-01 L2': the deepest container nesting a state may have. The root state mapping is
depth 1 and each nested mapping/list adds 1; scalars add nothing. Live bodies reach at most 6."""

MAX_NODES = 100_000
"""The largest EXPANDED graph a state may describe (every container and scalar counted once per path,
so a shared alias counts once per reference). It bounds alias bombs: acyclic sharing that expands
exponentially and makes graph equality -- the remote round-trip check -- run for hours. Live bodies
expand to fewer than 400 nodes."""


class _StateLoader(yaml.SafeLoader):  # type: ignore[misc,unused-ignore]
    """CE-PROC-L13-01 L3: a SafeLoader whose implicit resolvers are restricted to the YAML 1.2 core /
    JSON schema -- no yes/no/on/off booleans, sexagesimal numbers, implicit timestamps or `<<` merge
    keys. Every pattern is a subset of the YAML 1.1 resolver that `yaml.safe_dump` uses to decide
    quoting, so any scalar the dumper writes unquoted reads back exactly as it was written (L4)."""

    yaml_implicit_resolvers: ClassVar[dict[str, list[Any]]] = {}  # type: ignore[misc,unused-ignore]


for _tag, _pattern, _first in [
    ("tag:yaml.org,2002:bool", r"^(?:true|True|TRUE|false|False|FALSE)$", list("tTfF")),
    ("tag:yaml.org,2002:int", r"^[-+]?(?:0|[1-9][0-9]*)$", list("-+0123456789")),
    (
        "tag:yaml.org,2002:float",
        r"^(?:[-+]?(?:[0-9][0-9]*\.[0-9]*|\.[0-9]+)(?:[eE][-+][0-9]+)?|[-+]?\.(?:inf|Inf|INF)|\.(?:nan|NaN|NAN))$",
        list("-+0123456789."),
    ),
    ("tag:yaml.org,2002:null", r"^(?:~|null|Null|NULL|)$", [*"~nN", ""]),
]:
    _StateLoader.add_implicit_resolver(_tag, re.compile(_pattern), _first)


def _check_graph(state: Any) -> None:
    """CE-PROC-L13-01 L2': the loaded state is an acyclic JSON-domain graph (mappings with string keys,
    lists, strings, ints, floats, bools, null) of container depth <= MAX_DEPTH and expanded size <=
    MAX_NODES. Iterative -- an explicit stack, no recursion of its own -- and memoized per node, so
    shared aliases are walked once and a cycle (a node met again on its own ancestor path) is found."""
    heights: dict[int, int] = {}
    sizes: dict[int, int] = {}
    on_path: set[int] = set()
    stack: list[tuple[Any, str, bool]] = [(state, "workflow-state", False)]
    while stack:
        node, path, done = stack.pop()
        if not isinstance(node, (dict, list)):
            if not (node is None or isinstance(node, (str, int, float))):
                raise BodyFormatError(f"{path}: {type(node).__name__} is not a JSON value")
            continue
        key = id(node)
        children = list(node.values()) if isinstance(node, dict) else list(node)
        if done:
            on_path.discard(key)
            kids = [c for c in children if isinstance(c, (dict, list))]
            heights[key] = 1 + max((heights[id(c)] for c in kids), default=0)
            sizes[key] = 1 + sum(sizes[id(c)] if isinstance(c, (dict, list)) else 1 for c in children)
            if heights[key] > MAX_DEPTH:
                raise BodyFormatError(f"{path}: nesting deeper than {MAX_DEPTH}")
            if sizes[key] > MAX_NODES:
                raise BodyFormatError(f"{path}: expands to more than {MAX_NODES} nodes (alias expansion)")
            continue
        if key in heights:
            continue  # a shared, already-verified alias
        if key in on_path:
            raise BodyFormatError(f"{path}: cyclic alias")
        if len(on_path) >= MAX_DEPTH:
            raise BodyFormatError(f"{path}: nesting deeper than {MAX_DEPTH}")
        if isinstance(node, dict):
            for k in node:
                if not isinstance(k, str):
                    raise BodyFormatError(f"{path}: non-string key {k!r} ({type(k).__name__})")
        on_path.add(key)
        stack.append((node, path, True))
        items = list(node.items()) if isinstance(node, dict) else list(enumerate(node))
        for k, child in reversed(items):  # pushed in reverse, so visited in document order
            stack.append((child, f"{path}.{k}", False))


def load_state(text: str) -> Any:
    """The state block's YAML as a validated JSON-domain graph (CE-PROC-L13-01 L1'/L2'/L3).

    Any `Exception` while loading or checking is malformed content: `BodyFormatError`. Loading runs no
    remote call and no caller code, so nothing outside the content can raise here (rule 9). A
    `BaseException` that is not an `Exception` is not caught."""
    try:
        state = yaml.load(text, Loader=_StateLoader)
        _check_graph(state)
    except BodyFormatError:
        raise
    except Exception as error:  # L1': every content-derived failure, from any constructor
        raise BodyFormatError(f"state block is not valid YAML: {type(error).__name__}: {error}") from error
    return state


STATUSES = (
    "SCOPING",
    "CONTRACT_DRAFT",
    "CONTRACT_REVIEW",
    "PYTHON_IMPLEMENTATION",
    "IMPLEMENTATION_REVIEW",
    "REMEDIATION",
    "CONTRACT_CONVERGENCE",
    "FINAL_CONTRACT_REVIEW",
    "RUST_IMPLEMENTATION",
    "CLOSURE_REVIEW",
    "WAITING_FOR_TRIGGER",
    "CLOSED",
    "INCIDENT",
    "INVALID_UNAUTHORIZED",
    "BLOCKED_FOR_OWNER",
)
"""`coordination-state.md` §3.1."""

ACTIVE = frozenset(
    {
        "SCOPING",
        "CONTRACT_DRAFT",
        "CONTRACT_REVIEW",
        "PYTHON_IMPLEMENTATION",
        "IMPLEMENTATION_REVIEW",
        "REMEDIATION",
        "CONTRACT_CONVERGENCE",
        "FINAL_CONTRACT_REVIEW",
        "RUST_IMPLEMENTATION",
        "CLOSURE_REVIEW",
        "BLOCKED_FOR_OWNER",
    }
)
"""`coordination-state.md` §4.1: states requiring `next_owner` and `next_action`."""

NON_ACTIONABLE = frozenset({"INCIDENT", "INVALID_UNAUTHORIZED"})
OWNERS = frozenset({"Claude", "Codex", "Owner"})

FENCE_OPEN = "```yaml\n"
FENCE_CLOSE = "\n```"


class BodyFormatError(ValueError):
    """The issue body does not start with the canonical fenced-YAML state block."""


@dataclass(frozen=True)
class IssueBody:
    """An issue body split into its canonical state object and the prose that follows it."""

    state: dict[str, Any]
    prose: str

    @property
    def workflow(self) -> dict[str, Any]:
        workflow = self.state.get("workflow")
        if not isinstance(workflow, dict):
            raise BodyFormatError("state block has no `workflow` mapping")
        return workflow


def normalize(text: str) -> str:
    """One multiline document: strip a BOM, and use LF line endings (`agent-workflow.md` §11.1.1)."""
    return text.lstrip("\ufeff").replace("\r\n", "\n")


def split_body(body: str) -> IssueBody:
    """Parse `body`: it must start with the fenced YAML block (`coordination-state.md` §2)."""
    text = normalize(body)
    if not text.startswith(FENCE_OPEN):
        raise BodyFormatError("issue body does not start with a ```yaml state block")
    end = text.find(FENCE_CLOSE, len(FENCE_OPEN))
    if end < 0:
        raise BodyFormatError("unterminated ```yaml state block")
    state = load_state(text[len(FENCE_OPEN) : end])
    if not isinstance(state, dict):
        raise BodyFormatError("state block is not a YAML mapping")
    rest = text[end + len(FENCE_CLOSE) :]
    return IssueBody(state=state, prose=rest[1:] if rest.startswith("\n") else rest)


def render_body(state: dict[str, Any], prose: str) -> str:
    """The canonical body for `state` followed by `prose` (the inverse of `split_body`)."""
    text: str = yaml.safe_dump(state, sort_keys=False, width=110, allow_unicode=True)
    return FENCE_OPEN + text + "```\n" + prose


def candidates(workflow: dict[str, Any]) -> dict[str, Any]:
    """The `code`/`docs` candidate entries: the single accessor every consumer uses (CE-PROC-L13-01
    rule 8), read only after validation. A supplied v2 `current_candidate` is never rerouted to the
    v1 top-level form, even when malformed (rule 2)."""
    if "current_candidate" in workflow:
        current = workflow["current_candidate"]
        source = current if isinstance(current, dict) else {}
    else:
        source = workflow
    return {side: source.get(side) for side in ("code", "docs")}
