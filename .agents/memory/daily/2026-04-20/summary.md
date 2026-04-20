# 2026-04-20 summary

## Snapshot

- Captured 1 memory event.
- Main work: Added an UnknownAdapter sentinel with neutral Claude-compatible rendering and no-op wire/bootstrap behavior. Introduced AgentAdapter.matches_payload() as a new protocol method; Claude matches on transcript_path or Claude-unique hook events (Stop, SubagentStop, UserPromptSubmit, PostCompact); Gemini matches on AfterAgent/BeforeAgent; Codex explicitly abstains because its payload shape is not unique. Added a bounded ppid walk (_detect_runtime_from_process_tree, depth 6, cached) that recognizes claude/gemini/codex binaries in ancestry. detect_adapter() now resolves payload → process tree → env vars → UnknownAdapter. CodexAdapter.matches_environment() now positively detects CODEX_THREAD_ID / CODEX_SHELL / CODEX_CI / CODEX_INTERNAL_ORIGINATOR_OVERRIDE and the com.openai.codex macOS bundle id. session-start.py parses stdin before detection so the payload feeds the resolver and UnknownAdapter cleanly short-circuits the subagent bootstrap spawn with a diagnostic line to .agents/memory/logs/bootstrap.log. post-turn-notify.py and prompt-guard.py now pass the full payload into detect_adapter_from_hook_event.
- Top decision: Earlier detection fell through to CodexAdapter whenever CLAUDECODE / GEMINI_CLI did not propagate into the hook subprocess. That produced misattributed shard frontmatter, wrong runtime tags on log prefixes, and — worst — bootstrap spawns that presumed Codex credentials in Claude-only client repos. A fail-closed design (UnknownAdapter + explicit skip) is required so agentmemory never guesses a runtime it cannot confirm, and so client repos do not need to export any discovery env var for detection to work. ([2026-04-20 21:48:19 UTC by 2355287-davecthomas](events/2026-04-20T21-48-19Z--2355287-davecthomas--thread_28d776fa-60f2-4062-b731-a3db9ac77dcb--turn_02b10fb024.md))
- Blockers: Earlier detection fell through to CodexAdapter whenever CLAUDECODE / GEMINI_CLI did not propagate into the hook subprocess. That produced misattributed shard frontmatter, wrong runtime tags on log prefixes, and — worst — bootstrap spawns that presumed Codex credentials in Claude-only client repos. A fail-closed design (UnknownAdapter + explicit skip) is required so agentmemory never guesses a runtime it cannot confirm, and so client repos do not need to export any discovery env var for detection to work.

| Metric | Value |
|---|---|
| Memory events captured | 1 |
| Repo files changed | 1 |
| Decision candidates | 1 |
| Active blockers | 1 |

## Major work completed

- Added an UnknownAdapter sentinel with neutral Claude-compatible rendering and no-op wire/bootstrap behavior. Introduced AgentAdapter.matches_payload() as a new protocol method; Claude matches on transcript_path or Claude-unique hook events (Stop, SubagentStop, UserPromptSubmit, PostCompact); Gemini matches on AfterAgent/BeforeAgent; Codex explicitly abstains because its payload shape is not unique. Added a bounded ppid walk (_detect_runtime_from_process_tree, depth 6, cached) that recognizes claude/gemini/codex binaries in ancestry. detect_adapter() now resolves payload → process tree → env vars → UnknownAdapter. CodexAdapter.matches_environment() now positively detects CODEX_THREAD_ID / CODEX_SHELL / CODEX_CI / CODEX_INTERNAL_ORIGINATOR_OVERRIDE and the com.openai.codex macOS bundle id. session-start.py parses stdin before detection so the payload feeds the resolver and UnknownAdapter cleanly short-circuits the subagent bootstrap spawn with a diagnostic line to .agents/memory/logs/bootstrap.log. post-turn-notify.py and prompt-guard.py now pass the full payload into detect_adapter_from_hook_event.

## Why this mattered

- Earlier detection fell through to CodexAdapter whenever CLAUDECODE / GEMINI_CLI did not propagate into the hook subprocess. That produced misattributed shard frontmatter, wrong runtime tags on log prefixes, and — worst — bootstrap spawns that presumed Codex credentials in Claude-only client repos. A fail-closed design (UnknownAdapter + explicit skip) is required so agentmemory never guesses a runtime it cannot confirm, and so client repos do not need to export any discovery env var for detection to work.

## Active blockers

- Earlier detection fell through to CodexAdapter whenever CLAUDECODE / GEMINI_CLI did not propagate into the hook subprocess. That produced misattributed shard frontmatter, wrong runtime tags on log prefixes, and — worst — bootstrap spawns that presumed Codex credentials in Claude-only client repos. A fail-closed design (UnknownAdapter + explicit skip) is required so agentmemory never guesses a runtime it cannot confirm, and so client repos do not need to export any discovery env var for detection to work.

## Decision candidates

- Earlier detection fell through to CodexAdapter whenever CLAUDECODE / GEMINI_CLI did not propagate into the hook subprocess. That produced misattributed shard frontmatter, wrong runtime tags on log prefixes, and — worst — bootstrap spawns that presumed Codex credentials in Claude-only client repos. A fail-closed design (UnknownAdapter + explicit skip) is required so agentmemory never guesses a runtime it cannot confirm, and so client repos do not need to export any discovery env var for detection to work. ([2026-04-20 21:48:19 UTC by 2355287-davecthomas](events/2026-04-20T21-48-19Z--2355287-davecthomas--thread_28d776fa-60f2-4062-b731-a3db9ac77dcb--turn_02b10fb024.md))

## Next likely steps

- Verify the UnknownAdapter path on a client repo where neither env vars nor process ancestry resolve (e.g., a sandboxed CI runner) and confirm bootstrap.log captures the diagnostic without crashing SessionStart. Consider promoting this to an ADR that supersedes the Codex-as-fallback assumption in ADR-0006, and decide whether shard frontmatter should expose ai_tool=unknown verbatim or be suppressed when UnknownAdapter is active.

## Relevant event shards

- [2026-04-20 21:48:19 UTC by 2355287-davecthomas](events/2026-04-20T21-48-19Z--2355287-davecthomas--thread_28d776fa-60f2-4062-b731-a3db9ac77dcb--turn_02b10fb024.md)
