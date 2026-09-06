# Decision notes 2026-09-06

## 2026-09-06T00:26Z · davecthomas · feat/agents-md-block

**Decision:** document the convention in AGENTS.md for agents without agentmemory
**Why:** A teammate who clones an opted-in repo without installing agentmemory saw nothing about notes or ADRs; the convention lived only in hooks they did not have. bootstrap --init now adds a managed "Decision memory" block to AGENTS.md or CLAUDE.md when one exists, telling any agent where decisions live and how to record one by hand, and uninstall --repo strips it. A repo with neither file gets a log hint rather than a new top-level file.
**Commit:** 7437411
**Candidate:** true

