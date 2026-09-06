---
name: memory-note
description: Records one decision note (decision, why, alternatives, scope) in .agents/memory/notes/YYYY-MM-DD.md at the moment a non-obvious choice is made, so the next session starts from it. No LLM spawn; the note is staged with the code.
license: MIT
---

# Record A Decision Note

## Keywords

memory note, record decision, note this decision, remember that we chose, write down why, capture rationale, decision note

## When to Use This Skill

Write a note when you, or the developer, make a choice that a future reader could not recover from the diff alone:

- a design trade-off (chose A over B, and why)
- a rejected alternative
- a constraint discovered while working (an API limit, a tool quirk, a hidden dependency)
- a deliberate deviation from a convention

Do not write a note for routine edits, formatting, or anything the commit message already states plainly. One good note per real decision; zero is the common case.

---

## Workflow

```bash
python3 "$HOME/.agent/shared-repo-memory/memory-note.py" \
    --decision "<one sentence: what was decided>" \
    --why "<one to three sentences: the reason>" \
    [--alternatives "<what was rejected and why>"] \
    [--scope <path>] [--scope <path>]
```

- Decision is one sentence in the active voice. Why states the constraint or trade-off, not a restatement of the decision.
- Scope lists the paths the decision governs, when it is not repo-wide.
- The script appends to today's note file and stages it. Do not commit.
- A note that turns out to be architectural gets promoted later with `adr-promoter`; do not promote from here.

## Report the write

Memory that gets written silently teaches a developer nothing about what the system captures. End with exactly one line naming what was written and where, in this form:

```
**Recorded:** <what> -> <path>
```

One line, no ceremony, even when the developer did not ask to be told. When nothing was written, say that instead.

Example: `**Recorded:** decision on retry backoff -> .agents/memory/notes/2026-09-06--dave.md`
