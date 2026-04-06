---
name: adr-inspector
description: Inspects changed design docs for ADR-worthy decisions and promotes them through the existing ADR pipeline.
license: MIT
---

# Inspect Design Docs for ADR Candidates

## Keywords

adr, inspect, design doc, architecture decision, decision candidate, promote adr, design review

## When to Use This Skill

- A repository uses `.agents/memory/adr/` for durable architecture decision records
- Design documents were changed during an agent turn (files matching `docs/*`, `*design*`, `*spec*`, `*arch*`)
- You need to identify new architectural decisions and promote them to ADRs

This skill is typically invoked automatically by the post-turn hook when it detects design doc changes, but can also be invoked manually.

---

## Task Format

When invoked automatically, the task message contains:

```
Inspect these changed design docs for ADR-worthy decisions:
  <path1>
  <path2>
Repo root: <absolute path>
```

## Workflow

### 1. Read the changed design docs

Read each design doc path listed in the task message. Understand the full context of what decisions are being described.

### 2. Read existing ADRs to avoid duplicates

Read `.agents/memory/adr/INDEX.md` and scan existing ADR files to understand what decisions are already captured. Do not create duplicate ADRs for decisions that already exist, even if the wording differs.

### 3. Identify ADR-worthy decisions

Look for decisions that are **durable and architecturally significant**:

**Favor:**
- Architecture boundaries and layer separation
- Canonical data sources and ownership
- API contracts and interface decisions
- Tool and dependency choices with rationale
- Output conventions and format standards
- Accepted tradeoffs with explicit reasoning
- Invariants and constraints that the system must maintain

**Reject:**
- Tasks and rollout sequencing (not decisions)
- Local optimizations without systemic impact
- Implementation trivia (variable names, formatting)
- Decisions that are already captured in existing ADRs

### 4. For each new decision, create a decision-candidate shard

Write a shard under `.agents/memory/daily/<today>/events/` with:
- `decision_candidate: true` in frontmatter
- Rich semantic content in all four sections (Why, Repo changes, Evidence, Next)
- `files_touched` pointing to the design doc(s) that contain the decision

Shard filename format: `<timestamp>--<author>--adr-inspector.md`

Use the installed helper to determine the author:
```bash
git config user.name | tr ' ' '-' | tr '[:upper:]' '[:lower:]'
```

### 5. Promote each candidate to an ADR

For each shard created in step 4, call the promotion helper:

```bash
$HOME/.agent/shared-repo-memory/promote-adr.py <shard-path> --repo-root <repo-root> --title "<short imperative title>"
```

The title should be a short imperative sentence summarizing the decision (e.g., "Use adapter pattern to decouple runtime-specific behavior from core memory engine").

### 6. Stage the results

```bash
git add .agents/memory/adr/ .agents/memory/daily/
```

Do not commit. The developer commits explicitly.

## Quality Constraints

- **One ADR per distinct decision.** Do not split a single decision into multiple ADRs, and do not merge unrelated decisions into one.
- **Titles must be imperative and specific.** Not "Updated design doc" but "Decouple agent adapters from shared memory core."
- **The Why section must explain motivation**, not restate the decision. Why was this choice made? What problem does it solve? What alternatives were considered?
- **Evidence must cite sources.** Reference specific file paths, section headings, or design doc content that supports the decision.
- **Do not create an ADR if you are unsure it is architecturally significant.** It is better to miss a marginal decision than to pollute the ADR index with noise.
