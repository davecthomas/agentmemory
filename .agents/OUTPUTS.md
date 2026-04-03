---
document: outputs
project: agentmemory
type: [shell]
agent: output-discoverer
---

# Downstream Outputs & Effects

This document maps all downstream systems, events, and effects that this repository produces.

---

## Project Summary

| Field | Value |
|---|---|
| **Name** | `agentmemory` |
| **Type** | Shell / Python |
| **Description** | Shared repo memory system for agentic development — installs helper scripts, wires agent hooks, and distributes memory skills to developer machines |
| **Outputs** | Helper scripts written to `~/.agent/shared-repo-memory/`; skill files written to `~/.agent/skills/` and symlinked into agent-specific directories on developer machines |

---

## Events Published

| Event | Consumers | Infrastructure |
|---|---|---|
| None | - | - |

> This repository has no runtime service component and publishes no events.

---

## Data Outputs

| Destination | Type | Format | Consumers |
|---|---|---|---|
| `~/.agent/shared-repo-memory/` | Local filesystem | Python scripts | Agent hooks (Claude Code, Gemini CLI, Codex) |
| `~/.agent/skills/<skill-name>/` | Local filesystem | Markdown (`SKILL.md`) | AI coding agents on developer machines |
| `~/.claude/skills/<skill-name>` | Local symlink | Symlink → `~/.agent/skills/` | Claude Code |
| `~/.codex/skills/<skill-name>` | Local symlink | Symlink → `~/.agent/skills/` | Codex CLI |
| `~/.gemini/skills/<skill-name>` | Local symlink | Symlink → `~/.agent/skills/` | Gemini CLI |
| `<repo>/.agents/memory/` | Repo filesystem | Markdown | All agents, collaborators via Git |

**Memory skills distributed:**

| Skill | Purpose |
|---|---|
| `memory-writer` | Writes one event shard and rebuilds the daily summary after a meaningful agent turn |
| `memory-bootstrap` | Seeds initial decision candidates and ADRs from existing repo history |
| `adr-promoter` | Promotes decision-candidate shards into permanent ADRs |
| `news` | Summarizes recent repo memory and ADRs |
