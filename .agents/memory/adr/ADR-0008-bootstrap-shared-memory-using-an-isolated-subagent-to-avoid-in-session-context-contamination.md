# ADR-0008 Bootstrap shared memory using an isolated subagent to avoid in-session context contamination

Status: accepted
Date: 2026-04-13
Owners: dave-thomas
Must read: true
Supersedes: 
Superseded by: 
ai-generated: True
ai-model: claude-sonnet-4-5
ai-tool: claude
ai-surface: claude-code
ai-executor: adr-inspector

Purpose: Bootstrap shared memory using an isolated subagent to avoid in-session context contamination
Derived from: [2026-04-13T21-53-14Z--dave-thomas--adr-inspector](../daily/2026-04-13/events/2026-04-13T21-53-14Z--dave-thomas--adr-inspector.md)

## Context

When a wired repo has no event shards yet, the system needs to seed initial memory from existing commit history and design docs. The obvious path — injecting a "please bootstrap" instruction into the main agent's context — fails reliably in practice: the agent already has ADR index content loaded from `SessionStart`, sees that decisions are recorded, and reasons (incorrectly) that the repo is already initialized. It ignores the bootstrap instruction entirely. An isolated subagent spawned as a detached subprocess has no conversation history and no competing context; it receives only the `memory-bootstrap` skill as its system prompt and executes the task cleanly.

## Decision

Established that memory bootstrap must always run as a detached isolated subagent subprocess, never as an in-session instruction:
- `session-start.py` spawns the subagent via `claude -p` (Claude Code) or `gemini --prompt` (Gemini CLI), passing the `memory-bootstrap` SKILL.md as the system prompt and `--cwd <repo_root>` to anchor the working directory.
- `claude -p` inherits Claude Code's keychain auth — no `ANTHROPIC_API_KEY` is needed in the hook subprocess environment.
- A `.agents/memory/.auto_bootstrap_running` lock file prevents concurrent bootstrap runs; locks older than 300 seconds are treated as stale.
- Subagent output is written to `.agents/memory/logs/bootstrap.log` for debugging only (not committed).
- The `memory-bootstrap` SKILL.md includes a CLI / Non-Interactive Mode section that instructs the subagent to skip user-facing commentary and exit cleanly.
- Fallback: when the agent CLI binary is not on PATH, `auto-bootstrap.py` is invoked (requires `ANTHROPIC_API_KEY`).

## Consequences

- Validate that `claude -p` auth inheritance is reliable across all workstation configurations (keychain vs. env-var auth).
- Consider whether the 300-second lock-stale threshold is appropriate for slow bootstrap runs on large repos.

## Source memory events

- [2026-04-13T21-53-14Z--dave-thomas--adr-inspector](../daily/2026-04-13/events/2026-04-13T21-53-14Z--dave-thomas--adr-inspector.md)

## Related code paths

- docs/shared-repo-memory-system-design.md
