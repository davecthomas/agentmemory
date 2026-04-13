---
timestamp: "2026-04-13T21:57:05Z"
author: "dave-thomas"
branch: "main"
thread_id: "adr-inspector"
turn_id: "adr-inspector-postcompact"
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
checkpoint_outcome: "Decision candidate: PostCompact hook re-injects bounded memory context after context window compaction."
files_touched:
  - "docs/shared-repo-memory-system-design.md"
design_docs_touched:
  - "docs/shared-repo-memory-system-design.md"
verification:
  - "docs/shared-repo-memory-system-design.md §PostCompact Hook: 'Compaction discards the full transcript, including the memory context injected by SessionStart.'"
  - "docs/shared-repo-memory-system-design.md §Hook map: PostCompact → post-compact.py; yes for Claude Code, — for Gemini and Codex."
  - "docs/shared-repo-memory-system-design.md §Gemini CLI: 'PreCompress fires before compression and is advisory only.'"
---

## Why

Context window compaction is a runtime lifecycle event that discards the full transcript, including the memory context injected by `SessionStart`. Without explicit handling, the agent loses awareness of ADRs and recent daily summaries for the remainder of the session — all the context that `SessionStart` carefully loaded is silently gone. The `PostCompact` hook exists solely to re-inject the same bounded read set (ADR index + three most recent daily summaries) so the agent continues to operate with the same ground truth after compaction as before.

This also documents a real runtime asymmetry: Claude Code has a `PostCompact` event; Gemini CLI's `PreCompress` is advisory-only and fires before compression with no ability to re-inject context afterward. Codex has no equivalent. The decision acknowledges this divergence rather than papering over it.

## What changed

- `PostCompact` is wired to `post-compact.py` in Claude Code's `~/.claude/settings.json` with a 15-second timeout.
- The hook re-injects the same bounded read set that `SessionStart` loads: ADR index + three most recent daily summaries.
- Gemini CLI is documented as lacking a post-compaction re-injection path; `PreCompress` is explicitly noted as advisory-only.
- The system design treats `PostCompact` as a required hook for Claude Code, not an optional enhancement.

## Evidence

- `docs/shared-repo-memory-system-design.md` §PostCompact Hook: "Compaction discards the full transcript, including the memory context injected by SessionStart. Without this hook the agent loses awareness of ADRs and recent summaries for the remainder of the session."
- `docs/shared-repo-memory-system-design.md` §Hook map: `PostCompact` → `post-compact.py`, yes for Claude Code, `—` for Gemini CLI and Codex.
- `docs/shared-repo-memory-system-design.md` §Gemini CLI: "Gemini CLI has no PostCompact equivalent — its PreCompress fires before compression and is advisory only."

## Next

- Verify `post-compact.py` re-injects the identical bounded read set as `session-start.py` (no drift in what gets loaded).
- Consider whether the 15-second timeout is sufficient for large ADR indexes on slow disks.
- Document the Gemini CLI limitation explicitly in the runtime comparison so future contributors don't assume parity.
