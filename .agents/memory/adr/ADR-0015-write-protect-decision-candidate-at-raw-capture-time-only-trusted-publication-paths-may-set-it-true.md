# ADR-0015 Write-protect decision_candidate at raw capture time; only trusted publication paths may set it true

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

Purpose: Write-protect decision_candidate at raw capture time; only trusted publication paths may set it true
Derived from: [2026-04-13T21-57-07Z--dave-thomas--adr-inspector](../daily/2026-04-13/events/2026-04-13T21-57-07Z--dave-thomas--adr-inspector.md)

## Context

If an agent turn could set `decision_candidate: true` directly at raw capture time, premature or unvetted decisions would flow straight into the ADR pipeline without passing through the trust validation that episode-cluster evaluation provides. A single turn has incomplete context; it cannot reliably judge whether an action represents a durable architectural decision or an exploratory change that will be reversed.
The trust boundary is explicit: `decision_candidate` starts as `false` on every pending capture and can only be flipped to `true` during one of two controlled paths — trusted checkpoint publication (where the `memory-checkpointer` has evaluated the full episode cluster) or explicit ADR inspection (a human-or-skill-initiated action). Neither path can be triggered by the capturing agent unilaterally.

## Decision

- `decision_candidate` is always written as `false` by `post-turn-notify.py` on every new pending capture.
- The field may only transition to `true` during `publish-checkpoint.py` execution (after trust validation passes) or during explicit ADR inspector skill invocation.
- The `.githooks/pre-commit` hook enforces this boundary by rejecting any daily event shard still marked `enriched: false` (the enrichment step is part of the trusted publication path).
- The design doc codifies this as an invariant: "may be flipped to true only during trusted checkpoint publication or explicit ADR inspection."

## Consequences

- Audit `post-turn-notify.py` to confirm `decision_candidate` is always hardcoded to `false` with no override path at capture time.
- Confirm `publish-checkpoint.py` is the only non-skill path that may set `decision_candidate: true`.
- Consider adding a pre-commit check that rejects daily event shards where `decision_candidate: true` lacks a corresponding source shard reference, to detect bypass attempts.

## Source memory events

- [2026-04-13T21-57-07Z--dave-thomas--adr-inspector](../daily/2026-04-13/events/2026-04-13T21-57-07Z--dave-thomas--adr-inspector.md)

## Related code paths

- docs/shared-repo-memory-system-design.md
