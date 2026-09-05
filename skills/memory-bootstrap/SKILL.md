---
name: memory-bootstrap
description: Seeds decision memory for a repo with existing history by mining design docs and commit messages for the decisions that govern the codebase, then promoting a bounded set of them into ADRs.
license: MIT
---

# Bootstrap Decision Memory From Existing History

## Keywords

memory bootstrap, seed memory, bootstrap adrs, initial adrs, mine history for decisions, no memory yet

## When to Use This Skill

- A repo has opted in (`.agents/memory/config.json` exists) but `.agents/memory/adr/` has no ADRs
- The developer asks to seed memory from what already exists

Run once per repo. Re-running is safe but should only add decisions that are missing.

---

## Workflow

1. Gather sources, bounded:
   - `docs/**/*.md`, `README.md`, `AGENTS.md`, `CLAUDE.md`: read headings and any section named Decision, Principles, Architecture, or Design
   - `git log --format='%h %ad %s%n%b' --date=short -n 200`: keep commits whose body explains a *why* (contains "because", "so that", "instead of", "rather than", or a `Decision:` line)
2. Select three to seven decisions that still govern the code. A decision qualifies when reversing it would change how contributors work today. Skip anything superseded, cosmetic, or purely historical.
3. For each, promote with explicit text so the ADR carries context and alternatives:

```bash
python3 "$HOME/.agent/shared-repo-memory/promote-adr.py" \
    --title "<decision as a sentence>" \
    --context "<the problem it solved, from the source>" \
    --decision "<what was decided>" \
    --alternatives "<rejected options, or 'None recorded in sources'>" \
    --consequences "<what contributors must do differently>" \
    --source "<docs/path.md § heading>" [--source "<commit sha>"] \
    --tags "<top-level dirs it governs>"
```

   Use the source's date for context in the Context text; the ADR date is the promotion date.
4. Promote sequentially so ids stay ordered. Mark `--no-must-read` for decisions that matter only within one area.
5. Report the ADRs created with one line each, and name any decision you found but did not promote and why.
6. Do not write notes from history; notes are for decisions made now. Do not commit.
