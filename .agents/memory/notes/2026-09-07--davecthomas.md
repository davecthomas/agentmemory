# Decision notes 2026-09-07

## 2026-09-07T17:46Z · davecthomas · feat/cursor-skills

**Decision:** install the skills for Cursor as well as Claude Code
**Why:** Cursor reads the same SKILL.md format from its own skills directory, so one canonical copy under ~/.agent/skills serves both and the skills need no change. The installer now links into every agent directory that already exists on the machine, and never creates one for an agent that is absent, which would leave dead configuration behind. Uninstall cleans every directory it linked into. A symlink that points nowhere is an earlier install whose target moved, so it is replaced rather than treated as a conflict needing --force. This machine had eight such links; the agentmemory ones are now live. This covers the write path: Cursor's agent can invoke memory-note, memory-query, adr-promoter and the rest. The read path, injecting memory at the start of a Cursor session, is separate work: Cursor has no SessionStart hook.
**Commit:** c596e7c
**Source:** commit-capture

