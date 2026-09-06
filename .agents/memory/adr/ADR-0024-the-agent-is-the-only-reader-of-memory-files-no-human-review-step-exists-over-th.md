---
id: "ADR-0024"
title: "The agent is the only reader of memory files; no human review step exists over them"
status: "accepted"
date: "2026-09-06"
tags: "scripts,skills"
must_read: true
supersedes: ""
superseded_by: ""
---

# ADR-0024: The agent is the only reader of memory files; no human review step exists over them

## Context

v0.5 shipped a review queue over hook-captured notes: a Candidate marker, an unreviewed count in status and news, and a memory-note --dismiss command. All of it assumed a person opens .agents/memory/notes/*.md and accepts or rejects entries. Nobody does; the file is read by the agent, injected at session start or fetched through the memory skill. The entries being queued were the developer's own commit messages.

## Decision

Nothing under .agents/memory/ is designed for a person to read or triage. A note written by a hook carries provenance (Source: commit-capture) and nothing else; there is no review state, no counter, and no command to clear one. Curation is the agent's job during a session: it promotes a durable decision to an ADR with adr-promoter and otherwise leaves notes as memory. Humans see memory through the agent, the PR diff, and the README.

## Alternatives

Keep the review queue but have the agent work it at session start: rejected because it still treats a human-authored commit message as suspect and adds a chore with no reader. Delete hook capture entirely: rejected because commit bodies are the highest-provenance why the repo has.

## Consequences

Any proposed status line, counter, or command must name who runs it; if the answer is a person against a memory file, it is dropped. memory-status and news report counts and content, never to-dos.

## Sources

- docs/v0.5-decision-memory-plan.md
- user correction, 2026-09-06: humans never read that file
