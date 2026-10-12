"""Structured review records (`templates/review-record.md`, record §6.6; kit 0.3.0).

A review record carries one fenced YAML block whose top-level key is `review`; the prose stays below it.
The tool reads these headers from the published verdicts (comments on the coordination issue and on the
candidate PRs) to compute the §11.8 convergence counters and the §14.6 metrics. It never writes a
verdict and never decides semantics: the labels are the recorded verdicts and negative controls.

The rules implemented here are the agreed convergence contract `CE-PROC-P3A-01` (`minion-agent#213`):

- **Identity (R1-R4).** One review event is `(wp, reviewer, round)`; `round` is the reviewer's own
  count of its separately issued review events on the WP. Copies of one event whose parsed values are
  equal are mirrors (one event); copies whose values differ are a conflict, reported and excluded, never
  resolved by choosing.
- **Chronology (R5-R6).** Events are ordered by the publication time of their earliest copy; the total
  copy key is `(created_at, round, comment id, fence ordinal)`.
- **Discovery (R7-R10).** A fenced YAML block is a review claim when the YAML scanner's token prefix up to
  the first key scalar is `[Directive]* [DocumentStart]? [Anchor|Tag]* MappingStart Key [Anchor|Tag]*
  Scalar("review")`. One reason per claim, in priority: `unsupported publication form` (any property or
  an explicit key), `unparsable`, `invalid shape`, else valid. Nothing after the first key is consulted.

Validation is total (diagnostics, never a raise) and fails closed (unknown keys and malformed values
are errors). Presence is decided by the key, never by truthiness."""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import yaml
from markdown_it import MarkdownIt
from yaml.tokens import (
    AnchorToken,
    BlockMappingStartToken,
    DirectiveToken,
    DocumentStartToken,
    FlowMappingStartToken,
    KeyToken,
    ScalarToken,
    StreamStartToken,
    TagToken,
)

from .profile import TAXONOMY
from .validate import FINDING_ID, SHA, Problem, _finding_id, _text

SCHEMA_VERSION = 2
REVIEW_TYPES = (
    "CONTRACT_REVIEW",
    "IMPLEMENTATION_REVIEW",
    "TARGETED_CLOSURE",
    "CHECKPOINT",
    "FINAL_REVIEW",
    "CLOSURE_REVIEW",
    "PROCESS_REVIEW",
)
VERDICTS = ("APPROVED", "CHANGES_REQUESTED", "HANDOFF_BLOCKED")
TIERS = ("G0", "G1", "G2", "G3", "none")
CLASS_OUTCOMES = ("CONFIRMED", "CORRECTED")
ALIAS = re.compile(r"^[A-Z][A-Z0-9_]*$")
NOT_APPLICABLE = "NOT_APPLICABLE"
PARSER = MarkdownIt("commonmark", {"maxNesting": sys.maxsize})
"""The CommonMark parser that decides which text of a comment is a fenced code block (R7a). The
`commonmark` preset only, no plugins. `maxNesting` is unreachable (R11b): the library's only silent
truncation branches run when nesting reaches that limit, so with it unreachable every parse either reads
the whole body or raises (the interpreter's recursion limit), and the exception is contained per comment
(R11a). Never configure a finite limit here and never raise the recursion limit to make a body parse."""
PUBLICATION_LANGUAGES = ("yaml", "yml")


class UnreadComment(Exception):
    """The parser did not return normally for a comment (R11a): the comment contributes no claims and is
    reported as unread; the statement and metrics are INCOMPLETE."""


def publication_fences(text: str) -> list[str]:
    """The content of every publication fence of a comment, in document order (R7a): a fenced code block at
    the top level of the document (not inside a block quote or list item) whose raw info string's first
    whitespace-delimited word is `yaml` or `yml`, compared case-insensitively and without entity decoding.
    Content is exactly what the parser yields (opener indentation removed, line endings normalized, U+0000
    replaced by U+FFFD by the parser's core normalization, terminal line feed kept). Raises whatever the
    parser raises; `parse_review_records` turns that into `UnreadComment`."""
    tokens = PARSER.parse(text, {})  # a fresh environment per comment
    found: list[str] = []
    for token in tokens:
        if token.type != "fence" or token.level != 0:
            continue
        words = token.info.split()
        if words and words[0].lower() in PUBLICATION_LANGUAGES:
            found.append(token.content)
    return found


UNSUPPORTED = "unsupported publication form"
UNPARSABLE = "unparsable"
INVALID_SHAPE = "invalid shape"
REASONS = (UNSUPPORTED, UNPARSABLE, INVALID_SHAPE)

TOP_REQUIRED = (
    "schema_version",
    "wp",
    "type",
    "round",
    "complete",
    "reviewer",
    "author",
    "candidate",
    "verdict",
    "new_evidence",
    "findings",
    "closed",
)
TOP_OPTIONAL = ("gate_tier_verified", "class_confirmation")


class _Check:
    def __init__(self) -> None:
        self.problems: list[Problem] = []

    def error(self, path: str, message: str) -> None:
        self.problems.append(Problem("error", path, message))


# --- discovery (R7, R8 priority 1) -------------------------------------------------------------------


@dataclass(frozen=True)
class Claim:
    """One review claim found in a comment: `record` is the loaded document (or None), `reason` is the
    disposition decided before shape validation (`UNSUPPORTED`, `UNPARSABLE`) or None when the shape
    validator decides; `ordinal` is the fence's position among the YAML fences of its comment."""

    ordinal: int
    record: Any
    reason: str | None


def discover(block: str) -> tuple[bool, bool]:
    """R7: `(is_claim, unsupported)` from the scanner's token prefix up to the first key scalar.

    The prefix must be StreamStart [Directive]* [DocumentStart]? [Anchor|Tag]* (Block|Flow)MappingStart
    Key [Anchor|Tag]* Scalar; the block is a claim when that Scalar's value is `review`. `unsupported` is
    true when any Anchor/Tag token appears in the prefix or the Key token is explicit (its start mark is
    the `?` indicator). Any YAML error (reader or scanner) before the first key scalar means there is no
    recognizable first entry: not a claim."""
    unsupported = False
    stage = "start"
    try:
        for token in yaml.scan(block):
            if stage == "start":
                if isinstance(token, StreamStartToken):
                    stage = "prologue"
                    continue
                return False, False  # pragma: no cover  (the scanner's first token is always StreamStart)
            if stage == "prologue":
                if isinstance(token, DirectiveToken):
                    continue
                if isinstance(token, DocumentStartToken):
                    stage = "root"
                    continue
                stage = "root"
            if stage == "root":
                if isinstance(token, (AnchorToken, TagToken)):
                    unsupported = True
                    continue
                if isinstance(token, (BlockMappingStartToken, FlowMappingStartToken)):
                    stage = "key"
                    continue
                return False, False  # a root scalar, sequence or anything else: no mapping entry
            if stage == "key":
                if not isinstance(token, KeyToken):
                    return False, False
                if block[token.start_mark.index : token.start_mark.index + 1] == "?":
                    unsupported = True
                stage = "key-node"
                continue
            if stage == "key-node":
                if isinstance(token, (AnchorToken, TagToken)):
                    unsupported = True
                    continue
                if isinstance(token, ScalarToken):
                    return (True, unsupported) if token.value == "review" else (False, False)
                return False, False  # a collection or alias key is not the scalar key `review`
    except Exception:  # a reader or scanner failure before the first key: no recognizable first entry
        return False, False
    return False, False  # pragma: no cover  (the scanner always ends with StreamEnd, handled above)


def parse_review_records(text: str) -> list[Claim]:
    """Every review claim in `text` (R7a, R7b), each with its disposition reason when decided before shape
    validation (R8 priorities 1-2) or its loaded record otherwise. Nothing recognizable is dropped (R10).
    Raises `UnreadComment`, and nothing else, when the Markdown parser does not return normally (R11a); no
    claim of such a comment is ever emitted, including a fence tokenized before the failure."""
    try:
        blocks = publication_fences(text)
    except Exception as exc:  # RecursionError included; never retried with a larger limit
        raise UnreadComment(type(exc).__name__) from None
    claims: list[Claim] = []
    for ordinal, block in enumerate(blocks):
        is_claim, unsupported = discover(block)
        if not is_claim:
            continue
        if unsupported:
            claims.append(Claim(ordinal, None, UNSUPPORTED))
            continue
        try:
            claims.append(Claim(ordinal, yaml.safe_load(block), None))
        except Exception:  # any loader or construction failure of a recognized claim is `unparsable`
            claims.append(Claim(ordinal, None, UNPARSABLE))
    return claims


def _unknown(keys: Any, allowed: set[str]) -> list[str]:
    """Unknown keys as sorted strings; any YAML key type is tolerated."""
    return sorted(str(k) for k in keys if k not in allowed)


# --- shape (R8 priority 3) ----------------------------------------------------------------------------


def validate_review(record: Any) -> list[Problem]:
    """Every rule of the review header. Returns diagnostics; never raises."""
    c = _Check()
    if not isinstance(record, dict) or set(record) != {"review"}:
        c.error("review", "a review record is one mapping with the single top-level key `review`")
        return c.problems
    r = record["review"]
    if not isinstance(r, dict):
        c.error("review", f"must be a mapping, got {type(r).__name__}")
        return c.problems
    for key in TOP_REQUIRED:
        if key not in r:
            c.error(f"review.{key}", "required")
    extra = _unknown(r, set(TOP_REQUIRED) | set(TOP_OPTIONAL))
    if extra:
        c.error("review", f"unknown keys {extra}")
    version = r.get("schema_version")
    if "schema_version" in r and (
        not isinstance(version, int) or isinstance(version, bool) or version != SCHEMA_VERSION
    ):
        c.error(
            "review.schema_version",
            f"unsupported review schema_version {version!r} (supported: {SCHEMA_VERSION})",
        )
    if "wp" in r and not _text(r["wp"]):
        c.error("review.wp", "must be a non-empty string")
    if "type" in r and r["type"] not in REVIEW_TYPES:
        c.error("review.type", f"must be one of {', '.join(REVIEW_TYPES)}, got {r['type']!r}")
    rnd = r.get("round")
    if "round" in r and (not isinstance(rnd, int) or isinstance(rnd, bool) or rnd < 1):
        c.error("review.round", f"must be a positive integer (the reviewer's own event count), got {rnd!r}")
    for key in ("complete", "new_evidence"):
        if key in r and not isinstance(r[key], bool):
            c.error(f"review.{key}", f"must be a boolean, got {r[key]!r}")
    for key in ("reviewer", "author"):
        if key in r and not _text(r[key]):
            c.error(f"review.{key}", "must be a non-empty string")
    reviewer, author = r.get("reviewer"), r.get("author")
    if (
        isinstance(reviewer, str)
        and isinstance(author, str)
        and _text(reviewer)
        and _text(author)
        and reviewer.strip().lower() == author.strip().lower()
    ):
        c.error("review.reviewer", "the reviewer must differ from the candidate's author (independence)")
    if "candidate" in r:
        _candidate(c, r["candidate"])
    if "gate_tier_verified" in r and r["gate_tier_verified"] not in TIERS:
        c.error(
            "review.gate_tier_verified", f"must be one of {', '.join(TIERS)}, got {r['gate_tier_verified']!r}"
        )
    if "class_confirmation" in r:
        _class_confirmation(c, r["class_confirmation"])
    verdict = r.get("verdict")
    if "verdict" in r and verdict not in VERDICTS:
        c.error("review.verdict", f"must be one of {', '.join(VERDICTS)}, got {verdict!r}")
    blocking = _findings(c, r["findings"]) if "findings" in r else 0
    if "closed" in r:
        _closed(c, r["closed"])
    if verdict == "APPROVED" and blocking:
        c.error(
            "review.verdict",
            f"APPROVED with {blocking} blocking finding(s): a blocking finding is a rejection",
        )
    if verdict == "HANDOFF_BLOCKED" and isinstance(r.get("findings"), list) and r["findings"]:
        c.error(
            "review.findings", "HANDOFF_BLOCKED is not a verdict on the candidate; it carries no findings"
        )
    return c.problems


def _candidate(c: _Check, candidate: Any) -> None:
    if not isinstance(candidate, dict) or not candidate:
        c.error("review.candidate", "must be a non-empty mapping of side -> 40-hex SHA")
        return
    for side, sha in candidate.items():
        if not (isinstance(side, str) and _text(side)):
            c.error("review.candidate", "sides must be non-empty strings")
        elif not (isinstance(sha, str) and SHA.match(sha)):
            c.error(f"review.candidate.{side}", f"not a full 40-hex SHA: {sha!r}")


def _class_confirmation(c: _Check, cc: Any) -> None:
    if not isinstance(cc, dict):
        c.error("review.class_confirmation", "must be a mapping {kind, class, rule, outcome}")
        return
    for key in ("kind", "class", "rule"):
        if not _text(cc.get(key)):
            c.error(f"review.class_confirmation.{key}", "required non-empty string")
    if cc.get("outcome") not in CLASS_OUTCOMES:
        c.error(
            "review.class_confirmation.outcome",
            f"must be one of {', '.join(CLASS_OUTCOMES)}, got {cc.get('outcome')!r}",
        )
    extra = _unknown(cc, {"kind", "class", "rule", "outcome"})
    if extra:
        c.error("review.class_confirmation", f"unknown keys {extra}")


def _findings(c: _Check, findings: Any) -> int:
    """Validates the findings list and returns the number of blocking findings."""
    if not isinstance(findings, list):
        c.error("review.findings", "must be a list of {id, class, blocking, surface?, witness?}")
        return 0
    blocking = 0
    seen: set[str] = set()
    for i, f in enumerate(findings):
        path = f"review.findings[{i}]"
        if not isinstance(f, dict):
            c.error(path, "must be a mapping {id, class, blocking, surface?, witness?}")
            continue
        if not _finding_id(f.get("id")):
            c.error(f"{path}.id", f"must be a finding ID, got {f.get('id')!r}")
        elif f["id"] in seen:
            c.error(f"{path}.id", f"duplicate finding {f['id']}")
        else:
            seen.add(f["id"])
        klass = f.get("class")
        if not (isinstance(klass, str) and (klass in TAXONOMY or ALIAS.match(klass))):
            c.error(f"{path}.class", f"must be a taxonomy class or a profile alias, got {klass!r}")
        if not isinstance(f.get("blocking"), bool):
            c.error(f"{path}.blocking", f"must be a boolean, got {f.get('blocking')!r}")
        elif f["blocking"]:
            blocking += 1
        for key in ("surface", "witness"):
            if key in f and not _text(f[key]):
                c.error(f"{path}.{key}", "must be a non-empty string when present")
        extra = _unknown(f, {"id", "class", "blocking", "surface", "witness"})
        if extra:
            c.error(path, f"unknown keys {extra}")
    return blocking


def _closed(c: _Check, closed: Any) -> None:
    if not isinstance(closed, list):
        c.error("review.closed", "must be a list of {id, negative_control, reason?}")
        return
    for i, entry in enumerate(closed):
        path = f"review.closed[{i}]"
        if not isinstance(entry, dict):
            c.error(path, "must be a mapping {id, negative_control, reason?} (§11.8.7.1)")
            continue
        if not _finding_id(entry.get("id")):
            c.error(f"{path}.id", f"must be a finding ID, got {entry.get('id')!r}")
        control = entry.get("negative_control")
        if not (isinstance(control, str) and _text(control)):
            c.error(
                f"{path}.negative_control",
                "required: the known-bad method, or NOT_APPLICABLE with a reason",
            )
        elif control.strip() == NOT_APPLICABLE and not _text(entry.get("reason")):
            c.error(f"{path}.reason", "NOT_APPLICABLE requires the reason (documentary/traceability-only)")
        extra = _unknown(entry, {"id", "negative_control", "reason"})
        if extra:
            c.error(path, f"unknown keys {extra}")


# --- identity, mirrors, conflicts, chronology (R1-R6) ------------------------------------------------


@dataclass(frozen=True)
class Copy:
    """One published copy of a review claim: the remote's publication metadata plus the claim."""

    created_at: str | None
    comment_id: int | None
    claim: Claim

    @property
    def orderable(self) -> bool:
        """R5/R6 need the remote's publication metadata; a copy without it cannot be placed in time."""
        return isinstance(self.created_at, str) and isinstance(self.comment_id, int)


@dataclass
class Selection:
    """The distinct, valid review events of one work package, in publication order, with everything
    that was excluded from them made visible. `unorderable` copies (publication metadata missing) make
    the whole selection INCOMPLETE: it can still show what it read, never a negative result."""

    events: list[dict[str, Any]] = field(default_factory=list)
    mirrors: int = 0
    conflicts: list[dict[str, Any]] = field(default_factory=list)  # {identity, fields}
    invalid: dict[str, int] = field(default_factory=lambda: dict.fromkeys(REASONS, 0))
    multi_header_comments: int = 0
    unorderable: int = 0
    unread_comments: list[int | None] = field(default_factory=list)  # R11: ids of comments not fully read

    @property
    def invalid_total(self) -> int:
        return sum(self.invalid.values())

    @property
    def complete(self) -> bool:
        return self.unorderable == 0 and not self.unread_comments


def _differing_fields(headers: list[dict[str, Any]]) -> list[str]:
    """The top-level header fields whose values differ among same-identity copies (R4)."""
    keys = sorted({str(k) for h in headers for k in h})
    return [k for k in keys if len({json.dumps(h.get(k), sort_keys=True, default=str) for h in headers}) > 1]


def select_reviews(copies: list[Copy], wp: str, unread: list[int | None] | None = None) -> Selection:
    """R1-R6 over the published copies of one work package; `unread` are the ids of comments the parser
    did not fully read (R11), carried through so the result is marked INCOMPLETE."""
    s = Selection(unread_comments=list(unread or []))
    per_comment: Counter[int] = Counter()
    groups: dict[tuple[str, str, int], list[tuple[tuple[str, int, int, int], str, dict[str, Any]]]] = {}
    for copy in copies:
        if not copy.orderable:
            s.unorderable += 1  # R004: evidence whose publication metadata is missing is excluded, visibly
            continue
        assert isinstance(copy.comment_id, int)  # narrowed by `orderable`
        per_comment[copy.comment_id] += 1
        claim = copy.claim
        if claim.reason is not None:
            s.invalid[claim.reason] += 1
            continue
        if validate_review(claim.record):
            s.invalid[INVALID_SHAPE] += 1
            continue
        header = claim.record["review"]
        if header["wp"] != wp:
            continue  # another work package's record published here: not this WP's evidence
        identity = (str(header["wp"]), str(header["reviewer"]), int(header["round"]))
        key = (str(copy.created_at), int(header["round"]), copy.comment_id, claim.ordinal)
        canonical = json.dumps(header, sort_keys=True, default=str)
        groups.setdefault(identity, []).append((key, canonical, header))
    s.multi_header_comments = sum(1 for n in per_comment.values() if n > 1)
    ordered: list[tuple[tuple[str, int, int, int], dict[str, Any]]] = []
    for identity, members in groups.items():
        if len({canonical for _, canonical, _ in members}) > 1:
            s.conflicts.append(
                {
                    "identity": f"(wp={identity[0]}, reviewer={identity[1]}, round={identity[2]})",
                    "fields": _differing_fields([header for _, _, header in members]),
                }
            )
            continue
        s.mirrors += len(members) - 1
        representative = min(members, key=lambda m: m[0])
        ordered.append((representative[0], representative[2]))
    s.conflicts.sort(key=lambda c: str(c["identity"]))
    s.events = [header for _, header in sorted(ordered, key=lambda m: m[0])]
    return s


# --- counters and metrics (§11.8, §14.6) ------------------------------------------------------------


@dataclass
class Counters:
    """The §11.8 triggers from the distinct review events of one work package."""

    reviews: int = 0
    survived: dict[str, int] = field(default_factory=dict)  # blocking finding id -> events it survived
    successors: dict[str, list[str]] = field(default_factory=dict)  # surface -> distinct blocking ids
    rejected_complete: int = 0
    rounds_without_new_evidence: int = 0
    consecutive_without_new_evidence: int = 0
    mirrors: int = 0
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    invalid: dict[str, int] = field(default_factory=lambda: dict.fromkeys(REASONS, 0))
    multi_header_comments: int = 0
    unorderable: int = 0
    unread_comments: list[int | None] = field(default_factory=list)

    @property
    def a_fired(self) -> list[str]:
        return sorted(f for f, n in self.survived.items() if n >= 2)

    @property
    def b_fired(self) -> list[str]:
        return sorted(s for s, ids in self.successors.items() if len(ids) >= 2)

    @property
    def c_fired(self) -> bool:
        return self.rejected_complete >= 3

    @property
    def invalid_total(self) -> int:
        return sum(self.invalid.values())


def counters(selection: Selection) -> Counters:
    k = Counters(
        reviews=len(selection.events),
        mirrors=selection.mirrors,
        conflicts=list(selection.conflicts),
        invalid=dict(selection.invalid),
        multi_header_comments=selection.multi_header_comments,
        unorderable=selection.unorderable,
        unread_comments=list(selection.unread_comments),
    )
    streak = 0
    for r in selection.events:
        if r["verdict"] == "HANDOFF_BLOCKED":
            continue  # not a review of the candidate (§11.11)
        for f in r["findings"]:
            if f["blocking"]:
                k.survived[f["id"]] = k.survived.get(f["id"], 0) + 1
                if f.get("surface"):
                    ids = k.successors.setdefault(f["surface"], [])
                    if f["id"] not in ids:
                        ids.append(f["id"])
        if r["complete"] and r["verdict"] == "CHANGES_REQUESTED":
            k.rejected_complete += 1
        if r["verdict"] == "CHANGES_REQUESTED" and not r["new_evidence"]:
            k.rounds_without_new_evidence += 1
            streak += 1
        else:
            streak = 0
        k.consecutive_without_new_evidence = max(k.consecutive_without_new_evidence, streak)
    return k


def trigger_statement(k: Counters) -> str:
    """The mandatory §11.8 trigger statement, from recorded evidence only. Excluded evidence is listed so it
    is never mistaken for a negative result."""
    lines = [f"{k.reviews} distinct review event(s) read, ordered by publication time."]
    if k.mirrors:
        lines.append(
            f"{k.mirrors} transport cop{'y' if k.mirrors == 1 else 'ies'} of the same event ignored."
        )
    if k.unorderable:
        lines.append(
            f"EXCLUDED: {k.unorderable} review claim(s) in comment(s) without publication metadata (id or "
            "created_at missing): they cannot be ordered and were not read. THIS STATEMENT IS INCOMPLETE."
        )
    if k.unread_comments:
        ids = ", ".join("no id" if i is None else str(i) for i in k.unread_comments)
        lines.append(
            f"EXCLUDED: {len(k.unread_comments)} comment(s) could not be fully read by the Markdown parser "
            f"(comment id {ids}): no claim from them was read. THIS STATEMENT IS INCOMPLETE."
        )
    if k.conflicts:
        described = "; ".join(
            f"{c['identity']} differing in {', '.join(c['fields']) or 'no top-level field'}"
            for c in k.conflicts
        )
        lines.append(
            f"EXCLUDED: {len(k.conflicts)} conflicting identit{'y' if len(k.conflicts) == 1 else 'ies'} "
            f"(copies with the same identity but different values; not resolved): {described}."
        )
    if k.invalid_total:
        parts = [f"{n} {reason}" for reason, n in k.invalid.items() if n]
        lines.append(f"EXCLUDED: {k.invalid_total} invalid review header(s): {', '.join(parts)}.")
    if k.multi_header_comments:
        lines.append(
            f"{k.multi_header_comments} comment(s) carry more than one header; their order rests on fence "
            "position."
        )
    if k.a_fired:
        lines.append(f"Trigger A HAS FIRED: {', '.join(k.a_fired)} survived two or more independent reviews.")
    else:
        worst = max(k.survived.values(), default=0)
        lines.append(f"Trigger A has not fired: no blocking finding survived two reviews (max {worst}).")
    if k.b_fired:
        parts = [f"{s} ({', '.join(k.successors[s])})" for s in k.b_fired]
        lines.append(f"Trigger B HAS FIRED: successor findings on the same surface: {'; '.join(parts)}.")
    else:
        lines.append("Trigger B has not fired: no root-cause surface has two distinct blocking findings.")
    if k.c_fired:
        lines.append(f"Trigger C HAS FIRED: {k.rejected_complete} rejected complete reviews.")
    else:
        lines.append(f"Trigger C has not fired: {k.rejected_complete} rejected complete review(s).")
    lines.append(
        f"Rounds without new discriminating evidence: {k.rounds_without_new_evidence} "
        f"(longest streak {k.consecutive_without_new_evidence})."
    )
    fired = bool(k.a_fired or k.b_fired or k.c_fired)
    if fired:
        lines.append(
            "CONVERGENCE TRIGGER FIRED: enter CONTRACT_CONVERGENCE, or state why a single targeted fix "
            "closes the surface (routing.md RT-6 where routing is delegated)."
        )
    elif k.unorderable or k.unread_comments:
        lines.append(
            "RESULT INCOMPLETE: evidence was excluded (publication metadata missing or a comment not fully "
            "read), so no negative conclusion follows from the events read. Establish the missing evidence "
            "and rerun; "
            "the coordinator's own section 11.8 check against the full review history remains mandatory."
        )
    else:
        lines.append(
            "No trigger fired in the recorded events. The coordinator's own section 11.8 check against the "
            "full review history, including anything excluded above, remains mandatory."
        )
    return "\n".join(lines)


def metrics(workflow: dict[str, Any], selection: Selection) -> dict[str, Any]:
    """The §14.6 metrics available from the state block and the recorded review events."""
    k = counters(selection)
    reviews = selection.events
    by_class: Counter[str] = Counter()
    by_tier: Counter[str] = Counter()
    closed_nc = closed_na = 0
    for r in reviews:
        by_tier[str(r.get("gate_tier_verified", "none"))] += 1
        for f in r["findings"]:
            by_class[f["class"]] += 1
        for entry in r["closed"]:
            if entry["negative_control"].strip() == NOT_APPLICABLE:
                closed_na += 1
            else:
                closed_nc += 1
    history: dict[str, Any] = workflow["history"] if isinstance(workflow.get("history"), dict) else {}
    routes: list[Any] = history["routes"] if isinstance(history.get("routes"), list) else []
    route_ids = [r.get("rule") for r in routes if isinstance(r, dict)]
    consequence: dict[str, Any] = (
        workflow["consequence"] if isinstance(workflow.get("consequence"), dict) else {}
    )
    return {
        "work_package": workflow.get("work_package"),
        "kind": workflow.get("kind"),
        "class": consequence.get("class"),
        "status": workflow.get("status"),
        "review_events": k.reviews,
        "complete_reviews": sum(1 for r in reviews if r["complete"]),
        "targeted_reviews": sum(1 for r in reviews if not r["complete"]),
        "approvals": sum(1 for r in reviews if r["verdict"] == "APPROVED"),
        "rejected_complete_reviews": k.rejected_complete,
        "handoff_blocked": sum(1 for r in reviews if r["verdict"] == "HANDOFF_BLOCKED"),
        "rounds_without_new_evidence": k.rounds_without_new_evidence,
        "longest_streak_without_new_evidence": k.consecutive_without_new_evidence,
        "findings_recorded": sum(len(r["findings"]) for r in reviews),
        "findings_by_class": dict(sorted(by_class.items())),
        "closed_with_negative_control": closed_nc,
        "closed_documentary": closed_na,
        "gate_tiers_verified": dict(sorted(by_tier.items())),
        "routes_taken": sorted(Counter(str(r) for r in route_ids).items()),
        "owner_questions_routed": sum(1 for r in route_ids if r in ("RT-4", "RT-6")),
        "triggers": {"A": k.a_fired, "B": k.b_fired, "C": k.c_fired},
        "transport_copies_ignored": k.mirrors,
        "conflicting_identities": [dict(c) for c in k.conflicts],
        "invalid_review_headers": dict(k.invalid),
        "comments_with_multiple_headers": k.multi_header_comments,
        "claims_without_publication_metadata": k.unorderable,
        "unread_comments": list(k.unread_comments),
        "complete": k.unorderable == 0 and not k.unread_comments,
    }


__all__ = [
    "FINDING_ID",
    "INVALID_SHAPE",
    "PARSER",
    "SCHEMA_VERSION",
    "UNPARSABLE",
    "UNSUPPORTED",
    "Claim",
    "Copy",
    "Counters",
    "Selection",
    "UnreadComment",
    "counters",
    "discover",
    "metrics",
    "parse_review_records",
    "publication_fences",
    "select_reviews",
    "trigger_statement",
    "validate_review",
]
