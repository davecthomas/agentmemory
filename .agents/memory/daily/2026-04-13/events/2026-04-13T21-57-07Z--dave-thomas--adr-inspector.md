---
timestamp: "2026-04-13T21:57:07Z"
author: "dave-thomas"
branch: "main"
thread_id: "adr-inspector"
turn_id: "adr-inspector-decision-candidate-gate"
decision_candidate: true
enriched: true
ai_generated: true
ai_model: "claude-sonnet-4-6"
ai_tool: "claude"
ai_surface: "claude-code"
ai_executor: "adr-inspector"
workstream_id: "adr-inspector"
workstream_scope: "branch"
checkpoint_goal: "Identify and promote ADR-worthy architectural decisions from the system design doc."
checkpoint_surface: "docs/shared-repo-memory-system-design.md"
checkpoint_outcome: "Decision candidate: decision_candidate is write-protected at raw capture; only trusted publication paths may flip it true."
files_touched:
  - "docs/shared-repo-memory-system-design.md"
design_docs_touched:
  - "docs/shared-repo-memory-system-design.md"
verification:
  - "docs/shared-repo-memory-system-design.md §What is captured: 'decision_candidate: false on the pending capture; may be flipped to true only during trusted checkpoint publication or explicit ADR inspection.'"
  - "docs/shared-repo-memory-system-design.md §After capture: 'publish-checkpoint.py validates gestalt, privacy, and anti-mechanical rules before writing the final shard.'"
  - "ADR-0005: 'ADR promotion is always explicit and separate from post-turn capture.'"
---

## Why

If an agent turn could set `decision_candidate: true` directly at raw capture time, premature or unvetted decisions would flow straight into the ADR pipeline without passing through the trust validation that episode-cluster evaluation provides. A single turn has incomplete context; it cannot reliably judge whether an action represents a durable architectural decision or an exploratory change that will be reversed.

The trust boundary is explicit: `decision_candidate` starts as `false` on every pending capture and can only be flipped to `true` during one of two controlled paths — trusted checkpoint publication (where the `memory-checkpointer` has evaluated the full episode cluster) or explicit ADR inspection (a human-or-skill-initiated action). Neither path can be triggered by the capturing agent unilaterally.

## What changed

- `decision_candidate` is always written as `false` by `post-turn-notify.py` on every new pending capture.
- The field may only transition to `true` during `publish-checkpoint.py` execution (after trust validation passes) or during explicit ADR inspector skill invocation.
- The `.githooks/pre-commit` hook enforces this boundary by rejecting any daily event shard still marked `enriched: false` (the enrichment step is part of the trusted publication path).
- The design doc codifies this as an invariant: "may be flipped to true only during trusted checkpoint publication or explicit ADR inspection."

## Evidence

- `docs/shared-repo-memory-system-design.md` §What is captured: "`decision_candidate`: `false` on the pending capture; may be flipped to `true` only during trusted checkpoint publication or explicit ADR inspection."
- `docs/shared-repo-memory-system-design.md` §After capture: "publish-checkpoint.py validates gestalt, privacy, and anti-mechanical rules before writing the final shard."
- ADR-0005: "ADR promotion is always explicit and separate from post-turn capture" — this ADR complements that by locking the upstream flag that gates promotion eligibility.

## Next

- Audit `post-turn-notify.py` to confirm `decision_candidate` is always hardcoded to `false` with no override path at capture time.
- Confirm `publish-checkpoint.py` is the only non-skill path that may set `decision_candidate: true`.
- Consider adding a pre-commit check that rejects daily event shards where `decision_candidate: true` lacks a corresponding source shard reference, to detect bypass attempts.
