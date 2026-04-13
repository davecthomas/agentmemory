# ADR index

| ADR | Title | Status | Date | Tags | Must Read | Supersedes | Superseded By |
|---|---|---|---|---|---|---|---|
| ADR-0001 | [is the canonical agent-neutral shared memory location"](ADR-0001-agents-memory-is-the-canonical-agent-neutral-shared-memory-location.md) | "accepted" | "2026-04-02" | poc | true | "" |  |
| ADR-0002 | [agent assets use one install, many symlinks"](ADR-0002-shared-agent-assets-use-one-install-many-symlinks.md) | "accepted" | "2026-04-02" | poc | true | "" |  |
| ADR-0003 | [shards are the canonical write unit; daily summaries are derived read models"](ADR-0003-event-shards-are-the-canonical-write-unit-summaries-are-derived.md) | "accepted" | "2026-04-02" | poc | true | "" |  |
| ADR-0004 | [memory requires explicit commit and push to become collaborative"](ADR-0004-shared-memory-requires-explicit-commit-and-push-to-become-collaborative.md) | "accepted" | "2026-04-02" | poc | true | "" |  |
| ADR-0005 | [promotion is always explicit and separate from post-turn capture"](ADR-0005-adr-promotion-is-always-explicit-and-separate-from-post-turn-capture.md) | "accepted" | "2026-04-02" | poc | true | "" |  |
| ADR-0006 | [Code and Gemini CLI are the primary agent runtimes; Codex is deprioritized due to weak hook support"](ADR-0006-claude-and-gemini-are-primary-runtimes-codex-deprioritized.md) | "accepted" | "2026-04-02" | poc | true | "" |  |
| ADR-0007 | [Separate raw turn captures from durable checkpoints using a two-phase publication pipeline](ADR-0007-separate-raw-turn-captures-from-durable-checkpoints-using-a-two-phase-publication-pipeline.md) | accepted | 2026-04-13 | docs | true |  |  |
| ADR-0008 | [Bootstrap shared memory using an isolated subagent to avoid in-session context contamination](ADR-0008-bootstrap-shared-memory-using-an-isolated-subagent-to-avoid-in-session-context-contamination.md) | accepted | 2026-04-13 | docs | true |  |  |
| ADR-0011 | [Use a deterministic local episode graph to cluster pending captures for checkpoint evaluation](ADR-0011-use-a-deterministic-local-episode-graph-to-cluster-pending-captures-for-checkpoint-evaluation.md) | accepted | 2026-04-13 | docs | true |  |  |
| ADR-0012 | [Re-inject bounded memory context after PostCompact to preserve session memory invariant](ADR-0012-re-inject-bounded-memory-context-after-postcompact-to-preserve-session-memory-invariant.md) | accepted | 2026-04-13 | docs | true |  |  |
| ADR-0013 | [Re-inject bounded memory context via PostCompact hook to survive context window compaction](ADR-0013-re-inject-bounded-memory-context-via-postcompact-hook-to-survive-context-window-compaction.md) | accepted | 2026-04-13 | docs | true |  |  |
| ADR-0014 | [Establish a bounded priority-ordered default agent read path that excludes raw shard history](ADR-0014-establish-a-bounded-priority-ordered-default-agent-read-path-that-excludes-raw-shard-history.md) | accepted | 2026-04-13 | docs | true |  |  |
| ADR-0015 | [Write-protect decision_candidate at raw capture time; only trusted publication paths may set it true](ADR-0015-write-protect-decision-candidate-at-raw-capture-time-only-trusted-publication-paths-may-set-it-true.md) | accepted | 2026-04-13 | docs | true |  |  |
| ADR-0016 | [Wire SubagentStop to post-turn-notify.py to capture work from Task-tool subagents](ADR-0016-wire-subagentstop-to-post-turn-notify-py-to-capture-work-from-task-tool-subagents.md) | accepted | 2026-04-13 | docs | true |  |  |
| ADR-0017 | [Define a bounded prioritized read set as the canonical agent context budget at session start](ADR-0017-define-a-bounded-prioritized-read-set-as-the-canonical-agent-context-budget-at-session-start.md) | accepted | 2026-04-13 | docs | true |  |  |
| ADR-0018 | [Use git post-checkout, post-merge, and post-rewrite hooks to rebuild local catch-up after git operations](ADR-0018-use-git-post-checkout-post-merge-and-post-rewrite-hooks-to-rebuild-local-catch-up-after-git-operations.md) | accepted | 2026-04-13 | docs | true |  |  |
