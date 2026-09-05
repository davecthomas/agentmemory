---
id: "ADR-0022"
title: "Session context is one budgeted block: index, must-read decisions, recent notes, catch-up"
status: "accepted"
date: "2026-09-05"
tags: "scripts"
must_read: true
supersedes: "ADR-0017"
superseded_by: ""
---

# ADR-0022: Session context is one budgeted block: index, must-read decisions, recent notes, catch-up

## Context

ADR-0017 described a six-item read path that `session-start.py` never implemented; the code injected the ADR index and three daily summaries. The summaries repeated one paragraph under four headings and carried a fixed bug forward as an active blocker.

## Decision

`build_memory_context()` in `common.py` is the single source for what an agent is given, at SessionStart, after PostCompact, and in the evals. Order: ADR `INDEX.md`, the Decision section of every `must_read: true` ADR newest first, notes from the last `notes_window_days`, then `local/catchup.md`. Blocks are dropped once `context_budget_words` (default 2,500) is reached and a trailing line names what was omitted. Anything omitted is reachable through the `memory` skill (`memory-query.py`).

## Alternatives

Inject whole must-read ADRs: rejected because Context and Consequences double the size for little steering value; the Decision is what must be obeyed. Keep daily summaries: rejected because git log already lists activity and the summaries were fabricating sections.

## Consequences

`check_memory.py` fails a commit whose must-read set no longer fits the budget, forcing a choice between raising the budget and demoting an ADR.

## Sources

- docs/v0.5-decision-memory-plan.md § Session-start context
- PR #15
