---
timestamp: "2026-04-13T21:53:14Z"
author: "dave-thomas"
branch: "codex/6-runtime-log-identity-cleanup"
thread_id: "adr-inspector"
turn_id: "adr-inspector-0002"
decision_candidate: true
enriched: true
ai_generated: true
ai_model: "claude-sonnet-4-5"
ai_tool: "claude"
ai_surface: "claude-code"
ai_executor: "adr-inspector"
workstream_id: "adr-inspector"
workstream_scope: "branch"
checkpoint_goal: "Identify and promote ADR-worthy architectural decisions from the system design doc."
checkpoint_surface: "docs/shared-repo-memory-system-design.md"
checkpoint_outcome: "Decision candidate: bootstrap shared memory using an isolated subagent."
files_touched:
  - "docs/shared-repo-memory-system-design.md"
design_docs_touched:
  - "docs/shared-repo-memory-system-design.md"
verification:
  - "docs/shared-repo-memory-system-design.md §Memory Bootstrap §Why subagent, not in-session instruction: explicitly documents the rejected alternative."
  - "docs/shared-repo-memory-system-design.md §Subagent invocation: per-runtime CLI commands for detached subprocess spawning."
  - "docs/shared-repo-memory-system-design.md §Fallback chain: fallback to auto-bootstrap.py when agent CLI binary is absent."
---

## Why

When a wired repo has no event shards yet, the system needs to seed initial memory from existing commit history and design docs. The obvious path — injecting a "please bootstrap" instruction into the main agent's context — fails reliably in practice: the agent already has ADR index content loaded from `SessionStart`, sees that decisions are recorded, and reasons (incorrectly) that the repo is already initialized. It ignores the bootstrap instruction entirely. An isolated subagent spawned as a detached subprocess has no conversation history and no competing context; it receives only the `memory-bootstrap` skill as its system prompt and executes the task cleanly.

## What changed

Established that memory bootstrap must always run as a detached isolated subagent subprocess, never as an in-session instruction:
- `session-start.py` spawns the subagent via `claude -p` (Claude Code) or `gemini --prompt` (Gemini CLI), passing the `memory-bootstrap` SKILL.md as the system prompt and `--cwd <repo_root>` to anchor the working directory.
- `claude -p` inherits Claude Code's keychain auth — no `ANTHROPIC_API_KEY` is needed in the hook subprocess environment.
- A `.agents/memory/.auto_bootstrap_running` lock file prevents concurrent bootstrap runs; locks older than 300 seconds are treated as stale.
- Subagent output is written to `.agents/memory/logs/bootstrap.log` for debugging only (not committed).
- The `memory-bootstrap` SKILL.md includes a CLI / Non-Interactive Mode section that instructs the subagent to skip user-facing commentary and exit cleanly.
- Fallback: when the agent CLI binary is not on PATH, `auto-bootstrap.py` is invoked (requires `ANTHROPIC_API_KEY`).

## Evidence

- `docs/shared-repo-memory-system-design.md` §Memory Bootstrap §Why subagent, not in-session instruction: "Injecting a 'please bootstrap' instruction into the main agent's context fails in practice: the agent sees existing ADRs and reasons that the repo is already initialized, ignoring the instruction."
- §Subagent invocation table documents per-runtime CLI commands.
- §Fallback chain documents the two-tier fallback strategy (subagent CLI → auto-bootstrap.py).

## Next

- Validate that `claude -p` auth inheritance is reliable across all workstation configurations (keychain vs. env-var auth).
- Consider whether the 300-second lock-stale threshold is appropriate for slow bootstrap runs on large repos.
