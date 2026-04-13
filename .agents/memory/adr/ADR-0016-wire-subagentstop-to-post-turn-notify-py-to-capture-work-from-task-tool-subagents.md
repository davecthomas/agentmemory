# ADR-0016 Wire SubagentStop to post-turn-notify.py to capture work from Task-tool subagents

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

Purpose: Wire SubagentStop to post-turn-notify.py to capture work from Task-tool subagents
Derived from: [2026-04-13T21-58-05Z--dave-thomas--adr-inspector](../daily/2026-04-13/events/2026-04-13T21-58-05Z--dave-thomas--adr-inspector.md)

## Context

When an agent spawns a child via the Task tool (Claude Code's Agent-tool mechanism), the child executes a bounded sub-task and produces file changes that are architecturally indistinguishable from main-agent work. If only the `Stop` hook (main-agent turn end) is wired, sub-task work is invisible to the capture pipeline — the pending shard is never written, the episode cluster never sees the file changes, and the checkpoint never reflects what actually happened. Wiring `SubagentStop` closes this gap: it fires when each Task agent completes, giving `post-turn-notify.py` the same opportunity to capture a file-changing sub-turn as it has for main-agent turns.

## Decision

- `SubagentStop` is wired to `post-turn-notify.py` in `~/.claude/settings.json` alongside `Stop`, as documented in the Agent Wiring hook map in `docs/shared-repo-memory-system-design.md`.
- `post-turn-notify.py` uses `hookEventName == "SubagentStop"` as one of the two signals that identify a Claude Code invocation (the other being `"Stop"`).
- This wiring is Claude Code-specific: Gemini CLI's `AfterAgent` hook already fires at the agent level; Codex has no supported post-turn integration.

## Consequences

- Confirm that SubagentStop fires reliably for all Task-tool invocation patterns, including nested subagents.
- Evaluate whether Gemini CLI's AfterAgent already covers the analogous case or if sub-agent gaps exist there too.

## Source memory events

- [2026-04-13T21-58-05Z--dave-thomas--adr-inspector](../daily/2026-04-13/events/2026-04-13T21-58-05Z--dave-thomas--adr-inspector.md)

## Related code paths

- docs/shared-repo-memory-system-design.md
