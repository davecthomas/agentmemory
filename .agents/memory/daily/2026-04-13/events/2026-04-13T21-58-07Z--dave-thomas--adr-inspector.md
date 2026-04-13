---
timestamp: "2026-04-13T21:58:07Z"
author: "dave-thomas"
branch: "main"
thread_id: "adr-inspector"
turn_id: "git-hooks-catchup-rebuild"
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
checkpoint_surface: "docs/shared-repo-memory-system-design.md — Local Catch-up and How Memory Updates on git pull sections."
checkpoint_outcome: "Decision candidate: git post-checkout/post-merge/post-rewrite hooks are the canonical trigger for local catch-up rebuilds."
related_adrs:
  - "ADR-0004"
files_touched:
  - "docs/shared-repo-memory-system-design.md"
design_docs_touched:
  - "docs/shared-repo-memory-system-design.md"
verification:
  - "Design doc 'Local Catch-up' → 'Automatic triggers': post-checkout, post-merge, post-rewrite each call build-catchup.py."
  - "Design doc 'How Memory Updates on git pull': 'The intended experience: git pull is sufficient.'"
  - "Design doc file layout: .githooks/ lists post-checkout, post-merge, post-rewrite alongside pre-commit."
---

## Why

Local catch-up (`catchup.md`) is an uncommitted digest that reflects what changed since the last rebuild. It is not shared memory (never committed) and cannot be refreshed from the network. Without an automatic rebuild trigger, a `git pull` or branch switch would leave the catch-up stale: the agent's next session would read outdated "what's new since your last session" context even though the working tree already contains the updated shared-memory files. Using native git hooks — specifically `post-checkout`, `post-merge`, and `post-rewrite` — means the rebuild fires at exactly the right moment (after the tree changes) with no extra developer action and no polling loop.

## What changed

- `.githooks/post-checkout`, `.githooks/post-merge`, and `.githooks/post-rewrite` each call `build-catchup.py --trigger <event>` from the central install at `$HOME/.agent/shared-repo-memory/`.
- `build-catchup.py` writes `.codex/local/catchup.md` and `.codex/local/sync_state.json` with `last_seen_head`, last ADR/summary hashes, and a rebuild timestamp.
- These files are explicitly never committed; `.codex/local/` is local continuity state only.
- The `git config core.hooksPath .githooks` directive (set by `bootstrap-repo.py`) wires these hooks into every git operation in the repo.

## Evidence

- Design doc "Local Catch-up → Automatic triggers": "A normal `git pull`, branch switch, or rebase automatically rebuilds the local digest."
- Design doc "How Memory Updates on `git pull`": "The intended experience: `git pull` is sufficient. New shared memory arrives like any file change, and the local digest rebuilds automatically through hooks."
- Design doc file layout tree shows `.githooks/post-checkout`, `post-merge`, `post-rewrite` as first-class hook files.

## Next

- Verify that `post-rewrite` covers both `rebase` and `amend` correctly (git fires it for both).
- Evaluate whether a `post-fetch` hook is needed for scenarios where the tree is not checked out but memory is fetched.
