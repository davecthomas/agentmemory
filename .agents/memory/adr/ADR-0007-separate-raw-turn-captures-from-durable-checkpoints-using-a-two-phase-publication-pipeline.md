# ADR-0007 Separate raw turn captures from durable checkpoints using a two-phase publication pipeline

Status: accepted
Date: 2026-04-13
Owners: dave-thomas
Must read: true
Supersedes: 
Superseded by: 
ai-generated: True
ai-model: claude-sonnet-4-5
ai-tool: claude
ai-surface: claude-code
ai-executor: adr-inspector

Purpose: Separate raw turn captures from durable checkpoints using a two-phase publication pipeline
Derived from: [2026-04-13T21-53-13Z--dave-thomas--adr-inspector](../daily/2026-04-13/events/2026-04-13T21-53-13Z--dave-thomas--adr-inspector.md)

## Context

The system must prevent raw, mechanical, single-turn data from becoming durable shared memory. A single agent turn produces an incomplete picture of the workstream; directly publishing it would fill the memory layer with noisy, context-poor entries that mislead future agents. By separating raw capture (always local-only) from durable publication (synthesized from a bounded episode cluster after trust validation), the system ensures that durable memory reflects coherent workstream intent rather than individual turn artifacts.

## Decision

Established a two-phase capture/publication pipeline as a core architectural invariant:
- Phase 1 — **Pending capture**: after every file-changing turn, `post-turn-notify.py` writes a local-only shard under `.agents/memory/pending/`. This file must never be committed.
- Phase 2 — **Checkpoint publication**: a background `memory-checkpointer` subagent evaluates the active episode cluster (a bounded set of semantically related pending captures), applies trust and privacy validation, and calls `publish-checkpoint.py` only when the cluster passes. The published shard lands under `.agents/memory/daily/<date>/events/`.
- The `.githooks/pre-commit` hook enforces the boundary by rejecting staged pending captures and any daily event shard marked `enriched: false`.

## Consequences

- Ensure pre-commit hook logic is tested against staging scenarios where pending shards accidentally land in the index.
- Review whether the `enriched: false` guard is redundant with the pending-path guard, or whether both are load-bearing.

## Source memory events

- [2026-04-13T21-53-13Z--dave-thomas--adr-inspector](../daily/2026-04-13/events/2026-04-13T21-53-13Z--dave-thomas--adr-inspector.md)

## Related code paths

- docs/shared-repo-memory-system-design.md
