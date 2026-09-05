---
id: "ADR-0020"
title: "A repository opts in by committing .agents/memory/config.json"
status: "accepted"
date: "2026-09-05"
tags: "scripts,skills"
must_read: true
supersedes: ""
superseded_by: ""
---

# ADR-0020: A repository opts in by committing .agents/memory/config.json

## Context

In v0.4, installing agentmemory on a machine wired hooks that activated in every git repository the developer opened, bootstrapping wiring into repos that never asked for it.

## Decision

`.agents/memory/config.json` is the opt-in marker and the settings file (`decision_surfaces`, `context_budget_words`, `notes_window_days`). `bootstrap-repo.py --init`, wrapped by the `agentmemory` skill ("turn on agentmemory for this repo", `/agentmemory init`), writes it. Without the file, `session-start.py` and `post-compact.py` exit silently and `bootstrap-repo.py` refuses to wire the repo.

## Alternatives

A per-machine allowlist of repo paths: rejected because it does not travel with the repo, so teammates opt in one by one. An environment variable: rejected for the same reason.

## Consequences

Committing the file opts the whole team in together. A teammate without agentmemory installed sees only Markdown. `check_memory.py` skips repos that have not opted in.

## Sources

- docs/v0.5-decision-memory-plan.md § Opt-in
- PR #15
