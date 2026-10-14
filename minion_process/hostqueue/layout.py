"""Folder layout of the queue state (B-30) and the generation rule (K-33).

    <queue>/
        effects/<kind>/...       write-ahead effect markers (`markers.py`)
        journal/gen-<n>.log      one journal per generation; repair writes the next generation
        inbox/<request-id>.req   client requests, one immutable file each (B-3)
        outbox/<request-id>.res  broker responses
        rejected/<request-id>    malformed requests, kept with the reason
        quarantine/<time>/       original bytes kept by recovery and repair
        jobs/<job-id>/           runner input, result file; logs live in the project (B-31)

The current journal generation is the highest generation marker `effects/generation/<n>` that reads back
intact (K-33). An unreadable highest marker means the current generation is unknown, and the broker stays
in repair.
"""

from __future__ import annotations

from pathlib import Path

from . import fsops

INBOX = "inbox"
OUTBOX = "outbox"
REJECTED = "rejected"
QUARANTINE = "quarantine"
JOURNAL = "journal"
JOBS = "jobs"


def journal_path(root: Path, generation: int) -> Path:
    return root / JOURNAL / f"gen-{generation}.log"


def ensure(root: Path) -> None:
    for name in (INBOX, OUTBOX, REJECTED, QUARANTINE, JOURNAL, JOBS, "effects"):
        fsops.mkdir([root.parent], root / name)  # the queue folder itself is proved from its parent
