# WP-13-3-NEIGHBOURHOOD — a fix moved a join inside the timeout window (WP-13.3)

**Supports:** `WORKFLOW.md` §9.4 (re-check the neighbourhood after every fix).
**Source:** `agent-workflow.md` §9.4 at `dd9fd15`, verbatim.

> WP-13.3 shows the cost of skipping this. Its `WP133-I002` fix (joining full-output persistence at settlement) moved that join inside the timeout window. That produced `WP133-I003`, a settled success misreported as a timeout, which the timer and abort ordering neighbourhood would have caught.
