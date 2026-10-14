"""Record framing for the journal and the effect markers (K-13, K-25, K-26).

One record is a single line of ASCII framing around a UTF-8 JSON payload:

    MPQ1 <length: 8 hex> <sha256 of payload: 64 hex> <payload> END\\n

The length counts payload bytes. `END\\n` is the commit marker, written in the same write as the rest of the
record. Decoding never guesses: anything that does not match exactly is an *anomaly*, and the reader reports
where it is. Classifying the anomaly (tail or mid-journal) and deciding what it means is the caller's job.
No anomaly is ever presumed to be an uncommitted append (K-26).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

MAGIC = b"MPQ1 "
COMMIT = b" END\n"
_HEADER_LEN = len(MAGIC) + 8 + 1 + 64 + 1  # magic, length, space, checksum, space


class FramingError(ValueError):
    """A record could not be decoded exactly; `reason` names the first mismatch."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def encode(payload: dict[str, Any]) -> bytes:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    digest = hashlib.sha256(body).hexdigest().encode("ascii")
    return MAGIC + f"{len(body):08x}".encode("ascii") + b" " + digest + b" " + body + COMMIT


@dataclass(frozen=True)
class Decoded:
    payload: dict[str, Any]
    end: int  # offset just past this record


def decode_at(data: bytes, offset: int) -> Decoded:
    """Decode exactly one record starting at `offset`, or raise `FramingError`."""
    head = data[offset : offset + _HEADER_LEN]
    if len(head) < _HEADER_LEN:
        raise FramingError("short header")
    if not head.startswith(MAGIC):
        raise FramingError("bad magic")
    length_text = head[len(MAGIC) : len(MAGIC) + 8]
    if head[len(MAGIC) + 8 : len(MAGIC) + 9] != b" " or head[-1:] != b" ":
        raise FramingError("bad separators")
    try:
        length = int(length_text.decode("ascii"), 16)
    except (UnicodeDecodeError, ValueError):
        raise FramingError("bad length") from None
    digest = head[len(MAGIC) + 9 : len(MAGIC) + 9 + 64]
    body_start = offset + _HEADER_LEN
    body = data[body_start : body_start + length]
    if len(body) < length:
        raise FramingError("length beyond end of data")
    commit = data[body_start + length : body_start + length + len(COMMIT)]
    if commit != COMMIT:
        raise FramingError("missing or damaged commit marker")
    if hashlib.sha256(body).hexdigest().encode("ascii") != digest:
        raise FramingError("checksum mismatch")
    try:
        payload = json.loads(body.decode("ascii"))
    except (UnicodeDecodeError, ValueError):
        raise FramingError("payload is not JSON") from None
    if not isinstance(payload, dict):
        raise FramingError("payload is not an object")
    return Decoded(payload, body_start + length + len(COMMIT))


def decode_single(data: bytes) -> dict[str, Any]:
    """A marker file holds exactly one record and nothing else."""
    decoded = decode_at(data, 0)
    if decoded.end != len(data):
        raise FramingError("trailing bytes after the record")
    return decoded.payload


def next_valid_record(data: bytes, start: int) -> int | None:
    """The offset of the next position after `start` where a complete, valid record decodes, if any.

    Used only to classify an anomaly as mid-journal: valid data after damage means the damage is not at
    the tail."""
    position = data.find(MAGIC, start + 1)
    while position != -1:
        try:
            decode_at(data, position)
        except FramingError:
            position = data.find(MAGIC, position + 1)
            continue
        return position
    return None
