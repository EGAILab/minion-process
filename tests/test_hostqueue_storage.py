"""Framing, journal, effect markers, containment and the no-follow walk (B-4, K-13, K-25 to K-30, K-35,
K-36, B-31; witnesses W-24, W-53, W-83, W-84 and the N001 publication cut)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from minion_process.hostqueue import contain, framing, journal, walk
from minion_process.hostqueue.markers import ABSENT, MarkerExists, Markers, Unreadable

from .hostqueue_fake import FakeHost

# -- framing ---------------------------------------------------------------------------------------------


def test_encode_decode_round_trip() -> None:
    data = framing.encode({"seq": 1, "kind": "x", "v": "é"})
    assert framing.decode_single(data) == {"seq": 1, "kind": "x", "v": "é"}


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda d: d[:10], "short header"),
        (lambda d: b"XPQ1" + d[4:], "bad magic"),
        (lambda d: d[:13] + b"_" + d[14:], "bad separators"),
        (lambda d: d[:5] + b"zzzzzzzz" + d[13:], "bad length"),
        (lambda d: d[:5] + b"000fffff" + d[13:], "length beyond end of data"),
        (lambda d: d[:-5] + b" EXD\n", "missing or damaged commit marker"),
        (lambda d: d[:-6] + b"X" + d[-5:], "checksum mismatch"),
    ],
)
def test_decode_reports_the_first_mismatch(mutate: object, reason: str) -> None:
    data = framing.encode({"seq": 1, "kind": "x"})
    with pytest.raises(framing.FramingError) as caught:
        framing.decode_at(mutate(data), 0)  # type: ignore[operator]
    assert caught.value.reason == reason


def _frame(body: bytes) -> bytes:
    import hashlib

    digest = hashlib.sha256(body).hexdigest().encode()
    return framing.MAGIC + f"{len(body):08x}".encode() + b" " + digest + b" " + body + framing.COMMIT


def test_payload_must_be_a_json_object() -> None:
    with pytest.raises(framing.FramingError, match="not JSON"):
        framing.decode_at(_frame(b"\xff\xfe"), 0)
    with pytest.raises(framing.FramingError, match="not an object"):
        framing.decode_at(_frame(b"[1]"), 0)
    with pytest.raises(framing.FramingError, match="trailing"):
        framing.decode_single(_frame(b"{}") + b"x")


def test_next_valid_record_skips_damage() -> None:
    good = framing.encode({"seq": 2})
    assert framing.next_valid_record(b"junk" + framing.MAGIC + b"broken" + good, 0) == len(
        b"junk" + framing.MAGIC + b"broken"
    )
    assert framing.next_valid_record(b"junk", 0) is None


# -- journal ---------------------------------------------------------------------------------------------


def test_journal_append_and_replay(tmp_path: Path) -> None:
    path = tmp_path / "gen-1.log"
    j = journal.Journal(path, 1, "inst")
    j.append("a", x=1)
    j.append("b")
    replay = journal.read(path)
    assert [r["kind"] for r in replay.records] == ["a", "b"] and replay.anomaly is None
    assert replay.last_seq == 2 and replay.good_end == path.stat().st_size
    replay.keep(1)
    assert len(replay.records) == 1 and replay.good_end == replay.ends[0]
    replay.keep(0)
    assert replay.good_end == 0 and replay.last_seq == 0
    assert journal.read(tmp_path / "missing.log").records == []


def test_tail_and_mid_anomalies(tmp_path: Path) -> None:
    one, two, three = (framing.encode({"seq": n, "kind": "k"}) for n in (1, 2, 3))
    torn = journal.parse(one + two[:20])
    assert torn.anomaly is not None and torn.anomaly.position == "tail" and len(torn.records) == 1
    damaged_mid = journal.parse(one + two[:-6] + b"X" + two[-5:] + three)
    assert damaged_mid.anomaly is not None and damaged_mid.anomaly.position == "mid"
    out_of_order = journal.parse(one + three)
    assert out_of_order.anomaly is not None and out_of_order.anomaly.position == "mid"
    # W-53 / K-26: a complete final record with a bad checksum is an anomaly, never silently dropped
    bad_final = journal.parse(one + two[:-6] + b"X" + two[-5:])
    assert bad_final.anomaly is not None and bad_final.anomaly.reason == "checksum mismatch"


# -- markers ---------------------------------------------------------------------------------------------


def test_marker_publish_read_and_exclusive_final_name(tmp_path: Path) -> None:
    host = FakeHost()
    m = Markers(tmp_path, host, "broker-x")
    m.publish("launch", ("7",), {"group": "g"}, 3)
    marker = m.read("launch", "7")
    assert isinstance(marker, dict) and marker["after_seq"] == 3 and marker["group"] == "g"
    with pytest.raises(MarkerExists):  # W-84: the second publication at the final name is refused
        m.publish("launch", ("7",), {"group": "other"}, 4)
    assert m.read("launch", "7") == marker  # never overwritten
    assert not [p for p in (tmp_path / "effects" / "launch").iterdir() if p.name.startswith(".tmp-")]
    assert m.read("launch", "8") is ABSENT
    assert m.names("launch") == ["7"] and m.names("render") == []


def test_unreadable_marker_is_present_unknown(tmp_path: Path) -> None:
    m = Markers(tmp_path, FakeHost(), "broker-x")
    m.publish("policy", ("1",), {"policy": {}}, 0)
    path = tmp_path / "effects" / "policy" / "1"
    path.write_bytes(path.read_bytes()[:-3])  # W-83: corrupted content
    assert isinstance(m.read("policy", "1"), Unreadable)


def test_n001_published_before_the_call_returns(tmp_path: Path) -> None:
    """N001: a rename can publish the final name and then fail to return; recovery reads the final name."""

    class LateHost(FakeHost):
        def publish(self, temp: Path, final: Path) -> None:
            os.rename(temp, final)
            raise OSError("interrupted after the rename")

    m = Markers(tmp_path, LateHost(), "broker-x")
    with pytest.raises(OSError, match="interrupted"):
        m.publish("launch", ("9",), {}, 0)
    assert isinstance(m.read("launch", "9"), dict)  # present: the effect is reserved


def test_marker_identity_rules_and_temporaries(tmp_path: Path) -> None:
    m = Markers(tmp_path, FakeHost(), "broker-x")
    for bad in ("", ".", "..", "a/b", "c:d"):
        with pytest.raises(ValueError):
            m.path("launch", bad)
    with pytest.raises(ValueError):
        m.path("nonsense", "1")
    (tmp_path / "effects" / "launch").mkdir(parents=True)
    (tmp_path / "effects" / "launch" / ".tmp-broker-x-1").write_text("t")
    (tmp_path / "effects" / "launch" / ".tmp-broker-y-1").write_text("t")
    assert m.names("launch") == []
    assert m.remove_own_temporaries("broker-x") == [".tmp-broker-x-1"]
    assert (tmp_path / "effects" / "launch" / ".tmp-broker-y-1").exists()
    assert Markers(tmp_path / "none", FakeHost(), "z").remove_own_temporaries("z") == []


def test_listing_failure_is_never_absence(tmp_path: Path) -> None:
    m = Markers(tmp_path, FakeHost(), "broker-x")
    (tmp_path / "effects").mkdir()
    (tmp_path / "effects" / "launch").write_text("not a folder")
    with pytest.raises(OSError):
        m.names("launch")


# -- containment -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("raw", ["", "\\\\server\\share\\x", "//server/share", "relative\\x", "a/../b"])
def test_containment_refuses_bad_forms(tmp_path: Path, raw: str) -> None:
    with pytest.raises(contain.Contained):
        contain.assert_inside([tmp_path], Path(raw) if raw else Path(""))


def test_containment_drive_relative_and_driveless() -> None:
    assert contain._form_ok("C:foo") == "drive-relative path"
    if os.name == "nt":
        assert contain._form_ok("\\no\\drive") == "no drive"
    assert contain._form_ok(str(Path.cwd())) is None


def test_containment_lexical_and_links(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "a").mkdir(parents=True)
    assert (
        contain.assert_inside([root], root / "a" / "missing" / "deeper") == root / "a" / "missing" / "deeper"
    )
    with pytest.raises(contain.Contained, match="outside"):
        contain.assert_inside([root], tmp_path / "elsewhere")
    with pytest.raises(contain.Contained, match="outside"):
        contain.assert_inside([root], root)  # the root itself is not strictly below the root
    outside = tmp_path / "outside"
    outside.mkdir()
    link = root / "link"
    _make_dir_link(link, outside)
    with pytest.raises(contain.Contained, match="link or reparse"):
        contain.assert_inside([root], link / "x")


def test_containment_inspection_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "root"
    root.mkdir()

    def denied(path: object) -> object:
        raise PermissionError("denied")

    monkeypatch.setattr(contain.os, "lstat", denied)
    with pytest.raises(contain.Contained, match="cannot inspect"):
        contain.assert_inside([root], root / "x")


def _make_dir_link(link: Path, target: Path) -> None:
    if os.name == "nt":
        import subprocess

        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True)
    else:
        os.symlink(target, link, target_is_directory=True)


# -- walk ------------------------------------------------------------------------------------------------


def test_walk_never_follows_a_link_and_removes_only_the_link(tmp_path: Path) -> None:
    root = tmp_path / "copy"
    (root / "d").mkdir(parents=True)
    (root / "d" / "f.txt").write_text("x")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "precious.txt").write_text("keep")
    _make_dir_link(root / "j", outside)  # W-31: a nested outward junction
    listed = [e.path.relative_to(root).as_posix() for e in walk.entries(root)]
    assert "j/precious.txt" not in listed and "j" in listed
    bottom_up = [e.path.relative_to(root).as_posix() for e in walk.entries(root, bottom_up=True)]
    assert bottom_up.index("d/f.txt") < bottom_up.index("d")
    assert [p.name for p in walk.files(root)] == ["f.txt"]
    from minion_process.hostqueue import fsops

    for entry in walk.entries(root, bottom_up=True):
        if entry.is_dir or entry.link_is_dir:
            fsops.rmdir([tmp_path], entry.path)
        else:
            fsops.unlink([tmp_path], entry.path)
    assert not os.listdir(root) and (outside / "precious.txt").read_text() == "keep"


def test_walk_failure_propagates(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        list(walk.entries(tmp_path / "missing"))


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file symlink semantics")
def test_walk_removes_a_file_symlink(tmp_path: Path) -> None:  # pragma: no cover - POSIX only
    (tmp_path / "t").write_text("x")
    os.symlink(tmp_path / "t", tmp_path / "s")
    from minion_process.hostqueue import fsops

    fsops.unlink([tmp_path], tmp_path / "s")
    assert (tmp_path / "t").exists() and not os.path.lexists(tmp_path / "s")
