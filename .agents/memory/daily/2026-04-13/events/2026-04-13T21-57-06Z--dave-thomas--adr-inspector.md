---
timestamp: "2026-04-13T21:57:06Z"
author: "dave-thomas"
branch: "main"
thread_id: "adr-inspector"
turn_id: "adr-inspector-readpath"
decision_candidate: true
enriched: true
ai_generated: true
ai_model: "claude-sonnet-4-6"
ai_tool: "claude"
ai_surface: "claude-code"
ai_executor: "adr-inspector"
workstream_id: "adr-inspector"
workstream_scope: "branch"
checkpoint_goal: "Identify and promote ADR-worthy architectural decisions from the system design doc."
checkpoint_surface: "docs/shared-repo-memory-system-design.md"
checkpoint_outcome: "Decision candidate: bounded priority-ordered default agent read path that excludes raw shard history."
files_touched:
  - "docs/shared-repo-memory-system-design.md"
design_docs_touched:
  - "docs/shared-repo-memory-system-design.md"
verification:
  - "docs/shared-repo-memory-system-design.md §Default Agent Read Path: six-item priority-ordered list followed by 'This path is bounded — agents do not scan raw shard history at task start.'"
  - "docs/shared-repo-memory-system-design.md §Daily Summary: sections capped at max 10 items enforcing bounded read model."
  - "ADR-0003: 'Agents read summaries for cheap context; they read individual shards only when they need detail.'"
---

## Why

Agents must arrive at a task with relevant shared memory context, but reading every individual event shard at session start is too expensive and grows unboundedly as the repo accumulates history. A priority-ordered, bounded read path solves both problems: agents get the right signal (AGENTS.md → ADR index → must-read ADRs → recent summaries → catch-up digest) without scanning raw shard history.

The ordering also encodes relative authority: AGENTS.md governs behavior, ADRs govern durable decisions, daily summaries give recent operational context, and the catch-up digest covers what changed since the last sync. Each layer is more volatile than the last, and each is bounded in size by its own generation rules.

## What changed

The default agent read path is established as six items, consumed in priority order:
1. `AGENTS.md`
2. `.agents/memory/adr/INDEX.md`
3. Must-read ADR files (`Must read: true`)
4. Today's `summary.md`
5. Yesterday's `summary.md`
6. `.codex/local/catchup.md` (if present)

Raw event shards are explicitly excluded from the task-start read path. Agents read individual shards only when they need detail beyond what summaries provide.

## Evidence

- `docs/shared-repo-memory-system-design.md` §Default Agent Read Path: "In priority order: AGENTS.md, ADR INDEX.md, Must-read ADR files, Today's summary.md, Yesterday's summary.md, .codex/local/catchup.md." Followed by: "This path is bounded — agents do not scan raw shard history at task start."
- `docs/shared-repo-memory-system-design.md` §Daily Summary: describes summaries as the cheap read path with bounded sections (max 10 per section).
- ADR-0003: "Agents read summaries for cheap context; they read individual shards only when they need detail."

## Next

- Ensure `session-start.py` exactly implements this priority order rather than loading an ad hoc subset.
- Validate that "must-read ADR files" is bounded — if the ADR count grows large, must-read tagging must remain selective.
- Consider whether two days of summaries is always sufficient or whether a parameter for recency window is needed.
