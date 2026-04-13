---
timestamp: "2026-04-13T21:58:06Z"
author: "dave-thomas"
branch: "main"
thread_id: "adr-inspector"
turn_id: "bounded-read-path"
decision_candidate: true
enriched: true
ai_generated: true
ai_model: "claude-sonnet-4-6"
ai_tool: "claude"
ai_surface: "claude-code"
ai_executor: "adr-inspector"
workstream_id: "adr-inspector"
workstream_scope: "thread"
checkpoint_goal: "Identify and promote ADR-worthy decisions from the shared-repo-memory system design doc."
checkpoint_surface: "docs/shared-repo-memory-system-design.md — Default Agent Read Path at Task Start section."
checkpoint_outcome: "Decision candidate: bounded prioritized read set defines the canonical agent context budget at session start."
related_adrs:
  - "ADR-0001"
  - "ADR-0003"
files_touched:
  - "docs/shared-repo-memory-system-design.md"
design_docs_touched:
  - "docs/shared-repo-memory-system-design.md"
verification:
  - "Design doc section 'Default Agent Read Path at Task Start': ordered six-item priority list from AGENTS.md through catchup.md."
  - "Design doc section 'SessionStart Hook': additionalContext = 'ADR index + recent daily summaries'; explicitly bounded."
  - "Design doc Core Principle: 'This path is bounded — agents do not scan raw shard history at task start.'"
---

## Why

Without an explicit context budget, agents at session start could read arbitrary amounts of history — raw shard files, full commit logs, every ADR ever written — leading to bloated context, stale reasoning, or inconsistent behavior across sessions. An ordered, bounded read set establishes a predictable and enforceable contract: every agent session starts from the same curated context, prioritizing durable decisions (ADRs) over recent summaries over local state. The priority order is architecturally load-bearing: it ensures ADRs override any conflicting summary content, and that the agent sees decisions before operational history.

## What changed

- Established the canonical six-item ordered read path: `AGENTS.md` → ADR `INDEX.md` → must-read ADRs → today's `summary.md` → yesterday's `summary.md` → `.codex/local/catchup.md`.
- `session-start.py` injects exactly this set as `additionalContext` in the `hookSpecificOutput` response, and no more.
- `post-compact.py` re-injects the same bounded set after Claude Code compaction (see ADR-0012).
- Raw shard history is explicitly excluded from this path.

## Evidence

- Design doc "Default Agent Read Path at Task Start" section lists the exact priority order and ends with the invariant: "This path is bounded — agents do not scan raw shard history at task start."
- Design doc "SessionStart Hook" describes the `additionalContext` field as "ADR index + recent daily summaries" — matching the bounded set.
- Design doc "PostCompact Hook" confirms the same bounded set is re-injected after compaction.

## Next

- Document the rationale for "three most recent daily summaries" as the summary window — why three and not two or five.
- Evaluate whether the bounded path should include a `---today+2---` summary when sessions run past midnight.
