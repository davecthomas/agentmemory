---
id: "ADR-0019"
title: "Capture decisions as notes and at commit time, never per turn"
status: "accepted"
date: "2026-09-05"
tags: "scripts,skills"
must_read: true
supersedes: "ADR-0003, ADR-0007, ADR-0008, ADR-0011, ADR-0015, ADR-0016"
superseded_by: ""
---

# ADR-0019: Capture decisions as notes and at commit time, never per turn

## Context

The v0.4 pipeline captured every file-changing turn as a pending shard (files touched plus a diff stat), clustered shards with a local episode graph, and spawned a background `claude -p` session to decide whether to publish. An audit on 2026-09-05 found 129 captures, hundreds of background evaluations, and 2 surviving checkpoints. The intent behind a change was in the conversation and was discarded at capture time, so the evaluator had to reconstruct it from the diff.

## Decision

A decision enters memory in one of two ways. The agent or a human appends a note (`memory-note.py`: Decision, Why, Alternatives, Scope) to `.agents/memory/notes/YYYY-MM-DD.md` at the moment a non-obvious choice is made. Or the `post-commit` hook (`commit-capture.py`) appends a candidate note when a commit touches a `decision_surfaces` path or carries a `Decision:` line, copying the commit body verbatim as the why. No hook spawns an LLM. Per-turn capture, pending shards, the episode graph, daily event shards, and derived daily summaries are removed.

## Alternatives

Keep per-turn capture but include the transcript so the evaluator has the why: rejected because it moves the privacy problem to capture time and still costs a session per turn. Capture only at commit time: rejected because a commit message rarely records rejected alternatives; notes do.

## Consequences

Memory grows only when someone records a decision, so an agent session must be told to write notes (session-start does this). Candidate notes from the commit hook are unreviewed until promoted. Nothing local-only is generated, so the pre-commit shard guard is gone.

## Sources

- docs/v0.5-decision-memory-plan.md
- PR #15
