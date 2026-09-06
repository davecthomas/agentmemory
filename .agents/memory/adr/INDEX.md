# ADR index

| ADR | Title | Status | Date | Must read |
|---|---|---|---|---|
| ADR-0001 | [.agents/memory/ is the canonical agent-neutral shared memory location](ADR-0001-agents-memory-is-the-canonical-agent-neutral-shared-memory-location.md) | accepted | 2026-04-02 | yes |
| ADR-0002 | [Shared agent assets use one install, many symlinks](ADR-0002-shared-agent-assets-use-one-install-many-symlinks.md) | accepted | 2026-04-02 | yes |
| ADR-0003 | [Event shards are the canonical write unit; daily summaries are derived read models](ADR-0003-event-shards-are-the-canonical-write-unit-summaries-are-derived.md) | superseded (by ADR-0019) | 2026-04-02 | no |
| ADR-0004 | [Shared memory requires explicit commit and push to become collaborative](ADR-0004-shared-memory-requires-explicit-commit-and-push-to-become-collaborative.md) | accepted | 2026-04-02 | yes |
| ADR-0005 | [ADR promotion is always explicit and separate from post-turn capture](ADR-0005-adr-promotion-is-always-explicit-and-separate-from-post-turn-capture.md) | accepted | 2026-04-02 | yes |
| ADR-0006 | [Claude Code and Gemini CLI are the primary agent runtimes; Codex is deprioritized due to weak hook support](ADR-0006-claude-and-gemini-are-primary-runtimes-codex-deprioritized.md) | superseded (by ADR-0021) | 2026-04-02 | no |
| ADR-0007 | [Separate raw turn captures from durable checkpoints using a two-phase publication pipeline](ADR-0007-separate-raw-turn-captures-from-durable-checkpoints-using-a-two-phase-publication-pipeline.md) | superseded (by ADR-0019) | 2026-04-13 | no |
| ADR-0008 | [Bootstrap shared memory using an isolated subagent to avoid in-session context contamination](ADR-0008-bootstrap-shared-memory-using-an-isolated-subagent-to-avoid-in-session-context-contamination.md) | superseded (by ADR-0019) | 2026-04-13 | no |
| ADR-0011 | [Use a deterministic local episode graph to cluster pending captures for checkpoint evaluation](ADR-0011-use-a-deterministic-local-episode-graph-to-cluster-pending-captures-for-checkpoint-evaluation.md) | superseded (by ADR-0019) | 2026-04-13 | no |
| ADR-0012 | [Re-inject bounded memory context after PostCompact to preserve session memory invariant](ADR-0012-re-inject-bounded-memory-context-after-postcompact-to-preserve-session-memory-invariant.md) | accepted | 2026-04-13 | yes |
| ADR-0015 | [Write-protect decision_candidate at raw capture time; only trusted publication paths may set it true](ADR-0015-write-protect-decision-candidate-at-raw-capture-time-only-trusted-publication-paths-may-set-it-true.md) | superseded (by ADR-0019) | 2026-04-13 | no |
| ADR-0016 | [Wire SubagentStop to post-turn-notify.py to capture work from Task-tool subagents](ADR-0016-wire-subagentstop-to-post-turn-notify-py-to-capture-work-from-task-tool-subagents.md) | superseded (by ADR-0019) | 2026-04-13 | no |
| ADR-0017 | [Define a bounded prioritized read set as the canonical agent context budget at session start](ADR-0017-define-a-bounded-prioritized-read-set-as-the-canonical-agent-context-budget-at-session-start.md) | superseded (by ADR-0022) | 2026-04-13 | no |
| ADR-0018 | [Use git post-checkout, post-merge, and post-rewrite hooks to rebuild local catch-up after git operations](ADR-0018-use-git-post-checkout-post-merge-and-post-rewrite-hooks-to-rebuild-local-catch-up-after-git-operations.md) | accepted | 2026-04-13 | yes |
| ADR-0019 | [Capture decisions as notes and at commit time, never per turn](ADR-0019-capture-decisions-as-notes-and-at-commit-time-never-per-turn.md) | accepted | 2026-09-05 | yes |
| ADR-0020 | [A repository opts in by committing .agents/memory/config.json](ADR-0020-a-repository-opts-in-by-committing-agents-memory-config-json.md) | accepted | 2026-09-05 | yes |
| ADR-0021 | [Claude Code is the only supported runtime in v0.5](ADR-0021-claude-code-is-the-only-supported-runtime-in-v0-5.md) | accepted | 2026-09-05 | yes |
| ADR-0022 | [Session context is one budgeted block: index, must-read decisions, recent notes, catch-up](ADR-0022-session-context-is-one-budgeted-block.md) | accepted | 2026-09-05 | yes |
| ADR-0023 | [Black is pinned to an exact version](ADR-0023-black-is-pinned-to-an-exact-version.md) | accepted | 2026-09-05 | no |
| ADR-0024 | [The agent is the only reader of memory files; no human review step exists over them](ADR-0024-the-agent-is-the-only-reader-of-memory-files-no-human-review-step-exists-over-th.md) | accepted | 2026-09-06 | yes |
| ADR-0025 | [agentmemory skills depend only on agentmemory's own scripts](ADR-0025-agentmemory-skills-depend-only-on-agentmemory-s-own-scripts.md) | accepted | 2026-09-06 | yes |
