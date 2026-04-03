---
id: "ADR-0002"
title: "Shared agent assets use one install, many symlinks"
status: "accepted"
date: "2026-04-02"
tags: "install,architecture"
must_read: true
supersedes: ""
superseded_by: ""
---

# ADR-0002: Shared agent assets use one install, many symlinks

## Status
accepted

## Context
Skills, helper scripts, and reusable automation logic need to be available to multiple agent runtimes without maintaining duplicate copies per repo or per agent tool. If each agent tool installed its own copy of these assets, updates would require re-installing in N places and drift between copies would be inevitable.

## Decision
The canonical installed copy of all shared agent assets lives under `~/.agent/shared-repo-memory/`. Agent-specific paths such as `~/.codex/skills/<skill>` are symlinks to that installed copy. The agentmemory repo is the authoring source of truth. `install.sh` (delegating to `scripts/shared-repo-memory/install.py`) is the single supported operator entrypoint for installing assets and wiring hooks.

This model applies to:
- Python helper scripts (`session-start.py`, `post-turn-notify.py`, `rebuild-summary.py`, etc.)
- Skills (`memory-writer`, `adr-promoter`)

It does not apply to repo memory content, which lives in `<repo>/.agents/memory/` and is owned by the repo, not the user's home directory.

## Consequences
- `install.sh` must be rerunnable and idempotent.
- Skills and scripts update by re-running `install.sh` from the agentmemory repo checkout.
- Agent-specific config files (`~/.claude/settings.json`, `~/.codex/config.toml`, `~/.gemini/settings.json`) point at the shared install path, not per-repo copies.
- Session-start validation checks `~/.agent/shared-repo-memory/` for required scripts, not repo-local copies.
