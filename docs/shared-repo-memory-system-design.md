# Shared Repo Memory System — Design

## Purpose

Give coding agents durable repo context so every new session starts from prior decisions rather than rebuilding history from scratch. Memory persists across sessions, branches, and collaborators as plain Markdown committed to Git.

---

## Core Principles

- **Memory is plain Markdown in Git.** No external service, no database, no embedding pipeline.
- **The repo owns the memory.** Canonical storage lives under `<repo>/.agents/memory/`, committed and versioned like code.
- **Agent-facing paths are access paths, not storage.** `.codex/memory` is a symlink into `.agents/memory/` — it never holds a separate copy.
- **Writes are immutable event shards.** Each meaningful agent turn produces one shard. Shards are never edited after creation.
- **Read models are derived.** Daily summaries are rebuilt deterministically from shards. They are never the write target.
- **Durable decisions live only in ADRs.** ADR promotion is always explicit — never an automatic post-turn side effect.
- **Memory is not collaborative until committed and pushed.** The system auto-stages memory artifacts but never auto-commits or auto-pushes.

---

## File Layout

```
<repo>/
├── .agents/memory/                         # canonical shared memory — committed to Git
│   ├── adr/
│   │   ├── INDEX.md                        # ADR index table, rebuilt on every promotion
│   │   └── ADR-NNNN-<slug>.md             # one file per architecture decision
│   └── daily/
│       └── YYYY-MM-DD/
│           ├── events/
│           │   └── <timestamp>--<author>--thread_<id>--turn_<id>.md
│           └── summary.md                  # derived daily summary, rebuilt from shards
├── .codex/
│   ├── memory -> ../.agents/memory         # symlink — Codex access path only
│   └── local/
│       ├── catchup.md                      # uncommitted local catch-up digest
│       └── sync_state.json                 # watermark for catch-up rebuilds
├── .claude/
│   └── local/                              # Claude-specific local continuity state
└── .githooks/
    ├── post-checkout                        # triggers catch-up rebuild
    ├── post-merge                           # triggers catch-up rebuild
    └── post-rewrite                         # triggers catch-up rebuild

~/.agent/
├── shared-repo-memory/                      # installed helper scripts
│   ├── common.py
│   ├── bootstrap-repo.py
│   ├── session-start.py
│   ├── post-turn-notify.py
│   ├── prompt-guard.py
│   ├── post-compact.py
│   ├── rebuild-summary.py
│   ├── build-catchup.py
│   ├── promote-adr.py
│   └── auto-bootstrap.py                   # legacy fallback only (requires ANTHROPIC_API_KEY)
└── state/
    └── shared_asset_refresh_state.json

~/.agent/skills/
    ├── memory-writer/
    ├── memory-bootstrap/
    ├── adr-promoter/
    └── news/

~/.claude/skills/<skill>  →  ~/.agent/skills/<skill>
~/.codex/skills/<skill>   →  ~/.agent/skills/<skill>
~/.gemini/skills/<skill>  →  ~/.agent/skills/<skill>
```

---

## Installation

```bash
./install.sh
```

`install.sh` calls `scripts/shared-repo-memory/install.py`, which:

1. Creates `~/.agent/shared-repo-memory/` and copies all helper scripts into it
2. Creates `~/.agent/state/` and initialises `shared_asset_refresh_state.json`
3. Copies skills into `~/.agent/skills/` and creates per-agent symlinks under `~/.claude/skills/`, `~/.codex/skills/`, and `~/.gemini/skills/`
4. Writes agent config and hook wiring (see Agent Wiring)

### Repo bootstrap

`bootstrap-repo.py` creates the repo-local layout:

- `.agents/memory/adr/` and `.agents/memory/daily/`
- `.codex/local/` and `.claude/local/`
- `.githooks/` with `post-checkout`, `post-merge`, `post-rewrite`
- `.codex/memory → ../.agents/memory` symlink
- Empty `INDEX.md`
- `git config core.hooksPath .githooks`

`SessionStart` calls this automatically on every session open when any wiring is incomplete. You do not need to run it manually.

---

## Agent Wiring

### Hook map

| Hook event | Script | Claude Code | Gemini CLI | Codex |
|---|---|---|---|---|
| `SessionStart` / `SessionStart` | `session-start.py` | yes | yes | yes |
| `Stop` / `AfterAgent` | `post-turn-notify.py` | `Stop` | `AfterAgent` | via notify-wrapper |
| `SubagentStop` | `post-turn-notify.py` | yes | — | — |
| `UserPromptSubmit` / `BeforeAgent` | `prompt-guard.py` | `UserPromptSubmit` | `BeforeAgent` | — |
| `PostCompact` | `post-compact.py` | yes | — (no equivalent) | — |

### Claude Code — `~/.claude/settings.json`

```json
{
  "shared_repo_memory_configured": true,
  "shared_agent_assets_repo_path": "/path/to/this/repo",
  "hooks": {
    "SessionStart":       [{ "hooks": [{ "type": "command", "command": "~/.agent/shared-repo-memory/session-start.py",    "timeout": 30 }] }],
    "Stop":               [{ "hooks": [{ "type": "command", "command": "~/.agent/shared-repo-memory/post-turn-notify.py", "timeout": 60 }] }],
    "SubagentStop":       [{ "hooks": [{ "type": "command", "command": "~/.agent/shared-repo-memory/post-turn-notify.py", "timeout": 60 }] }],
    "UserPromptSubmit":   [{ "hooks": [{ "type": "command", "command": "~/.agent/shared-repo-memory/prompt-guard.py",     "timeout": 10 }] }],
    "PostCompact":        [{ "hooks": [{ "type": "command", "command": "~/.agent/shared-repo-memory/post-compact.py",     "timeout": 15 }] }]
  }
}
```

### Codex — `~/.codex/config.toml` + `~/.codex/hooks.json`

```toml
experimental_use_hooks = true
hooks_config_path = "~/.codex/hooks.json"
shared_repo_memory_configured = true
```

```json
{
  "hooks": {
    "SessionStart": [{ "hooks": [{ "type": "command", "command": "~/.agent/shared-repo-memory/session-start.py" }] }]
  }
}
```

Post-turn capture uses `scripts/shared-repo-memory/notify-wrapper.sh` via the repo-local `notify` path.

### Gemini CLI — `~/.gemini/settings.json`

```json
{
  "shared_repo_memory_configured": true,
  "hooks": {
    "SessionStart": [{ "matcher": "*", "hooks": [{ "name": "shared-repo-memory-session-start", "type": "command", "command": "~/.agent/shared-repo-memory/session-start.py",    "timeout": 30000 }] }],
    "AfterAgent":   [{ "matcher": "*", "hooks": [{ "name": "shared-repo-memory-post-turn",     "type": "command", "command": "~/.agent/shared-repo-memory/post-turn-notify.py", "timeout": 30000 }] }],
    "BeforeAgent":  [{ "matcher": "*", "hooks": [{ "name": "shared-repo-memory-prompt-guard",  "type": "command", "command": "~/.agent/shared-repo-memory/prompt-guard.py",     "timeout": 10000 }] }]
  }
}
```

Gemini CLI has no `PostCompact` equivalent — `PreCompress` fires before compression and is advisory only.

### Agent detection at runtime

`post-turn-notify.py` detects the calling agent to set AI attribution fields:

| Signal | Agent |
|---|---|
| `hookEventName == "Stop"` or `hookEventName == "SubagentStop"` | Claude Code |
| `hookEventName == "AfterAgent"` | Gemini CLI |
| Neither | Codex |

`session-start.py` also detects the agent in order to choose the correct subagent CLI for memory bootstrap (see [Memory Bootstrap](#memory-bootstrap)):

| Env var | Agent |
|---|---|
| `CLAUDECODE=1` | Claude Code |
| `GEMINI_CLI=1` | Gemini CLI |
| Neither | defaults to `claude` (covers Codex sessions with `claude` on PATH) |

`prompt-guard.py` does not need to detect the agent — it emits the same JSON schema for all agents.

---

## SessionStart Hook

`session-start.py` runs at every session open.

1. Checks `shared_repo_memory_configured` — exits silently if absent or false
2. Verifies required installed assets exist under `~/.agent/shared-repo-memory/`
3. Checks repo wiring; calls `bootstrap-repo.py` to fix any gaps
4. Loads the ADR index and the three most recent daily summaries as memory context
5. If event shards are absent, spawns a bootstrap subagent in the background (see [Memory Bootstrap](#memory-bootstrap))
6. Outputs a single unified JSON schema accepted by all agents:

```json
{
  "systemMessage": "Shared repo memory loaded. Last refresh: <timestamp>.",
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "<ADR index + recent daily summaries>"
  }
}
```

`systemMessage` appears in the agent UI. `additionalContext` is injected into the model context before the first turn. Noop and error paths omit `hookSpecificOutput` and only include `systemMessage`.

### Shared-asset refresh throttle

`SessionStart` is also responsible for refreshing the installed shared assets from the `agentmemory` checkout. Refresh runs no more than once per 24-hour window per workstation, gated by `~/.agent/state/shared_asset_refresh_state.json`.

---

## UserPromptSubmit / BeforeAgent Hook

`prompt-guard.py` runs before every user turn (`UserPromptSubmit` on Claude Code, `BeforeAgent` on Gemini CLI).

Fires only when needed: if the repo has memory wiring but no event shards yet. Injects a one-time instruction into the agent's context telling it to proactively offer to run the `news` skill before proceeding. Tracks which sessions have already received the nudge in `~/.agent/state/prompt-guard-sessions.json` — the nudge fires at most once per session.

This is the recovery path for sessions where memory was deleted or never bootstrapped. It fires mid-session, unlike `SessionStart` which only fires at session open.

### Performance

Because this hook fires on every user prompt, latency is critical. It uses a fast-exit strategy so the common case (shards already exist) adds no meaningful overhead:

1. Parse stdin payload (unavoidable).
2. Read the session-state file — a small JSON dict.
3. If this `session_id` is already in the dict → **exit immediately**. No subprocess, no filesystem traversal, no glob.
4. Walk up from `cwd` in pure Python to find the memory root — no `git` subprocess.
5. If wiring is absent → mark session done and exit.
6. Glob for shards — short-circuits on the first match via `any()`.
7. If shards found → mark session done and exit.
8. Only if shards are absent: inject the nudge, mark session done.

After the first prompt in any session where shards exist, every subsequent prompt costs only: stdin read + tiny JSON file read + dict lookup + exit.

---

## PostCompact Hook

`post-compact.py` runs after Claude Code compacts (summarises) the context window.

Compaction discards the full transcript, including the memory context injected by `SessionStart`. Without this hook the agent loses awareness of ADRs and recent summaries for the remainder of the session. The hook re-injects the same bounded read set: ADR index + three most recent daily summaries.

Gemini CLI has no `PostCompact` equivalent — its `PreCompress` fires before compression and is advisory only.

---

## Memory Bootstrap

When `SessionStart` detects that a wired repo has no event shards yet, it spawns an isolated bootstrap subagent in the background so the session is not blocked.

### Why subagent, not in-session instruction

Injecting a "please bootstrap" instruction into the main agent's context fails in practice: the agent sees existing ADRs and reasons that the repo is already initialised, ignoring the instruction. An isolated subagent has no conversation history and no competing context — it simply receives the skill as its system prompt and executes it.

### Subagent invocation

`session-start.py` spawns the subagent as a detached subprocess using the agent CLI:

| Agent | Command |
|---|---|
| Claude Code | `claude -p --system <SKILL.md content> --cwd <repo_root> "Bootstrap shared repo memory…"` |
| Gemini CLI | `gemini --prompt "Bootstrap…" --system-prompt <SKILL.md content>` |
| Codex (fallback) | same as Claude Code — `claude` binary used cross-agent |

`claude -p` inherits Claude Code's keychain auth — no `ANTHROPIC_API_KEY` needed in the hook subprocess environment.

### Fallback chain

1. **Subagent CLI** (`claude -p` or `gemini --prompt`) — primary path; no API key required
2. **`auto-bootstrap.py`** — legacy path; used when the agent CLI binary is not on PATH; requires `ANTHROPIC_API_KEY` in the environment

### Lock file

`.agents/memory/.auto_bootstrap_running` prevents concurrent bootstrap runs. Lock files older than 300 seconds are treated as stale and ignored.

### Bootstrap log

Subagent stdout and stderr are written to `.agents/memory/logs/bootstrap.log` for debugging. This file is not committed.

### Skill: non-interactive mode

The `memory-bootstrap` SKILL.md includes a **CLI / Non-Interactive Mode** section instructing the subagent to skip user-facing commentary, write shards directly, call `rebuild-summary.py`, and exit. This ensures the subagent completes cleanly without waiting for user input that will never arrive.

---

## Post-Turn Capture

`post-turn-notify.py` runs after every agent turn via `Stop` or `SubagentStop` (Claude Code), `AfterAgent` (Gemini), or `notify-wrapper.sh` (Codex).

`SubagentStop` fires when a Task agent (spawned via the Agent tool) completes. Wiring `post-turn-notify.py` to `SubagentStop` ensures that significant work done inside subagents also produces event shards, not just main-agent turns.

### Meaningful turn gate

**A shard is written only if `files_touched` is non-empty.** Turns with no tracked file changes produce no shard.

### What is captured

| Field | Source |
|---|---|
| `timestamp` | current UTC time for live turns; **source event date** (commit date, doc date) for bootstrap shards — never today's date for historical content |
| `author` | `git config user.email` (local part, slugified) |
| `branch` | `git rev-parse --abbrev-ref HEAD` |
| `thread_id` | payload field or stable hash of payload |
| `turn_id` | payload field or stable hash of payload |
| `decision_candidate` | payload strings contain: decision, policy, contract, standard, repo rule, adr, must read, governing |
| `ai_model` | `CLAUDE_MODEL` env var → payload `model` field → `claude-unknown` |
| `ai_tool` | `claude` / `gemini` / `codex` per agent detection |
| `files_touched` | `git status --porcelain` excluding `.agents/memory/` and `.codex/local/` |
| `verification` | payload strings matching: pass, fail, error, warning, test, lint, build, verified |

### Shard filename

```
<timestamp>--<author>--thread_<thread_id>--turn_<turn_id>.md
```

If a shard for the same thread and turn already exists, the existing file is kept (idempotent).

### Shard format

```markdown
---
timestamp: "2026-04-03T14:22:00Z"
author: "davidcthomas"
branch: "main"
thread_id: "abc123"
turn_id: "turn_def456"
decision_candidate: false
ai_generated: true
ai_model: "claude-sonnet-4-6"
ai_tool: "claude"
ai_surface: "claude-code"
ai_executor: "local-agent"
related_adrs:
  - "ADR-0001"
files_touched:
  - "scripts/shared-repo-memory/session-start.py"
verification:
  - "Tests passed."
# bootstrapped_at is only present on shards written by memory-bootstrap, not live turns.
# It records when the bootstrap ran; timestamp records the source event date.
bootstrapped_at: "2026-04-03T14:22:00Z"
---

## Why

- <first line of user prompt or assistant response>

## What changed

- Updated scripts/shared-repo-memory/session-start.py

## Evidence

- <verification matches from payload>

## Next

- <blocker or next-step matches from payload>
```

### After writing

1. Calls `rebuild-summary.py` to regenerate today's `summary.md`
2. Auto-stages the shard and rebuilt summary via `git add`

---

## Daily Summary

`rebuild-summary.py --repo-root <path> --date YYYY-MM-DD`

Reads all shards for the given date and produces a deterministic `summary.md`. Always rebuilt from scratch — never edited in place.

Sections:

| Section | Content |
|---|---|
| Snapshot | Event count, main work, top decision, blockers — as a table |
| Major work completed | `What changed` excerpts (max 10) |
| Why this mattered | `Why` excerpts (max 10) |
| Active blockers | Blocker lines deduplicated by branch+thread (max 10) |
| Decision candidates | `decision_candidate: true` shards with links (max 10) |
| Next likely steps | `Next` lines deduplicated by thread (max 10) |
| Relevant event shards | Links to contributing shards (max 10) |

---

## Local Catch-up

`build-catchup.py --repo-root <path> --trigger <trigger>`

Writes `.codex/local/catchup.md` — an uncommitted digest of what changed since the last rebuild. Never committed.

Sections: ADR changes (10 most recent), summary changes (2 most recent), active blockers, next likely steps, referenced event shards (max 20).

Also writes `.codex/local/sync_state.json` with `last_seen_head`, last ADR/summary hashes, and rebuild timestamp.

### Automatic triggers

`.githooks/post-checkout`, `post-merge`, and `post-rewrite` each call `scripts/shared-repo-memory/run-catchup.sh`. A normal `git pull`, branch switch, or rebase automatically rebuilds the local digest.

---

## ADR Promotion

`promote-adr.py <shard-path> --repo-root <path> [--title <title>]`

Promotes a decision-candidate shard into a permanent ADR. Only shards with `decision_candidate: true` are accepted.

Creates `ADR-NNNN-<slug>.md` where `NNNN` is one above the current highest ADR number. Rebuilds `INDEX.md` after writing.

### ADR file format

```markdown
# ADR-NNNN <title>

Status: accepted
Date: YYYY-MM-DD
Owners: <author>
Must read: true
Supersedes:
Superseded by:
ai-generated: true
ai-model: <model from source shard>
ai-tool: <tool from source shard>
ai-surface: <surface from source shard>
ai-executor: <executor from source shard>

Purpose: <title>
Derived from: <link to source event shard>

## Context

<Why section from source shard>

## Decision

<What changed section from source shard>

## Consequences

<Next section from source shard>

## Source memory events

- <link to source shard>

## Related code paths

- <files_touched from source shard>
```

### INDEX.md format

```markdown
# ADR index

| ADR | Title | Status | Date | Tags | Must Read | Supersedes | Superseded By |
|---|---|---|---|---|---|---|---|
| [ADR-0001](ADR-0001-<slug>.md) | <title> | accepted | YYYY-MM-DD | <tags> | true | | |
```

Tags are derived from the top-level directory names of `files_touched` in the source shard.

---

## Skills

Each skill is a Markdown file installed to `~/.agent/skills/<skill>/SKILL.md`. Per-agent symlinks point at the same copy — a skill update only needs to touch one location.

| Skill | Purpose |
|---|---|
| `memory-writer` | Write one event shard and rebuild the daily summary |
| `memory-bootstrap` | Seed initial decision candidates and ADRs from existing repo history |
| `adr-promoter` | Promote a decision-candidate shard into a permanent ADR |
| `news` | Summarize recent summaries and ADRs; bootstrap if repo has no memory history yet |

---

## Collaboration Model

```
agent turn completes
    → shard written + summary rebuilt + both auto-staged

developer commits (same commit as the code change)
    → memory is in Git history on the current branch

developer pushes / PR merged
    → memory is on the remote

teammate git pull
    → .agents/memory/ updated like any other tracked file
    → .githooks/post-merge fires → catchup.md rebuilt
    → next session picks up the updated context
```

`.codex/local/` is never committed — it is local continuity state only.

---

## How Memory Updates on `git pull`

Shared memory and local catch-up update through separate mechanisms:

**Shared memory** lives under `.agents/memory/` — committed, versioned files. A `git pull` updates them exactly like source code. No extra step is required; the `.codex/memory` symlink exposes the updated files to Codex immediately.

**Local catch-up** lives under `.codex/local/` — uncommitted, derived files. After the working tree changes, `.githooks/post-merge` (merge-based pull), `post-rewrite` (rebase-based pull), or `post-checkout` (branch switch or clone) each rebuild `catchup.md` from the updated repo state.

The intended experience: `git pull` is sufficient. New shared memory arrives like any file change, and the local digest rebuilds automatically through hooks.

---

## Default Agent Read Path at Task Start

In priority order:

1. `AGENTS.md`
2. `.agents/memory/adr/INDEX.md`
3. Must-read ADR files (`Must read: true`)
4. Today's `summary.md`
5. Yesterday's `summary.md`
6. `.codex/local/catchup.md` (if present)

This path is bounded — agents do not scan raw shard history at task start.
