---
id: "ADR-0004"
title: "Shared memory requires explicit commit and push to become collaborative"
status: "accepted"
date: "2026-04-02"
tags: "collaboration,workflow,git"
must_read: true
supersedes: ""
superseded_by: ""
---

# ADR-0004: Shared memory requires explicit commit and push to become collaborative

## Status
accepted

## Context
Auto-committing memory files as a side effect of each agent turn would bypass normal code review, pollute commit history with low-signal entries, and create commits not associated with any meaningful code change. It would also make it impossible to review memory and code together in a pull request.

The system needs a clear collaboration boundary: the point at which one agent's memory becomes visible and useful to other collaborators.

## Decision
Post-turn hooks stage generated memory files (shards and summary) but do not commit or push. Commit and push are explicit steps performed by a human or by an agent using the existing commit workflow. Memory becomes collaborative shared state only after those steps push the committed memory files to the remote on the same branch and in the same pull request as the code they describe.

The system does not create separate memory-only publication paths. Memory moves with code.

## Consequences
- Memory files can be reviewed alongside code changes in pull requests.
- Auto-staging by the post-turn hook is the only automatic git operation; everything after that is explicit.
- A collaborator's agent session will not see another developer's in-progress memory until that memory is committed, pushed, and pulled.
- Local catch-up (`.codex/local/catchup.md`) reflects only what has been pushed and pulled; it is never pre-populated with staged-but-uncommitted memory from another workstation.
