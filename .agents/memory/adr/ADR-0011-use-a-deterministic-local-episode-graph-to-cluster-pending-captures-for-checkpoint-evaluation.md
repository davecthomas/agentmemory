# ADR-0011 Use a deterministic local episode graph to cluster pending captures for checkpoint evaluation

Status: accepted
Date: 2026-04-13
Owners: dave-thomas
Must read: true
Supersedes: 
Superseded by: 
ai-generated: True
ai-model: claude-sonnet-4-6
ai-tool: claude
ai-surface: claude-code
ai-executor: adr-inspector

Purpose: Use a deterministic local episode graph to cluster pending captures for checkpoint evaluation
Derived from: [2026-04-13T21-55-27Z--dave-thomas--adr-inspector](../daily/2026-04-13/events/2026-04-13T21-55-27Z--dave-thomas--adr-inspector.md)

## Context

The old checkpoint clustering mechanism grouped pending captures by thread ID or branch — a heuristic that could bundle unrelated work done on the same thread, or fragment related work done across threads. A deterministic local episode graph addresses this by building explicit associations from repo-grounded signals: shared file paths, adjacent timestamps, and matching workstream IDs. Clustering from graph traversal produces episode boundaries that reflect actual semantic relationships rather than incidental provenance metadata. Persisting per-episode manifests under `.agents/memory/state/episode-graph/episodes/` makes the clustering logic locally inspectable without requiring a graph library or external service.

## Decision

- The `.agents/memory/state/` subtree was added to hold local-only derived episode state: `state/episode-graph/episodes/` for per-episode manifests and `state/checkpoint-context/` for active episode cluster evaluator inputs.
- The glossary term "workstream episode" was renamed to "episode cluster" and its definition updated to specify it is "selected by the local episode graph."
- Checkpoint context manifests were moved from `.agents/memory/logs/checkpoint-context/` to `.agents/memory/state/checkpoint-context/`.
- The state subtrees are treated as local-only: added to `.gitignore` and ignored by the `pre-commit` guard.

## Consequences

- Validate that episode graph edge-building produces stable cluster boundaries across multi-threaded parallel agent sessions.
- Review whether the episode manifest format should be versioned to allow safe schema evolution.

## Source memory events

- [2026-04-13T21-55-27Z--dave-thomas--adr-inspector](../daily/2026-04-13/events/2026-04-13T21-55-27Z--dave-thomas--adr-inspector.md)

## Related code paths

- docs/shared-repo-memory-system-design.md
