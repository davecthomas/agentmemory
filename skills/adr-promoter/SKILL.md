---
name: adr-promoter
description: Promotes a decision-candidate shared repo-memory event shard into an ADR and refreshes the ADR index.
license: MIT
---

# Promote A Decision Candidate To An ADR

## Keywords

adr, promote adr, decision candidate, architecture decision record, shared repo memory, durable decision, adr index

## When to Use This Skill

- A repository uses `.agents/memory/adr/` for durable decisions
- A shared repo-memory event shard has `decision_candidate: true`
- You need to create one ADR and refresh `.agents/memory/adr/INDEX.md`

---

## Workflow

- Treat missing folders inside `.agents/memory/` as normal repo-owned state. Create `.agents/memory/adr/` or other required subdirectories automatically without asking the user for confirmation.
- Confirm the candidate shard exists under `.agents/memory/daily/YYYY-MM-DD/events/`.
- Read the shard and use its `Why`, `What changed`, `Evidence`, and `Next` sections as the ADR source.
- Create exactly one new ADR under `.agents/memory/adr/`.
- Refresh `.agents/memory/adr/INDEX.md` in identifier order.
- Keep the promotion explicit. Do not auto-commit or auto-push the ADR changes.
- In this POC repo, prefer the installed helper:

```bash
./scripts/shared-repo-memory/promote-adr.sh .agents/memory/daily/YYYY-MM-DD/events/<shard>.md
```
