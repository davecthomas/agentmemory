---
name: memory-commit
description: Commits the repository's uncommitted decision memory as its own commit in the current pull request, with a message naming the decisions and ADRs it carries.
license: MIT
---

# Commit Decision Memory

## Keywords

memory commit, commit memory, commit the notes, commit decision memory, memory sweep, uncommitted memory, stage memory, memory before PR

## When to Use This Skill

- Before opening or updating a pull request, so the decisions ride with the code that prompted them
- The developer asks to commit notes, ADRs, or "the memory"
- `/agentmemory status` or `news` shows memory that has never been committed

- A repository was just opted in with `/agentmemory init` and the opt-in needs committing

Hooks and skills write memory but never commit it (ADR-0004). This is the explicit step, and the only one: no other skill here runs `git commit`.

---

## Workflow

1. Preview. From the repository root:

   ```bash
   python3 "$HOME/.agent/shared-repo-memory/memory-commit.py" --no-stage
   ```

   It prints the drafted message to stdout and the file list to stderr, changing nothing. When there is no uncommitted memory it says so and stops; report that and stop too.
2. Show the developer the message and the files.
3. Commit, once the developer agrees:

   ```bash
   python3 "$HOME/.agent/shared-repo-memory/memory-commit.py" --commit
   ```

   The script stages the memory paths and commits them with the drafted message. It commits nothing else and never pushes.

4. Report the write in one line, then say it belongs in the same pull request as the code it explains:

   ```
   **Recorded:** 2 decisions and 1 ADR committed -> <sha>
   ```

## Rules

- One commit, memory paths only. Never mix code into it, and never commit code from this skill.
- The opt-in edits `init` makes to `.gitignore` and `AGENTS.md` ride along, but only while their whole uncommitted diff sits inside the agentmemory block. When the script reports one as mixed with the developer's own edits, relay that and leave it to them.
- Never push. Pushing stays with the developer.
- Do not edit note or ADR content here. A wrong note gets fixed with `memory-note`, a wrong ADR with `adr-promoter`.
- The message names decisions and ADRs. Setup and configuration instructions belong in `AGENTS.md` and the README, not in a commit message repeated forever. The script adds a longer pointer to the repository's first memory commit only.
- Use only `memory-commit.py`. Another commit helper may be installed on the developer's machine, but agentmemory ships on its own and cannot depend on one being there.
