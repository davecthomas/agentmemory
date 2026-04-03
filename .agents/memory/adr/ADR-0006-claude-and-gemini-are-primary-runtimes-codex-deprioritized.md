---
id: "ADR-0006"
title: "Claude Code and Gemini CLI are the primary agent runtimes; Codex is deprioritized due to weak hook support"
status: "accepted"
date: "2026-04-02"
tags: "agent-runtime,claude,gemini,install,hooks"
must_read: true
supersedes: ""
superseded_by: ""
---

# ADR-0006: Claude Code and Gemini CLI are the primary agent runtimes; Codex is deprioritized due to weak hook support

## Status
accepted

## Context
The original design targeted Codex CLI, Gemini CLI, and Claude Code equally. In practice, Codex CLI has weak hook support — its hook surface is not reliable enough to drive the full SessionStart + post-turn capture lifecycle. Claude Code and Gemini CLI both expose strong, well-specified hook contracts (`SessionStart`, `Stop`/`AfterAgent`) that this system depends on.

## Decision
Claude Code and Gemini CLI are the two primary tested and supported runtimes. `install.py` wires hooks for both:

**Claude Code** (`~/.claude/settings.json`):
- `SessionStart` → `session-start.py`: validates wiring, bootstraps `.agents/memory/`, injects ADR + recent summary into session context.
- `Stop` → `post-turn-notify.py`: captures a shard after each meaningful turn. Detected via `hook_event_name: Stop`; sets `ai_tool: claude`, `ai_surface: claude-code`.

**Gemini CLI** (`~/.gemini/settings.json`):
- `SessionStart` → `session-start.py`: same validation and bootstrap path.
- `AfterAgent` → `post-turn-notify.py`: captures a shard after each turn. Detected via `hook_event_name: AfterAgent`; sets `ai_tool: gemini`, `ai_surface: gemini-cli`.

Codex wiring (`~/.codex/config.toml`, `~/.codex/hooks.json`) is maintained for compatibility but is not actively tested or relied upon. The `shared_repo_memory_configured` flag is checked in Claude settings first, then Codex config, as the workstation-wide enable signal.

## Consequences
- The memory system works end-to-end with either Claude Code or Gemini CLI; operators can use either.
- Shard frontmatter (`ai_tool`, `ai_surface`) correctly attributes memory to the runtime that produced it, enabling mixed-runtime repos where some shards come from Claude sessions and others from Gemini sessions.
- Codex users are not blocked but should expect reduced reliability until Codex hook support matures.
- `install.py` must be kept in sync with both Claude and Gemini hook formats as those CLIs evolve.
