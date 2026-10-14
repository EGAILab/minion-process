"""The append-only state journal (B-4, K-13, K-25 to K-28).

The broker is the only writer. Each transition is one framed record carrying a gap-free sequence number
and the writing broker's instance id. A record is written in one call and flushed to disk before the
broker acts on it. Replay never discards an anomaly silently: it stops at the first one and reports its
offset, its reason and whether any valid record follows it (mid-journal) or not (tail).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import fsops
from .framing import FramingError, decode_at, encode, next_valid_record


@dataclass(frozen=True)
class Anomaly:
    offset: int
    reason: str
    position: str  # "tail" | "mid"


@dataclass
class Replay:
    records: list[dict[str, Any]] = field(default_factory=list)
    anomaly: Anomaly | None = None
    good_end: int = 0  # offset just past the last good record
    ends: list[int] = field(default_factory=list)  # end offset of each record, for truncating at an invariant

    def keep(self, count: int) -> None:
        """Keep only the first `count` records (an invariant failed at record `count`)."""
        self.records = self.records[:count]
        self.ends = self.ends[:count]
        self.good_end = self.ends[-1] if self.ends else 0

    @property
    def last_seq(self) -> int:
        return int(self.records[-1]["seq"]) if self.records else 0


def read(path: Path) -> Replay:
    """Replay the journal file. A missing file is an empty journal; any other read failure propagates
    (inspection failure is never treated as absence, K-36)."""
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return Replay()
    return parse(data)


def parse(data: bytes) -> Replay:
    replay = Replay()
    offset = 0
    expected_seq = 1
    while offset < len(data):
        try:
            decoded = decode_at(data, offset)
        except FramingError as exc:
            position = "mid" if next_valid_record(data, offset) is not None else "tail"
            replay.anomaly = Anomaly(offset, exc.reason, position)
            return replay
        seq = decoded.payload.get("seq")
        if seq != expected_seq:
            # A well-framed record out of sequence is corruption, not a torn append: always mid-journal.
            replay.anomaly = Anomaly(offset, f"sequence {seq!r}, expected {expected_seq}", "mid")
            return replay
        replay.records.append(decoded.payload)
        replay.ends.append(decoded.end)
        replay.good_end = decoded.end
        offset = decoded.end
        expected_seq += 1
    return replay


class Journal:
    """Appends to a journal whose current content has replayed without an anomaly."""

    def __init__(self, path: Path, next_seq: int, instance: str, roots: list[Path] | None = None) -> None:
        self.path = path
        self.next_seq = next_seq
        self.instance = instance
        self.roots = roots if roots is not None else [path.parent.parent]

    def append(self, kind: str, **fields: Any) -> dict[str, Any]:
        record = {"seq": self.next_seq, "instance": self.instance, "kind": kind, **fields}
        fsops.append(self.roots, self.path, encode(record))
        self.next_seq += 1
        return record
