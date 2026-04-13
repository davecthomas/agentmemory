---
timestamp: "2026-04-13T21:53:13Z"
author: "dave-thomas"
branch: "codex/6-runtime-log-identity-cleanup"
thread_id: "adr-inspector"
turn_id: "adr-inspector-0001"
decision_candidate: true
enriched: true
ai_generated: true
ai_model: "claude-sonnet-4-5"
ai_tool: "claude"
ai_surface: "claude-code"
ai_executor: "adr-inspector"
workstream_id: "adr-inspector"
workstream_scope: "branch"
checkpoint_goal: "Identify and promote ADR-worthy architectural decisions from the system design doc."
checkpoint_surface: "docs/shared-repo-memory-system-design.md"
checkpoint_outcome: "Decision candidate: two-phase capture/publication pipeline."
files_touched:
  - "docs/shared-repo-memory-system-design.md"
design_docs_touched:
  - "docs/shared-repo-memory-system-design.md"
verification:
  - "docs/shared-repo-memory-system-design.md §Core Principles: 'Raw capture and publication are separate phases.'"
  - "docs/shared-repo-memory-system-design.md §Glossary: 'pending capture', 'episode cluster', 'checkpoint' defined as distinct concepts."
  - "docs/shared-repo-memory-system-design.md §Post-Turn Capture: publish pipeline steps 1–6 describe the two-phase boundary explicitly."
---

## Why

The system must prevent raw, mechanical, single-turn data from becoming durable shared memory. A single agent turn produces an incomplete picture of the workstream; directly publishing it would fill the memory layer with noisy, context-poor entries that mislead future agents. By separating raw capture (always local-only) from durable publication (synthesized from a bounded episode cluster after trust validation), the system ensures that durable memory reflects coherent workstream intent rather than individual turn artifacts.

## What changed

Established a two-phase capture/publication pipeline as a core architectural invariant:
- Phase 1 — **Pending capture**: after every file-changing turn, `post-turn-notify.py` writes a local-only shard under `.agents/memory/pending/`. This file must never be committed.
- Phase 2 — **Checkpoint publication**: a background `memory-checkpointer` subagent evaluates the active episode cluster (a bounded set of semantically related pending captures), applies trust and privacy validation, and calls `publish-checkpoint.py` only when the cluster passes. The published shard lands under `.agents/memory/daily/<date>/events/`.
- The `.githooks/pre-commit` hook enforces the boundary by rejecting staged pending captures and any daily event shard marked `enriched: false`.

## Evidence

- `docs/shared-repo-memory-system-design.md` §Core Principles: "Raw capture and publication are separate phases. Each file-changing turn may produce one pending local-only capture. Durable shared memory is synthesized later from an episode cluster, not written directly from a single turn."
- Glossary entries for `pending capture`, `episode cluster`, and `checkpoint` define three distinct concepts at separate abstraction levels.
- Post-Turn Capture §After capture (steps 1–6) documents the full pipeline from pending write → checkpoint evaluation → validation → publish → summary rebuild → pre-commit guard.

## Next

- Ensure pre-commit hook logic is tested against staging scenarios where pending shards accidentally land in the index.
- Review whether the `enriched: false` guard is redundant with the pending-path guard, or whether both are load-bearing.
