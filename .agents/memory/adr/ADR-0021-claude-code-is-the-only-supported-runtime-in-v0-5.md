---
id: "ADR-0021"
title: "Claude Code is the only supported runtime in v0.5"
status: "accepted"
date: "2026-09-05"
tags: "scripts"
must_read: true
supersedes: "ADR-0006"
superseded_by: ""
---

# ADR-0021: Claude Code is the only supported runtime in v0.5

## Context

v0.4 carried adapters for Claude Code, Gemini CLI, and Codex, plus runtime detection by payload, process ancestry, and environment. Codex never had a post-turn hook; the adapters, installer branches, and their tests were roughly 3,000 lines that the content model had not yet earned.

## Decision

Only Claude Code is wired: `SessionStart` and `PostCompact` in `~/.claude/settings.json`, skills symlinked into `~/.claude/skills/`. Scripts still install under the agent-neutral `~/.agent/` paths (ADR-0002) so another runtime can be added when the memory model has proven itself through the evals.

## Alternatives

Keep Gemini support since it had a working post-turn hook: rejected because v0.5 has no post-turn hook at all, so the adapter would exist only for SessionStart.

## Consequences

Gemini and Codex users get no hooks until an adapter returns. The `.codex/memory` symlink and `.codex/local/` are no longer created.

## Sources

- docs/v0.5-decision-memory-plan.md
- PR #15
