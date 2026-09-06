---
name: adr-promoter
description: Promotes a decision note, or an explicitly stated decision, into an Architecture Decision Record under .agents/memory/adr/ and rebuilds the index.
license: MIT
---

# Promote A Decision To An ADR

## Keywords

adr, promote adr, promote note, architecture decision record, make this an ADR, durable decision, adr index

## When to Use This Skill

- A decision note in `.agents/memory/notes/` describes a choice that governs the codebase going forward
- The developer states a decision and asks for it to be recorded durably
- A note the commit hook captured (`Source: commit-capture`) describes a decision that governs the code going forward

Promotion is always explicit. Do not promote as a side effect of other work.

---

## Workflow

From a note (preferred, keeps provenance):

```bash
python3 "$HOME/.agent/shared-repo-memory/promote-adr.py" \
    --from-note .agents/memory/notes/YYYY-MM-DD.md --entry <N> \
    [--title "<better title>"] [--consequences "<what follows>"] [--tags "<a,b>"]
```

From explicit text:

```bash
python3 "$HOME/.agent/shared-repo-memory/promote-adr.py" \
    --title "<title>" --context "<why the decision was needed>" \
    --decision "<what was decided>" [--alternatives "<rejected options>"] \
    [--consequences "<what follows>"] [--source "<doc, commit, or note>"] \
    [--no-must-read]
```

- Entries are numbered from 1 in file order. Read the note file first to pick the right one.
- Write Consequences yourself when the note lacks them; an ADR without consequences is a wish.
- When the decision replaces an earlier ADR, pass `--supersedes ADR-NNNN`; the old ADR is marked superseded, leaves the session context, and the index shows the link both ways.
- `must_read` defaults to true, which injects the Decision section at every session start. Use `--no-must-read` for decisions that matter only when touching one area; the `memory` skill still finds them.
- The script writes the ADR, rebuilds `INDEX.md`, and stages both. Do not commit.
- To rebuild the index alone: `promote-adr.py --reindex`.

## Report the write

Memory that gets written silently teaches a developer nothing about what the system captures. End with exactly one line naming what was written and where, in this form:

```
**Recorded:** <what> -> <path>
```

One line, no ceremony, even when the developer did not ask to be told. When nothing was written, say that instead.

An ADR is the most durable thing this system writes, so say which one and whether it is must-read:

```
**Recorded:** ADR-0025 (must-read) agentmemory skills depend only on agentmemory's own scripts -> .agents/memory/adr/ADR-0025-...md
```

When the promotion superseded an earlier ADR, name it in the same line.
