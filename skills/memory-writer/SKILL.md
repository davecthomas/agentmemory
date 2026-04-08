---
name: memory-writer
description: Routes a meaningful manual post-turn invocation through post-turn-notify.py so the turn becomes a pending shared-memory capture and, if trustworthy, a later published checkpoint.
license: MIT
---

# Write A Shared Repo-Memory Event

## Keywords

memory writer, shared repo memory, event shard, daily summary, notify hook, codex notify, meaningful turn, stage memory files

## When to Use This Skill

- A repository uses `.agents/memory/` as canonical shared repo memory
- A Codex `notify` callback or equivalent post-turn flow needs to write one event shard
- You need to rebuild `.agents/memory/daily/YYYY-MM-DD/summary.md` from shard inputs

---

## Workflow

- Treat missing directories anywhere under `.agents/memory/` as normal first-write state. Create `.agents/memory/pending/YYYY-MM-DD/`, `.agents/memory/logs/`, or other required subdirectories automatically without asking the user for confirmation.
- Do **not** write directly into `.agents/memory/daily/YYYY-MM-DD/events/`.
- Route the turn through `post-turn-notify.py`, which writes one privacy-safe pending capture, builds a local workstream bundle, and lets the background checkpoint flow decide whether durable publication is justified.
- Fail clearly if required metadata such as `ai_model` cannot be resolved accurately.
- In this POC repo, the installed helper entrypoint is:

```bash
$HOME/.agent/shared-repo-memory/post-turn-notify.py --repo-root <repo-root>
```
