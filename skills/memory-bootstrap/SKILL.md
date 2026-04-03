---
name: memory-bootstrap
description: Seeds a bounded set of shared repo-memory decision candidates from recent design docs and recent commit history, then promotes the strongest initial decisions into ADRs.
license: MIT
---

# Bootstrap Foundational Repo Memory

## Keywords

memory bootstrap, bootstrap repo memory, seed repo memory, seed adr candidates, bootstrap durable decisions, bootstrap foundational decisions, design doc to decision candidates, recent commits to memory, shared repo memory bootstrap

## When to Use This Skill

- A repository already has shared repo-memory wiring, but its history layer is still thin or empty
- A developer asks to bootstrap foundational decisions, seed ADR candidates, or mine recent design docs and commits for durable decisions
- A developer recently added or named a design doc and wants the durable decisions in that doc distilled into shared memory
- You need a small reviewable set of decision-candidate shards before normal post-turn capture has accumulated enough history
- The repository uses `.agents/memory/` as canonical shared memory

---

## Workflow

- Keep user interaction minimal during bootstrap. This skill is for seeding history, not for negotiating repo setup.
- Assume `SessionStart` already handled repo-local shared-memory wiring. If `.agents/memory/adr/INDEX.md` is still missing, or `.codex/memory` is not wired to `../.agents/memory`, stop and report that repo startup wiring failed instead of trying to create the repo layout from this skill.
- Treat cross-repo bootstrap as an anti-pattern. Do not attempt to seed memory for some other repository from the current workspace.
- If the user names one design doc, prioritize that doc and keep the output tightly scoped to it.
- If the user recently added a design doc but did not name it, prioritize design-like docs changed in the recent commit window before looking at broader history.
- Work from a bounded source set. Default to the last 24 commits on the current branch and any design-like docs changed in that window. Also include any design docs the user names explicitly.
- Prefer design docs as the rationale source. Use commits, diffs, and changed paths as corroborating evidence and discovery signals, not as the sole basis for foundational decisions.
- Select only durable decisions. Favor boundaries, ownership models, contracts, canonical sources of truth, migration rules, invariants, and accepted architecture tradeoffs.
- Reject tasks, rollout sequencing, local optimizations, and implementation trivia.
- Cluster related statements into one decision family instead of creating one shard per paragraph, heading, or commit.
- Deduplicate against existing ADRs under `.agents/memory/adr/` and recent decision-candidate shards under `.agents/memory/daily/`.
- Emit a small batch by default: target three to five decision-candidate shards and stop at seven unless the user explicitly asks for more.
- Write ordinary event shards under `.agents/memory/daily/YYYY-MM-DD/events/` using the existing shared repo-memory shard contract and set `decision_candidate: true` only on the selected bootstrap outputs.
- **Use the source event date, not today's date**, for the shard directory path, filename timestamp, and frontmatter `timestamp` field. Determine the source date from the commit date, design doc last-modified date, or the earliest commit in the cluster that the decision is derived from. Using today's date is wrong — it places historical decisions in the wrong daily directory and makes them appear as current activity.
- Add a `bootstrapped_at` frontmatter field set to the current UTC timestamp (when the bootstrap ran). This distinguishes bootstrap shards from live-turn shards and preserves auditability.
- After writing all shards, rebuild the daily summary for every distinct source date that received a shard by running `rebuild-summary.py --repo-root <repo-root> --date <YYYY-MM-DD>` for each affected date. Do not skip this step — without it the summary for that date will be missing.
- In `Evidence`, cite the design doc path and section headings, plus supporting commit hashes or changed paths when they materially reinforce the decision.
- During initial bootstrap, immediately promote the strongest selected candidates into ADRs so the repo does not start with an empty durable-memory layer.
- Keep the promotion explicit by using `adr-promoter` as part of the operator-invoked bootstrap workflow; do not silently promote unrelated historical candidates outside that bounded bootstrap set.
- Promote bootstrap candidates sequentially so ADR identifiers and index ordering remain stable.
- If the source material does not justify at least one durable decision, report that clearly instead of forcing output.
