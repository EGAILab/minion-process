# L0506-D004-STATUS-SYNC — a closure without its status sync (`minion-agent#131`)

**Supports:** `WORKFLOW.md` §11.1.3 (`CLOSED` requires the status sync merged first).
**Source:** `agent-workflow.md` §11.1.3 at `dd9fd15`, verbatim.

> For a work package whose disposition certifies requirements, `CLOSED` requires its **status sync** to be merged first. That is the manifest rows and spec status lines that record the certification (for example `CERTIFIED_CLOSED`). A closure without it leaves the durable record contradicting the issue: L0506-D004 (`minion-agent#131`) closed cross-language while `TOOL-042` still read `CONTRACT_DRAFT`, until `#156` / docs `#252`. A mechanical check that the work package's rows read `CERTIFIED_CLOSED` is a candidate `minion_process` guard (§12.7).
