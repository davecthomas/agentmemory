---
id: "ADR-0025"
title: "agentmemory skills depend only on agentmemory's own scripts"
status: "accepted"
date: "2026-09-06"
tags: "skills"
must_read: true
supersedes: ""
superseded_by: ""
---

# ADR-0025: agentmemory skills depend only on agentmemory's own scripts

## Context

The memory-commit skill first told the agent to hand its drafted message to a commit skill when the developer had one, and to fall back to memory-commit.py otherwise. That commit skill ships from a different repository. agentmemory installs on its own, so the branch would take a path that does not exist on most machines, and on the machines where it does exist the two paths behave differently. The same trap sits behind any PR-prep, branch-naming, or review skill a developer happens to have installed.

## Decision

A skill in this repository may invoke only the scripts under ~/.agent/shared-repo-memory/ and the other skills this repository ships. It may not name, detect, or branch on a skill or tool from another repository, and it may not degrade to a different behaviour depending on what else is installed. Where another tool would be convenient, agentmemory provides the capability itself: memory-commit.py performs its own commit rather than delegating.

## Alternatives

Detect the other skill and use it when present: rejected because it makes behaviour depend on an unrelated repository's install state, and the untested path is the common one. Declare a hard dependency and document it as a prerequisite: rejected because agentmemory is meant to install and work on its own.

## Consequences

agentmemory sometimes reimplements a small piece of something a developer already has, such as committing with a drafted message. That duplication is the price of installing standalone. A new skill that reaches for an outside tool is a review failure.

## Sources

- PR #47 review: the memory-commit skill branched on an external commit skill
- skills/memory-commit/SKILL.md
