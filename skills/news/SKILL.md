---
name: news
description: Summarizes the most recent repo news from shared repo memory and ADRs, and invokes memory-bootstrap when a repo is wired but has no substantive shared-memory history yet.
license: MIT
---

# Summarize Recent Repo News

## Keywords

news, what's new, what is new, what happened, what's been happening, anything special lately, what's hot, what did I miss, catch me up, recent repo news, recent memory, recent adr changes

## When to Use This Skill

- A developer asks what is new in the repo or what they missed
- A developer asks what has been happening lately, what is hot, or anything semantically similar
- A repository uses `.agents/memory/` as canonical shared memory and `.agents/memory/adr/` for durable decisions

---

## Workflow

- Read by recency, not by time window. Do not answer "nothing new" only because the repo has been quiet for days or months.
- If the repo has no shared-memory surface yet, distinguish between missing startup wiring and missing history:
  - if `.agents/memory/adr/INDEX.md` is missing entirely, report that `SessionStart` has not yet bootstrapped shared repo memory for this repo in the current session
  - tell the user to restart Codex in this repo if they want shared memory enabled immediately; otherwise explain that the next fresh Codex session should bootstrap repo wiring automatically
  - do not invoke `memory-bootstrap` from this skill when startup wiring is missing
- If the repo is already wired but has no substantive shared-memory history yet, invoke `memory-bootstrap` instead of stopping at "no news":
  - treat an empty shared-memory tree, or a tree with only the ADR index scaffold and no substantive artifacts yet, as a bootstrap-needed condition
  - before invoking bootstrap, tell the user: "No memory history found — running memory-bootstrap to seed it from existing commits and docs…"
  - after bootstrap completes, summarize the newly created summaries and ADRs as the repo's first news report
- Start with the newest shared-memory artifacts available:
  - newest daily summaries under `.agents/memory/daily/*/summary.md`
  - newest ADRs under `.agents/memory/adr/`
  - referenced event shards only when needed for supporting detail
- Default to a bounded recency set, such as the latest two daily summaries and the latest five ADRs. Expand only if the newest artifacts are too sparse to answer well.
- Prefer summaries and ADRs over raw event shards. Use shards to clarify evidence, blockers, or next steps, not as the first read surface.
- Use event shards to recover attribution for the most important recent items. Summaries and ADRs may tell you what changed, but the shard frontmatter tells you who did the work and which AI model participated.
- Separate short-horizon news from durable decisions:
  - recent work, blockers, and next steps come from the newest summaries
  - important governing changes come from the newest ADRs
- Attribute recent work as collaboration when the shard says `ai_generated: true`:
  - prefer `author and <ai_model>` in user-facing prose, for example `davidcthomas and gpt-5.4 established ...`
  - if `ai_generated: false`, attribute the work to the `author` only
  - if multiple authors or models appear in the same recency window, group or separate the items clearly instead of flattening them into one actor
  - if `ai_model` is missing but `ai_generated: true`, attribute to the `author` and say it was AI-assisted without inventing a model name
- When the repo has been quiet, still summarize the most recent known work and say when it was last recorded.
- Highlight what is actually noteworthy:
  - major work completed
  - newly surfaced or newly promoted decisions
  - active blockers
  - likely next steps
- Keep the answer concise and operator-friendly. The user asked for news, not a full memory dump.
- If shared memory still does not exist after bootstrap was attempted, say that clearly and do not invent activity.
