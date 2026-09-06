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
```

Then say what it means for the developer, not what was wired. Three short parts, nothing more:

1. The outcome, in a sentence: their agent now keeps decisions across sessions, and once they push, their teammates' agents read the same decisions.
2. The one thing they must do: run `/memory-commit`, which commits the opt-in for them. Offer to run it now.

3. One closing line: nothing else about how they work changes, and `/agentmemory status` shows what memory holds.

Add a fourth line only when the repository has commit history but no ADRs: offer `/memory-bootstrap` to seed it from what is already there.

Do not list the hooks, the config keys, the `.gitignore` block, or the file layout. A developer who wants them will ask, and they are in the README. Do not commit for them.

### `status`

```bash
python3 "$HOME/.agent/shared-repo-memory/memory-status.py"
```

Relay its report as is: opted in or not, wiring gaps, ADR and note counts, must-read ADRs, and what a new session is given in words and tokens. Add `--context` to see the injected block itself.

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
