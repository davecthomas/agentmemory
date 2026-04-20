# 2026-04-20 summary

## Snapshot

- Captured 2 memory events.
- Main work: Added an UnknownAdapter sentinel with neutral Claude-compatible rendering and no-op wire/bootstrap behavior. Introduced AgentAdapter.matches_payload() as a new protocol method; Claude matches on transcript_path or Claude-unique hook events (Stop, SubagentStop, UserPromptSubmit, PostCompact); Gemini matches on AfterAgent/BeforeAgent; Codex explicitly abstains because its payload shape is not unique. Added a bounded ppid walk (_detect_runtime_from_process_tree, depth 6, cached) that recognizes claude/gemini/codex binaries in ancestry. detect_adapter() now resolves payload → process tree → env vars → UnknownAdapter. CodexAdapter.matches_environment() now positively detects CODEX_THREAD_ID / CODEX_SHELL / CODEX_CI / CODEX_INTERNAL_ORIGINATOR_OVERRIDE and the com.openai.codex macOS bundle id. session-start.py parses stdin before detection so the payload feeds the resolver and UnknownAdapter cleanly short-circuits the subagent bootstrap spawn with a diagnostic line to .agents/memory/logs/bootstrap.log. post-turn-notify.py and prompt-guard.py now pass the full payload into detect_adapter_from_hook_event.
- Top decision: Earlier detection fell through to CodexAdapter whenever CLAUDECODE / GEMINI_CLI did not propagate into the hook subprocess. That produced misattributed shard frontmatter, wrong runtime tags on log prefixes, and — worst — bootstrap spawns that presumed Codex credentials in Claude-only client repos. A fail-closed design (UnknownAdapter + explicit skip) is required so agentmemory never guesses a runtime it cannot confirm, and so client repos do not need to export any discovery env var for detection to work. ([2026-04-20 21:48:19 UTC by 2355287-davecthomas](events/2026-04-20T21-48-19Z--2355287-davecthomas--thread_28d776fa-60f2-4062-b731-a3db9ac77dcb--turn_02b10fb024.md))
- Blockers: Earlier detection fell through to CodexAdapter whenever CLAUDECODE / GEMINI_CLI did not propagate into the hook subprocess. That produced misattributed shard frontmatter, wrong runtime tags on log prefixes, and — worst — bootstrap spawns that presumed Codex credentials in Claude-only client repos. A fail-closed design (UnknownAdapter + explicit skip) is required so agentmemory never guesses a runtime it cannot confirm, and so client repos do not need to export any discovery env var for detection to work.

| Metric | Value |
|---|---|
| Memory events captured | 2 |
| Repo files changed | 2 |
| Decision candidates | 1 |
| Active blockers | 1 |

## Major work completed

- Added an UnknownAdapter sentinel with neutral Claude-compatible rendering and no-op wire/bootstrap behavior. Introduced AgentAdapter.matches_payload() as a new protocol method; Claude matches on transcript_path or Claude-unique hook events (Stop, SubagentStop, UserPromptSubmit, PostCompact); Gemini matches on AfterAgent/BeforeAgent; Codex explicitly abstains because its payload shape is not unique. Added a bounded ppid walk (_detect_runtime_from_process_tree, depth 6, cached) that recognizes claude/gemini/codex binaries in ancestry. detect_adapter() now resolves payload → process tree → env vars → UnknownAdapter. CodexAdapter.matches_environment() now positively detects CODEX_THREAD_ID / CODEX_SHELL / CODEX_CI / CODEX_INTERNAL_ORIGINATOR_OVERRIDE and the com.openai.codex macOS bundle id. session-start.py parses stdin before detection so the payload feeds the resolver and UnknownAdapter cleanly short-circuits the subagent bootstrap spawn with a diagnostic line to .agents/memory/logs/bootstrap.log. post-turn-notify.py and prompt-guard.py now pass the full payload into detect_adapter_from_hook_event.
- Added a new repo-root entry point uninstall.sh that execs scripts/shared-repo-memory/uninstall.py with global (default), --repo, --purge-memory, and --dry-run scopes matching install.sh. The uninstaller orchestrates per-adapter cleanup by calling a new AgentAdapter.unwire_hooks protocol method, implemented for Claude, Codex, and Gemini (and a no-op for UnknownAdapter). Each adapter reverses only its own wire_hooks: entries are identified by installer-owned hook names or by commands that point at ctx.install_root, so user-added hook entries for other tooling survive. The Codex adapter additionally strips the installer's config.toml keys, its canonical comments, and the per-repo trust block it appended. Global scope also removes ~/.agent/shared-repo-memory scripts, per-agent skill symlinks, canonical skill copies, and the shared_asset_refresh_state.json; per-repo scope removes .githooks only when content still matches, unsets core.hooksPath only when still equal to .githooks and no other hooks remain, drops .codex/memory, and strips the installer's .gitignore marker block. Committed memory under .agents/memory is untouched unless --purge-memory stages git rm -r explicitly for operator review.

## Why this mattered

- Earlier detection fell through to CodexAdapter whenever CLAUDECODE / GEMINI_CLI did not propagate into the hook subprocess. That produced misattributed shard frontmatter, wrong runtime tags on log prefixes, and — worst — bootstrap spawns that presumed Codex credentials in Claude-only client repos. A fail-closed design (UnknownAdapter + explicit skip) is required so agentmemory never guesses a runtime it cannot confirm, and so client repos do not need to export any discovery env var for detection to work.
- Until this turn the installer was one-way: there was no first-class, tested way to back out shared-repo-memory wiring. Operators trying to uninstall had to hand-edit Claude/Codex/Gemini hook files, the Codex config.toml trust/hook keys, .githooks, core.hooksPath, .codex/memory symlinks, and the installer's .gitignore block. That was error-prone, non-symmetric with install.sh, and risked removing user-added hooks for unrelated tools. A durable, fail-closed uninstaller is required for this codebase to be trustworthy in other repos.

## Active blockers

- Earlier detection fell through to CodexAdapter whenever CLAUDECODE / GEMINI_CLI did not propagate into the hook subprocess. That produced misattributed shard frontmatter, wrong runtime tags on log prefixes, and — worst — bootstrap spawns that presumed Codex credentials in Claude-only client repos. A fail-closed design (UnknownAdapter + explicit skip) is required so agentmemory never guesses a runtime it cannot confirm, and so client repos do not need to export any discovery env var for detection to work.

## Decision candidates

- Earlier detection fell through to CodexAdapter whenever CLAUDECODE / GEMINI_CLI did not propagate into the hook subprocess. That produced misattributed shard frontmatter, wrong runtime tags on log prefixes, and — worst — bootstrap spawns that presumed Codex credentials in Claude-only client repos. A fail-closed design (UnknownAdapter + explicit skip) is required so agentmemory never guesses a runtime it cannot confirm, and so client repos do not need to export any discovery env var for detection to work. ([2026-04-20 21:48:19 UTC by 2355287-davecthomas](events/2026-04-20T21-48-19Z--2355287-davecthomas--thread_28d776fa-60f2-4062-b731-a3db9ac77dcb--turn_02b10fb024.md))

## Next likely steps

- Verify the UnknownAdapter path on a client repo where neither env vars nor process ancestry resolve (e.g., a sandboxed CI runner) and confirm bootstrap.log captures the diagnostic without crashing SessionStart. Consider promoting this to an ADR that supersedes the Codex-as-fallback assumption in ADR-0006, and decide whether shard frontmatter should expose ai_tool=unknown verbatim or be suppressed when UnknownAdapter is active.
- Validate on a freshly installed host: exercise ./uninstall.sh --dry-run, then ./uninstall.sh, then ./uninstall.sh --repo, and confirm no user-added hooks are lost and that core.hooksPath is only unset when safe.
- Decide whether a companion CI check should assert that every new adapter method added to AgentAdapter also has a corresponding unwire path, to keep install and uninstall in lockstep.
- Land this branch (feat/uninstaller) via PR and update any top-level install documentation that still implies installation is one-way.

## Relevant event shards

- [2026-04-20 21:48:19 UTC by 2355287-davecthomas](events/2026-04-20T21-48-19Z--2355287-davecthomas--thread_28d776fa-60f2-4062-b731-a3db9ac77dcb--turn_02b10fb024.md)
- [2026-04-20 22:38:40 UTC by 2355287-davecthomas](events/2026-04-20T22-38-40Z--2355287-davecthomas--thread_28d776fa-60f2-4062-b731-a3db9ac77dcb--turn_58a7125909.md)
