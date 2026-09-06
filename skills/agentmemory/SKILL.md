---
name: agentmemory
description: Turns agentmemory on or off for the current repository, or reports its status. A repo opts in by committing .agents/memory/config.json; nothing happens in a repo that has not opted in.
license: MIT
---

# Manage agentmemory For This Repo

## Keywords

agentmemory init, agentmemory status, agentmemory off, turn on agentmemory, enable agentmemory, enable memory for this repo, opt in to agentmemory, set up decision memory, disable agentmemory, turn off agentmemory

## When to Use This Skill

- The developer says "turn on agentmemory for this repo", "/agentmemory init", or similar
- The developer asks whether agentmemory is active here, or what it has recorded ("/agentmemory status")
- The developer wants it off for this repo ("/agentmemory off")

Installing agentmemory on a machine never enables it for a repo. This skill is the opt-in.

---

## Subcommands

All scripts live in `$HOME/.agent/shared-repo-memory/`. Run them from the repo root.

### `init` (default when the request is "turn on")

```bash
python3 "$HOME/.agent/shared-repo-memory/bootstrap-repo.py" --init
git add .agents/memory/config.json .agents/memory/adr/INDEX.md
```

Then tell the developer, in a few lines:

- `.agents/memory/config.json` was written and staged; committing it opts the whole team in
- what got wired locally: `.githooks/` (pre-commit, post-commit, post-checkout, post-merge, post-rewrite), `core.hooksPath`, the managed `.gitignore` block
- a managed "Decision memory" block was added to `AGENTS.md` or `CLAUDE.md` when one exists, so agents without agentmemory still learn the convention; commit it too
- the default `decision_surfaces` is `["docs/**"]`; edit `config.json` to change it
- if the repo has history but no ADRs yet, offer `/memory-bootstrap`

Do not commit. The developer commits `config.json` with their next change.

### `status`

```bash
python3 "$HOME/.agent/shared-repo-memory/memory-status.py"
```

Relay its report as is: opted in or not, wiring gaps, ADR and note counts, must-read ADRs, unreviewed candidate notes, and what a new session is given in words and tokens. Add `--context` to see the injected block itself.

### `off`

```bash
python3 "$HOME/.agent/shared-repo-memory/uninstall.py" --repo
git rm --cached .agents/memory/config.json
```

Report what was removed. ADRs and notes stay on disk and in git; say so. Offer `--purge-memory` only if the developer asks to drop the memory from the repo entirely.

---

## Rules

- Never run `init` in a repo the developer did not name. The current working directory is the target.
- Never commit or push.
- If `$HOME/.agent/shared-repo-memory/bootstrap-repo.py` is missing, agentmemory is not installed on this machine; point at `./install.sh` in the agentmemory checkout and stop.
