---
id: "ADR-0001"
title: ".agents/memory/ is the canonical agent-neutral shared memory location"
status: "accepted"
date: "2026-04-02"
tags: "storage,architecture"
must_read: true
supersedes: ""
superseded_by: ""
---

# ADR-0001: .agents/memory/ is the canonical agent-neutral shared memory location

## Status
accepted

## Context
Multiple agent runtimes (Codex, Gemini, Claude Code) each have their own config and tooling namespaces (`.codex/`, `.gemini/`, `.claude/`). Without a clear rule, each agent would store repo memory under its own namespace, creating duplicated or fragmented state that no single agent — or human reviewer — could treat as authoritative.

The system needs one place that is owned by the repo (not by any one agent), committed to Git, and reviewable in pull requests like any other source artifact.

## Decision
The canonical location for shared repo memory is `<repo>/.agents/memory/`. All memory writes target this path. Agent-facing paths such as `<repo>/.codex/memory` are symlinks to `../.agents/memory` and exist only as access paths — they are never the canonical storage location and must never receive direct writes.

The `.agents/` namespace is intentionally agent-neutral. No single tool owns it.

## Consequences
- Memory files are repo-owned and Git-reviewable alongside the code they describe.
- Any agent that can read files can read shared repo memory; no agent-specific adapter is required for reads.
- Bootstrap and wiring scripts must create the symlink correctly and must not treat the symlink target as a second storage location.
- Tooling that checks for `.codex/memory` must treat a missing symlink as a wiring error, not a missing memory store.
