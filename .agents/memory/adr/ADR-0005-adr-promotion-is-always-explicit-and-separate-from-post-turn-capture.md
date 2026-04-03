---
id: "ADR-0005"
title: "ADR promotion is always explicit and separate from post-turn capture"
status: "accepted"
date: "2026-04-02"
tags: "adr,curation,workflow"
must_read: false
supersedes: ""
superseded_by: ""
---

# ADR-0005: ADR promotion is always explicit and separate from post-turn capture

## Status
accepted

## Context
Post-turn hooks must run quickly and non-interactively. They cannot pause to ask a human whether a given shard constitutes a durable architectural decision. If promotion happened automatically, ADRs would accumulate noise and lose their value as a stable, curated decision record.

At the same time, durable decisions that emerge during agent work should have a clear path to the ADR layer without requiring manual document creation from scratch.

## Decision
A post-turn shard may have `decision_candidate: true` in its frontmatter when the content contains decision-bearing language (policy, contract, standard, ADR, governing, etc.). This flag marks the shard as a candidate but does not trigger ADR creation. ADR files are created only through the explicit `adr-promoter` workflow, which reads one candidate shard, writes one ADR under `.agents/memory/adr/`, and updates `INDEX.md`. This step requires a deliberate operator or agent action.

## Consequences
- ADRs represent genuinely curated decisions, not automatically promoted noise.
- Operators can review decision-candidate shards in the daily summary and choose which ones to promote.
- The `decision_candidate` flag in shard frontmatter is the handoff signal between post-turn capture and the ADR promotion workflow.
- The ADR layer stays small, stable, and high-signal.
