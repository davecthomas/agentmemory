---
timestamp: "2026-04-13T21:55:28Z"
author: "dave-thomas"
branch: "main"
thread_id: "adr-inspector"
turn_id: "adr-inspector-2"
decision_candidate: true
enriched: true
ai_generated: true
ai_model: "claude-sonnet-4-6"
ai_tool: "claude"
ai_surface: "claude-code"
ai_executor: "adr-inspector"
workstream_id: "adr-inspector"
workstream_scope: "branch"
checkpoint_goal: "Capture the architectural decision to use a PostCompact hook to preserve memory context across Claude Code context window compaction."
checkpoint_surface: "Shared repo-memory session context lifecycle and Claude Code hook surface."
checkpoint_outcome: "Decision candidate promoted; ADR created."
files_touched:
  - "docs/shared-repo-memory-system-design.md"
design_docs_touched:
  - "docs/shared-repo-memory-system-design.md"
verification:
  - "docs/shared-repo-memory-system-design.md — PostCompact Hook section: 'Compaction discards the full transcript, including the memory context injected by SessionStart. Without this hook the agent loses awareness of ADRs and recent summaries for the remainder of the session.'"
  - "docs/shared-repo-memory-system-design.md — Hook map table: PostCompact → post-compact.py for Claude Code; Gemini CLI row is blank."
  - "docs/shared-repo-memory-system-design.md — Claude Code settings JSON includes PostCompact wired to post-compact.py."
---

## Why

Claude Code's compaction (context window summarization) discards the full transcript, including the ADR index and daily summaries injected by the `SessionStart` hook. Without a recovery mechanism, the agent loses awareness of past decisions and recent work for the remainder of the session — exactly the context that `SessionStart` was designed to provide. The `PostCompact` hook re-injects the same bounded read set so the memory system's core invariant holds even after mid-session compaction: every agent turn, whenever it occurs in a session, starts from prior decisions rather than rebuilding history from scratch.

## What changed

- `post-compact.py` was added as a hook script and wired to Claude Code's `PostCompact` event in `~/.claude/settings.json`.
- On firing, it re-injects the same bounded read set as `SessionStart`: ADR index + three most recent daily summaries.
- Gemini CLI explicitly has no equivalent — its `PreCompress` event fires before compression and is advisory only, so no equivalent recovery hook is wired for Gemini sessions.

## Evidence

- `docs/shared-repo-memory-system-design.md`, PostCompact Hook section: "Compaction discards the full transcript, including the memory context injected by `SessionStart`. Without this hook the agent loses awareness of ADRs and recent summaries for the remainder of the session. The hook re-injects the same bounded read set: ADR index + three most recent daily summaries."
- `docs/shared-repo-memory-system-design.md`, Hook map table: `PostCompact → post-compact.py` for Claude Code; the Gemini CLI row has no PostCompact entry.
- `docs/shared-repo-memory-system-design.md`, Claude Code settings JSON: `"PostCompact": [{ "hooks": [{ "type": "command", "command": "~/.agent/shared-repo-memory/post-compact.py", "timeout": 15 }] }]`.

## Next

- When Gemini CLI exposes a post-compaction hook with read access to the session, wire the same re-injection pattern.
- Verify that PostCompact re-injection correctly handles newly bootstrapped repos where no daily summaries yet exist.
