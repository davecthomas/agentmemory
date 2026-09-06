# Decision notes 2026-09-06

## 2026-09-06T00:26Z · davecthomas · feat/agents-md-block

**Decision:** document the convention in AGENTS.md for agents without agentmemory
**Why:** A teammate who clones an opted-in repo without installing agentmemory saw nothing about notes or ADRs; the convention lived only in hooks they did not have. bootstrap --init now adds a managed "Decision memory" block to AGENTS.md or CLAUDE.md when one exists, telling any agent where decisions live and how to record one by hand, and uninstall --repo strips it. A repo with neither file gets a log hint rather than a new top-level file.
**Commit:** 7437411
**Source:** commit-capture

## 2026-09-06T12:31Z · davecthomas · docs/readme-walkthrough

**Decision:** make the opt-in a five-step walkthrough
**Why:** The opt-in section said "in a Claude Code session inside the repository" and left three things to guess: that you leave the agentmemory checkout and cd to your own repo, that the session must be a new one because the hooks were installed after the old one started, and which files to commit. A scratch-repo run confirms init changes .agents/, .gitignore, and AGENTS.md, none of which the README listed. The section is now numbered steps with the shell commands, the commit, a restart, and /agentmemory status as the check that it worked.
**Commit:** dae1428
**Source:** commit-capture

