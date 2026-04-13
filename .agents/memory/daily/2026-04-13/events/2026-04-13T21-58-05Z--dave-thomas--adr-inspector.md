---
timestamp: "2026-04-13T21:58:05Z"
author: "dave-thomas"
branch: "main"
thread_id: "adr-inspector"
turn_id: "subagent-stop-capture"
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
checkpoint_surface: "docs/shared-repo-memory-system-design.md — Post-Turn Capture section."
checkpoint_outcome: "Decision candidate: wire SubagentStop to ensure Task-tool subagent turns produce pending captures."
related_adrs:
  - "ADR-0007"
files_touched:
  - "docs/shared-repo-memory-system-design.md"
design_docs_touched:
  - "docs/shared-repo-memory-system-design.md"
verification:
  - "Design doc section 'Post-Turn Capture': 'SubagentStop fires when a Task agent (spawned via the Agent tool) completes. Wiring post-turn-notify.py to SubagentStop ensures that significant work done inside subagents also produces pending shards, not just main-agent turns.'"
  - "Hook map table in 'Agent Wiring' lists SubagentStop → post-turn-notify.py for Claude Code only."
---

## Why

When an agent spawns a child via the Task tool (Claude Code's Agent-tool mechanism), the child executes a bounded sub-task and produces file changes that are architecturally indistinguishable from main-agent work. If only the `Stop` hook (main-agent turn end) is wired, sub-task work is invisible to the capture pipeline — the pending shard is never written, the episode cluster never sees the file changes, and the checkpoint never reflects what actually happened. Wiring `SubagentStop` closes this gap: it fires when each Task agent completes, giving `post-turn-notify.py` the same opportunity to capture a file-changing sub-turn as it has for main-agent turns.

## What changed

- `SubagentStop` is wired to `post-turn-notify.py` in `~/.claude/settings.json` alongside `Stop`, as documented in the Agent Wiring hook map in `docs/shared-repo-memory-system-design.md`.
- `post-turn-notify.py` uses `hookEventName == "SubagentStop"` as one of the two signals that identify a Claude Code invocation (the other being `"Stop"`).
- This wiring is Claude Code-specific: Gemini CLI's `AfterAgent` hook already fires at the agent level; Codex has no supported post-turn integration.

## Evidence

- Design doc "Post-Turn Capture" section explicitly names `SubagentStop` and explains the rationale.
- Hook map in "Agent Wiring": `SubagentStop → post-turn-notify.py | Claude Code: writes pending shard + spawns publish flow`.
- Agent detection table in "Agent Wiring" confirms `hookEventName == "Stop"` or `hookEventName == "SubagentStop"` both identify Claude Code.

## Next

- Confirm that SubagentStop fires reliably for all Task-tool invocation patterns, including nested subagents.
- Evaluate whether Gemini CLI's AfterAgent already covers the analogous case or if sub-agent gaps exist there too.
