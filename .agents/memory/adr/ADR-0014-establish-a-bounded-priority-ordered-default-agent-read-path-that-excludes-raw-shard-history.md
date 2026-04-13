# ADR-0014 Establish a bounded priority-ordered default agent read path that excludes raw shard history

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

Purpose: Establish a bounded priority-ordered default agent read path that excludes raw shard history
Derived from: [2026-04-13T21-57-06Z--dave-thomas--adr-inspector](../daily/2026-04-13/events/2026-04-13T21-57-06Z--dave-thomas--adr-inspector.md)

## Context

Agents must arrive at a task with relevant shared memory context, but reading every individual event shard at session start is too expensive and grows unboundedly as the repo accumulates history. A priority-ordered, bounded read path solves both problems: agents get the right signal (AGENTS.md → ADR index → must-read ADRs → recent summaries → catch-up digest) without scanning raw shard history.
The ordering also encodes relative authority: AGENTS.md governs behavior, ADRs govern durable decisions, daily summaries give recent operational context, and the catch-up digest covers what changed since the last sync. Each layer is more volatile than the last, and each is bounded in size by its own generation rules.

## Decision

The default agent read path is established as six items, consumed in priority order:
1. `AGENTS.md`
2. `.agents/memory/adr/INDEX.md`
3. Must-read ADR files (`Must read: true`)
4. Today's `summary.md`
5. Yesterday's `summary.md`
6. `.codex/local/catchup.md` (if present)
Raw event shards are explicitly excluded from the task-start read path. Agents read individual shards only when they need detail beyond what summaries provide.

## Consequences

- Ensure `session-start.py` exactly implements this priority order rather than loading an ad hoc subset.
- Validate that "must-read ADR files" is bounded — if the ADR count grows large, must-read tagging must remain selective.
- Consider whether two days of summaries is always sufficient or whether a parameter for recency window is needed.

## Source memory events

- [2026-04-13T21-57-06Z--dave-thomas--adr-inspector](../daily/2026-04-13/events/2026-04-13T21-57-06Z--dave-thomas--adr-inspector.md)

## Related code paths

- docs/shared-repo-memory-system-design.md
