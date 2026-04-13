# ADR-0012 Re-inject bounded memory context after PostCompact to preserve session memory invariant

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

Purpose: Re-inject bounded memory context after PostCompact to preserve session memory invariant
Derived from: [2026-04-13T21-55-28Z--dave-thomas--adr-inspector](../daily/2026-04-13/events/2026-04-13T21-55-28Z--dave-thomas--adr-inspector.md)

## Context

Claude Code's compaction (context window summarization) discards the full transcript, including the ADR index and daily summaries injected by the `SessionStart` hook. Without a recovery mechanism, the agent loses awareness of past decisions and recent work for the remainder of the session — exactly the context that `SessionStart` was designed to provide. The `PostCompact` hook re-injects the same bounded read set so the memory system's core invariant holds even after mid-session compaction: every agent turn, whenever it occurs in a session, starts from prior decisions rather than rebuilding history from scratch.

## Decision

- `post-compact.py` was added as a hook script and wired to Claude Code's `PostCompact` event in `~/.claude/settings.json`.
- On firing, it re-injects the same bounded read set as `SessionStart`: ADR index + three most recent daily summaries.
- Gemini CLI explicitly has no equivalent — its `PreCompress` event fires before compression and is advisory only, so no equivalent recovery hook is wired for Gemini sessions.

## Consequences

- When Gemini CLI exposes a post-compaction hook with read access to the session, wire the same re-injection pattern.
- Verify that PostCompact re-injection correctly handles newly bootstrapped repos where no daily summaries yet exist.

## Source memory events

- [2026-04-13T21-55-28Z--dave-thomas--adr-inspector](../daily/2026-04-13/events/2026-04-13T21-55-28Z--dave-thomas--adr-inspector.md)

## Related code paths

- docs/shared-repo-memory-system-design.md
