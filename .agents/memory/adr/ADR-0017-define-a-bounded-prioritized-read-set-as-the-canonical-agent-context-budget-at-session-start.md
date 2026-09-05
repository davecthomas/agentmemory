---
id: "ADR-0017"
title: "Define a bounded prioritized read set as the canonical agent context budget at session start"
status: "superseded"
date: "2026-04-13"
tags: "docs"
must_read: false
supersedes: ""
superseded_by: "ADR-0022"
---

# ADR-0017: Define a bounded prioritized read set as the canonical agent context budget at session start

## Context

Without an explicit context budget, agents at session start could read arbitrary amounts of history — raw shard files, full commit logs, every ADR ever written — leading to bloated context, stale reasoning, or inconsistent behavior across sessions. An ordered, bounded read set establishes a predictable and enforceable contract: every agent session starts from the same curated context, prioritizing durable decisions (ADRs) over recent summaries over local state. The priority order is architecturally load-bearing: it ensures ADRs override any conflicting summary content, and that the agent sees decisions before operational history.

## Decision

- Established the canonical six-item ordered read path: `AGENTS.md` → ADR `INDEX.md` → must-read ADRs → today's `summary.md` → yesterday's `summary.md` → `.codex/local/catchup.md`.
- `session-start.py` injects exactly this set as `additionalContext` in the `hookSpecificOutput` response, and no more.
- `post-compact.py` re-injects the same bounded set after Claude Code compaction (see ADR-0012).
- Raw shard history is explicitly excluded from this path.

## Alternatives

None recorded.

## Consequences

- Document the rationale for "three most recent daily summaries" as the summary window — why three and not two or five.
- Evaluate whether the bounded path should include a `---today+2---` summary when sessions run past midnight.

## Sources

- Memory event 2026-04-13T21-58-06Z--dave-thomas--adr-inspector (v0.4 event shard; removed in v0.5)
- Code path: docs/shared-repo-memory-system-design.md
- Written by adr-inspector (claude-sonnet-4-6) on 2026-04-13
