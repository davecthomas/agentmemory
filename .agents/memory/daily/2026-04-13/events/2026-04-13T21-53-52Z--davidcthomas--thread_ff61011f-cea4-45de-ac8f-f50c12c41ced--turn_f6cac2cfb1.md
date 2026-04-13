---
timestamp: "2026-04-13T21:53:52Z"
author: "davidcthomas"
branch: "codex/6-runtime-log-identity-cleanup"
thread_id: "ff61011f-cea4-45de-ac8f-f50c12c41ced"
turn_id: "f6cac2cfb1"
workstream_id: "thread-ff61011f-cea4-45de-ac8f-f50c12c41ced"
workstream_scope: "thread"
episode_id: "episode-thread-ff61011f-cea4-45de-ac8f-f50c12c41ced"
episode_scope: "thread"
checkpoint_goal: "Normalize the runtime log identity schema across shared-repo-memory helper scripts, replacing legacy agent/provider field names with a consistent runtime-based naming convention."
checkpoint_surface: "The runtime logging context layer in common.py and the git hook generation template in bootstrap-repo.py, which together control how all helper scripts identify their execution runtime in log output."
checkpoint_outcome: "Renamed _LOG_CONTEXT_AGENT_ID/_LOG_CONTEXT_PROVIDER_VERSION to _LOG_CONTEXT_RUNTIME_ID/_LOG_CONTEXT_RUNTIME_VERSION, added _SCRIPT_RUNTIME_DEFAULTS map for non-agent entrypoints, updated hook templates to export AGENTMEMORY_RUNTIME_ID/AGENTMEMORY_RUNTIME_VERSION env vars, and bumped the system version to v0.4.3."
decision_candidate: false
enriched: true
ai_generated: true
ai_model: "claude-unknown"
ai_tool: "claude"
ai_surface: "claude-code"
ai_executor: "local-agent"
related_adrs:
files_touched:
  - "docs/shared-repo-memory-system-design.md"
  - "scripts/shared-repo-memory/bootstrap-repo.py"
  - "scripts/shared-repo-memory/common.py"
  - "scripts/shared-repo-memory/run-catchup.sh"
design_docs_touched:
  - "docs/shared-repo-memory-system-design.md"
verification:
  - "git diff:  4 files changed, 3 insertions(+), 31 deletions(-); `.githooks/post-checkout`, `post-merge`, and `post-rewrite` each call `build-catchup.py` from the central install at `$HOME/.agent/shared-repo-memory/`. A normal `git pull`, branch switch, or rebase automatically rebuilds the local digest. `.githooks/pre-commit` separately protects the publication boundary by rejecting raw shared-memory artifacts.; if ! python3 \"$HOME/.agent/shared-repo-memory/build-catchup.py\" --repo-root \"$repo_root\" --trigger {str_hook_name}; then; SHARED_REPO_MEMORY_SYSTEM_VERSION: str = \"0.4.4\""
  - "design doc touched: docs/shared-repo-memory-system-design.md"
source_pending_shards:
  - ".agents/memory/pending/2026-04-13/2026-04-13T21-53-52Z--davidcthomas--thread_ff61011f-cea4-45de-ac8f-f50c12c41ced--turn_f6cac2cfb1.md"
---

## Why

- The old agent/provider naming was ambiguous — it conflated the concept of an AI agent runtime (claude, gemini) with non-agent callers like git hooks, bootstrap scripts, and the installer. Consistently using runtime-id eliminates that ambiguity so log lines always identify the exact execution path that produced them, whether that is an agent turn, a git hook invocation, or a CLI script run. This makes post-mortem log analysis and hook-trace review reliable.

## What changed

- common.py renamed module-level log context globals to runtime-id/runtime-version terminology and added _SCRIPT_RUNTIME_DEFAULTS, a dict that maps each helper script filename to its canonical runtime-id string so non-agent callers (bootstrap-repo, installer, build-catchup) no longer fall through to the ambiguous 'unknown' default. The hook generation template in bootstrap-repo.py was updated to export AGENTMEMORY_RUNTIME_ID and AGENTMEMORY_RUNTIME_VERSION before invoking hook scripts, so the runtime context is available to all child processes without requiring each one to probe the environment independently. run-catchup.sh gained a guarded export of AGENTMEMORY_RUNTIME_ID defaulting to git-hook. docs/shared-repo-memory-system-design.md was brought into alignment with the new env var names. System version bumped to 0.4.3 to signal the schema change to consuming scripts.

## Evidence

- docs/shared-repo-memory-system-design.md was explicitly updated as part of this change, grounding the new AGENTMEMORY_RUNTIME_ID and AGENTMEMORY_RUNTIME_VERSION env var names as canonical in the system design. The version bump to 0.4.3 recorded in common.py SHARED_REPO_MEMORY_SYSTEM_VERSION is a deliberate schema-change signal, consistent with prior version increments that mark behavioral changes. The HEAD commit on branch codex/6-runtime-log-identity-cleanup carries the message 'v0.4.3 normalizes agentmemory runtime logging', confirming the intent was a named, releasable normalization rather than incidental cleanup.

## Next

- Repos bootstrapped before this change will still have hook files using the old SHARED_REPO_MEMORY_AGENT_ID / SHARED_REPO_MEMORY_PROVIDER_VERSION env vars; re-running bootstrap-repo.py on each wired repo will regenerate their hooks with the new AGENTMEMORY_ names. Verify that other helper script callers of set_runtime_log_context (build-catchup.py, session-start.py, post-turn-notify.py) pass runtime-id values consistent with the new _SCRIPT_RUNTIME_DEFAULTS map.
