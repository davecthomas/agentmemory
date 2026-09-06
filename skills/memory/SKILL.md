---
name: memory
description: Answers "what do we know about X?" from repo decision memory by searching ADRs, decision notes, design docs, and the git history of a path, and returns a bounded Markdown digest.
license: MIT
---

# Query Repo Memory

## Keywords

memory, what do we know about, why is this like this, why did we, has this been decided, decision about, look up memory, check the ADRs, prior decisions, what did we decide

## When to Use This Skill

- Before changing a subsystem, to see what was already decided about it
- When the developer asks why something is the way it is
- When session-start context said an item was omitted for budget and you need it

Run this before reading code to answer a "why" question. Memory is cheaper than re-deriving intent from a diff.

---

## Workflow

```bash
python3 "$HOME/.agent/shared-repo-memory/memory-query.py" <topic or path> [more terms]
```

- Pass a topic ("runtime detection"), a path (`scripts/shared-repo-memory/`), or both. A path that exists also yields its recent commits.
- Narrow with `--since YYYY-MM-DD`, `--until YYYY-MM-DD`, or `--author <name>` when the developer asks about a period or a person ("what did we decide about auth last quarter", "what has Priya been deciding").
- Read the ADRs section first; those are the durable decisions. Notes are recent and may not have been promoted yet.
- Quote the ADR id when you rely on one, so the developer can check it.
- If the answer is "Nothing in ADRs, notes, or docs mentions this yet", say so, then look at the code, and record what you learn with `memory-note` if it was non-obvious.
- Never edit memory files from this skill.
