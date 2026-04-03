---
id: "ADR-0003"
title: "Event shards are the canonical write unit; daily summaries are derived read models"
status: "accepted"
date: "2026-04-02"
tags: "write-model,events,summaries"
must_read: true
supersedes: ""
superseded_by: ""
---

# ADR-0003: Event shards are the canonical write unit; daily summaries are derived read models

## Status
accepted

## Context
If all collaborators write to a single shared file (a traditional append-only log or daily journal), merge conflicts are guaranteed. Any file that two agents or two humans edit in the same day will conflict. The system needs a write model that is safe for parallel contributors.

At the same time, agents need a cheap read path. Reading every individual shard for context at session start is too expensive.

## Decision
The canonical write unit is an immutable event shard stored under `.agents/memory/daily/YYYY-MM-DD/events/<timestamp>--<author>--thread_<id>--turn_<id>.md`. One shard per meaningful turn. Shards are never edited after creation.

Daily summaries (`.agents/memory/daily/YYYY-MM-DD/summary.md`) are derived read models rebuilt deterministically from the shard set for that day. They are never the canonical write target. Rebuilding a summary twice from unchanged shard inputs must produce byte-identical output.

## Consequences
- Multiple collaborators can write memory in parallel without merge conflicts (each turn gets a unique filename).
- Post-turn tooling writes shards, then triggers summary rebuild; it never writes summaries directly.
- Summary content is only as good as the approved shard set; bad shard selection is not compensated for in the summary layer.
- Agents read summaries for cheap context; they read individual shards only when they need detail.
- Shard filenames encode enough metadata (timestamp, author, thread, turn) to be self-describing without reading the file.
