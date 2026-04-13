---
timestamp: "2026-04-13T21:55:27Z"
author: "dave-thomas"
branch: "main"
thread_id: "adr-inspector"
turn_id: "adr-inspector"
decision_candidate: true
enriched: true
ai_generated: true
ai_model: "claude-sonnet-4-6"
ai_tool: "claude"
ai_surface: "claude-code"
ai_executor: "adr-inspector"
workstream_id: "adr-inspector"
workstream_scope: "branch"
checkpoint_goal: "Capture the architectural decision to use a deterministic local episode graph for pending-capture clustering."
checkpoint_surface: "Shared repo-memory episode clustering and checkpoint publication pipeline."
checkpoint_outcome: "Decision candidate promoted; ADR created."
files_touched:
  - "docs/shared-repo-memory-system-design.md"
design_docs_touched:
  - "docs/shared-repo-memory-system-design.md"
verification:
  - "docs/shared-repo-memory-system-design.md — Glossary: 'episode cluster: A bounded, semantically related collection of pending captures selected by the local episode graph…'"
  - "docs/shared-repo-memory-system-design.md — File layout shows state/episode-graph/episodes/ and state/checkpoint-context/ as new local-only subtrees."
  - "Commit f2a84c0: 'Replaces the old same-thread-or-branch bundle heuristic with a bounded local episode graph so checkpoint publication is driven by stronger repo-grounded associations.'"
---

## Why

The old checkpoint clustering mechanism grouped pending captures by thread ID or branch — a heuristic that could bundle unrelated work done on the same thread, or fragment related work done across threads. A deterministic local episode graph addresses this by building explicit associations from repo-grounded signals: shared file paths, adjacent timestamps, and matching workstream IDs. Clustering from graph traversal produces episode boundaries that reflect actual semantic relationships rather than incidental provenance metadata. Persisting per-episode manifests under `.agents/memory/state/episode-graph/episodes/` makes the clustering logic locally inspectable without requiring a graph library or external service.

## What changed

- The `.agents/memory/state/` subtree was added to hold local-only derived episode state: `state/episode-graph/episodes/` for per-episode manifests and `state/checkpoint-context/` for active episode cluster evaluator inputs.
- The glossary term "workstream episode" was renamed to "episode cluster" and its definition updated to specify it is "selected by the local episode graph."
- Checkpoint context manifests were moved from `.agents/memory/logs/checkpoint-context/` to `.agents/memory/state/checkpoint-context/`.
- The state subtrees are treated as local-only: added to `.gitignore` and ignored by the `pre-commit` guard.

## Evidence

- `docs/shared-repo-memory-system-design.md`, Glossary: "episode cluster: A bounded, semantically related collection of pending captures selected by the local episode graph and evaluated together so the system can infer the broader effort."
- `docs/shared-repo-memory-system-design.md`, File layout: new `state/checkpoint-context/` (local-only evaluator inputs) and `state/episode-graph/episodes/` (derived local episode manifests).
- Commit f2a84c0 message: "Replaces the old same-thread-or-branch bundle heuristic with a bounded local episode graph so checkpoint publication is driven by stronger repo-grounded associations."

## Next

- Validate that episode graph edge-building produces stable cluster boundaries across multi-threaded parallel agent sessions.
- Review whether the episode manifest format should be versioned to allow safe schema evolution.
