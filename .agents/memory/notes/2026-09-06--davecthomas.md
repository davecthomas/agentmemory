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

## 2026-09-06T13:41Z · davecthomas · fix/self-contained-skills

**Decision:** agentmemory skills call only this repo's scripts; no branching on tools from other repos.
**Why:** memory-commit told the agent to use an external commit skill when present, so behaviour depended on another repository being installed and the common path went untested.
**Alternatives:** Detect and delegate when the other tool exists.
**Scope:** skills/

## 2026-09-06T14:29Z · davecthomas · feat/green-memory-writes

**Decision:** Colour memory writes green on a terminal
**Why:** a developer watching a commit scroll past should see that something was remembered; captured output stays plain so logs are not polluted
**Scope:** scripts/

## 2026-09-06T14:30Z · davecthomas · feat/green-memory-writes

**Decision:** print memory writes in green on a terminal
**Why:** A developer watching a commit scroll past had no visual cue that anything was remembered. Lines that record a write now print green, and only when stderr is a terminal, so output an agent captures and output in CI stay plain. NO_COLOR turns it off and AGENTMEMORY_COLOR=always forces it on. memory-note and promote-adr gained a stderr line as well, since they only printed a path to stdout, which the developer rarely sees. In chat the same convention is markdown rather than colour, so the skills report a bold Recorded line.
**Commit:** 28c3e54
**Source:** commit-capture

