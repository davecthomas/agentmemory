---
id: "ADR-0012"
title: "Re-inject bounded memory context after PostCompact to preserve session memory invariant"
status: "accepted"
date: "2026-04-13"
tags: "docs"
must_read: false
supersedes: ""
superseded_by: ""
---

# ADR-0012: Re-inject bounded memory context after PostCompact to preserve session memory invariant

## Context

Claude Code's compaction (context window summarization) discards the full transcript, including the ADR index and daily summaries injected by the `SessionStart` hook. Without a recovery mechanism, the agent loses awareness of past decisions and recent work for the remainder of the session — exactly the context that `SessionStart` was designed to provide. The `PostCompact` hook re-injects the same bounded read set so the memory system's core invariant holds even after mid-session compaction: every agent turn, whenever it occurs in a session, starts from prior decisions rather than rebuilding history from scratch.

## Decision

- `post-compact.py` was added as a hook script and wired to Claude Code's `PostCompact` event in `~/.claude/settings.json`.
- On firing, it re-injects the same bounded read set as `SessionStart`: ADR index + three most recent daily summaries.
- Gemini CLI explicitly has no equivalent — its `PreCompress` event fires before compression and is advisory only, so no equivalent recovery hook is wired for Gemini sessions.

## Alternatives

Rely on Claude Code's compaction summary to preserve the injected memory: rejected because the summary is lossy and does not know which lines are load-bearing. Re-read memory only on demand through a skill: rejected because the invariant is that every turn starts from prior decisions without being asked.

## Consequences

- When Gemini CLI exposes a post-compaction hook with read access to the session, wire the same re-injection pattern.
- Verify that PostCompact re-injection correctly handles newly bootstrapped repos where no daily summaries yet exist.

## Sources

- Memory event 2026-04-13T21-55-28Z--dave-thomas--adr-inspector (v0.4 event shard; removed in v0.5)
- Code path: docs/shared-repo-memory-system-design.md
- Written by adr-inspector (claude-sonnet-4-6) on 2026-04-13
