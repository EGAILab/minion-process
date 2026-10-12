# WP-13-3-TIMING — fixed sleeps flaked under load and masked a negative control (WP-13.3, L12-D002)

**Supports:** `WORKFLOW.md` §9.6 (event-driven witnesses).
**Source:** `agent-workflow.md` §9.6 at `dd9fd15`, verbatim.

> In WP-13.3, two settlement witnesses that slept a fixed time flaked under load, and one flake masked a negative control's real killer. Both became event-driven: the parent exits only once its descendant is running. The L12-D002 Rust witnesses used stdin handshakes from the start.
