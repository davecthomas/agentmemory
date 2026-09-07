---
id: "ADR-2026-09-07-205a"
title: "Cursor is supported through its skills directory and a generated rule file"
status: "accepted"
date: "2026-09-07"
tags: "scripts,install"
scope: "scripts/shared-repo-memory/cursor-rules.py, scripts/shared-repo-memory/install.py"
must_read: true
supersedes: "ADR-0021"
superseded_by: ""
---

# ADR-2026-09-07-205a: Cursor is supported through its skills directory and a generated rule file

## Context

ADR-0021 narrowed v0.5 to Claude Code to prove the content model before spending on adapters. That has held up, and the eval measures it. Cursor turns out to need no adapter: it reads the same SKILL.md format from ~/.cursor/skills, so the write path works unchanged. Only the read path differs, because Cursor has no SessionStart hook to inject context.

## Decision

The installer links skills into every agent directory present on the machine, currently ~/.claude/skills and ~/.cursor/skills, and creates none for an agent that is absent. For the read path, cursor-rules.py renders the same bounded memory block into .cursor/rules/agentmemory.mdc with alwaysApply set, and the generated git hooks refresh it after commit, merge, checkout and rewrite. The rule is derived and gitignored, like the catch-up digest: committing it would conflict on every branch that records a decision.

## Alternatives

An MCP server exposing query and note as tools: still worth doing for clients with no rules mechanism, but it needs a running process and a per-client registration, where a rule file needs neither. A committed rule file: rejected, it conflicts constantly and is stale for anyone who has not pulled. Waiting for Cursor to add a session hook: rejected, the rules mechanism already exists and does the job.

## Consequences

The Cursor rule reflects memory as of the last git operation rather than the last second, which is close enough because memory only changes on a commit or a pull. A Cursor user who never runs a git command in the repo sees a stale rule until they do. The .mdc frontmatter shape is Cursor's, so a change to that format is a change here; the body stays readable Markdown either way.

## Sources

- #60
- scripts/shared-repo-memory/cursor-rules.py
