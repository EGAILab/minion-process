# L09-REENTRANT-OBSERVER — a one-language-only extensibility point (Layer 09)

**Supports:** `WORKFLOW.md` §11.8.4 (challenge pass).
**Source:** `agent-workflow.md` §11.8.4 at `dd9fd15`, verbatim.

> Does the defect's own ROOT CAUSE depend on an extensibility point (a synchronous listener hook, a reentrant callback, a mutable shared handle) that one language's own already-certified lower layers expose and the other does not? If so, say which side actually needs the fix and which side may need nothing at all -- a "yes, idiomatically implementable" answer can still hide that the mechanism itself is a one-language-only cost the other language's own architecture never introduced (Layer 09: five Python passes and a convergence cycle defended against a reentrant `on_status_change` observer that had no Rust counterpart, because Rust's own Layer-08 architecture never exposed a synchronous status-observer hook at all -- this was only discovered at Rust-closure time, not during characterization).
