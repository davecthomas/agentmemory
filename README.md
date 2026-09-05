# agentmemory

Decision memory for coding agents, kept as plain Markdown in the repository.

A fresh Claude Code session in an opted-in repo starts with the repo's architecture decisions in context, records new decisions as it makes them, and can ask "what do we know about X?" without re-deriving intent from code. Teammates see the same decisions in the PR that introduced them.

Current version: `0.5.0`. The v0.5 rebuild and the audit behind it are in [docs/v0.5-decision-memory-plan.md](docs/v0.5-decision-memory-plan.md).

## How it works

```
Session starts        →  SessionStart hook injects: ADR index, must-read ADR
                         decisions, recent notes, catch-up. Bounded to a word budget.

Agent makes a          →  memory-note skill appends 3 lines to
non-obvious choice        .agents/memory/notes/YYYY-MM-DD.md (staged, not committed)

Developer commits      →  post-commit hook appends a candidate note when the commit
                         touches docs/** or carries a "Decision:" line. The note is
                         staged and rides in the next commit (or `git commit --amend`).

Note proves durable    →  adr-promoter skill writes ADR-NNNN-<slug>.md, rebuilds INDEX.md

Teammate pulls         →  post-merge hook writes local/catchup.md from git log

Anyone asks "why?"     →  memory skill searches ADRs, notes, docs, git log -- <path>
```

No hook spawns an LLM. Nothing is committed or pushed automatically. Everything under `.agents/memory/` except `local/` is meant to be committed with the code it describes.

## Install

Requires Python 3.13+, Git, and Claude Code.

```bash
git clone git@github.com:davecthomas/agentmemory.git
cd agentmemory
./install.sh            # --dry-run to preview, --force to replace non-symlink skill dirs
```

The installer copies the scripts to `~/.agent/shared-repo-memory/`, the skills to `~/.agent/skills/` with symlinks from `~/.claude/skills/`, and adds `SessionStart` and `PostCompact` hooks to `~/.claude/settings.json`. Restart open Claude Code sessions afterwards.

Installing turns nothing on. Every hook exits silently in a repo that has not opted in.

## Opt a repository in

In a Claude Code session inside the repo:

```
/agentmemory init
```

or say "turn on agentmemory for this repo". This runs `bootstrap-repo.py --init`, which writes `.agents/memory/config.json` (the opt-in marker), creates `adr/`, `notes/`, and `local/`, adds a managed block to `.gitignore`, generates the git hooks under `.githooks/`, and sets `core.hooksPath`. Commit `config.json` and the whole team is opted in; teammates without agentmemory installed see only Markdown.

`/agentmemory status` reports wiring and counts. `/agentmemory off` reverses the repo wiring and leaves the memory files in place.

If the repo has history but no ADRs, `/memory-bootstrap` mines the design docs and commit messages for the three to seven decisions that still govern the code and promotes them.

## Layout

```
<repo>/.agents/memory/
├── config.json          # opt-in marker + settings
├── adr/
│   ├── INDEX.md         # rebuilt by promote-adr.py
│   └── ADR-NNNN-<slug>.md
├── notes/
│   └── YYYY-MM-DD.md    # append-only decision notes
└── local/               # gitignored: catchup.md, state.json
```

`config.json` defaults:

```json
{
  "decision_surfaces": ["docs/**"],
  "context_budget_words": 2500,
  "notes_window_days": 14
}
```

## Skills

| Skill | Use |
|---|---|
| `agentmemory` | `init`, `status`, `off` for the current repo |
| `memory` | "What do we know about X?" |
| `memory-note` | Record a decision at the moment it is made |
| `adr-promoter` | Turn a note (or stated decision) into an ADR |
| `memory-bootstrap` | Seed ADRs from existing docs and commits |
| `news` | What changed in memory recently |

## Scripts

All in `scripts/shared-repo-memory/`, installed to `~/.agent/shared-repo-memory/`:

| Script | Role |
|---|---|
| `session-start.py` | Hook. Repairs wiring, injects context. `--print-context` prints the block. |
| `post-compact.py` | Hook. Re-injects context after compaction. |
| `bootstrap-repo.py` | `--init` opts a repo in; otherwise repairs wiring. |
| `catchup.py` | Git hook. Writes `local/catchup.md` from memory changes since last seen. |
| `check-memory.py` | Git hook (pre-commit). Structural checks on `.agents/memory/`. |
| `memory-note.py` | Append a note. |
| `commit-capture.py` | Git hook. Candidate note from a decision-bearing commit. |
| `promote-adr.py` | Write an ADR, rebuild the index. `--from-note`, `--reindex`. |
| `memory-query.py` | Search ADRs, notes, docs, path history. |
| `install.py` / `uninstall.py` | Machine scope; `uninstall.py --repo` for repo scope. |

Together they are about 2,100 lines of Python with no dependencies beyond the standard library.

## Evals

Memory has to earn its context budget.

- `scripts/shared-repo-memory/check-memory.py` runs in the pre-commit hook and rejects a commit whose ADR index, links, frontmatter, note format, or budget is broken.
- `evals/run_eval.py` asks `claude -p`, with tools disabled, the questions in `evals/questions.json` with and without the session-start context, scores `must_mention` coverage, writes `evals/results/<timestamp>.json`, and fails when memory does not beat the baseline.

```bash
python3 evals/run_eval.py                 # all questions, both conditions
python3 evals/run_eval.py --limit 3       # quick check
python3 evals/run_eval.py --dry-run       # prompt sizes only
```

## Uninstall

```bash
./uninstall.sh                # machine: hooks, skills, scripts
./uninstall.sh --repo         # this repo: hooks, hooksPath, .gitignore block, local/
./uninstall.sh --repo --purge-memory   # also stage git rm --cached .agents/memory
./uninstall.sh --dry-run
```

Uninstall removes only what it can identify as its own; edited hooks and user-added settings survive.

## Development

```bash
poetry install
poetry run pytest scripts/shared-repo-memory/test -q
poetry run black . && poetry run ruff check scripts/ evals/
```

`scripts/shared-repo-memory/project-pre-commit.sh` runs black, ruff, the tests, and `check_memory.py` on every commit through the generated pre-commit hook.
