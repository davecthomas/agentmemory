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

1. Run the miner and read its ranked list; it scans `docs/**/*.md`, `README.md`, `AGENTS.md`, `CLAUDE.md` for decision-bearing sections and the last 300 commits for bodies that explain a why:

   ```bash
   python3 "$HOME/.agent/shared-repo-memory/memory-bootstrap.py" [--limit 15]
   ```

   Open the source of any candidate you are unsure about before promoting it.
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
5. Report it the way the developer cares about, in three short parts:

   1. The outcome, in a sentence: their agent now starts every session knowing these decisions, and so does every teammate's agent once the ADRs are pushed.
   2. The decisions themselves, one line each, titles only.
   3. One closing line: they are Markdown under `.agents/memory/adr/`, so review and edit them like code, then run `/memory-commit` to commit them.

   Do not explain the mining, the scoring, or the sources unless asked. If you rejected a strong candidate, say so in one line.
6. Do not write notes from history; notes are for decisions made now. Do not commit; `/memory-commit` is the commit path.

## Report the write

Memory that gets written silently teaches a developer nothing about what the system captures. End with exactly one line naming what was written and where, in this form:

```
Recorded: <what> -> <path>
```

One line, no ceremony, even when the developer did not ask to be told. When nothing was written, say that instead.

Report the whole set in one line:

```
Recorded: 4 ADRs seeded from docs and history -> .agents/memory/adr/
```
