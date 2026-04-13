# ADR-0013 Re-inject bounded memory context via PostCompact hook to survive context window compaction

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

Purpose: Re-inject bounded memory context via PostCompact hook to survive context window compaction
Derived from: [2026-04-13T21-57-05Z--dave-thomas--adr-inspector](../daily/2026-04-13/events/2026-04-13T21-57-05Z--dave-thomas--adr-inspector.md)

## Context

Context window compaction is a runtime lifecycle event that discards the full transcript, including the memory context injected by `SessionStart`. Without explicit handling, the agent loses awareness of ADRs and recent daily summaries for the remainder of the session — all the context that `SessionStart` carefully loaded is silently gone. The `PostCompact` hook exists solely to re-inject the same bounded read set (ADR index + three most recent daily summaries) so the agent continues to operate with the same ground truth after compaction as before.
This also documents a real runtime asymmetry: Claude Code has a `PostCompact` event; Gemini CLI's `PreCompress` is advisory-only and fires before compression with no ability to re-inject context afterward. Codex has no equivalent. The decision acknowledges this divergence rather than papering over it.

## Decision

- `PostCompact` is wired to `post-compact.py` in Claude Code's `~/.claude/settings.json` with a 15-second timeout.
- The hook re-injects the same bounded read set that `SessionStart` loads: ADR index + three most recent daily summaries.
- Gemini CLI is documented as lacking a post-compaction re-injection path; `PreCompress` is explicitly noted as advisory-only.
- The system design treats `PostCompact` as a required hook for Claude Code, not an optional enhancement.

## Consequences

- Verify `post-compact.py` re-injects the identical bounded read set as `session-start.py` (no drift in what gets loaded).
- Consider whether the 15-second timeout is sufficient for large ADR indexes on slow disks.
- Document the Gemini CLI limitation explicitly in the runtime comparison so future contributors don't assume parity.

## Source memory events

- [2026-04-13T21-57-05Z--dave-thomas--adr-inspector](../daily/2026-04-13/events/2026-04-13T21-57-05Z--dave-thomas--adr-inspector.md)

## Related code paths

- docs/shared-repo-memory-system-design.md
