"""Witnesses for the agreed CE-PROC-P3A-01 checkpoint, revision 7 (kit 0.3.0): the Markdown publication
domain is the CommonMark parser's block structure (R7a; matrix M11), and a comment contributes claims only
when the parser read it completely, with the silent nesting cutoff made unreachable and every parser
failure contained as an unread comment that makes the result INCOMPLETE (R11; matrix M12)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import markdown_it
import pytest
import yaml
from markdown_it import MarkdownIt

from minion_process import review
from minion_process.cli import main
from minion_process.github import GitHub
from minion_process.review import (
    INVALID_SHAPE,
    PARSER,
    Claim,
    UnreadComment,
    parse_review_records,
    publication_fences,
    select_reviews,
    validate_review,
)

from .test_minion_process import CODE, FakeGitHub, workflow
from .test_p3a_convergence import fence, header

H = fence(header())


def run(fake: FakeGitHub, *argv: str) -> int:
    return main(list(argv), gh=GitHub(fake.run))


def events(text: str) -> int:
    claims = parse_review_records(text)
    return len(select_reviews([review.Copy("t", 1, c) for c in claims], "WP-X").events)


def indent(block: str, n: int) -> str:
    return "".join(" " * n + line + "\n" for line in block.splitlines())


def nested_items(depth: int, last: str = "- item\n") -> str:
    return "".join("  " * i + "- item\n" for i in range(depth - 1)) + "  " * (depth - 1) + last


# --- M11: Markdown context ----------------------------------------------------------------------------------


def test_m11a_html_blocks_hide_fences() -> None:
    for wrapper in (("<!--\n", "-->\n"), ("<pre>\n", "</pre>\n"), ("<div>\n", "</div>\n")):
        body = wrapper[0] + H + wrapper[1]
        assert publication_fences(body) == [] and parse_review_records(body) == [], wrapper


def test_m11b_positives_after_other_blocks() -> None:
    for prefix in ("<!-- note -->\n\n", "## Verdict\n", "a paragraph line\n", "[x]: <url>\n"):
        assert events(prefix + H) == 1, prefix


def test_m11c_outer_code_blocks_make_the_example_literal() -> None:
    assert parse_review_records("````markdown\n" + H + "````\n") == []
    assert parse_review_records("~~~~\n" + H + "~~~~\n") == []


def test_m11d_text_before_the_opener_is_a_paragraph() -> None:
    assert parse_review_records("Example " + H) == []


def test_m11e_whole_block_indentation() -> None:
    assert events(indent(H, 3)) == 1
    assert publication_fences(indent(H, 3)) == publication_fences(H)  # de-indented, loads identically
    assert parse_review_records(indent(H, 4)) == []  # an indented code block


def test_m11f_quoted_and_listed_headers_are_quotations() -> None:
    quoted = "".join("> " + line + "\n" for line in H.splitlines())
    lines = H.splitlines()
    listed = "- " + lines[0] + "\n" + "".join("  " + line + "\n" for line in lines[1:])
    assert parse_review_records(quoted) == [] and parse_review_records(listed) == []


def test_m11g_info_string_first_word_raw() -> None:
    body = H.replace("```yaml", "~~~yaml").replace("```\n", "~~~\n")
    assert events(body) == 1
    assert events(H.replace("```yaml", "```yml title", 1)) == 1
    assert events(H.replace("```yaml", "```YAML", 1)) == 1
    assert parse_review_records(H.replace("```yaml", "```yaml-ish", 1)) == []
    assert parse_review_records(H.replace("```yaml", "```ya&#109;l", 1)) == []  # raw info, no entity decoding


def test_m11h_unclosed_fence_is_published() -> None:
    assert events(H.rsplit("```\n", 1)[0]) == 1


def test_m11i_ordinals_count_publication_fences_only() -> None:
    text = H + "\nprose\n" + fence(header(round=2)) + "```text\nreview: null\n```\n"
    assert [c.ordinal for c in parse_review_records(text)] == [0, 1]


def test_m11j_crlf_inline_and_table_cell() -> None:
    assert events(H.replace("\n", "\r\n")) == 1
    assert parse_review_records("see `review: null` here\n") == []
    assert parse_review_records("| a |\n|---|\n| ```yaml review: null ``` |\n") == []


def test_m11k_fence_looking_content_is_an_ordinary_fence() -> None:
    body = "````yaml\n```yaml\nreview: null\n```\n````\n"
    assert len(publication_fences(body)) == 1  # one publication fence
    assert parse_review_records(body) == []  # zero claims, zero invalid headers, zero events


def test_m11l_keep_chomp_content_is_handed_over_unmodified() -> None:
    (c,) = parse_review_records("```yaml\nreview: |+\n  x\n\n```\n")
    assert c.record == {"review": "x\n\n"} and c.reason is None
    assert any(p.path == "review" for p in validate_review(c.record))  # invalid shape, as a header


def test_m11m_nul_is_replaced_by_the_markdown_transport() -> None:
    (c,) = parse_review_records('```yaml\nreview: "a\x00b"\n```\n')
    assert c.record == {"review": "a�b"}
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load('review: "a\x00b"\n')  # the raw content would not even load


# --- M12: completeness -------------------------------------------------------------------------------------


def test_m12a_parser_exception_makes_the_comment_unread(
    fake: FakeGitHub, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    real = PARSER.parse

    def flaky(src: str, env: Any = None) -> Any:
        if "BOOM" in src:
            raise ValueError("injected")
        return real(src, env)

    monkeypatch.setattr(PARSER, "parse", flaky)
    fake.issue_comments[(CODE, 10)] = ["BOOM\n" + H, fence(header(round=2))]
    assert run(fake, "convergence", "counters", "10") == 0
    out = capsys.readouterr().out
    assert "1 distinct review event(s) read" in out
    assert "EXCLUDED: 1 comment(s) could not be fully read by the Markdown parser (comment id 10001)" in out
    assert (
        "THIS STATEMENT IS INCOMPLETE" in out and "RESULT INCOMPLETE" in out and "No trigger fired" not in out
    )
    target = tmp_path / "m.yaml"
    assert run(fake, "metrics", "10", "--out", str(target)) == 0
    m = yaml.safe_load(target.read_text(encoding="utf-8"))
    assert m["review_events"] == 1 and m["unread_comments"] == [10001] and m["complete"] is False
    with pytest.raises(UnreadComment):
        parse_review_records("BOOM\n" + H)


def test_m12b_codex_ten_item_body_is_fully_read() -> None:
    assert events(nested_items(10) + "\n" + H) == 1


def test_m12c_codex_reference_definition_body_is_fully_read() -> None:
    body = nested_items(50, "- [x]: /url\n") + "\n" + H
    env: dict[str, Any] = {}
    PARSER.parse(body, env)
    assert "X" in env["references"]  # the no-token block was read, not dropped
    assert events(body) == 1


def test_m12d_four_hundred_items_are_fully_read() -> None:
    assert events(nested_items(400) + "\n" + H) == 1


def test_m12e_recursion_failure_is_contained_as_unread(
    fake: FakeGitHub, capsys: pytest.CaptureFixture[str]
) -> None:
    limit = sys.getrecursionlimit()
    deep_quote = "> " * 4000 + "text\n"  # 8 001 characters, within the remote's comment cap
    assert len(deep_quote) < 65536
    for body in (nested_items(5000) + "\n" + H, deep_quote + "\n" + H, H + "\n" + deep_quote):
        with pytest.raises(UnreadComment, match="RecursionError"):
            parse_review_records(body)  # H before the failure is not credited either
    fake.issue_comments[(CODE, 10)] = [H + "\n" + deep_quote, fence(header(round=2))]
    assert run(fake, "convergence", "counters", "10") == 0
    out = capsys.readouterr().out
    assert (
        "1 distinct review event(s) read" in out and "comment id 10001" in out and "RESULT INCOMPLETE" in out
    )
    assert sys.getrecursionlimit() == limit


def test_m12f_negative_control_library_default_loses_the_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(review, "PARSER", MarkdownIt("commonmark"))  # maxNesting 20, the C004 failure
    assert events(nested_items(9) + "\n" + H) == 1
    assert (
        events(nested_items(10) + "\n" + H) == 0
    )  # silently gone: the intended witnesses M12b/M12c catch this
    body = nested_items(50, "- [x]: /url\n") + "\n" + H
    env: dict[str, Any] = {}
    review.PARSER.parse(body, env)
    assert "references" not in env and events(body) == 0


def test_m12g_parser_configuration() -> None:
    assert PARSER.options["maxNesting"] == sys.maxsize
    assert PARSER.get_active_rules() == MarkdownIt("commonmark").get_active_rules()  # no plugins
    major = int(markdown_it.__version__.split(".")[0])
    assert 3 <= major < 5


def test_unread_comment_without_metadata_is_reported_as_no_id(
    fake: FakeGitHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.issue_comments[(CODE, 10)] = [{"body": "> " * 4000 + "text\n"}]
    assert run(fake, "convergence", "counters", "10") == 0
    assert "(comment id no id)" in capsys.readouterr().out


def test_review_check_reports_an_unreadable_record(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "deep.md"
    path.write_text("> " * 4000 + "text\n\n" + H, encoding="utf-8")
    assert main(["review-check", str(path)]) == 1
    out = capsys.readouterr().out
    assert "could not be fully read by the Markdown parser (RecursionError)" in out and "INVALID" in out


def test_selection_complete_requires_no_unread() -> None:
    s = select_reviews([review.Copy("t", 1, Claim(0, header(), None))], "WP-X", unread=[7])
    assert len(s.events) == 1 and not s.complete and s.unread_comments == [7]
    assert select_reviews([], "WP-X").complete
    assert INVALID_SHAPE  # imported for the matrix's disposition wording
    _ = workflow  # the shared fixture module is imported for FakeGitHub state
