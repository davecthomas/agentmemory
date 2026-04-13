# ADR-0018 Use git post-checkout, post-merge, and post-rewrite hooks to rebuild local catch-up after git operations

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

Purpose: Use git post-checkout, post-merge, and post-rewrite hooks to rebuild local catch-up after git operations
Derived from: [2026-04-13T21-58-07Z--dave-thomas--adr-inspector](../daily/2026-04-13/events/2026-04-13T21-58-07Z--dave-thomas--adr-inspector.md)

## Context

Local catch-up (`catchup.md`) is an uncommitted digest that reflects what changed since the last rebuild. It is not shared memory (never committed) and cannot be refreshed from the network. Without an automatic rebuild trigger, a `git pull` or branch switch would leave the catch-up stale: the agent's next session would read outdated "what's new since your last session" context even though the working tree already contains the updated shared-memory files. Using native git hooks — specifically `post-checkout`, `post-merge`, and `post-rewrite` — means the rebuild fires at exactly the right moment (after the tree changes) with no extra developer action and no polling loop.

## Decision

- `.githooks/post-checkout`, `.githooks/post-merge`, and `.githooks/post-rewrite` each call `build-catchup.py --trigger <event>` from the central install at `$HOME/.agent/shared-repo-memory/`.
- `build-catchup.py` writes `.codex/local/catchup.md` and `.codex/local/sync_state.json` with `last_seen_head`, last ADR/summary hashes, and a rebuild timestamp.
- These files are explicitly never committed; `.codex/local/` is local continuity state only.
- The `git config core.hooksPath .githooks` directive (set by `bootstrap-repo.py`) wires these hooks into every git operation in the repo.

## Consequences

- Verify that `post-rewrite` covers both `rebase` and `amend` correctly (git fires it for both).
- Evaluate whether a `post-fetch` hook is needed for scenarios where the tree is not checked out but memory is fetched.

## Source memory events

- [2026-04-13T21-58-07Z--dave-thomas--adr-inspector](../daily/2026-04-13/events/2026-04-13T21-58-07Z--dave-thomas--adr-inspector.md)

## Related code paths

- docs/shared-repo-memory-system-design.md
